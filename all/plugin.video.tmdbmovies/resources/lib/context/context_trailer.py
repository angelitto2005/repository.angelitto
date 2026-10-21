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
try:
    from resources.lib.core.config import IMG_BASE, BACKDROP_BASE
except Exception:
    IMG_BASE = "https://image.tmdb.org/t/p/w500"
    BACKDROP_BASE = "https://image.tmdb.org/t/p/w1280"

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

def search_tmdb_id_by_title(title, year=None, media_type='movie'):
    """ID-ul TMDb al unui titlu, din cautarea pe titlu (cu an, daca exista)."""
    if not title:
        return ''
    url = '{}/search/{}?api_key={}&query={}&year={}'.format(
        BASE_URL, media_type, API_KEY, quote_plus(title), year or ''
    )
    data = get_json(url)
    for result in (data.get('results') or []):
        found_id = result.get('id')
        if found_id:
            log('Found {} via title search: id={}'.format(media_type, found_id))
            return str(found_id)
    return ''

def search_trailer_by_title(title, year=None, media_type='movie', season=None, found_id=''):
    if not found_id:
        found_id = search_tmdb_id_by_title(title, year, media_type)
    if found_id:
        return find_trailer_video(found_id, media_type, season=season)
    return None

def _get_details_for_osd(dbtype, tmdb_id, season=None, episode=None):
    """Overview + tagline|gen pentru OSD-ul trailerului, in limba setata pentru
    plot (fallback EN). Fara asta, tmdbm.trailers isi ia singur plotul: pentru
    episoade harta lui de dbtype nu cunoaste 'episode' si interogheaza
    /movie/{imdb_id} cu ID-ul SERIALULUI -> overview-ul altui film!
    Tagline-ul pleaca FARA [B] (randul TagLine din OSD afiseaza literal
    [/B]-ul final) si cu genurile incluse in string (parametrul genre=
    alimenteaza doar linia de sub titlul clipului, nu randul din OSD).
    Intoarce si art-ul (poster/fanart) pentru panoul de info al playerului."""
    try:
        from resources.lib.core.config import get_plot_language_code, LANG_TO_TMDB
        lang = LANG_TO_TMDB.get(get_plot_language_code(), 'en-US')
    except Exception:
        lang = 'en-US'

    def _get(path):
        d = get_json(f"{BASE_URL}/{path}?api_key={API_KEY}&language={lang}") or {}
        if not d or d.get('success') is False:
            d = get_json(f"{BASE_URL}/{path}?api_key={API_KEY}&language=en-US") or {}
        return d

    def _get_en(path):
        return get_json(f"{BASE_URL}/{path}?api_key={API_KEY}&language=en-US") or {}

    try:
        if dbtype == 'movie':
            _item_path, _show_path = f'movie/{tmdb_id}', None
        elif dbtype == 'season' and season is not None:
            _item_path, _show_path = f'tv/{tmdb_id}/season/{season}', f'tv/{tmdb_id}'
        elif dbtype == 'episode' and season is not None and episode:
            _item_path = f'tv/{tmdb_id}/season/{season}/episode/{episode}'
            _show_path = f'tv/{tmdb_id}'
        else:
            _item_path, _show_path = f'tv/{tmdb_id}', None

        show = _get(_show_path) if _show_path else {}
        item = _get(_item_path)

        overview = (item.get('overview') or '').strip() or (show.get('overview') or '').strip()
        # Genuri/tagline: la serial vin din 'show', la film sunt pe 'item'
        # (sezoanele/episoadele TMDb nu au aceste campuri deloc).
        _gsrc = show if show else item
        tagline_text = ((show.get('tagline') or item.get('tagline') or '')).strip()
        # TMDb nu traduce nici motto-ul, nici descrierea in multe limbi (de
        # multe ori nu are deloc traducere) si raspunde 200 cu obiectul gol,
        # deci fallback-ul de mai sus nu se declanseaza pentru ele. Aici se
        # cere explicit versiunea in englezza: fara asta un film netradus
        # arata motto-ul, dar nu si descrierea.
        if not tagline_text or not overview:
            _en_item = _get_en(_item_path)
            if not overview:
                overview = (_en_item.get('overview') or '').strip() or overview
            if not tagline_text:
                _en_show = _get_en(_show_path) if _show_path else _en_item
                tagline_text = (_en_show.get('tagline') or '').strip()
        genres_str = ', '.join(g.get('name') for g in (_gsrc.get('genres') or []) if g.get('name'))

        # Art pentru OSD: posterul itemului (la sezon/episod lipseste, se
        # ia posterul serialului), fanartul din backdrop.
        _poster = item.get('poster_path') or item.get('still_path') or show.get('poster_path') or ''
        _backdrop = item.get('backdrop_path') or show.get('backdrop_path') or ''
        art = {}
        if _poster:
            art['poster'] = art['thumb'] = IMG_BASE + _poster
        if _backdrop:
            art['fanart'] = BACKDROP_BASE + _backdrop

        def _head():
            # Acelasi format ca la Extended Info (dovedit corect in OSD).
            if tagline_text and genres_str:
                return f"[B][COLOR yellow]{tagline_text}[/COLOR][/B] | [B][COLOR FF00CED1]{genres_str}[/COLOR][/B]\n"
            elif tagline_text:
                return f"[B][COLOR yellow]{tagline_text}[/COLOR][/B]\n"
            elif genres_str:
                return f"[B][COLOR FF00CED1]{genres_str}[/COLOR][/B]\n"
            return ''

        if dbtype in ('season', 'episode'):
            # OSD-ul pentru continut episodic nu randeaza fiabil TagLine ->
            # ingropam motto+gen in plot (ca la Extended Info) si nu trimitem
            # tagline separat (ar risca duplicare).
            plot_out = _head() + overview
            log('OSD meta (seas/ep): plot={}c (cu antet motto|gen) art={}'.format(len(plot_out or ''), bool(art)))
            return plot_out or None, None, art

        # La fel ca la TMDb Info si Extended Info: motto-ul si genurile merg
        # IN plot, nu intr-un rand TagLine separat - multe skinuri nu
        # arata randul TagLine, iar acolo informatia s-ar pierdea. Tagline
        # separat ar dubla motto-ul in OSD.
        plot_out = _head() + overview
        log('OSD meta: plot={}c (cu antet motto|gen) art={}'.format(len(plot_out or ''), bool(art)))
        return plot_out or None, None, art
    except Exception as e:
        log('OSD meta error: {}'.format(e))
        return None, None, {}


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

    # Info label-urile din ListItem pot veni goale (de ex. dupa o redare
    # sau cand containerul tocmai s-a renovat). Atunci luam ID-ul TMDb din
    # cautarea pe titlu, ca trailerul, meta pentru OSD si posterul sa fie
    # la fel de disponibile in orice situatie.
    _title_search_done = False
    if not tmdb_id and title and media_type:
        log('tmdb_id missing from ListItem; searching by title')
        tmdb_id = search_tmdb_id_by_title(title, year, media_type)
        _title_search_done = True
        log('tmdb_id from title search: {}'.format(tmdb_id))

    # Meta pentru OSD (motto+gen + plot in limba setata), ca la TMDb INFO.
    _osd_dbtype = dbtype if dbtype in ('movie', 'tvshow', 'tv', 'season', 'episode') else media_type
    plot_param, tagline_param, art_param = None, None, {}
    if tmdb_id and media_type:
        plot_param, tagline_param, art_param = _get_details_for_osd(
            _osd_dbtype, tmdb_id, season=season, episode=episode_num)

    video_id = None
    url = ''
    imdb_id = get_first_valid([
        'ListItem.UniqueID(imdb)',
        'ListItem.Property(imdb_id)',
        'ListItem.Property(imdbId)'
    ])

    # Modul IMDb: intai trailerul de pe IMDb (MP4 direct, pornire imediata).
    # Cautarea pe YouTube ramane in a doua plan, ca fallback.
    try:
        from resources.lib.playback.trailer_player import get_trailer_mode, imdb_trailer_url
    except Exception:
        get_trailer_mode = None
        imdb_trailer_url = None
    if get_trailer_mode and get_trailer_mode() == 'imdb':
        url = imdb_trailer_url(tmdb_id=tmdb_id, dbtype=dbtype, imdb_id=imdb_id)
        log('IMDb trailer url: {}'.format('yes' if url else 'none'))

    if not url:
        if tmdb_id and media_type:
            video_id = find_trailer_video(tmdb_id, media_type, season=season)

        if not video_id and title and media_type and not _title_search_done:
            log('Fallback: searching by title')
            video_id = search_trailer_by_title(title, year, media_type, season=season)

        if not video_id and title:
            log('Fallback: searching YouTube directly')
            video_id = search_youtube_trailer(title, year)

        log('video_id={}'.format(video_id))

        if video_id:
            from resources.lib.playback.trailer_player import get_trailer_url
            url = get_trailer_url(video_id, tmdb_id=tmdb_id, dbtype=dbtype,
                                  title=title, year=year, season=season,
                                  plot=plot_param, tagline=tagline_param,
                                  imdb_id=imdb_id)

    if url:
        if genre and url.startswith('plugin://'):
            url = '{}&{}'.format(url, urlencode({'genre': genre}))
        li = xbmcgui.ListItem(path=url)
        tag = li.getVideoInfoTag()
        if title:
            tag.setTitle(title)
            tag.setOriginalTitle(title)
        if plot_param:
            tag.setPlot(plot_param)
        if genre:
            tag.setGenres([g.strip() for g in genre.replace('/', ',').split(',') if g.strip()])
        if art_param:
            try:
                li.setArt(art_param)
            except Exception:
                pass
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
