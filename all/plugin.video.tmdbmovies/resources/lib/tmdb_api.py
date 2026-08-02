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
import re
import time
import datetime

from resources.lib.config import (
    BASE_URL, API_KEY, IMG_BASE, BACKDROP_BASE, HANDLE, ADDON,
    TMDB_SESSION_FILE, FAVORITES_FILE,
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
    """Deseneaza lista instantaneu din datele cached folosind Batch Add."""
    items_to_add = [] 
    
    for item in items:
        # Reconstructie ListItem daca vine din JSON (warmup)
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
                    # Convertim in string apoi verificam daca e cifra
                    year_str = str(info['year'])
                    if year_str.isdigit():
                        tag.setYear(int(year_str))
                except:
                    pass # Daca e "None" sau gol, pur si simplu nu setam anul
            # -------------------------

            if info.get('rating'): tag.setRating(float(info['rating']))
            if info.get('votes'): tag.setVotes(int(info['votes']))
            if info.get('duration'): tag.setDuration(int(info['duration']))
            if info.get('premiered'): tag.setPremiered(info['premiered'])
            if info.get('studio'):
                st_val = info['studio']
                # Verificam daca e deja o lista, daca nu, o punem noi intr-una
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
            if info.get('season'):
                try:
                    tag.setSeason(int(info['season']))
                except:
                    pass
            if info.get('episode'):
                try:
                    tag.setEpisode(int(info['episode']))
                except:
                    pass
            if info.get('tvshowtitle'):
                tag.setTvShowTitle(str(info['tvshowtitle']))
            
            # APLICAM BIFA DOAR DACA NU E FOLDER (Butonul Next nu are bifa)
            if not item['is_folder']:
                if info.get('playcount') == 1: 
                    tag.setPlaycount(1)
                else:
                    tag.setPlaycount(0)
                
                # Intotdeauna verificam daca exista resume_time (chiar daca e watched, poate utilizatorul l-a reinceput)
                if item.get('resume_time') and item.get('total_time'):
                    set_resume_point(li, item['resume_time'], item['total_time'])
                elif info.get('playcount') == 1:
                    tag.setResumePoint(0.0, 0.0)
            else:
                if info.get('playcount') == 1:
                    tag.setPlaycount(1)
                else:
                    tag.setPlaycount(0)

            if item.get('cm'):
                li.addContextMenuItems(item['cm'])

            # Restaurare proprietati (badge episode_type + watched counts AF3)
            # Fara ele, randarea din fast cache pierde badge-urile si cercul cu episoade ramase
            _props = item.get('properties') or {}
            for _k, _v in _props.items():
                if _v:
                    li.setProperty(_k, str(_v))

        items_to_add.append((item['url'], li, item['is_folder']))
    
    xbmcplugin.addDirectoryItems(HANDLE, items_to_add, len(items_to_add))
    
    if items:
        xbmcplugin.setContent(HANDLE, items[0]['info'].get('mediatype', 'movies') + 's')
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=True)
    

# === THREADING PREFETCHER (OPTIMIZAT PENTRU STABILITATE UI) ===
def prefetch_metadata_parallel(items, media_type):
    """Prefetch metadata in background with early abort. Uses user's language so data
    can be served directly from pool without re-fetch. Separate session + short timeout."""
    if not items: return
    
    import threading, time, requests
    from resources.lib.config import BASE_URL, API_KEY, get_headers, get_plot_language, get_plot_language_code, get_plot_img_lang
    from resources.lib.cache import ram_pool_set, ram_cache_set_tvshow
    
    current_lang = get_plot_language_code()
    url_lang = get_plot_language()
    img_lang = 'en,null,xx' if current_lang == 'en' else get_plot_img_lang()
    
    prefetch_session = requests.Session()
    
    def fetch_task(item):
        if xbmc.Monitor().abortRequested(): return
        tid = str(item.get('id') or item.get('tmdb_id') or '')
        if not tid or tid == 'None': return
        m_type = item.get('media_type') or ('movie' if media_type == 'movie' else 'tv')
        endpoint = 'movie' if m_type == 'movie' else 'tv'
        try:
            url = (f"{BASE_URL}/{endpoint}/{tid}?api_key={API_KEY}&language={url_lang}"
                   f"&append_to_response=external_ids,images,content_ratings,release_dates"
                   f"&include_image_language={img_lang}")
            res = prefetch_session.get(url, headers=get_headers(), timeout=1.0)
            if res.status_code == 200:
                data = res.json()
                data['_cached_lang'] = current_lang
                data['_lightweight'] = True
                _extract_mpaa(data, m_type)
                _ensure_clearlogo(data)
                ram_pool_set(str(tid), data)
                if m_type != 'movie':
                    ram_cache_set_tvshow(tid, data)
        except:
            pass
    
    threads = []
    for item in items:
        t = threading.Thread(target=fetch_task, args=(item,))
        t.daemon = True
        threads.append(t)
        t.start()
    
    deadline = time.time() + 1.1
    for t in threads:
        remaining = deadline - time.time()
        if remaining > 0:
            t.join(timeout=remaining)
        else:
            break
    
    # Close prefetch session to abort in-flight requests → remaining threads exit fast
    try:
        prefetch_session.close()
    except:
        pass

