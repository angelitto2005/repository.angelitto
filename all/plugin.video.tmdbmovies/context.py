import sys
import xbmc
import xbmcgui
from urllib.parse import quote_plus

def log(msg):
    xbmc.log(f"[tmdbmovies-context] {msg}", xbmc.LOGINFO)

def get_valid_id(labels, validation_type='digit'):
    for label in labels:
        val = xbmc.getInfoLabel(label)
        if not val or val == label: continue
        val = str(val).strip()
        if validation_type == 'digit':
            if val.isdigit() and val != '0': return val
        elif validation_type == 'imdb':
            if val.startswith('tt'): return val
    return ''

def main():
    # 1. IDs
    tmdb_labels = ['ListItem.Property(tmdb_id)', 'ListItem.Property(tmdb)', 'ListItem.Property(id)', 'ListItem.TMDBId', 'VideoPlayer.TMDBId']
    tmdb_id = get_valid_id(tmdb_labels, 'digit')

    imdb_labels = ['ListItem.IMDBNumber', 'ListItem.Property(imdb_id)', 'ListItem.Property(imdb)', 'VideoPlayer.IMDBNumber']
    imdb_id = get_valid_id(imdb_labels, 'imdb')

    tvdb_labels = ['ListItem.Property(tvdb_id)', 'ListItem.Property(tvdb)']
    tvdb_id = get_valid_id(tvdb_labels, 'digit')

    # 2. Determină Tipul (Prioritate DBTYPE)
    dbtype = xbmc.getInfoLabel('ListItem.DBTYPE') # 'movie', 'tvshow', 'season', 'episode'
    mediatype = xbmc.getInfoLabel('ListItem.Property(mediatype)')
    
    # Valori brute
    raw_season = xbmc.getInfoLabel('ListItem.Season') or xbmc.getInfoLabel('ListItem.Property(season)')
    raw_episode = xbmc.getInfoLabel('ListItem.Episode') or xbmc.getInfoLabel('ListItem.Property(episode)')
    
    # Logică de corecție a tipului
    final_type = 'movie' # Default
    final_season = raw_season
    final_episode = raw_episode

    # A. Verificare DBTYPE (Cel mai sigur pentru Library)
    if dbtype == 'season':
        final_type = 'season'
        final_episode = '' # Ignorăm episodul dacă suntem pe folder de sezon!
    elif dbtype == 'episode':
        final_type = 'episode'
    elif dbtype == 'tvshow':
        final_type = 'tv'
    # B. Verificare Mediatype (Pentru Addon-uri care nu pun DBTYPE)
    elif mediatype == 'season':
        final_type = 'season'
        final_episode = ''
    elif mediatype == 'episode':
        final_type = 'episode'
    # C. Fallback (Deducere din numere)
    elif raw_season and raw_episode:
        final_type = 'episode'
    elif raw_season:
        final_type = 'season'
    elif dbtype == 'movie' or mediatype == 'movie':
        final_type = 'movie'

    # 3. Titles & Specifics
    title = xbmc.getInfoLabel('ListItem.Title') or xbmc.getInfoLabel('ListItem.Label') or xbmc.getInfoLabel('ListItem.OriginalTitle')
    tv_show_title = xbmc.getInfoLabel('ListItem.TVShowTitle') or xbmc.getInfoLabel('ListItem.Property(tvshowtitle)')
    year = xbmc.getInfoLabel('ListItem.Year') or xbmc.getInfoLabel('ListItem.Property(year)')

    # LOGGING
    log(f"Item: '{title}' | DBType: {dbtype} | FinalType: {final_type} | S{final_season}E{final_episode}")

    if not (tmdb_id or imdb_id or tvdb_id or title):
        xbmcgui.Dialog().notification("TMDb Info", "Lipsă informații item", xbmcgui.NOTIFICATION_WARNING)
        return

    # Construim comanda
    path = "plugin://plugin.video.tmdbmovies/"
    params = f"?mode=global_info&type={final_type}"
    
    if tmdb_id: params += f"&tmdb_id={quote_plus(tmdb_id)}"
    if imdb_id: params += f"&imdb_id={quote_plus(imdb_id)}"
    if tvdb_id: params += f"&tvdb_id={quote_plus(tvdb_id)}"
    
    # Dacă e serial/sezon/episod, căutăm după numele serialului, nu după titlul episodului/sezonului
    search_title = tv_show_title if tv_show_title else title
    params += f"&title={quote_plus(search_title)}"
    
    if year: params += f"&year={quote_plus(year)}"
    if final_season: params += f"&season={quote_plus(final_season)}"
    if final_episode: params += f"&episode={quote_plus(final_episode)}"

    xbmc.executebuiltin(f"RunPlugin({path}{params})")

if __name__ == '__main__':
    main()