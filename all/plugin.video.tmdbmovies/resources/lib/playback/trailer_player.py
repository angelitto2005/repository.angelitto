import xbmc
import xbmcgui
import xbmcaddon
import xbmcvfs
import os
import sys
import threading

from resources.lib.core.config import ADDON
TRAILER_PLAYER = 'plugin://tmdbm.trailers'
YOUTUBE_PLUGIN = 'plugin://plugin.video.youtube'
TV_TYPES = ('tv', 'tvshow', 'show', 'series', 'season', 'episode')

def has_tmdbm_trailers():
    try:
        xbmcaddon.Addon('tmdbm.trailers')
        return True
    except Exception:
        return False

def has_youtube_plugin():
    try:
        xbmcaddon.Addon('plugin.video.youtube')
        return True
    except Exception:
        return False

def get_trailer_mode():
    try:
        val = ADDON.getSetting('trailer_player')
        if val == '1': return 'youtube_plugin'
        if val == '2': return 'imdb'
        return 'yt-dlp'
    except:
        return 'yt-dlp'

def _icon():
    return os.path.join(xbmcvfs.translatePath(ADDON.getAddonInfo('path')), 'icon.png')

def _notify_install_tmdbm():
    xbmcgui.Dialog().notification(
        "[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]",
        "[COLOR FFCCCCFF]Install[/COLOR] [B][COLOR FF00CED1]TMDbM [COLOR FFF70D1A]Trailers[/COLOR][/B] [COLOR FFCCCCFF]from[/COLOR] [B][COLOR FFC45AEC]Angelitto Repository[/COLOR][/B]",
        _icon(), 5000
    )

def _notify_install_youtube():
    xbmcgui.Dialog().notification(
        "[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]",
        "[COLOR FFCCCCFF]Install[/COLOR] [B][COLOR FFCCCCFF]You[COLOR FFF70D1A]Tube[/COLOR] [COLOR FFCCCCFF]Plugin[/COLOR][/B] [COLOR FFCCCCFF]from[/COLOR] [B][COLOR FFC45AEC]Kodi Repository[/COLOR][/B]",
        _icon(), 5000
    )

def _notify_no_trailer_addon():
    xbmcgui.Dialog().notification(
        "[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]",
        "[COLOR FFCCCCFF]No trailer addon installed[/COLOR] - [COLOR FFCCCCFF]install[/COLOR] [B][COLOR FF00CED1]TMDbM[/COLOR] [COLOR FFF70D1A]Trailers[/COLOR][/B] [COLOR FFCCCCFF]or[/COLOR] [B][COLOR FFF70D1A]You[/COLOR] [COLOR FFCCCCFF]Plugin[/B]",
        _icon(), 5000
    )

def media_type_for(dbtype):
    return 'tv' if str(dbtype or '').lower() in TV_TYPES else 'movie'

def imdb_trailer_url(tmdb_id=None, dbtype=None, imdb_id=''):
    """Direct MP4 of the IMDb trailer, '' when the title has none."""
    if not imdb_id:
        try:
            imdb_id = xbmc.getInfoLabel('ListItem.UniqueID(imdb)') or ''
        except Exception:
            imdb_id = ''
    try:
        from resources.lib.playback.imdb_trailer import url_for
        url, definition = url_for(tmdb_id, media_type_for(dbtype), imdb_id=imdb_id)
    except Exception as exc:
        xbmc.log(f"[TRAILER] IMDb trailer error: {exc}", xbmc.LOGWARNING)
        return ''
    if url:
        xbmc.log(f"[TRAILER] IMDb trailer {imdb_id} ({definition or 'MP4'})", xbmc.LOGINFO)
    return url

def get_trailer_url(video_id, tmdb_id=None, dbtype=None, title=None, year=None, season=None, plot=None, studio=None, tagline=None, genre=None, imdb_id=''):
    from urllib.parse import urlencode
    mode = get_trailer_mode()
    extra = ''
    parts = []
    if tmdb_id:
        parts.append(('tmdb_id', str(tmdb_id)))
    if dbtype:
        parts.append(('dbtype', str(dbtype)))
    if title:
        parts.append(('title', str(title)))
    if year:
        parts.append(('year', str(year)))
    if season:
        parts.append(('season', str(season)))
    if plot:
        _pp = str(plot)[:2000]
        if '[' in _pp[-40:] and ']' not in _pp.rsplit('[', 1)[-1]:
            _pp = _pp.rsplit('[', 1)[0]
        parts.append(('plot', _pp))
    if studio:
        parts.append(('studio', str(studio)))
    if tagline:
        parts.append(('tagline', str(tagline)))
    if genre:
        parts.append(('genre', str(genre)))
    # Limba pentru meta-urile luate de tmdbm.trailers (plot sezon/episod)
    try:
        from resources.lib.core.config import get_plot_language_code, LANG_TO_TMDB
        parts.append(('lang', LANG_TO_TMDB.get(get_plot_language_code(), 'en-US')))
    except:
        pass
    if parts:
        extra = '&' + urlencode(parts)

    base = '{TRAILER_PLAYER}/play/?video_id={vid}'.format(
        TRAILER_PLAYER=TRAILER_PLAYER, vid=video_id)

    if mode == 'imdb':
        url = imdb_trailer_url(tmdb_id=tmdb_id, dbtype=dbtype, imdb_id=imdb_id)
        if url:
            return url
        if not video_id:
            if has_tmdbm_trailers() or has_youtube_plugin():
                return None
            _notify_no_trailer_addon()
            return None
        if has_tmdbm_trailers():
            return base + extra
        if has_youtube_plugin():
            return f"{YOUTUBE_PLUGIN}/play/?video_id={video_id}"
        _notify_no_trailer_addon()
        return None

    if mode == 'yt-dlp':
        if has_tmdbm_trailers():
            return base + extra
        _notify_install_tmdbm()
        if has_youtube_plugin():
            return f"{YOUTUBE_PLUGIN}/play/?video_id={video_id}"
        _notify_no_trailer_addon()
        return None

    if mode == 'youtube_plugin':
        if has_youtube_plugin():
            return f"{YOUTUBE_PLUGIN}/play/?video_id={video_id}"
        _notify_install_youtube()
        if has_tmdbm_trailers():
            return base + extra
        _notify_no_trailer_addon()
        return None

    return None

