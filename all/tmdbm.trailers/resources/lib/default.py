import os
import sys
from urllib.parse import parse_qs, urlparse

import xbmc
import xbmcgui
import xbmcplugin

_LIB = os.path.dirname(os.path.abspath(__file__))
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

import config
import router

ADDON_ID = config.ADDON_ID


def _log(msg, level=xbmc.LOGDEBUG):
    xbmc.log('[{}] {}'.format(ADDON_ID, msg), level)


def _int_or_none(value):
    if value and str(value).isdigit():
        return int(value)
    return None


def play(video_id, title=None, genre=None, year=None, tmdb_id=None, dbtype=None,
         season=None, episode=None, plot=None, studio=None, tagline=None,
         lang=None):
    handle = int(sys.argv[1])
    params = {'video_id': video_id, 'title': title, 'genre': genre,
              'year': year, 'tmdb_id': tmdb_id, 'dbtype': dbtype,
              'season': season, 'episode': episode, 'plot': plot,
              'studio': studio, 'tagline': tagline, 'lang': lang}
    try:
        import playback
        from music import queue
        queue.cancel()
        if playback.is_external_play(params):
            playback.resolve_play(handle, params, arm=False)
        else:
            playback.resolve_play(handle, params)
    except Exception as e:
        _log('Error: {}'.format(str(e)), xbmc.LOGERROR)
        import traceback
        _log(traceback.format_exc(), xbmc.LOGERROR)
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())


def main():
    plugin_url = sys.argv[0] if sys.argv else 'plugin://{}/'.format(ADDON_ID)
    query = sys.argv[2] if len(sys.argv) > 2 else ''
    handle = 0
    if len(sys.argv) > 1:
        try:
            handle = int(sys.argv[1])
        except ValueError:
            handle = 0

    parsed = urlparse(plugin_url)
    route = parsed.path.rstrip('/')
    params = {k: v[0] for k, v in parse_qs(query.lstrip('?')).items()}
    video_id = params.get('video_id')
    title = params.get('title')
    genre = params.get('genre')
    year = params.get('year')
    tmdb_id = params.get('tmdb_id')
    dbtype = params.get('dbtype')
    season = _int_or_none(params.get('season'))
    episode = _int_or_none(params.get('episode'))
    plot = params.get('plot')
    studio = params.get('studio')
    tagline = params.get('tagline')
    lang = params.get('lang')

    if route == '/play' and video_id:
        play(video_id, title=title, genre=genre, year=year,
             tmdb_id=tmdb_id, dbtype=dbtype, season=season,
             episode=episode, plot=plot, studio=studio,
             tagline=tagline, lang=lang)
        return

    mode = params.pop('mode', None) or 'root'
    _log('route {} handle {} query {!r}'.format(mode, handle, query[:120]),
         xbmc.LOGINFO)
    router.dispatch(handle, mode, params)


if __name__ == '__main__':
    main()