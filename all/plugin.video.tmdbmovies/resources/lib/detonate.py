# -*- coding: utf-8 -*-
# =============================================================================
# DETONATE - cloud.mail.ru public folders (Bollywood section)
#
# Flow (verificat live pe API real, 2026-08-20):
#   1. Listare folder public:
#        GET https://cloud.mail.ru/api/v2/folder?weblink=PKz7/7ATNUQoQk
#      -> body.list: [{name, kind: folder|file, size, weblink, mtime, hash}]
#      NOTA: parametrul weblink trebuie sa fie DOAR hash-ul "XXXX/YYYY"
#      (fara https://cloud.mail.ru/public/ - acel format da 400 "invalid").
#   2. Dispatcher (token de sesiune, se roteste):
#        GET https://cloud.mail.ru/api/v2/dispatcher
#      -> body.weblink_get.url = https://clocloNN.cloud.mail.ru/public/TOKEN/g/no
#   3. Download direct:
#        {weblink_get}/{weblink_cale}   (calea URL-encoded)
#      -> HTTP 301 catre https://clocloNN.datacloudmail.ru/public/get/.../no/file
#      -> fisierul direct, suporta Range requests (206) - playback Kodi OK.
#   4. Playlist HLS (videowl/0p/{b64}.m3u8) cere auth -> NU folosim.
# =============================================================================

import os
import re
import sys
import time
from urllib.parse import urlencode, quote, unquote

import xbmc
import xbmcgui
import xbmcplugin

from resources.lib.config import HANDLE, ADDON

API_FOLDER = "https://cloud.mail.ru/api/v2/folder"
API_DISPATCHER = "https://cloud.mail.ru/api/v2/dispatcher"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

VIDEO_EXTS = ('.mkv', '.mp4', '.avi', '.wmv', '.mov', '.m4v', '.ts', '.webm',
              '.flv', '.3gp', '.mpg', '.mpeg', '.m2ts', '.divx', '.ogv')

# Linkuri hardcodate, grupate pe ani. Userul furnizeaza un link nou pt fiecare
# an (radacina e de obicei chiar folderul numit cu anul, ex. '2026').
HARDCODED_LINKS = {
    '2026': ['PKz7/7ATNUQoQk'],
}

# Cache RAM pentru listari (TTL 300s) si dispatcher (TTL 300s)
_folder_cache = {}
_dispatcher_cache = {'ts': 0, 'url': ''}
_CACHE_TTL = 300

# Cache RAM pt rezultatele cautarilor TMDb: (titlu, an) -> tmdb_id
_search_cache = {}
_deadline_ts = [0.0]

# =============================================================================
# HTTP helpers
# =============================================================================

def _log(msg):
    try:
        xbmc.log("[DETONATE] " + str(msg), xbmc.LOGINFO)
    except Exception:
        pass


