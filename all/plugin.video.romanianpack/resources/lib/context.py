# -*- coding: utf-8 -*-
import sys
import xbmc
import xbmcaddon
import xbmcgui
from resources.functions import log

try:
    import urllib.parse as urllib
except ImportError:
    import urllib

def quote(text):
    if sys.version_info.major < 3 and isinstance(text, unicode):
        text = text.encode('utf-8')
    return urllib.quote_plus(str(text))

def log_debug(msg):
    log("[CONTEXT-DEBUG] %s" % msg)

if __name__ == '__main__':
    addon_id = 'plugin.video.romanianpack'
    addon = xbmcaddon.Addon(id=addon_id)
    search_mode = addon.getSetting('context_trakt_search_mode')
    base_url = 'plugin://%s' % addon_id
    
    # Preluam item-ul selectat
    list_item = sys.listitem
    
    # === ZONA DEBUGGING EXTINS ===
    log_debug("================ START CONTEXT MENU ================")
    log_debug("Label item: %s" % list_item.getLabel())
    log_debug("Path item: %s" % list_item.getPath())
    
    # 1. Verificare InfoTag (Metoda noua Kodi)
    info_tag = list_item.getVideoInfoTag()
    log_debug("MediaType: %s" % info_tag.getMediaType())
    log_debug("InfoTag IMDb: %s" % info_tag.getIMDBNumber())
    try:
        log_debug("InfoTag UniqueIDs: %s" % str(info_tag.getUniqueIDs()))
    except:
        log_debug("InfoTag UniqueIDs: Eroare citire")

    # 2. Verificare TOATE proprietatile posibile
    # Verificam ce proprietati exista efectiv pe item
    potential_keys = [
        'tmdb_id', 'TMDb_ID', 'tmdb', 'id', 'TMDb', 'tmdbid', 
        'imdb_id', 'IMDb_ID', 'imdb', 'imdbnumber', 'IMDBNumber', 
        'tvdb_id', 'season', 'episode', 'Season', 'Episode', 'Year', 'year',
        'dbid', 'dbtype'
    ]
    
    found_props = {}
    for key in potential_keys:
        val = list_item.getProperty(key)
        if val:
            found_props[key] = val
            log_debug("PROPERTY FOUND: Key='%s' -> Value='%s'" % (key, val))
            
    if not found_props:
        log_debug("Nicio proprietate relevanta gasita pe ListItem!")

    # 3. Verificare Window Properties (Fallback)
    win = xbmcgui.Window(10000)
    win_props = {}
    for key in ['TMDb_ID', 'tmdb_id', 'tmdb', 'VideoPlayer.TMDb', 'IMDb_ID', 'imdb_id', 'imdb']:
        val = win.getProperty(key)
        if val:
            win_props[key] = val
            log_debug("WINDOW PROPERTY: Key='%s' -> Value='%s'" % (key, val))
    # ==============================

    dbtype = info_tag.getMediaType()
    dbid = info_tag.getDbId()
    
    # --- LOGICA DE EXTRAGERE ---
    imdb_id = None
    tmdb_id = None
    
    # Prioritate 1: InfoTag UniqueIDs
    try:
        unique_ids = info_tag.getUniqueIDs()
        if unique_ids:
            if 'imdb' in unique_ids: imdb_id = unique_ids['imdb']
            if 'tmdb' in unique_ids: tmdb_id = unique_ids['tmdb']
    except: pass
    
    if imdb_id: log_debug("ID gasit in InfoTag: IMDb=%s" % imdb_id)
    if tmdb_id: log_debug("ID gasit in InfoTag: TMDb=%s" % tmdb_id)

    # === START MODIFICARE: PRIORITATE STRICTĂ SURSE SIGURE ===
    # 1. Încercăm prima dată din PATH-ul itemului (cel mai sigur pentru addonuri externe)
    if not tmdb_id or not imdb_id:
        try:
            path = list_item.getPath()
            if '?' in path:
                from urllib.parse import parse_qs, urlparse
                params_path = parse_qs(urlparse(path).query)
                if not tmdb_id and 'tmdb_id' in params_path:
                    tmdb_id = params_path['tmdb_id'][0]
                    log_debug("ID gasit in Path: TMDb=%s" % tmdb_id)
                if not imdb_id and 'imdb_id' in params_path:
                    imdb_id = params_path['imdb_id'][0]
                    log_debug("ID gasit in Path: IMDb=%s" % imdb_id)
                if season == -1 and 'season' in params_path:
                    season = int(params_path['season'][0])
                if episode == -1 and 'episode' in params_path:
                    episode = int(params_path['episode'][0])
                if not dbtype and 'type' in params_path:
                    dbtype = params_path['type'][0]
        except: pass

    # 2. Încercăm din proprietățile locale ale itemului (setate in addonul sursa)
    if not tmdb_id:
        for key in ['tmdb_id', 'TMDb_ID', 'tmdb', 'tmdbid']:
            val = list_item.getProperty(key)
            if val and str(val).isdigit():
                tmdb_id = val
                log_debug("ID gasit in Local Property '%s': TMDb=%s" % (key, tmdb_id))
                break
        
    if not imdb_id:
        for key in ['imdb_id', 'IMDb_ID', 'imdb', 'imdbnumber']:
            val = list_item.getProperty(key)
            if val and str(val).startswith('tt'):
                imdb_id = val
                log_debug("ID gasit in Local Property '%s': IMDb=%s" % (key, imdb_id))
                break

    # 3. DOAR DACĂ NU AM GĂSIT NIMIC în sursele de mai sus (Path sau Local), verificăm Window Properties.
    # Această condiție "if not tmdb_id and not imdb_id" este CRITICĂ: 
    # ea previne mixarea unui ID corect din link cu un ID vechi/murdar din fereastra Kodi 10000.
    if not tmdb_id and not imdb_id:
        win = xbmcgui.Window(10000)
        log_debug("Niciun ID gasit in Path/Local. Verificam Window Properties...")
        if not tmdb_id:
            for key in ['TMDb_ID', 'tmdb_id', 'tmdb', 'VideoPlayer.TMDb']:
                val = win.getProperty(key)
                if val and str(val).isdigit():
                    tmdb_id = val
                    log_debug("ID gasit in Window Property: TMDb=%s" % tmdb_id)
                    break
        if not imdb_id:
            for key in ['IMDb_ID', 'imdb_id', 'imdb', 'VideoPlayer.IMDb', 'VideoPlayer.IMDBNumber']:
                val = win.getProperty(key)
                if val and str(val).startswith('tt'):
                    imdb_id = val
                    log_debug("ID gasit in Window Property: IMDb=%s" % imdb_id)
                    break
    # === SFÂRȘIT MODIFICARE ===
    
    # --- Constructie Cautare ---
    search_term = ""
    title = info_tag.getTitle()
    if not title:
        title = list_item.getLabel()

    # Detectie Sezon/Episod
    season = info_tag.getSeason()
    episode = info_tag.getEpisode()
    
    if season == -1:
        s_prop = list_item.getProperty('Season') or list_item.getProperty('season')
        if s_prop and str(s_prop).isdigit(): season = int(s_prop)
        
    if episode == -1:
        e_prop = list_item.getProperty('Episode') or list_item.getProperty('episode')
        if e_prop and str(e_prop).isdigit(): episode = int(e_prop)

    log_debug("Date detectate -> Title: %s | Season: %s | Episode: %s" % (title, season, episode))

    params_extra = ""

    if dbtype == 'episode' or (season > -1 and episode > -1):
        show_title = info_tag.getTVShowTitle()
        if not show_title:
            # Incercam proprietati pentru showtitle
            show_title = list_item.getProperty('tvshowtitle') or list_item.getProperty('showtitle')
        
        if not show_title:
            show_title = title # Fallback la titlu
            
        if season > -1:
            term_full = '%s S%02dE%02d' % (show_title, season, episode)
            term_season = '%s S%02d' % (show_title, season)
            search_term = term_season if search_mode == '2' else term_full
            
            params_extra = "&season=%s&episode=%s&showname=%s&mediatype=episode" % (season, episode, quote(show_title))
        else:
            search_term = show_title
            params_extra = "&mediatype=tv"
    else:
        year = info_tag.getYear()
        if not year:
            y_prop = list_item.getProperty('Year') or list_item.getProperty('year')
            if y_prop and str(y_prop).isdigit(): year = int(y_prop)
            
        if year:
            search_term = '%s %d' % (title, year)
        else:
            search_term = title
        params_extra = "&mediatype=movie"

    if search_term:
        params = ""
        if imdb_id: params += '&imdb_id=%s' % quote(str(imdb_id))
        if tmdb_id: params += '&tmdb_id=%s' % quote(str(tmdb_id))
        if dbid and int(dbid) > 0: params += '&kodi_dbtype=%s&kodi_dbid=%s' % (dbtype, dbid)
            
        params += params_extra
        
        log_debug("QUERY FINAL: Term='%s' | Params='%s'" % (search_term, params))
        
        if search_mode == '0':
            final_url = '%s?action=searchSites&modalitate=edit&query=%s%s' % (base_url, quote(search_term), params)
        else:
            final_url = '%s?action=searchSites&searchSites=cuvant&cuvant=%s%s' % (base_url, quote(search_term), params)
            
        xbmc.executebuiltin('Container.Update(%s)' % final_url)
    else:
        log_debug("Esec: Nu s-a putut construi termenul de cautare.")
        xbmc.executebuiltin('Notification(MRSP, Nu s-au putut extrage detalii, 3000)')