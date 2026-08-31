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

def search_youtube_api(title, year=None):
    """Cauta pe YouTube prin Google API v3 (rotatie de chei) si alege primul
    cel mai bun rezultat: prefera un videoclip cu 'trailer'/'teaser' in titlu."""
    try:
        from resources.lib.context.extended_info_mod import get_youtube_api_data
    except Exception:
        return None
    query = '{} {} trailer'.format(title, year) if year else '{} trailer'.format(title)
    try:
        items = get_youtube_api_data(query)
    except Exception:
        return None
    if not items:
        return None
    best = None
    for item in items:
        video_id = (item.get('id') or {}).get('videoId')
        if not video_id:
            continue
        raw = (item.get('snippet') or {}).get('title', '') or ''
        lower = raw.lower()
        if 'trailer' in lower or 'teaser' in lower:
            return video_id
        if best is None:
            best = video_id
    return best

def search_youtube_trailer(title, year=None):
    """Fallback: cauta pe YouTube cu Google API v3, apoi cu yt-dlp."""
    video_id = search_youtube_api(title, year)
    if video_id:
        return video_id
    try:
        trailers_addon = str(Path(xbmcaddon.Addon('tmdbm.trailers').getAddonInfo('path')) / 'resources' / 'lib')
        if trailers_addon not in sys.path:
            sys.path.insert(0, trailers_addon)
        import yt_dlp
        query = f'{title} {year} trailer' if year else f'{title} trailer'
        ydl = yt_dlp.YoutubeDL({'quiet': True, 'extract_flat': True})
        info = ydl.extract_info(f'ytsearch1:{query}', download=False)
        entries = info.get('entries')
        if entries:
            return entries[0]['id']
    except:
        pass
    return None

def get_movie_original_language(tmdb_id, media_type):
    url = f"{BASE_URL}/{media_type}/{tmdb_id}?api_key={API_KEY}"
    data = get_json(url)
    return data.get('original_language') or 'en'

def _pick_trailer_key(videos):
    """Alegeti primul trailer oficial/teaser dintr-o lista de videoclipuri
    TMDb (site YouTube). Returneaza cheia YouTube sau None."""
    priority_types = ['Trailer', 'Teaser']
    for vid_type in priority_types:
        for v in videos:
            if v.get('site') == 'YouTube' and v.get('type') == vid_type:
                return v.get('key')
    for v in videos:
        if v.get('site') == 'YouTube':
            return v.get('key')
    return None

def find_trailer_video(tmdb_id, media_type, season=None):
    """Gaseste trailerul din videoclipurile TMDb. Pentru 'tv' cu season,
    cauta intai trailerele SEZONULUI (endpoint de sezon), apoi fallback pe
    trailerele SERIALULUI. Altfel cauta doar trailerele tipului dat."""
    priority_types = ['Trailer', 'Teaser']

    if media_type == 'tv' and season:
        url = f"{BASE_URL}/tv/{tmdb_id}/season/{season}/videos?api_key={API_KEY}&language=en-US"
        data = get_json(url)
        key = _pick_trailer_key(data.get('results', []))
        if key:
            return key

    original_lang = get_movie_original_language(tmdb_id, media_type)
    langs = [f'{original_lang}', 'en', 'null']
    seen = set()
    for lang in langs:
        if lang in seen:
            continue
        seen.add(lang)
        url = f"{BASE_URL}/{media_type}/{tmdb_id}/videos?api_key={API_KEY}&language=en-US&include_video_language={lang}"
        data = get_json(url)
        videos = data.get('results', [])
        if not videos:
            continue
        key = _pick_trailer_key(videos)
        if key:
            return key
    return None

def search_trailer_by_title(title, year=None, media_type='movie', season=None):
    url = '{}/search/{}?api_key={}&query={}&year={}'.format(
        BASE_URL, media_type, API_KEY, quote_plus(title), year or ''
    )
    data = get_json(url)
    results = data.get('results', [])
    if results:
        found_id = results[0].get('id')
        if found_id:
            log('Found {} via title search: id={}'.format(media_type, found_id))
            return find_trailer_video(str(found_id), media_type, season=season)
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
    season_raw = xbmc.getInfoLabel('ListItem.Season')
    if not season_raw or season_raw == '0':
        season_raw = xbmc.getInfoLabel('ListItem.Property(season)')

    log('tmdb_id={} dbtype={} mediatype={} season={}'.format(tmdb_id, dbtype, mediatype, season_raw))

    if dbtype in ('movie', 'tvshow', 'episode', 'season'):
        media_type = 'movie' if dbtype == 'movie' else 'tv'
    elif mediatype in ('movie', 'tv'):
        media_type = mediatype
    else:
        media_type = None

    season = None
    if dbtype == 'season' and season_raw and season_raw.isdigit():
        season = int(season_raw)

    if dbtype in ('episode', 'season'):
        title = get_first_valid(['ListItem.TVShowTitle', 'ListItem.Property(tvshow.title)'])
    else:
        title = get_first_valid(['ListItem.Title', 'ListItem.Label'])
    year_raw = get_first_valid(['ListItem.Year', 'ListItem.Property(year)'])
    year = year_raw if year_raw and year_raw.isdigit() else None
    genre = get_first_valid(['ListItem.Genre'])

    log('title={} year={} genre={} media_type={} season={}'.format(title, year, genre, media_type, season))

    video_id = None
    if tmdb_id and media_type:
        video_id = find_trailer_video(tmdb_id, media_type, season=season)

    if not video_id and title and media_type:
        log('Fallback: searching by title')
        video_id = search_trailer_by_title(title, year, media_type, season=season)

    if not video_id and title:
        log('Fallback: searching YouTube directly')
        video_id = search_youtube_trailer(title, year)

    log('video_id={}'.format(video_id))

    if video_id:
        from resources.lib.trailer_player import get_trailer_url, has_tmdbm_trailers, has_youtube_plugin
        url = get_trailer_url(video_id, tmdb_id=tmdb_id, dbtype=dbtype,
                              title=title, year=year, season=season)
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
