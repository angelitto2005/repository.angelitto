import xbmc
import xbmcgui
import xbmcaddon
import xbmcvfs
import os
import sys
import threading

from resources.lib.config import ADDON
TRAILER_PLAYER = 'plugin://tmdbm.trailers'
YOUTUBE_PLUGIN = 'plugin://plugin.video.youtube'

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
        return 'yt-dlp' if val == '0' else 'youtube_plugin'
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
        "[COLOR FFCCCCFF]No trailer addon installed[/COLOR] - [COLOR FFCCCCFF]install[/COLOR] [B][COLOR FF00CED1]TMDbM[/COLOR] [COLOR FFF70D1A]Trailers[/COLOR][/B] [COLOR FFCCCCFF]or[/COLOR] [B][COLOR FFCCCCFF]You[COLOR FFF70D1A]Tube[/COLOR] Plugin[/B]",
        _icon(), 5000
    )

def get_trailer_url(video_id, tmdb_id=None, dbtype=None, title=None, year=None, season=None):
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
    if parts:
        extra = '&' + urlencode(parts)

    base = '{TRAILER_PLAYER}/play/?video_id={vid}'.format(
        TRAILER_PLAYER=TRAILER_PLAYER, vid=video_id)

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

def play_trailer(video_id, tmdb_id=None, dbtype=None, title=None, year=None, season=None):
    url = get_trailer_url(video_id, tmdb_id=tmdb_id, dbtype=dbtype,
                          title=title, year=year, season=season)
    if url:
        xbmc.executebuiltin(f'RunPlugin({url})')

def play_trailer_blocking(video_id, tmdb_id=None, dbtype=None, title=None, year=None, season=None):
    """Play trailer and block until playback finishes."""
    url = get_trailer_url(video_id, tmdb_id=tmdb_id, dbtype=dbtype,
                          title=title, year=year, season=season)
    if not url:
        return
    xbmc.Player().play(url)
    monitor = xbmc.Monitor()
    for _ in range(30):
        if xbmc.Player().isPlaying(): break
        if monitor.abortRequested(): return
        monitor.waitForAbort(0.5)
    while xbmc.Player().isPlaying() and not monitor.abortRequested():
        monitor.waitForAbort(1)
