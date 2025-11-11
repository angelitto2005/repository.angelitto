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
    # În Python 3, toate string-urile sunt deja unicode, deci nu mai există tipul 'unicode'
    # În Python 2, trebuie să ne asigurăm că textul este encodat în utf-8 înainte de a-l pasa la quote_plus
    if sys.version_info.major < 3 and isinstance(text, unicode):
        text = text.encode('utf-8')
    
    return urllib.quote_plus(str(text))

if __name__ == '__main__':
    addon_id = 'plugin.video.romanianpack'
    base_url = 'plugin://%s' % addon_id
    
    list_item = sys.listitem
    info_tag = list_item.getVideoInfoTag()
    
    dbtype = info_tag.getMediaType()
    dbid = info_tag.getDbId()
    
    search_term = ""
    
    if dbtype == 'episode':
        show_title = info_tag.getTVShowTitle()
        season = info_tag.getSeason()
        episode = info_tag.getEpisode()
        # Căutăm doar după sezon pentru a găsi season packs
        search_term = '%s S%02d' % (show_title, season)
    elif dbtype == 'movie':
        search_term = info_tag.getTitle()
        year = info_tag.getYear()
        if year:
            search_term += ' %s' % year

    if search_term and dbid and int(dbid) > 0:
        # Construim URL-ul care include direct datele Kodi
        final_url = '%s?action=searchSites&searchSites=cuvant&cuvant=%s&kodi_dbtype=%s&kodi_dbid=%s' % (
            base_url, 
            quote(search_term), 
            dbtype, 
            dbid
        )
        xbmc.executebuiltin('Container.Update(%s)' % final_url)
# --- SFÂRȘIT COD NOU ---