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
    TMDB_V4_BASE_URL, TMDB_IMAGE_BASE, IMAGE_RESOLUTION,
    TMDB_V4_TOKEN_FILE, TMDB_V4_READ_TOKEN
)
from resources.lib.utils import get_json, get_language, log, paginate_list, read_json, write_json, get_genres_string, set_resume_point
from resources.lib.cache import cache_object, MainCache, get_fast_cache, set_fast_cache
from resources.lib import menus
from resources.lib import trakt_sync
from resources.lib.config import PAGE_LIMIT
from concurrent.futures import ThreadPoolExecutor, as_completed

LANG = get_language()
VIDEO_LANGS = "en,null,xx,ro,hi,ta,te,ml,kn,bn,pa,gu,mr,ur,or,as,es,fr,de,it,ru,ja,ko,zh"

SEARCH_HISTORY_FILE = os.path.join(ADDON.getAddonInfo('profile'), 'search_history.json')
ADDON_PATH = ADDON.getAddonInfo('path')
TRAKT_ICON = os.path.join(ADDON_PATH, 'resources', 'media', 'trakt.png')
TMDB_ICON = os.path.join(ADDON_PATH, 'resources', 'media', 'tmdb.png')
TMDbmovies_ICON = os.path.join(ADDON_PATH, 'icon.png')
NEXT_PAGE_ICON = os.path.join(ADDON_PATH, 'resources', 'media', 'item_next.png')


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
            tag.setPlot(info.get('plot', ''))
            
            # --- FIX BUG AN (None) ---
            if info.get('year'):
                try:
                    # Convertim în string apoi verificăm dacă e cifră
                    year_str = str(info['year'])
                    if year_str.isdigit():
                        tag.setYear(int(year_str))
                except:
                    pass # Dacă e "None" sau gol, pur și simplu nu setăm anul
            # -------------------------

            if info.get('rating'): tag.setRating(float(info['rating']))
            if info.get('votes'): tag.setVotes(int(info['votes']))
            if info.get('duration'): tag.setDuration(int(info['duration']))
            if info.get('premiered'): tag.setPremiered(info['premiered'])
            if info.get('studio'):
                st_val = info['studio']
                # Verificăm dacă e deja o listă, dacă nu, o punem noi într-una
                if isinstance(st_val, list):
                    tag.setStudios(st_val)
                else:
                    tag.setStudios([str(st_val)])
            if info.get('genre'):
                if isinstance(info['genre'], list):
                    tag.setGenres(info['genre'])
                elif isinstance(info['genre'], str):
                    tag.setGenres(info['genre'].split(', '))
            if info.get('mpaa'): tag.setMpaa(str(info['mpaa']))
            
            # APLICĂM BIFA DOAR DACĂ NU E FOLDER (Butonul Next nu are bifă)
            if not item['is_folder']:
                if info.get('playcount') == 1: 
                    tag.setPlaycount(1)
                else:
                    tag.setPlaycount(0)
                
                # Întotdeauna verificăm dacă există resume_time (chiar dacă e watched, poate utilizatorul l-a reînceput)
                if item.get('resume_time') and item.get('total_time'):
                    set_resume_point(li, item['resume_time'], item['total_time'])
                elif info.get('playcount') == 1:
                    tag.setResumePoint(0.0, 0.0)
            else:
                tag.setPlaycount(0)

            if item.get('cm'):
                li.addContextMenuItems(item['cm'])

        items_to_add.append((item['url'], li, item['is_folder']))
    
    xbmcplugin.addDirectoryItems(HANDLE, items_to_add, len(items_to_add))
    
    if items:
        xbmcplugin.setContent(HANDLE, items[0]['info'].get('mediatype', 'movies') + 's')
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=True)
    

# === THREADING PREFETCHER (OPTIMIZAT PENTRU STABILITATE UI) ===
def prefetch_metadata_parallel(items, media_type):
    """Încarcă metadatele în cache (SQL) folosind fire de execuție limitate."""
    if not items: return
    
    def fetch_task(item):
        # Verificăm dacă Kodi vrea să se închidă sau să schimbe fereastra
        if xbmc.Monitor().abortRequested(): return

        tid = str(item.get('id') or item.get('tmdb_id') or '')
        if tid and tid != 'None':
            m_type = item.get('media_type') or ('movie' if media_type == 'movie' else 'tv')
            # Această funcție scrie în cache-ul SQL
            get_tmdb_item_details(tid, m_type)

    # MODIFICARE: Reducem max_workers de la 15 la 5.
    # 15 thread-uri blochează UI-ul la navigare rapidă (Back/Forward).
    # 5 thread-uri sunt suficiente pentru a umple cache-ul rapid fără lag.
    with ThreadPoolExecutor(max_workers=5) as executor:
        # Folosim list() pentru a forța execuția, dar executorul gestionează pool-ul
        list(executor.map(fetch_task, items))

# =============================================================================
# FUNCȚIE PENTRU LOCALIZARE COMPLETĂ (PLOT, POSTER, FANART în RO, Nume în EN)
# =============================================================================
def get_localized_assets(media_type, original_plot='', original_poster='', original_backdrop='', full_details=None):
    try:
        from resources.lib.config import get_plot_language_code
        lang_code = get_plot_language_code()
        if lang_code == 'en':
            return original_plot, original_poster, original_backdrop
    except:
        return original_plot, original_poster, original_backdrop

    out_plot = original_plot
    out_poster = original_poster
    out_backdrop = original_backdrop

    if full_details:
        translations = full_details.get('translations', {}).get('translations', [])
        for t in translations:
            if t.get('iso_639_1') == lang_code:
                localized = t.get('data', {}).get('overview')
                if localized: out_plot = localized
                break
        
        images = full_details.get('images', {})
        
        posters = images.get('posters', []) or images.get('stills', [])
        for p in posters:
            if p.get('iso_639_1') == lang_code:
                out_poster = p.get('file_path')
                break
        
        backdrops = images.get('backdrops', [])
        for b in backdrops:
            if b.get('iso_639_1') == lang_code:
                out_backdrop = b.get('file_path')
                break

    return out_plot, out_poster, out_backdrop

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
        if 'mpaa' in info_data and info_data['mpaa']:
            tag.setMpaa(str(info_data['mpaa']))
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
            # Îi spunem lui Kodi explicit ca ID-ul 'imdb' să fie cel principal (default)
            # Asta va forța Kodi să populeze automat VideoPlayer.IMDBNumber!
            default_id = 'imdb' if 'imdb' in unique_ids else 'tmdb'
            tag.setUniqueIDs(unique_ids, default_id)
        if 'cast' in info_data:
            actors = []
            for a in info_data['cast']:
                if isinstance(a, dict):
                    # Convertim dicționarul în obiectul Actor cerut de Kodi
                    actors.append(xbmc.Actor(name=a.get('name', ''), role=a.get('role', ''), thumbnail=a.get('thumbnail', '')))
                else:
                    actors.append(a)
            tag.setCast(actors)

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

        # ✅ SETĂM PLAYCOUNT
        if is_fully_watched: 
            tag.setPlaycount(1)
        else: 
            tag.setPlaycount(0)
            
        # ✅ SETĂM CERCULEȚ PROGRES (indiferent dacă e vizionat sau nu, dacă utilizatorul a reînceput vizionarea)
        if 'resume_percent' in info_data and info_data['resume_percent'] > 0:
            percent = float(info_data['resume_percent'])
            
            if duration == 0:
                duration = 7200 if info_data.get('mediatype') == 'movie' else 2700
                try: tag.setDuration(duration)
                except: pass
            
            resume_time = int((percent / 100.0) * duration)
            
            try: 
                tag.setResumePoint(float(resume_time), float(duration))
            except: 
                pass
            
    except Exception as e:
        log(f"[METADATA] Error: {e}", xbmc.LOGERROR)

def add_directory(name, params, folder=True, icon=None, thumb=None, fanart=None, clearlogo=None, cm=None, info=None, uids=None, watched_info=None):
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
        'trakt_sync_smart', 'trakt_sync_smart_action', # <-- ADAUGAT AICI
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
        
    if clearlogo:
        art['clearlogo'] = clearlogo
        art['tvshow.clearlogo'] = clearlogo
        # --- FIX SEZOANE & AF3 ---
        art['tvshow.logo'] = clearlogo
        art['logo'] = clearlogo
        art['fanart_clearlogo'] = clearlogo
        
        try:
            li.setProperty('clearlogo', clearlogo)
            li.setProperty('tvshow.clearlogo', clearlogo)
            li.setProperty('logo', clearlogo)
        except: pass
        
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
    xbmcgui.Dialog().notification("[B][COLOR FFFDBD01]Search[/COLOR][/B]", "History cleared", TMDbmovies_ICON, 2000, False)
    xbmc.executebuiltin("Container.Refresh")

def delete_search_item(params):
    """Funcția apelată din meniul contextual pentru ștergere."""
    query = params.get('query')
    search_type = params.get('type')
    remove_search_from_history(query, search_type)
    xbmcgui.Dialog().notification("[B][COLOR FFFDBD01]Search[/COLOR][/B]", "Removed from history", TMDbmovies_ICON, 2000, False)
    xbmc.executebuiltin("Container.Refresh")