def _get_json(url, timeout=15):
    import requests
    try:
        r = requests.get(url, headers={'User-Agent': UA}, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        _log("GET " + url + " -> HTTP " + str(r.status_code))
    except Exception as e:
        _log("GET " + url + " error: " + repr(e))
    return None


# =============================================================================
# Links din setari
# =============================================================================

def _to_weblink(part):
    """Normalizeaza o intrare (URL complet sau hash) la forma hash XXXX/YYYY.
    Intoarce '' daca intrarea nu e un link cloud.mail.ru valid."""
    part = (part or '').strip()
    if not part:
        return ''
    m = re.search(r'cloud\.mail\.ru/public/([A-Za-z0-9_-]+/[A-Za-z0-9_-]+)', part, re.I)
    if m:
        return m.group(1)
    if re.match(r'^[A-Za-z0-9_-]+/[A-Za-z0-9_-]+$', part):
        return part
    return ''


def get_links():
    """Linkuri hardcodate (HARDCODED_LINKS) + setarea detonate_links
    (URL-uri sau hash-uri, separate prin virgula / newline / punct-virgula).
    Normalizate la hash si deduplicate pastrand ordinea: hardcodatele primele."""
    out = []
    for _year, links in HARDCODED_LINKS.items():
        for l in links:
            wl = _to_weblink(l)
            if wl and wl not in out:
                out.append(wl)
    try:
        raw = ADDON.getSetting('detonate_links') or ''
    except Exception:
        raw = ''
    for part in re.split(r'[,\n;]', raw):
        wl = _to_weblink(part)
        if wl and wl not in out:
            out.append(wl)
    return out


# =============================================================================
# Folder API
# =============================================================================

def _fetch_folder(weblink):
    """Listeaza folderul public. Cache RAM 300s. Returneaza (nume, list[])
    sau (None, None). Numele folderului poate fi el insusi un an (ex: radacina
    '2026' contine direct filmele - verificat pe API real)."""
    now = time.time()
    hit = _folder_cache.get(weblink)
    if hit and (now - hit[0]) < _CACHE_TTL:
        return hit[1], hit[2]
    data = _get_json(API_FOLDER + "?weblink=" + quote(weblink, safe=''))
    if data and data.get('status') == 200 and data.get('body'):
        body = data['body']
        listing = body.get('list') or []
        name = body.get('name') or ''
        _folder_cache[weblink] = (now, name, listing)
        return name, listing
    return None, None


def _get_dispatcher_url():
    """Intoarce URL-ul de baza weblink_get (token de sesiune). Cache 300s."""
    now = time.time()
    if _dispatcher_cache['url'] and (now - _dispatcher_cache['ts']) < _CACHE_TTL:
        return _dispatcher_cache['url']
    data = _get_json(API_DISPATCHER)
    if data and data.get('body'):
        try:
            url = data['body'].get('weblink_get') or []
            if isinstance(url, list):
                url = url[0].get('url', '') if url else ''
            elif isinstance(url, dict):
                url = url.get('url', '')
        except Exception:
            url = ''
        if url:
            _dispatcher_cache['ts'] = now
            _dispatcher_cache['url'] = url
            return url
    return ''


# =============================================================================
# Curatare nume filme
# =============================================================================

_YEAR_RE = re.compile(r'(?:\(?)(19|20)\d{2}(?:\)?)')
_QUALITY_RE = re.compile(r'(2160p|1080p|720p|480p|360p)', re.I)
_TAG_RE = re.compile(
    r'\b(?:2160p|1080p|720p|480p|360p|4k|hdr10?|hdr|hdrip|web-?dl|webrip|web-?rip|'
    r'hdhub4u|hdhub|x264|x265|h\.?264|h\.?265|hevc|10bit|8bit|ds4k|esub|subs?|'
    r'dubbed|ddp\s?5\.?1|dd5\.?1|dolby\s?atmos|atmos|aac|5\.1|7\.1|2\.0|dual\s?audio|'
    r'dual|audio|uncut|unrated|hq|extended|remux|blu-?ray|dvdrip|hdtv|proper|repack|'
    r'screener|\d+(?:\.\d+)?\s?(?:gb|gib|mb|mib|kbps)|amzn|netflix|prime|disney\+?|'
    r'ott|mxplayer|jiocinema|hindi|tamil|telugu|kannada|malayalam|bengali|marathi|'
    r'punjabi|oriya|english)\b', re.IGNORECASE)


def clean_title(name):
    """Extrage titlu + an din numele fisierului (ex: 'Alpha 2026 Kannada HQ
    HDRip - 720p - x264 - DD5.1 ... .mkv' -> 'Alpha', '2026')."""
    base = os.path.splitext(str(name))[0]
    year = ''
    head = base
    m = _YEAR_RE.search(base)
    if m:
        year = m.group(0).strip('()')
        head = base[:m.start()]
    parts = re.split(r'\s+-\s+', head, maxsplit=1)
    if len(parts) > 1 and (len(parts[0]) >= 3 or len(head) > 45):
        head = parts[0]
    title = _TAG_RE.sub(' ', head)
    title = re.sub(r'[._]+', ' ', title)
    title = re.sub(r'\s+', ' ', title).strip(' -–—_[]()')
    if not title:
        title = os.path.splitext(str(name))[0]
    return title, year


def _format_size(size):
    try:
        size = int(size or 0)
    except Exception:
        return ''
    if size <= 0:
        return ''
    if size >= 1073741824:
        return "{:.2f} GB".format(size / 1073741824)
    if size >= 1048576:
        return "{:.0f} MB".format(size / 1048576)
    return "{:.0f} KB".format(size / 1024)


def _quality_from_name(name):
    m = _QUALITY_RE.search(str(name))
    return m.group(1).lower() if m else ''


def _is_video(name):
    return os.path.splitext(str(name))[1].lower() in VIDEO_EXTS


# =============================================================================
# TMDb lookup (cautare + detalii) - paralel, cu deadline global
# =============================================================================

def _search_tmdb(title, year):
    """Cauta filmul pe TMDb (titlu curatat + an) si intoarce tmdb_id sau None.
    Prefera rezultatul cu anul identic, altfel primul rezultat."""
    try:
        from resources.lib.tmdb_api import get_tmdb_search_results
        res = get_tmdb_search_results(title, 'movie', 1)
        if res is None or res.status_code != 200:
            return None
        results = (res.json() or {}).get('results') or []
        if not results:
            return None
        best = results[0]
        if year:
            for it in results:
                rd = str(it.get('release_date') or '')[:4]
                if rd == str(year):
                    best = it
                    break
        return best.get('id')
    except Exception as e:
        _log("Search failed (" + str(title) + "): " + repr(e))
        return None


def _lookup(title, year):
    """Cautare + detalii TMDb pentru un film. Intoarce dict de detalii sau {}.
    Respecta deadline-ul global (listele raman rapide la prima vizita)."""
    key = (str(title).lower().strip(), str(year))
    tid = _search_cache.get(key)
    if tid is None:
        if time.time() > _deadline_ts[0]:
            return {}
        tid = _search_tmdb(title, year)
        if tid:
            _search_cache[key] = tid
    if not tid:
        return {}
    if time.time() > _deadline_ts[0]:
        return {}
    try:
        from resources.lib.tmdb_api import get_tmdb_item_details
        data = get_tmdb_item_details(tid, 'movie', lightweight=True)
        return data or {}
    except Exception as e:
        _log("Details failed (" + str(title) + "): " + repr(e))
        return {}


def _enrich_movies(files):
    """Lookup TMDb paralel (max 5 workeri, deadline global ~6s) pentru toate
    filmele dintr-o lista. Intoarce {nume_fisier: detalii}."""
    out = {}
    jobs = []
    for f in files:
        title, year = clean_title(f.get('name', ''))
        if title:
            jobs.append((f.get('name', ''), title, year))
    if not jobs:
        return out
    _deadline_ts[0] = time.time() + 6.0
    from concurrent.futures import ThreadPoolExecutor
    try:
        with ThreadPoolExecutor(max_workers=5) as ex:
            futs = {ex.submit(_lookup, t, y): n for n, t, y in jobs}
            for fut in futs:
                try:
                    meta = fut.result()
                except Exception:
                    meta = {}
                if meta:
                    out[futs[fut]] = meta
    except Exception as e:
        _log("Enrich error: " + repr(e))
    return out


# =============================================================================
# Rendering
# =============================================================================

def _base_url():
    return sys.argv[0]


def _add_folder(handle, label, params, icon='DefaultFolder.png'):
    url = _base_url() + '?' + urlencode(params)
    li = xbmcgui.ListItem(label=label)
    li.setArt({'icon': icon, 'thumb': icon, 'poster': icon})
    xbmcplugin.addDirectoryItem(handle, url, li, isFolder=True)


def _add_movie(handle, entry, meta=None):
    """Adauga un fisier video ca item playable. Cand lookup-ul TMDb a reusit
    (meta): poster/fanart/plot/rating/durata + bifa watched + cerculet de
    resume de la providerul activ (via set_metadata)."""
    name = entry.get('name', '')
    weblink = entry.get('weblink', '')
    title, year = clean_title(name)
    size = _format_size(entry.get('size'))
    quality = _quality_from_name(name)

    label = title
    if year:
        label += " (" + year + ")"
    if size:
        label += " [B][COLOR gray][" + size + "][/COLOR][/B]"
    if quality:
        label += " [B][COLOR FF6AFB92][" + quality + "][/COLOR][/B]"

    tmdb_id = ''
    if meta:
        tmdb_id = str(meta.get('id') or meta.get('tmdb_id') or '')

    watched = False
    progress = 0
    if tmdb_id:
        try:
            from resources.lib import watched_provider
            watched = bool(watched_provider.is_movie_watched(tmdb_id))
        except Exception:
            pass
        try:
            from resources.lib import trakt_sync
            progress = float(trakt_sync.get_local_playback_progress(tmdb_id, 'movie') or 0)
        except Exception:
            pass

    if watched and '[COLOR' not in label:
        label = '[B][COLOR FF6AFB92]' + label + '[/COLOR][/B]'

    params = {'mode': 'detonate_play', 'link': weblink}
    if tmdb_id:
        params['tmdb_id'] = tmdb_id
    url = _base_url() + '?' + urlencode(params)

    li = xbmcgui.ListItem(label=label)
    li.setProperty('IsPlayable', 'true')

    info = {'mediatype': 'movie', 'title': title}
    if year:
        info['year'] = int(year)
    if size:
        info['size'] = entry.get('size', 0)

    if meta:
        from resources.lib.config import IMG_BASE, BACKDROP_BASE
        poster_path = meta.get('poster_path', '')
        backdrop_path = meta.get('backdrop_path', '')
        poster = (IMG_BASE + poster_path) if poster_path else 'DefaultVideo.png'
        backdrop = (BACKDROP_BASE + backdrop_path) if backdrop_path else ''
        li.setArt({'icon': poster, 'thumb': poster, 'poster': poster, 'fanart': backdrop})

        plot = meta.get('overview', '') or ''
        tagline = str(meta.get('tagline') or '').strip()
        try:
            genres = ", ".join([g['name'] for g in meta.get('genres', [])])
        except Exception:
            genres = ''
        plot_header = ''
        if tagline and genres:
            plot_header = "[B][COLOR yellow]" + tagline + "[/COLOR][/B] | [B][COLOR FF00CED1]" + genres + "[/COLOR][/B]\n"
        elif tagline:
            plot_header = "[B][COLOR yellow]" + tagline + "[/COLOR][/B]\n"
        elif genres:
            plot_header = "[B][COLOR FF00CED1]" + genres + "[/COLOR][/B]\n"
        info['plot'] = plot_header + plot
        info['rating'] = meta.get('vote_average', 0)
        info['votes'] = meta.get('vote_count', 0)
        info['premiered'] = meta.get('release_date', '')
        try:
            studio = meta['production_companies'][0].get('name', '')
        except Exception:
            studio = ''
        if studio:
            info['studio'] = studio
        try:
            duration = int(meta.get('runtime') or 0) * 60
        except Exception:
            duration = 0
        if duration <= 0:
            duration = 7200
        info['duration'] = duration

        resume_percent = 0
        if progress >= 1000000:
            resume_time = int(progress - 1000000)
            resume_percent = (resume_time / duration) * 100
        elif 0 < progress < 90:
            resume_percent = progress
        info['resume_percent'] = resume_percent
    else:
        icon = 'DefaultVideo.png'
        li.setArt({'icon': icon, 'thumb': icon, 'poster': icon})

    try:
        from resources.lib.tmdb_api import set_metadata
        unique_ids = {'tmdb': tmdb_id} if tmdb_id else None
        set_metadata(li, info, unique_ids=unique_ids, watched_info=watched)
    except Exception:
        li.setInfo('video', {'title': title, 'mediatype': 'movie'})
        if year:
            li.setInfo('video', {'year': int(year)})

    # Context menu complet (My Trakt / My TMDB / My MDBList / My Simkl /
    # Mark Watched-Unwatched / Add to Favorites / Delete Resume etc.) —
    # acelasi meniu ca in restul addonului, gate-uit de Settings > Menu.
    if tmdb_id:
        try:
            from resources.lib.tmdb_api import _get_full_context_menu
            _imdb = ''
            try:
                _imdb = (meta or {}).get('external_ids', {}).get('imdb_id', '')
            except Exception:
                pass
            cm = _get_full_context_menu(tmdb_id, 'movie', title, year=year, imdb_id=_imdb)
            if cm:
                li.addContextMenuItems(cm)
        except Exception as e:
            _log("Context menu error: " + repr(e))

    xbmcplugin.addDirectoryItem(handle, url, li, isFolder=False)


# =============================================================================
# Liste
# =============================================================================

def list_years():
    """Radacina Detonate: ani (radacina insasi numita cu anul, subfoldere
    ^\\d{4}$ sau anul extras din numele fisierelor), alte foldere, filme directe."""
    handle = HANDLE
    links = get_links()
    if not links:
        xbmcgui.Dialog().notification('Detonate', 'No cloud.mail.ru links configured - add them in Settings > Detonate', xbmcgui.NOTIFICATION_WARNING, 6000)
        xbmcplugin.endOfDirectory(handle)
        return

    years = {}        # an -> weblink-ul de deschis
    folders = {}
    files = []
    for link in links:
        root_name, listing = _fetch_folder(link)
        if listing is None:
            _log("Folder fetch failed: " + link)
            continue
        if root_name and re.fullmatch(r'\d{4}', root_name):
            # Radacina insasi e un an (ex: folderul '2026' cu 33 filme direct)
            years.setdefault(root_name, link)
            continue
        for it in listing:
            kind = it.get('kind', 'file')
            if kind == 'folder':
                fname = it.get('name', '')
                if re.fullmatch(r'\d{4}', fname):
                    years.setdefault(fname, it.get('weblink', ''))
                else:
                    folders.setdefault(fname, it)
            elif _is_video(it.get('name', '')):
                files.append(it)
    # Filmele din radacini care nu sunt an: anul din numele fisierului
    for f in files:
        _t, _y = clean_title(f.get('name', ''))
        if _y:
            years.setdefault(_y, '')

    xbmcplugin.setContent(handle, 'files')
    for y in sorted(years, reverse=True):
        _add_folder(handle, '[B][COLOR FFCCCCFF]' + y + '[/COLOR][/B]',
                    {'mode': 'detonate_year', 'year': y}, icon='calender.png')
    for fname in sorted(folders):
        f = folders[fname]
        _add_folder(handle, fname,
                    {'mode': 'detonate_folder', 'link': f.get('weblink', '')})
    if not years:
        metas = _enrich_movies(files)
        for f in files:
            _add_movie(handle, f, metas.get(f.get('name', '')))
    xbmcplugin.endOfDirectory(handle)


def list_year(year):
    """Filmele din anul dat, colectate din toate link-urile configurate.
    Surse posibile: radacina numita cu anul, subfolder numit cu anul,
    sau filme cu anul in nume aflate direct in radacina."""
    handle = HANDLE
    links = get_links()
    if not links:
        xbmcplugin.endOfDirectory(handle)
        return

    seen = {}
    for link in links:
        root_name, listing = _fetch_folder(link)
        if listing is None:
            continue
        target = None
        if root_name == str(year):
            target = listing
        else:
            for it in listing:
                if it.get('kind') == 'folder' and it.get('name') == str(year):
                    _rn, sub = _fetch_folder(it.get('weblink', ''))
                    target = sub
                    break
            if target is None:
                # radacina ne-an: filme direct cu anul in nume
                for f in listing:
                    if f.get('kind') == 'file' and _is_video(f.get('name', '')):
                        _t, _y = clean_title(f.get('name', ''))
                        if _y == str(year):
                            seen.setdefault(f.get('name', ''), f)
                continue
        for f in (target or []):
            if f.get('kind') == 'file' and _is_video(f.get('name', '')):
                seen.setdefault(f.get('name', ''), f)

    metas = _enrich_movies(list(seen.values()))
    xbmcplugin.setContent(handle, 'movies')
    for fname in sorted(seen):
        _add_movie(handle, seen[fname], metas.get(fname))
    xbmcplugin.endOfDirectory(handle)


def list_folder(weblink):
    """Listare generica de folder (foldere non-an din radacina)."""
    handle = HANDLE
    _name, listing = _fetch_folder(weblink)
    files = []
    if listing:
        for it in listing:
            if it.get('kind') == 'folder':
                _add_folder(handle, it.get('name', ''),
                            {'mode': 'detonate_folder', 'link': it.get('weblink', '')})
            elif _is_video(it.get('name', '')):
                files.append(it)
    metas = _enrich_movies(files)
    xbmcplugin.setContent(handle, 'files')
    for f in files:
        _add_movie(handle, f, metas.get(f.get('name', '')))
    xbmcplugin.endOfDirectory(handle)


# =============================================================================
# Playback
# =============================================================================
# CRITIC (descoperit pe API real, 2026-08-20): token-ul din URL-ul de redirect
# (datacloudmail.ru/public/get/{token}/no/{file}) e LEGAT de User-Agent-ul
# cererii care a primit 301-ul. Daca addonul urmareste redirect-ul cu UA Mozilla
# si da lui Kodi URL-ul final, Kodi deschide cu UA-ul lui (Kodi/21.0) -> 403.
# De aceea biblioteca mailru-cloud-guest-api intoarce DOAR URL-ul start
# (weblink_get + cale) fara sa urmareasca redirect-ul: downloader-ul urmareste
# 301 cu propriul UA in aceeasi lant de cereri -> token valid.
# Fix: NU urmarim redirect-ul in Python; Kodi urmareste 301 cu UA-ul lui.

def play_movie(weblink, tmdb_id=''):
    """Playback direct: URL-ul start (weblink_get + cale) dat direct lui Kodi,
    care urmareste 301 cu propriul UA (token valid). Cu tmdb_id: art/plot
    din cache-ul TMDb (instant, deja populat de lista)."""
    handle = HANDLE
    base = _get_dispatcher_url()
    if not base:
        xbmcgui.Dialog().notification('Detonate', 'Could not resolve file URL', xbmcgui.NOTIFICATION_ERROR, 6000)
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
        return
    url = base.rstrip('/') + '/' + quote(weblink, safe='/')

    name = os.path.basename(unquote(weblink))
    title, year = clean_title(name)

    li = xbmcgui.ListItem(path=url)
    info = {'mediatype': 'movie', 'title': title}
    if year:
        info['year'] = int(year)
    if tmdb_id:
        try:
            from resources.lib.tmdb_api import get_tmdb_item_details
            from resources.lib.config import IMG_BASE, BACKDROP_BASE
            meta = get_tmdb_item_details(tmdb_id, 'movie', lightweight=True) or {}
            poster_path = meta.get('poster_path', '')
            backdrop_path = meta.get('backdrop_path', '')
            if poster_path:
                li.setArt({'icon': IMG_BASE + poster_path, 'thumb': IMG_BASE + poster_path,
                           'poster': IMG_BASE + poster_path})
            if backdrop_path:
                li.setArt({'fanart': BACKDROP_BASE + backdrop_path})
            if meta.get('overview'):
                info['plot'] = meta['overview']
        except Exception:
            pass

    try:
        from resources.lib.tmdb_api import set_metadata
        set_metadata(li, info, unique_ids={'tmdb': tmdb_id} if tmdb_id else None, watched_info=False)
    except Exception:
        li.setInfo('video', {'title': title, 'mediatype': 'movie'})
        if year:
            li.setInfo('video', {'year': int(year)})

    _log("Playing: " + title + " -> " + url)
    xbmcplugin.setResolvedUrl(handle, True, li)
    try:
        xbmc.Player().play(url, li)
    except Exception as e:
        _log("player.play error: " + repr(e))