def youtube_video_url(video_id, tmdb_id=None, dbtype=None, title=None, year=None, season=None, plot=None, studio=None, tagline=None, genre=None):
    """URL for a YouTube clip the user picked explicitly (never the IMDb one)."""
    if not video_id:
        return ''
    if get_trailer_mode() == 'youtube_plugin':
        return f"{YOUTUBE_PLUGIN}/play/?video_id={video_id}"
    if not has_tmdbm_trailers() and has_youtube_plugin():
        return f"{YOUTUBE_PLUGIN}/play/?video_id={video_id}"
    from urllib.parse import urlencode
    parts = []
    if tmdb_id:
        parts.append(('tmdb_id', str(tmdb_id)))
    if dbtype:
        parts.append(('dbtype', str(dbtype)))
    if title:
        parts.append(('title', str(title)))
    if year:
        parts.append(('year', str(year)))
    if season:
        parts.append(('season', str(season)))
    if plot:
        _pp = str(plot)[:2000]
        if '[' in _pp[-40:] and ']' not in _pp.rsplit('[', 1)[-1]:
            _pp = _pp.rsplit('[', 1)[0]
        parts.append(('plot', _pp))
    if studio:
        parts.append(('studio', str(studio)))
    if tagline:
        parts.append(('tagline', str(tagline)))
    if genre:
        parts.append(('genre', str(genre)))
    try:
        from resources.lib.core.config import get_plot_language_code, LANG_TO_TMDB
        parts.append(('lang', LANG_TO_TMDB.get(get_plot_language_code(), 'en-US')))
    except:
        pass
    extra = ('&' + urlencode(parts)) if parts else ''
    return f'{TRAILER_PLAYER}/play/?video_id={video_id}{extra}'

def _direct_listitem(url, title=None, plot=None, genre=None, studio=None, year=None):
    li = xbmcgui.ListItem(path=url)
    try:
        tag = li.getVideoInfoTag()
        if title:
            tag.setTitle(title)
            tag.setOriginalTitle(title)
        if plot:
            tag.setPlot(str(plot))
        if studio:
            tag.setStudios([studio])
        if year and str(year).isdigit():
            tag.setYear(int(year))
        if genre:
            tag.setGenres([g.strip() for g in str(genre).replace('/', ',').split(',') if g.strip()])
    except Exception:
        pass
    return li

def play_trailer(video_id, tmdb_id=None, dbtype=None, title=None, year=None, season=None, plot=None, studio=None, tagline=None, genre=None, imdb_id=''):
    url = get_trailer_url(video_id, tmdb_id=tmdb_id, dbtype=dbtype,
                          title=title, year=year, season=season,
                          plot=plot, studio=studio, tagline=tagline, genre=genre,
                          imdb_id=imdb_id)
    if not url:
        return
    if url.startswith('plugin://'):
        xbmc.executebuiltin(f'RunPlugin({url})')
        return
    xbmc.Player().play(url, _direct_listitem(url, title=title, plot=plot,
                                             genre=genre, studio=studio, year=year))

def play_trailer_blocking(video_id, tmdb_id=None, dbtype=None, title=None, year=None, season=None, plot=None, studio=None, tagline=None, genre=None, imdb_id=''):
    """Play trailer and block until playback finishes."""
    url = get_trailer_url(video_id, tmdb_id=tmdb_id, dbtype=dbtype,
                          title=title, year=year, season=season,
                          plot=plot, studio=studio, tagline=tagline, genre=genre,
                          imdb_id=imdb_id)
    if not url:
        return
    if url.startswith('plugin://'):
        xbmc.Player().play(url)
    else:
        xbmc.Player().play(url, _direct_listitem(url, title=title, plot=plot,
                                                  genre=genre, studio=studio, year=year))
    monitor = xbmc.Monitor()
    for _ in range(30):
        if xbmc.Player().isPlaying(): break
        if monitor.abortRequested(): return
        monitor.waitForAbort(0.5)
    while xbmc.Player().isPlaying() and not monitor.abortRequested():
        monitor.waitForAbort(1)