# =============================================================================
# FUNCTIE PENTRU LOCALIZARE COMPLETA (PLOT, POSTER, FANART in RO, Nume in EN)
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
    Construieste URL-ul complet pentru imaginile listelor TMDb.
    """
    if not image_path:
        return None
    
    # Daca e deja URL complet, returnam direct
    if image_path.startswith('http'):
        return image_path
    
    # Alegem rezolutia bazata pe tip
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
            li.setProperty('dbtype', info_data['mediatype'])
        if 'title' in info_data: 
            tag.setTitle(str(info_data['title']))
        if 'plot' in info_data: 
            tag.setPlot(str(info_data['plot']))
        
        # Durata (importanta pentru cerculet progres)
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
            default_id = 'imdb' if 'imdb' in unique_ids else 'tmdb'
            tag.setUniqueIDs(unique_ids, default_id)
            # Fortam si legacy m_strIMDBNumber pentru library items unde
            # setUniqueIDs poate fi ignorat la setResolvedUrl
            if 'imdb' in unique_ids:
                try: tag.setIMDBNumber(str(unique_ids['imdb']))
                except: pass
        if 'cast' in info_data:
            actors = []
            for a in info_data['cast']:
                if isinstance(a, dict):
                    # Convertim dictionarul in obiectul Actor cerut de Kodi
                    actors.append(xbmc.Actor(name=a.get('name', ''), role=a.get('role', ''), thumbnail=a.get('thumbnail', '')))
                else:
                    actors.append(a)
            tag.setCast(actors)

        # LOGICA WATCHED - SIMPLIFICATA
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
                # Label galben bold + contor pentru seriale/sezoane incepute
                if w > 0 and not is_fully_watched:
                    li.setProperty('PercentPlayed', str(int((float(w)/float(t))*100)))
                    try:
                        cur = li.getLabel()
                        if cur and '[/' not in cur:
                            li.setLabel(f"[B][COLOR FFEFD702]{cur}[/COLOR] [COLOR FF6AFB92]({w}/{t})[/COLOR][/B]")
                    except: pass
            else:
                li.setProperty('TotalEpisodes', '0')

        # ✅ SETAM PLAYCOUNT
        if is_fully_watched: 
            tag.setPlaycount(1)
        else: 
            tag.setPlaycount(0)
            
        # ✅ SETAM CERCULET PROGRES (indiferent daca e vizionat sau nu, daca utilizatorul a reinceput vizionarea)
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
    # FIX: Nu setam IsPlayable pentru mode=sources
    # Lasam player.py sa gestioneze redarea manual
    # ============================================================
    # ✅ FIX: Lista de moduri care sunt ACTIUNI (nu playable, nu folder)
    ACTION_MODES = [
        'sources',  # Gestionat separat de player
        'tmdb_auth', 'tmdb_logout', 'tmdb_auth_action', 'tmdb_logout_action',
        'trakt_auth', 'trakt_revoke', 'trakt_auth_action', 'trakt_revoke_action',
        'trakt_sync', 'trakt_sync_db', 'trakt_sync_action',
        'trakt_sync_smart', 'trakt_sync_smart_action', # <-- ADAUGAT AICI
        'tmdb_refresh_lists',
        'multiselect_genres',
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
    # Pentru mode=sources, NU setam IsPlayable - plugin-ul gestioneaza singur
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

    # --- MODIFICARE NOUA ---
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
    """Citeste istoricul de cautare."""
    data = read_json(SEARCH_HISTORY_FILE)
    if not data or not isinstance(data, list):
        return []
    return data

def add_search_to_history(query, search_type):
    """Adauga o cautare noua la inceputul listei (Max 20)."""
    history = get_search_history()
    
    # Cream obiectul nou
    new_item = {'query': query, 'type': search_type}
    
    # Eliminam duplicatele (daca exista deja, il stergem ca sa-l punem primul)
    history = [h for h in history if not (h['query'] == query and h['type'] == search_type)]
    
    # Adaugam la inceput
    history.insert(0, new_item)
    
    # Pastram doar ultimele 20
    history = history[:20]
    
    write_json(SEARCH_HISTORY_FILE, history)

def remove_search_from_history(query, search_type):
    """Sterge o cautare specifica."""
    history = get_search_history()
    history = [h for h in history if not (h['query'] == query and h['type'] == search_type)]
    write_json(SEARCH_HISTORY_FILE, history)

def clear_search_history_action():
    """Sterge tot istoricul."""
    if xbmcvfs.exists(SEARCH_HISTORY_FILE):
        xbmcvfs.delete(SEARCH_HISTORY_FILE)
    xbmcgui.Dialog().notification("[B][COLOR FFFDBD01]Search[/COLOR][/B]", "History cleared", TMDbmovies_ICON, 2000, False)
    xbmc.executebuiltin("Container.Refresh")

def delete_search_item(params):
    """Functia apelata din meniul contextual pentru stergere."""
    query = params.get('query')
    search_type = params.get('type')
    remove_search_from_history(query, search_type)
    xbmcgui.Dialog().notification("[B][COLOR FFFDBD01]Search[/COLOR][/B]", "Removed from history", TMDbmovies_ICON, 2000, False)
    xbmc.executebuiltin("Container.Refresh")

def edit_search_item(params):
    """Functia apelata din meniul contextual pentru editare."""
    old_query = params.get('query')
    search_type = params.get('type')
    
    dialog = xbmcgui.Dialog()
    new_query = dialog.input("Edit search", defaultt=old_query, type=xbmcgui.INPUT_ALPHANUM)
    
    # Verificam daca utilizatorul a scris ceva si daca e diferit de ce era inainte
    if new_query and new_query != old_query:
        # 1. Stergem vechea intrare
        remove_search_from_history(old_query, search_type)
        
        # 2. Adaugam noua intrare (ACESTA ERA PASUL LIPSA)
        add_search_to_history(new_query, search_type)
        
        # 3. Dam Refresh la lista ca sa apara modificarea vizual
        xbmcgui.Dialog().notification("[B][COLOR FFFDBD01]Search[/COLOR][/B]", "Change saved", TMDbmovies_ICON, 2000, False)
        xbmc.executebuiltin("Container.Refresh")


def search_menu():
    SEARCH_MOVIE_ICON = os.path.join(ADDON_PATH, 'resources', 'media', 'search_movie.png')
    SEARCH_TV_ICON = os.path.join(ADDON_PATH, 'resources', 'media', 'search_tv.png')
    
    # Iconita pentru istoric (search.png)
    SEARCH_HISTORY_ICON = os.path.join(ADDON_PATH, 'resources', 'media', 'search_history.png')
    # Fallback daca nu exista search.png, folosim default
    if not os.path.exists(SEARCH_HISTORY_ICON):
        SEARCH_HISTORY_ICON = 'DefaultIconSearch.png'

    # 1. Butoanele principale de cautare
    add_directory("[B][COLOR FFFDBD01]Search Movies[/COLOR][/B]", {'mode': 'perform_search', 'type': 'movie'}, icon=SEARCH_MOVIE_ICON, thumb=SEARCH_MOVIE_ICON, folder=True)
    add_directory("[B][COLOR FFFDBD01]Search TV Shows[/COLOR][/B]", {'mode': 'perform_search', 'type': 'tv'}, icon=SEARCH_TV_ICON, thumb=SEARCH_TV_ICON, folder=True)
    
    # 2. Istoricul de cautare
    history = get_search_history()
    
    if history:
        
        for item in history:
            query = item.get('query')
            stype = item.get('type')
            
            # Formatam tipul (Movie sau TV Show)
            type_label = "Movie" if stype == 'movie' else "TV Show"
            
            # FORMATUL CERUT: History: titlu(Type) bold+inclinat
            label = f"History: [B][I][COLOR FFCA762B]{query} [/COLOR][/I][/B] ({type_label})"
            
            # Context Menu pentru Edit si Delete
            cm = [
                ('Edit Search', f"RunPlugin({sys.argv[0]}?mode=edit_search&query={quote(query)}&type={stype})"),
                ('Delete Search', f"RunPlugin({sys.argv[0]}?mode=delete_search&query={quote(query)}&type={stype})")
            ]
            
            # Parametrii pentru a rula din nou cautarea la click
            url_params = {'mode': 'perform_search_query', 'query': query, 'type': stype}
            
            # Adaugam cu iconita search.png
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
        add_directory(f"[B][COLOR FF00CED1]TMDB: {session.get('username', 'Connected')}[/COLOR][/B]", {'mode': 'noop'}, folder=False, icon='DefaultUser.png')
        add_directory("[COLOR red]Disconnect TMDB[/COLOR]", {'mode': 'tmdb_logout'}, folder=False, icon='DefaultIconError.png')
    else:
        add_directory("[B][COLOR FF00CED1]Connect TMDB[/COLOR][/B]", {'mode': 'tmdb_auth'}, folder=False, icon='DefaultUser.png')

    trakt_token = ADDON.getSetting('trakt_access_token')
    if trakt_token:
        user = trakt_api.get_trakt_username(trakt_token)
        ADDON.setSetting('trakt_status', f"Connected: {user}")
        add_directory(f"[B][COLOR pink]Trakt: {user}[/COLOR][/B]", {'mode': 'noop'}, folder=False, icon='DefaultUser.png')
        add_directory("[COLOR red]Disconnect Trakt[/COLOR]", {'mode': 'trakt_revoke'}, folder=False, icon='DefaultIconError.png')
        add_directory("[COLOR FF6AFB92]Smart Sync[/COLOR]", {'mode': 'trakt_sync_smart_action'}, folder=False, icon='DefaultAddonService.png')
        add_directory("[COLOR cyan]Force Full Sync[/COLOR]", {'mode': 'trakt_sync_action'}, folder=False, icon='DefaultAddonService.png')
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
        # Dinamic: Cele mai votate/adaugate la favorite filme din ultimele 60 de zile
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
            f"&with_original_language=en"            # ✅ Doar limba engleza (corect)
            f"&page={page_no}"
            f"&region=US"
            f"&primary_release_date.gte={tomorrow}"
            f"&primary_release_date.lte={max_date}"  # ✅ Max 120 zile (nu filme din 2028)
            f"&sort_by=primary_release_date.asc"             # ✅ Cele mai populare primele
            f"&without_genres=99"             # ✅ Fara documentare
            f"&with_runtime.gte=60"                  # ✅ Fara scurtmetraje
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
        # LOGICA BLOCKBUSTERS: Toate timpurile, incasari gigantice, minim 500 voturi
        url = f"{BASE_URL}/discover/movie?api_key={API_KEY}&language={LANG}&page={page_no}&sort_by=revenue.desc&vote_count.gte=500"

    elif action == 'tmdb_movies_box_office':
        # LOGICA TOP BOX OFFICE: Cele mai mari incasari din ULTIMUL AN
        year_ago = (datetime.date.today() - datetime.timedelta(days=365)).strftime('%Y-%m-%d')
        url = f"{BASE_URL}/discover/movie?api_key={API_KEY}&language={LANG}&page={page_no}&primary_release_date.gte={year_ago}&sort_by=revenue.desc"
        
    elif action == 'tmdb_movies_premieres':
        current_date, previous_date = get_dates(31, reverse=True)
        url += f"&release_date.gte={previous_date}&release_date.lte={current_date}&with_release_type=1|3|2&sort_by=popularity.desc"
        
    elif action == 'tmdb_movies_latest_releases':
        current_date = datetime.date.today().strftime('%Y-%m-%d')
        # Filtram strict dupa lansarea Digitala (with_release_type=4)
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
        # Premieres = Digital releases din ultima luna
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
        # In Theaters = In cinematografe acum
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
        # Upcoming = Filme care urmeaza, sortate CRONOLOGIC (cele mai apropiate primele)
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        url = (
            f"{BASE_URL}/discover/movie?api_key={API_KEY}&language=en-US"
            f"&with_original_language={INDIAN_LANGS}"
            f"&primary_release_date.gte={tomorrow}"
            f"&sort_by=primary_release_date.asc"
            f"&page={page_no}"
        )

    elif action == 'hindi_movies_anticipated':
        # Anticipated = Filme viitoare sortate dupa POPULARITATE (cele cu hype)
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        url = (
            f"{BASE_URL}/discover/movie?api_key={API_KEY}&language=en-US"
            f"&with_original_language={INDIAN_LANGS}"
            f"&primary_release_date.gte={tomorrow}"
            f"&sort_by=popularity.desc"
            f"&page={page_no}"
        )

    # =========================================================================
    # ROMANIAN MOVIES (Filme Romanesti)
    # =========================================================================
    elif action == 'romania_movies_latest':
        current_date = datetime.date.today().strftime('%Y-%m-%d')
        url = (
            f"{BASE_URL}/discover/movie?api_key={API_KEY}&language=ro-RO"
            f"&with_original_language=ro"
            f"&primary_release_date.lte={current_date}"
            f"&sort_by=primary_release_date.desc"
            f"&with_runtime.gte=40&vote_count.gte=2"
            f"&page={page_no}"
        )
    elif action == 'romania_movies_trending':
        year_ago = (datetime.date.today() - datetime.timedelta(days=365)).strftime('%Y-%m-%d')
        url = (
            f"{BASE_URL}/discover/movie?api_key={API_KEY}&language=ro-RO"
            f"&with_original_language=ro"
            f"&primary_release_date.gte={year_ago}"
            f"&sort_by=popularity.desc"
            f"&with_runtime.gte=40&vote_count.gte=2"
            f"&page={page_no}"
        )
    elif action == 'romania_movies_popular':
        url = (
            f"{BASE_URL}/discover/movie?api_key={API_KEY}&language=ro-RO"
            f"&with_original_language=ro"
            f"&sort_by=popularity.desc"
            f"&with_runtime.gte=40&vote_count.gte=2"
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
            f"&with_runtime.gte=40&vote_count.gte=2"
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
            f"&with_runtime.gte=40&vote_count.gte=2"
            f"&page={page_no}"
        )

    return requests.get(url, timeout=15)


def get_tmdb_tv_standard(action, page_no):
    import requests # Lazy loading
    
    if action == 'tmdb_tv_popular':
        url = f"{BASE_URL}/tv/popular?api_key={API_KEY}&language={LANG}&page={page_no}"
    elif action == 'tmdb_tv_premieres':
        url = f"{BASE_URL}/discover/tv?api_key={API_KEY}&language={LANG}&page={page_no}&with_original_language=en&region=US"
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
        # Dinamic: Cele mai votate/adaugate la favorite seriale din ultimele 90 de zile
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
        url = f"{BASE_URL}/discover/tv?api_key={API_KEY}&language={LANG}&page={page_no}&with_original_language=en&region=US&sort_by=popularity.desc&first_air_date.gte={current_date}&first_air_date.lte={future_date}"
    
    elif action == 'tmdb_tv_trending_day':
        url = f"{BASE_URL}/trending/tv/day?api_key={API_KEY}&language={LANG}&page={page_no}"
        
    elif action == 'tmdb_tv_trending_week':
        url = f"{BASE_URL}/trending/tv/week?api_key={API_KEY}&language={LANG}&page={page_no}"

    # =========================================================================
    # ROMANIAN TV SHOWS (Seriale Romanesti)
    # =========================================================================
    elif action == 'romania_tv_latest':
        current_date = datetime.date.today().strftime('%Y-%m-%d')
        url = (
            f"{BASE_URL}/discover/tv?api_key={API_KEY}&language=ro-RO"
            f"&with_original_language=ro"
            f"&first_air_date.lte={current_date}"
            f"&sort_by=first_air_date.desc"
            f"&vote_count.gte=2"
            f"&page={page_no}"
        )
    elif action == 'romania_tv_trending':
        year_ago = (datetime.date.today() - datetime.timedelta(days=365)).strftime('%Y-%m-%d')
        url = (
            f"{BASE_URL}/discover/tv?api_key={API_KEY}&language=ro-RO"
            f"&with_original_language=ro"
            f"&first_air_date.gte={year_ago}"
            f"&sort_by=popularity.desc"
            f"&vote_count.gte=2"
            f"&page={page_no}"
        )
    elif action == 'romania_tv_popular':
        url = (
            f"{BASE_URL}/discover/tv?api_key={API_KEY}&language=ro-RO"
            f"&with_original_language=ro"
            f"&sort_by=popularity.desc"
            f"&vote_count.gte=2"
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
            f"&vote_count.gte=2"
            f"&page={page_no}"
        )

    return requests.get(url, timeout=15)


def build_movie_list(params):
    # --- PRIORITATE FOREGROUND ---
    window = xbmcgui.Window(10000)
    window.setProperty('tmdbmovies_loading_active', 'true')
    
    # Adaugam un mic delay daca fundalul era ocupat, sa-i dam timp sa se opreasca
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

    # Fetch multiple API pages daca PAGE_LIMIT > 20
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
        if api_page == start_api_page + api_pages_needed - 1:
            more_pages = True
        if len(results) < ITEMS_PER_API_PAGE:
            break

    if not all_results:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    current_items = all_results[:PAGE_LIMIT]
    has_next = len(all_results) > PAGE_LIMIT or more_pages

# Pre-warm + procesare: prefetch populeaza RAM pool, apoi _process_movie_item citeste instant din cache
    cache_list = []
    items_to_add = []

    prefetch_metadata_parallel(current_items, 'movie')

    for item in current_items:
        processed = _process_movie_item(item, return_data=True, skip_details=True)
        if processed:
            cache_list.append(processed)
            items_to_add.append((processed['url'], processed['li'], processed['is_folder']))

# --- FIX PAGINARE SI CACHE ---
    if has_next:
        # Cream manual item-ul de Next Page
        next_label = f"[B]Next Page ({page+1}) >>[/B]"
        next_params = {'mode': 'build_movie_list', 'action': action, 'new_page': str(page + 1)}
        next_url = f"{sys.argv[0]}?{urlencode(next_params)}"
        
        next_li = xbmcgui.ListItem(next_label)
        next_li.setArt({'icon': NEXT_PAGE_ICON, 'thumb': NEXT_PAGE_ICON})
        
        # 1. Adaugam la afisare imediata
        items_to_add.append((next_url, next_li, True))
        
        # 2. Adaugam la Cache RAM (STRUCTURA CORECTATA PENTRU A EVITA KeyError 'li')
        cache_list.append({
            'url': next_url,
            'li': next_li,          # <--- ADAUGAT (CRITIC PENTRU CACHE)
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
    
    # Pre-fetch paginile urmatoare INAINTE de endOfDirectory (maxim timp pentru thread)
    trigger_next_page_warmup(action, page, 'movie')
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=True)
    # Important: Curatam proprietatea ca sa stie fundalul ca am terminat
    window.clearProperty('tmdbmovies_loading_active')
    
    # Save to RAM
    set_fast_cache(cache_key, [{'label': i['li'].getLabel(), 'url': i['url'], 'is_folder': i['is_folder'], 
                                'art': i['art'], 'info': i['info'], 'cm': i['cm_items'], 
                                'resume_time': i['resume_time'], 'total_time': i['total_time']} for i in cache_list])


def build_tvshow_list(params):
    window = xbmcgui.Window(10000)
    window.setProperty('tmdbmovies_loading_active', 'true')
    
    # Adaugam un mic delay daca fundalul era ocupat, sa-i dam timp sa se opreasca
    if xbmcgui.Window(10000).getProperty('tmdbmovies_warmup_busy') == 'true':
        xbmc.sleep(100)
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

    # Fetch multiple API pages daca PAGE_LIMIT > 20
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
        if api_page == start_api_page + api_pages_needed - 1:
            more_pages = True
        if len(results) < ITEMS_PER_API_PAGE:
            break

    if not all_results:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    current_items = all_results[:PAGE_LIMIT]
    has_next = len(all_results) > PAGE_LIMIT or more_pages

# Pre-warm + procesare: prefetch populeaza RAM pool, apoi _process_tv_item citeste instant din cache
    cache_list = []
    items_to_add = []

    prefetch_metadata_parallel(current_items, 'tv')

    for item in current_items:
        processed = _process_tv_item(item, return_data=True, skip_details=True)
        if processed:
            cache_list.append(processed)
            items_to_add.append((processed['url'], processed['li'], processed['is_folder']))

# --- FIX PAGINARE SI CACHE ---
    if has_next:
        # Cream manual item-ul de Next Page
        next_label = f"[B]Next Page ({page+1}) >>[/B]"
        next_params = {'mode': 'build_tvshow_list', 'action': action, 'new_page': str(page + 1)}
        next_url = f"{sys.argv[0]}?{urlencode(next_params)}"
        
        next_li = xbmcgui.ListItem(next_label)
        next_li.setArt({'icon': NEXT_PAGE_ICON, 'thumb': NEXT_PAGE_ICON})
        
        # 1. Adaugam la afisare
        items_to_add.append((next_url, next_li, True))
        
        # 2. Adaugam la Cache RAM (STRUCTURA CORECTATA)
        cache_list.append({
            'url': next_url,
            'li': next_li,          # <--- ADAUGAT (CRITIC)
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

    # Pre-fetch paginile urmatoare INAINTE de endOfDirectory (maxim timp pentru thread)
    trigger_next_page_warmup(action, page, 'tv')
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=True)
    # Important: Curatam proprietatea ca sa stie fundalul ca am terminat
    window.clearProperty('tmdbmovies_loading_active')
    
    # Save to RAM
    set_fast_cache(cache_key, [{'label': i['li'].getLabel(), 'url': i['url'], 'is_folder': i['is_folder'], 
                                'art': i['art'], 'info': i['info'], 'cm': i['cm_items'], 
                                'resume_time': 0, 'total_time': 0} for i in cache_list])

def _get_full_context_menu(tmdb_id, content_type, title='', is_in_favorites_view=False, year='', season=None, episode=None, imdb_id=''):
    cm = []
    # info_params = urlencode({'mode': 'show_info', 'type': content_type, 'tmdb_id': tmdb_id})
    # cm.append(('[B][COLOR FFFDBD01]TMDb Info[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{info_params})"))
    
    # --- ADAUGAT EXTENDED INFO (Metoda cu argumente explicite) ---
    # Folosim calea speciala pentru a fi siguri ca gaseste scriptul
    # Trimitem id si type ca argumente separate prin virgula
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

    # --- INSEREAZA RANDURILE ASTEA PENTRU MDB: ---
    mdb_params_dict = {'mode': 'mdblist_context_menu', 'tmdb_id': tmdb_id, 'type': content_type, 'title': title, 'imdb_id': imdb_id}
    cm.append(('[B][COLOR lightskyblue]My MDBList[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{urlencode(mdb_params_dict)})"))

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

    # --- Mark as Watched/Unwatched direct in root menu ---
    from resources.lib.watched_provider import get_label as _prov_label, get_color as _prov_color
    _prov_lbl = _prov_label()
    _prov_clr = _prov_color()
    _w_label = f'[B][COLOR FF6AFB92]Mark Watched [COLOR {_prov_clr}]({_prov_lbl})[/COLOR][/B]'
    _uw_label = f'[B][COLOR FFE41B17]Mark Unwatched [COLOR {_prov_clr}]({_prov_lbl})[/COLOR][/B]'
    if content_type == 'movie':
        from resources.lib.watched_provider import is_movie_watched as _is_mw
        _is_w = _is_mw(tmdb_id)
        _w_sp = urlencode({'mode': 'mark_watched', 'tmdb_id': tmdb_id, 'type': 'movie'})
        _uw_sp = urlencode({'mode': 'mark_unwatched', 'tmdb_id': tmdb_id, 'type': 'movie'})
        cm.append((_uw_label if _is_w else _w_label, f"RunPlugin({sys.argv[0]}?{_uw_sp if _is_w else _w_sp})"))
    elif content_type in ('tv', 'show'):
        from resources.lib.watched_provider import get_watched_counts as _get_wc
        _is_w = (_get_wc(tmdb_id, 'tv') > 0)
        _w_sp = urlencode({'mode': 'mark_watched', 'tmdb_id': tmdb_id, 'type': 'tv'})
        _uw_sp = urlencode({'mode': 'mark_unwatched', 'tmdb_id': tmdb_id, 'type': 'tv'})
        cm.append((_uw_label if _is_w else _w_label, f"RunPlugin({sys.argv[0]}?{_uw_sp if _is_w else _w_sp})"))
    elif content_type == 'episode':
        if season is not None and episode is not None:
            _w_sp = urlencode({'mode': 'mark_watched', 'tmdb_id': tmdb_id, 'type': 'episode', 'season': str(season), 'episode': str(episode)})
            cm.append((_w_label, f"RunPlugin({sys.argv[0]}?{_w_sp})"))
    # ---------------------------------------------------------
    
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
    
    # Recunoastem procentele noi (<90) dar si formatul vechi de resume (>= 1000000)
    if progress > 0 and (progress < 90 or progress >= 1000000):
        rem_params = {'mode': 'remove_progress', 'tmdb_id': tmdb_id, 'type': content_type}
        if season: rem_params['season'] = str(season)
        if episode: rem_params['episode'] = str(episode)
        cm.append(('[B][COLOR red]Delete Resume[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{urlencode(rem_params)})"))

    return cm

def _process_movie_item(item, is_in_favorites_view=False, return_data=False, skip_details=False):
    from resources.lib import watched_provider
    tmdb_id = str(item.get('id', ''))
    if not tmdb_id: return None  # Returnam None daca nu e ID valid

    title = item.get('title') or 'Unknown'
    year = str(item.get('release_date', ''))[:4]
    plot = item.get('overview', '')
    
    full_details = (get_tmdb_item_details(tmdb_id, 'movie', lightweight=True) or {}) if not skip_details else _get_cached_details(tmdb_id, 'movie')
    
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
    
    # Acum full_details are DEJA RO in el automat!
    tagline = full_details.get('tagline', '').strip()
    genres_str = get_genres_string(item.get('genre_ids',[]))
    if not genres_str and full_details.get('genres'):
        genres_str = ", ".join([g['name'] for g in full_details['genres']])
        
    plot = full_details.get('overview') or item.get('overview', '')
    
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

    # --- LOGICA CULOARE ROSIE FILME NELANSATE ---
    display_title = f"{title} ({year})" if year else title
    if premiered:
        try:
            p_str = str(premiered)[:10]
            parts = p_str.split('-')
            release_date = datetime.date(int(parts[0]), int(parts[1]), int(parts[2]))
            today = datetime.date.today()
            if release_date > today:
                if release_date == today:
                    date_label = f"[B][COLOR white](Today)[/COLOR][/B]"
                elif release_date == today + datetime.timedelta(days=1):
                    date_label = f"[B][COLOR white](Tomorrow)[/COLOR][/B]"
                else:
                    date_label = f"[B][COLOR white]({parts[2]}.{parts[1]}.{parts[0]})[/COLOR][/B]"
                display_title = f"[B][COLOR FFE238EC]{display_title}[/COLOR] {date_label}"
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

    is_watched = watched_provider.get_watched_counts(tmdb_id, 'movie') > 0
    if is_watched and '[COLOR' not in display_title:
        display_title = f'[B][COLOR FF6AFB92]{display_title}[/COLOR][/B]'

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

    # Adauga clearlogo=movie_logo in apelul functiei
    xbmcplugin.addDirectoryItem(HANDLE, f"{sys.argv[0]}?{urlencode(url_params)}", li, False)


def _process_tv_item(item, is_in_favorites_view=False, return_data=False, skip_details=False):
    from resources.lib import trakt_api
    tmdb_id = str(item.get('id', ''))
    if not tmdb_id: return None

    title = item.get('name', item.get('title', 'Unknown'))
    year = str(item.get('first_air_date', ''))[:4]
    plot = item.get('overview', '')

    full_details = (get_tmdb_item_details(tmdb_id, 'tv', lightweight=True) or {}) if not skip_details else _get_cached_details(tmdb_id, 'tv')
    # --- FALLBACK TITLU: cand itemul n-are nume (ex: dropped din DB), luam din metadata ---
    if not title or title == 'Unknown':
        title = full_details.get('name') or 'Unknown'
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
    
    # 1. Datele de baza in engleza
    tagline = full_details.get('tagline', '').strip()
    genres_str = get_genres_string(item.get('genre_ids',[]))
    if not genres_str and full_details.get('genres'):
        genres_str = ", ".join([g['name'] for g in full_details['genres']])
        
    plot = full_details.get('overview') or item.get('overview', '')
    
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

    # --- LOGICA CULOARE ROSIE SERIALE NELANSATE ---
    display_name = f"{title} ({year})" if year else title
    if premiered:
        try:
            p_str = str(premiered)[:10]
            parts = p_str.split('-')
            release_date = datetime.date(int(parts[0]), int(parts[1]), int(parts[2]))
            today = datetime.date.today()
            if release_date > today:
                if release_date == today:
                    date_label = f"[B][COLOR white](Today)[/COLOR][/B]"
                elif release_date == today + datetime.timedelta(days=1):
                    date_label = f"[B][COLOR white](Tomorrow)[/COLOR][/B]"
                else:
                    date_label = f"[B][COLOR white]({parts[2]}.{parts[1]}.{parts[0]})[/COLOR][/B]"
                display_name = f"[B][COLOR FFE238EC]{display_name}[/COLOR] {date_label}"
        except: pass

    poster_path = full_details.get('poster_path', item.get('poster_path', ''))
    poster = f"{IMG_BASE}{poster_path}" if poster_path else TMDbmovies_ICON
    backdrop_path = full_details.get('backdrop_path', item.get('backdrop_path', ''))
    backdrop = f"{BACKDROP_BASE}{backdrop_path}" if backdrop_path else ''

    watched_info = get_watched_status_tvshow(tmdb_id)
    
    # Asiguram-ne ca valorile sunt intotdeauna numere intregi (evitam eroarea cu NoneType)
    w_watched = int(watched_info.get('watched') or 0)
    w_total = int(watched_info.get('total') or 0)
    
    # Verificam daca serialul este vazut complet pentru bifa
    is_watched = w_watched >= w_total if w_total > 0 else False
    if is_watched and '[COLOR' not in display_name:
        display_name = f'[B][COLOR FF6AFB92]{display_name}[/COLOR][/B]'
    
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
            'art': art,  # ACUM TRIMIT TOATE ART-URILE INCLUZAND LOGO!
            'cm_items': cm,
            'label': display_name
        }
    # ----------------------------------------

    xbmcplugin.addDirectoryItem(HANDLE, f"{sys.argv[0]}?{urlencode(url_params)}", li, True)


# Optimized get_watched_status_tvshow
def get_watched_status_tvshow(tmdb_id):
    from resources.lib import watched_provider, trakt_sync
    str_id = str(tmdb_id)
    watched_count = watched_provider.get_watched_counts(tmdb_id, 'tv')

    if str_id in TV_META_CACHE:
        total_eps = TV_META_CACHE[str_id]
    else:
        total_eps = trakt_sync.get_tv_meta_from_db(str_id)
        TV_META_CACHE[str_id] = total_eps

    if not total_eps and watched_count > 0:
        details = get_tmdb_item_details(str_id, 'tv')
        if details:
            total_eps = details.get('number_of_episodes', 0)
            if total_eps:
                trakt_sync.set_tv_meta_to_db(str_id, total_eps)
        else:
            total_eps = 0
        TV_META_CACHE[str_id] = total_eps

    return {'watched': watched_count, 'total': total_eps}
# --------------------------------------------------------------------


# TMDB V4 AUTH -------------------

def get_tmdb_v4_token():
    """Citeste token-ul v4 al utilizatorului din fisierul local."""
    data = read_json(TMDB_V4_TOKEN_FILE)
    if data and data.get('access_token'):
        return data['access_token']
    return None

def tmdb_auth():
    """Autentificare TMDb cu QR code (v4, stil Umbrella) — singura metoda de conectare."""
    dialog = xbmcgui.Dialog()
    
    # Verificam daca avem cheia de develop in config
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
        
        # 2. Construim URL-ul de aprobare
        url_full = f"https://www.themoviedb.org/auth/access?request_token={request_token}"
        
        # Copiem link-ul in clipboard (daca e pe PC/Android)
        xbmc.executebuiltin(f'SetProperty(TMDbAuthLink,{url_full},home)')
        
        # --- GENERARE LINK SCURT (TinyURL) — doar pentru afisare; QR-ul are URL-ul complet ---
        try:
            r_tiny = requests.get(f'http://tinyurl.com/api-create.php?url={url_full}', timeout=5)
            if r_tiny.status_code == 200 and r_tiny.text.startswith('http'):
                url_display = r_tiny.text.strip()
            else:
                url_display = url_full  # Fallback la cel lung
        except:
            url_display = url_full
        
        # a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•
        # QR CODE AUTH (stil Umbrella) — dialog custom cu QR + cod
        # doModal() pe MAIN THREAD (input garantat); polling in background
        # a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•
        import threading
        from resources.lib.utils import make_qr
        from resources.lib.auth_dialog import QRProgressDialog, run_modal_main_thread

        qr_path = make_qr(url_full, 'tmdb_v4_qr.png')
        msg = (f"1. Open this link in browser:\n"
               f"[B][COLOR FF00CED1]{url_display}[/COLOR][/B]\n"
               f"2. Log in and press [B]Approve[/B]")

        pdialog = QRProgressDialog(
            'auth_qr.xml', ADDON.getAddonInfo('path'), 'Default', '1080i',
            heading='[B][COLOR FF00CED1]TMDb Authentication[/COLOR][/B]',
            qr_image=qr_path or '',
            icon=TMDB_ICON,
            addon_icon=os.path.join(ADDON.getAddonInfo('path'), 'icon.png'),
            content=msg,
        )

        log(f"[TMDB] Auth: aproba acest link (doar el conteaza): {url_full}", xbmc.LOGINFO)

        _result = {}
        _mon = xbmc.Monitor()
        expires_in = 3600  # Request token TMDb v4: valid 60 minute

        def _poll():
            start_time = time.time()
            polls = 0
            while not pdialog.iscanceled() and not _mon.abortRequested():
                elapsed = time.time() - start_time
                if elapsed > expires_in:
                    pdialog.expired = True
                    pdialog.close()
                    return
                percent = max(0, int(100 - (elapsed / expires_in * 100)))
                pdialog.update(percent, msg)
                time.sleep(5)
                try:
                    # Inainte de aprobare raspunde cu 422/41 (nu invalideaza token-ul);
                    # dupa Approve pe site, prima apelare cu succes schimba token-ul.
                    r2 = requests.post('https://api.themoviedb.org/4/auth/access_token',
                                       headers=headers,
                                       json={'request_token': request_token},
                                       timeout=15)
                    data2 = r2.json()
                    polls += 1
                    if data2.get('success'):
                        log(f"[TMDB] Access token granted after {polls} poll(s)", xbmc.LOGINFO)
                        _result['data'] = data2
                        _result['polls'] = polls
                        _result['last'] = 'approved'
                        pdialog.close()
                        return
                    _result['polls'] = polls
                    _result['last'] = f"HTTP {r2.status_code} code {data2.get('status_code')}"
                    if data2.get('status_code') != 41:
                        log(f"[TMDB] Poll {polls}: {_result['last']} {data2.get('status_message')}", xbmc.LOGWARNING)
                except Exception as e:
                    polls += 1
                    _result['polls'] = polls
                    _result['last'] = f"EXC {e!r}"
                    log(f"[TMDB] Poll {polls} exception: {e!r}", xbmc.LOGWARNING)

        threading.Thread(target=_poll, daemon=True).start()
        log(f"[TMDB] QR dialog deschis — poll la fiecare 5s", xbmc.LOGINFO)
        run_modal_main_thread(pdialog)
        pdialog.close()

        # 3. Schimbam Request Token pe Access Token (Final)
        data2 = _result.get('data')
        if data2:
            username = 'User'
            try:
                acc_headers = {'Authorization': f"Bearer {data2['access_token']}"}
                acc_r = requests.get(f"{BASE_URL}/account", headers=acc_headers, timeout=10)
                if acc_r.status_code == 200:
                    username = acc_r.json().get('username', 'User')
            except:
                pass

            write_json(TMDB_V4_TOKEN_FILE, {
                'access_token': data2['access_token'],
                'account_id': data2['account_id'],
                'username': username
            })
            ADDON.setSetting('tmdb_status', f"Connected: {username}")
            dialog.notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", f"Connected: [B][COLOR FFF70D1A]{username}[/COLOR][/B]", TMDB_ICON, 3000, False)
            
            # a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•
            # ADAUGAT: Actualizare automata a listelor (inclusiv seriale v4)
            # a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•
            t = threading.Thread(target=trakt_sync.sync_full_library, kwargs={'silent': False, 'force': True})
            t.daemon = True
            t.start()
            # a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•a•
        elif pdialog.expired:
            dialog.notification("TMDb", "Request expired. Try again.", xbmcgui.NOTIFICATION_ERROR)
        elif not pdialog.iscanceled():
            dialog.notification("Error", "You did not approve.", xbmcgui.NOTIFICATION_ERROR)
        else:
            log(f"[TMDB] Auth dialog closed by user; polls={_result.get('polls', 0)} last={_result.get('last', 'never')}", xbmc.LOGWARNING)
            if _result.get('polls', 0) > 0:
                dialog.notification("TMDb", "No approval detected. Close ALL old TMDb tabs in browser, then approve the NEW link shown on screen.", xbmcgui.NOTIFICATION_WARNING)
            
    except Exception as e:
        log(f"[TMDB] Auth Error: {e}", xbmc.LOGERROR)
        dialog.notification("Error", "Check the log", xbmcgui.NOTIFICATION_ERROR)



# ------------------

def get_tmdb_session():
    """Returneaza datele contului TMDb autentificat cu QR (v4): account_id, access_token, username."""
    data = read_json(TMDB_V4_TOKEN_FILE)
    # Verificam intai daca data exista si este un dictionar
    if data and isinstance(data, dict):
        if data.get('access_token') and data.get('account_id'):
            return data
    return None


def tmdb_auth_v4():
    """Alias pentru compatibilitate — aceeasi autentificare QR ca tmdb_auth()."""
    return tmdb_auth()

def tmdb_logout():
    # --- START PROTECTIE DECONECTARE ACCIDENTALA ---
    if not xbmcgui.Dialog().yesno("[B][COLOR FF00CED1]Disconnect TMDb[/COLOR][/B]", "Are you sure you want to disconnect your TMDb account?"):
        return
    # --- END PROTECTIE ---

    # Sesiune veche v3 (daca a ramas dinainte de migrarea pe QR/v4)
    old_session = read_json(TMDB_SESSION_FILE)
    if old_session and isinstance(old_session, dict) and old_session.get('session_id'):
        try:
            url = f"{BASE_URL}/authentication/session?api_key={API_KEY}"
            requests.delete(url, json={'session_id': old_session['session_id']}, timeout=10)
        except:
            pass

    if xbmcvfs.exists(TMDB_SESSION_FILE):
        xbmcvfs.delete(TMDB_SESSION_FILE)
    if xbmcvfs.exists(TMDB_V4_TOKEN_FILE):
        xbmcvfs.delete(TMDB_V4_TOKEN_FILE)
    if xbmcvfs.exists(TMDB_LISTS_CACHE_FILE):
        xbmcvfs.delete(TMDB_LISTS_CACHE_FILE)

    ADDON.setSetting('tmdb_status', "Disconnected")

    xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "User Disconnected", TMDB_ICON, 3000, False)
    xbmc.executebuiltin("Container.Refresh")

def tmdb_auth_request(path, method='GET', data=None, params=None, v4=False):
    """Cerere autentificata TMDb cu token-ul v4 al utilizatorului (Authorization: Bearer).
    v4=True  → base https://api.themoviedb.org/4
    v4=False → base https://api.themoviedb.org/3 (v3 accepta Bearer v4, fara api_key)
    """
    token = get_tmdb_v4_token()
    if not token:
        return None

    url = f"{TMDB_V4_BASE_URL if v4 else BASE_URL}{path}"

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json;charset=utf-8'
    }

    try:
        if method == 'GET':
            r = requests.get(url, headers=headers, params=params, timeout=15)
        elif method == 'POST':
            r = requests.post(url, headers=headers, json=data, params=params, timeout=15)
        elif method == 'DELETE':
            r = requests.delete(url, headers=headers, json=data, params=params, timeout=15)
        else:
            return None

        if r.status_code in [200, 201, 204]:
            if r.status_code == 204 or not r.text:
                return {}
            return r.json()
        else:
            log(f"[TMDB] Auth request failed: {r.status_code} {r.text}", xbmc.LOGERROR)
            return None
    except Exception as e:
        log(f"[TMDB] Auth request error: {e}", xbmc.LOGERROR)
        return None


def tmdb_v4_request(endpoint, method='GET', data=None):
    """Cerere v4 cu token-ul utilizatorului (inainte folosea API read token)."""
    return tmdb_auth_request(endpoint, method=method, data=data, v4=True)


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
        return []

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
            description = lst.get('description', '')  # ✅ ADAUGAT
            
            # Citim poster si backdrop din SQL
            poster_path = lst.get('poster', '')
            backdrop_path = lst.get('backdrop', '')
            
            # Construim URL-urile complete
            poster = get_list_image_url(poster_path, 'poster') if poster_path else TMDB_ICON
            fanart = get_list_image_url(backdrop_path, 'fanart') if backdrop_path else ''
            
            cm = [
                ('Refresh Lists', f"RunPlugin({sys.argv[0]}?mode=tmdb_refresh_lists)"), 
            ]

            # ✅ ADAUGAT: info cu plot (description)
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
    
    # 1. Incercam SQL
    results = trakt_sync.get_recommendations_from_db(content_type)
    
    # 2. Fallback: daca SQL e gol, fortam sync si reincarcam
    if not results:
        try:
            log("[TMDB] Recommendations goale in SQL, fortam sync...")
            conn = trakt_sync.get_connection()
            c = conn.cursor()
            trakt_sync._sync_tmdb_recommendations_fast(c)
            conn.commit()
            conn.close()
            
            # Reincarcam dupa sync
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
            f"[B]Next Page ({page+1}) >>[/B]", 
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
    
    # REPARAT NameError: folosim variabila m_type determinata corect
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
    token = get_tmdb_v4_token()
    if not token:
        return None
    url = f"{TMDB_V4_BASE_URL}/account/{session['account_id']}/{endpoint}"
    headers = {'Authorization': f'Bearer {token}'}
    return requests.get(url, headers=headers, params={'language': LANG, 'page': page_no, 'sort_by': 'created_at.desc'}, timeout=10)


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

        endpoint = f"{'movie' if content_type == 'movie' else 'tv'}/watchlist"
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
        # Adaugam butonul Next Page manual pentru Batch/Cache
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
    
    # Salvam in RAM
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

        endpoint = f"{'movie' if content_type == 'movie' else 'tv'}/favorites"
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
    m_type = 'tv' if content_type in ('tv', 'tvshow', 'episode', 'season', 'show') else 'movie'
    # v4 NU are POST pentru watchlist (404). Endpoint-ul corect e v3:
    # POST /3/account/{account_id}/watchlist — hex account_id v4 functioneaza cu Bearer (verificat live 201).
    result = tmdb_auth_request(f"/account/{session['account_id']}/watchlist", method='POST',
                               data={'media_type': m_type, 'media_id': int(tmdb_id), 'watchlist': True}, v4=False)
    if result and result.get('success', True):
        details = get_tmdb_item_details(str(tmdb_id), content_type) or {}
        d_title = details.get('title') or details.get('name', 'Unknown')
        d_year = str(details.get('release_date') or details.get('first_air_date', ''))[:4]
        d_poster = details.get('poster_path', '')
        d_overview = details.get('overview', '')
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]",
                                      f"[B][COLOR yellow]{d_title}[/COLOR][/B] added to [B][COLOR FF00CED1]Watchlist[/COLOR][/B]",
                                      TMDB_ICON, 3000, False)
        
        # --- FIX BUFFERING: SQL INSTANT ---
        try:
            # 1. Update SQL Instant
            conn = trakt_sync.get_connection()
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO tmdb_account_lists VALUES (?,?,?,?,?,?,?,?)", 
                      ('watchlist', m_type, str(tmdb_id), d_title, d_year, d_poster, str(time.time()), d_overview))
            conn.commit()
            conn.close()
        except: pass

        # 2. Refresh UI Imediat (ca sa dispara rotita)
        from resources.lib.cache import clear_all_fast_cache
        clear_all_fast_cache()
        xbmc.executebuiltin("Container.Refresh")
        
        return True
        # -------------------------------------------------
    return False

def remove_from_tmdb_watchlist(content_type, tmdb_id):
    session = get_tmdb_session()
    if not session: return False
    m_type = 'tv' if content_type in ('tv', 'tvshow', 'episode', 'season', 'show') else 'movie'
    result = tmdb_auth_request(f"/account/{session['account_id']}/watchlist", method='POST',
                               data={'media_type': m_type, 'media_id': int(tmdb_id), 'watchlist': False}, v4=False)
    if result and result.get('success', True):
        details = get_tmdb_item_details(str(tmdb_id), content_type) or {}
        d_title = details.get('title') or details.get('name', 'Unknown')
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]",
                                      f"[B][COLOR yellow]{d_title}[/COLOR][/B] removed from [B][COLOR FF00CED1]Watchlist[/COLOR][/B]",
                                      TMDB_ICON, 3000, False)
        
        # --- FIX BUFFERING: SQL INSTANT ---
        try:
            conn = trakt_sync.get_connection()
            c = conn.cursor()
            c.execute("DELETE FROM tmdb_account_lists WHERE list_type=? AND media_type=? AND tmdb_id=?", 
                      ('watchlist', m_type, str(tmdb_id)))
            conn.commit()
            conn.close()
        except: pass
        
        from resources.lib.cache import clear_all_fast_cache
        clear_all_fast_cache()
        xbmc.executebuiltin("Container.Refresh")
        
        return True
        # -------------------------------------------------
    return False


def add_to_tmdb_favorites(content_type, tmdb_id):
    session = get_tmdb_session()
    if not session:
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Not connected", TMDB_ICON, 3000, False)
        return False

    m_type = 'tv' if content_type in ('tv', 'tvshow', 'episode', 'season', 'show') else 'movie'
    # v4 NU are POST pentru favorites (404). Endpoint-ul corect e v3:
    # POST /3/account/{account_id}/favorite — hex account_id v4 functioneaza cu Bearer (verificat live 201).
    result = tmdb_auth_request(f"/account/{session['account_id']}/favorite", method='POST',
                               data={'media_type': m_type, 'media_id': int(tmdb_id), 'favorite': True}, v4=False)

    if result and result.get('success', True):
        details = get_tmdb_item_details(str(tmdb_id), content_type) or {}
        d_title = details.get('title') or details.get('name', 'Unknown')
        d_year = str(details.get('release_date') or details.get('first_air_date', ''))[:4]
        d_poster = details.get('poster_path', '')
        d_overview = details.get('overview', '')
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]",
                                      f"[B][COLOR yellow]{d_title}[/COLOR][/B] added to [B][COLOR FF00CED1]Favorites[/COLOR][/B]",
                                      TMDB_ICON, 3000, False)
        
        # --- FIX BUFFERING: SQL INSTANT ---
        try:
            conn = trakt_sync.get_connection()
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO tmdb_account_lists VALUES (?,?,?,?,?,?,?,?)", 
                      ('favorite', m_type, str(tmdb_id), d_title, d_year, d_poster, str(time.time()), d_overview))
            conn.commit()
            conn.close()
        except: pass

        from resources.lib.cache import clear_all_fast_cache
        clear_all_fast_cache()
        xbmc.executebuiltin("Container.Refresh")
        
        return True
        # -------------------------------------------------
    return False


def remove_from_tmdb_favorites(content_type, tmdb_id):
    session = get_tmdb_session()
    if not session:
        return False

    m_type = 'tv' if content_type in ('tv', 'tvshow', 'episode', 'season', 'show') else 'movie'
    result = tmdb_auth_request(f"/account/{session['account_id']}/favorite", method='POST',
                               data={'media_type': m_type, 'media_id': int(tmdb_id), 'favorite': False}, v4=False)

    if result and result.get('success', True):
        details = get_tmdb_item_details(str(tmdb_id), content_type) or {}
        d_title = details.get('title') or details.get('name', 'Unknown')
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]",
                                      f"[B][COLOR yellow]{d_title}[/COLOR][/B] removed from [B][COLOR FF00CED1]Favorites[/COLOR][/B]",
                                      TMDB_ICON, 3000, False)
        
        # --- FIX BUFFERING: SQL INSTANT ---
        try:
            conn = trakt_sync.get_connection()
            c = conn.cursor()
            c.execute("DELETE FROM tmdb_account_lists WHERE list_type=? AND media_type=? AND tmdb_id=?", 
                      ('favorite', m_type, str(tmdb_id)))
            conn.commit()
            conn.close()
        except: pass

        from resources.lib.cache import clear_all_fast_cache
        clear_all_fast_cache()
        xbmc.executebuiltin("Container.Refresh")

        return True
        # -------------------------------------------------
    return False


def add_to_tmdb_list(list_id, tmdb_id, content_type='movie'):
    session = get_tmdb_session()
    if not session: 
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Not connected", TMDB_ICON, 3000, False)
        return False

    success = False
    media_type_normalized = 'tv' if content_type in ['tv', 'tvshow', 'episode', 'season', 'show'] else 'movie'
    
    # --- API V4 (singura metoda — suporta si seriale, si filme) ---
    resp = tmdb_auth_request(f"/list/{list_id}/items", method='POST',
                             data={"items": [{"media_type": media_type_normalized, "media_id": int(tmdb_id)}]}, v4=True)
    
    if resp and resp.get('success'):
        # Notificare cu numele listei (colorat TMDb + bold)
        list_name = 'List'
        d_title = ''
        try:
            conn_l = trakt_sync.get_connection()
            c_l = conn_l.cursor()
            c_l.execute("SELECT name FROM tmdb_custom_lists WHERE list_id=?", (str(list_id),))
            row_l = c_l.fetchone()
            if row_l: list_name = row_l[0]
            conn_l.close()
        except: pass
        try:
            details = get_tmdb_item_details(str(tmdb_id), media_type_normalized) or {}
            d_title = details.get('title') or details.get('name', 'Unknown')
        except: pass
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]",
                                      f"[B][COLOR yellow]{d_title}[/COLOR][/B] added to [B][COLOR FF00CED1]{list_name}[/COLOR][/B]",
                                      TMDB_ICON, 3000, False)
        success = True
    else:
        log(f"[TMDB] V4 Add failed: {resp}")

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
            # 1. Verificam daca item-ul exista deja (contorul nu se incrementeaza la duplicate)
            c.execute("SELECT 1 FROM tmdb_custom_list_items WHERE list_id=? AND tmdb_id=?", 
                      (str(list_id), str(tmdb_id)))
            is_duplicate = c.fetchone() is not None
            
            # 2. Inseram item-ul in baza locala (INSERT OR REPLACE pentru update sigur)
            c.execute("INSERT OR REPLACE INTO tmdb_custom_list_items VALUES (?,?,?,?,?,?,?,?)", 
                      (str(list_id), str(tmdb_id), media_type_normalized, d_title, d_year, d_poster, d_overview, -1))
            
            # 3. Actualizam contorul doar daca e item nou (nu duplicat)
            if is_duplicate:
                c.execute("UPDATE tmdb_custom_lists SET poster = ?, backdrop = ? WHERE list_id=?", 
                          (d_poster, d_backdrop, str(list_id)))
            else:
                c.execute("UPDATE tmdb_custom_lists SET item_count = item_count + 1, poster = ?, backdrop = ? WHERE list_id=?", 
                          (d_poster, d_backdrop, str(list_id)))
            conn.commit()
            conn.close()
        except Exception as e:
            log(f"[TMDB] Error updating local SQL on add: {e}")

        # 3. Curatam cache-ul RAM si dam refresh o singura data, la final
        from resources.lib.cache import clear_all_fast_cache
        clear_all_fast_cache()
        xbmc.executebuiltin("Container.Refresh")
        return True
    
    return False


def remove_from_tmdb_list(list_id, tmdb_id, content_type='movie'):
    session = get_tmdb_session()
    if not session: return False

    success = False
    m_type = 'tv' if content_type in ['tv', 'tvshow', 'episode', 'season', 'show'] else 'movie'

    def try_delete(media_t):
        resp = tmdb_auth_request(f"/list/{list_id}/items", method='DELETE',
                                 data={"items": [{"media_type": media_t, "media_id": int(tmdb_id)}]}, v4=True)
        if not resp:
            return False
        if resp.get('success'):
            results = resp.get('results') or []
            if results:
                return bool(results[0].get('success'))
            return True
        return False

    success = try_delete(m_type)
    success_type = m_type
    
    if not success:
        other_type = 'movie' if m_type == 'tv' else 'tv'
        success = try_delete(other_type)
        if success: success_type = other_type

    if success:
        # 1. Stergere locala SQL + ACTUALIZARE POSTER LISTA
        try:
            from resources.lib import trakt_sync
            conn = trakt_sync.get_connection()
            c = conn.cursor()
            
            # A. Stergem item-ul
            c.execute("DELETE FROM tmdb_custom_list_items WHERE list_id=? AND tmdb_id=?", 
                      (str(list_id), str(tmdb_id)))
            
            # B. Luam posterul primului element RAMAS pentru coperta listei
            c.execute("SELECT poster FROM tmdb_custom_list_items WHERE list_id=? ORDER BY sort_index ASC LIMIT 1", 
                      (str(list_id),))
            row = c.fetchone()
            
            # C. Numaram cate au mai ramas
            c.execute("SELECT COUNT(*) FROM tmdb_custom_list_items WHERE list_id=?", 
                      (str(list_id),))
            new_count = c.fetchone()[0]
            
            # D. Actualizam lista: count + poster nou
            if row and new_count > 0:
                c.execute("UPDATE tmdb_custom_lists SET item_count=?, poster=? WHERE list_id=?", 
                          (new_count, row[0] or '', str(list_id)))
            else:
                # The list is empty - resetam tot
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

        list_name = 'list'
        try:
            conn_n = trakt_sync.get_connection()
            c_n = conn_n.cursor()
            c_n.execute("SELECT name FROM tmdb_custom_lists WHERE list_id=?", (str(list_id),))
            row_n = c_n.fetchone()
            if row_n: list_name = row_n[0]
            conn_n.close()
        except: pass
        try:
            # Folosim tipul care a sters CU SUCCES (fallback-ul poate fi alt tip decat m_type)
            details = get_tmdb_item_details(str(tmdb_id), success_type) or {}
            d_title = details.get('title') or details.get('name', 'Unknown')
        except:
            d_title = ''
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]",
                                      f"[B][COLOR yellow]{d_title}[/COLOR][/B] removed from [B][COLOR FF00CED1]{list_name}[/COLOR][/B]",
                                      TMDB_ICON, 3000, False)
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
    return get_tmdb_user_lists_v4()


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


def show_mdblist_context_menu(tmdb_id, imdb_id, content_type, title='', season=None, episode=None):
    import xbmcgui
    import xbmc
    import os
    from resources.lib.config import ADDON
    
    MDB_ICON = os.path.join(ADDON.getAddonInfo('path'), 'resources', 'media', 'mdblist.png')
    
    from resources.lib import mdblist
    if not mdblist.is_authenticated():
        xbmcgui.Dialog().notification("[B][COLOR lightskyblue]MDBList[/COLOR][/B]", "Add your [B][COLOR lightskyblue]MDBList[/COLOR][/B] API Key in Settings!", MDB_ICON, 3000, False)
        return

    if not title:
        try:
            from resources.lib.trakt_sync import get_tmdb_item_details_from_db
            details = get_tmdb_item_details_from_db(tmdb_id, 'tv' if str(content_type).lower() not in ('movie', 'movies') else 'movie') or {}
            title = details.get('title') or details.get('name', 'Title')
        except:
            title = 'Title'

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
    
    from resources.lib.mdblist_sync import is_in_collection
    _in_collection = is_in_collection(tmdb_id)
    if _in_collection:
        options.append(('Remove from [B][COLOR lightskyblue]MDB Collection[/COLOR][/B]', 'mdblist_remove_collection'))
    else:
        options.append(('Add to [B][COLOR lightskyblue]MDB Collection[/COLOR][/B]', 'mdblist_add_collection'))

    if str(content_type).lower() not in ('movie', 'movies'):
        from resources.lib.mdblist_sync import is_dropped
        if is_dropped(tmdb_id):
            options.append(('Restore [B][COLOR FF6AFB92]Dropped Show[/COLOR][/B]', 'mdblist_unmark_dropped'))
        else:
            options.append(('[B][COLOR FFE41B17]Drop Show[/COLOR][/B]', 'mdblist_mark_dropped'))
        
    options.append(('Add to [B][COLOR lightskyblue]My MDBLists[/COLOR][/B]', 'mdblist_add_to_list'))
    options.append(('Remove from [B][COLOR lightskyblue]My MDBLists[/COLOR][/B]', 'mdblist_remove_from_list'))
    options.append(('[B]Rate on [COLOR lightskyblue]MDBList[/COLOR][/B]', 'mdblist_rating'))

    dialog = xbmcgui.Dialog()
    ret = dialog.contextmenu([opt[0] for opt in options])

    if ret < 0:
        return

    action = options[ret][1]
    
    from resources.lib.mdblist_api import MDBListAPI
    _mdb_api = MDBListAPI()
    
    if action == 'mdblist_watchlist_add':
        if mdblist.watchlist_add(imdb_id=imdb_id, tmdb_id=tmdb_id, mediatype=content_type, title=title):
            xbmc.sleep(1000)
            xbmc.executebuiltin("Container.Refresh")
    elif action == 'mdblist_watchlist_remove':
        if mdblist.watchlist_remove(imdb_id=imdb_id, tmdb_id=tmdb_id, mediatype=content_type, title=title):
            xbmc.sleep(1000)
            xbmc.executebuiltin("Container.Refresh")
    elif action == 'mdblist_add_to_list':
        show_mdblist_add_to_list_dialog(tmdb_id, imdb_id, content_type, title)
    elif action == 'mdblist_remove_from_list':
        show_mdblist_remove_from_list_dialog(tmdb_id, imdb_id, content_type, title)
    elif action == 'mdblist_rating':
        from resources.lib.mdblist_api import prompt_mdblist_rating
        prompt_mdblist_rating(tmdb_id, content_type, season, episode, title)
    elif action == 'mdblist_mark_dropped':
        if _mdb_api.mark_dropped(tmdb_id):
            from resources.lib.mdblist_sync import drop_add_local
            drop_add_local(tmdb_id, title)
            xbmcgui.Dialog().notification("[B][COLOR lightskyblue]MDBList[/COLOR][/B]", f"[B][COLOR yellow]{title}[/COLOR][/B] — [B][COLOR FFE41B17]Drop Show[/COLOR][/B]", MDB_ICON, 3000, False)
            xbmc.sleep(1000)
            xbmc.executebuiltin("Container.Refresh")
    elif action == 'mdblist_unmark_dropped':
        if _mdb_api.unmark_dropped(tmdb_id):
            from resources.lib.mdblist_sync import drop_remove_local, clear_cached
            drop_remove_local(tmdb_id)
            clear_cached('dropped')
            xbmcgui.Dialog().notification("[B][COLOR lightskyblue]MDBList[/COLOR][/B]", f"[B][COLOR yellow]{title}[/COLOR][/B] — Restore [B][COLOR FF6AFB92]Dropped Show[/COLOR][/B]", MDB_ICON, 3000, False)
            xbmc.sleep(1000)
            xbmc.executebuiltin("Container.Refresh")
    elif action == 'mdblist_add_collection':
        _mdb_api.add_to_collection(content_type, tmdb_id)
        from resources.lib.mdblist_sync import get_connection as _mdb_conn, clear_cached as _mdb_clear_cache
        _mc = _mdb_conn()
        _mc.execute("INSERT OR REPLACE INTO mdblist_collection (tmdb_id, media_type, collected_at) VALUES (?,?,datetime('now'))", (str(tmdb_id), content_type))
        _mc.commit()
        _mc.close()
        _mdb_clear_cache('collection')
        xbmcgui.Dialog().notification("[B][COLOR lightskyblue]MDBList[/COLOR][/B]", f"[B][COLOR yellow]{title}[/COLOR][/B] added to [B][COLOR lightskyblue]Collection[/COLOR][/B]", MDB_ICON, 3000, False)
        xbmc.executebuiltin("Container.Refresh")
    elif action == 'mdblist_remove_collection':
        _mdb_api.remove_from_collection(content_type, tmdb_id)
        from resources.lib.mdblist_sync import get_connection as _mdb_conn, clear_cached as _mdb_clear_cache
        _mc = _mdb_conn()
        _mc.execute("DELETE FROM mdblist_collection WHERE tmdb_id=?", (str(tmdb_id),))
        _mc.commit()
        _mc.close()
        _mdb_clear_cache('collection')
        xbmcgui.Dialog().notification("[B][COLOR lightskyblue]MDBList[/COLOR][/B]", f"[B][COLOR yellow]{title}[/COLOR][/B] removed from [B][COLOR lightskyblue]Collection[/COLOR][/B]", MDB_ICON, 3000, False)
        xbmc.executebuiltin("Container.Refresh")


def show_mdblist_add_to_list_dialog(tmdb_id, imdb_id, content_type, title=''):
    import xbmcgui
    import xbmc
    import os
    from resources.lib.config import ADDON
    
    MDB_ICON = os.path.join(ADDON.getAddonInfo('path'), 'resources', 'media', 'mdblist.png')

    if not title:
        try:
            from resources.lib.trakt_sync import get_tmdb_item_details_from_db
            details = get_tmdb_item_details_from_db(tmdb_id, 'tv' if str(content_type).lower() not in ('movie', 'movies') else 'movie') or {}
            title = details.get('title') or details.get('name', 'Title')
        except:
            title = 'Title'
    
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
            xbmcgui.Dialog().notification("[B][COLOR lightskyblue]MDBList[/COLOR][/B]", f"[B][COLOR yellow]{title}[/COLOR][/B] added to [B][COLOR FF6AFB92]{selected_list.get('name')}[/COLOR][/B]", MDB_ICON, 3000, False)
            xbmc.sleep(1000)
            xbmc.executebuiltin("Container.Refresh")


def show_mdblist_remove_from_list_dialog(tmdb_id, imdb_id, content_type, title=''):
    import xbmcgui
    import xbmc
    import os
    from resources.lib.config import ADDON
    
    MDB_ICON = os.path.join(ADDON.getAddonInfo('path'), 'resources', 'media', 'mdblist.png')

    if not title:
        try:
            from resources.lib.trakt_sync import get_tmdb_item_details_from_db
            details = get_tmdb_item_details_from_db(tmdb_id, 'tv' if str(content_type).lower() not in ('movie', 'movies') else 'movie') or {}
            title = details.get('title') or details.get('name', 'Title')
        except:
            title = 'Title'
    
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
            xbmcgui.Dialog().notification("[B][COLOR lightskyblue]MDBList[/COLOR][/B]", f"[B][COLOR yellow]{title}[/COLOR][/B] removed from [B][COLOR FF6AFB92]{selected_list.get('name')}[/COLOR][/B]", MDB_ICON, 3000, False)
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
        
        # ✅ FIX: Construire corecta URL imagini
        poster_path = lst.get('poster', '')
        backdrop_path = lst.get('backdrop', '')
        
        poster = get_list_image_url(lst.get('poster', ''), 'poster') or TMDB_ICON
        li.setArt({'thumb': poster, 'icon': poster, 'poster': poster})
        
        display_items.append(li)

    dialog = xbmcgui.Dialog()
    ret = dialog.select("Remove from List", display_items, useDetails=True)

    if ret >= 0:
        selected_list = lists_with_item[ret]
        remove_from_tmdb_list(selected_list['list_id'], tmdb_id, content_type)


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
            if not title:
                title = f.get('title', '')
            xbmcgui.Dialog().notification("[B][COLOR FFFF69B4]Favorites[/COLOR][/B]", f"[B][COLOR yellow]{title}[/COLOR][/B] — already in favorites", TMDbmovies_ICON, 2000, False)
            return

    new_item = {
        'tmdb_id': tmdb_id,
        'title': title,
        'added': time.strftime('%d-%m-%Y %H:%M:%S')
    }

    favs[c_type].insert(0, new_item)
    write_json(FAVORITES_FILE, favs)
    
    # Curatam RAM-ul pentru ca lista sa se updateze imediat cand intram in ea
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
    removed_title = ''
    for f in favs[c_type]:
        if str(f.get('tmdb_id')) == str(tmdb_id):
            removed_title = f.get('title', '')
            break
    favs[c_type] = [f for f in favs[c_type] if str(f.get('tmdb_id')) != str(tmdb_id)]

    if len(favs[c_type]) < initial_len:
        write_json(FAVORITES_FILE, favs)
        
        # Curatam RAM-ul
        from resources.lib.cache import clear_all_fast_cache
        clear_all_fast_cache()
        
        xbmcgui.Dialog().notification("[B][COLOR FFFF69B4]Favorites[/COLOR][/B]", f"Removed: [B][COLOR yellow]{removed_title}[/COLOR][/B]", TMDbmovies_ICON, 3000, False)
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
    # Includem si numarul de elemente in cheie pentru a invalida cache-ul cand se adauga/sterge ceva
    cache_key = f"local_favs_{content_type}_{len(local_items)}"
    cached_data = get_fast_cache(cache_key)
    if cached_data:
        render_from_fast_cache(cached_data)
        return
    # ---------------------------------

    # 2. PREFETCHING PARALEL PENTRU VITEZA MAXIMA
    # Construim o lista fake compatibila cu prefetcher-ul
    fake_items_for_prefetch = [{'id': fav.get('tmdb_id'), 'media_type': content_type} for fav in local_items if fav.get('tmdb_id')]
    prefetch_metadata_parallel(fake_items_for_prefetch, content_type)

    # 3. PROCESARE SI BATCH ADD
    items_to_add = []
    cache_list = []
    
    for fav in local_items:
        tmdb_id = fav.get('tmdb_id')
        if not tmdb_id:
            continue

        endpoint = 'movie' if content_type == 'movie' else 'tv'
        
        # Citim direct din DB (Acum e instant datorita prefetcherului care a umplut DB-ul)
        data = trakt_sync.get_tmdb_item_details_from_db(tmdb_id, endpoint)
        
        # Fallback de siguranta
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
    
    # 4. SALVAM IN RAM PENTRU URMATOAREA DATA
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
    from resources.lib.cache import _ensure_ram_cache_ver
    _ensure_ram_cache_ver()
    
    xbmcplugin.setContent(HANDLE, 'seasons')

    # Folosim Creierul Central care stie de limba RO/EN si se vindeca singur!
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

    from resources.lib import watched_provider
    import datetime
    today = datetime.date.today()

    for s in data.get('seasons', []):
        s_num = s['season_number']
        if s_num == 0:
            continue

        name = f"Season {s_num}"
        ep_count = s.get('episode_count', 0)
        
        # s_poster primeste automat posterul RO din creierul central!
        s_poster = f"{IMG_BASE}{s.get('poster_path', '')}" if s.get('poster_path') else poster
        
        premiered = s.get('air_date', '')

        display_name = name
        if premiered:
            try:
                parts = str(premiered).split('-')
                if datetime.date(int(parts[0]), int(parts[1]), int(parts[2])) > today:
                    display_name = f"[B][COLOR FFE238EC]{name}[/COLOR] ({parts[2]}.{parts[1]}.{parts[0]}[/B])"
            except: pass

        # Plot-ul sezonului vine deja tradus daca setarea e pe RO
        season_plot = s.get('overview', '')
        if not season_plot:
            season_plot = main_show_plot

        watched_count = watched_provider.get_watched_counts(tmdb_id, 'season', s_num)
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

        # --- NOU: Adaugam Meniul Contextual (Mark Watched/Unwatched) pentru Sezoane ---
        cm =[]
        is_fully_watched = (watched_count >= ep_count) if ep_count > 0 else False
        info['playcount'] = 1 if is_fully_watched else 0
        # Label galben bold + contor pentru sezoane incepute
        if watched_count > 0 and not is_fully_watched:
            if '[/' not in display_name:
                display_name = f"[B][COLOR FFEFD702]{display_name}[/COLOR] [COLOR FF6AFB92]({watched_count}/{ep_count})[/COLOR][/B]"
        elif is_fully_watched and '[COLOR' not in display_name:
            display_name = f'[B][COLOR FF6AFB92]{display_name}[/COLOR][/B]'
        
        watched_params = urlencode({'mode': 'mark_watched', 'tmdb_id': tmdb_id, 'type': 'season', 'season': s_num})
        unwatched_params = urlencode({'mode': 'mark_unwatched', 'tmdb_id': tmdb_id, 'type': 'season', 'season': s_num})

        from resources.lib.watched_provider import get_label as _prov_label, get_color as _prov_color
        _prov_lbl = _prov_label()
        _prov_clr = _prov_color()
        if is_fully_watched:
            cm.append((f'[B][COLOR FFE41B17]Mark Unwatched [COLOR {_prov_clr}]({_prov_lbl})[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{unwatched_params})"))
        else:
            cm.append((f'[B][COLOR FF6AFB92]Mark Watched [COLOR {_prov_clr}]({_prov_lbl})[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{watched_params})"))
            
        trakt_params = urlencode({'mode': 'trakt_context_menu', 'tmdb_id': tmdb_id, 'type': 'season', 'title': name, 'season': s_num})
        cm.append(('[B][COLOR pink]My Trakt[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{trakt_params})"))
        # -----------------------------------------------------------------------------

        # Trebuie sa trimitem si uids={'tmdb': tmdb_id} pentru ca AF3 sa lege Logo-ul de serial!
        add_directory(
            display_name,
            {'mode': 'episodes', 'tmdb_id': tmdb_id, 'season': str(s_num), 'tv_show_title': tv_title},
            thumb=s_poster, fanart=backdrop, clearlogo=show_logo, info=info, 
            uids={'tmdb': str(tmdb_id)}, watched_info=watched_info, cm=cm, folder=True
        )

    xbmcplugin.endOfDirectory(HANDLE)

    # Pre-fetch first 2 season details in background for instant episode loading
    import threading
    first_seasons = [s['season_number'] for s in data.get('seasons', []) if s['season_number'] in (1, 2)]
    for sn in first_seasons:
        t = threading.Thread(target=get_smart_season_details, args=(tmdb_id, sn), daemon=True)
        t.start()


def get_smart_season_details(tmdb_id, season_num):
    from resources.lib import trakt_sync
    from resources.lib.cache import ram_cache_get_season, ram_cache_set_season
    from resources.lib.config import ADDON, SESSION, get_headers, BASE_URL, API_KEY, get_plot_language_code, get_plot_img_lang, LANG_TO_TMDB
    current_lang = get_plot_language_code()

    # Check RAM cache first (instant) — validam limba: cache-ul EN (prefetch) nu poate
    # umple lista cu nume englezesti cand plot_language e RO
    ram_data = ram_cache_get_season(tmdb_id, season_num)
    if ram_data:
        if ram_data.get('_cached_lang') == current_lang:
            return ram_data
        ram_data = None

    data = trakt_sync.get_tmdb_season_details_from_db(tmdb_id, season_num)
    
    if data:
        cached_lang = data.get('_cached_lang', 'en')
        if cached_lang == current_lang:
            ram_cache_set_season(tmdb_id, season_num, data)
            return data
            
    url_en = f"{BASE_URL}/tv/{tmdb_id}/season/{season_num}?api_key={API_KEY}&language=en-US"
    
    for _attempt in range(3):
        try:
            res_en = SESSION.get(url_en, headers=get_headers(), timeout=5)
            if res_en.status_code == 429 and _attempt < 2:
                xbmc.sleep(1000 * (_attempt + 1))
                continue
            if res_en.status_code != 200:
                log(f"[SEASON] tv/{tmdb_id}/season/{season_num}: HTTP {res_en.status_code}", xbmc.LOGWARNING)
                return None
            data = res_en.json()
            data['_cached_lang'] = 'en'
            
            if current_lang != 'en':
                tmdb_lang = LANG_TO_TMDB.get(current_lang, 'en-US')
                url_target = f"{BASE_URL}/tv/{tmdb_id}/season/{season_num}?api_key={API_KEY}&language={tmdb_lang}&append_to_response=images&include_image_language={get_plot_img_lang()}"
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
                            if target_name and not re.match(r'^[A-Za-z\u00c0-\u024f]+\s+\d+$', target_name):
                                ep['name'] = target_name
                            if target_ep.get('still_path'): ep['still_path'] = target_ep['still_path']
                    data['_cached_lang'] = current_lang

            conn = trakt_sync.get_connection()
            try:
                trakt_sync.set_tmdb_season_details_to_db(conn.cursor(), tmdb_id, season_num, data)
                conn.commit()
            finally:
                conn.close()
            ram_cache_set_season(tmdb_id, season_num, data)
            return data
        except Exception as e:
            log(f"[SEASON] tv/{tmdb_id}/season/{season_num} fetch error: {e}", xbmc.LOGWARNING)
            xbmc.sleep(500 * (_attempt + 1))
    return None

def list_episodes(tmdb_id, season_num, tv_show_title):
    from resources.lib.cache import _ensure_ram_cache_ver
    _ensure_ram_cache_ver()
    from resources.lib import trakt_sync
    from resources.lib import trakt_api
    from resources.lib import watched_provider
    xbmcplugin.setContent(HANDLE, 'episodes')

    data = get_smart_season_details(tmdb_id, season_num)

    if not data:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    poster = f"{IMG_BASE}{data.get('poster_path', '')}" if data.get('poster_path') else ''
    
    # --- MODIFICARE: Obtinem IMDb ID al SERIALULUI (Parent) ---
    # Incercam sa luam detaliile serialului din DB sau API pentru a gasi IMDb ID
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

    # Batch fetch all progress for this season (one query instead of per-episode)
    progress_map = trakt_sync.get_local_playback_progress_batch(tmdb_id, 'tv', season_num)

    for ep in data.get('episodes', []):
        ep_num = ep['episode_number']
        original_ep_name = ep.get('name', '') or f'Episode {int(ep_num)}'
        
        # --- LOGICA NATIVA PREMIERE / FINALE PENTRU SKIN (Fara text vizibil) ---
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
        
        # --- LOGICA CULOARE ROSIE EPISOD (INJECTATA) ---
        display_label = name
        ep_air_date = ep.get('air_date', '')
        if ep_air_date:
            try:
                parts = str(ep_air_date).split('-')
                if datetime.date(int(parts[0]), int(parts[1]), int(parts[2])) > today:
                    display_label = f"[B][COLOR FFE238EC]{season_num}x{int(ep_num):02d} {original_ep_name}[/COLOR] ({parts[2]}.{parts[1]}.{parts[0]})[/B]"
            except: pass
        # -----------------------------------------------
        
        progress_value = progress_map.get(ep_num, 0)
        resume_percent = 0
        resume_seconds = 0
        
        if progress_value >= 1000000:
            resume_seconds = int(progress_value - 1000000)
        elif progress_value > 0 and progress_value < 90:
            resume_percent = progress_value

# Imaginile si plotul sunt deja localizate automat de Dual-Fetch-ul de mai sus!
        # --- LOGICA NOUA IMAGINI EPISOD (Standard Modern) ---
        ep_still = ep.get('still_path', '')
        
        # Poster-ul vertical
        season_poster_path = data.get('poster_path', '') if data else ''
        if not season_poster_path and show_details: season_poster_path = show_details.get('poster_path', '')
        base_poster = f"{IMG_BASE}{season_poster_path}" if season_poster_path else ''
        
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

        is_watched = watched_provider.is_episode_watched(tmdb_id, season_num, ep_num)
        
        try:
            duration = int(ep.get('runtime') or 0) * 60
        except:
            duration = 0
            
        # Daca episodul nu are durata pe TMDb, luam de la serial sau punem 45 min default
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
        cm.append(('[B][COLOR FFFF69B4]My Plays[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{urlencode(plays_params)})"))
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
        
        # AF3 ascunde thumb-ul daca e identic cu posterul → la modurile Poster (2/3)
        # thumb/landscape devin still-ul episodului (identic cu POV: thumb != poster)
        if art_pref in ('2', '3'):
            thumb_art = f"{IMG_BASE}{ep_still}" if has_still else ''
            landscape_art = thumb_art or ep_icon
        else:
            thumb_art = ep_icon
            landscape_art = ep_icon

        art = {
            'thumb': thumb_art,
            'icon': ep_icon, 
            'landscape': landscape_art,
            'tvshow.landscape': landscape_art,
            'tvshow.poster': base_poster, 
            'season.poster': base_poster, 
            'fanart': final_fanart
        }
        
        if skin_compat == '1':
            art['poster'] = base_poster  # AF3 (Afiseaza Poster Vertical 2:3)
        else:
            art['poster'] = ep_icon      # Estuary (Forteaza Thumbnail 16:9)
            
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
        
        original_lang = data.get('original_language') or 'en'
        lang_code = original_lang.split('-')[0].split('_')[0]
        
        # Adaugam limba originala prima in lista
        try_locales = []
        if lang_code == 'hi':
            try_locales.extend(['hi-IN', 'ta-IN', 'te-IN', 'ml-IN', 'kn-IN', 'pa-IN'])
        elif lang_code == 'ta':
            try_locales.extend(['ta-IN', 'hi-IN', 'te-IN', 'ml-IN', 'kn-IN', 'en-US'])
        elif lang_code == 'te':
            try_locales.extend(['te-IN', 'hi-IN', 'ta-IN', 'ml-IN', 'kn-IN', 'en-US'])
        else:
            try_locales = ['en-US', 'ta-IN', 'te-IN', 'hi-IN', 'ml-IN', 'kn-IN', 'pa-IN', 'xx']
        
        safe_include = f"{lang_code},en,null,xx,hi,ta,te,ml,kn,bn,gu,mr,ur,or,as,es,fr,de,it,ro"
        
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

    # Construire URL Final (folosind setarea trailer_player)
    if found_video:
        from resources.lib.config import get_trailer_url as _gtu
        trailer_url = _gtu(found_video.get('key'))
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

        # --- 1. SETARE GENURI SI TAGLINE ---
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
            # La filme, Kodi stie sa puna Genul in dreapta si Tagline-ul sub titlu
            if colored_genres_list:
                tag.setGenres(colored_genres_list)
                
            if tagline and genres_str:
                tag.setTagLine(f"[B][COLOR yellow]{tagline}[/COLOR][/B]   |   {genres_str}")
            elif tagline:
                tag.setTagLine(f"[B][COLOR yellow]{tagline}[/COLOR][/B]")
            elif genres_str:
                tag.setTagLine(f"{genres_str}")
        else:
            # PACALIM KODI LA SERIALE! 
            # Pentru ca ignora Tagline-ul, il unim cu Genul (pe care stim ca il afiseaza sub titlu)
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
        
        # 1. Calculam Statusul si aplicam CULORI DINAMICE
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
        
        # 4. Tara de origine
        country_names = []
        if content_type in ['movie', 'tv', 'tvshow']:
            pcs = data.get('production_countries', [])
            for c in pcs:
                if c.get('name') and c['name'] not in country_names:
                    country_names.append(c['name'])
            origins = data.get('origin_country', [])
            for o in origins:
                if o and o not in country_names:
                    country_names.append(o)
        if country_names:
            tag.setCountries(country_names[:3])
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
    if poster_path: # <--- Folosim variabila localizata, nu data.get('poster_path')
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

    # 1. Gasirea ID-ului Principal (Film sau Serial)
    found_id = tmdb_id
    
    # Determinam media type pentru cautare
    if content_type in ['tv', 'season', 'episode']:
        found_media = 'tv'
    else:
        found_media = 'movie'

    # Daca nu avem TMDb ID, il cautam
    if not found_id:
        # A. Cautare prin External IDs
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
        
        # B. Cautare prin TVDb
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

        # C. Cautare prin Titlu (Fallback)
        if not found_id and title:
            clean_title = title.split('(')[0].strip()
            url = f"{BASE_URL}/search/{found_media}?api_key={API_KEY}&query={quote(clean_title)}"
            
            if year and str(year).isdigit() and found_media == 'movie':
                url += f"&primary_release_year={year}"
                    
            data = get_json(url)
            if data.get('results'):
                found_id = data['results'][0]['id']
                log(f"[GLOBAL-INFO] Found parent ID by title: {found_id}")

    # 2. Afisare Info bazat pe tipul cerut
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
            # Info standard (Film sau Serial intreg)
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
        from resources.lib.config import ADDON, get_plot_language_code, get_plot_img_lang, LANG_TO_TMDB
        lang_code = get_plot_language_code()
        if lang_code != 'en' and data and data.get('success') != False:
            tmdb_lang = LANG_TO_TMDB.get(lang_code, 'en-US')
            url_target = url_en.replace('language=en-US', f'language={tmdb_lang}') + f"&include_image_language={get_plot_img_lang()}"
            data_target = get_json(url_target)
            
            if data_target:
                if data_target.get('overview'): 
                    data['overview'] = data_target['overview']
                
                if specific_type == 'episode' and data_target.get('name'):
                    target_name = data_target['name'].strip()
                    if not re.match(r'^[A-Za-z\u00c0-\u024f]+\s+\d+$', target_name):
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
                from resources.lib.config import get_trailer_url as _gtu
                trailer_url = _gtu(v.get('key'))
                break
        if trailer_url:
            break
    
    # 2. FALLBACK: Daca nu am gasit, cautam la nivel de serial
    if not trailer_url and show_data:
        show_videos = show_data.get('videos', {}).get('results', [])
        for vid_type in priority_types:
            for v in show_videos:
                if v.get('site') == 'YouTube' and v.get('type') == vid_type:
                    from resources.lib.config import get_trailer_url as _gtu
                    trailer_url = _gtu(v.get('key'))
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
    """Cere input si afiseaza rezultatele - REFRESH SAFE folosind cache!"""
    search_type = params.get('type', 'multi')
    query = params.get('query')
    page = int(params.get('page', '1')) # <--- ADAUGAT: Preluam pagina
    
    # 1. Daca avem query in URL (redirect) - afisam direct
    if query:
        from urllib.parse import unquote
        build_search_result(search_type, unquote(query), page) # <--- Trimitem pagina
        return
    
    # 2. Verificam cache-ul pentru Container.Refresh
    cache_key = f'tmdb_search_{search_type}'
    cached_query = xbmcgui.Window(10000).getProperty(cache_key)
    
    # Detectam daca suntem deja pe pagina de rezultate (refresh)
    container_path = xbmc.getInfoLabel('Container.FolderPath')
    is_refresh = cached_query and 'perform_search' in container_path
    
    if is_refresh:
        # E un refresh - folosim query-ul din cache
        build_search_result(search_type, cached_query, page) # <--- Trimitem pagina
        return
    
    # 3. Cautare noua - cerem input
    dialog = xbmcgui.Dialog()
    new_query = dialog.input("Search...", type=xbmcgui.INPUT_ALPHANUM)
    
    if new_query:
        add_search_to_history(new_query, search_type)
        # Salvam in cache pentru refresh-uri viitoare
        xbmcgui.Window(10000).setProperty(cache_key, new_query)
        # Afisam rezultatele direct
        build_search_result(search_type, new_query, 1) # <--- Aici e pagina 1 (cautare noua)
    else:
        # Cancel
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)


def perform_search_query(params):
    """Executa direct o cautare din istoric."""
    search_type = params.get('type', 'multi')
    query = params.get('query', '')
    page = int(params.get('page', '1')) # <--- ADAUGAT: Preluam pagina
    
    if query:
        from urllib.parse import unquote
        query = unquote(query)
        add_search_to_history(query, search_type)
        # Salvam in cache pentru refresh
        xbmcgui.Window(10000).setProperty(f'tmdb_search_{search_type}', query)
        build_search_result(search_type, query, page) # <--- Trimitem pagina
    else:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)

def get_tmdb_search_results(query, search_type, page):
    url = f"{BASE_URL}/search/{search_type}?api_key={API_KEY}&language={LANG}&query={quote(query)}&page={page}"
    return requests.get(url, timeout=10)


# --- COD EXISTENT ---
def build_search_result(search_type, query, page=1): # Adaugat parametrul page
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

    # Paginare pentru cautare
    total_pages = data.get('total_pages', 1)
    if page < total_pages:
        next_label = f"[B]Next Page ({page+1}) >>[/B]"
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


def build_actors_list(params):
    action = params.get('action', 'popular')
    page = int(params.get('page', '1'))

    from resources.lib.config import PAGE_LIMIT
    ITEMS_PER_API_PAGE = 20
    api_pages_needed = max(1, (PAGE_LIMIT + ITEMS_PER_API_PAGE - 1) // ITEMS_PER_API_PAGE)
    start_api_page = (page - 1) * api_pages_needed + 1

    cache_key = f"actors_{action}_{page}"
    cached_data = get_fast_cache(cache_key)
    if cached_data:
        render_from_fast_cache(cached_data)
        return

    all_results = []
    more_pages = False
    for api_page in range(start_api_page, start_api_page + api_pages_needed):
        url = f"{BASE_URL}/person/popular?api_key={API_KEY}&language={LANG}&page={api_page}"
        data = get_json(url)
        if not data:
            break
        results = data.get('results', [])
        all_results.extend(results)
        if api_page == start_api_page + api_pages_needed - 1:
            if (data.get('total_pages', 0) or 0) > api_page:
                more_pages = True
        if len(results) < ITEMS_PER_API_PAGE:
            break

    if not all_results:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    current_items = all_results[:PAGE_LIMIT]
    has_next = len(all_results) > PAGE_LIMIT or more_pages

    items_to_add = []
    cache_list = []

    if page == 1:
        search_url = f"{sys.argv[0]}?{urlencode({'mode': 'perform_actor_search'})}"
        search_li = xbmcgui.ListItem('[B][COLOR FFFDBD01]Search Actors[/COLOR][/B]')
        search_icon = os.path.join(ADDON_PATH, 'resources', 'media', 'search.png')
        search_li.setArt({'icon': search_icon, 'thumb': search_icon})
        items_to_add.append((search_url, search_li, True))
        cache_list.append({'label': '[B][COLOR FFFDBD01]Search Actors[/COLOR][/B]', 'url': search_url, 'is_folder': True, 'art': {'icon': search_icon}, 'info': {}, 'cm': []})

    for actor in current_items:
        actor_id = actor.get('id')
        name = actor.get('name', 'Unknown')
        profile = actor.get('profile_path', '')
        thumb = f"{IMG_BASE}{profile}" if profile else ''

        li = xbmcgui.ListItem(label=name)
        art = {'icon': thumb, 'thumb': thumb}
        if thumb:
            art['poster'] = thumb
        li.setArt(art)

        known_for = actor.get('known_for', [])
        if known_for:
            titles = []
            for kf in known_for[:2]:
                kf_type = kf.get('media_type', '')
                kf_title = kf.get('title') or kf.get('name', '')
                if kf_title:
                    titles.append(kf_title)
            if titles:
                li.setInfo('video', {'plot': ', '.join(titles)})

        actor_url = f"{sys.argv[0]}?{urlencode({'mode': 'actor_dialog', 'actor_id': str(actor_id)})}"
        items_to_add.append((actor_url, li, False))
        cache_list.append({'label': name, 'url': actor_url, 'is_folder': False, 'art': {'icon': thumb, 'thumb': thumb}, 'info': {}, 'cm': []})

    if has_next:
        next_label = f"[B]Next Page ({page+1}) >>[/B]"
        next_params = {'mode': 'build_actors_list', 'action': action, 'page': str(page + 1)}
        next_url = f"{sys.argv[0]}?{urlencode(next_params)}"
        next_li = xbmcgui.ListItem(next_label)
        next_li.setArt({'icon': NEXT_PAGE_ICON, 'thumb': NEXT_PAGE_ICON})
        items_to_add.append((next_url, next_li, True))
        cache_list.append({'label': next_label, 'url': next_url, 'is_folder': True, 'art': {'icon': NEXT_PAGE_ICON}, 'info': {}, 'cm': []})

    if items_to_add:
        xbmcplugin.addDirectoryItems(HANDLE, items_to_add, len(items_to_add))
    xbmcplugin.setContent(HANDLE, 'files')
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=True)
    set_fast_cache(cache_key, cache_list)


def perform_actor_search(params):
    query = params.get('query')
    page = int(params.get('page', '1'))

    if query:
        build_actor_search_result(query, page)
        return

    cache_key = 'tmdb_actor_search'
    cached_query = xbmcgui.Window(10000).getProperty(cache_key)
    container_path = xbmc.getInfoLabel('Container.FolderPath')
    is_refresh = cached_query and 'perform_actor_search' in container_path

    if is_refresh:
        build_actor_search_result(cached_query, page)
        return

    new_query = xbmcgui.Dialog().input('Search Actor', type=xbmcgui.INPUT_ALPHANUM)
    if new_query:
        xbmcgui.Window(10000).setProperty(cache_key, new_query)
        build_actor_search_result(new_query, 1)
    else:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)


def build_actor_search_result(query, page=1):
    cache_key = f"actor_search_{query}_{page}"
    cached_data = get_fast_cache(cache_key)
    if cached_data:
        render_from_fast_cache(cached_data)
        return

    url = f"{BASE_URL}/search/person?api_key={API_KEY}&language={LANG}&query={quote(query)}&page={page}"
    data = get_json(url)
    if not data:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    results = data.get('results', [])
    items_to_add = []
    cache_list = []

    for actor in results:
        actor_id = actor.get('id')
        name = actor.get('name', 'Unknown')
        profile = actor.get('profile_path', '')
        thumb = f"{IMG_BASE}{profile}" if profile else ''

        li = xbmcgui.ListItem(label=name)
        art = {'icon': thumb, 'thumb': thumb}
        if thumb:
            art['poster'] = thumb
        li.setArt(art)

        known_for = actor.get('known_for', [])
        if known_for:
            titles = []
            for kf in known_for[:2]:
                kf_title = kf.get('title') or kf.get('name', '')
                if kf_title:
                    titles.append(kf_title)
            if titles:
                li.setInfo('video', {'plot': ', '.join(titles)})

        actor_url = f"{sys.argv[0]}?{urlencode({'mode': 'actor_dialog', 'actor_id': str(actor_id)})}"
        items_to_add.append((actor_url, li, False))
        cache_list.append({'label': name, 'url': actor_url, 'is_folder': False, 'art': {'icon': thumb, 'thumb': thumb}, 'info': {}, 'cm': []})

    total_pages = min(data.get('total_pages', 1), 500)
    if page < total_pages:
        next_label = f"[B]Next Page ({page+1}) >>[/B]"
        next_params = {'mode': 'perform_actor_search', 'query': query, 'page': str(page + 1)}
        next_url = f"{sys.argv[0]}?{urlencode(next_params)}"
        next_li = xbmcgui.ListItem(next_label)
        next_li.setArt({'icon': NEXT_PAGE_ICON, 'thumb': NEXT_PAGE_ICON})
        items_to_add.append((next_url, next_li, True))
        cache_list.append({'label': next_label, 'url': next_url, 'is_folder': True, 'art': {'icon': NEXT_PAGE_ICON}, 'info': {}, 'cm': []})

    if items_to_add:
        xbmcplugin.addDirectoryItems(HANDLE, items_to_add, len(items_to_add))
    xbmcplugin.setContent(HANDLE, 'files')
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=True)
    set_fast_cache(cache_key, cache_list)


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

    # v4 NU are create-list (404) — v3: POST /3/list (verificat live 201, raspuns cu 'list_id')
    result = tmdb_auth_request("/list", method='POST',
                               data={'name': list_name, 'description': description,
                                     'iso_639_1': (LANG or 'en')[:2], 'iso_3166_1': 'US'}, v4=False)

    list_id = (result or {}).get('list_id')
    if result and list_id:
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", f"List created: [B][COLOR yellow]{list_name}[/COLOR][/B]", TMDB_ICON, 3000, False)
        trakt_sync.sync_tmdb_only(silent=True) 
        xbmc.executebuiltin("Container.Refresh")
        return list_id
    else:
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Error creating list", xbmcgui.NOTIFICATION_ERROR)
    return None


def delete_tmdb_list(list_id):
    session = get_tmdb_session()
    if not session:
        return False

    dialog = xbmcgui.Dialog()
    if not dialog.yesno("Confirm", "Are you sure you want to delete this list?"):
        return False

    list_name = ''
    try:
        conn_l = trakt_sync.get_connection()
        c_l = conn_l.cursor()
        c_l.execute("SELECT name FROM tmdb_custom_lists WHERE list_id=?", (str(list_id),))
        row_l = c_l.fetchone()
        conn_l.close()
        if row_l and row_l[0]:
            list_name = row_l[0]
    except: pass

    # v4 NU are delete-list (404) — v3: DELETE /3/list/{id} (verificat live 200)
    result = tmdb_auth_request(f"/list/{list_id}", method='DELETE', v4=False)

    if result is not None:
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", f"List deleted: [B][COLOR FF00CED1]{list_name}[/COLOR][/B]", TMDB_ICON, 3000, False)
        trakt_sync.sync_tmdb_only(silent=True) 
        xbmc.executebuiltin("Container.Refresh")
        return True

    xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Delete error", xbmcgui.NOTIFICATION_ERROR)
    return False


def clear_tmdb_list(list_id):
    session = get_tmdb_session()
    if not session:
        return False

    dialog = xbmcgui.Dialog()
    if not dialog.yesno("Confirm", "Are you sure you want to clear this list?"):
        return False

    list_name = ''
    try:
        conn_l = trakt_sync.get_connection()
        c_l = conn_l.cursor()
        c_l.execute("SELECT name FROM tmdb_custom_lists WHERE list_id=?", (str(list_id),))
        row_l = c_l.fetchone()
        conn_l.close()
        if row_l and row_l[0]:
            list_name = row_l[0]
    except: pass

    # v3 accepta Bearer v4 — endpointul /clear nu exista in v4
    result = tmdb_auth_request(f"/list/{list_id}/clear", method='POST', params={'confirm': 'true'}, v4=False)

    if result is not None:
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", f"List cleared: [B][COLOR FF00CED1]{list_name}[/COLOR][/B]", TMDB_ICON, 3000, False)
        trakt_sync.sync_tmdb_only(silent=True) 
        xbmc.executebuiltin("Container.Refresh")
        return True

    return False


def rate_tmdb_item_silent(tmdb_id, content_type, rating_value, season=None, episode=None):
    session = get_tmdb_session()
    if not session: return False

    if content_type == 'episode' or (season and episode):
        # v3 + Bearer (accepta token v4)
        result = tmdb_auth_request(f"/tv/{tmdb_id}/season/{season}/episode/{episode}/rating", method='POST',
                                   data={'value': float(rating_value)}, v4=False)
    else:
        # v4 NU are rating (404) — v3: POST /3/{movie|tv}/{id}/rating (verificat live 201)
        endpoint = 'movie' if content_type == 'movie' else 'tv'
        result = tmdb_auth_request(f"/{endpoint}/{tmdb_id}/rating", method='POST',
                                   data={'value': float(rating_value)}, v4=False)

    if result is not None:
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

    # v4 NU are rating (404) — v3: DELETE /3/{movie|tv}/{id}/rating
    endpoint = 'movie' if content_type == 'movie' else 'tv'
    result = tmdb_auth_request(f"/{endpoint}/{tmdb_id}/rating", method='DELETE', v4=False)

    if result is not None:
        xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDB[/COLOR][/B]", "Rating deleted", TMDB_ICON, 3000, False)
        return True

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


def _ensure_clearlogo(data):
    """Normalizeaza clearlogo din images.logos daca lipseste cheia top-level
    (ex: date puse in RAM pool de prefetch_metadata_parallel, care nu extrag logo-ul)."""
    if not data or data.get('clearlogo'):
        return data
    try:
        for img in data.get('images', {}).get('logos', []):
            if img.get('file_path', '').lower().endswith('.png'):
                data['clearlogo'] = img['file_path']
                break
    except:
        pass
    return data


def _get_cached_details(tmdb_id, content_type):
    """Cache-only lookup — zero API calls. Respecta _cached_lang."""
    str_id = str(tmdb_id)
    from resources.lib.config import get_plot_language_code
    current_lang = get_plot_language_code()
    from resources.lib.cache import ram_pool_get
    pool_data = ram_pool_get(str_id)
    if pool_data and pool_data.get('_cached_lang') == current_lang:
        return _ensure_clearlogo(pool_data)
    from resources.lib import trakt_sync
    data = trakt_sync.get_tmdb_item_details_from_db(str_id, content_type)
    if data and data.get('_cached_lang') == current_lang:
        return _ensure_clearlogo(data)
    return {}


def _extract_mpaa(data, content_type):
    """Extrage MPAA (TV-MA/R/PG-13 etc.) din content_ratings (tv) sau release_dates (movie)."""
    try:
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
    except:
        pass


def get_tmdb_item_details(tmdb_id, content_type, lightweight=False):
    """Fetch detalii TMDB. lightweight=True omite credits/videos (lista)."""
    endpoint = 'movie' if content_type == 'movie' else 'tv'
    str_id = str(tmdb_id)
    
    from resources.lib.config import get_plot_language_code
    current_lang = get_plot_language_code()
    
    from resources.lib.cache import ram_cache_get_tvshow, ram_cache_set_tvshow, ram_pool_get, ram_pool_set
    # 1. Check global RAM pool — skip if language doesn't match
    pool_data = ram_pool_get(str_id)
    if pool_data and pool_data.get('_cached_lang') == current_lang:
        if lightweight or not pool_data.get('_lightweight'):
            return _ensure_clearlogo(pool_data)
    
    # 2. Check Window Properties RAM cache — skip if language doesn't match
    ram_data = ram_cache_get_tvshow(str_id)
    if ram_data and ram_data.get('_cached_lang') == current_lang:
        if lightweight or not ram_data.get('_lightweight'):
            ram_pool_set(str_id, ram_data)
            return _ensure_clearlogo(ram_data)
    
    from resources.lib.config import ADDON, SESSION, get_headers, get_plot_img_lang, LANG_TO_TMDB
    from resources.lib import trakt_sync
    data = trakt_sync.get_tmdb_item_details_from_db(str_id, content_type)
    
    if data:
        cached_lang = data.get('_cached_lang', 'en')
        if cached_lang == current_lang:
            ram_pool_set(str_id, data)
            ram_cache_set_tvshow(str_id, data)
            return _ensure_clearlogo(data)
    
    append = "external_ids,images,content_ratings,release_dates" if lightweight else "credits,videos,external_ids,images,content_ratings,release_dates"
    url_en = f"{BASE_URL}/{endpoint}/{tmdb_id}?api_key={API_KEY}&language=en-US&append_to_response={append}&include_image_language=en,null,xx"
    
    try:
        res_en = SESSION.get(url_en, headers=get_headers(), timeout=5)
        if res_en.status_code != 200: return None
        data = res_en.json()
        
        data['_cached_lang'] = 'en'
        data['_lightweight'] = lightweight
        
        _extract_mpaa(data, content_type)
        
        en_logos = [img for img in data.get('images', {}).get('logos', []) if img.get('file_path', '').lower().endswith('.png')]
        if en_logos:
            data['clearlogo'] = en_logos[0]['file_path']
        
        if current_lang != 'en':
            tmdb_lang = LANG_TO_TMDB.get(current_lang, 'en-US')
            url_target = f"{BASE_URL}/{endpoint}/{tmdb_id}?api_key={API_KEY}&language={tmdb_lang}&append_to_response=images&include_image_language={get_plot_img_lang()}"
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
                    
                data['_cached_lang'] = current_lang
        
        _ensure_clearlogo(data)
        ram_pool_set(str_id, data)
        ram_cache_set_tvshow(tmdb_id, data)
        if not lightweight:
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
    from resources.lib import watched_provider
    return watched_provider.get_watched_counts(tmdb_id, 'movie') > 0


def get_watched_status_season(tmdb_id, season_num):
    from resources.lib import watched_provider

    watched_count = watched_provider.get_watched_counts(tmdb_id, 'season', season_num)

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
# FUNCTII IN PROGRESS (Corectate)
# =============================================================================

def in_progress_movies(params):
    """Afiseaza filmele cu resume point + PLOT + METADATA COMPLETE."""
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
            # Este numarul magic, deci avem secunde exacte
            resume_seconds = int(progress_raw - 1000000)
            if duration > 0:
                progress_percent = (resume_seconds / duration) * 100
        elif 0 < progress_raw < 90:
            # Este un procentaj standard (ex: de la Trakt)
            progress_percent = progress_raw
            if duration > 0:
                resume_seconds = int((progress_percent / 100.0) * duration)
        # <<---------------------------------------------------->>

        poster = f"{IMG_BASE}{poster_path_api}" if poster_path_api else ''
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
        from resources.lib.watched_provider import get_label as _prov_label, get_color as _prov_color
        cm.append((f'[B][COLOR FF6AFB92]Mark Watched [COLOR {_prov_color()}]({_prov_label()})[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?mode=mark_watched&tmdb_id={tmdb_id}&type=movie)"))

        url_params = {'mode': 'sources', 'tmdb_id': tmdb_id, 'type': 'movie', 'title': title, 'year': year}
        
        if resume_seconds > 0:
            url_params['resume_time'] = resume_seconds
        
        from resources.lib.watched_provider import get_watched_counts as _get_wc
        is_watched_this = _get_wc(tmdb_id, 'movie') > 0
        display_title_ip = f"{title} ({year})"
        if is_watched_this:
            display_title_ip = f'[B][COLOR FF6AFB92]{display_title_ip}[/COLOR][/B]'

        url = f"{sys.argv[0]}?{urlencode(url_params)}"
        li = xbmcgui.ListItem(display_title_ip)
        
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
            f"[B]Next Page ({page+1}) >>[/B]",
            {'mode': 'in_progress_movies', 'page': str(page + 1)},
            icon=NEXT_PAGE_ICON, folder=True
        )
        
    xbmcplugin.setContent(HANDLE, 'movies')
    xbmcplugin.endOfDirectory(HANDLE)


def in_progress_tvshows(params):
    """Afiseaza TOATE serialele in progres. Sursa unificata cu Up Next pentru sincronizare 100%."""
    from resources.lib import trakt_sync
    from concurrent.futures import ThreadPoolExecutor
    import datetime

    # === CITIM SETAREA INAINTE DE CACHE ===
    try: show_future = ADDON.getSetting('upnext_show_future') == 'true'
    except: show_future = False

    # === 1. FAST CACHE CHECK (RAM) ===
    # Bump LABEL_VERSION cand se modifica formatul label-urilor (e.g. culoare TBA)
    LABEL_VERSION = "2"
    cache_key = f"in_progress_tvshows_all_future_{show_future}_{LABEL_VERSION}"
    cached_data = get_fast_cache(cache_key)
    if cached_data:
        render_from_fast_cache(cached_data)
        return
    # ==================================

    try: icon = os.path.join(ADDON.getAddonInfo('path'), 'resources', 'media', 'in_progress_tvshow.png')
    except: icon = 'DefaultIcon.png'

    # Sursa de adevar este acum EXACT aceeasi ca la Up Next
    raw_items = trakt_sync.get_next_episodes_from_db()

    if not raw_items:
        add_directory("[COLOR cyan]No TV shows in progress. Sync Trakt.[/COLOR]",
                      {'mode': 'trakt_sync_db'}, folder=False, icon='DefaultIconInfo.png')
        xbmcplugin.endOfDirectory(HANDLE)
        return

    today = datetime.date.today()
    max_future_date = today + datetime.timedelta(days=7)

    # 2. FILTRARE STRICTA
    valid_shows = []
    for item in raw_items:
        tmdb_id = str(item['tmdb_id'])

        # Aplicam regula 7 zile / TBA
        if not show_future:
            air_date_str = item.get('air_date', '')
            if not air_date_str:
                # Nu are data de difuzare sau e TBA -> Ascundem
                continue
            try:
                parts = str(air_date_str).split('T')[0].split('-')
                air_date = datetime.date(int(parts[0]), int(parts[1]), int(parts[2]))
                if air_date > max_future_date:
                    # Apare peste mai mult de 7 zile -> Ascundem
                    continue 
            except:
                # Esec parsare data (probabil TBA) -> Ascundem
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

    # 4. CONSTRUIRE LISTA UI
    for item in valid_shows:
        tmdb_id = str(item['tmdb_id'])
        
        details = get_tmdb_item_details(tmdb_id, 'tv')
        if not details:
            continue

        # Calculam rapid episoadele din SQL / TMDB
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
        poster      = f"{IMG_BASE}{poster_path}" if poster_path else ''
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

        air_date_str = item.get('air_date', '')
        is_tba = not air_date_str

        if is_tba:
            label = f"[B][COLOR FFFF4444]{name} [COLOR yellow](TBA)[/COLOR][/B]"
        else:
            label = f"{name} ({year})" if year else name
            if curr_total > 0 and curr_watched >= curr_total:
                label += f" [B][COLOR lime](Complet)[/COLOR][/B]"
            elif curr_watched > 0:
                label = f"[B][COLOR FFEFD702]{label}[/COLOR] [COLOR FF6AFB92]({curr_watched}/{display_total})[/COLOR][/B]"
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
            'properties' : {
                'TotalEpisodes': str(watched_info_dict['total']) if watched_info_dict['total'] > 0 else '0',
                'WatchedEpisodes': str(watched_info_dict['watched']),
                'UnWatchedEpisodes': str(max(0, watched_info_dict['total'] - watched_info_dict['watched'])) if watched_info_dict['total'] > 0 else '',
                'PercentPlayed': str(int((float(watched_info_dict['watched'])/float(watched_info_dict['total']))*100)) if (watched_info_dict['total'] > 0 and 0 < watched_info_dict['watched'] < watched_info_dict['total']) else '',
            }
        })

    if items_to_add:
        xbmcplugin.addDirectoryItems(HANDLE, items_to_add, len(items_to_add))
    
    xbmcplugin.setContent(HANDLE, 'tvshows')
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=True)

    set_fast_cache(cache_key, cache_list)


def in_progress_episodes(params):
    """Afiseaza episoadele cu PLOT si METADATA COMPLETE (fara paginare)."""
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
    
    # 1. Trage detaliile serialelor in paralel
    prefetch_metadata_parallel(all_results, 'tv')
    
    # 2. Season prefetch (session dedicata + timeout scurt, inchisa la final)
    import threading, requests
    from resources.lib.config import BASE_URL, API_KEY, get_headers, get_plot_language, get_plot_language_code
    from resources.lib.cache import ram_cache_set_season

    ip_lang = get_plot_language_code()
    ip_tmdb_lang = get_plot_language()
    in_progress_session = requests.Session()
    def _prefetch_in_progress_season_worker(it):
        if xbmc.Monitor().abortRequested(): return
        try:
            t_id = str(it.get('id') or it.get('tmdb_id', ''))
            s_num = int(it.get('season', 0))
            if not t_id or not s_num: return
            url = f"{BASE_URL}/tv/{t_id}/season/{s_num}?api_key={API_KEY}&language={ip_tmdb_lang}"
            res = in_progress_session.get(url, headers=get_headers(), timeout=0.25)
            if res.status_code == 200:
                data = res.json()
                data['_cached_lang'] = ip_lang
                ram_cache_set_season(t_id, s_num, data)
        except:
            pass

    for itm in all_results:
        t = threading.Thread(target=_prefetch_in_progress_season_worker, args=(itm,))
        t.daemon = True
        t.start()

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
        base_poster = f"{IMG_BASE}{season_poster_path}" if season_poster_path else ''
        
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

        from resources.lib.watched_provider import is_mdblist as _is_mdb_provider
        _show_clr = 'lightskyblue' if _is_mdb_provider() else 'FF00CED1'
        display_label = f"[B][COLOR {_show_clr}]{show_name}[/COLOR][/B] - [B][COLOR FFCCCCCC]S{season:02d}E{episode:02d}[/COLOR][/B] - [B][COLOR FFCCCCFF][I]{ep_name}[/I][/COLOR][/B]"
        
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
        
        from resources.lib.watched_provider import get_label as _prov_label, get_color as _prov_color
        _prov_lbl = _prov_label()
        _prov_clr = _prov_color()
        cm = [
            (f'[B][COLOR FF6AFB92]Mark Watched [COLOR {_prov_clr}]({_prov_lbl})[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?mode=mark_watched&tmdb_id={tmdb_id}&type=episode&season={season}&episode={episode})"),
            ('[B][COLOR FFFF69B4]My Plays[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?mode=show_my_plays_menu&tmdb_id={tmdb_id}&type=episode&title={quote_plus(show_name)}&ep_name={quote_plus(ep_name)}&season={season}&episode={episode}&imdb_id={show_imdb_id}&premiered={premiered})"),
            ('[B]Scrape with Custom Values[/B]', f"RunPlugin({sys.argv[0]}?mode=sources&tmdb_id={tmdb_id}&type=tv&title={quote_plus(show_name)}&season={season}&episode={episode}&custom_interactive=true)"),
            ('[B][COLOR red]Delete Resume[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?mode=remove_progress&tmdb_id={tmdb_id}&type=episode&season={season}&episode={episode})")
        ]
        
        b_show_params = urlencode({'mode': 'details', 'tmdb_id': tmdb_id, 'type': 'tv', 'title': show_name})
        cm.append(('[B][COLOR cyan]Browse Show[/COLOR][/B]', f"Container.Update({sys.argv[0]}?{b_show_params})"))
        
        b_season_params = urlencode({'mode': 'episodes', 'tmdb_id': tmdb_id, 'season': str(season), 'tv_show_title': show_name})
        cm.append(('[B][COLOR cyan]Browse Season[/COLOR][/B]', f"Container.Update({sys.argv[0]}?{b_season_params})"))
        
        clear_p_params = urlencode({'mode': 'clear_sources_context', 'tmdb_id': tmdb_id, 'type': 'tv', 'season': str(season), 'episode': str(episode), 'title': f"{show_name} S{season:02d}E{episode:02d}"})
        cm.append(('[B][COLOR orange]Clear sources cache[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{clear_p_params})"))
        
        url_params = {'mode': 'sources', 'tmdb_id': tmdb_id, 'type': 'tv', 'season': str(season), 'episode': str(episode), 'title': ep_name, 'tv_show_title': show_name}
        
        if resume_seconds > 0:
            url_params['resume_time'] = resume_seconds
        
        url = f"{sys.argv[0]}?{urlencode(url_params)}"
        
        li = xbmcgui.ListItem(display_label)
        
        try: skin_compat = ADDON.getSetting('skin_type')
        except: skin_compat = '0'
        
        # AF3 ascunde thumb-ul daca e identic cu posterul → la modurile Poster (2/3)
        # thumb/landscape devin still-ul episodului (identic cu POV: thumb != poster)
        if art_pref in ('2', '3'):
            thumb_art = f"{IMG_BASE}{ep_still}" if has_still else ''
            landscape_art = thumb_art or ep_icon
        else:
            thumb_art = ep_icon
            landscape_art = ep_icon

        art_dict = {
            'thumb': thumb_art,
            'icon': ep_icon, 
            'landscape': landscape_art,
            'tvshow.landscape': landscape_art,
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
            'total_time': duration,
            'properties': {
                'episode_type': ep_type,
                'TotalEpisodes': str(show_watched_info['total']) if show_watched_info['total'] > 0 else '0',
                'WatchedEpisodes': str(show_watched_info['watched']),
                'UnWatchedEpisodes': str(max(0, show_watched_info['total'] - show_watched_info['watched'])) if show_watched_info['total'] > 0 else '',
                'PercentPlayed': str(int((float(show_watched_info['watched'])/float(show_watched_info['total']))*100)) if (show_watched_info['total'] > 0 and 0 < show_watched_info['watched'] < show_watched_info['total']) else '',
            }
        })
        
    if items_to_add:
        xbmcplugin.addDirectoryItems(HANDLE, items_to_add, len(items_to_add))
        
    xbmcplugin.setContent(HANDLE, 'episodes')
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=True)
    
    set_fast_cache(cache_key, cache_list)
    try:
        in_progress_session.close()
    except:
        pass


def get_next_episodes(params=None):
    """Afiseaza Next Episodes (Up Next) cu sortare avansata si filtrare 'dropped'.
    Sursa e dinamica: providerul de watched status decide (MDBList → mdblist_next_episodes,
    altfel → trakt_next_episodes)."""
    import datetime
    from resources.lib import trakt_sync

    # 1. OBTINEREA DATELOR BRUTE DIN BAZA DE DATE LOCALA (sursa dinamica pe provider)
    from resources.lib.watched_provider import is_mdblist as _is_mdblist_provider
    use_mdblist = _is_mdblist_provider()
    show_color = 'lightskyblue' if use_mdblist else 'FF00CED1'
    if use_mdblist:
        from resources.lib.mdblist_sync import get_next_episodes_from_db as _mdb_next
        raw_items = _mdb_next()
        for _it in raw_items:
            _it.setdefault('overview', '')
            _it.setdefault('poster', '')
    else:
        raw_items = trakt_sync.get_next_episodes_from_db()
    
    today = datetime.date.today()
    max_future_date = today + datetime.timedelta(days=7)

    # 2. CITIREA SETARILOR DIN settings.xml
    try:
        show_future = ADDON.getSetting('upnext_show_future') == 'true'
    except:
        show_future = False
        
    # 3. FILTRAREA SERIALELOR ABANDONATE (DROPPED/HIDDEN) - LOGICA NOUA
    #    (mdblist exclude deja mdblist_dropped in interogarea sa)
    if not use_mdblist:
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
        
        # Aplicam filtrele de data, inclusiv cel de 7 zile
        if air_date <= today:
            available_now.append(item)
        elif today < air_date <= max_future_date:
            upcoming_soon.append(item)
        else: # Mai mult de 7 zile in viitor
            if show_future: 
                later.append(item)
            
    # 5. SORTAREA INTELIGENTA (REPARATA SI MAI ROBUSTA)
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

    # A. Disponibile acum: sortate descrescator dupa ultima vizionare EXACTA
    available_now.sort(key=get_last_watched_ts, reverse=True)
    
    # B. Urmatoarele 7 zile: sortate cronologic (cel mai apropiat primul)
    upcoming_soon.sort(key=lambda x: x.get('air_date', ''))
    
    # C. Celelalte liste (daca sunt active)
    if show_future:
        # Peste 7 zile: sortate cronologic dupa data lansarii
        later.sort(key=lambda x: x.get('air_date', ''))
        # TBA: sortate alfabetic dupa numele serialului
        tba.sort(key=lambda x: x.get('show_title', ''))
        # Combinam listele strict in aceasta ordine
        items = available_now + upcoming_soon + later + tba
    else:
        # Daca setarea e OFF, ignoram complet later si tba
        items = available_now + upcoming_soon

    # 6. CONSTRUIREA LISTEI FINALE
    if not items:
        if use_mdblist:
            add_directory("[COLOR gray]No new episodes (Run 'MDBList Sync')[/COLOR]", {'mode': 'mdblist_sync'}, folder=False)
        else:
            add_directory("[COLOR gray]No new episodes (Run 'Trakt Sync')[/COLOR]", {'mode': 'trakt_sync_db'}, folder=False)
        xbmcplugin.endOfDirectory(HANDLE)
        return

    # Fast cache check (LABEL_VERSION bumped cand se schimba formatul label-urilor)
    LABEL_VERSION = "3"
    cache_key = f"next_episodes_all_future_{show_future}_{LABEL_VERSION}"
    cached_data = get_fast_cache(cache_key)
    if cached_data:
        render_from_fast_cache(cached_data)
        return

    # Prefetch-ul ramane pentru viteza (Trage detaliile serialelor in paralel)
    prefetch_metadata_parallel(items, 'tv')

    # =========================================================================
    # Season prefetch (foloseste get_smart_season_details pentru EN fallback)
    # =========================================================================
    from concurrent.futures import ThreadPoolExecutor
    def _prefetch_season_worker(it):
        if not xbmc.Monitor().abortRequested():
            get_smart_season_details(str(it['tmdb_id']), it['season'])
    executor = ThreadPoolExecutor(max_workers=5)
    for it in items:
        if not xbmc.Monitor().abortRequested():
            executor.submit(_prefetch_season_worker, it)
    executor.shutdown(wait=False)
    # =========================================================================

    items_to_add = []
    cache_list = []

    for it in items:
        tmdb_id = it['tmdb_id']
        
        # --- INCEPUT NOU: CALCUL EPISOADE RAMASE (AF3 / ESTUARY) ---
        show_watched_info = get_watched_status_tvshow(tmdb_id)
        unwatched_count = 0
        if show_watched_info['total'] > 0:
            unwatched_count = max(0, show_watched_info['total'] - show_watched_info['watched'])
        # --- SFARSIT NOU ---
        
        # 1. Extragem datele complete si garantat RO/EN (Aici se intampla magia Clearlogo!)
        show_details = get_tmdb_item_details(tmdb_id, 'tv', lightweight=True)
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
        
        # 4. Gasim episodul in baza noastra TMDb pentru a lua Durata, Stelutele (Rating) si Voturile!
        #    Cache first (RAM → SQLite) + API fallback
        from resources.lib.cache import ram_cache_get_season
        from resources.lib.config import get_plot_language_code
        _plot_lang = get_plot_language_code()
        season_data = ram_cache_get_season(tmdb_id, it['season'])
        if season_data:
            if season_data.get('_cached_lang') != _plot_lang:
                season_data = None
        if not season_data:
            season_data = trakt_sync.get_tmdb_season_details_from_db(tmdb_id, it['season'])
            if season_data:
                if season_data.get('_cached_lang') != _plot_lang:
                    season_data = None
        if not season_data:
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
                    ep_name_localized = ep.get('name', '').strip()
                    if ep_name_localized and not re.match(r'^[A-Za-z\u00c0-\u024f]+\s+\d+$', ep_name_localized):
                        it['ep_title'] = ep_name_localized
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
            
            # Determinam premiere/finale si pentru episoade nepublicate inca (ex: saptamana viitoare)
            if not ep_type and it['episode'] is not None:
                if it['episode'] == 1:
                    ep_type = 'series_premiere' if it['season'] == 1 else 'season_premiere'
                elif total_eps_in_season > 0 and it['episode'] == total_eps_in_season:
                    if show_status in['Ended', 'Canceled'] and it['season'] == total_seasons:
                        ep_type = 'series_finale'
                    else:
                        ep_type = 'season_finale'
                    
        # --- LOGICA NOUA IMAGINI UP NEXT (Standard Modern) ---
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
        # --- SFARSIT MODIFICARE ---

        # 5. Dam dictionarului info absolut tot (Acum Kodi stie durata si stelutele)
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
            'resume_percent': resume_percent # <--- ADAUGAT AICI PENTRU CERCULET
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
                
        label = f"[B][COLOR {show_color}]{it['show_title']}[/COLOR][/B] - [B][COLOR FFCCCCCC]S{it['season']:02d}E{it['episode']:02d}[/COLOR][/B] - [B][COLOR FFCCCCFF][I]{it['ep_title']}{badge}[/I][/COLOR][/B]"

        # Logica de afisare a datei pentru episoadele viitoare
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
                        zile_str = "Maine"
                    elif 1 < days_until <= 7:
                        zile_str = f"In {days_until} zile"
                    else:
                        zile_str = f"{parts[2]}.{parts[1]}.{parts[0]}"
                    label = f"[B][COLOR FFFF69B4]{it['show_title']}[/COLOR] [COLOR FFFF69B4]- S{it['season']:02d}E{it['episode']:02d}[/COLOR] - [I][COLOR FFCCCCFF]{it['ep_title']}[/COLOR][/I]  [COLOR yellow]({zile_str})[/COLOR]{badge}[/B]"
            except: 
                pass
        elif show_future: # TBA (fara data)
             label = f"[B][COLOR {show_color}]{it['show_title']}[/COLOR] [COLOR FFFF4444]- S{it['season']:02d}E{it['episode']:02d}[/COLOR] - [I][COLOR FFCCCCFF]{it['ep_title']}[/COLOR][/I]  [COLOR yellow](TBA)[/COLOR]{badge}[/B]"
             
        # --- NOU: AFISARE ESTUARY NUMAR EPISOADE RAMASE ---
        if skin_compat == '0' and unwatched_count > 0:
            label += f" [COLOR orange] ({unwatched_count})[/COLOR]"
        # --------------------------------------------------

        url_params = {'mode': 'sources', 'tmdb_id': tmdb_id, 'type': 'tv', 'season': str(it['season']), 'episode': str(it['episode']), 'title': it['ep_title'], 'tv_show_title': it['show_title']}

        # --- ADAUGAT: Trimitem timpul de resume catre player pentru a oferi optiunea "Resume from..." ---
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
        
        # --- INCEPUT ADAUGARE BROWSE OPTIONS ---
        # Browse Show (Afiseaza sezoanele)
        b_show_params = urlencode({'mode': 'details', 'tmdb_id': tmdb_id, 'type': 'tv', 'title': it['show_title']})
        cm.append(('[B][COLOR cyan]Browse Show[/COLOR][/B]', f"Container.Update({sys.argv[0]}?{b_show_params})"))
        
        # Browse Season (Afiseaza episoadele din sezonul curent)
        b_season_params = urlencode({'mode': 'episodes', 'tmdb_id': tmdb_id, 'season': str(it['season']), 'tv_show_title': it['show_title']})
        cm.append(('[B][COLOR cyan]Browse Season[/COLOR][/B]', f"Container.Update({sys.argv[0]}?{b_season_params})"))
        # --- SFARSIT ADAUGARE BROWSE OPTIONS ----
        
        # --- INCEPUT ADAUGARE NOUA: Clear Sources Cache pentru Up Next ---
        clear_p_params = urlencode({
            'mode': 'clear_sources_context', 
            'tmdb_id': tmdb_id, 
            'type': 'tv', 
            'season': str(it['season']), 
            'episode': str(it['episode']),
            'title': f"{it['show_title']} S{it['season']:02d}E{it['episode']:02d}"
        })
        cm.append(('[B][COLOR orange]Clear sources cache[/COLOR][/B]', f"RunPlugin({sys.argv[0]}?{clear_p_params})"))
        # --- SFARSIT ADAUGARE NOUA ---
        
        url = f"{sys.argv[0]}?{urlencode(url_params)}"
        li = xbmcgui.ListItem(label)
        
        try: skin_compat = ADDON.getSetting('skin_type')
        except: skin_compat = '0'
        
        # AF3 ascunde thumb-ul daca e identic cu posterul → la modurile Poster (2/3)
        # thumb/landscape devin still-ul episodului (identic cu POV: thumb != poster)
        if art_pref in ('2', '3'):
            thumb_art = f"{IMG_BASE}{ep_still}" if has_still else ''
            landscape_art = thumb_art or ep_icon
        else:
            thumb_art = ep_icon
            landscape_art = ep_icon

        art = {
            'thumb': thumb_art,
            'icon': ep_icon, 
            'landscape': landscape_art,
            'tvshow.landscape': landscape_art,
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
        # Modificat watched_info pentru a seta proprietatile AF3
        set_metadata(li, info, unique_ids={'tmdb': str(tmdb_id), 'imdb': imdb_id}, watched_info=show_watched_info)
        
        # --- ADAUGAT: Setam manual cercul de progres pentru Kodi ---
        from resources.lib.utils import set_resume_point
        set_resume_point(li, resume_seconds, duration)
        
        if cm: li.addContextMenuItems(cm)
        items_to_add.append((url, li, False))
        cache_list.append({
            'label': li.getLabel(), 'url': url, 'is_folder': False,
            'info': info, 'art': art, 'cm': cm,
            'resume_time': resume_seconds, 'total_time': duration,
            'properties': {
                'episode_type': ep_type,
                'TotalEpisodes': str(show_watched_info['total']) if show_watched_info['total'] > 0 else '0',
                'WatchedEpisodes': str(show_watched_info['watched']),
                'UnWatchedEpisodes': str(max(0, show_watched_info['total'] - show_watched_info['watched'])) if show_watched_info['total'] > 0 else '',
                'PercentPlayed': str(int((float(show_watched_info['watched'])/float(show_watched_info['total']))*100)) if (show_watched_info['total'] > 0 and 0 < show_watched_info['watched'] < show_watched_info['total']) else '',
            }
        })

    # === AICI SE TERMINA BUCLA FOR ===

    if items_to_add:
        xbmcplugin.addDirectoryItems(HANDLE, items_to_add, len(items_to_add))

    xbmcplugin.setContent(HANDLE, 'episodes')
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=True)
    set_fast_cache(cache_key, cache_list)
    try:
        season_session.close()
    except:
        pass


# FOR SEREN
def get_trakt_client_id():
    """Extrage Trakt client_id fara a genera erori in log daca addon-urile lipsesc."""
    import os
    import re
    import xbmc
    
    # Folosim xbmcvfs pentru a verifica daca un folder de addon exista, e mai sigur
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
            continue  # Sarim peste daca addon-ul nu e instalat
        
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
    
    # Fallback scan (doar daca Seren exista)
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
    """Converteste IMDb/TMDb ID → Trakt ID, fara erori in log."""
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
# MENU: MY PLAYS (Custom Player Launcher) - CU SUPORT SETARI
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
    
    # === CITIRE SETARI PLAYERE ===
    # != 'false' asigura ca, daca setarea nu a fost inca salvata in settings.xml, va functiona ca TRUE implicit.
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
        # External addon integration (optional player)
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
        meta_enc = "" # O definim aici sa fie accesibila si la Umbrella
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
                # Fallback: Search (nu necesita Trakt ID)
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

    # --- EXECUTIE ---
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
    """Proceseaza o lista in fundal cu intrerupere fortata (Zero Hang)."""
    monitor = xbmc.Monitor()
    window = xbmcgui.Window(10000)
    cache_key = f"list_{content_type}_{action}_{page}"
    
    if monitor.abortRequested() or window.getProperty('tmdbmovies_loading_active') == 'true' or get_fast_cache(cache_key):
        return

    results = None
    try:
        results = trakt_sync.get_tmdb_from_db(action, page)
        
        if not results:
            if monitor.abortRequested() or window.getProperty('tmdbmovies_loading_active') == 'true':
                return
            string = f"{action}_{page}_{LANG}"
            data = cache_object(get_tmdb_movies_standard if content_type == 'movie' else get_tmdb_tv_standard, 
                                string, [action, page], expiration=1)
            if data: results = data.get('results', [])
    except: pass
    
    if not results or monitor.abortRequested() or window.getProperty('tmdbmovies_loading_active') == 'true':
        return

    cache_list = []
    items_to_process = results[:15] 
    
    for item in items_to_process:
        if monitor.abortRequested() or window.getProperty('tmdbmovies_loading_active') == 'true':
            return
        
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

    if len(cache_list) > 0 and not (monitor.abortRequested() or window.getProperty('tmdbmovies_loading_active') == 'true'):
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
    """Lanseaza warmup-ul intr-un invoker Kodi separat (nu blocheaza plugin-ul)."""
    window = xbmcgui.Window(10000)
    if window.getProperty('tmdbmovies_warmup_busy') == 'true' or \
       window.getProperty('tmdbmovies_loading_active') == 'true':
        return
    import urllib.parse
    xbmc.executebuiltin(f'RunPlugin(plugin://plugin.video.tmdbmovies/?mode=background_warmup&type={content_type})')


def run_background_warmup_sync(content_type):
    """Executa warmup-ul sincron (intr-un invoker separat)."""
    import time
    window = xbmcgui.Window(10000)
    if window.getProperty('tmdbmovies_warmup_busy') == 'true':
        return
    window.setProperty('tmdbmovies_warmup_busy', 'true')
    monitor = xbmc.Monitor()
    
    try:
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
            delay = 0.3
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
            delay = 0.7

        if monitor.waitForAbort(1.0): return

        for act in actions:
            if monitor.abortRequested() or window.getProperty('tmdbmovies_loading_active') == 'true':
                log("[WARMUP] User activity detected. Killing background task for stability.")
                break
            
            process_single_list_warmup(act, content_type, 1)
            
            if monitor.waitForAbort(delay): break
    finally:
        window.clearProperty('tmdbmovies_warmup_busy')

def trigger_next_page_warmup(action, current_page, content_type):
    """Pre-fetch 1-2 pagini inline (lista e deja randata, delay invizibil). Fara thread."""
    import time
    from resources.lib.cache import cache_object
    from resources.lib.trakt_sync import get_tmdb_from_db
    
    deadline = time.time() + 0.5
    for i in range(1, 3):
        if time.time() > deadline: break
        if get_tmdb_from_db(action, current_page + i):
            continue
        try:
            if content_type == 'movie':
                cache_object(get_tmdb_movies_standard, f"{action}_{current_page + i}_{LANG}", [action, current_page + i], expiration=24)
            else:
                cache_object(get_tmdb_tv_standard, f"{action}_{current_page + i}_{LANG}", [action, current_page + i], expiration=24)
        except:
            break
    

def navigator_genres(params):
    menu_type = params.get('menu_type', 'movie')
    icons_path = os.path.join(ADDON_PATH, 'resources', 'media')
    genre_icon = os.path.join(icons_path, 'genres.png')

    if menu_type == 'movie':
        genre_list = menus.MOVIE_GENRES
    else:
        genre_list = menus.TV_GENRES

    add_directory('[B]Multiselect[/B]',
                 {'mode': 'multiselect_genres', 'media_type': menu_type},
                 icon=os.path.join(icons_path, 'item_next.png'), folder=False)

    for genre in genre_list:
        add_directory(genre['name'],
                     {'mode': 'list_by_genre', 'media_type': menu_type, 'genre_id': str(genre['id'])},
                     icon=genre_icon, folder=True)

    xbmcplugin.endOfDirectory(HANDLE)


def multiselect_genres(params):
    menu_type = params.get('media_type', 'movie')

    if menu_type == 'movie':
        genre_list = menus.MOVIE_GENRES
    else:
        genre_list = menus.TV_GENRES

    dialog = xbmcgui.Dialog()
    items = [genre['name'] for genre in genre_list]
    selected = dialog.multiselect('Select Genres', items)

    if selected is None or selected == []:
        return

    genre_ids = ','.join([str(genre_list[i]['id']) for i in selected])
    url_params = {'mode': 'list_by_genre', 'media_type': menu_type, 'genre_id': genre_ids}
    url = f"{sys.argv[0]}?{urlencode(url_params)}"
    xbmc.executebuiltin('Container.Update(%s)' % url)


def navigator_years(params):
    menu_type = params.get('menu_type', 'movie')
    import datetime
    current_year = datetime.datetime.now().year
    icons_path = os.path.join(ADDON_PATH, 'resources', 'media')
    cal_icon = os.path.join(icons_path, 'calender.png')

    for year in range(current_year, 1999, -1):
        add_directory(str(year),
                     {'mode': 'list_by_year', 'media_type': menu_type, 'year': str(year)},
                     icon=cal_icon, folder=True)

    xbmcplugin.endOfDirectory(HANDLE)


def list_by_genre(params):
    media_type = params.get('media_type', 'movie')
    genre_id = params.get('genre_id')
    page = int(params.get('page', '1'))

    if not genre_id:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    cache_key = f"genre_{media_type}_{genre_id}_{page}"
    cached_data = get_fast_cache(cache_key)
    if cached_data:
        render_from_fast_cache(cached_data)
        return

    if media_type == 'movie':
        url = f"{BASE_URL}/discover/movie?api_key={API_KEY}&language={LANG}&with_genres={genre_id}&page={page}&sort_by=popularity.desc&vote_count.gte=10"
    else:
        url = f"{BASE_URL}/discover/tv?api_key={API_KEY}&language={LANG}&with_genres={genre_id}&page={page}&sort_by=popularity.desc&vote_count.gte=10"

    data = get_json(url)
    if not data or not data.get('results'):
        xbmcplugin.endOfDirectory(HANDLE)
        return

    results = data['results']
    prefetch_metadata_parallel(results, media_type)

    items_to_add = []
    cache_list = []

    for item in results:
        processed = _process_movie_item(item, return_data=True) if media_type == 'movie' else _process_tv_item(item, return_data=True)
        if processed:
            items_to_add.append((processed['url'], processed['li'], processed['is_folder']))
            cache_list.append(processed)

    total_pages = data.get('total_pages', 1)
    if page < total_pages:
        next_label = f"[B]Next Page ({page+1}) >>[/B]"
        next_params = {'mode': 'list_by_genre', 'media_type': media_type, 'genre_id': genre_id, 'page': str(page+1)}
        next_url = f"{sys.argv[0]}?{urlencode(next_params)}"
        next_li = xbmcgui.ListItem(next_label)
        next_li.setArt({'icon': NEXT_PAGE_ICON, 'thumb': NEXT_PAGE_ICON})
        items_to_add.append((next_url, next_li, True))
        cache_list.append({'label': next_label, 'url': next_url, 'is_folder': True, 'art': {'icon': NEXT_PAGE_ICON}, 'info': {'mediatype': 'video'}, 'cm_items': []})

    if items_to_add:
        xbmcplugin.addDirectoryItems(HANDLE, items_to_add, len(items_to_add))

    xbmcplugin.setContent(HANDLE, 'movies' if media_type == 'movie' else 'tvshows')
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=True)
    set_fast_cache(cache_key, [{'label': i['li'].getLabel() if 'li' in i else i['label'], 'url': i['url'], 'is_folder': i['is_folder'], 'art': i['art'], 'info': i['info'], 'cm': i['cm_items'], 'resume_time': i.get('resume_time', 0), 'total_time': i.get('total_time', 0)} for i in cache_list])


def list_by_year(params):
    media_type = params.get('media_type', 'movie')
    year = params.get('year')
    page = int(params.get('page', '1'))

    if not year:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    cache_key = f"year_{media_type}_{year}_{page}"
    cached_data = get_fast_cache(cache_key)
    if cached_data:
        render_from_fast_cache(cached_data)
        return

    if media_type == 'movie':
        url = f"{BASE_URL}/discover/movie?api_key={API_KEY}&language={LANG}&primary_release_year={year}&page={page}&sort_by=popularity.desc&vote_count.gte=10"
    else:
        url = f"{BASE_URL}/discover/tv?api_key={API_KEY}&language={LANG}&first_air_date_year={year}&page={page}&sort_by=popularity.desc&vote_count.gte=10"

    data = get_json(url)
    if not data or not data.get('results'):
        xbmcplugin.endOfDirectory(HANDLE)
        return

    results = data['results']
    prefetch_metadata_parallel(results, media_type)

    items_to_add = []
    cache_list = []

    for item in results:
        processed = _process_movie_item(item, return_data=True) if media_type == 'movie' else _process_tv_item(item, return_data=True)
        if processed:
            items_to_add.append((processed['url'], processed['li'], processed['is_folder']))
            cache_list.append(processed)

    total_pages = data.get('total_pages', 1)
    if page < total_pages:
        next_label = f"[B]Next Page ({page+1}) >>[/B]"
        next_params = {'mode': 'list_by_year', 'media_type': media_type, 'year': year, 'page': str(page+1)}
        next_url = f"{sys.argv[0]}?{urlencode(next_params)}"
        next_li = xbmcgui.ListItem(next_label)
        next_li.setArt({'icon': NEXT_PAGE_ICON, 'thumb': NEXT_PAGE_ICON})
        items_to_add.append((next_url, next_li, True))
        cache_list.append({'label': next_label, 'url': next_url, 'is_folder': True, 'art': {'icon': NEXT_PAGE_ICON}, 'info': {'mediatype': 'video'}, 'cm_items': []})

    if items_to_add:
        xbmcplugin.addDirectoryItems(HANDLE, items_to_add, len(items_to_add))

    xbmcplugin.setContent(HANDLE, 'movies' if media_type == 'movie' else 'tvshows')
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=True)
    set_fast_cache(cache_key, [{'label': i['li'].getLabel() if 'li' in i else i['label'], 'url': i['url'], 'is_folder': i['is_folder'], 'art': i['art'], 'info': i['info'], 'cm': i['cm_items'], 'resume_time': i.get('resume_time', 0), 'total_time': i.get('total_time', 0)} for i in cache_list])


def navigator_providers(params):
    menu_type = params.get('menu_type', 'movie')
    icons_path = os.path.join(ADDON_PATH, 'resources', 'media')
    fallback_icon = os.path.join(icons_path, f'{menu_type}.png')

    url = f"{BASE_URL}/watch/providers/{menu_type}?api_key={API_KEY}&language={LANG}&watch_region=US"
    data = get_json(url)

    if not data or not data.get('results'):
        xbmcplugin.endOfDirectory(HANDLE)
        return

    for provider in data['results']:
        thumb = None
        if provider.get('logo_path'):
            thumb = f"https://image.tmdb.org/t/p/original{provider['logo_path']}"
        add_directory(provider['provider_name'],
                     {'mode': 'list_by_provider', 'media_type': menu_type, 'provider_id': str(provider['provider_id'])},
                     icon=thumb or fallback_icon, thumb=thumb, folder=True)

    xbmcplugin.endOfDirectory(HANDLE)


def list_by_provider(params):
    media_type = params.get('media_type', 'movie')
    provider_id = params.get('provider_id')
    page = int(params.get('page', '1'))

    if not provider_id:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    cache_key = f"provider_{media_type}_{provider_id}_{page}"
    cached_data = get_fast_cache(cache_key)
    if cached_data:
        render_from_fast_cache(cached_data)
        return

    if media_type == 'movie':
        url = f"{BASE_URL}/discover/movie?api_key={API_KEY}&language={LANG}&region=US&watch_region=US&with_watch_providers={provider_id}&page={page}&sort_by=popularity.desc&vote_count.gte=10"
    else:
        url = f"{BASE_URL}/discover/tv?api_key={API_KEY}&language={LANG}&region=US&watch_region=US&with_watch_providers={provider_id}&page={page}&sort_by=popularity.desc&vote_count.gte=10"

    data = get_json(url)
    if not data or not data.get('results'):
        xbmcplugin.endOfDirectory(HANDLE)
        return

    results = data['results']
    prefetch_metadata_parallel(results, media_type)

    items_to_add = []
    cache_list = []

    for item in results:
        processed = _process_movie_item(item, return_data=True) if media_type == 'movie' else _process_tv_item(item, return_data=True)
        if processed:
            items_to_add.append((processed['url'], processed['li'], processed['is_folder']))
            cache_list.append(processed)

    total_pages = data.get('total_pages', 1)
    if page < total_pages:
        next_label = f"[B]Next Page ({page+1}) >>[/B]"
        next_params = {'mode': 'list_by_provider', 'media_type': media_type, 'provider_id': provider_id, 'page': str(page+1)}
        next_url = f"{sys.argv[0]}?{urlencode(next_params)}"
        next_li = xbmcgui.ListItem(next_label)
        next_li.setArt({'icon': NEXT_PAGE_ICON, 'thumb': NEXT_PAGE_ICON})
        items_to_add.append((next_url, next_li, True))
        cache_list.append({'label': next_label, 'url': next_url, 'is_folder': True, 'art': {'icon': NEXT_PAGE_ICON}, 'info': {'mediatype': 'video'}, 'cm_items': []})

    if items_to_add:
        xbmcplugin.addDirectoryItems(HANDLE, items_to_add, len(items_to_add))

    xbmcplugin.setContent(HANDLE, 'movies' if media_type == 'movie' else 'tvshows')
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=True)
    set_fast_cache(cache_key, [{'label': i['li'].getLabel() if 'li' in i else i['label'], 'url': i['url'], 'is_folder': i['is_folder'], 'art': i['art'], 'info': i['info'], 'cm': i['cm_items'], 'resume_time': i.get('resume_time', 0), 'total_time': i.get('total_time', 0)} for i in cache_list])


def list_highest_revenue(params):
    media_type = params.get('media_type', 'movie')
    page = int(params.get('page', '1'))

    cache_key = f"highest_revenue_{page}"
    cached_data = get_fast_cache(cache_key)
    if cached_data:
        render_from_fast_cache(cached_data)
        return

    url = f"{BASE_URL}/discover/movie?api_key={API_KEY}&language={LANG}&region=US&page={page}&sort_by=revenue.desc&vote_count.gte=10"

    data = get_json(url)
    if not data or not data.get('results'):
        xbmcplugin.endOfDirectory(HANDLE)
        return

    results = data['results']
    prefetch_metadata_parallel(results, media_type)

    items_to_add = []
    cache_list = []

    for item in results:
        processed = _process_movie_item(item, return_data=True)
        if processed:
            items_to_add.append((processed['url'], processed['li'], processed['is_folder']))
            cache_list.append(processed)

    total_pages = data.get('total_pages', 1)
    if page < total_pages:
        next_label = f"[B]Next Page ({page+1}) >>[/B]"
        next_params = {'mode': 'list_highest_revenue', 'page': str(page+1)}
        next_url = f"{sys.argv[0]}?{urlencode(next_params)}"
        next_li = xbmcgui.ListItem(next_label)
        next_li.setArt({'icon': NEXT_PAGE_ICON, 'thumb': NEXT_PAGE_ICON})
        items_to_add.append((next_url, next_li, True))
        cache_list.append({'label': next_label, 'url': next_url, 'is_folder': True, 'art': {'icon': NEXT_PAGE_ICON}, 'info': {'mediatype': 'video'}, 'cm_items': []})

    if items_to_add:
        xbmcplugin.addDirectoryItems(HANDLE, items_to_add, len(items_to_add))

    xbmcplugin.setContent(HANDLE, 'movies')
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=True)
    set_fast_cache(cache_key, [{'label': i['li'].getLabel() if 'li' in i else i['label'], 'url': i['url'], 'is_folder': i['is_folder'], 'art': i['art'], 'info': i['info'], 'cm': i['cm_items'], 'resume_time': i.get('resume_time', 0), 'total_time': i.get('total_time', 0)} for i in cache_list])


def list_most_voted(params):
    media_type = params.get('media_type', 'movie')
    page = int(params.get('page', '1'))

    cache_key = f"most_voted_{media_type}_{page}"
    cached_data = get_fast_cache(cache_key)
    if cached_data:
        render_from_fast_cache(cached_data)
        return

    if media_type == 'movie':
        url = f"{BASE_URL}/discover/movie?api_key={API_KEY}&language={LANG}&region=US&page={page}&sort_by=vote_count.desc&vote_count.gte=10"
    else:
        url = f"{BASE_URL}/discover/tv?api_key={API_KEY}&language={LANG}&region=US&page={page}&sort_by=vote_count.desc&vote_count.gte=10"

    data = get_json(url)
    if not data or not data.get('results'):
        xbmcplugin.endOfDirectory(HANDLE)
        return

    results = data['results']
    prefetch_metadata_parallel(results, media_type)

    items_to_add = []
    cache_list = []

    for item in results:
        processed = _process_movie_item(item, return_data=True) if media_type == 'movie' else _process_tv_item(item, return_data=True)
        if processed:
            items_to_add.append((processed['url'], processed['li'], processed['is_folder']))
            cache_list.append(processed)

    total_pages = data.get('total_pages', 1)
    if page < total_pages:
        next_label = f"[B]Next Page ({page+1}) >>[/B]"
        next_params = {'mode': 'list_most_voted', 'media_type': media_type, 'page': str(page+1)}
        next_url = f"{sys.argv[0]}?{urlencode(next_params)}"
        next_li = xbmcgui.ListItem(next_label)
        next_li.setArt({'icon': NEXT_PAGE_ICON, 'thumb': NEXT_PAGE_ICON})
        items_to_add.append((next_url, next_li, True))
        cache_list.append({'label': next_label, 'url': next_url, 'is_folder': True, 'art': {'icon': NEXT_PAGE_ICON}, 'info': {'mediatype': 'video'}, 'cm_items': []})

    if items_to_add:
        xbmcplugin.addDirectoryItems(HANDLE, items_to_add, len(items_to_add))

    xbmcplugin.setContent(HANDLE, 'movies' if media_type == 'movie' else 'tvshows')
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=True)
    set_fast_cache(cache_key, [{'label': i['li'].getLabel() if 'li' in i else i['label'], 'url': i['url'], 'is_folder': i['is_folder'], 'art': i['art'], 'info': i['info'], 'cm': i['cm_items'], 'resume_time': i.get('resume_time', 0), 'total_time': i.get('total_time', 0)} for i in cache_list])


def navigator_networks(params):
    menu_type = params.get('menu_type', 'tv')
    page = int(params.get('page', '1'))
    per_page = 50
    icons_path = os.path.join(ADDON_PATH, 'resources', 'media')
    fallback_icon = os.path.join(icons_path, 'networks.png')

    networks = menus.TV_NETWORKS
    total = len(networks)
    start = (page - 1) * per_page
    end = min(start + per_page, total)
    page_networks = networks[start:end]

    def fetch_logo(net):
        nid = str(net['id'])
        net_url = f"{BASE_URL}/network/{nid}?api_key={API_KEY}"
        net_data = get_json(net_url)
        if net_data and net_data.get('logo_path'):
            return nid, f"{IMG_BASE}{net_data['logo_path']}"
        return nid, None

    logos = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fetch_logo, net): net for net in page_networks}
        for future in as_completed(futures):
            nid, logo = future.result()
            logos[nid] = logo

    for network in page_networks:
        nid = str(network['id'])
        thumb = logos.get(nid)
        add_directory(network['name'],
                     {'mode': 'list_by_network', 'media_type': menu_type, 'network_id': nid},
                     icon=thumb or fallback_icon, thumb=thumb, folder=True)

    if end < total:
        add_directory(f"[B]Next Page ({page+1}) >>[/B]",
                     {'mode': 'navigator_networks', 'menu_type': menu_type, 'page': str(page+1)},
                     icon=os.path.join(icons_path, 'item_next.png'), folder=True)

    xbmcplugin.endOfDirectory(HANDLE)


def list_by_network(params):
    media_type = params.get('media_type', 'tv')
    network_id = params.get('network_id')
    page = int(params.get('page', '1'))

    if not network_id:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    cache_key = f"network_{media_type}_{network_id}_{page}"
    cached_data = get_fast_cache(cache_key)
    if cached_data:
        render_from_fast_cache(cached_data)
        return

    url = f"{BASE_URL}/discover/tv?api_key={API_KEY}&language={LANG}&region=US&with_networks={network_id}&page={page}&sort_by=popularity.desc&vote_count.gte=10"

    data = get_json(url)
    if not data or not data.get('results'):
        xbmcplugin.endOfDirectory(HANDLE)
        return

    results = data['results']
    prefetch_metadata_parallel(results, media_type)

    items_to_add = []
    cache_list = []

    for item in results:
        processed = _process_tv_item(item, return_data=True)
        if processed:
            items_to_add.append((processed['url'], processed['li'], processed['is_folder']))
            cache_list.append(processed)

    total_pages = data.get('total_pages', 1)
    if page < total_pages:
        next_label = f"[B]Next Page ({page+1}) >>[/B]"
        next_params = {'mode': 'list_by_network', 'media_type': media_type, 'network_id': network_id, 'page': str(page+1)}
        next_url = f"{sys.argv[0]}?{urlencode(next_params)}"
        next_li = xbmcgui.ListItem(next_label)
        next_li.setArt({'icon': NEXT_PAGE_ICON, 'thumb': NEXT_PAGE_ICON})
        items_to_add.append((next_url, next_li, True))
        cache_list.append({'label': next_label, 'url': next_url, 'is_folder': True, 'art': {'icon': NEXT_PAGE_ICON}, 'info': {'mediatype': 'video'}, 'cm_items': []})

    if items_to_add:
        xbmcplugin.addDirectoryItems(HANDLE, items_to_add, len(items_to_add))

    xbmcplugin.setContent(HANDLE, 'tvshows')
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=True)
    set_fast_cache(cache_key, [{'label': i['li'].getLabel() if 'li' in i else i['label'], 'url': i['url'], 'is_folder': i['is_folder'], 'art': i['art'], 'info': i['info'], 'cm': i['cm_items'], 'resume_time': i.get('resume_time', 0), 'total_time': i.get('total_time', 0)} for i in cache_list])
