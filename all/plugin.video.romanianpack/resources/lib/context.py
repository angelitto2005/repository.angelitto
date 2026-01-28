# -*- coding: utf-8 -*-
import sys
import xbmc
import xbmcaddon

try:
    import urllib.parse as urllib
except ImportError:
    import urllib

def quote(text):
    if sys.version_info.major < 3 and isinstance(text, unicode):
        text = text.encode('utf-8')
    return urllib.quote_plus(str(text))

if __name__ == '__main__':
    addon_id = 'plugin.video.romanianpack'
    addon = xbmcaddon.Addon(id=addon_id)
    search_mode = addon.getSetting('context_trakt_search_mode')
    base_url = 'plugin://%s' % addon_id
    
    list_item = sys.listitem
    info_tag = list_item.getVideoInfoTag()
    
    dbtype = info_tag.getMediaType()
    dbid = info_tag.getDbId()
    
    # --- EXTRAGERE EXTINSA ID-uri ---
    imdb_id = info_tag.getIMDBNumber()
    tmdb_id = None
    
    # 1. Cautam in UniqueIDs (Metoda standard Kodi)
    try:
        unique_ids = info_tag.getUniqueIDs()
        if unique_ids:
            if not imdb_id and 'imdb' in unique_ids:
                imdb_id = unique_ids['imdb']
            if 'tmdb' in unique_ids:
                tmdb_id = unique_ids['tmdb']
    except: pass

    # 2. Fallback: Cautam in Properties (TMDbHelper si alte addonuri pun ID-urile aici)
    if not tmdb_id:
        try:
            tmdb_id = list_item.getProperty('tmdb_id') or list_item.getProperty('TMDb_ID')
        except: pass
        
    if not imdb_id:
        try:
            imdb_id = list_item.getProperty('imdb_id') or list_item.getProperty('IMDb_ID')
        except: pass

    # --- Constructie Cautare ---
    search_term = ""
    title = info_tag.getTitle()
    if not title:
        title = list_item.getLabel()

    if dbtype == 'episode' or (info_tag.getSeason() > -1 and info_tag.getEpisode() > -1):
        show_title = info_tag.getTVShowTitle()
        if not show_title:
            show_title = title
        season = info_tag.getSeason()
        episode = info_tag.getEpisode()
        
        if season > -1:
            term_full = '%s S%02dE%02d' % (show_title, season, episode)
            term_season = '%s S%02d' % (show_title, season)
            search_term = term_season if search_mode == '2' else term_full
    else:
        year = info_tag.getYear()
        if year:
            search_term = '%s %d' % (title, year)
        else:
            search_term = title

    if search_term:
        params = ""
        # Adaugam ID-urile in URL
        if imdb_id:
            params += '&imdb_id=%s' % quote(str(imdb_id))
        if tmdb_id:
            params += '&tmdb_id=%s' % quote(str(tmdb_id))
        # Adaugam DBID local daca exista
        if dbid and int(dbid) > 0:
            params += '&kodi_dbtype=%s&kodi_dbid=%s' % (dbtype, dbid)
        
        xbmc.log('[MRSP-CONTEXT] Term: %s | IMDb: %s | TMDb: %s' % (search_term, imdb_id, tmdb_id), level=xbmc.LOGINFO)
        
        if search_mode == '0':
            final_url = '%s?action=searchSites&modalitate=edit&query=%s%s' % (base_url, quote(search_term), params)
        else:
            final_url = '%s?action=searchSites&searchSites=cuvant&cuvant=%s%s' % (base_url, quote(search_term), params)
            
        xbmc.executebuiltin('Container.Update(%s)' % final_url)
    else:
        xbmc.executebuiltin('Notification(MRSP, Nu s-au putut extrage detalii, 3000)')