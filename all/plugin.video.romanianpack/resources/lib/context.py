# --- COD NOU (ÎNLOCUIRE COMPLETĂ) ---
import sys
import xbmc
import xbmcaddon

try:
    # Python 3
    import urllib.parse as urllib
except ImportError:
    # Python 2
    import urllib

def quote(text):
    """ Helper function to URL encode text, compatible with Python 2 and 3 """
    if sys.version_info.major < 3 and isinstance(text, unicode):
        text = text.encode('utf-8')
    
    return urllib.quote_plus(str(text))

if __name__ == '__main__':
    addon_id = 'plugin.video.romanianpack'
    base_url = 'plugin://%s' % addon_id
    
    list_item = sys.listitem
    info_tag = list_item.getVideoInfoTag()
    
    # Preluam tipul (episode/movie) si ID-ul intern din Kodi
    dbtype = info_tag.getMediaType()
    dbid = info_tag.getDbId()
    
    # Ne asiguram ca avem un ID valid inainte de a continua
    if not dbid or int(dbid) < 1:
        xbmc.log('[MRSP-CONTEXT] Error: Could not get a valid DBID from ListItem.', level=xbmc.LOGERROR)
        sys.exit()
        
    search_term = ""
    
    if dbtype == 'episode':
        show_title = info_tag.getTVShowTitle()
        season = info_tag.getSeason()
        episode = info_tag.getEpisode()
        # Cautam dupa titlu si sezon pentru a prinde si "season packs"
        search_term = '%s S%02d' % (show_title, season)
    elif dbtype == 'movie':
        search_term = info_tag.getTitle()
        year = info_tag.getYear()
        if year:
            search_term += ' %d' % year

    if search_term:
        # Construim URL-ul final, adaugand dbtype si dbid ca parametri
        # Acesti parametri vor fi "pasati" prin tot addon-ul pana la player
        final_url = '%s?action=searchSites&searchSites=cuvant&cuvant=%s&kodi_dbtype=%s&kodi_dbid=%s' % (
            base_url, 
            quote(search_term), 
            dbtype, 
            dbid
        )
        xbmc.executebuiltin('Container.Update(%s)' % final_url)