def edit_search_item(params):
    """Funcția apelată din meniul contextual pentru editare."""
    old_query = params.get('query')
    search_type = params.get('type')
    
    dialog = xbmcgui.Dialog()
    new_query = dialog.input("Edit search", defaultt=old_query, type=xbmcgui.INPUT_ALPHANUM)
    
    # Verificăm dacă utilizatorul a scris ceva și dacă e diferit de ce era înainte
    if new_query and new_query != old_query:
        # 1. Ștergem vechea intrare
        remove_search_from_history(old_query, search_type)
        
        # 2. Adăugăm noua intrare (ACESTA ERA PASUL LIPSĂ)
        add_search_to_history(new_query, search_type)
        
        # 3. Dăm Refresh la listă ca să apară modificarea vizual
        xbmcgui.Dialog().notification("[B][COLOR FFFDBD01]Search[/COLOR][/B]", "Change saved", TMDbmovies_ICON, 2000, False)
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

    MDB_ICON = os.path.join(ADDON_PATH, 'resources', 'media', 'mdblist.png')
    add_directory("[B][COLOR lightskyblue]MDB Lists[/COLOR][/B]", {'mode': 'mdblist_menu'}, icon=MDB_ICON, thumb=MDB_ICON, folder=True)
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
        add_directory(f"[B][COLOR FF00CED1]TMDB: {session.get('username', 'Connected')}[/COLOR][/B]", {'mode': 'noop'}, folder=False, icon='DefaultUser.png')
        add_directory("[COLOR red]Disconnect TMDB[/COLOR]", {'mode': 'tmdb_logout'}, folder=False, icon='DefaultIconError.png')
    else:
        add_directory("[B][COLOR FF00CED1]Connect TMDB[/COLOR][/B]", {'mode': 'tmdb_auth'}, folder=False, icon='DefaultUser.png')

    add_directory("[B][COLOR FF00CED1]TMDb v4 Authorization (TV Shows)[/COLOR][/B]", {'mode': 'tmdb_auth_v4_action'}, folder=False, icon='DefaultUser.png')

    trakt_token = read_json(TRAKT_TOKEN_FILE)
    if trakt_token and trakt_token.get('access_token'):
        user = trakt_api.get_trakt_username(trakt_token['access_token'])
        ADDON.setSetting('trakt_status', f"Connected: {user}")
        add_directory(f"[B][COLOR pink]Trakt: {user}[/COLOR][/B]", {'mode': 'noop'}, folder=False, icon='DefaultUser.png')
        add_directory("[COLOR red]Disconnect Trakt[/COLOR]", {'mode': 'trakt_revoke'}, folder=False, icon='DefaultIconError.png')
        add_directory("[COLOR FF6AFB92]Smart Sync[/COLOR]", {'mode': 'trakt_sync_smart_action'}, folder=False, icon='DefaultAddonService.png')
        add_directory("[COLOR cyan]Force Full Sync[/COLOR]", {'mode': 'trakt_sync_db'}, folder=False, icon='DefaultAddonService.png')
    else:
        add_directory("[B][COLOR pink]Connect Trakt[/COLOR][/B]", {'mode': 'trakt_auth'}, folder=False, icon='DefaultUser.png')

    add_directory("Addon Settings", {'mode': 'settings'}, folder=False, icon='DefaultAddonService.png')
    add_directory("[COLOR orange]Delete All Cache[/COLOR]", {'mode': 'clear_all_cache'}, folder=False, icon='DefaultAddonNone.png')

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
        # Dinamic: Cele mai votate/adăugate la favorite filme din ultimele 60 de zile
        current_date = datetime.date.today().strftime('%Y-%m-%d')
        recent_past = (datetime.date.today() - datetime.timedelta(days=60)).strftime('%Y-%m-%d')
        url = (
            f"{BASE_URL}/discover/movie?api_key={API_KEY}"
            f"&language=en-US&region=US"
            f"&primary_release_date.gte={recent_past}"
            f"&primary_release_date.lte={current_date}"
            f"&sort_by=vote_count.desc"
            f"&page={page_no}"
        )
        
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
            f"&without_genres=99"             # ✅ Fara documentare
            f"&with_runtime.gte=60"                  # ✅ Fără scurtmetraje
            f"&popularity.gte=40"                    # ✅ Moderat - nu pierzi filme bune
            f"&with_release_type=2|3"                # ✅ Doar cinema (Limited + Wide)
            f"&include_adult=false"                  # ✅ OK
        )

    elif action == 'tmdb_movies_anticipated':
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        max_date = (datetime.date.today() + datetime.timedelta(days=120)).strftime('%Y-%m-%d')
        url = (
            f"{BASE_URL}/discover/movie?api_key={API_KEY}"
            f"&language={LANG}"
            f"&primary_release_date.gte={tomorrow}"
            f"&primary_release_date.lte={max_date}"
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
        current_date = datetime.date.today().strftime('%Y-%m-%d')
        # Filtrăm strict după lansarea Digitală (with_release_type=4)
        url = (
            f"{BASE_URL}/discover/movie?api_key={API_KEY}&language={LANG}&region=US"
            f"&release_date.lte={current_date}"
            f"&with_release_type=4"
            f"&sort_by=release_date.desc"
            f"&with_runtime.gte=60&without_genres=99&vote_count.gte=5"
            f"&page={page_no}"
        )
    elif action == 'tmdb_movies_netflix':
        current_date = datetime.date.today().strftime('%Y-%m-%d')
        url = f"{BASE_URL}/discover/movie?api_key={API_KEY}&language={LANG}&region=US&watch_region=US&with_watch_providers=8&primary_release_date.lte={current_date}&sort_by=primary_release_date.desc&with_runtime.gte=60&without_genres=99&vote_count.gte=5&page={page_no}"
    elif action == 'tmdb_movies_amazon':
        current_date = datetime.date.today().strftime('%Y-%m-%d')
        url = f"{BASE_URL}/discover/movie?api_key={API_KEY}&language={LANG}&region=US&watch_region=US&with_watch_providers=9&primary_release_date.lte={current_date}&sort_by=primary_release_date.desc&with_runtime.gte=60&without_genres=99&vote_count.gte=5&page={page_no}"
    elif action == 'tmdb_movies_disney':
        current_date = datetime.date.today().strftime('%Y-%m-%d')
        url = f"{BASE_URL}/discover/movie?api_key={API_KEY}&language={LANG}&region=US&watch_region=US&with_watch_providers=337&primary_release_date.lte={current_date}&sort_by=primary_release_date.desc&with_runtime.gte=60&without_genres=99&vote_count.gte=5&page={page_no}"
    elif action == 'tmdb_movies_apple':
        current_date = datetime.date.today().strftime('%Y-%m-%d')
        url = f"{BASE_URL}/discover/movie?api_key={API_KEY}&language={LANG}&region=US&watch_region=US&with_watch_providers=350&primary_release_date.lte={current_date}&sort_by=primary_release_date.desc&with_runtime.gte=60&without_genres=99&vote_count.gte=5&page={page_no}"
    
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

    # =========================================================================
    # ROMANIAN MOVIES (Filme Românești)
    # =========================================================================
    elif action == 'romania_movies_latest':
        current_date = datetime.date.today().strftime('%Y-%m-%d')
        url = (
            f"{BASE_URL}/discover/movie?api_key={API_KEY}&language=ro-RO"
            f"&with_original_language=ro"
            f"&primary_release_date.lte={current_date}"
            f"&sort_by=primary_release_date.desc"
            f"&page={page_no}"
        )
    elif action == 'romania_movies_trending':
        year_ago = (datetime.date.today() - datetime.timedelta(days=365)).strftime('%Y-%m-%d')
        url = (
            f"{BASE_URL}/discover/movie?api_key={API_KEY}&language=ro-RO"
            f"&with_original_language=ro"
            f"&primary_release_date.gte={year_ago}"
            f"&sort_by=popularity.desc"
            f"&page={page_no}"
        )
    elif action == 'romania_movies_popular':
        url = (
            f"{BASE_URL}/discover/movie?api_key={API_KEY}&language=ro-RO"
            f"&with_original_language=ro"
            f"&sort_by=popularity.desc"
            f"&page={page_no}"
        )
    elif action == 'romania_movies_premieres':
        current_date = datetime.date.today().strftime('%Y-%m-%d')
        previous_date = (datetime.date.today() - datetime.timedelta(days=365)).strftime('%Y-%m-%d')
        url = (
            f"{BASE_URL}/discover/movie?api_key={API_KEY}&language=ro-RO"
            f"&with_original_language=ro"
            f"&primary_release_date.gte={previous_date}"
            f"&primary_release_date.lte={current_date}"
            f"&with_release_type=4|5"
            f"&sort_by=primary_release_date.desc"
            f"&page={page_no}"
        )
    elif action == 'romania_movies_in_theaters':
        current_date = datetime.date.today().strftime('%Y-%m-%d')
        previous_date = (datetime.date.today() - datetime.timedelta(days=90)).strftime('%Y-%m-%d')
        url = (
            f"{BASE_URL}/discover/movie?api_key={API_KEY}&language=ro-RO"
            f"&with_original_language=ro"
            f"&primary_release_date.gte={previous_date}"
            f"&primary_release_date.lte={current_date}"
            f"&with_release_type=3"
            f"&sort_by=primary_release_date.desc"
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
    
    elif action == 'tmdb_tv_latest_releases':
        current_date = datetime.date.today().strftime('%Y-%m-%d')
        url = f"{BASE_URL}/discover/tv?api_key={API_KEY}&language={LANG}&region=US&first_air_date.lte={current_date}&sort_by=first_air_date.desc&without_genres=99,10763,10767&vote_count.gte=5&page={page_no}"
        
    elif action == 'tmdb_tv_netflix':
        current_date = datetime.date.today().strftime('%Y-%m-%d')
        url = f"{BASE_URL}/discover/tv?api_key={API_KEY}&language={LANG}&region=US&watch_region=US&with_watch_providers=8&first_air_date.lte={current_date}&sort_by=first_air_date.desc&without_genres=99,10763,10767&vote_count.gte=5&page={page_no}"

    elif action == 'tmdb_tv_amazon':
        current_date = datetime.date.today().strftime('%Y-%m-%d')
        url = f"{BASE_URL}/discover/tv?api_key={API_KEY}&language={LANG}&region=US&watch_region=US&with_watch_providers=9&first_air_date.lte={current_date}&sort_by=first_air_date.desc&without_genres=99,10763,10767&vote_count.gte=5&page={page_no}"

    elif action == 'tmdb_tv_disney':
        current_date = datetime.date.today().strftime('%Y-%m-%d')
        url = f"{BASE_URL}/discover/tv?api_key={API_KEY}&language={LANG}&region=US&watch_region=US&with_watch_providers=337&first_air_date.lte={current_date}&sort_by=first_air_date.desc&without_genres=99,10763,10767&vote_count.gte=5&page={page_no}"

    elif action == 'tmdb_tv_apple':
        current_date = datetime.date.today().strftime('%Y-%m-%d')
        url = f"{BASE_URL}/discover/tv?api_key={API_KEY}&language={LANG}&region=US&watch_region=US&with_watch_providers=350&first_air_date.lte={current_date}&sort_by=first_air_date.desc&without_genres=99,10763,10767&vote_count.gte=5&page={page_no}"
    
    elif action == 'tmdb_tv_airing_today':
        url = f"{BASE_URL}/tv/airing_today?api_key={API_KEY}&language={LANG}&page={page_no}"
        
    elif action == 'tmdb_tv_on_the_air':
        url = f"{BASE_URL}/tv/on_the_air?api_key={API_KEY}&language={LANG}&page={page_no}"
        
    elif action == 'tmdb_tv_top_rated':
        # Dinamic: Cele mai votate/adăugate la favorite seriale din ultimele 90 de zile
        current_date = datetime.date.today().strftime('%Y-%m-%d')
        recent_past = (datetime.date.today() - datetime.timedelta(days=90)).strftime('%Y-%m-%d')
        url = (
            f"{BASE_URL}/discover/tv?api_key={API_KEY}"
            f"&language=en-US&region=US"
            f"&first_air_date.gte={recent_past}"
            f"&first_air_date.lte={current_date}"
            f"&sort_by=vote_count.desc"
            f"&page={page_no}"
        )
        
    elif action == 'tmdb_tv_upcoming':
        current_date, future_date = get_dates(31, reverse=False)
        url += f"&sort_by=popularity.desc&first_air_date.gte={current_date}&first_air_date.lte={future_date}"
    
    elif action == 'tmdb_tv_trending_day':
        url = f"{BASE_URL}/trending/tv/day?api_key={API_KEY}&language={LANG}&page={page_no}"
        
    elif action == 'tmdb_tv_trending_week':
        url = f"{BASE_URL}/trending/tv/week?api_key={API_KEY}&language={LANG}&page={page_no}"

    # =========================================================================
    # ROMANIAN TV SHOWS (Seriale Românești)
    # =========================================================================
    elif action == 'romania_tv_latest':
        current_date = datetime.date.today().strftime('%Y-%m-%d')
        url = (
            f"{BASE_URL}/discover/tv?api_key={API_KEY}&language=ro-RO"
            f"&with_original_language=ro"
            f"&first_air_date.lte={current_date}"
            f"&sort_by=first_air_date.desc"
            f"&page={page_no}"
        )
    elif action == 'romania_tv_trending':
        year_ago = (datetime.date.today() - datetime.timedelta(days=365)).strftime('%Y-%m-%d')
        url = (
            f"{BASE_URL}/discover/tv?api_key={API_KEY}&language=ro-RO"
            f"&with_original_language=ro"
            f"&first_air_date.gte={year_ago}"
            f"&sort_by=popularity.desc"
            f"&page={page_no}"
        )
    elif action == 'romania_tv_popular':
        url = (
            f"{BASE_URL}/discover/tv?api_key={API_KEY}&language=ro-RO"
            f"&with_original_language=ro"
            f"&sort_by=popularity.desc"
            f"&page={page_no}"
        )
    elif action == 'romania_tv_premieres':
        current_date = datetime.date.today().strftime('%Y-%m-%d')
        previous_date = (datetime.date.today() - datetime.timedelta(days=730)).strftime('%Y-%m-%d')
        url = (
            f"{BASE_URL}/discover/tv?api_key={API_KEY}&language=ro-RO"
            f"&with_original_language=ro"
            f"&first_air_date.gte={previous_date}"
            f"&first_air_date.lte={current_date}"
            f"&sort_by=first_air_date.desc"
            f"&page={page_no}"
        )

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

    # Trakt redirection
    if action and 'trakt_movies_' in action:
        from resources.lib import trakt_api
        list_type = action.replace('trakt_movies_', '')
        params['list_type'] = list_type
        params['media_type'] = 'movies'
        trakt_api.trakt_discovery_list(params)
        return

    from resources.lib.config import PAGE_LIMIT
    ITEMS_PER_API_PAGE = 20
    api_pages_needed = max(1, (PAGE_LIMIT + ITEMS_PER_API_PAGE - 1) // ITEMS_PER_API_PAGE)
    start_api_page = (page - 1) * api_pages_needed + 1

# --- FAST CACHE CHECK (RAM) ---
    cache_key = f"list_movie_{action}_{page}"
    cached_data = get_fast_cache(cache_key)
    if cached_data:
        render_from_fast_cache(cached_data)
        return
    # ---------------------------------

    # Fetch multiple API pages dacă PAGE_LIMIT > 20
    all_results = []
    more_pages = False
    for api_page in range(start_api_page, start_api_page + api_pages_needed):
        results = trakt_sync.get_tmdb_from_db(action, api_page)
        if not results:
            cache_lang = "ro-RO" if "romania_" in action else LANG
            string = f"{action}_{api_page}_{cache_lang}"
            data = cache_object(get_tmdb_movies_standard, string, [action, api_page], expiration=24)
            if data:
                results = data.get('results', [])
        if not results:
            break
        all_results.extend(results)
        if len(results) < ITEMS_PER_API_PAGE:
            break
        if api_page == start_api_page + api_pages_needed - 1:
            more_pages = True

    if not all_results:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    current_items = all_results[:PAGE_LIMIT]
    has_next = len(all_results) > PAGE_LIMIT or more_pages

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
        next_li.setArt({'icon': NEXT_PAGE_ICON, 'thumb': NEXT_PAGE_ICON})
        
        # 1. Adăugăm la afișare imediată
        items_to_add.append((next_url, next_li, True))
        
        # 2. Adăugăm la Cache RAM (STRUCTURA CORECTATĂ PENTRU A EVITA KeyError 'li')
        cache_list.append({
            'url': next_url,
            'li': next_li,          # <--- ADĂUGAT (CRITIC PENTRU CACHE)
            'is_folder': True,
            'info': {'mediatype': 'video'}, # Minim necesar
            'art': {'icon': NEXT_PAGE_ICON, 'thumb': NEXT_PAGE_ICON},
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

    if action and 'trakt_tv_' in action:
        from resources.lib import trakt_api
        list_type = action.replace('trakt_tv_', '')
        params['list_type'] = list_type
        params['media_type'] = 'shows'
        trakt_api.trakt_discovery_list(params)
        return

    from resources.lib.config import PAGE_LIMIT
    ITEMS_PER_API_PAGE = 20
    api_pages_needed = max(1, (PAGE_LIMIT + ITEMS_PER_API_PAGE - 1) // ITEMS_PER_API_PAGE)
    start_api_page = (page - 1) * api_pages_needed + 1

# --- FAST CACHE CHECK (RAM) ---
    cache_key = f"list_tv_{action}_{page}"
    cached_data = get_fast_cache(cache_key)
    if cached_data:
        render_from_fast_cache(cached_data)
        return
    # ---------------------------------

    # Fetch multiple API pages dacă PAGE_LIMIT > 20
    all_results = []
    more_pages = False
    for api_page in range(start_api_page, start_api_page + api_pages_needed):
        results = trakt_sync.get_tmdb_from_db(action, api_page)
        if not results:
            cache_lang = "ro-RO" if "romania_" in action else LANG
            string = f"{action}_{api_page}_{cache_lang}"
            data = cache_object(get_tmdb_tv_standard, string, [action, api_page], expiration=24)
            if data:
                results = data.get('results', [])
        if not results:
            break
        all_results.extend(results)
        if len(results) < ITEMS_PER_API_PAGE:
            break
        if api_page == start_api_page + api_pages_needed - 1:
            more_pages = True

    if not all_results:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    current_items = all_results[:PAGE_LIMIT]
    has_next = len(all_results) > PAGE_LIMIT or more_pages

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
        next_li.setArt({'icon': NEXT_PAGE_ICON, 'thumb': NEXT_PAGE_ICON})
        
        # 1. Adăugăm la afișare
        items_to_add.append((next_url, next_li, True))
        
        # 2. Adăugăm la Cache RAM (STRUCTURA CORECTATĂ)
        cache_list.append({
            'url': next_url,
            'li': next_li,          # <--- ADĂUGAT (CRITIC)
            'is_folder': True,
            'info': {'mediatype': 'video'},
            'art': {'icon': NEXT_PAGE_ICON, 'thumb': NEXT_PAGE_ICON},
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

    trakt_params_dict = {'mode': 'trakt_context_menu', 'tmdb_id': tmdb_id, 'type': content_type, 'title': title}
    if season: trakt_params_dict['season'] = season
    if episode: trakt_params_dict['episode'] = episode
    cm.append(('[B][COLOR pink]My Trakt[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{urlencode(trakt_params_dict)})"))

    tmdb_params_dict = {'mode': 'tmdb_context_menu', 'tmdb_id': tmdb_id, 'type': content_type, 'title': title}
    if season: tmdb_params_dict['season'] = season
    if episode: tmdb_params_dict['episode'] = episode
    cm.append(('[B][COLOR FF00CED1]My TMDB[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{urlencode(tmdb_params_dict)})"))

    # --- INSEREAZA RÂNDURILE ASTEA PENTRU MDB: ---
    mdb_params_dict = {'mode': 'mdblist_context_menu', 'tmdb_id': tmdb_id, 'type': content_type, 'title': title, 'imdb_id': imdb_id}
    cm.append(('[B][COLOR lightskyblue]My MDB Lists[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{urlencode(mdb_params_dict)})"))

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
    
    if is_in_favorites_view:
        rem_params = urlencode({'mode': 'remove_favorite', 'type': content_type, 'tmdb_id': tmdb_id})
        cm.append(('[B][COLOR yellow]Remove from My Favorites[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{rem_params})"))
    else:
        fav_params = urlencode({'mode': 'add_favorite', 'type': content_type, 'tmdb_id': tmdb_id, 'title': title})
        cm.append(('[B][COLOR yellow]Add to My Favorites[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{fav_params})"))

    if content_type in ('movie', 'episode'):
        if content_type == 'movie':
            scrape_params = urlencode({'mode': 'sources', 'tmdb_id': tmdb_id, 'type': 'movie', 'title': title, 'year': year, 'custom_title': '', 'custom_interactive': 'true'})
        else:
            scrape_params = urlencode({'mode': 'sources', 'tmdb_id': tmdb_id, 'type': 'tv', 'title': title, 'season': str(season), 'episode': str(episode), 'custom_title': '', 'custom_interactive': 'true'})
        cm.append(('[B]Scrape with Custom Values[/B]', f"RunPlugin({sys.argv[0]}?{scrape_params})"))

    from resources.lib import trakt_sync
    progress = trakt_sync.get_local_playback_progress(tmdb_id, content_type, season, episode)
    
    # Recunoaștem procentele noi (<90) dar și formatul vechi de resume (>= 1000000)
    if progress > 0 and (progress < 90 or progress >= 1000000):
        rem_params = {'mode': 'remove_progress', 'tmdb_id': tmdb_id, 'type': content_type}
        if season: rem_params['season'] = str(season)
        if episode: rem_params['episode'] = str(episode)
        cm.append(('[B][COLOR red]Delete Resume[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{urlencode(rem_params)})"))

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
    
    try:
        duration = int(full_details.get('runtime') or 0) * 60
    except:
        duration = 0
    if duration <= 0: duration = 7200 # Fallback 2 ore
    
    # Acum full_details are DEJA RO în el automat!
    tagline = full_details.get('tagline', '').strip()
    genres_str = get_genres_string(item.get('genre_ids',[]))
    if not genres_str and full_details.get('genres'):
        genres_str = ", ".join([g['name'] for g in full_details['genres']])
        
    plot = full_details.get('overview', item.get('overview', ''))
    
    try: show_motto = ADDON.getSetting('show_motto_genre') != 'false'
    except: show_motto = True
    
    plot_header = ""
    if show_motto:
        if tagline and genres_str:
            plot_header = f"[B][COLOR yellow]{tagline}[/COLOR][/B] | [B][COLOR FF00CED1]{genres_str}[/COLOR][/B]\n"
        elif tagline:
            plot_header = f"[B][COLOR yellow]{tagline}[/COLOR][/B]\n"
        elif genres_str:
            plot_header = f"[B][COLOR FF00CED1]{genres_str}[/COLOR][/B]\n"
        
    plot = plot_header + plot
    
    poster_path = full_details.get('poster_path', item.get('poster_path', ''))
    backdrop_path = full_details.get('backdrop_path', item.get('backdrop_path', ''))
    
    raw_logo = full_details.get('clearlogo', '')
    movie_logo = f"{IMG_BASE}{raw_logo}" if raw_logo and not raw_logo.startswith('http') else raw_logo

    # --- LOGICA CULOARE ROȘIE FILME NELANSATE ---
    display_title = f"{title} ({year})" if year else title
    if premiered:
        try:
            parts = str(premiered).split('-')
            if datetime.date(int(parts[0]), int(parts[1]), int(parts[2])) > datetime.date.today():
                display_title = f"[B][COLOR FFE238EC]{display_title}[/COLOR] (Nelansat)[/B]"
        except: pass

    # --- CALCUL RESUME ---
    from resources.lib import trakt_sync
    progress_value = trakt_sync.get_local_playback_progress(tmdb_id, 'movie')
    
    resume_percent = 0
    resume_time = 0
    if progress_value >= 1000000:
        resume_time = int(progress_value - 1000000)
        resume_percent = (resume_time / duration) * 100
    elif 0 < progress_value < 90:
        resume_percent = progress_value
        resume_time = int((resume_percent / 100.0) * duration)

    poster_path = full_details.get('poster_path', item.get('poster_path', ''))
    poster = f"{IMG_BASE}{poster_path}" if poster_path else TMDbmovies_ICON
    backdrop_path = full_details.get('backdrop_path', item.get('backdrop_path', ''))
    backdrop = f"{BACKDROP_BASE}{backdrop_path}" if backdrop_path else ''

    is_watched = trakt_api.get_watched_counts(tmdb_id, 'movie') > 0

    info = {
        'mediatype': 'movie', 'title': title, 'year': year, 'plot': plot, 
        'rating': rating, 'votes': votes, 'premiered': premiered, 
        'studio': studio, 'duration': duration, 'resume_percent': resume_percent,
        'genre': genres_str,
        'playcount': 1 if is_watched else 0,
        'mpaa': full_details.get('mpaa', '')
    }
    
    # --- MODIFICARE: Trimitem imdb_id in context menu ---
    cm = _get_full_context_menu(tmdb_id, 'movie', title, is_in_favorites_view, year=year, imdb_id=imdb_id)
    # ----------------------------------------------------
    url_params = {'mode': 'sources', 'tmdb_id': tmdb_id, 'type': 'movie', 'title': title, 'year': year}
    
    li = xbmcgui.ListItem(display_title)
    
    art = {'icon': poster, 'thumb': poster, 'poster': poster, 'fanart': backdrop}
    if movie_logo:
        art['clearlogo'] = movie_logo
    li.setArt(art)
    
    li.setProperty('tmdb_id', tmdb_id)
    set_metadata(li, info, unique_ids={'tmdb': tmdb_id}, watched_info=is_watched)
    
    if resume_time > 0:
        set_resume_point(li, resume_time, duration)

    if cm: li.addContextMenuItems(cm)
    
    # --- LOGICA DE RETURNARE PENTRU CACHE ---
    if return_data:
        return {
            'url': f"{sys.argv[0]}?{urlencode(url_params)}",
            'li': li,
            'is_folder': False,
            'info': info,
            'art': {'icon': poster, 'thumb': poster, 'poster': poster, 'fanart': backdrop, 'clearlogo': movie_logo},
            'cm_items': cm,
            'resume_time': resume_time,
            'total_time': duration,
            'label': display_title
        }

    # Adaugă clearlogo=movie_logo în apelul funcției
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
    
    try:
        runtimes = full_details.get('episode_run_time')
        duration = int(runtimes[0]) * 60 if runtimes and runtimes[0] else 0
    except:
        duration = 0
    
    # 1. Datele de bază în engleză
    tagline = full_details.get('tagline', '').strip()
    genres_str = get_genres_string(item.get('genre_ids',[]))
    if not genres_str and full_details.get('genres'):
        genres_str = ", ".join([g['name'] for g in full_details['genres']])
        
    plot = full_details.get('overview', item.get('overview', ''))
    
    try: show_motto = ADDON.getSetting('show_motto_genre') != 'false'
    except: show_motto = True
    
    plot_header = ""
    if show_motto:
        if tagline and genres_str:
            plot_header = f"[B][COLOR yellow]{tagline}[/COLOR][/B] | [B][COLOR FF00CED1]{genres_str}[/COLOR][/B]\n"
        elif tagline:
            plot_header = f"[B][COLOR yellow]{tagline}[/COLOR][/B]\n"
        elif genres_str:
            plot_header = f"[B][COLOR FF00CED1]{genres_str}[/COLOR][/B]\n"
        
    plot = plot_header + plot
        
    poster_path = full_details.get('poster_path', item.get('poster_path', ''))
    backdrop_path = full_details.get('backdrop_path', item.get('backdrop_path', ''))
    
    raw_logo = full_details.get('clearlogo', '')
    tv_logo = f"{IMG_BASE}{raw_logo}" if raw_logo and not raw_logo.startswith('http') else raw_logo

    # --- LOGICA CULOARE ROȘIE SERIALE NELANSATE ---
    display_name = f"{title} ({year})" if year else title
    if premiered:
        try:
            parts = str(premiered).split('-')
            if datetime.date(int(parts[0]), int(parts[1]), int(parts[2])) > datetime.date.today():
                display_name = f"[B][COLOR FFE238EC]{display_name}[/COLOR] (Nelansat)[/B]"
        except: pass

    poster_path = full_details.get('poster_path', item.get('poster_path', ''))
    poster = f"{IMG_BASE}{poster_path}" if poster_path else TMDbmovies_ICON
    backdrop_path = full_details.get('backdrop_path', item.get('backdrop_path', ''))
    backdrop = f"{BACKDROP_BASE}{backdrop_path}" if backdrop_path else ''

    watched_info = get_watched_status_tvshow(tmdb_id)
    
    # Asigurăm-ne că valorile sunt întotdeauna numere întregi (evităm eroarea cu NoneType)
    w_watched = int(watched_info.get('watched') or 0)
    w_total = int(watched_info.get('total') or 0)
    
    # Verificăm dacă serialul este văzut complet pentru bifă
    is_watched = w_watched >= w_total if w_total > 0 else False
    
    info = {
        'mediatype': 'tvshow', 'title': title, 'year': year, 'plot': plot, 
        'rating': rating, 'votes': votes, 'premiered': premiered, 
        'studio': studio, 'duration': duration, 'genre': genres_str,
        'playcount': 1 if is_watched else 0,
        'mpaa': full_details.get('mpaa', '')
    }

    # --- MODIFICARE: Trimitem parametrul year catre _get_full_context_menu ---
    cm = _get_full_context_menu(tmdb_id, 'tv', title, is_in_favorites_view, year=year, imdb_id=imdb_id)
    # -------------------------------------------------------------------------
    url_params = {'mode': 'details', 'tmdb_id': tmdb_id, 'type': 'tv', 'title': title}
    
    li = xbmcgui.ListItem(display_name)
    
    art = {'icon': poster, 'thumb': poster, 'poster': poster, 'fanart': backdrop}
    if tv_logo:
        art['clearlogo'] = tv_logo
        art['tvshow.clearlogo'] = tv_logo
        art['tvshow.logo'] = tv_logo
        art['logo'] = tv_logo
        art['fanart_clearlogo'] = tv_logo
    li.setArt(art)
    
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
            'art': art,  # ACUM TRIMIT TOATE ART-URILE INCLUZÂND LOGO!
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


# TMDB V4 AUTH -------------------

def get_tmdb_v4_token():
    """Citește token-ul v4 al utilizatorului din fișierul local."""
    data = read_json(TMDB_V4_TOKEN_FILE)
    if data and data.get('access_token'):
        return data['access_token']
    return None

def tmdb_auth_v4():
    """Procesul de autorizare TMDb v4 (pentru seriale) cu Link Scurt."""
    dialog = xbmcgui.Dialog()
    
    # Verificăm dacă avem cheia de develop în config
    if not TMDB_V4_READ_TOKEN or "PUNE_AICI" in TMDB_V4_READ_TOKEN:
        dialog.notification("Error Config", "TMDB_V4_READ_TOKEN not set in config.py!", xbmcgui.NOTIFICATION_ERROR)
        return

    headers = {
        'Authorization': f'Bearer {TMDB_V4_READ_TOKEN}',
        'Content-Type': 'application/json;charset=utf-8'
    }
    
    try:
        # 1. Cerem Request Token
        r = requests.post('https://api.themoviedb.org/4/auth/request_token', headers=headers, timeout=10)
        data = r.json()
        
        if not data.get('success'):
            dialog.notification("Error TMDb", data.get('status_message', 'Error'), xbmcgui.NOTIFICATION_ERROR)
            return
            
        request_token = data['request_token']
        
        # 2. Construim URL-ul complet
        url_full = f"https://www.themoviedb.org/auth/access?request_token={request_token}"
        
        # --- GENERARE LINK SCURT (TinyURL) ---
        try:
            r_tiny = requests.get(f'http://tinyurl.com/api-create.php?url={url_full}', timeout=5)
            if r_tiny.status_code == 200:
                url_display = r_tiny.text
            else:
                url_display = url_full # Fallback la cel lung
        except:
            url_display = url_full
        
        # Copiem link-ul lung în clipboard (dacă e pe PC/Android)
        xbmc.executebuiltin(f'SetProperty(TMDbAuthLink,{url_full},home)')
        
        text = (f"Authorization required for TV Shows:\n\n"
                f"1. Go to this link (from phone/PC):\n"
                f"[COLOR yellow][B]{url_display}[/B][/COLOR]\n\n"
                f"2. Log in and press [B]Approve[/B].\n"
                f"3. After approving on the site, press [B]OK[/B] here.")
        
        # Afișăm dialogul și așteptăm OK-ul utilizatorului
        if not dialog.yesno("TMDb v4 Authorization", text, yeslabel="I Approved", nolabel="Cancel"):
            return # Userul a dat Cancel
        
        # 3. Schimbăm Request Token pe Access Token (Final)
        payload = {'request_token': request_token}
        r2 = requests.post('https://api.themoviedb.org/4/auth/access_token', headers=headers, json=payload, timeout=15)
        data2 = r2.json()
        
        if data2.get('success'):
            write_json(TMDB_V4_TOKEN_FILE, {
                'access_token': data2['access_token'],
                'account_id': data2['account_id']
            })
            dialog.notification("TMDb v4", "Authorization successful!", TMDB_ICON, 3000, False)
            
            # ══════════════════════════════════════════════════════════
            # ADĂUGAT: Actualizare automată a listelor (inclusiv seriale v4)
            # ══════════════════════════════════════════════════════════
            import threading
            from resources.lib import trakt_sync
            t = threading.Thread(target=trakt_sync.sync_full_library, kwargs={'silent': False, 'force': True})
            t.daemon = True
            t.start()
            # ══════════════════════════════════════════════════════════
            # Reîmprospătăm variabilele globale sau cache-ul dacă e necesar
        else:
            msg = data2.get('status_message', 'Unknown error')
            dialog.notification("Error", f"You did not approve: {msg}", xbmcgui.NOTIFICATION_ERROR)
            
    except Exception as e:
        log(f"[TMDB] Auth Error: {e}", xbmc.LOGERROR)
        dialog.notification("Error", "Check the log", xbmcgui.NOTIFICATION_ERROR)



# ------------------

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
            dialog.notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Token initialization error", xbmcgui.NOTIFICATION_ERROR)
            return False
    except:
        dialog.notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Server connection error", xbmcgui.NOTIFICATION_ERROR)
        return False

    username = dialog.input("Enter TMDB Username", type=xbmcgui.INPUT_ALPHANUM)
    if not username: return False

    password = dialog.input("Enter TMDB Password", type=xbmcgui.INPUT_ALPHANUM, option=xbmcgui.ALPHANUM_HIDE_INPUT)
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
            dialog.notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Incorrect username or password!", xbmcgui.NOTIFICATION_ERROR)
            return False
            
    except Exception as e:
        log(f"[TMDB] Login Error: {e}", xbmc.LOGERROR)
        dialog.notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Validation error", xbmcgui.NOTIFICATION_ERROR)
        return False

    return create_tmdb_session(request_token)

def create_tmdb_session(request_token):
    dialog = xbmcgui.Dialog()
    try:
        session_url = f"{BASE_URL}/authentication/session/new?api_key={API_KEY}"
        r = requests.post(session_url, json={'request_token': request_token}, timeout=10)

        if r.status_code != 200:
            dialog.notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Session creation error!", xbmcgui.NOTIFICATION_ERROR)
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

        ADDON.setSetting('tmdb_status', f"Connected: {username}")

        dialog.notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", f"Connected: [B][COLOR FFF70D1A]{username}[/COLOR][/B]", TMDB_ICON, 3000, False)
        
        # ══════════════════════════════════════════════════════════
        # ADĂUGAT: Sincronizare automată în background după conectare
        # ══════════════════════════════════════════════════════════
        import threading
        from resources.lib import trakt_sync
        t = threading.Thread(target=trakt_sync.sync_full_library, kwargs={'silent': False, 'force': True})
        t.daemon = True
        t.start()
        # ══════════════════════════════════════════════════════════

        xbmc.executebuiltin("Container.Refresh")
        return True

    except Exception as e:
        log(f"[TMDB] Session Error: {e}", xbmc.LOGERROR)
        dialog.notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Session error", xbmcgui.NOTIFICATION_ERROR)
        return False

def tmdb_logout():
    # --- START PROTECTIE DECONECTARE ACCIDENTALA ---
    if not xbmcgui.Dialog().yesno("[B][COLOR FF00CED1]Disconnect TMDb[/COLOR][/B]", "Are you sure you want to disconnect your TMDb account?"):
        return
    # --- END PROTECTIE ---

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

    ADDON.setSetting('tmdb_status', "Disconnected")

    xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "User Disconnected", TMDB_ICON, 3000, False)
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
    xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "List cache cleared", TMDB_ICON, 3000, False)
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
    detail_tasks = []

    for lst in lists_v4:
        list_id = str(lst.get('id'))
        
        poster_path = lst.get('poster_path', '')
        backdrop_path = lst.get('backdrop_path', '')
        
        poster = get_list_image_url(poster_path, 'poster') or ''
        backdrop = get_list_image_url(backdrop_path, 'fanart') or ''
        
        entry = {
            'id': list_id,
            'name': lst.get('name', 'Unknown'),
            'description': lst.get('description', ''),
            'item_count': lst.get('number_of_items', lst.get('item_count', 0)),
            'poster': poster,
            'backdrop': backdrop,
            'public': lst.get('public', False),
            '_needs_detail': not poster and bool(list_id)
        }
        
        if entry['_needs_detail']:
            detail_tasks.append(entry)
        else:
            lists_with_details.append(entry)

    if detail_tasks:
        def fetch_worker(list_id):
            return list_id, get_tmdb_list_details_v4(list_id)
        
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(fetch_worker, e['id']): e for e in detail_tasks}
            detail_map = {}
            for future in as_completed(futures):
                list_id, details = future.result()
                detail_map[list_id] = details
        
        for entry in detail_tasks:
            list_details = detail_map.get(entry['id'])
            if list_details and list_details.get('results'):
                first_item = list_details['results'][0]
                item_poster = first_item.get('poster_path', '')
                item_backdrop = first_item.get('backdrop_path', '')
                if item_poster:
                    entry['poster'] = get_list_image_url(item_poster, 'poster')
                if item_backdrop and not entry['backdrop']:
                    entry['backdrop'] = get_list_image_url(item_backdrop, 'fanart')
            lists_with_details.append(entry)

    return lists_with_details


def get_tmdb_user_lists_v3():
    session = get_tmdb_session()
    if not session:
        return []

    lists_url = f"{BASE_URL}/account/{session['account_id']}/lists?api_key={API_KEY}&session_id={session['session_id']}"
    lists_data = get_json(lists_url)

    if not lists_data or 'results' not in lists_data:
        return []

    lists = lists_data['results']
    results = [None] * len(lists)

    def fetch_worker(idx, lst):
        list_id = str(lst.get('id'))
        url = f"{BASE_URL}/list/{list_id}?api_key={API_KEY}&language={LANG}"
        details = get_json(url)
        poster_path = ''
        backdrop_path = ''
        if details and details.get('items'):
            first = details['items'][0]
            poster_path = first.get('poster_path', '')
            backdrop_path = first.get('backdrop_path', '')
        return idx, {
            'id': list_id,
            'name': lst.get('name', 'Unknown'),
            'description': lst.get('description', ''),
            'item_count': lst.get('item_count', 0),
            'poster': f"{IMG_BASE}{poster_path}" if poster_path else '',
            'backdrop': f"{BACKDROP_BASE}{backdrop_path}" if backdrop_path else ''
        }

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fetch_worker, i, lst): i for i, lst in enumerate(lists)}
        for future in as_completed(futures):
            idx, entry = future.result()
            results[idx] = entry

    return results


def tmdb_my_lists():
    session = get_tmdb_session()
    if not session:
        add_directory("[B][COLOR FF00CED1]Connect TMDB[/COLOR][/B]", {'mode': 'tmdb_auth'}, icon='DefaultUser.png', folder=False)
        xbmcplugin.endOfDirectory(HANDLE)
        return

    add_directory("[B][COLOR FFCCCCFF]Watchlist[/COLOR][/B]", {'mode': 'tmdb_watchlist_menu'}, icon=TMDB_ICON, thumb=TMDB_ICON, folder=True)
    add_directory("[B][COLOR FFCCCCFF]Favorites[/COLOR][/B]", {'mode': 'tmdb_favorites_menu'}, icon=TMDB_ICON, thumb=TMDB_ICON, folder=True)
    add_directory("[B][COLOR FFCCCCFF]Recommendations[/COLOR][/B]", {'mode': 'tmdb_recommendations_menu'}, icon=TMDB_ICON, thumb=TMDB_ICON, folder=True)
    
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
                f"[B][COLOR FFCCCCFF]{name} [COLOR FFFDBD01]({count})[/COLOR][/B]",
                {'mode': 'tmdb_list_items', 'list_id': list_id, 'list_name': name},
                icon=poster, thumb=poster, fanart=fanart, cm=cm, info=info, folder=True
            )
    else:
        add_directory("[COLOR gray]No personal lists or sync again[/COLOR]", {'mode': 'trakt_sync_db'}, folder=False)

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
            log(f"[TMDB] Error sync recommendations: {e}", xbmc.LOGERROR)
    
    if not results:
        add_directory("[COLOR gray]No recommendations available[/COLOR]", {'mode': 'noop'}, folder=False)
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
        add_directory(f"[B]Next Page ({page+1}) >>[/B]", {'mode': 'tmdb_list_items', 'list_id': list_id, 'list_name': list_name, 'page': str(page+1)}, icon=NEXT_PAGE_ICON, folder=True)
    xbmcplugin.setContent(HANDLE, 'movies'); xbmcplugin.endOfDirectory(HANDLE)


def clear_list_cache(params):
    list_id = params.get('list_id')
    cache = MainCache()
    cache.delete(f"tmdb_list_full_{list_id}") 
    xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]", "List Cache Cleared!", TMDbmovies_ICON, 3000, False)
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
        next_li.setArt({'icon': NEXT_PAGE_ICON, 'thumb': NEXT_PAGE_ICON})
        items_to_add.append((next_url, next_li, True))
        cache_list.append({'label': next_label, 'url': next_url, 'is_folder': True, 'art': {'icon': NEXT_PAGE_ICON}, 'info': {'mediatype': 'video'}, 'cm_items': []})

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
        add_directory(f"[B]Next Page ({page+1}) >>[/B]", {'mode': 'tmdb_favorites', 'type': content_type, 'page': str(page+1)}, icon=NEXT_PAGE_ICON, folder=True)
    xbmcplugin.setContent(HANDLE, 'movies' if content_type == 'movie' else 'tvshows')
    xbmcplugin.endOfDirectory(HANDLE)


def add_to_tmdb_watchlist(content_type, tmdb_id):
    session = get_tmdb_session()
    if not session:
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Not connected", xbmcgui.NOTIFICATION_WARNING)
        return False
    url = f"{BASE_URL}/account/{session['account_id']}/watchlist?api_key={API_KEY}&session_id={session['session_id']}"
    payload = {'media_type': content_type, 'media_id': int(tmdb_id), 'watchlist': True}
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code in [200, 201]:
            xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Added to [B][COLOR FF00CED1]Watchlist[/COLOR][/B]", TMDB_ICON, 3000, False)
            
            # --- FIX BUFFERING: SQL INSTANT ---
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
                          ('watchlist', content_type, str(tmdb_id), d_title, d_year, d_poster, str(time.time()), d_overview))
                conn.commit()
                conn.close()
            except: pass

            # 2. Refresh UI Imediat (ca să dispară rotița)
            from resources.lib.cache import clear_all_fast_cache
            clear_all_fast_cache()
            xbmc.executebuiltin("Container.Refresh")
            
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
            xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Removed from [B][COLOR FF00CED1]Watchlist[/COLOR][/B]", TMDB_ICON, 3000, False)
            
            # --- FIX BUFFERING: SQL INSTANT ---
            try:
                conn = trakt_sync.get_connection()
                c = conn.cursor()
                c.execute("DELETE FROM tmdb_account_lists WHERE list_type=? AND media_type=? AND tmdb_id=?", 
                          ('watchlist', content_type, str(tmdb_id)))
                conn.commit()
                conn.close()
            except: pass
            
            from resources.lib.cache import clear_all_fast_cache
            clear_all_fast_cache()
            xbmc.executebuiltin("Container.Refresh")
            
            return True
            # -------------------------------------------------
    except: pass
    return False


def add_to_tmdb_favorites(content_type, tmdb_id):
    session = get_tmdb_session()
    if not session:
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Not connected", TMDB_ICON, 3000, False)
        return False

    url = f"{BASE_URL}/account/{session['account_id']}/favorite?api_key={API_KEY}&session_id={session['session_id']}"
    payload = {'media_type': content_type, 'media_id': int(tmdb_id), 'favorite': True}

    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code in [200, 201]:
            xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Added to [B][COLOR FF00CED1]Favorites[/COLOR][/B]", TMDB_ICON, 3000, False)
            
            # --- FIX BUFFERING: SQL INSTANT ---
            try:
                details = get_tmdb_item_details(str(tmdb_id), content_type) or {}
                conn = trakt_sync.get_connection()
                c = conn.cursor()
                d_title = details.get('title') or details.get('name', 'Unknown')
                d_year = str(details.get('release_date') or details.get('first_air_date', ''))[:4]
                d_poster = details.get('poster_path', '')
                d_overview = details.get('overview', '')
                c.execute("INSERT OR REPLACE INTO tmdb_account_lists VALUES (?,?,?,?,?,?,?,?)", 
                          ('favorite', content_type, str(tmdb_id), d_title, d_year, d_poster, str(time.time()), d_overview))
                conn.commit()
                conn.close()
            except: pass

            from resources.lib.cache import clear_all_fast_cache
            clear_all_fast_cache()
            xbmc.executebuiltin("Container.Refresh")
            
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
            xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Removed from [B][COLOR FF00CED1]Favorites[/COLOR][/B]", TMDB_ICON, 3000, False)
            
            # --- FIX BUFFERING: SQL INSTANT ---
            try:
                conn = trakt_sync.get_connection()
                c = conn.cursor()
                c.execute("DELETE FROM tmdb_account_lists WHERE list_type=? AND media_type=? AND tmdb_id=?", 
                          ('favorite', content_type, str(tmdb_id)))
                conn.commit()
                conn.close()
            except: pass

            from resources.lib.cache import clear_all_fast_cache
            clear_all_fast_cache()
            xbmc.executebuiltin("Container.Refresh")

            return True
            # -------------------------------------------------
    except:
        pass
    return False


def add_to_tmdb_list(list_id, tmdb_id, content_type='movie'):
    session = get_tmdb_session()
    if not session: 
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Not connected", TMDB_ICON, 3000, False)
        return False

    success = False
    media_type_normalized = 'tv' if content_type in ['tv', 'tvshow'] else 'movie'
    
    # --- LOGICA NOUĂ PENTRU SERIALE (API V4) ---
    if content_type == 'tv' or content_type == 'tvshow':
        # 1. Luăm token-ul userului
        user_v4_token = get_tmdb_v4_token()
        
        # 2. Dacă nu există, cerem autorizare
        if not user_v4_token:
            if xbmcgui.Dialog().yesno("Authorization Required", "To add TV shows, additional TMDb v4 authorization is required.\nDo you want to authorize now?"):
                tmdb_auth_v4()
                user_v4_token = get_tmdb_v4_token() # Reîncercăm citirea
            
            if not user_v4_token: return False # Dacă tot nu a autorizat, ieșim

        url = f"{TMDB_V4_BASE_URL}/list/{list_id}/items"
        
        # Folosim token-ul userului
        headers = {
            'Authorization': f'Bearer {user_v4_token}',
            'Content-Type': 'application/json;charset=utf-8'
        }
        payload = {
            "items": [
                {
                    "media_type": "tv",
                    "media_id": int(tmdb_id)
                }
            ]
        }
        
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=10)
            if r.status_code in [200, 201]:
                resp_data = r.json()
                if resp_data.get('success'):
                    xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "TV show added to list", TMDB_ICON, 3000, False)
                    success = True
                else:
                    log(f"[TMDB] V4 Add failed logic: {resp_data}")
            else:
                log(f"[TMDB] V4 Add failed status: {r.status_code} - {r.text}")
        except Exception as e:
            log(f"[TMDB] V4 Add Error: {e}", xbmc.LOGERROR)

    # --- LOGICA VECHE PENTRU FILME (API V3) ---
    else:
        url = f"{BASE_URL}/list/{list_id}/add_item?api_key={API_KEY}&session_id={session['session_id']}"
        try:
            r = requests.post(url, json={'media_id': int(tmdb_id)}, timeout=10)
            if r.status_code in [200, 201]:
                xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Added to list", TMDB_ICON, 3000, False)
                success = True
        except: pass

    if success:
        try:
            details = get_tmdb_item_details(str(tmdb_id), media_type_normalized) or {}
            d_title = details.get('title') or details.get('name', 'Unknown')
            d_year = str(details.get('release_date') or details.get('first_air_date', ''))[:4]
            d_poster = details.get('poster_path', '')
            d_backdrop = details.get('backdrop_path', '') # Definit corect aici
            d_overview = details.get('overview', '')
            
            conn = trakt_sync.get_connection()
            c = conn.cursor()
            # 1. Inserăm item-ul în baza locală (sort_index -1 pentru a fi primul)
            c.execute("INSERT OR REPLACE INTO tmdb_custom_list_items VALUES (?,?,?,?,?,?,?,?)", 
                      (str(list_id), str(tmdb_id), media_type_normalized, d_title, d_year, d_poster, d_overview, -1))
            
            # 2. Actualizăm imaginea de copertă a listei (poster + backdrop) și incrementăm contorul
            c.execute("UPDATE tmdb_custom_lists SET item_count = item_count + 1, poster = ?, backdrop = ? WHERE list_id=?", 
                      (d_poster, d_backdrop, str(list_id)))
            conn.commit()
            conn.close()
        except Exception as e:
            log(f"[TMDB] Error updating local SQL on add: {e}")

        # 3. Curățăm cache-ul RAM și dăm refresh o singură dată, la final
        from resources.lib.cache import clear_all_fast_cache
        clear_all_fast_cache()
        xbmc.executebuiltin("Container.Refresh")
        return True
    
    return False


def remove_from_tmdb_list(list_id, tmdb_id, content_type='movie'):
    session = get_tmdb_session()
    if not session: return False

    success = False
    m_type = 'tv' if content_type in ['tv', 'tvshow', 'episode'] else 'movie'
    user_v4_token = get_tmdb_v4_token()

    if user_v4_token:
        url = f"https://api.themoviedb.org/4/list/{list_id}/items"
        headers = {'Authorization': f'Bearer {user_v4_token}', 'Content-Type': 'application/json', 'accept': 'application/json'}
        
        def try_delete(media_t):
            try:
                payload = {"items": [{"media_type": media_t, "media_id": int(tmdb_id)}]}
                r = requests.request("DELETE", url, json=payload, headers=headers, timeout=10)
                res = r.json()
                return res.get('success') and res.get('results') and res['results'][0].get('success')
            except: return False

        success = try_delete(m_type)
        
        if not success:
            other_type = 'movie' if m_type == 'tv' else 'tv'
            success = try_delete(other_type)

    if not success and m_type == 'movie':
        url_v3 = f"https://api.themoviedb.org/3/list/{list_id}/remove_item?api_key={API_KEY}&session_id={session['session_id']}"
        try:
            r = requests.post(url_v3, json={'media_id': int(tmdb_id)}, timeout=10)
            if r.status_code in [200, 201]: success = True
        except: pass

    if success:
        # 1. Ștergere locală SQL + ACTUALIZARE POSTER LISTĂ
        try:
            from resources.lib import trakt_sync
            conn = trakt_sync.get_connection()
            c = conn.cursor()
            
            # A. Ștergem item-ul
            c.execute("DELETE FROM tmdb_custom_list_items WHERE list_id=? AND tmdb_id=?", 
                      (str(list_id), str(tmdb_id)))
            
            # B. Luăm posterul primului element RĂMAS pentru coperta listei
            c.execute("SELECT poster FROM tmdb_custom_list_items WHERE list_id=? ORDER BY sort_index ASC LIMIT 1", 
                      (str(list_id),))
            row = c.fetchone()
            
            # C. Numărăm câte au mai rămas
            c.execute("SELECT COUNT(*) FROM tmdb_custom_list_items WHERE list_id=?", 
                      (str(list_id),))
            new_count = c.fetchone()[0]
            
            # D. Actualizăm lista: count + poster nou
            if row and new_count > 0:
                c.execute("UPDATE tmdb_custom_lists SET item_count=?, poster=? WHERE list_id=?", 
                          (new_count, row[0] or '', str(list_id)))
            else:
                # The list is empty - resetăm tot
                c.execute("UPDATE tmdb_custom_lists SET item_count=0, poster='', backdrop='' WHERE list_id=?", 
                          (str(list_id),))
            
            conn.commit()
            conn.close()
        except Exception as e:
            log(f"[TMDB] SQL Remove Error: {e}")

        # 2. Invalidare Smart Sync
        try:
            from resources.lib.config import LAST_SYNC_FILE
            sync_data = read_json(LAST_SYNC_FILE) or {}
            if 'lists' in sync_data:
                del sync_data['lists']
                write_json(LAST_SYNC_FILE, sync_data)
        except: pass

        from resources.lib.cache import clear_all_fast_cache
        clear_all_fast_cache()
        
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Deleted from website and local", TMDB_ICON, 3000, False)
        xbmc.executebuiltin("Container.Refresh")
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


def show_tmdb_context_menu(tmdb_id, content_type, title='', season=None, episode=None):
    session = get_tmdb_session()
    if not session:
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Not connected", xbmcgui.NOTIFICATION_WARNING)
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
        if rate_tmdb_item(tmdb_id, content_type, season, episode):
            xbmc.executebuiltin("Container.Refresh")


def show_mdblist_context_menu(tmdb_id, imdb_id, content_type, title=''):
    import xbmcgui
    import xbmc
    import os
    from resources.lib.config import ADDON
    
    MDB_ICON = os.path.join(ADDON.getAddonInfo('path'), 'resources', 'media', 'mdblist.png')
    
    from resources.lib import mdblist
    if not mdblist.is_authenticated():
        xbmcgui.Dialog().notification("[B][COLOR lightskyblue]MDBList[/COLOR][/B]", "Add your [B][COLOR lightskyblue]MDBList[/COLOR][/B] API Key in Settings!", MDB_ICON, 3000, False)
        return

    xbmc.executebuiltin('ActivateWindow(busydialognocancel)')
    
    watchlist = mdblist.fetch_watchlist(content_type)
    in_watchlist = False
    if watchlist:
        for item in watchlist:
            item_tmdb = str(item.get('tmdbid') or item.get('tmdb_id') or item.get('show_tmdbid') or item.get('id', ''))
            if item_tmdb == str(tmdb_id):
                in_watchlist = True
                break

    xbmc.executebuiltin('Dialog.Close(busydialognocancel)')

    options = []
    if in_watchlist:
        options.append(('Remove from [B][COLOR lightskyblue]MDB Watchlist[/COLOR][/B]', 'mdblist_watchlist_remove'))
    else:
        options.append(('Add to [B][COLOR lightskyblue]MDB Watchlist[/COLOR][/B]', 'mdblist_watchlist_add'))
        
    options.append(('Add to [B][COLOR lightskyblue]My MDB Lists[/COLOR][/B]', 'mdblist_add_to_list'))
    options.append(('Remove from [B][COLOR lightskyblue]My MDB Lists[/COLOR][/B]', 'mdblist_remove_from_list'))

    dialog = xbmcgui.Dialog()
    ret = dialog.contextmenu([opt[0] for opt in options])

    if ret < 0:
        return

    action = options[ret][1]
    
    if action == 'mdblist_watchlist_add':
        if mdblist.watchlist_add(imdb_id=imdb_id, tmdb_id=tmdb_id, mediatype=content_type):
            xbmc.executebuiltin("Container.Refresh")
    elif action == 'mdblist_watchlist_remove':
        if mdblist.watchlist_remove(imdb_id=imdb_id, tmdb_id=tmdb_id, mediatype=content_type):
            xbmc.sleep(1000) # Pauză pt a permite API-ului să dea delete înainte de refresh UI
            xbmc.executebuiltin("Container.Refresh")
    elif action == 'mdblist_add_to_list':
        show_mdblist_add_to_list_dialog(tmdb_id, imdb_id, content_type, title)
    elif action == 'mdblist_remove_from_list':
        show_mdblist_remove_from_list_dialog(tmdb_id, imdb_id, content_type, title)


def show_mdblist_add_to_list_dialog(tmdb_id, imdb_id, content_type, title=''):
    import xbmcgui
    import xbmc
    import os
    from resources.lib.config import ADDON
    
    MDB_ICON = os.path.join(ADDON.getAddonInfo('path'), 'resources', 'media', 'mdblist.png')
    
    xbmc.executebuiltin('ActivateWindow(busydialognocancel)')
    from resources.lib import mdblist
    all_lists = mdblist.fetch_user_lists()
    xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
    
    if not all_lists:
        xbmcgui.Dialog().notification("[B][COLOR lightskyblue]MDBList[/COLOR][/B]", "You have no personal lists on the site.", MDB_ICON, 3000, False)
        return

    # --- FILTRARE LISTE STATICE ---
    static_lists = []
    for lst in all_lists:
        if lst.get('dynamic') is True or lst.get('is_dynamic') is True or lst.get('type') == 'dynamic':
            continue
        static_lists.append(lst)

    if not static_lists:
        xbmcgui.Dialog().notification("[B][COLOR lightskyblue]MDBList[/COLOR][/B]", "You have no STATIC lists to add to.", MDB_ICON, 3000, False)
        return

    display_items = []
    for lst in static_lists:
        name = lst.get('name', 'Unknown')
        count = lst.get('items', 0)
        display_items.append(f"[B][COLOR lightskyblue]{name}[/COLOR][/B] ({count} iteme)")

    dialog = xbmcgui.Dialog()
    ret = dialog.select("Add to [B][COLOR lightskyblue]MDBList[/COLOR][/B] List", display_items)

    if ret >= 0:
        selected_list = static_lists[ret]
        list_id = selected_list.get('id')
        if mdblist.list_add(list_id, imdb_id=imdb_id, tmdb_id=tmdb_id, mediatype=content_type):
            xbmcgui.Dialog().notification("[B][COLOR lightskyblue]MDBList[/COLOR][/B]", f"Added to [B][COLOR FF6AFB92]{selected_list.get('name')}[/COLOR][/B]", MDB_ICON, 3000, False)


def show_mdblist_remove_from_list_dialog(tmdb_id, imdb_id, content_type, title=''):
    import xbmcgui
    import xbmc
    import os
    from resources.lib.config import ADDON
    
    MDB_ICON = os.path.join(ADDON.getAddonInfo('path'), 'resources', 'media', 'mdblist.png')
    
    xbmc.executebuiltin('ActivateWindow(busydialognocancel)')
    from resources.lib import mdblist
    user_lists = mdblist.fetch_user_lists()
    
    if not user_lists:
        xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
        xbmcgui.Dialog().notification("[B][COLOR lightskyblue]MDBList[/COLOR][/B]", "You have no personal lists on the site.", MDB_ICON, 3000, False)
        return

    # --- FILTRARE LISTE STATICE ---
    static_lists = []
    for lst in user_lists:
        if lst.get('dynamic') is True or lst.get('is_dynamic') is True or lst.get('type') == 'dynamic':
            continue
        static_lists.append(lst)

    lists_with_item = []
    
    def check_worker(lst):
        list_id = lst.get('id')
        items, _ = mdblist.fetch_list_items(list_id, page=1, limit=1000)
        found = False
        if items:
            for item in items:
                item_tmdb = str(item.get('tmdbid') or item.get('tmdb_id') or item.get('show_tmdbid') or item.get('id', ''))
                if item_tmdb == str(tmdb_id):
                    found = True
                    break
        return lst if found else None
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(check_worker, lst) for lst in static_lists]
        for future in as_completed(futures):
            result = future.result()
            if result:
                lists_with_item.append(result)

    xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
    
    if not lists_with_item:
        xbmcgui.Dialog().notification("[B][COLOR lightskyblue]MDBList[/COLOR][/B]", "Title is NOT in any personal STATIC list.", MDB_ICON, 3000, False)
        return

    display_items = []
    for lst in lists_with_item:
        name = lst.get('name', 'Unknown')
        display_items.append(f"[B][COLOR lightskyblue]{name}[/COLOR][/B]")

    dialog = xbmcgui.Dialog()
    ret = dialog.select("Remove from [B][COLOR lightskyblue]MDBList[/COLOR][/B] List", display_items)

    if ret >= 0:
        selected_list = lists_with_item[ret]
        list_id = selected_list.get('id')
        if mdblist.list_remove(list_id, imdb_id=imdb_id, tmdb_id=tmdb_id, mediatype=content_type):
            xbmcgui.Dialog().notification("[B][COLOR lightskyblue]MDBList[/COLOR][/B]", f"Removed from [B][COLOR FF6AFB92]{selected_list.get('name')}[/COLOR][/B]", MDB_ICON, 3000, False)
            xbmc.sleep(1000)
            xbmc.executebuiltin("Container.Refresh")


def show_tmdb_add_to_list_dialog(tmdb_id, content_type):
    lists = trakt_sync.get_tmdb_custom_lists_from_db() 
    if not lists:
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "You have no lists", TMDB_ICON, 3000, False)
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
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Not in any list", TMDB_ICON, 3000, False)
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
            xbmcgui.Dialog().notification("[B][COLOR FFFF69B4]Favorites[/COLOR][/B]", "Already in favorites", TMDbmovies_ICON, 2000, False)
            return

    new_item = {
        'tmdb_id': tmdb_id,
        'title': title,
        'added': time.strftime('%Y-%m-%d %H:%M:%S')
    }

    favs[c_type].insert(0, new_item)
    write_json(FAVORITES_FILE, favs)
    
    # Curățăm RAM-ul pentru ca lista să se updateze imediat când intrăm în ea
    from resources.lib.cache import clear_all_fast_cache
    clear_all_fast_cache()
    
    xbmcgui.Dialog().notification("[B][COLOR FFFF69B4]Favorites[/COLOR][/B]", f"Added: [B][COLOR yellow]{title}[/COLOR][/B]", TMDbmovies_ICON, 2000, False)


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
        
        # Curățăm RAM-ul
        from resources.lib.cache import clear_all_fast_cache
        clear_all_fast_cache()
        
        xbmcgui.Dialog().notification("[B][COLOR FFFF69B4]Favorites[/COLOR][/B]", "Removed from favorites", TMDbmovies_ICON, 3000, False)
        xbmc.executebuiltin("Container.Refresh")


def list_favorites(content_type):
    favs = read_json(FAVORITES_FILE)
    
    if not favs or not isinstance(favs, dict):
        favs = {'movie': [], 'tv': []}
    
    items = favs.get(content_type, [])
    local_items = [f for f in items if f.get('added')]

    if not local_items:
        xbmcgui.Dialog().notification("[B][COLOR FFFF69B4]Favorites[/COLOR][/B]", "The list is empty", TMDbmovies_ICON, 3000, False)
        xbmcplugin.endOfDirectory(HANDLE)
        return

    # --- 1. FAST CACHE CHECK (RAM) ---
    # Includem și numărul de elemente în cheie pentru a invalida cache-ul când se adaugă/șterge ceva
    cache_key = f"local_favs_{content_type}_{len(local_items)}"
    cached_data = get_fast_cache(cache_key)
    if cached_data:
        render_from_fast_cache(cached_data)
        return
    # ---------------------------------

    # 2. PREFETCHING PARALEL PENTRU VITEZĂ MAXIMĂ
    # Construim o listă fake compatibilă cu prefetcher-ul
    fake_items_for_prefetch = [{'id': fav.get('tmdb_id'), 'media_type': content_type} for fav in local_items if fav.get('tmdb_id')]
    prefetch_metadata_parallel(fake_items_for_prefetch, content_type)

    # 3. PROCESARE ȘI BATCH ADD
    items_to_add = []
    cache_list = []
    
    for fav in local_items:
        tmdb_id = fav.get('tmdb_id')
        if not tmdb_id:
            continue

        endpoint = 'movie' if content_type == 'movie' else 'tv'
        
        # Citim direct din DB (Acum e instant datorită prefetcherului care a umplut DB-ul)
        data = trakt_sync.get_tmdb_item_details_from_db(tmdb_id, endpoint)
        
        # Fallback de siguranță
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
                processed = _process_movie_item(data, is_in_favorites_view=True, return_data=True)
            else:
                processed = _process_tv_item(data, is_in_favorites_view=True, return_data=True)
                
            if processed:
                items_to_add.append((processed['url'], processed['li'], processed['is_folder']))
                cache_list.append(processed)

    if items_to_add:
        xbmcplugin.addDirectoryItems(HANDLE, items_to_add, len(items_to_add))

    xbmcplugin.setContent(HANDLE, 'movies' if content_type == 'movie' else 'tvshows')
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=True)
    
    # 4. SALVĂM ÎN RAM PENTRU URMĂTOAREA DATĂ
    set_fast_cache(cache_key, [{
        'label': i['li'].getLabel() if 'li' in i else i['label'], 
        'url': i['url'], 
        'is_folder': i['is_folder'], 
        'art': i['art'], 
        'info': i['info'], 
        'cm': i['cm_items'], 
        'resume_time': i.get('resume_time', 0), 
        'total_time': i.get('total_time', 0)
    } for i in cache_list])

def show_details(tmdb_id, content_type):
    xbmcplugin.setContent(HANDLE, 'seasons')

    # Folosim Creierul Central care știe de limba RO/EN și se vindecă singur!
    data = get_tmdb_item_details(tmdb_id, 'tv')

    if not data:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    poster = f"{IMG_BASE}{data.get('poster_path', '')}" if data.get('poster_path') else ''
    backdrop = f"{BACKDROP_BASE}{data.get('backdrop_path', '')}" if data.get('backdrop_path') else ''
    tv_title = data.get('name', '')
    
    main_show_plot = data.get('overview', '')
    
    studio = ''
    if data.get('networks'):
        studio = data['networks'][0].get('name', '')
        
    show_mpaa = data.get('mpaa', '')
    raw_logo = data.get('clearlogo', '')
    show_logo = f"{IMG_BASE}{raw_logo}" if raw_logo and not raw_logo.startswith('http') else raw_logo
    show_rating = float(data.get('vote_average', 0.0))
    show_votes = int(data.get('vote_count', 0))

    from resources.lib import trakt_api
    import datetime
    today = datetime.date.today()

    for s in data.get('seasons', []):
        s_num = s['season_number']
        if s_num == 0:
            continue

        name = f"Season {s_num}"
        ep_count = s.get('episode_count', 0)
        
        # s_poster primește automat posterul RO din creierul central!
        s_poster = f"{IMG_BASE}{s.get('poster_path', '')}" if s.get('poster_path') else poster
        
        premiered = s.get('air_date', '')

        display_name = name
        if premiered:
            try:
                parts = str(premiered).split('-')
                if datetime.date(int(parts[0]), int(parts[1]), int(parts[2])) > today:
                    display_name = f"[B][COLOR FFE238EC]{name}[/COLOR] (Lansare: {premiered}[/B])"
            except: pass

        # Plot-ul sezonului vine deja tradus dacă setarea e pe RO
        season_plot = s.get('overview', '')
        if not season_plot:
            season_plot = main_show_plot

        watched_count = trakt_api.get_watched_counts(tmdb_id, 'season', s_num)
        watched_info = {'watched': watched_count, 'total': ep_count}
        
        s_rating = float(s.get('vote_average') or show_rating)

        info = {
            'mediatype': 'season',
            'title': name,
            'plot': season_plot,
            'tvshowtitle': tv_title,
            'season': s_num,
            'premiered': premiered,
            'studio': studio,
            'mpaa': show_mpaa,
            'rating': s_rating,
            'votes': show_votes
        }

        # --- NOU: Adăugăm Meniul Contextual (Mark Watched/Unwatched) pentru Sezoane ---
        cm =[]
        is_fully_watched = (watched_count >= ep_count) if ep_count > 0 else False
        
        watched_params = urlencode({'mode': 'mark_watched', 'tmdb_id': tmdb_id, 'type': 'season', 'season': s_num})
        unwatched_params = urlencode({'mode': 'mark_unwatched', 'tmdb_id': tmdb_id, 'type': 'season', 'season': s_num})

        if is_fully_watched:
            cm.append(('Mark as [B][COLOR FFE41B17]Unwatched[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{unwatched_params})"))
        else:
            cm.append(('Mark as [B][COLOR FFE41B17]Watched[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{watched_params})"))
            
        trakt_params = urlencode({'mode': 'trakt_context_menu', 'tmdb_id': tmdb_id, 'type': 'season', 'title': name, 'season': s_num})
        cm.append(('[B][COLOR pink]My Trakt[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{trakt_params})"))
        # -----------------------------------------------------------------------------

        # Trebuie să trimitem și uids={'tmdb': tmdb_id} pentru ca AF3 să lege Logo-ul de serial!
        add_directory(
            display_name,
            {'mode': 'episodes', 'tmdb_id': tmdb_id, 'season': str(s_num), 'tv_show_title': tv_title},
            thumb=s_poster, fanart=backdrop, clearlogo=show_logo, info=info, 
            uids={'tmdb': str(tmdb_id)}, watched_info=watched_info, cm=cm, folder=True
        )

    xbmcplugin.endOfDirectory(HANDLE)


def get_smart_season_details(tmdb_id, season_num):
    from resources.lib import trakt_sync
    from resources.lib.config import ADDON, SESSION, get_headers, BASE_URL, API_KEY, get_plot_language_code, LANG_TO_TMDB
    current_lang = get_plot_language_code()

    data = trakt_sync.get_tmdb_season_details_from_db(tmdb_id, season_num)
    
    if data:
        cached_lang = data.get('_cached_lang', 'en')
        if cached_lang == current_lang:
            return data
            
    url_en = f"{BASE_URL}/tv/{tmdb_id}/season/{season_num}?api_key={API_KEY}&language=en-US"
    
    try:
        res_en = SESSION.get(url_en, headers=get_headers(), timeout=5)
        if res_en.status_code == 200:
            data = res_en.json()
            data['_cached_lang'] = 'en'
            
            if current_lang != 'en':
                tmdb_lang = LANG_TO_TMDB.get(current_lang, 'en-US')
                url_target = f"{BASE_URL}/tv/{tmdb_id}/season/{season_num}?api_key={API_KEY}&language={tmdb_lang}&append_to_response=images&include_image_language={current_lang}"
                res_target = SESSION.get(url_target, headers=get_headers(), timeout=5)
                
                if res_target.status_code == 200:
                    data_target = res_target.json()
                    if data_target.get('overview'): data['overview'] = data_target['overview']
                    
                    target_posters = data_target.get('images', {}).get('posters',[])
                    if target_posters: data['poster_path'] = target_posters[0].get('file_path')
                        
                    target_eps = {ep['episode_number']: ep for ep in data_target.get('episodes',[])}
                    for ep in data.get('episodes',[]):
                        ep_num = ep['episode_number']
                        if ep_num in target_eps:
                            target_ep = target_eps[ep_num]
                            if target_ep.get('overview', '').strip(): ep['overview'] = target_ep['overview']
                            target_name = target_ep.get('name', '').strip()
                            if target_name and not (target_name.lower().startswith("episodul ") and target_name.split(" ")[-1].isdigit()):
                                ep['name'] = target_name
                            if target_ep.get('still_path'): ep['still_path'] = target_ep['still_path']
                    data['_cached_lang'] = current_lang

            conn = trakt_sync.get_connection()
            trakt_sync.set_tmdb_season_details_to_db(conn.cursor(), tmdb_id, season_num, data)
            conn.commit()
            conn.close()
            return data
    except: pass
    return None

def list_episodes(tmdb_id, season_num, tv_show_title):
    from resources.lib import trakt_sync
    from resources.lib import trakt_api
    xbmcplugin.setContent(HANDLE, 'episodes')

    data = get_smart_season_details(tmdb_id, season_num)

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
    
    show_mpaa = show_details.get('mpaa', '') if show_details else ''
    show_logo = show_details.get('clearlogo', '') if show_details else ''
    
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

    show_status = show_details.get('status', '') if show_details else ''
    total_seasons = show_details.get('number_of_seasons', 0) if show_details else 0
    total_eps_in_season = len(data.get('episodes',[])) if data else 0

    for ep in data.get('episodes', []):
        ep_num = ep['episode_number']
        original_ep_name = ep.get('name', '') or f'Episode {int(ep_num)}'
        
        # --- LOGICĂ NATIVĂ PREMIERE / FINALE PENTRU SKIN (Fără text vizibil) ---
        api_ep_type = ep.get('episode_type', '')
        ep_type = api_ep_type
        
        if int(ep_num) == 1:
            ep_type = 'series_premiere' if int(season_num) == 1 else 'season_premiere'
        elif total_eps_in_season > 0 and int(ep_num) == total_eps_in_season:
            if show_status in ['Ended', 'Canceled'] and int(season_num) == total_seasons:
                ep_type = 'series_finale'
            else:
                ep_type = 'season_finale'
        elif api_ep_type == 'mid_season':
            ep_type = 'mid_season_finale'
        # -----------------------------------------------------------------------
        
        name = f"{season_num}x{int(ep_num):02d} {original_ep_name}"
        
        # --- LOGICA CULOARE ROȘIE EPISOD (INJECTATĂ) ---
        display_label = name
        ep_air_date = ep.get('air_date', '')
        if ep_air_date:
            try:
                parts = str(ep_air_date).split('-')
                if datetime.date(int(parts[0]), int(parts[1]), int(parts[2])) > today:
                    display_label = f"[B][COLOR FFE238EC]{season_num}x{int(ep_num):02d} {original_ep_name}[/COLOR] (Lansare: {ep_air_date})[/B]"
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

# Imaginile și plotul sunt deja localizate automat de Dual-Fetch-ul de mai sus!
        # --- LOGICĂ NOUĂ IMAGINI EPISOD (Standard Modern) ---
        ep_still = ep.get('still_path', '')
        
        # Poster-ul vertical
        season_poster_path = data.get('poster_path', '') if data else ''
        if not season_poster_path and show_details: season_poster_path = show_details.get('poster_path', '')
        base_poster = f"{IMG_BASE}{season_poster_path}" if season_poster_path else icon
        
        # Fanart-ul serialului
        show_fanart_path = show_details.get('backdrop_path', '') if show_details else ''
        base_fanart = f"{BACKDROP_BASE}{show_fanart_path}" if show_fanart_path else base_poster
        
        try:
            art_pref = ADDON.getSetting('episodes_art')
        except:
            art_pref = '0'

        # 0 = Thumb + Fanart (Hibrid)
        # 1 = Thumb + Thumb
        # 2 = Poster + Fanart

        has_still = bool(ep_still)
        
        if art_pref == '3':
            # Poster + Thumb
            ep_icon = base_poster
            final_fanart = f"{IMG_BASE}{ep_still}" if has_still else base_fanart
        elif art_pref == '2':
            # Poster + Fanart
            ep_icon = base_poster
            final_fanart = base_fanart
        elif art_pref == '1':
            # Thumb + Thumb
            ep_icon = f"{IMG_BASE}{ep_still}" if has_still else base_poster
            final_fanart = f"{IMG_BASE}{ep_still}" if has_still else base_fanart
        else:
            # 0: Thumb + Fanart (Hibrid / Default)
            ep_icon = f"{IMG_BASE}{ep_still}" if has_still else base_poster
            final_fanart = base_fanart
        # ----------------------------------

        is_watched = trakt_api.check_episode_watched(tmdb_id, season_num, ep_num)
        
        try:
            duration = int(ep.get('runtime') or 0) * 60
        except:
            duration = 0
            
        # Dacă episodul nu are durată pe TMDb, luăm de la serial sau punem 45 min default
        if duration <= 0:
            try:
                runtimes = show_details.get('episode_run_time', []) if show_details else []
                duration = int(runtimes[0]) * 60 if runtimes and runtimes[0] else 2700
            except:
                duration = 2700

        if resume_seconds > 0 and duration > 0:
            resume_percent = (resume_seconds / duration) * 100

        ep_plot = ep.get('overview', '')

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
            'votes': ep.get('vote_count', 0),
            'mpaa': show_mpaa
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
        
        fav_params = urlencode({'mode': 'add_favorite', 'type': 'tv', 'tmdb_id': tmdb_id, 'title': tv_show_title})
        cm.append(('[B][COLOR yellow]Add TV Show to My Favorites[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{fav_params})"))

        clear_ep_params = urlencode({'mode': 'clear_sources_context', 'tmdb_id': tmdb_id, 'type': 'tv', 'season': str(season_num), 'episode': str(ep_num), 'title': f"{tv_show_title} S{season_num}E{ep_num}"})
        cm.append(('[B][COLOR orange]Clear sources cache[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{clear_ep_params})"))
        
        trakt_rate_params = urlencode({'mode': 'trakt_rating', 'tmdb_id': tmdb_id, 'type': 'episode', 'season': str(season_num), 'episode': str(ep_num)})
        cm.append(('Add [B][COLOR pink]Rating (Trakt)[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{trakt_rate_params})"))

        tmdb_rate_params = urlencode({'mode': 'tmdb_rating', 'tmdb_id': tmdb_id, 'type': 'episode', 'season': str(season_num), 'episode': str(ep_num)})
        cm.append(('Add [B][COLOR FF00CED1]Rating (TMDb)[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{tmdb_rate_params})"))
        
        if resume_percent > 0 and resume_percent < 90:
            rem_prog_params = urlencode({'mode': 'remove_progress', 'tmdb_id': tmdb_id, 'type': 'episode', 'season': str(season_num), 'episode': str(ep_num)})
            cm.append(('[B][COLOR red]Delete Resume[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{rem_prog_params})"))
        
        scrape_params = urlencode({'mode': 'sources', 'tmdb_id': tmdb_id, 'type': 'tv', 'title': tv_show_title, 'season': str(season_num), 'episode': str(ep_num), 'custom_title': '', 'custom_interactive': 'true'})
        cm.append(('[B]Scrape with Custom Values[/B]', f"RunPlugin({sys.argv[0]}?{scrape_params})"))

        url_params = {'mode': 'sources', 'tmdb_id': tmdb_id, 'type': 'tv', 'season': str(season_num), 'episode': str(ep_num), 'title': ep.get('name', ''), 'tv_show_title': tv_show_title}
        
        if resume_percent > 0 and resume_percent < 90 and duration > 0:
            resume_seconds = int((resume_percent / 100.0) * duration)
            url_params['resume_time'] = resume_seconds
        
        url = f"{sys.argv[0]}?{urlencode(url_params)}"
        
        li = xbmcgui.ListItem(display_label)
        
        try: skin_compat = ADDON.getSetting('skin_type')
        except: skin_compat = '0'
        
        art = {
            'thumb': ep_icon, 
            'icon': ep_icon, 
            'landscape': ep_icon,
            'tvshow.poster': base_poster, 
            'season.poster': base_poster, 
            'fanart': final_fanart
        }
        
        if skin_compat == '1':
            art['poster'] = base_poster  # AF3 (Afișează Poster Vertical 2:3)
        else:
            art['poster'] = ep_icon      # Estuary (Forțează Thumbnail 16:9)
            
        if show_logo:
            art['clearlogo'] = f"{IMG_BASE}{show_logo}" if not show_logo.startswith('http') else show_logo
            art['tvshow.clearlogo'] = f"{IMG_BASE}{show_logo}" if not show_logo.startswith('http') else show_logo
        li.setArt(art)
        
        li.setProperty('tmdb_id', tmdb_id)
        if ep_type:
            li.setProperty('episode_type', ep_type)
        set_metadata(li, info, unique_ids={'tmdb': tmdb_id, 'imdb': show_imdb_id}, watched_info=is_watched)
        set_resume_point(li, resume_seconds, duration)
        
        if cm: li.addContextMenuItems(cm)
        xbmcplugin.addDirectoryItem(HANDLE, url, li, isFolder=False)

    xbmcplugin.endOfDirectory(HANDLE)


def show_info_dialog(params):
    tmdb_id = params.get('tmdb_id')
    content_type = params.get('type')

    # Folosim direct creierul central care ne aduce din prima tot (inclusiv RO)
    data = get_tmdb_item_details(tmdb_id, content_type)
    if not data:
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Load error", xbmcgui.NOTIFICATION_ERROR)
        return

    title = data.get('title') or data.get('name', 'Unknown')
    li = xbmcgui.ListItem(title)

    plot = data.get('overview', '')
    tagline_text = data.get('tagline', '').strip()
    genres_str = ", ".join([g['name'] for g in data.get('genres',[])])
    
    try:
        from resources.lib.config import ADDON
        show_motto = ADDON.getSetting('show_motto_genre') != 'false'
    except: show_motto = True
    
    plot_header = ""
    if show_motto:
        if tagline_text and genres_str:
            plot_header = f"[B][COLOR yellow]{tagline_text}[/COLOR][/B] | [B][COLOR FF00CED1]{genres_str}[/COLOR][/B]\n"
        elif tagline_text:
            plot_header = f"[B][COLOR yellow]{tagline_text}[/COLOR][/B]\n"
        elif genres_str:
            plot_header = f"[B][COLOR FF00CED1]{genres_str}[/COLOR][/B]\n"
        
    plot = plot_header + plot
        
    poster_path = data.get('poster_path', '')
    backdrop_path = data.get('backdrop_path', '')

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
        tag.setPlot(plot) # <--- AICI ERA BUG-UL (era data.get('overview'))

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

        # --- 1. SETARE GENURI ȘI TAGLINE ---
        genres_str = ""
        colored_genres_list = []
        if data.get('genres'):
            genres_list = [g['name'] for g in data['genres']]
            colored_genres_list = [f"[B][COLOR cyan]{g}[/COLOR][/B]" for g in genres_list]
            genres_str = " • ".join(colored_genres_list)

        raw_tagline = data.get('tagline')
        tagline = raw_tagline.strip() if raw_tagline else ""

        # --- 2. TRUCURI PENTRU SKIN-UL KODI ---
        if content_type == 'movie':
            # La filme, Kodi știe să pună Genul în dreapta și Tagline-ul sub titlu
            if colored_genres_list:
                tag.setGenres(colored_genres_list)
                
            if tagline and genres_str:
                tag.setTagLine(f"[B][COLOR yellow]{tagline}[/COLOR][/B]   |   {genres_str}")
            elif tagline:
                tag.setTagLine(f"[B][COLOR yellow]{tagline}[/COLOR][/B]")
            elif genres_str:
                tag.setTagLine(f"{genres_str}")
        else:
            # PĂCĂLIM KODI LA SERIALE! 
            # Pentru că ignoră Tagline-ul, îl unim cu Genul (pe care știm că îl afișează sub titlu)
            final_tv_string = ""
            if tagline and genres_str:
                final_tv_string = f"[B][COLOR yellow]{tagline}[/COLOR][/B]   |   {genres_str}"
            elif tagline:
                final_tv_string = f"[B][COLOR yellow]{tagline}[/COLOR][/B]"
            elif genres_str:
                final_tv_string = genres_str
                
            if final_tv_string:
                # Trimitem totul ca un singur "Gen"
                tag.setGenres([final_tv_string])

        # --- FIX STATUS: Folosim "Studios" pentru a afisa Statusul in dreapta ---
        # Estuary afiseaza lista de Studiouri (Networks) sub Rating/An.
        studios_list = []
        
        # 1. Calculam Statusul și aplicăm CULORI DINAMICE
        if content_type in ['tv', 'tvshow'] and 'status' in data:
            st = data['status']
            status_text = ""
            
            if st == 'Returning Series': 
                status_text = "[COLOR cyan]Status: [B]Continuing[/COLOR][/B]" 
            elif st == 'Ended': 
                status_text = "[COLOR orange]Status: [B]Ended[/COLOR][/B]"
            elif st == 'Canceled': 
                status_text = "[COLOR red]Status: [B]Canceled[/COLOR][/B]"
            elif st == 'In Production': 
                status_text = "[B][COLOR yellow]Status: In Production[/COLOR][/B]"
            else:
                # Pentru orice alt status necunoscut
                status_text = f"[B][COLOR cyan]Status: {st}[/COLOR][/B]"
            
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

        try:
            if data.get('runtime'):
                tag.setDuration(int(data.get('runtime')) * 60)
        except:
            pass

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
    if poster_path: # <--- Folosim variabila localizată, nu data.get('poster_path')
        art['poster'] = f"{IMG_BASE}{poster_path}"
        art['thumb'] = f"{IMG_BASE}{poster_path}"
        art['icon'] = f"{IMG_BASE}{poster_path}"
    if backdrop_path:
        art['fanart'] = f"{BACKDROP_BASE}{backdrop_path}"
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
        xbmcgui.Dialog().notification("TMDb Info", "Could not identify title", xbmcgui.NOTIFICATION_WARNING, 3000)


def show_specific_info_dialog(tmdb_id, specific_type, season=1, episode=1):
    import xbmcgui
    
    show_data = None
    try:
        show_url = f"{BASE_URL}/tv/{tmdb_id}?api_key={API_KEY}&language={LANG}&include_video_language={VIDEO_LANGS}&append_to_response=videos"
        show_data = get_json(show_url)
    except:
        pass
    
    if specific_type == 'season':
        url_en = f"{BASE_URL}/tv/{tmdb_id}/season/{season}?api_key={API_KEY}&language=en-US&include_video_language={VIDEO_LANGS}&append_to_response=images,credits,videos"
    else:
        url_en = f"{BASE_URL}/tv/{tmdb_id}/season/{season}/episode/{episode}?api_key={API_KEY}&language=en-US&include_video_language={VIDEO_LANGS}&append_to_response=images,credits,videos"
        
    data = get_json(url_en)
    
    try:
        from resources.lib.config import ADDON, get_plot_language_code, LANG_TO_TMDB
        lang_code = get_plot_language_code()
        if lang_code != 'en' and data and data.get('success') != False:
            tmdb_lang = LANG_TO_TMDB.get(lang_code, 'en-US')
            url_target = url_en.replace('language=en-US', f'language={tmdb_lang}') + f"&include_image_language={lang_code}"
            data_target = get_json(url_target)
            
            if data_target:
                if data_target.get('overview'): 
                    data['overview'] = data_target['overview']
                
                if specific_type == 'episode' and data_target.get('name'):
                    target_name = data_target['name'].strip()
                    if not (target_name.lower().startswith("episodul ") and target_name.split(" ")[-1].isdigit()):
                        data['name'] = target_name
                
                imgs = data_target.get('images', {})
                target_posters = imgs.get('posters', []) or imgs.get('stills', [])
                if target_posters:
                    data['poster_path'] = target_posters[0].get('file_path')
                    data['still_path'] = target_posters[0].get('file_path')
                elif data_target.get('poster_path'):
                    data['poster_path'] = data_target.get('poster_path')
                elif data_target.get('still_path'):
                    data['still_path'] = data_target.get('still_path')
                    
                if show_data and not data.get('overview'):
                    show_loc_url = f"{BASE_URL}/tv/{tmdb_id}?api_key={API_KEY}&language={tmdb_lang}"
                    show_loc = get_json(show_loc_url)
                    if show_loc and show_loc.get('overview'):
                        show_data['overview'] = show_loc['overview']
    except Exception as e:
        log(f"[SPECIFIC-INFO] Error localization: {e}")

    if not data or data.get('success') == False:
        log(f"[SPECIFIC-INFO] Season/Episode not found (S{season}E{episode}), falling back to TV show info")
        if show_data:
            show_info_dialog({'tmdb_id': str(tmdb_id), 'type': 'tv'})
            return
        else:
            xbmcgui.Dialog().notification("TMDb Info", "Season/Episode does not exist", xbmcgui.NOTIFICATION_WARNING)
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
    page = int(params.get('page', '1')) # <--- ADĂUGAT: Preluăm pagina
    
    # 1. Dacă avem query în URL (redirect) - afișăm direct
    if query:
        from urllib.parse import unquote
        build_search_result(search_type, unquote(query), page) # <--- Trimitem pagina
        return
    
    # 2. Verificăm cache-ul pentru Container.Refresh
    cache_key = f'tmdb_search_{search_type}'
    cached_query = xbmcgui.Window(10000).getProperty(cache_key)
    
    # Detectăm dacă suntem deja pe pagina de rezultate (refresh)
    container_path = xbmc.getInfoLabel('Container.FolderPath')
    is_refresh = cached_query and 'perform_search' in container_path
    
    if is_refresh:
        # E un refresh - folosim query-ul din cache
        build_search_result(search_type, cached_query, page) # <--- Trimitem pagina
        return
    
    # 3. Căutare nouă - cerem input
    dialog = xbmcgui.Dialog()
    new_query = dialog.input("Search...", type=xbmcgui.INPUT_ALPHANUM)
    
    if new_query:
        add_search_to_history(new_query, search_type)
        # Salvăm în cache pentru refresh-uri viitoare
        xbmcgui.Window(10000).setProperty(cache_key, new_query)
        # Afișăm rezultatele direct
        build_search_result(search_type, new_query, 1) # <--- Aici e pagina 1 (căutare nouă)
    else:
        # Cancel
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)


def perform_search_query(params):
    """Execută direct o căutare din istoric."""
    search_type = params.get('type', 'multi')
    query = params.get('query', '')
    page = int(params.get('page', '1')) # <--- ADĂUGAT: Preluăm pagina
    
    if query:
        from urllib.parse import unquote
        query = unquote(query)
        add_search_to_history(query, search_type)
        # Salvăm în cache pentru refresh
        xbmcgui.Window(10000).setProperty(f'tmdb_search_{search_type}', query)
        build_search_result(search_type, query, page) # <--- Trimitem pagina
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
        next_li.setArt({'icon': NEXT_PAGE_ICON, 'thumb': NEXT_PAGE_ICON})
        items_to_add.append((next_url, next_li, True))
        cache_list.append({'label': next_label, 'url': next_url, 'is_folder': True, 'art': {'icon': NEXT_PAGE_ICON}, 'info': {'mediatype': 'video'}, 'cm_items': []})

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
        next_li.setArt({'icon': NEXT_PAGE_ICON, 'thumb': NEXT_PAGE_ICON})
        items_to_add.append((next_url, next_li, True))
        cache_list.append({'label': next_label, 'url': next_url, 'is_folder': True, 'art': {'icon': NEXT_PAGE_ICON}, 'info': {'mediatype': 'video'}, 'cm_items': []})

    if items_to_add:
        xbmcplugin.addDirectoryItems(HANDLE, items_to_add, len(items_to_add))

    xbmcplugin.setContent(HANDLE, 'movies' if menu_type == 'movie' else 'tvshows')
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=True)
    set_fast_cache(cache_key, [{'label': i['li'].getLabel() if 'li' in i else i['label'], 'url': i['url'], 'is_folder': i['is_folder'], 'art': i['art'], 'info': i['info'], 'cm': i['cm_items'], 'resume_time': 0, 'total_time': 0} for i in cache_list])


def tmdb_edit_list(params):
    list_id = params.get('list_id')
    xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Feature in development", TMDB_ICON, 3000, False)


def create_tmdb_list():
    session = get_tmdb_session()
    if not session:
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Not connected", xbmcgui.NOTIFICATION_WARNING)
        return None

    dialog = xbmcgui.Dialog()
    list_name = dialog.input("List name", type=xbmcgui.INPUT_ALPHANUM)
    if not list_name:
        return None

    description = dialog.input("Description (optional)", type=xbmcgui.INPUT_ALPHANUM)

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
            xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", f"List created: [B][COLOR yellow]{list_name}[/COLOR][/B]", TMDB_ICON, 3000, False)
            trakt_sync.sync_tmdb_only(silent=True) 
            xbmc.executebuiltin("Container.Refresh")
            return list_id
        else:
            xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Error creating list", xbmcgui.NOTIFICATION_ERROR)
    except Exception as e:
        log(f"[TMDB] Create List Error: {e}", xbmc.LOGERROR)
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Connection error", xbmcgui.NOTIFICATION_ERROR)

    return None


def delete_tmdb_list(list_id):
    session = get_tmdb_session()
    if not session:
        return False

    dialog = xbmcgui.Dialog()
    if not dialog.yesno("Confirm", "Are you sure you want to delete this list?"):
        return False

    url = f"{BASE_URL}/list/{list_id}?api_key={API_KEY}&session_id={session['session_id']}"

    try:
        r = requests.delete(url, timeout=10)
        if r.status_code in [200, 201, 204]:
            xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "List deleted", TMDB_ICON, 3000, False)
            trakt_sync.sync_tmdb_only(silent=True) 
            xbmc.executebuiltin("Container.Refresh")
            return True
    except:
        pass

    xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Delete error", xbmcgui.NOTIFICATION_ERROR)
    return False


def clear_tmdb_list(list_id):
    session = get_tmdb_session()
    if not session:
        return False

    dialog = xbmcgui.Dialog()
    if not dialog.yesno("Confirm", "Are you sure you want to clear this list?"):
        return False

    url = f"{BASE_URL}/list/{list_id}/clear?api_key={API_KEY}&session_id={session['session_id']}&confirm=true"

    try:
        r = requests.post(url, timeout=10)
        if r.status_code in [200, 201, 204]:
            xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "List cleared", TMDB_ICON, 3000, False)
            trakt_sync.sync_tmdb_only(silent=True) 
            xbmc.executebuiltin("Container.Refresh")
            return True
    except:
        pass

    return False


def rate_tmdb_item_silent(tmdb_id, content_type, rating_value, season=None, episode=None):
    session = get_tmdb_session()
    if not session: return False

    if content_type == 'episode' or (season and episode):
        url = f"{BASE_URL}/tv/{tmdb_id}/season/{season}/episode/{episode}/rating?api_key={API_KEY}&session_id={session['session_id']}"
    else:
        endpoint = 'movie' if content_type == 'movie' else 'tv'
        url = f"{BASE_URL}/{endpoint}/{tmdb_id}/rating?api_key={API_KEY}&session_id={session['session_id']}"

    try:
        r = requests.post(url, json={'value': float(rating_value)}, timeout=10)
        if r.status_code in [200, 201]:
            try:
                from resources.lib import trakt_sync
                conn = trakt_sync.get_connection()
                conn.execute("DELETE FROM tmdb_account_lists WHERE tmdb_id=? AND list_type='watchlist'", (str(tmdb_id),))
                conn.commit()
                conn.close()
                from resources.lib.cache import clear_all_fast_cache
                clear_all_fast_cache()
            except: pass
            return True
    except: pass
    return False

def rate_tmdb_item(tmdb_id, content_type, season=None, episode=None):
    session = get_tmdb_session()
    if not session:
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Not connected", xbmcgui.NOTIFICATION_WARNING)
        return False
    
    from resources.lib import trakt_api
    trakt_api._prompt_trakt_rating(tmdb_id, content_type, season, episode, "", service='tmdb')


def delete_tmdb_rating(tmdb_id, content_type):
    session = get_tmdb_session()
    if not session:
        return False

    endpoint = 'movie' if content_type == 'movie' else 'tv'
    url = f"{BASE_URL}/{endpoint}/{tmdb_id}/rating?api_key={API_KEY}&session_id={session['session_id']}"

    try:
        r = requests.delete(url, timeout=10)
        if r.status_code in [200, 201, 204]:
            xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Rating deleted", TMDB_ICON, 3000, False)
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
    
    from resources.lib.config import ADDON, SESSION, get_headers, get_plot_language_code, LANG_TO_TMDB
    current_lang = get_plot_language_code()
    
    from resources.lib import trakt_sync
    data = trakt_sync.get_tmdb_item_details_from_db(tmdb_id, content_type)
    
    if data:
        cached_lang = data.get('_cached_lang', 'en')
        if cached_lang == current_lang:
            return data
            
    url_en = f"{BASE_URL}/{endpoint}/{tmdb_id}?api_key={API_KEY}&language=en-US&append_to_response=credits,videos,external_ids,images,content_ratings,release_dates&include_image_language=en,null,xx"
    
    try:
        res_en = SESSION.get(url_en, headers=get_headers(), timeout=5)
        if res_en.status_code != 200: return None
        data = res_en.json()
        
        data['_cached_lang'] = 'en'
        
        mpaa = ''
        if content_type == 'tv' and 'content_ratings' in data:
            for r in data['content_ratings'].get('results', []):
                if r.get('iso_3166_1') == 'US':
                    mpaa = r.get('rating', '')
                    break
        elif content_type == 'movie' and 'release_dates' in data:
            for r in data['release_dates'].get('results', []):
                if r.get('iso_3166_1') == 'US':
                    for rd in r.get('release_dates', []):
                        if rd.get('certification'):
                            mpaa = rd.get('certification')
                            break
                    if mpaa: break
        if mpaa:
            data['mpaa'] = mpaa
        
        en_logos = [img for img in data.get('images', {}).get('logos', []) if img.get('file_path', '').lower().endswith('.png')]
        if en_logos:
            data['clearlogo'] = en_logos[0]['file_path']
        
        if current_lang != 'en':
            tmdb_lang = LANG_TO_TMDB.get(current_lang, 'en-US')
            url_target = f"{BASE_URL}/{endpoint}/{tmdb_id}?api_key={API_KEY}&language={tmdb_lang}&append_to_response=images&include_image_language={current_lang}"
            res_target = SESSION.get(url_target, headers=get_headers(), timeout=5)
            
            if res_target.status_code == 200:
                data_target = res_target.json()
                
                if data_target.get('overview'):
                    data['overview'] = data_target['overview']
                if data_target.get('tagline'):
                    data['tagline'] = data_target['tagline']
                
                target_imgs = data_target.get('images', {})
                
                target_logos = [l for l in target_imgs.get('logos', []) if l.get('file_path', '').lower().endswith('.png')]
                if target_logos: 
                    data['clearlogo'] = target_logos[0]['file_path']
                
                target_posters = target_imgs.get('posters', [])
                if target_posters:
                    data['poster_path'] = target_posters[0]['file_path']
                    
                target_backdrops = target_imgs.get('backdrops', [])
                if target_backdrops:
                    data['backdrop_path'] = target_backdrops[0]['file_path']
                    
                # NOTĂ IMPORTANTĂ: Nu am atins `data['title']` sau `data['name']`. Ele rămân EN!
                
                data['_cached_lang'] = current_lang
                                
        conn = trakt_sync.get_connection()
        trakt_sync.set_tmdb_item_details_to_db(conn.cursor(), tmdb_id, content_type, data)
        conn.commit()
        conn.close()
        return data
    except Exception as e:
        import xbmc
        xbmc.log(f"[TMDB] Fetch Error: {e}", xbmc.LOGERROR)
        return None

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
        xbmcgui.Dialog().notification("[B][COLOR FFFF69B4]Favorites[/COLOR][/B]", "No favorites to export", TMDbmovies_ICON, 2000, False)
        return

    dialog = xbmcgui.Dialog()
    path = dialog.browseSingle(3, "Choose export location", 'files', '.json')

    if path:
        export_file = os.path.join(path, 'tmdbmovies_favorites_backup.json')
        write_json(export_file, favs)
        xbmcgui.Dialog().notification("[B][COLOR FFFF69B4]Favorites[/COLOR][/B]", "Export complete!", TMDbmovies_ICON, 2000, False)


def import_local_favorites():
    dialog = xbmcgui.Dialog()
    path = dialog.browseSingle(1, "Select import file", 'files', '.json')

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
                xbmcgui.Dialog().notification("[B][COLOR FFFF69B4]Favorites[/COLOR][/B]", "Import complete!", TMDbmovies_ICON, 2000, False)
                xbmc.executebuiltin("Container.Refresh")
        except Exception as e:
            log(f"[IMPORT] Error: {e}", xbmc.LOGERROR)
            xbmcgui.Dialog().notification("[B][COLOR FFFF69B4]Favorites[/COLOR][/B]", "Import error", TMDbmovies_ICON, 2000, False)


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

def in_progress_movies(params):
    """Afișează filmele cu resume point + PLOT + METADATA COMPLETE."""
    from resources.lib import trakt_sync
    from resources.lib.config import PAGE_LIMIT
    
    try: icon = os.path.join(ADDON.getAddonInfo('path'), 'resources', 'media', 'player.png')
    except: icon = 'DefaultIcon.png'
    
    page = int(params.get('page', '1'))
    all_results = trakt_sync.get_in_progress_movies_from_db()
    
    if not all_results:
        add_directory("[COLOR cyan]No movies started. Sync Trakt.[/COLOR]", {'mode': 'trakt_sync_db'}, folder=False, icon='DefaultIconInfo.png')
        xbmcplugin.endOfDirectory(HANDLE)
        return
    
    results, total_pages = paginate_list(all_results, page, PAGE_LIMIT)
        
    for item in results:
        tmdb_id = str(item.get('id') or item.get('tmdb_id', ''))
        if not tmdb_id: continue

        title = item.get('title', 'Unknown')
        year = str(item.get('year', ''))
        
        details = get_tmdb_item_details(tmdb_id, 'movie')
        
        plot = item.get('overview', '')
        poster_path_api = ''
        backdrop_path_api = ''
        imdb_id = ''
        rating, votes, premiered, studio, duration = 0, 0, '', '', 0
        movie_mpaa = ''
        movie_logo = ''
        cast = []

        tagline = ''
        genres_str = ''
        if details:
            imdb_id = details.get('external_ids', {}).get('imdb_id', '')
            plot = details.get('overview', plot)
            tagline = details.get('tagline', '').strip()
            genres_str = ", ".join([g['name'] for g in details.get('genres',[])])
            poster_path_api = details.get('poster_path', '')
            rating = details.get('vote_average', 0.0)
            votes = details.get('vote_count', 0)
            premiered = details.get('release_date', '')
            
            raw_logo = details.get('clearlogo', '')
            movie_logo = f"{IMG_BASE}{raw_logo}" if raw_logo and not raw_logo.startswith('http') else raw_logo
            movie_mpaa = details.get('mpaa', '')
            
            if details.get('production_companies'):
                studio = [c['name'] for c in details['production_companies']]
                
            for p in details.get('credits', {}).get('cast', [])[:15]:
                if p.get('name'):
                    thumb = f"{IMG_BASE}{p['profile_path']}" if p.get('profile_path') else ''
                    cast.append({"name": p['name'], "role": p.get('character', ''), "thumbnail": thumb})
                    
            try:
                duration = int(details.get('runtime') or 0) * 60
            except:
                pass

        # <<-- MODIFICARE CHEIE: Interpretarea valorii din DB -->>
        progress_raw = float(item.get('progress', 0))
        resume_seconds = 0
        progress_percent = 0

        if progress_raw >= 1000000:
            # Este numărul magic, deci avem secunde exacte
            resume_seconds = int(progress_raw - 1000000)
            if duration > 0:
                progress_percent = (resume_seconds / duration) * 100
        elif 0 < progress_raw < 90:
            # Este un procentaj standard (ex: de la Trakt)
            progress_percent = progress_raw
            if duration > 0:
                resume_seconds = int((progress_percent / 100.0) * duration)
        # <<---------------------------------------------------->>

        poster = f"{IMG_BASE}{poster_path_api}" if poster_path_api else icon
        backdrop = f"{BACKDROP_BASE}{backdrop_path_api}" if backdrop_path_api else ''
        
        try: show_motto = ADDON.getSetting('show_motto_genre') != 'false'
        except: show_motto = True
        
        display_plot = f"[B][COLOR orange]Progress: {int(progress_percent)}%[/COLOR][/B]\n"
        if show_motto:
            if tagline and genres_str:
                display_plot += f"[B][COLOR yellow]{tagline}[/COLOR][/B] | [B][COLOR FF00CED1]{genres_str}[/COLOR][/B]\n"
            elif tagline:
                display_plot += f"[B][COLOR yellow]{tagline}[/COLOR][/B]\n"
            elif genres_str:
                display_plot += f"[B][COLOR FF00CED1]{genres_str}[/COLOR][/B]\n"
            
        display_plot += plot

        info = {
            'mediatype': 'movie', 'title': title, 'year': year, 'plot': display_plot,
            'resume_percent': progress_percent, 'rating': rating, 'votes': votes,
            'premiered': premiered, 'studio': studio, 'duration': duration,
            'mpaa': movie_mpaa, 'cast': cast, 'genre': genres_str
        }
        
        cm = _get_full_context_menu(tmdb_id, 'movie', title, imdb_id=imdb_id, year=year)
        cm.append(('[B][COLOR lime]Mark Watched[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?mode=mark_watched&tmdb_id={tmdb_id}&type=movie)"))

        url_params = {'mode': 'sources', 'tmdb_id': tmdb_id, 'type': 'movie', 'title': title, 'year': year}
        
        if resume_seconds > 0:
            url_params['resume_time'] = resume_seconds
        
        url = f"{sys.argv[0]}?{urlencode(url_params)}"
        li = xbmcgui.ListItem(f"{title} ({year})")
        
        art_dict = {'icon': poster, 'thumb': poster, 'poster': poster, 'fanart': backdrop}
        if movie_logo:
            art_dict['clearlogo'] = movie_logo
        li.setArt(art_dict)
        
        set_metadata(li, info, unique_ids={'tmdb': tmdb_id, 'imdb': imdb_id}, watched_info=False)
        
        set_resume_point(li, resume_seconds, duration)
        
        if cm:
            li.addContextMenuItems(cm)
        
        xbmcplugin.addDirectoryItem(HANDLE, url, li, isFolder=False)
    
    if page < total_pages:
        add_directory(
            f"[B]Next Page ({page+1}/{total_pages}) >>[/B]",
            {'mode': 'in_progress_movies', 'page': str(page + 1)},
            icon=NEXT_PAGE_ICON, folder=True
        )
        
    xbmcplugin.setContent(HANDLE, 'movies')
    xbmcplugin.endOfDirectory(HANDLE)


def in_progress_tvshows(params):
    """Afișează TOATE serialele în progres. Sursă unificată cu Up Next pentru sincronizare 100%."""
    from resources.lib import trakt_sync
    from concurrent.futures import ThreadPoolExecutor
    import datetime

    # === CITIM SETAREA ÎNAINTE DE CACHE ===
    try: show_future = ADDON.getSetting('upnext_show_future') == 'true'
    except: show_future = False

    # === 1. FAST CACHE CHECK (RAM) ===
    # Acum cheia conține și setarea. Dacă schimbi setarea, cache-ul se invalidează instant!
    cache_key = f"in_progress_tvshows_all_future_{show_future}"
    cached_data = get_fast_cache(cache_key)
    if cached_data:
        render_from_fast_cache(cached_data)
        return
    # ==================================

    try: icon = os.path.join(ADDON.getAddonInfo('path'), 'resources', 'media', 'in_progress_tvshow.png')
    except: icon = 'DefaultIcon.png'

    # Sursa de adevăr este acum EXACT aceeași ca la Up Next
    raw_items = trakt_sync.get_next_episodes_from_db()

    if not raw_items:
        add_directory("[COLOR cyan]No TV shows in progress. Sync Trakt.[/COLOR]",
                      {'mode': 'trakt_sync_db'}, folder=False, icon='DefaultIconInfo.png')
        xbmcplugin.endOfDirectory(HANDLE)
        return

    today = datetime.date.today()
    max_future_date = today + datetime.timedelta(days=7)

    # 2. FILTRARE STRICTĂ
    valid_shows = []
    for item in raw_items:
        tmdb_id = str(item['tmdb_id'])

        # Aplicăm regula 7 zile / TBA
        if not show_future:
            air_date_str = item.get('air_date', '')
            if not air_date_str:
                # Nu are dată de difuzare sau e TBA -> Ascundem
                continue
            try:
                parts = str(air_date_str).split('T')[0].split('-')
                air_date = datetime.date(int(parts[0]), int(parts[1]), int(parts[2]))
                if air_date > max_future_date:
                    # Apare peste mai mult de 7 zile -> Ascundem
                    continue 
            except:
                # Eșec parsare dată (probabil TBA) -> Ascundem
                continue
                
        valid_shows.append(item)

    if not valid_shows:
        add_directory("[COLOR cyan]All current shows are completed or appear in the future.[/COLOR]",
                      {'mode': 'noop'}, folder=False, icon='DefaultIconInfo.png')
        xbmcplugin.endOfDirectory(HANDLE)
        return

    # 3. PREFETCH METADATA
    prefetch_metadata_parallel([{'id': str(i['tmdb_id']), 'media_type': 'tv'} for i in valid_shows], 'tv')

    items_to_add = []
    cache_list = []

    try: show_motto = ADDON.getSetting('show_motto_genre') != 'false'
    except: show_motto = True

    # 4. CONSTRUIRE LISTĂ UI
    for item in valid_shows:
        tmdb_id = str(item['tmdb_id'])
        
        details = get_tmdb_item_details(tmdb_id, 'tv')
        if not details:
            continue

        # Calculăm rapid episoadele din SQL / TMDB
        watched_info_db = get_watched_status_tvshow(tmdb_id)
        curr_watched = int(watched_info_db.get('watched', 0))
        curr_total = int(watched_info_db.get('total', 0))
        
        if curr_total == 0:
            curr_total = details.get('number_of_episodes', 0)
            if curr_total > 0:
                trakt_sync.set_tv_meta_to_db(tmdb_id, curr_total)

        # --- Extragem datele ---
        name       = details.get('name', item.get('show_title', 'Unknown'))
        year       = str(details.get('first_air_date', ''))[:4]
        plot       = details.get('overview', '')
        imdb_id    = details.get('external_ids', {}).get('imdb_id', '')
        tagline    = details.get('tagline', '').strip()
        genres_str = ", ".join([g['name'] for g in details.get('genres', [])])
        poster_path = details.get('poster_path', '')
        poster      = f"{IMG_BASE}{poster_path}" if poster_path else icon
        backdrop    = f"{BACKDROP_BASE}{details.get('backdrop_path', '')}" if details.get('backdrop_path') else ''
        raw_logo    = details.get('clearlogo', '')
        clearlogo   = f"{IMG_BASE}{raw_logo}" if raw_logo and not raw_logo.startswith('http') else raw_logo

        cast = []
        for p in details.get('credits', {}).get('cast', [])[:15]:
            if p.get('name'):
                thumb = f"{IMG_BASE}{p['profile_path']}" if p.get('profile_path') else ''
                cast.append({"name": p['name'], "role": p.get('character', ''), "thumbnail": thumb})

        duration = 0
        try:
            runtimes = details.get('episode_run_time', [])
            if runtimes and runtimes[0]: duration = int(runtimes[0]) * 60
        except: pass

        # --- Progress display ---
        display_total = str(curr_total) if curr_total > 0 else "?"
        progress_pct  = int((curr_watched / curr_total) * 100) if curr_total > 0 else 0
        if progress_pct > 100: progress_pct = 100

        display_plot = f"[B][COLOR orange]Watched: {curr_watched}/{display_total} ({progress_pct}%)[/COLOR][/B]\n"
        if show_motto:
            if tagline and genres_str:
                display_plot += f"[B][COLOR yellow]{tagline}[/COLOR][/B] | [B][COLOR FF00CED1]{genres_str}[/COLOR][/B]\n"
            elif tagline:
                display_plot += f"[B][COLOR yellow]{tagline}[/COLOR][/B]\n"
            elif genres_str:
                display_plot += f"[B][COLOR FF00CED1]{genres_str}[/COLOR][/B]\n"
        display_plot += plot

        info = {
            'mediatype'  : 'tvshow',
            'title'      : name,
            'year'       : year,
            'plot'       : display_plot,
            'tvshowtitle': name,
            'rating'     : details.get('vote_average', 0.0),
            'votes'      : details.get('vote_count', 0),
            'premiered'  : details.get('first_air_date', ''),
            'studio'     : details.get('networks', [{}])[0].get('name', '') if details.get('networks') else '',
            'duration'   : duration,
            'mpaa'       : details.get('mpaa', ''),
            'cast'       : cast,
            'genre'      : genres_str,
        }
        art = {
            'icon'  : poster, 'thumb' : poster, 'poster' : poster,
            'fanart': backdrop,
        }
        if clearlogo: art['clearlogo'] = clearlogo

        watched_info_dict = {'watched': curr_watched, 'total': curr_total}
        cm  = _get_full_context_menu(tmdb_id, 'tv', name, year=year, imdb_id=imdb_id)
        url_params = {'mode': 'details', 'tmdb_id': tmdb_id, 'type': 'tv', 'title': name}
        url = f"{sys.argv[0]}?{urlencode(url_params)}"

        label = f"{name} ({year})" if year else name
        
        # Colorare logică (Afișăm complet verde doar dacă nu se supune regulii Up Next de viitor)
        if curr_total > 0 and curr_watched >= curr_total:
            label += f" [B][COLOR lime](Complet)[/COLOR][/B]"
        else:
            label += f" [B][COLOR FF6AFB92]({curr_watched}/{display_total})[/COLOR][/B]"

        li = xbmcgui.ListItem(label)
        li.setArt(art)
        set_metadata(li, info, unique_ids={'tmdb': tmdb_id, 'imdb': imdb_id}, watched_info=watched_info_dict)
        if cm: li.addContextMenuItems(cm)

        items_to_add.append((url, li, True))
        cache_list.append({
            'label'      : label,
            'url'        : url,
            'is_folder'  : True,
            'art'        : art,
            'info'       : info,
            'cm'         : cm,
            'resume_time': 0,
            'total_time' : 0,
        })

    if items_to_add:
        xbmcplugin.addDirectoryItems(HANDLE, items_to_add, len(items_to_add))
    
    xbmcplugin.setContent(HANDLE, 'tvshows')
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=True)

    set_fast_cache(cache_key, cache_list)


def in_progress_episodes(params):
    """Afișează episoadele cu PLOT și METADATA COMPLETE (fără paginare)."""
    from resources.lib import trakt_sync
    from concurrent.futures import ThreadPoolExecutor
    
    cache_key = "in_progress_episodes_all"
    cached_data = get_fast_cache(cache_key)
    if cached_data:
        render_from_fast_cache(cached_data)
        return
    
    try: icon = os.path.join(ADDON.getAddonInfo('path'), 'resources', 'media', 'player.png')
    except: icon = 'DefaultIcon.png'
    
    all_results = trakt_sync.get_in_progress_episodes_from_db()
    
    if not all_results:
        add_directory("[COLOR cyan]No episodes paused midway. Sync Trakt.[/COLOR]", {'mode': 'trakt_sync_db'}, folder=False, icon='DefaultIconInfo.png')
        xbmcplugin.endOfDirectory(HANDLE)
        return
    
    # 1. Trage detaliile serialelor în paralel
    prefetch_metadata_parallel(all_results, 'tv')
    
    # 2. Trage detaliile sezoanelor în paralel
    def _prefetch_in_progress_season_worker(it):
        if not xbmc.Monitor().abortRequested():
            t_id = str(it.get('id') or it.get('tmdb_id', ''))
            s_num = int(it.get('season', 0))
            if t_id and s_num:
                get_smart_season_details(t_id, s_num)

    with ThreadPoolExecutor(max_workers=15) as executor:
        list(executor.map(_prefetch_in_progress_season_worker, all_results))

    items_to_add = []
    cache_list = []

    for item in all_results:
        tmdb_id = str(item.get('id') or item.get('tmdb_id', ''))
        if not tmdb_id: continue

        season = int(item.get('season', 0))
        episode = int(item.get('episode', 0))
        
        ep_plot = ''
        rating, votes, premiered, duration = 0.0, 0, '', 0
        
        show_details = get_tmdb_item_details(tmdb_id, 'tv')
        show_name = show_details.get('name', 'Unknown Show') if show_details else 'Unknown Show'
        
        show_imdb_id = ''
        show_mpaa = ''
        show_logo = ''
        studio = ''
        
        if show_details:
            show_mpaa = show_details.get('mpaa', '')
            raw_logo = show_details.get('clearlogo', '')
            show_logo = f"{IMG_BASE}{raw_logo}" if raw_logo and not raw_logo.startswith('http') else raw_logo
            if show_details.get('networks'): studio = [n['name'] for n in show_details['networks']]
            show_imdb_id = show_details.get('external_ids', {}).get('imdb_id', '')

        db_title = item.get('title') or item.get('name', f'Episode {episode}')
        ep_name = db_title.split(' - ')[-1].strip() if ' - ' in db_title else db_title
        
        season_data = get_smart_season_details(tmdb_id, season)
        
        ep_still = ''
        ep_type = ''
        if season_data:
            total_eps_in_season = len(season_data.get('episodes',[]))
            show_status = show_details.get('status', '') if show_details else ''
            total_seasons = show_details.get('number_of_seasons', 0) if show_details else 0
            
            for ep in season_data.get('episodes',[]):
                if ep.get('episode_number') == episode:
                    if ep.get('overview'): ep_plot = ep.get('overview')
                    if ep.get('still_path'): ep_still = ep.get('still_path')
                    if ep.get('name'): ep_name = ep.get('name')
                    rating = float(ep.get('vote_average', 0))
                    votes = int(ep.get('vote_count', 0))
                    premiered = ep.get('air_date', '')
                    try:
                        duration = int(ep.get('runtime') or 0) * 60
                    except:
                        duration = 0
                        
                    if duration <= 0:
                        try:
                            runtimes = show_details.get('episode_run_time', []) if show_details else []
                            duration = int(runtimes[0]) * 60 if runtimes and runtimes[0] else 2700
                        except:
                            duration = 2700
                    
                    api_ep_type = ep.get('episode_type', '')
                    ep_type = api_ep_type
                    if episode == 1:
                        ep_type = 'series_premiere' if season == 1 else 'season_premiere'
                    elif total_eps_in_season > 0 and episode == total_eps_in_season:
                        if show_status in ['Ended', 'Canceled'] and season == total_seasons:
                            ep_type = 'series_finale'
                        else:
                            ep_type = 'season_finale'
                    elif api_ep_type == 'mid_season':
                        ep_type = 'mid_season_finale'
                        
                    break
        
        progress_raw = float(item.get('progress', 0))
        resume_seconds = 0
        progress_percent = 0

        if progress_raw >= 1000000:
            resume_seconds = int(progress_raw - 1000000)
            if duration > 0:
                progress_percent = (resume_seconds / duration) * 100
        elif 0 < progress_raw < 90:
            progress_percent = progress_raw
            if duration > 0:
                resume_seconds = int((progress_percent / 100.0) * duration)
            
        try: art_pref = ADDON.getSetting('episodes_art')
        except: art_pref = '0'

        season_poster_path = season_data.get('poster_path', '') if season_data else ''
        if not season_poster_path and show_details: season_poster_path = show_details.get('poster_path', '')
        base_poster = f"{IMG_BASE}{season_poster_path}" if season_poster_path else icon
        
        show_fanart_path = show_details.get('backdrop_path', '') if show_details else ''
        base_fanart = f"{BACKDROP_BASE}{show_fanart_path}" if show_fanart_path else base_poster

        has_still = bool(ep_still)
        if art_pref == '3':
            ep_icon = base_poster
            final_fanart = f"{IMG_BASE}{ep_still}" if has_still else base_fanart
        elif art_pref == '2':
            ep_icon = base_poster
            final_fanart = base_fanart
        elif art_pref == '1':
            ep_icon = f"{IMG_BASE}{ep_still}" if has_still else base_poster
            final_fanart = f"{IMG_BASE}{ep_still}" if has_still else base_fanart
        else:
            ep_icon = f"{IMG_BASE}{ep_still}" if has_still else base_poster
            final_fanart = base_fanart
        
        show_watched_info = get_watched_status_tvshow(tmdb_id)
        unwatched_count = 0
        if show_watched_info['total'] > 0:
            unwatched_count = max(0, show_watched_info['total'] - show_watched_info['watched'])

        try: skin_compat = ADDON.getSetting('skin_type')
        except: skin_compat = '0'

        display_label = f"[B][COLOR FF00CED1]{show_name}[/COLOR][/B] - [B][COLOR FFCCCCCC]S{season:02d}E{episode:02d}[/COLOR][/B] - [B][COLOR FFCCCCFF][I]{ep_name}[/I][/COLOR][/B]"
        
        if skin_compat == '0' and unwatched_count > 0:
            display_label += f" [COLOR orange] ({unwatched_count})[/COLOR]"

        display_plot = f"[B][COLOR orange]Progress: {int(progress_percent)}%[/COLOR][/B]\n{ep_plot}"

        info = {
            'mediatype': 'episode', 'title': ep_name,
            'plot': display_plot,
            'tvshowtitle': show_name, 'season': season, 'episode': episode,
            'resume_percent': progress_percent, 'rating': rating, 'votes': votes, 'premiered': premiered,
            'duration': duration, 'studio': studio, 'mpaa': show_mpaa
        }
        
        cm = [
            ('[B][COLOR lime]Mark Watched[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?mode=mark_watched&tmdb_id={tmdb_id}&type=episode&season={season}&episode={episode})"),
            ('[B]Scrape with Custom Values[/B]', f"RunPlugin({sys.argv[0]}?mode=sources&tmdb_id={tmdb_id}&type=tv&title={quote_plus(show_name)}&season={season}&episode={episode}&custom_interactive=true)"),
            ('[B][COLOR red]Delete Resume[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?mode=remove_progress&tmdb_id={tmdb_id}&type=episode&season={season}&episode={episode})")
        ]
        
        b_show_params = urlencode({'mode': 'details', 'tmdb_id': tmdb_id, 'type': 'tv', 'title': show_name})
        cm.append(('[B][COLOR cyan]Browse Show[/COLOR][/B]', f"Container.Update({sys.argv[0]}?{b_show_params})"))
        
        b_season_params = urlencode({'mode': 'episodes', 'tmdb_id': tmdb_id, 'season': str(season), 'tv_show_title': show_name})
        cm.append(('[B][COLOR cyan]Browse Season[/COLOR][/B]', f"Container.Update({sys.argv[0]}?{b_season_params})"))
        
        plays_params = {
            'mode': 'show_my_plays_menu', 'tmdb_id': tmdb_id, 'type': 'episode',
            'title': show_name, 'ep_name': ep_name, 'premiered': premiered,
            'season': season, 'episode': episode, 'imdb_id': show_imdb_id
        }
        cm.append(('[B][COLOR FFFDBD01]My Plays[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{urlencode(plays_params)})"))
        
        clear_p_params = urlencode({'mode': 'clear_sources_context', 'tmdb_id': tmdb_id, 'type': 'tv', 'season': str(season), 'episode': str(episode), 'title': f"{show_name} S{season:02d}E{episode:02d}"})
        cm.append(('[B][COLOR orange]Clear sources cache[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{clear_p_params})"))
        
        url_params = {'mode': 'sources', 'tmdb_id': tmdb_id, 'type': 'tv', 'season': str(season), 'episode': str(episode), 'title': ep_name, 'tv_show_title': show_name}
        
        if resume_seconds > 0:
            url_params['resume_time'] = resume_seconds
        
        url = f"{sys.argv[0]}?{urlencode(url_params)}"
        
        li = xbmcgui.ListItem(display_label)
        
        try: skin_compat = ADDON.getSetting('skin_type')
        except: skin_compat = '0'
        
        art_dict = {
            'thumb': ep_icon, 
            'icon': ep_icon, 
            'landscape': ep_icon,
            'tvshow.poster': base_poster, 
            'season.poster': base_poster, 
            'fanart': final_fanart
        }
        
        if skin_compat == '1':
            art_dict['poster'] = base_poster
        else:
            art_dict['poster'] = ep_icon
            
        if show_logo: art_dict['clearlogo'] = show_logo
        li.setArt(art_dict)
        
        li.setProperty('tmdb_id', tmdb_id)
        if ep_type:
            li.setProperty('episode_type', ep_type)
            
        set_metadata(li, info, unique_ids={'tmdb': str(tmdb_id), 'imdb': show_imdb_id}, watched_info=show_watched_info)
        set_resume_point(li, resume_seconds, duration)
        
        if cm: li.addContextMenuItems(cm)
        
        items_to_add.append((url, li, False))
        
        cache_list.append({
            'label': display_label,
            'url': url,
            'is_folder': False,
            'art': art_dict,
            'info': info,
            'cm': cm,
            'resume_time': resume_seconds,
            'total_time': duration
        })
        
    if items_to_add:
        xbmcplugin.addDirectoryItems(HANDLE, items_to_add, len(items_to_add))
        
    xbmcplugin.setContent(HANDLE, 'episodes')
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=True)
    
    set_fast_cache(cache_key, cache_list)


def get_next_episodes(params=None):
    """Afișează Next Episodes (Up Next) cu sortare avansată și filtrare 'dropped'."""
    from resources.lib import trakt_sync
    import datetime

    # 1. OBȚINEREA DATELOR BRUTE DIN BAZA DE DATE LOCALĂ
    raw_items = trakt_sync.get_next_episodes_from_db()
    
    today = datetime.date.today()
    max_future_date = today + datetime.timedelta(days=7)

    # 2. CITIREA SETĂRILOR DIN settings.xml
    try:
        show_future = ADDON.getSetting('upnext_show_future') == 'true'
    except:
        show_future = False
        
    # 3. FILTRAREA SERIALELOR ABANDONATE (DROPPED/HIDDEN) - LOGICĂ NOUĂ
    try:
        conn = trakt_sync.get_connection()
        c = conn.cursor()
        c.execute("SELECT tmdb_id FROM trakt_hidden_shows")
        hidden_tmdb_ids = {row['tmdb_id'] for row in c.fetchall()}
        conn.close()
        
        if hidden_tmdb_ids:
            initial_count = len(raw_items)
            raw_items = [item for item in raw_items if str(item.get('tmdb_id')) not in hidden_tmdb_ids]
            removed_count = initial_count - len(raw_items)
            if removed_count > 0:
                log(f"[UP NEXT] Filtered out {removed_count} dropped/hidden shows.")
    except Exception as e:
        log(f"[UP NEXT] Error filtering hidden shows: {e}", xbmc.LOGERROR)
    
    # 4. SEPARAREA EPISOADELOR PE CATEGORII
    available_now = []
    upcoming_soon = []
    later = []
    tba = []

    for item in raw_items:
        air_date_str = item.get('air_date', '')
        
        if not air_date_str:
            if show_future: 
                tba.append(item)
            continue
            
        try:
            parts = str(air_date_str).split('T')[0].split('-')
            air_date = datetime.date(int(parts[0]), int(parts[1]), int(parts[2]))
        except:
            if show_future: 
                tba.append(item)
            continue
        
        # Aplicăm filtrele de dată, inclusiv cel de 7 zile
        if air_date <= today:
            available_now.append(item)
        elif today < air_date <= max_future_date:
            upcoming_soon.append(item)
        else: # Mai mult de 7 zile în viitor
            if show_future: 
                later.append(item)
            
    # 5. SORTAREA INTELIGENTĂ (REPARATĂ ȘI MAI ROBUSTĂ)
    # Helper pentru a asigura un timestamp valid la sortare
    def get_last_watched_ts(x):
        lw = x.get('last_watched_at')
        if not lw: 
            return 1
            
        try:
            d_str = str(lw).replace('Z', '').split('.')[0]
            date_part, time_part = d_str.split('T')
            y, m, d = map(int, date_part.split('-'))
            H, M, S = map(int, time_part.split(':'))
            return datetime.datetime(y, m, d, H, M, S).timestamp()
        except:
            try:
                d_str = str(lw).split('T')[0]
                y, m, d = map(int, d_str.split('-'))
                return datetime.datetime(y, m, d, 0, 0, 0).timestamp()
            except:
                return 1

    # A. Disponibile acum: sortate descrescător după ultima vizionare EXACTĂ
    available_now.sort(key=get_last_watched_ts, reverse=True)
    
    # B. Următoarele 7 zile: sortate cronologic (cel mai apropiat primul)
    upcoming_soon.sort(key=lambda x: x.get('air_date', ''))
    
    # C. Celelalte liste (dacă sunt active)
    if show_future:
        # Peste 7 zile: sortate cronologic după data lansării
        later.sort(key=lambda x: x.get('air_date', ''))
        # TBA: sortate alfabetic după numele serialului
        tba.sort(key=lambda x: x.get('show_title', ''))
        # Combinăm listele strict în această ordine
        items = available_now + upcoming_soon + later + tba
    else:
        # Dacă setarea e OFF, ignorăm complet later și tba
        items = available_now + upcoming_soon

    # 6. CONSTRUIREA LISTEI FINALE
    if not items:
        add_directory("[COLOR gray]No new episodes (Run 'Trakt Sync')[/COLOR]", {'mode': 'trakt_sync_db'}, folder=False)
        xbmcplugin.endOfDirectory(HANDLE)
        return

    # Prefetch-ul rămâne pentru viteză (Trage detaliile serialelor în paralel)
    prefetch_metadata_parallel(items, 'tv')

    # =========================================================================
    # FIX VITEZĂ UP NEXT: Multithreading pentru detaliile Sezoanelor!
    # Tragem toate sezoanele simultan în loc de unul câte unul.
    # =========================================================================
    def _prefetch_season_worker(it):
        if not xbmc.Monitor().abortRequested():
            # Apelează funcția existentă care face cererea API și o salvează în SQL
            get_smart_season_details(str(it['tmdb_id']), it['season'])

    # Lansăm 10 fire de execuție pentru a descărca zeci de sezoane în 1-2 secunde
    with ThreadPoolExecutor(max_workers=10) as executor:
        list(executor.map(_prefetch_season_worker, items))
    # =========================================================================

    for it in items:
        tmdb_id = it['tmdb_id']
        
        # --- ÎNCEPUT NOU: CALCUL EPISOADE RĂMASE (AF3 / ESTUARY) ---
        show_watched_info = get_watched_status_tvshow(tmdb_id)
        unwatched_count = 0
        if show_watched_info['total'] > 0:
            unwatched_count = max(0, show_watched_info['total'] - show_watched_info['watched'])
        # --- SFÂRȘIT NOU ---
        
        # 1. Extragem datele complete și garantat RO/EN (Aici se întâmplă magia Clearlogo!)
        show_details = get_tmdb_item_details(tmdb_id, 'tv')
        imdb_id = show_details.get('external_ids', {}).get('imdb_id', '') if show_details else ''
        
        # 2. Extragem absolut tot ce vrea Kodi (Clearlogo, MPAA, Studio)
        raw_logo = show_details.get('clearlogo', '') if show_details else ''
        show_logo = f"{IMG_BASE}{raw_logo}" if raw_logo and not raw_logo.startswith('http') else raw_logo
        
        show_mpaa = show_details.get('mpaa', '') if show_details else ''
        studio = ''
        if show_details and show_details.get('networks'):
            studio = show_details['networks'][0].get('name', '')

        # 3. Metadate implicite episod (de la Trakt)
        ep_plot = it['overview']
        ep_still = ''
        rating = 0.0
        votes = 0
        duration = 0
        
        # 4. Găsim episodul în baza noastră TMDb pentru a lua Durata, Steluțele (Rating) și Voturile!
        season_data = get_smart_season_details(tmdb_id, it['season'])
        ep_type = ''
        if season_data:
            total_eps_in_season = len(season_data.get('episodes',[]))
            show_status = show_details.get('status', '') if show_details else ''
            total_seasons = show_details.get('number_of_seasons', 0) if show_details else 0
            
            for ep in season_data.get('episodes',[]):
                if ep.get('episode_number') == it['episode']:
                    if ep.get('overview'): ep_plot = ep.get('overview')
                    if ep.get('still_path'): ep_still = ep.get('still_path')
                    # Adăugăm metadatele esențiale pentru AF3
                    rating = ep.get('vote_average', 0.0)
                    votes = ep.get('vote_count', 0)
                    try:
                        duration = int(ep.get('runtime') or 0) * 60
                    except:
                        duration = 0
                        
                    if duration <= 0:
                        try:
                            runtimes = show_details.get('episode_run_time', []) if show_details else []
                            duration = int(runtimes[0]) * 60 if runtimes and runtimes[0] else 2700
                        except:
                            duration = 2700
                    
                    api_ep_type = ep.get('episode_type', '')
                    ep_type = api_ep_type
                    if it['episode'] == 1:
                        ep_type = 'series_premiere' if it['season'] == 1 else 'season_premiere'
                    elif total_eps_in_season > 0 and it['episode'] == total_eps_in_season:
                        if show_status in['Ended', 'Canceled'] and it['season'] == total_seasons:
                            ep_type = 'series_finale'
                        else:
                            ep_type = 'season_finale'
                    elif api_ep_type == 'mid_season':
                        ep_type = 'mid_season_finale'
                        
                    break
                    
        # --- LOGICĂ NOUĂ IMAGINI UP NEXT (Standard Modern) ---
        season_poster_path = ''
        if season_data: season_poster_path = season_data.get('poster_path', '')
        if not season_poster_path and show_details: season_poster_path = show_details.get('poster_path', '')
        base_poster = f"{IMG_BASE}{season_poster_path}" if season_poster_path else (it.get('poster') or TRAKT_ICON)
        
        show_fanart_path = show_details.get('backdrop_path', '') if show_details else ''
        base_fanart = f"{BACKDROP_BASE}{show_fanart_path}" if show_fanart_path else base_poster

        try:
            art_pref = ADDON.getSetting('episodes_art')
        except:
            art_pref = '0'

        has_still = bool(ep_still)
        
        if art_pref == '3':
            # Poster + Thumb
            ep_icon = base_poster
            final_fanart = f"{IMG_BASE}{ep_still}" if has_still else base_fanart
        elif art_pref == '2':
            # Poster + Fanart
            ep_icon = base_poster
            final_fanart = base_fanart
        elif art_pref == '1':
            # Thumb + Thumb
            ep_icon = f"{IMG_BASE}{ep_still}" if has_still else base_poster
            final_fanart = f"{IMG_BASE}{ep_still}" if has_still else base_fanart
        else:
            # 0: Thumb + Fanart (Hibrid)
            ep_icon = f"{IMG_BASE}{ep_still}" if has_still else base_poster
            final_fanart = base_fanart
        # ----------------------------------
        
        # --- START MODIFICARE: CALCUL RESUME PENTRU UP NEXT ---
        from resources.lib import trakt_sync
        progress_value = trakt_sync.get_local_playback_progress(tmdb_id, 'tv', it['season'], it['episode'])
        resume_percent = 0
        resume_seconds = 0
        
        if progress_value >= 1000000:
            resume_seconds = int(progress_value - 1000000)
            if duration > 0:
                resume_percent = (resume_seconds / duration) * 100
        elif 0 < progress_value < 90:
            resume_percent = progress_value
            if duration > 0:
                resume_seconds = int((resume_percent / 100.0) * duration)
        # --- SFÂRȘIT MODIFICARE ---

        # 5. Dăm dicționarului info absolut tot (Acum Kodi știe durata și steluțele)
        info = {
            'mediatype': 'episode', 
            'title': it['ep_title'], 
            'tvshowtitle': it['show_title'], 
            'season': it['season'], 
            'episode': it['episode'], 
            'plot': ep_plot, 
            'premiered': it['air_date'],
            'rating': rating,
            'votes': votes,
            'duration': duration,
            'mpaa': show_mpaa,
            'studio': studio,
            'resume_percent': resume_percent # <--- ADĂUGAT AICI PENTRU CERCULEȚ
        }
        
        try: skin_compat = ADDON.getSetting('skin_type')
        except: skin_compat = '0'

        badge = ""
        if skin_compat == '0':
            if ep_type in['series_premiere', 'season_premiere']:
                badge = "[COLOR FF00FA9A] • Season Premiere[/COLOR]"
            elif ep_type in ['series_finale', 'season_finale']:
                badge = "[COLOR FFFF4444] • Season Finale[/COLOR]"
            elif ep_type == 'mid_season_finale':
                badge = "[COLOR FFFF4444] • Mid-Season Finale[/COLOR]"
                
        label = f"[B][COLOR FF00CED1]{it['show_title']}[/COLOR][/B] - [B][COLOR FFCCCCCC]S{it['season']:02d}E{it['episode']:02d}[/COLOR][/B] - [B][COLOR FFCCCCFF][I]{it['ep_title']}{badge}[/I][/COLOR][/B]"

        # Logica de afișare a datei pentru episoadele viitoare
        # <<-- MODIFICARE AICI PENTRU CULOARE -->>
        is_upcoming = False
        if it['air_date']:
            try:
                parts = str(it['air_date']).split('T')[0].split('-')
                air_date_obj = datetime.date(int(parts[0]), int(parts[1]), int(parts[2]))
                if air_date_obj > today:
                    is_upcoming = True
                    days_until = (air_date_obj - today).days
                    if days_until == 1:
                        zile_str = "Tomorrow"
                    elif 1 < days_until <= 7:
                        zile_str = f"In {days_until} days"
                    else: # Peste 7 zile (dacă setarea e activă)
                        zile_str = it['air_date']
                    # Culoarea e reparată aici, închidem corect tag-ul roz și punem galben pe dată
                    label = f"[B][COLOR FFFF69B4]{it['show_title']} - S{it['season']:02d}E{it['episode']:02d}[/COLOR] [COLOR yellow]({zile_str})[/COLOR][/B]"
                    if badge:
                        label += f" [I]{badge}[/I]"
            except: 
                pass
        elif show_future: # Dacă nu are dată deloc (TBA) și setarea e activă
             label = f"{label} [I][B][COLOR red]Nelansat[/COLOR][/B][/I]"
             
        # --- NOU: AFIȘARE ESTUARY NUMĂR EPISOADE RĂMASE ---
        if skin_compat == '0' and unwatched_count > 0:
            label += f" [COLOR orange] ({unwatched_count})[/COLOR]"
        # --------------------------------------------------

        url_params = {'mode': 'sources', 'tmdb_id': tmdb_id, 'type': 'tv', 'season': str(it['season']), 'episode': str(it['episode']), 'title': it['ep_title'], 'tv_show_title': it['show_title']}

        # --- ADĂUGAT: Trimitem timpul de resume către player pentru a oferi opțiunea "Resume from..." ---
        if resume_seconds > 0:
            url_params['resume_time'] = resume_seconds

        cm = _get_full_context_menu(
            tmdb_id, 
            'episode',             
            it['show_title'], 
            imdb_id=imdb_id,
            season=it['season'],   
            episode=it['episode']  
        )
        
        # --- ÎNCEPUT ADĂUGARE BROWSE OPTIONS ---
        # Browse Show (Afișează sezoanele)
        b_show_params = urlencode({'mode': 'details', 'tmdb_id': tmdb_id, 'type': 'tv', 'title': it['show_title']})
        cm.append(('[B][COLOR cyan]Browse Show[/COLOR][/B]', f"Container.Update({sys.argv[0]}?{b_show_params})"))
        
        # Browse Season (Afișează episoadele din sezonul curent)
        b_season_params = urlencode({'mode': 'episodes', 'tmdb_id': tmdb_id, 'season': str(it['season']), 'tv_show_title': it['show_title']})
        cm.append(('[B][COLOR cyan]Browse Season[/COLOR][/B]', f"Container.Update({sys.argv[0]}?{b_season_params})"))
        # --- SFÂRȘIT ADĂUGARE BROWSE OPTIONS ----
        
        # --- ÎNCEPUT ADĂUGARE NOUĂ: Clear Sources Cache pentru Up Next ---
        clear_p_params = urlencode({
            'mode': 'clear_sources_context', 
            'tmdb_id': tmdb_id, 
            'type': 'tv', 
            'season': str(it['season']), 
            'episode': str(it['episode']),
            'title': f"{it['show_title']} S{it['season']:02d}E{it['episode']:02d}"
        })
        cm.append(('[B][COLOR orange]Clear sources cache[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{clear_p_params})"))
        # --- SFÂRȘIT ADĂUGARE NOUĂ ---
        
        url = f"{sys.argv[0]}?{urlencode(url_params)}"
        li = xbmcgui.ListItem(label)
        
        try: skin_compat = ADDON.getSetting('skin_type')
        except: skin_compat = '0'
        
        art = {
            'thumb': ep_icon, 
            'icon': ep_icon, 
            'landscape': ep_icon,
            'tvshow.poster': base_poster, 
            'season.poster': base_poster, 
            'fanart': final_fanart
        }
        
        if skin_compat == '1':
            art['poster'] = base_poster
        else:
            art['poster'] = ep_icon
            
        if show_logo:
            art['clearlogo'] = show_logo
            art['tvshow.clearlogo'] = show_logo
            art['tvshow.logo'] = show_logo
            art['logo'] = show_logo
            art['fanart_clearlogo'] = show_logo
        li.setArt(art)
        li.setProperty('tmdb_id', str(tmdb_id))
        if ep_type:
            li.setProperty('episode_type', ep_type)
        # Modificat watched_info pentru a seta proprietățile AF3
        set_metadata(li, info, unique_ids={'tmdb': str(tmdb_id), 'imdb': imdb_id}, watched_info=show_watched_info)
        
        # --- ADĂUGAT: Setăm manual cercul de progres pentru Kodi ---
        from resources.lib.utils import set_resume_point
        set_resume_point(li, resume_seconds, duration)
        
        if cm: li.addContextMenuItems(cm)
        xbmcplugin.addDirectoryItem(HANDLE, url, li, isFolder=False)

    # === AICI SE TERMINĂ BUCLA FOR ===
    
    xbmcplugin.setContent(HANDLE, 'episodes')
    xbmcplugin.endOfDirectory(HANDLE)


# FOR SEREN
def get_trakt_client_id():
    """Extrage Trakt client_id fără a genera erori în log dacă addon-urile lipsesc."""
    import os
    import re
    import xbmc
    
    # Folosim xbmcvfs pentru a verifica dacă un folder de addon există, e mai sigur
    def addon_exists(addon_id):
        addon_path = f"special://home/addons/{addon_id}"
        return xbmcvfs.exists(addon_path)

    search_map = {
        'plugin.video.seren': [
            'resources/lib/modules/globals.py',
            'resources/lib/modules/trakt/trakt_api.py',
            'resources/lib/common/tools.py',
        ],
        'script.trakt': [
            'resources/lib/trakt/api.py',
            'resources/lib/traktapi.py',
        ],
        'plugin.video.themoviedb.helper': [
            'resources/tmdbhelper/lib/api/trakt/api.py',
            'resources/lib/trakt/api.py',
        ],
    }
    
    for addon_id, paths in search_map.items():
        if not addon_exists(addon_id):
            continue  # Sărim peste dacă addon-ul nu e instalat
        
        try:
            import xbmcaddon
            addon_instance = xbmcaddon.Addon(addon_id)
            base = addon_instance.getAddonInfo('path')
        except:
            continue

        for rp in paths:
            fp = os.path.join(base, *rp.split('/'))
            if not os.path.isfile(fp): continue
            try:
                with open(fp, 'r', encoding='utf-8', errors='ignore') as f:
                    txt = f.read()
                for m in re.finditer(r'["\']([a-f0-9]{64})["\']', txt):
                    xbmc.log(f"[TMDb Movies] Trakt client_id found in {addon_id}", xbmc.LOGINFO)
                    return m.group(1)
            except: continue
    
    # Fallback scan (doar dacă Seren există)
    if addon_exists('plugin.video.seren'):
        try:
            import xbmcaddon
            seren_addon = xbmcaddon.Addon('plugin.video.seren')
            base = seren_addon.getAddonInfo('path')
            for root, _, files in os.walk(base):
                for fn in files:
                    if not fn.endswith('.py'): continue
                    fp = os.path.join(root, fn)
                    try:
                        with open(fp, 'r', encoding='utf-8', errors='ignore') as f:
                            txt = f.read()
                        if 'client' not in txt.lower(): continue
                        for m in re.finditer(r'["\']([a-f0-9]{64})["\']', txt):
                            xbmc.log(f"[TMDb Movies] Trakt client_id found via fallback in {fp}", xbmc.LOGINFO)
                            return m.group(1)
                    except: continue
        except: pass
    
    return None


def get_trakt_id(imdb_id, tmdb_id, media_type='movie'):
    """Convertește IMDb/TMDb ID → Trakt ID, fără erori în log."""
    import requests
    import xbmc
    
    client_id = get_trakt_client_id()
    if not client_id:
        # AICI AM SCOS LINIA CARE GENERA EROAREA IN LOG!
        return None
    
    headers = {
        'Content-Type': 'application/json',
        'trakt-api-version': '2',
        'trakt-api-key': client_id
    }
    
    trakt_type = 'movie' if media_type == 'movie' else 'show'
    
    if imdb_id and str(imdb_id).startswith('tt'):
        try:
            r = requests.get(
                f"https://api.trakt.tv/search/imdb/{imdb_id}?type={trakt_type}",
                headers=headers, timeout=5
            )
            if r.ok and r.json():
                tid = r.json()[0][trakt_type]['ids']['trakt']
                return tid
        except: pass
    
    if tmdb_id:
        try:
            r = requests.get(
                f"https://api.trakt.tv/search/tmdb/{tmdb_id}?type={trakt_type}",
                headers=headers, timeout=5
            )
            if r.ok and r.json():
                tid = r.json()[0][trakt_type]['ids']['trakt']
                return tid
        except: pass
    
    return None

    
# =============================================================================
# MENU: MY PLAYS (Custom Player Launcher) - CU SUPORT SETĂRI
# =============================================================================
def show_my_plays_menu(params):
    import json
    import xbmc
    from resources.lib.config import ADDON
    
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
        main_details = get_tmdb_item_details(tmdb_id, 'movie' if c_type == 'movie' else 'tv') or {}
        
        if main_details:
            if main_details.get('poster_path'):
                poster = f"{IMG_BASE}{main_details['poster_path']}"
            if main_details.get('backdrop_path'):
                fanart = f"{BACKDROP_BASE}{main_details['backdrop_path']}"
            
            ext_ids = main_details.get('external_ids', {})
            if not correct_imdb_id: correct_imdb_id = ext_ids.get('imdb_id', '')
            correct_tvdb_id = str(ext_ids.get('tvdb_id', ''))
            
            status = main_details.get('status', '')
            if main_details.get('genres'):
                genre = ' / '.join([g['name'] for g in main_details['genres']])
            if main_details.get('networks'):
                studio = main_details['networks'][0].get('name', '')
            elif main_details.get('production_companies'):
                studio = main_details['production_companies'][0].get('name', '')
            
            if not year:
                date_ref = main_details.get('release_date') or main_details.get('first_air_date')
                if date_ref: year = date_ref[:4]

        if c_type == 'episode':
            ep_url = f"{BASE_URL}/tv/{tmdb_id}/season/{season}/episode/{episode}?api_key={API_KEY}&language={LANG}&append_to_response=credits"
            import requests
            r_ep = requests.get(ep_url, timeout=3)
            if r_ep.status_code == 200:
                ed = r_ep.json()
                plot = ed.get('overview', '')
                rating = float(ed.get('vote_average', 0.0))
                votes = int(ed.get('vote_count', 0))
                for actor in ed.get('credits', {}).get('guest_stars', [])[:10]:
                    cast_list.append({"name": actor['name'], "role": actor.get('character', '')})
        else:
            plot = main_details.get('overview', '')
            rating = float(main_details.get('vote_average', 0.0))
            votes = int(main_details.get('vote_count', 0))
            for actor in main_details.get('credits', {}).get('cast', [])[:10]:
                cast_list.append({"name": actor['name'], "role": actor.get('character', '')})

    except: pass

    if not year and premiered: year = premiered[:4]
    
    # === CITIRE SETĂRI PLAYERE ===
    # != 'false' asigură că, dacă setarea nu a fost încă salvată în settings.xml, va funcționa ca TRUE implicit.
    show_pov = ADDON.getSetting('use_pov') != 'false'
    show_salts = ADDON.getSetting('use_salts') != 'false'
    show_fenlight = ADDON.getSetting('use_fenlight') != 'false'
    show_redlight = ADDON.getSetting('use_redlight') != 'false'
    show_fen = ADDON.getSetting('use_fen') != 'false'
    show_magneto = ADDON.getSetting('use_magneto') != 'false'
    show_luckodi = ADDON.getSetting('use_luckodi') != 'false'
    show_umbrella = ADDON.getSetting('use_umbrella') != 'false'
    show_elementum = ADDON.getSetting('use_elementum') != 'false'
    show_cinebox = ADDON.getSetting('use_cinebox') != 'false'
    show_seren = ADDON.getSetting('use_seren') != 'false'
    show_mrsplite = ADDON.getSetting('use_mrsplite') != 'false'
    show_tmdbhelper = ADDON.getSetting('use_tmdbhelper') != 'false'

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
        if show_tmdbhelper:
            url = f"plugin://plugin.video.themoviedb.helper/?info=search&type=tv&query={safe_title}"
            options.append(f"[B]Search with [COLOR FF00CED1]TMDB Helper[/COLOR][/B]")
            actions.append(url)
            is_folder_list.append(True) 
            is_luc_kodi_action.append(False)
        
        if not options:
            xbmcgui.Dialog().notification("My Plays", "Toate playerele sunt dezactivate!", xbmcgui.NOTIFICATION_WARNING)
            return
            
        ret = xbmcgui.Dialog().contextmenu(options)
        if ret >= 0:
            xbmc.executebuiltin(f'ActivateWindow(Videos,"{actions[ret]}",return)')
        return

    # =========================================================================
    # 1. PLAYERE DIRECTE
    # =========================================================================
    if c_type != 'season':
        # POV
        if show_pov:
            if c_type == 'movie':
                pov_url = f"plugin://plugin.video.pov/?mode=play_media&mediatype=movie&query={safe_title}&year={year}&poster={quote_plus(poster)}&tmdb_id={tmdb_id}&autoplay=false"
            else:
                pov_url = f"plugin://plugin.video.pov/?mode=play_media&mediatype=episode&query={safe_title}&year={year}&season={season}&episode={episode}&tmdb_id={tmdb_id}&autoplay=false"
            options.append(f"[B]{prefix} [COLOR FFB041FF]POV[/COLOR][/B]")
            actions.append(pov_url)
            is_folder_list.append(False)
            is_luc_kodi_action.append(False)

        # SALTS
        if show_salts:
            if c_type == 'movie':
                salts_url = f"plugin://plugin.video.sallts/?mode=play_media&mediatype=movie&query={safe_title}&year={year}&poster={quote_plus(poster)}&tmdb_id={tmdb_id}&autoplay=false"
            else:
                salts_url = f"plugin://plugin.video.sallts/?mode=play_media&mediatype=episode&query={safe_title}&year={year}&season={season}&episode={episode}&tmdb_id={tmdb_id}&autoplay=false"
            options.append(f"[B]{prefix} [COLOR gold]SALTS[/COLOR][/B]")
            actions.append(salts_url)
            is_folder_list.append(False)
            is_luc_kodi_action.append(False)

        # FEN LIGHT
        if show_fenlight:
            if c_type == 'movie':
                fen_url = f"plugin://plugin.video.fenlight/?mode=playback.media&media_type=movie&query={safe_title}&year={year}&poster={quote_plus(poster)}&title={safe_title}&tmdb_id={tmdb_id}&autoplay=false"
            else:
                fen_url = f"plugin://plugin.video.fenlight/?mode=playback.media&media_type=episode&query={safe_title}&year={year}&season={season}&episode={episode}&ep_name={quote_plus(ep_name)}&tmdb_id={tmdb_id}&premiered={premiered}&autoplay=false"
            options.append(f"[B]{prefix} [COLOR lightskyblue]Fen Light[/COLOR][/B]")
            actions.append(fen_url)
            is_folder_list.append(False)
            is_luc_kodi_action.append(False)

        # RED LIGHT
        if show_redlight:
            if c_type == 'movie':
                red_url = f"plugin://plugin.video.redlight/?mode=playback.media&media_type=movie&query={safe_title}&year={year}&poster={quote_plus(poster)}&title={safe_title}&tmdb_id={tmdb_id}&autoplay=false"
            else:
                red_url = f"plugin://plugin.video.redlight/?mode=playback.media&media_type=episode&query={safe_title}&year={year}&season={season}&episode={episode}&ep_name={quote_plus(ep_name)}&tmdb_id={tmdb_id}&premiered={premiered}&autoplay=false"
            options.append(f"[B]{prefix} [COLOR FFFF2222]Red Light[/COLOR][/B]")
            actions.append(red_url)
            is_folder_list.append(False)
            is_luc_kodi_action.append(False)

        # FEN
        if show_fen:
            if c_type == 'movie':
                fen_url = f"plugin://plugin.video.fen/?mode=playback.media&media_type=movie&query={safe_title}&year={year}&poster={quote_plus(poster)}&title={safe_title}&tmdb_id={tmdb_id}&autoplay=false"
            else:
                fen_url = f"plugin://plugin.video.fen/?mode=playback.media&media_type=episode&query={safe_title}&year={year}&season={season}&episode={episode}&ep_name={quote_plus(ep_name)}&tmdb_id={tmdb_id}&premiered={premiered}&autoplay=false"
            options.append(f"[B]{prefix} [COLOR lightskyblue]Fen[/COLOR][/B]")
            actions.append(fen_url)
            is_folder_list.append(False)
            is_luc_kodi_action.append(False)

        # MAGNETO
        if show_magneto:
            if c_type == 'movie':
                mag_url = f"plugin://script.module.magneto/?action=MediaPlay&mediatype=movie&imdb_id={correct_imdb_id}"
            else:
                mag_url = f"plugin://script.module.magneto/?action=MediaPlay&mediatype=episode&imdb_id={correct_imdb_id}&season={season}&episode={episode}"
            
            options.append(f"[B]{prefix} [COLOR red]Magneto[/COLOR][/B]")
            actions.append(mag_url)
            is_folder_list.append(False)
            is_luc_kodi_action.append(False)


        # =========================================================================
        # 2. luc_Kodi
        # =========================================================================
        meta_enc = "" # O definim aici să fie accesibilă și la Umbrella
        if show_luckodi or show_umbrella:
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
                "castandart": cast_list
            }
            
            if c_type == 'episode':
                meta_obj.update({"title": ep_name, "tvshowtitle": title, "label": ep_name, "season": int(season), "episode": int(episode), "tvdb": correct_tvdb_id})
                meta_enc = quote_plus(json.dumps(meta_obj, ensure_ascii=False))
                lk_url = f"plugin://plugin.video.luc_kodi/?action=play&tmdb={tmdb_id}&tvdb={correct_tvdb_id}&title={quote_plus(ep_name)}&tvshowtitle={safe_title}&season={season}&episode={episode}&year={year}&premiered={premiered}&imdb={correct_imdb_id}&select=0&meta={meta_enc}"
            else:
                meta_obj.update({"title": title, "originaltitle": title})
                meta_enc = quote_plus(json.dumps(meta_obj, ensure_ascii=False))
                lk_url = f"plugin://plugin.video.luc_kodi/?action=play&tmdb={tmdb_id}&title={safe_title}&year={year}&premiered={premiered}&imdb={correct_imdb_id}&select=0&meta={meta_enc}"

            if show_luckodi:
                options.append(f"[B]{prefix} [COLOR ff00fa9a]luc_[/COLOR]Kodi[/B]")
                actions.append(lk_url)
                is_folder_list.append(False)
                is_luc_kodi_action.append(True)

        # =========================================================================
        # 3. UMBRELLA
        # =========================================================================
        if show_umbrella:
            if c_type == 'movie':
                umb_url = f"plugin://plugin.video.umbrella/?action=play&title={safe_title}&year={year}&imdb={correct_imdb_id}&tmdb={tmdb_id}&meta={meta_enc}&select=0"
            else:
                umb_url = f"plugin://plugin.video.umbrella/?action=play&title={quote_plus(ep_name)}&year={year}&imdb={correct_imdb_id}&tmdb={tmdb_id}&tvdb={correct_tvdb_id}&season={season}&episode={episode}&tvshowtitle={safe_title}&premiered={premiered}&meta={meta_enc}&select=0"
            
            options.append(f"[B]{prefix} [COLOR FFE41B17]Umbrella[/COLOR][/B]")
            actions.append(umb_url)
            is_folder_list.append(False)
            is_luc_kodi_action.append(True)

        # =========================================================================
        # 4. ELEMENTUM
        # =========================================================================
        if show_elementum:
            if c_type == 'movie':
                elem_url = f"plugin://plugin.video.elementum/library/play/movie/{tmdb_id}"
            else:
                elem_url = f"plugin://plugin.video.elementum/library/play/show/{tmdb_id}/season/{season}/episode/{episode}"
            
            options.append(f"[B]{prefix} [COLOR FF786D5F]Elementum[/COLOR][/B]")
            actions.append(elem_url)
            is_folder_list.append(False)
            is_luc_kodi_action.append(True)

        # =========================================================================
        # 5. CINEBOX
        # =========================================================================
        if show_cinebox:
            if c_type == 'movie':
                cine_url = f"plugin://plugin.video.cinebox/?action=find_sources&media_type=movie&title={safe_title}&year={year}&tmdb_id={tmdb_id}&imdb_id={correct_imdb_id}&poster={quote_plus(poster)}&autoplay=false"
            else:
                cine_url = f"plugin://plugin.video.cinebox/?action=find_sources&media_type=tvshow&title={safe_title}&year={year}&season={season}&episode={episode}&tmdb_id={tmdb_id}&imdb_id={correct_imdb_id}&poster={quote_plus(poster)}&autoplay=false"
            
            options.append(f"[B]{prefix} [COLOR FFA70D2A]CINEBOX[/COLOR][/B]")
            actions.append(cine_url)
            is_folder_list.append(False)
            is_luc_kodi_action.append(True)
            
        # =========================================================================
        # 6. SEREN
        # =========================================================================
        if show_seren:
            trakt_media = 'movie' if c_type == 'movie' else 'show'
            trakt_id = get_trakt_id(correct_imdb_id, tmdb_id, trakt_media)
            
            if trakt_id:
                trakt_id_int = int(trakt_id)
                if c_type == 'movie':
                    action_args = quote_plus(json.dumps({"item_type": "movie", "trakt_id": trakt_id_int}))
                    seren_url = f"plugin://plugin.video.seren/?action=getSources&forceresumecheck=true&source_select=true&actionArgs={action_args}"
                else:
                    action_args = quote_plus(json.dumps({"episode": int(episode), "item_type": "episode", "season": int(season), "trakt_id": trakt_id_int}))
                    seren_url = f"plugin://plugin.video.seren/?action=getSources&smartPlay=false&source_select=true&forceresumecheck=true&actionArgs={action_args}"
                
                options.append(f"[B]{prefix} [COLOR FF00BFFF]Seren[/COLOR][/B]")
                actions.append(seren_url)
                is_folder_list.append(False)
                is_luc_kodi_action.append(True)
            else:
                # Fallback: Search (nu necesită Trakt ID)
                seren_url = f"plugin://plugin.video.seren/?action=moviesSearchResults&actionArgs={safe_title}" if c_type == 'movie' else f"plugin://plugin.video.seren/?action=showsSearchResults&actionArgs={safe_title}"
                options.append(f"[B]Search with [COLOR FF00BFFF]Seren[/COLOR][/B]")
                actions.append(seren_url)
                is_folder_list.append(True)
                is_luc_kodi_action.append(False)
            
        # =========================================================================
        # 7. MRSP Lite
        # =========================================================================
        if show_mrsplite:
            if c_type == 'movie':
                mrsp_url = f"plugin://plugin.video.romanianpack/?action=searchSites&searchSites=cuvant&cuvant={safe_title}+{year}&tmdb_id={tmdb_id}&imdb_id={correct_imdb_id}&mediatype=movie"
            else:
                try: s_str = f"s{int(season):02d}"
                except: s_str = f"s{season}"
                mrsp_url = f"plugin://plugin.video.romanianpack/?action=searchSites&searchSites=cuvant&cuvant={safe_title}+{s_str}&showname={safe_title}&season={season}&episode={episode}&tmdb_id={tmdb_id}&imdb_id={correct_imdb_id}&mediatype=episode"
            
            options.append(f"[B]{prefix} [COLOR orange]MRSP Lite[/COLOR][/B]")
            actions.append(mrsp_url)
            is_folder_list.append(False)
            is_luc_kodi_action.append(False)

        # =========================================================================
        # 8. TMDb Helper
        # =========================================================================
        if show_tmdbhelper:
            if c_type == 'movie':
                actions.append(f"plugin://plugin.video.themoviedb.helper/?info=search&type=movie&query={safe_title}")
                options.append(f"[B]Search with [COLOR gold]TMDB Helper[/COLOR][/B]")
                is_folder_list.append(True)
                is_luc_kodi_action.append(False)
                
                url = f"plugin://plugin.video.themoviedb.helper/?info=play&type=movie&tmdb_id={tmdb_id}"
                options.append(f"[B]{prefix} [COLOR FF00CED1]TMDB Helper[/COLOR][/B]")
                actions.append(url)
                is_folder_list.append(False)
                is_luc_kodi_action.append(False)
            elif c_type == 'episode':
                url = f"plugin://plugin.video.themoviedb.helper/?info=play&type=episode&tmdb_id={tmdb_id}&season={season}&episode={episode}"
                options.append(f"[B]{prefix} [COLOR FF00CED1]TMDB Helper[/COLOR][/B]")
                actions.append(url)
                is_folder_list.append(False)
                is_luc_kodi_action.append(False)

    # --- EXECUȚIE ---
    if not options:
        xbmcgui.Dialog().notification("My Plays", "Toate playerele sunt dezactivate!", xbmcgui.NOTIFICATION_WARNING)
        return

    ret = xbmcgui.Dialog().contextmenu(options)
    if ret >= 0:
        target = actions[ret]
        
        if is_luc_kodi_action[ret]:
            xbmc.executebuiltin('Dialog.Close(all,true)')
            xbmc.sleep(300)
            
            if "script.module.magneto" in target:
                xbmc.executebuiltin(f"RunPlugin({target})")
            else:
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
            'art': {'icon': NEXT_PAGE_ICON, 'thumb': NEXT_PAGE_ICON},
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
                    'tmdb_movies_netflix',  'tmdb_movies_amazon',
                    'tmdb_movies_disney', 'tmdb_movies_apple', 
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
                    'trakt_tv_trending', 'trakt_tv_popular', 'trakt_tv_anticipated',
                    'tmdb_tv_latest_releases', 'tmdb_tv_netflix',
                    'tmdb_tv_amazon', 'tmdb_tv_disney', 'tmdb_tv_apple'
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
    
