from pathlib import Path
import sys

addon_root = str(Path(__file__).parent.parent.parent.parent)
if addon_root not in sys.path:
    sys.path.insert(0, addon_root)

import xbmc
import xbmcgui
import xbmcaddon
import re
from urllib.parse import quote_plus, urlencode

ADDON = xbmcaddon.Addon('plugin.video.tmdbmovies')
API_KEY = "8ad3c21a92a64da832c559d58cc63ab4"
BASE_URL = "https://api.themoviedb.org/3"

def log(msg):
    xbmc.log(f"[TMDb Play Trailer] {msg}", xbmc.LOGINFO)

def get_first_valid(labels):
    for label in labels:
        val = xbmc.getInfoLabel(label)
        if val and val != label and val.lower() not in ['', 'none', 'null', '-1']:
            return str(val).strip()
    return ""

def get_json(url):
    try:
        import requests
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.json()
    except:
        pass
    return {}

def find_trailer_video(tmdb_id, media_type):
    """Cauta trailer pe TMDb si returneaza video_id-ul YouTube."""
    priority_types = ['Trailer', 'Teaser']
    
    url = f"{BASE_URL}/{media_type}/{tmdb_id}/videos?api_key={API_KEY}&language=en-US&include_video_language=en,null"
    data = get_json(url)
    videos = data.get('results', [])
    
    for vid_type in priority_types:
        for v in videos:
            if v.get('site') == 'YouTube' and v.get('type') == vid_type:
                return v.get('key')
    
    if videos:
        for v in videos:
            if v.get('site') == 'YouTube':
                return v.get('key')
    
    return None

def search_trailer_by_title(title, year=None, media_type='movie'):
    url = '{}/search/{}?api_key={}&query={}&year={}'.format(
        BASE_URL, media_type, API_KEY, quote_plus(title), year or ''
    )
    data = get_json(url)
    results = data.get('results', [])
    if results:
        found_id = results[0].get('id')
        if found_id:
            log('Found {} via title search: id={}'.format(media_type, found_id))
            return find_trailer_video(str(found_id), media_type)
    return None

def main():
    tmdb_id = get_first_valid([
        'ListItem.Property(show_tmdb_id)',
        'ListItem.Property(tvshow.tmdb_id)',
        'ListItem.Property(tmdb_id)',
        'ListItem.Property(tmdb)',
        'ListItem.TMDBId',
        'VideoPlayer.TMDBId',
        'ListItem.UniqueID(tmdb)'
    ])

    folder_path = xbmc.getInfoLabel('Container.FolderPath')
    log('FolderPath: {}'.format(folder_path))
    if 'tmdb_id=' in folder_path:
        match = re.search(r'[?&]tmdb_id=(\d+)', folder_path)
        if match:
            tmdb_id = match.group(1)

    dbtype = xbmc.getInfoLabel('ListItem.DBTYPE').lower().strip()
    mediatype = xbmc.getInfoLabel('ListItem.Property(mediatype)').lower().strip()

    log('tmdb_id={} dbtype={} mediatype={}'.format(tmdb_id, dbtype, mediatype))

    if dbtype in ('movie', 'tvshow'):
        media_type = 'movie' if dbtype == 'movie' else 'tv'
    elif mediatype in ('movie', 'tv'):
        media_type = mediatype
    else:
        media_type = None

    title = get_first_valid(['ListItem.Title', 'ListItem.Label'])
    year_raw = get_first_valid(['ListItem.Year', 'ListItem.Property(year)'])
    year = year_raw if year_raw and year_raw.isdigit() else None
    genre = get_first_valid(['ListItem.Genre'])

    log('title={} year={} genre={} media_type={}'.format(title, year, genre, media_type))

    video_id = None
    if tmdb_id and media_type:
        video_id = find_trailer_video(tmdb_id, media_type)

    if not video_id and title and media_type:
        log('Fallback: searching by title')
        video_id = search_trailer_by_title(title, year, media_type)

    log('video_id={}'.format(video_id))

    if video_id:
        from resources.lib.trailer_player import get_trailer_url, has_tmdbm_trailers, has_youtube_plugin
        url = get_trailer_url(video_id)
        if not url:
            return
        li = xbmcgui.ListItem(path=url)
        if title:
            tag = li.getVideoInfoTag()
            tag.setTitle(title)
            tag.setOriginalTitle(title)
        if genre:
            tag = li.getVideoInfoTag()
            tag.setGenres([g.strip() for g in genre.replace('/', ',').split(',') if g.strip()])
        log('Playing: {}'.format(url))
        xbmc.Player().play(url, li)
    else:
        xbmcgui.Dialog().notification(
            "[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]",
            "[B][COLOR FF6AFB92]No trailer found[/COLOR][/B]",
            xbmcgui.NOTIFICATION_INFO, 3000
        )

if __name__ == '__main__':
    main()
