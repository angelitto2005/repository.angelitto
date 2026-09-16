import sys
from urllib.parse import parse_qs, urlparse

import xbmc
import xbmcgui
import xbmcplugin

ADDON_ID = 'tmdbm.trailers'

def _log(msg, level=xbmc.LOGDEBUG):
    xbmc.log('[{}] {}'.format(ADDON_ID, msg), level)

def play(video_id, title=None, genre=None, year=None, tmdb_id=None, dbtype=None,
         season=None, episode=None, plot=None, studio=None, tagline=None, lang=None):
    handle = int(sys.argv[1])
    try:
        from player import play_youtube
        li = play_youtube(video_id, title=title, genre=genre, year=year,
                          tmdb_id=tmdb_id, dbtype=dbtype, season=season,
                          episode_num=episode, plot=plot, studio=studio,
                          tagline=tagline, lang=lang)
        xbmcplugin.setResolvedUrl(handle, True, li)
    except Exception as e:
        _log('Error: {}'.format(str(e)), xbmc.LOGERROR)
        import traceback
        _log(traceback.format_exc(), xbmc.LOGERROR)
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())

def main():
    try:
        plugin_url = sys.argv[0]
        query = sys.argv[2]
    except IndexError:
        return

    parsed = urlparse(plugin_url)
    route = parsed.path.rstrip('/')
    params = parse_qs(query.lstrip('?'))
    video_id = params.get('video_id', [None])[0]
    title = params.get('title', [None])[0]
    genre = params.get('genre', [None])[0]
    year = params.get('year', [None])[0]
    tmdb_id = params.get('tmdb_id', [None])[0]
    dbtype = params.get('dbtype', [None])[0]
    season_raw = params.get('season', [None])[0]
    season = None
    if season_raw and str(season_raw).isdigit():
        season = int(season_raw)
    episode_raw = params.get('episode', [None])[0]
    episode = None
    if episode_raw and str(episode_raw).isdigit():
        episode = int(episode_raw)
    plot = params.get('plot', [None])[0]
    studio = params.get('studio', [None])[0]
    tagline = params.get('tagline', [None])[0]
    lang = params.get('lang', [None])[0]

    if route == '/play' and video_id:
        play(video_id, title=title, genre=genre, year=year,
             tmdb_id=tmdb_id, dbtype=dbtype, season=season,
             episode=episode, plot=plot, studio=studio,
             tagline=tagline, lang=lang)
    else:
        handle = int(sys.argv[1])
        xbmcplugin.setContent(handle, '')
        xbmcplugin.endOfDirectory(handle)

if __name__ == '__main__':
    main()
