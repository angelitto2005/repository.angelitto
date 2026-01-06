import sys
import xbmc
import xbmcgui
from urllib.parse import quote_plus

def log(msg):
    xbmc.log(f"[tmdbmovies-context] {msg}", xbmc.LOGINFO)

def get_valid_id(labels, validation_type='digit'):
    """Iterează prin label-uri și returnează prima valoare validă."""
    for label in labels:
        val = xbmc.getInfoLabel(label)
        
        # Curățare de bază
        if not val or val == label: 
            continue
            
        val = str(val).strip()
        
        # Validare Numerică (pentru TMDb/TVDb)
        if validation_type == 'digit':
            if val.isdigit() and val != '0':
                return val
                
        # Validare IMDb (trebuie să înceapă cu tt)
        elif validation_type == 'imdb':
            if val.startswith('tt'):
                return val
                
        # Validare Generic (orice string ne-gol)
        elif validation_type == 'any':
            if val:
                return val
                
    return ''

def main():
    label = xbmc.getInfoLabel('ListItem.Label')
    
    # 1. Extragem TMDb ID (Doar cifre!)
    # Ordinea e importantă: întâi proprietățile addon-urilor, apoi cele standard Kodi
    tmdb_labels = [
        'ListItem.Property(tmdb_id)',
        'ListItem.Property(tmdb)',
        'ListItem.Property(id)',
        'ListItem.TMDBId',
        'VideoPlayer.TMDBId'
    ]
    tmdb_id = get_valid_id(tmdb_labels, 'digit')

    # 2. Extragem IMDb ID (Doar format tt...)
    imdb_labels = [
        'ListItem.IMDBNumber',
        'ListItem.Property(imdb_id)',
        'ListItem.Property(imdb)',
        'VideoPlayer.IMDBNumber'
    ]
    imdb_id = get_valid_id(imdb_labels, 'imdb')

    # 3. Extragem TVDb ID
    tvdb_labels = [
        'ListItem.Property(tvdb_id)',
        'ListItem.Property(tvdb)'
    ]
    tvdb_id = get_valid_id(tvdb_labels, 'digit')

    # 4. Tip Conținut & Titlu
    dbtype = xbmc.getInfoLabel('ListItem.DBTYPE')
    mediatype = xbmc.getInfoLabel('ListItem.Property(mediatype)')
    
    final_type = 'movie'
    if dbtype in ['tvshow', 'season', 'episode'] or mediatype in ['tvshow', 'season', 'episode']:
        final_type = 'tv'
    
    title = xbmc.getInfoLabel('ListItem.Title') or xbmc.getInfoLabel('ListItem.Label') or xbmc.getInfoLabel('ListItem.OriginalTitle')
    year = xbmc.getInfoLabel('ListItem.Year') or xbmc.getInfoLabel('ListItem.Property(year)')

    # LOGGING
    log(f"Item: {label} | TMDb: '{tmdb_id}' | IMDb: '{imdb_id}' | TVDb: '{tvdb_id}'")

    if not (tmdb_id or imdb_id or tvdb_id or title):
        xbmcgui.Dialog().notification("TMDb Info", "Lipsă informații item", xbmcgui.NOTIFICATION_WARNING)
        return

    # Construim comanda
    path = "plugin://plugin.video.tmdbmovies/"
    params = f"?mode=global_info&type={final_type}"
    
    if tmdb_id: params += f"&tmdb_id={quote_plus(tmdb_id)}"
    if imdb_id: params += f"&imdb_id={quote_plus(imdb_id)}"
    if tvdb_id: params += f"&tvdb_id={quote_plus(tvdb_id)}"
    if title:   params += f"&title={quote_plus(title)}"
    if year:    params += f"&year={quote_plus(year)}"

    xbmc.executebuiltin(f"RunPlugin({path}{params})")

if __name__ == '__main__':
    main()