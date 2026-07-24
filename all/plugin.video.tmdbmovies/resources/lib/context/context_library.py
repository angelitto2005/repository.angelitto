# Context Menu: Add to Library
from pathlib import Path
import sys

addon_root = str(Path(__file__).parent.parent.parent.parent)
if addon_root not in sys.path:
    sys.path.insert(0, addon_root)

import xbmc
import xbmcgui
from resources.lib.context.context import get_source_info, get_first_valid, get_int_value, resolve_tmdb_id, log

def main():
    source, source_path = get_source_info()
    tmdb_id = get_first_valid([
        'ListItem.Property(show_tmdb_id)', 'ListItem.Property(tvshow.tmdb_id)',
        'ListItem.Property(tmdb_id)', 'ListItem.Property(tmdb)',
        'ListItem.Property(TmdbId)', 'ListItem.TMDBId',
        'VideoPlayer.TMDBId', 'ListItem.UniqueID(tmdb)'
    ])
    folder_path = xbmc.getInfoLabel('Container.FolderPath')
    if 'tmdb_id=' in folder_path:
        import re
        match = re.search(r'[?&]tmdb_id=(\d+)', folder_path)
        if match:
            tmdb_id = match.group(1)
    imdb_id = get_first_valid([
        'ListItem.IMDBNumber', 'ListItem.Property(imdb_id)',
        'ListItem.UniqueID(imdb)', 'VideoPlayer.IMDBNumber'
    ])
    tvdb_id = get_first_valid([
        'ListItem.Property(tvdb_id)', 'ListItem.UniqueID(tvdb)'
    ])
    dbtype = xbmc.getInfoLabel('ListItem.DBTYPE').lower().strip()
    mediatype = xbmc.getInfoLabel('ListItem.Property(mediatype)').lower().strip()
    final_type = 'movie'
    season_num = None
    episode_num = None
    if dbtype in ('tvshow', 'season', 'episode') or mediatype in ('tvshow', 'season', 'episode', 'tv'):
        final_type = 'tv'
        season_num = get_int_value(get_first_valid(['ListItem.Season', 'ListItem.Property(season)', 'VideoPlayer.Season']))
        episode_num = get_int_value(get_first_valid(['ListItem.Episode', 'ListItem.Property(episode)', 'VideoPlayer.Episode']))
        if episode_num and episode_num > 50:
            episode_num = None
    title = get_first_valid(['ListItem.Title', 'ListItem.Label', 'ListItem.OriginalTitle'])
    tv_show_title = get_first_valid([
        'ListItem.TVShowTitle', 'ListItem.Property(tvshowtitle)',
        'ListItem.Property(TVShowTitle)', 'VideoPlayer.TVShowTitle'
    ])
    search_title = tv_show_title if (final_type == 'tv' and tv_show_title) else title
    year = get_first_valid(['ListItem.Year', 'ListItem.Property(year)'])
    if not tmdb_id or not str(tmdb_id).isdigit():
        if imdb_id or tvdb_id:
            real_tmdb_id, real_type = resolve_tmdb_id(imdb_id, tvdb_id, search_title, year, 
                get_first_valid(['ListItem.Premiered', 'ListItem.Date', 'ListItem.Aired']), final_type)
            if real_tmdb_id:
                tmdb_id = str(real_tmdb_id)
                if real_type == 'tv':
                    final_type = 'tv'
        if not tmdb_id:
            xbmcgui.Dialog().notification('TMDb Library', 'Cannot find TMDb ID', xbmcgui.NOTIFICATION_WARNING)
            return
    from resources.lib.library import add_to_library
    add_to_library(tmdb_id=tmdb_id, media_type=final_type, title=search_title,
                   year=year, season=season_num, episode=episode_num)

if __name__ == '__main__':
    main()