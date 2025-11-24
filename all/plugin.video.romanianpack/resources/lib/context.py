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
    
    # Preluam setarea: 0=Edit, 1=Direct S+E, 2=Direct S
    search_mode = addon.getSetting('context_trakt_search_mode')
    
    base_url = 'plugin://%s' % addon_id
    list_item = sys.listitem
    info_tag = list_item.getVideoInfoTag()
    
    dbtype = info_tag.getMediaType()
    dbid = info_tag.getDbId()
    
    if not dbid or int(dbid) < 1:
        xbmc.log('[MRSP-CONTEXT] Error: No valid DBID.', level=xbmc.LOGERROR)
        sys.exit()

    search_term = ""
    
    if dbtype == 'episode':
        show_title = info_tag.getTVShowTitle()
        season = info_tag.getSeason()
        episode = info_tag.getEpisode()
        
        # Construim termenul de baza
        term_full = '%s S%02dE%02d' % (show_title, season, episode)
        term_season = '%s S%02d' % (show_title, season)
        
        if search_mode == '2': # Direct2 (Doar sezon)
            search_term = term_season
        else: # Edit Box (0) sau Direct1 (1) -> Preferam S+E
            search_term = term_full
            
    elif dbtype == 'movie':
        title = info_tag.getTitle()
        year = info_tag.getYear()
        if year:
            search_term = '%s %d' % (title, year)
        else:
            search_term = title

    if search_term:
        # Construim URL-ul in functie de mod
        # Mode 0 = Edit Box -> folosim param 'modalitate=edit' & 'query'
        # Mode 1/2 = Direct -> folosim param 'searchSites=cuvant' & 'cuvant'
        
        params = '&kodi_dbtype=%s&kodi_dbid=%s' % (dbtype, dbid)
        
        if search_mode == '0':
            final_url = '%s?action=searchSites&modalitate=edit&query=%s%s' % (base_url, quote(search_term), params)
        else:
            final_url = '%s?action=searchSites&searchSites=cuvant&cuvant=%s%s' % (base_url, quote(search_term), params)
            
        xbmc.executebuiltin('Container.Update(%s)' % final_url)