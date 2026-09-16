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
    """Cauta trailer pe YouTube: intai Innertube gratis, fallback Google API v3."""
    try:
        from resources.lib.context.extended_info_mod import get_youtube_search_results
    except Exception:
        return None
    query = '{} {} trailer'.format(title, year) if year else '{} trailer'.format(title)
    try:
        items = get_youtube_search_results(query)
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

def _get_details_for_osd(dbtype, tmdb_id, season=None, episode=None):
    """Overview + tagline|gen pentru OSD-ul trailerului, in limba setata pentru
    plot (fallback EN). Fara asta, tmdbm.trailers isi ia singur plotul: pentru
    episoade harta lui de dbtype nu cunoaste 'episode' si interogheaza
    /movie/{tmdb_id} cu ID-ul SERIALULUI -> overview-ul altui film!
    Tagline-ul pleaca FARA [B] (randul TagLine din OSD afiseaza literal
    [/B]-ul final) si cu genurile incluse in string (parametrul genre=
    alimenteaza doar linia de sub titlul clipului, nu randul din OSD)."""
    try:
        from resources.lib.config import get_plot_language_code, LANG_TO_TMDB
        lang = LANG_TO_TMDB.get(get_plot_language_code(), 'en-US')
    except Exception:
        lang = 'en-US'

    def _get(path):
        d = get_json(f"{BASE_URL}/{path}?api_key={API_KEY}&language={lang}") or {}
        if not d or d.get('success') is False:
            d = get_json(f"{BASE_URL}/{path}?api_key={API_KEY}&language=en-US") or {}
        return d

    try:
        if dbtype == 'movie':
            item, show = _get(f'movie/{tmdb_id}'), {}
        elif dbtype == 'season' and season is not None:
            show = _get(f'tv/{tmdb_id}')
            item = _get(f'tv/{tmdb_id}/season/{season}')
        elif dbtype == 'episode' and season is not None and episode:
            show = _get(f'tv/{tmdb_id}')
            item = _get(f'tv/{tmdb_id}/season/{season}/episode/{episode}')
        else:
            item, show = _get(f'tv/{tmdb_id}'), {}

        overview = (item.get('overview') or '').strip() or (show.get('overview') or '').strip()
        # Genuri/tagline: la serial vin din 'show', la film sunt pe 'item'
        # (sezoanele/episoadele TMDb nu au aceste campuri deloc).
        _gsrc = show if show else item
        tagline_text = ((show.get('tagline') or item.get('tagline') or '')).strip()
        # TMDb nu traduce motto-ul in multe limbi (de multe ori nici nu il are
        # localizat): fallback la EN ca randul "motto | gen" sa nu dispara.
        if not tagline_text:
            _en_path = 'movie/{}'.format(tmdb_id) if dbtype == 'movie' else 'tv/{}'.format(tmdb_id)
            _en = get_json(f"{BASE_URL}/{_en_path}?api_key={API_KEY}&language=en-US") or {}
            tagline_text = (_en.get('tagline') or '').strip()
        genres_str = ', '.join(g.get('name') for g in (_gsrc.get('genres') or []) if g.get('name'))

        def _head():
            # Acelasi format ca la Extended Info (dovedit corect in OSD).
            if tagline_text and genres_str:
                return f"[B][COLOR yellow]{tagline_text}[/COLOR][/B] | [B][COLOR FF00CED1]{genres_str}[/COLOR][/B]\n"
            if tagline_text:
                return f"[B][COLOR yellow]{tagline_text}[/COLOR][/B]\n"
            if genres_str:
                return f"[B][COLOR FF00CED1]{genres_str}[/COLOR][/B]\n"
            return ''

        if dbtype in ('season', 'episode'):
            # OSD-ul pentru continut episodic nu randeaza fiabil TagLine ->
            # ingropam motto+gen in plot (ca la Extended Info) si nu trimitem
            # tagline separat (ar risca duplicare).
            plot_out = _head() + overview
            log('OSD meta (seas/ep): plot={}c (cu antet motto|gen)'.format(len(plot_out or '')))
            return plot_out or None, None

        tagline_param = None
        if tagline_text and genres_str:
            tagline_param = f"[COLOR yellow]{tagline_text}[/COLOR]   |   [COLOR FF00CED1]{genres_str}[/COLOR]"
        elif tagline_text:
            tagline_param = f"[COLOR yellow]{tagline_text}[/COLOR]"
        elif genres_str:
            tagline_param = f"[COLOR FF00CED1]{genres_str}[/COLOR]"
        log('OSD meta: plot={}c tagline={}'.format(len(overview or ''), bool(tagline_param)))
        return overview or None, tagline_param
    except Exception as e:
        log('OSD meta error: {}'.format(e))
        return None, None


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
    if dbtype in ('season', 'episode') and season_raw and season_raw.isdigit():
        season = int(season_raw)
    episode_num = None
    if dbtype == 'episode':
        _ep_raw = (xbmc.getInfoLabel('ListItem.Episode') or '').strip()
        if _ep_raw.isdigit():
            episode_num = int(_ep_raw)

    if dbtype in ('episode', 'season'):
        title = get_first_valid(['ListItem.TVShowTitle', 'ListItem.Property(tvshow.title)'])
    else:
        title = get_first_valid(['ListItem.Title', 'ListItem.Label'])
    year_raw = get_first_valid(['ListItem.Year', 'ListItem.Property(year)'])
    year = year_raw if year_raw and year_raw.isdigit() else None
    genre = get_first_valid(['ListItem.Genre'])

    log('title={} year={} genre={} media_type={} season={}'.format(title, year, genre, media_type, season))

    # Meta pentru OSD (motto+gen + plot in limba setata), ca la TMDb INFO.
    _osd_dbtype = dbtype if dbtype in ('movie', 'tvshow', 'tv', 'season', 'episode') else media_type
    plot_param, tagline_param = None, None
    if tmdb_id and media_type:
        plot_param, tagline_param = _get_details_for_osd(
            _osd_dbtype, tmdb_id, season=season, episode=episode_num)

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
                              title=title, year=year, season=season,
                              plot=plot_param, tagline=tagline_param)
        if not url:
            return
        if genre:
            url = '{}&{}'.format(url, urlencode({'genre': genre}))
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
