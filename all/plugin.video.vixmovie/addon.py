import datetime
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qsl, urlencode

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin

import client


def log(msg, level="info"):
    prefix = "[VIXMOVIE-ADDON]"
    xbmc.log(f"{prefix} [{level.upper()}]: {msg}")


# --- Setup ---
_HANDLE = int(sys.argv[1])
_BASE_URL = sys.argv[0]
_ARGS = dict(parse_qsl(sys.argv[2][1:]))
ADDON = xbmcaddon.Addon()
TITLES_RO = ADDON.getSetting("titles_ro") == "true"
PLOTS_RO = ADDON.getSetting("plots_ro") == "true"
TITLES_EN = ADDON.getSetting("titles_english") == "true"


# --- Lazy-loaded Global Data ---
_MOVIE_IDS = None
_TV_IDS = None
_EPISODE_INFO = None
_PREFETCH_LOCK = threading.Lock()


def _prefetch_ids(media_type):
    global _MOVIE_IDS, _TV_IDS
    try:
        if media_type == "tv":
            if _TV_IDS is None:
                client.get_source_tv_ids()
        else:
            if _MOVIE_IDS is None:
                client.get_source_movie_ids()
    except Exception:
        pass


def prefetch_ids_async(media_type):
    thread = threading.Thread(target=_prefetch_ids, args=(media_type,))
    thread.daemon = True
    thread.start()


def get_movie_ids():
    global _MOVIE_IDS
    if _MOVIE_IDS is None:
        _MOVIE_IDS = client.get_source_movie_ids()
    return _MOVIE_IDS


def get_tv_ids():
    global _TV_IDS
    if _TV_IDS is None:
        _TV_IDS = client.get_source_tv_ids()
    return _TV_IDS


def get_episode_info():
    global _EPISODE_INFO
    if _EPISODE_INFO is None:
        _EPISODE_INFO = client.get_source_episode_info()
    return _EPISODE_INFO


# --- Constants ---
ITEMS_PER_PAGE = 20
IMG_BASE_URL = "https://image.tmdb.org/t/p/"

# --- Refactored Helper Functions: Item Creation ---


def _create_base_list_item(
    title,
    params,
    info_data,
    art_data,
    is_folder,
    is_playable=False,
    tmdb_id=None,
    media_type=None,
):
    li = xbmcgui.ListItem(title)
    if is_playable:
        li.setProperty("IsPlayable", "true")

    li.setInfo("video", {k: v for k, v in info_data.items() if not k.startswith("_")})
    li.setArt(art_data)

    cast_list = info_data.get("_cast") or []
    try:
        if cast_list:
            li.setCast(cast_list)
    except Exception:
        pass

    try:
        tmdb_rating = float(info_data.get("rating") or 0)
        tmdb_votes = int(info_data.get("votes") or 0)
        if tmdb_rating > 0:
            li.setRating("tmdb", tmdb_rating, votes=tmdb_votes, defaultt=True)
    except Exception:
        pass

    if tmdb_id and media_type:
        is_fav = client.is_favorite(str(tmdb_id), media_type)
        if is_fav:
            li.addContextMenuItems(
                [
                    (
                        "Elimina din favorite",
                        f"RunPlugin({_BASE_URL}?action=toggle_favorite&media_type={media_type}&tmdb_id={tmdb_id}&title={title})",
                    )
                ]
            )
        else:
            li.addContextMenuItems(
                [
                    (
                        "Adauga la favorite",
                        f"RunPlugin({_BASE_URL}?action=toggle_favorite&media_type={media_type}&tmdb_id={tmdb_id}&title={title})",
                    )
                ]
            )

    url = f"{_BASE_URL}?{urlencode(params)}"
    return url, li, is_folder


def _create_movie_item(details):
    if not details or not details.get("id"):
        return None

    tmdb_id = details["id"]
    needs_en = TITLES_EN or (not TITLES_RO) or (not PLOTS_RO)

    # Single combined API call: details + credits + videos (append_to_response)
    lang = "en-US" if needs_en else "ro-RO"
    full = client.get_movie_full_details(tmdb_id, lang) or {}

    # --- Title ---
    ro_title = details.get("title") or details.get("original_title") or ""
    if needs_en:
        title = full.get("title") or full.get("original_title") or ro_title
        if TITLES_RO and not TITLES_EN:
            # Only overview is in EN, keep RO title
            title = ro_title
    else:
        title = ro_title

    if not title:
        return None

    # --- Overview ---
    if not PLOTS_RO:
        overview = full.get("overview") or details.get("overview") or ""
    else:
        overview = details.get("overview") or ""

    # --- Cast (from combined response) ---
    credits_data = full.get("credits") or {}
    cast = []
    for p in (credits_data.get("cast") or [])[:20]:
        cast.append(
            {
                "name": p.get("name", ""),
                "role": p.get("character", "") or "",
                "thumbnail": f"{IMG_BASE_URL}w185{p['profile_path']}"
                if p.get("profile_path")
                else "",
            }
        )

    # --- Trailer (from combined response) ---
    trailer_url = client.get_trailer_url_from_videos_data(full.get("videos"))
    if not trailer_url:
        trailer_url = (
            f"plugin://plugin.video.themoviedb.helper/play/plugin/"
            f"?type=trailer&tmdb_type=movie&tmdb_id={tmdb_id}"
        )

    # --- Genres (full objects only available in detail call) ---
    genres = full.get("genres") or []
    genre_str = " / ".join([g["name"] for g in genres if g.get("name")])

    params = {
        "action": "play",
        "media_type": "movie",
        "tmdb_id": tmdb_id,
        "title": title,
    }
    info = {
        "title": title,
        "originaltitle": details.get("original_title")
        or full.get("original_title")
        or "",
        "year": int(
            (details.get("release_date") or full.get("release_date") or "0").split("-")[
                0
            ]
            or 0
        ),
        "plot": overview,
        "rating": details.get("vote_average") or full.get("vote_average"),
        "votes": details.get("vote_count") or full.get("vote_count") or 0,
        "duration": (full.get("runtime") or 0) * 60,
        "genre": genre_str,
        "mediatype": "movie",
        "trailer": trailer_url,
        "_cast": cast,
    }

    art = {
        "poster": f"{IMG_BASE_URL}w500{details['poster_path']}"
        if details.get("poster_path")
        else "",
        "fanart": f"{IMG_BASE_URL}original{details['backdrop_path']}"
        if details.get("backdrop_path")
        else "",
    }

    return _create_base_list_item(
        title,
        params,
        info,
        art,
        is_folder=False,
        is_playable=True,
        tmdb_id=tmdb_id,
        media_type="movie",
    )


def _create_tv_show_item(details):
    if not details or not details.get("id"):
        return None

    tmdb_id = details["id"]
    needs_en = TITLES_EN or (not TITLES_RO) or (not PLOTS_RO)

    # Single combined API call: details + credits + videos (append_to_response)
    lang = "en-US" if needs_en else "ro-RO"
    full = client.get_tv_full_details(tmdb_id, lang) or {}

    # --- Title ---
    ro_title = details.get("name") or details.get("original_name") or ""
    if needs_en:
        title = full.get("name") or full.get("original_name") or ro_title
        if TITLES_RO and not TITLES_EN:
            # Only overview is in EN, keep RO title
            title = ro_title
    else:
        title = ro_title

    if not title:
        return None

    # --- Overview ---
    if not PLOTS_RO:
        overview = full.get("overview") or details.get("overview") or ""
    else:
        overview = details.get("overview") or ""

    # --- Cast (from combined response) ---
    credits_data = full.get("credits") or {}
    cast = []
    for p in (credits_data.get("cast") or [])[:20]:
        cast.append(
            {
                "name": p.get("name", ""),
                "role": p.get("character", "") or "",
                "thumbnail": f"{IMG_BASE_URL}w185{p['profile_path']}"
                if p.get("profile_path")
                else "",
            }
        )

    # --- Trailer (from combined response) ---
    trailer_url = client.get_trailer_url_from_videos_data(full.get("videos"))
    if not trailer_url:
        trailer_url = (
            f"plugin://plugin.video.themoviedb.helper/play/plugin/"
            f"?type=trailer&tmdb_type=tv&tmdb_id={tmdb_id}"
        )

    # --- Genres (full objects only available in detail call) ---
    genres = full.get("genres") or []
    genre_str = " / ".join([g["name"] for g in genres if g.get("name")])

    params = {"action": "list_seasons", "tv_show_id": tmdb_id, "title": title}
    info = {
        "title": title,
        "originaltitle": details.get("original_name")
        or full.get("original_name")
        or "",
        "year": int(
            (details.get("first_air_date") or full.get("first_air_date") or "0").split(
                "-"
            )[0]
            or 0
        ),
        "plot": overview,
        "rating": details.get("vote_average") or full.get("vote_average"),
        "votes": details.get("vote_count") or full.get("vote_count") or 0,
        "genre": genre_str,
        "mediatype": "tvshow",
        "trailer": trailer_url,
        "_cast": cast,
    }

    art = {
        "poster": f"{IMG_BASE_URL}w500{details['poster_path']}"
        if details.get("poster_path")
        else "",
        "fanart": f"{IMG_BASE_URL}original{details['backdrop_path']}"
        if details.get("backdrop_path")
        else "",
    }

    return _create_base_list_item(
        title, params, info, art, is_folder=True, tmdb_id=tmdb_id, media_type="tv"
    )


def _create_season_item(tv_show_id, season_details):
    season_number = season_details.get("season_number")
    title = season_details.get("name", f"Season {season_number}")

    params = {
        "action": "list_episodes",
        "tv_show_id": tv_show_id,
        "season_number": season_number,
    }
    info = {
        "title": title,
        "plot": season_details.get("overview"),
        "year": int(season_details.get("air_date", "0").split("-")[0]),
        "mediatype": "season",
    }
    art = {
        "poster": f"{IMG_BASE_URL}w500{season_details.get('poster_path')}"
        if season_details.get("poster_path")
        else ""
    }

    return _create_base_list_item(title, params, info, art, is_folder=True)


def _create_episode_item(tv_show_id, episode_details):
    season_number = episode_details.get("season_number")
    episode_number = episode_details.get("episode_number")
    title = f"{episode_number}. {episode_details.get('name')}"

    params = {
        "action": "play",
        "media_type": "episode",
        "tmdb_id": tv_show_id,
        "season": season_number,
        "episode": episode_number,
        "title": title,
    }
    info = {
        "title": title,
        "plot": episode_details.get("overview"),
        "rating": episode_details.get("vote_average"),
        "aired": episode_details.get("air_date"),
        "mediatype": "episode",
    }
    art = {
        "thumb": f"{IMG_BASE_URL}w500{episode_details.get('still_path')}"
        if episode_details.get("still_path")
        else ""
    }

    return _create_base_list_item(
        title, params, info, art, is_folder=False, is_playable=True
    )


# --- Generic Population Function ---
def _populate_filtered_list(media_type, api_func, api_params, page, next_action_params):
    content_type = "tvshows" if media_type == "tv" else "movies"
    xbmcplugin.setContent(_HANDLE, content_type)

    create_item_func = (
        _create_tv_show_item if media_type == "tv" else _create_movie_item
    )

    xbmc.executebuiltin("Container.SetViewMode(50)")

    local_ids = get_tv_ids() if media_type == "tv" else get_movie_ids()
    if not local_ids:
        xbmcgui.Dialog().notification(
            "MIAF", "Se încarcă listele... Așteptați.", xbmcgui.NOTIFICATION_INFO, 3000
        )
        xbmcplugin.endOfDirectory(_HANDLE)
        return

    # --- Phase 1: collect enough filtered TMDB results (fast — uses cached list API) ---
    items_to_skip = (page - 1) * ITEMS_PER_PAGE
    collected = []
    tmdb_page = 0
    has_more_results = True

    while len(collected) < ITEMS_PER_PAGE and has_more_results:
        tmdb_page += 1
        api_params_copy = dict(api_params)
        api_params_copy["page"] = tmdb_page

        data = api_func(**api_params_copy)

        if not data:
            xbmcgui.Dialog().notification(
                "Eroare",
                "Nu s-au putut încărca datele. Verificați conexiunea.",
                xbmcgui.NOTIFICATION_ERROR,
            )
            has_more_results = False
            break

        if not data.get("results") or data.get("page", 1) > data.get("total_pages", 1):
            has_more_results = False
            break

        filtered = [r for r in data["results"] if str(r["id"]) in local_ids]

        # Skip items for plugin-level pagination
        if items_to_skip > 0:
            skip = min(items_to_skip, len(filtered))
            filtered = filtered[skip:]
            items_to_skip -= skip

        collected.extend(filtered)

        if data.get("page", 1) >= data.get("total_pages", 1):
            has_more_results = False

    # --- Phase 2: build list items in parallel (each item does 1 TMDb API call) ---
    batch = collected[:ITEMS_PER_PAGE]

    with ThreadPoolExecutor(max_workers=8) as executor:
        items = list(executor.map(create_item_func, batch))

    items_added = 0
    for item in items:
        if item:
            xbmcplugin.addDirectoryItem(
                handle=_HANDLE, url=item[0], listitem=item[1], isFolder=item[2]
            )
            items_added += 1

    # Show "next page" if there are more results (either more TMDB pages, or
    # we collected more than one page worth of items)
    if items_added > 0 and (has_more_results or len(collected) > ITEMS_PER_PAGE):
        next_page_li = xbmcgui.ListItem(f"Pagina următoare ({page + 1})")
        next_page_li.setArt({"icon": "DefaultFolder.png"})
        next_action_params["page"] = page + 1
        url = f"{_BASE_URL}?{urlencode(next_action_params)}"
        xbmcplugin.addDirectoryItem(
            handle=_HANDLE, url=url, listitem=next_page_li, isFolder=True
        )

    xbmcplugin.endOfDirectory(_HANDLE)


# --- Playback ---
def play_media():
    media_type = _ARGS.get("media_type")
    tmdb_id = _ARGS.get("tmdb_id")
    title = _ARGS.get("title", "Necunoscut")

    xbmc.executebuiltin("ActivateWindow(busyindicator,'','','')")

    try:
        if media_type == "movie":
            stream_url = client.get_stream_url(tmdb_id)
        elif media_type == "episode":
            season = _ARGS.get("season")
            episode = _ARGS.get("episode")
            stream_url = client.get_stream_url(tmdb_id, season, episode)
        else:
            stream_url = None
    except Exception as e:
        log(f"Playback error: {e}")
        stream_url = None
    finally:
        xbmc.executebuiltin("Dialog.Close(busyindicator)")

    if stream_url:
        play_item = xbmcgui.ListItem(path=stream_url)
        play_item.setInfo("video", {"title": title})
        xbmcplugin.setResolvedUrl(_HANDLE, True, listitem=play_item)
    else:
        xbmcgui.Dialog().notification(
            "MIAF",
            f'Nu am putut obține link-ul pentru "{title}"',
            xbmcgui.NOTIFICATION_WARNING,
        )
        xbmcplugin.setResolvedUrl(_HANDLE, False, listitem=xbmcgui.ListItem())


# --- Main Menu & Navigation ---
def list_main_menu():
    xbmcplugin.setPluginCategory(_HANDLE, "MIAF")

    li_search = xbmcgui.ListItem("Caută")
    li_search.setArt({"icon": "DefaultAddonsSearch.png"})
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE,
        url=f"{_BASE_URL}?action=list_search_menu",
        listitem=li_search,
        isFolder=True,
    )

    li_movies = xbmcgui.ListItem("Filme")
    li_movies.setArt({"icon": "DefaultMovies.png"})
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE,
        url=f"{_BASE_URL}?action=list_movies_menu",
        listitem=li_movies,
        isFolder=True,
    )

    li_tv = xbmcgui.ListItem("Seriale")
    li_tv.setArt({"icon": "DefaultTVShows.png"})
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE,
        url=f"{_BASE_URL}?action=list_tv_menu",
        listitem=li_tv,
        isFolder=True,
    )

    li_trending = xbmcgui.ListItem("În Trend")
    li_trending.setArt({"icon": "DefaultMovies.png"})
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE,
        url=f"{_BASE_URL}?action=list_trending",
        listitem=li_trending,
        isFolder=True,
    )

    li_networks = xbmcgui.ListItem("Rețele TV")
    li_networks.setArt({"icon": "DefaultTVShows.png"})
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE,
        url=f"{_BASE_URL}?action=list_networks",
        listitem=li_networks,
        isFolder=True,
    )

    li_favorites = xbmcgui.ListItem("Favorite")
    li_favorites.setArt({"icon": "DefaultFavourites.png"})
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE,
        url=f"{_BASE_URL}?action=list_favorites_menu",
        listitem=li_favorites,
        isFolder=True,
    )

    xbmcplugin.endOfDirectory(_HANDLE)


def list_search_menu():
    prefetch_ids_async("movie")
    prefetch_ids_async("tv")
    xbmcplugin.setPluginCategory(_HANDLE, "Caută")

    li_movies = xbmcgui.ListItem("Caută Filme")
    li_movies.setArt({"icon": "DefaultMovies.png"})
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE,
        url=f"{_BASE_URL}?action=search&media_type=movie",
        listitem=li_movies,
        isFolder=False,
    )

    li_tv = xbmcgui.ListItem("Caută Seriale")
    li_tv.setArt({"icon": "DefaultTVShows.png"})
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE,
        url=f"{_BASE_URL}?action=search&media_type=tv",
        listitem=li_tv,
        isFolder=False,
    )

    li_person = xbmcgui.ListItem("Caută Persoane (Actori/Regizori)")
    li_person.setArt({"icon": "DefaultActor.png"})
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE,
        url=f"{_BASE_URL}?action=search_person",
        listitem=li_person,
        isFolder=False,
    )
    xbmcplugin.endOfDirectory(_HANDLE)


def list_movies_menu():
    prefetch_ids_async("movie")
    xbmcplugin.setPluginCategory(_HANDLE, "Filme")

    li_popular = xbmcgui.ListItem("Cele mai populare")
    li_popular.setArt({"icon": "DefaultMovies.png"})
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE,
        url=f"{_BASE_URL}?action=list_popular&media_type=movie",
        listitem=li_popular,
        isFolder=True,
    )

    li_top = xbmcgui.ListItem("Cele mai bine evaluate")
    li_top.setArt({"icon": "DefaultMovies.png"})
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE,
        url=f"{_BASE_URL}?action=list_top_rated&media_type=movie",
        listitem=li_top,
        isFolder=True,
    )

    li_upcoming = xbmcgui.ListItem("În curând")
    li_upcoming.setArt({"icon": "DefaultRecentlyAddedMovies.png"})
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE,
        url=f"{_BASE_URL}?action=list_upcoming&media_type=movie",
        listitem=li_upcoming,
        isFolder=True,
    )

    li_now = xbmcgui.ListItem("Acum în cinematografe")
    li_now.setArt({"icon": "DefaultMovies.png"})
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE,
        url=f"{_BASE_URL}?action=list_now_playing&media_type=movie",
        listitem=li_now,
        isFolder=True,
    )

    li_years = xbmcgui.ListItem("După an")
    li_years.setArt({"icon": "DefaultYear.png"})
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE,
        url=f"{_BASE_URL}?action=list_years&media_type=movie",
        listitem=li_years,
        isFolder=True,
    )

    li_decades = xbmcgui.ListItem("După deceniu")
    li_decades.setArt({"icon": "DefaultYear.png"})
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE,
        url=f"{_BASE_URL}?action=list_decades&media_type=movie",
        listitem=li_decades,
        isFolder=True,
    )

    li_genres = xbmcgui.ListItem("După gen")
    li_genres.setArt({"icon": "DefaultGenre.png"})
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE,
        url=f"{_BASE_URL}?action=list_genres&media_type=movie",
        listitem=li_genres,
        isFolder=True,
    )
    xbmcplugin.endOfDirectory(_HANDLE)


def list_tv_menu():
    prefetch_ids_async("tv")
    xbmcplugin.setPluginCategory(_HANDLE, "Seriale")

    li_popular = xbmcgui.ListItem("Cele mai populare")
    li_popular.setArt({"icon": "DefaultTVShows.png"})
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE,
        url=f"{_BASE_URL}?action=list_popular&media_type=tv",
        listitem=li_popular,
        isFolder=True,
    )

    li_top = xbmcgui.ListItem("Cele mai bine evaluate")
    li_top.setArt({"icon": "DefaultTVShows.png"})
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE,
        url=f"{_BASE_URL}?action=list_top_rated&media_type=tv",
        listitem=li_top,
        isFolder=True,
    )

    li_airing = xbmcgui.ListItem("Azi la TV")
    li_airing.setArt({"icon": "DefaultTVShows.png"})
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE,
        url=f"{_BASE_URL}?action=list_airing_today&media_type=tv",
        listitem=li_airing,
        isFolder=True,
    )

    li_onair = xbmcgui.ListItem("În difuzare")
    li_onair.setArt({"icon": "DefaultInProgressShows.png"})
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE,
        url=f"{_BASE_URL}?action=list_on_the_air&media_type=tv",
        listitem=li_onair,
        isFolder=True,
    )

    li_years = xbmcgui.ListItem("După an")
    li_years.setArt({"icon": "DefaultYear.png"})
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE,
        url=f"{_BASE_URL}?action=list_years&media_type=tv",
        listitem=li_years,
        isFolder=True,
    )

    li_decades = xbmcgui.ListItem("După deceniu")
    li_decades.setArt({"icon": "DefaultYear.png"})
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE,
        url=f"{_BASE_URL}?action=list_decades&media_type=tv",
        listitem=li_decades,
        isFolder=True,
    )

    li_genres = xbmcgui.ListItem("După gen")
    li_genres.setArt({"icon": "DefaultGenre.png"})
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE,
        url=f"{_BASE_URL}?action=list_genres&media_type=tv",
        listitem=li_genres,
        isFolder=True,
    )
    xbmcplugin.endOfDirectory(_HANDLE)


# --- Listing Functions (Movies & TV) ---
def list_popular():
    media_type = _ARGS.get("media_type")
    page = int(_ARGS.get("page", "1"))
    api_func = (
        client.get_popular_tv_tmdb if media_type == "tv" else client.get_popular_tmdb
    )
    xbmcplugin.setPluginCategory(_HANDLE, f"Cele mai populare (Pagina {page})")
    _populate_filtered_list(
        media_type,
        api_func,
        {},
        page,
        {"action": "list_popular", "media_type": media_type},
    )


def list_top_rated():
    media_type = _ARGS.get("media_type")
    page = int(_ARGS.get("page", "1"))
    api_func = (
        client.get_top_rated_tv_tmdb
        if media_type == "tv"
        else client.get_top_rated_tmdb
    )
    xbmcplugin.setPluginCategory(_HANDLE, f"Cele mai bine evaluate (Pagina {page})")
    _populate_filtered_list(
        media_type,
        api_func,
        {},
        page,
        {"action": "list_top_rated", "media_type": media_type},
    )


def list_upcoming():
    page = int(_ARGS.get("page", "1"))
    api_func = client.get_upcoming_tmdb
    xbmcplugin.setPluginCategory(_HANDLE, f"În curând (Pagina {page})")
    _populate_filtered_list(
        "movie",
        api_func,
        {},
        page,
        {"action": "list_upcoming", "media_type": "movie"},
    )


def list_now_playing():
    page = int(_ARGS.get("page", "1"))
    api_func = client.get_now_playing_tmdb
    xbmcplugin.setPluginCategory(_HANDLE, f"Acum în cinematografe (Pagina {page})")
    _populate_filtered_list(
        "movie",
        api_func,
        {},
        page,
        {"action": "list_now_playing", "media_type": "movie"},
    )


def list_airing_today():
    page = int(_ARGS.get("page", "1"))
    api_func = client.get_airing_today_tv_tmdb
    xbmcplugin.setPluginCategory(_HANDLE, f"Azi la TV (Pagina {page})")
    _populate_filtered_list(
        "tv",
        api_func,
        {},
        page,
        {"action": "list_airing_today", "media_type": "tv"},
    )


def list_on_the_air():
    page = int(_ARGS.get("page", "1"))
    api_func = client.get_on_the_air_tv_tmdb
    xbmcplugin.setPluginCategory(_HANDLE, f"În difuzare (Pagina {page})")
    _populate_filtered_list(
        "tv",
        api_func,
        {},
        page,
        {"action": "list_on_the_air", "media_type": "tv"},
    )


def list_decades():
    media_type = _ARGS.get("media_type")
    xbmcplugin.setPluginCategory(_HANDLE, "Selectați Deceniul")
    decades = [2020, 2010, 2000, 1990, 1980]
    for decade in decades:
        li = xbmcgui.ListItem(f"{decade}s")
        li.setArt({"icon": "DefaultYear.png"})
        params = {
            "action": "list_by_decade",
            "media_type": media_type,
            "decade": str(decade),
        }
        url = f"{_BASE_URL}?{urlencode(params)}"
        xbmcplugin.addDirectoryItem(handle=_HANDLE, url=url, listitem=li, isFolder=True)
    xbmcplugin.endOfDirectory(_HANDLE)


def list_by_decade():
    media_type = _ARGS.get("media_type")
    decade = _ARGS.get("decade")
    page = int(_ARGS.get("page", "1"))
    if not decade:
        return
    year_start = int(decade)
    year_end = year_start + 9
    api_func = (
        client.get_tv_by_year_tmdb
        if media_type == "tv"
        else client.get_movies_by_year_tmdb
    )
    xbmcplugin.setPluginCategory(_HANDLE, f"{decade}s (Pagina {page})")
    _populate_filtered_list(
        media_type,
        api_func,
        {"year_start": year_start, "year_end": year_end},
        page,
        {"action": "list_by_decade", "media_type": media_type, "decade": decade},
    )


def list_years():
    media_type = _ARGS.get("media_type")
    xbmcplugin.setPluginCategory(_HANDLE, "Selectați Anul")
    current_year = datetime.datetime.now().year
    for year in range(current_year, 1980 - 1, -1):
        li = xbmcgui.ListItem(str(year))
        li.setArt({"icon": "DefaultYear.png"})
        params = {"action": "list_by_year", "media_type": media_type, "year": str(year)}
        url = f"{_BASE_URL}?{urlencode(params)}"
        xbmcplugin.addDirectoryItem(handle=_HANDLE, url=url, listitem=li, isFolder=True)
    xbmcplugin.endOfDirectory(_HANDLE)


def list_by_year():
    media_type = _ARGS.get("media_type")
    year = _ARGS.get("year")
    page = int(_ARGS.get("page", "1"))
    if not year:
        return
    api_func = (
        client.get_tv_by_year_tmdb
        if media_type == "tv"
        else client.get_movies_by_year_tmdb
    )
    xbmcplugin.setPluginCategory(_HANDLE, f"Din anul {year} (Pagina {page})")
    _populate_filtered_list(
        media_type,
        api_func,
        {"year": year},
        page,
        {"action": "list_by_year", "media_type": media_type, "year": year},
    )


def list_genres():
    media_type = _ARGS.get("media_type")
    xbmcplugin.setPluginCategory(_HANDLE, "Selectați Genul")
    api_func = (
        client.get_tv_genres_tmdb if media_type == "tv" else client.get_genres_tmdb
    )
    data = api_func()
    if data and "genres" in data:
        for genre in data["genres"]:
            li = xbmcgui.ListItem(genre["name"])
            li.setArt({"icon": "DefaultGenre.png"})
            params = {
                "action": "list_by_genre",
                "media_type": media_type,
                "genre_id": genre["id"],
                "genre_name": genre["name"],
            }
            url = f"{_BASE_URL}?{urlencode(params)}"
            xbmcplugin.addDirectoryItem(
                handle=_HANDLE, url=url, listitem=li, isFolder=True
            )
    xbmcplugin.endOfDirectory(_HANDLE)


def list_by_genre():
    media_type = _ARGS.get("media_type")
    genre_id = _ARGS.get("genre_id")
    genre_name = _ARGS.get("genre_name", "Gen necunoscut")
    page = int(_ARGS.get("page", "1"))
    if not genre_id:
        return
    api_func = (
        client.get_tv_by_genre_tmdb
        if media_type == "tv"
        else client.get_movies_by_genre_tmdb
    )
    xbmcplugin.setPluginCategory(_HANDLE, f'Genul "{genre_name}" (Pagina {page})')
    next_params = {
        "action": "list_by_genre",
        "media_type": media_type,
        "genre_id": genre_id,
        "genre_name": genre_name,
    }
    _populate_filtered_list(
        media_type, api_func, {"genre_id": genre_id}, page, next_params
    )


def search():
    media_type = _ARGS.get("media_type")
    keyboard = xbmc.Keyboard("", f"Introduceți termenul de căutare pentru {media_type}")
    keyboard.doModal()
    if keyboard.isConfirmed() and keyboard.getText():
        query = keyboard.getText()
        params = {
            "action": "list_search_results",
            "media_type": media_type,
            "query": query,
        }
        xbmc.executebuiltin(f"Container.Update({_BASE_URL}?{urlencode(params)})")


def list_search_results():
    media_type = _ARGS.get("media_type")
    query = _ARGS.get("query")
    page = int(_ARGS.get("page", "1"))
    if not query:
        return
    api_func = client.search_tv_tmdb if media_type == "tv" else client.search_tmdb
    xbmcplugin.setPluginCategory(
        _HANDLE, f'Rezultate căutare pentru "{query}" (Pagina {page})'
    )
    next_params = {
        "action": "list_search_results",
        "media_type": media_type,
        "query": query,
    }
    _populate_filtered_list(media_type, api_func, {"query": query}, page, next_params)


# --- TV Show Specific Listing ---
def list_seasons():
    tv_show_id = int(_ARGS.get("tv_show_id"))
    title = _ARGS.get("title")
    xbmcplugin.setPluginCategory(_HANDLE, title)

    show_details = client.get_tv_details_tmdb(tv_show_id)
    if not show_details or "seasons" not in show_details:
        xbmcplugin.endOfDirectory(_HANDLE)
        return

    available_seasons = get_episode_info().get(str(tv_show_id), {})

    for season_summary in show_details["seasons"]:
        season_number = season_summary.get("season_number")
        if season_number in available_seasons:
            item = _create_season_item(tv_show_id, season_summary)
            if item:
                xbmcplugin.addDirectoryItem(
                    handle=_HANDLE, url=item[0], listitem=item[1], isFolder=item[2]
                )

    xbmcplugin.endOfDirectory(_HANDLE)


def list_episodes():
    tv_show_id = int(_ARGS.get("tv_show_id"))
    season_number = int(_ARGS.get("season_number"))
    xbmcplugin.setPluginCategory(_HANDLE, f"Sezonul {season_number}")
    xbmcplugin.setContent(_HANDLE, "episodes")

    season_details = client.get_season_details_tmdb(tv_show_id, season_number)
    if not season_details or "episodes" not in season_details:
        xbmcplugin.endOfDirectory(_HANDLE)
        return

    available_episodes = (
        get_episode_info().get(str(tv_show_id), {}).get(season_number, set())
    )

    for episode_details in season_details["episodes"]:
        episode_number = episode_details.get("episode_number")
        if episode_number in available_episodes:
            item = _create_episode_item(tv_show_id, episode_details)
            if item:
                xbmcplugin.addDirectoryItem(
                    handle=_HANDLE, url=item[0], listitem=item[1], isFolder=item[2]
                )

    xbmcplugin.endOfDirectory(_HANDLE)


def list_trending():
    xbmcplugin.setPluginCategory(_HANDLE, "În Trend")
    xbmcplugin.setContent(_HANDLE, "movies")

    data = client.get_trending_movies()
    if not data or not data.get("results"):
        xbmcgui.Dialog().notification(
            "MIAF",
            "Nu s-au putut încărca filmele în trend.",
            xbmcgui.NOTIFICATION_WARNING,
        )
        xbmcplugin.endOfDirectory(_HANDLE)
        return

    local_ids = get_movie_ids()
    for details in data["results"][:50]:
        tmdb_id = str(details.get("id"))
        if tmdb_id in local_ids:
            title = details.get("title", "Necunoscut")
            poster = (
                f"{IMG_BASE_URL}w500{details.get('poster_path')}"
                if details.get("poster_path")
                else ""
            )

            li = xbmcgui.ListItem(title)
            li.setArt(
                {
                    "poster": poster,
                    "fanart": f"{IMG_BASE_URL}original{details.get('backdrop_path')}"
                    if details.get("backdrop_path")
                    else "",
                }
            )
            li.setInfo("video", {"title": title, "mediatype": "movie"})

            is_fav = client.is_favorite(tmdb_id, "movie")
            if is_fav:
                li.addContextMenuItems(
                    [
                        (
                            "Elimina din favorite",
                            f"RunPlugin({_BASE_URL}?action=toggle_favorite&media_type=movie&tmdb_id={tmdb_id}&title={title})",
                        )
                    ]
                )
            else:
                li.addContextMenuItems(
                    [
                        (
                            "Adauga la favorite",
                            f"RunPlugin({_BASE_URL}?action=toggle_favorite&media_type=movie&tmdb_id={tmdb_id}&title={title})",
                        )
                    ]
                )

            params = {
                "action": "play",
                "media_type": "movie",
                "tmdb_id": tmdb_id,
                "title": title,
            }
            url = f"{_BASE_URL}?{urlencode(params)}"
        xbmcplugin.addDirectoryItem(
            handle=_HANDLE, url=url, listitem=li, isFolder=False
        )

    xbmcplugin.endOfDirectory(_HANDLE)


def list_collections():
    xbmcplugin.setPluginCategory(_HANDLE, "Colecții")
    xbmcplugin.setContent(_HANDLE, "movies")

    log("Loading collections...")
    data = client.get_movie_collections()
    log(f"Collections data: {data}")

    if not data:
        xbmcgui.Dialog().notification(
            "MIAF", "Eroare la încărcarea colecțiilor.", xbmcgui.NOTIFICATION_WARNING
        )
        xbmcplugin.endOfDirectory(_HANDLE)
        return

    results = data.get("results", [])
    log(f"Found {len(results)} collections")

    if not results:
        xbmcgui.Dialog().notification(
            "MIAF", "Nu există colecții disponibile.", xbmcgui.NOTIFICATION_INFO
        )
        xbmcplugin.endOfDirectory(_HANDLE)
        return

    for details in results[:50]:
        title = details.get("name", "Colecție necunoscută")
        poster = (
            f"{IMG_BASE_URL}w500{details.get('poster_path')}"
            if details.get("poster_path")
            else ""
        )

        li = xbmcgui.ListItem(title)
        li.setArt(
            {
                "poster": poster,
                "fanart": f"{IMG_BASE_URL}original{details.get('backdrop_path')}"
                if details.get("backdrop_path")
                else "",
            }
        )
        li.setInfo("video", {"title": title, "mediatype": "movie"})

        is_fav = client.is_favorite(str(details.get("id")), "movie")
        if is_fav:
            li.addContextMenuItems(
                [
                    (
                        "Elimina din favorite",
                        f"RunPlugin({_BASE_URL}?action=toggle_favorite&media_type=movie&tmdb_id={details.get('id')}&title={title})",
                    )
                ]
            )
        else:
            li.addContextMenuItems(
                [
                    (
                        "Adauga la favorite",
                        f"RunPlugin({_BASE_URL}?action=toggle_favorite&media_type=movie&tmdb_id={details.get('id')}&title={title})",
                    )
                ]
            )

        params = {
            "action": "play",
            "media_type": "movie",
            "tmdb_id": details.get("id"),
            "title": title,
        }
        url = f"{_BASE_URL}?{urlencode(params)}"
        xbmcplugin.addDirectoryItem(
            handle=_HANDLE, url=url, listitem=li, isFolder=False
        )

    xbmcplugin.endOfDirectory(_HANDLE)


def list_networks():
    xbmcplugin.setPluginCategory(_HANDLE, "Rețele TV / Streaming")
    data = client.get_tv_networks()
    if not data or "results" not in data:
        xbmcgui.Dialog().notification(
            "MIAF", "Nu s-au putut încărca rețelele.", xbmcgui.NOTIFICATION_WARNING
        )
        xbmcplugin.endOfDirectory(_HANDLE)
        return

    for network in data.get("results", []):
        name = network.get("name", "Unknown")
        li = xbmcgui.ListItem(name)
        li.setArt({"icon": "DefaultTVShows.png"})
        li.setInfo("video", {"title": name, "mediatype": "tvshow"})
        params = {
            "action": "list_by_network",
            "network_id": network.get("id"),
            "network_name": name,
        }
        url = f"{_BASE_URL}?{urlencode(params)}"
        xbmcplugin.addDirectoryItem(handle=_HANDLE, url=url, listitem=li, isFolder=True)

    xbmcplugin.endOfDirectory(_HANDLE)


def list_by_network():
    network_id = _ARGS.get("network_id")
    network_name = _ARGS.get("network_name", "Unknown")
    page = int(_ARGS.get("page", "1"))
    if not network_id:
        return

    xbmcplugin.setPluginCategory(_HANDLE, f"Rețeaua {network_name}")
    _populate_filtered_list(
        "tv",
        client.get_tv_by_network_tmdb,
        {"network_id": network_id},
        page,
        {
            "action": "list_by_network",
            "network_id": network_id,
            "network_name": network_name,
        },
    )


def search_person():
    keyboard = xbmc.Keyboard("", "Caută actor sau regizor")
    keyboard.doModal()
    if keyboard.isConfirmed() and keyboard.getText():
        query = keyboard.getText()
        params = {"action": "list_person_results", "query": query}
        xbmc.executebuiltin(f"Container.Update({_BASE_URL}?{urlencode(params)})")


def list_person_results():
    query = _ARGS.get("query")
    page = int(_ARGS.get("page", "1"))
    if not query:
        return

    xbmcplugin.setPluginCategory(_HANDLE, f'Rezultate pentru "{query}"')
    data = client.search_person_tmdb(query, page)
    if not data or not data.get("results"):
        xbmcgui.Dialog().notification(
            "MIAF", "Nu s-au găsit rezultate.", xbmcgui.NOTIFICATION_INFO
        )
        xbmcplugin.endOfDirectory(_HANDLE)
        return

    for person in data.get("results", [])[:20]:
        name = person.get("name", "Unknown")
        profile_path = person.get("profile_path")
        thumb = f"{IMG_BASE_URL}w185{profile_path}" if profile_path else ""

        known_for = person.get("known_for", [])
        media_type = (
            "tv" if known_for and known_for[0].get("media_type") == "tv" else "movie"
        )

        li = xbmcgui.ListItem(name)
        li.setArt({"thumb": thumb})
        li.setInfo("video", {"title": name, "mediatype": "video"})

        params = {
            "action": "list_person_credits",
            "person_id": person.get("id"),
            "person_name": name,
        }
        url = f"{_BASE_URL}?{urlencode(params)}"
        xbmcplugin.addDirectoryItem(handle=_HANDLE, url=url, listitem=li, isFolder=True)

    xbmcplugin.endOfDirectory(_HANDLE)


def list_person_credits():
    person_id = _ARGS.get("person_id")
    person_name = _ARGS.get("person_name", "Unknown")
    xbmcplugin.setPluginCategory(_HANDLE, f"Filmografie: {person_name}")
    xbmcplugin.setContent(_HANDLE, "movies")

    local_movie_ids = get_movie_ids()
    local_tv_ids = get_tv_ids()

    movies_data = client.get_person_movies_tmdb(person_id)
    tv_data = client.get_person_tv_tmdb(person_id)

    for movie in (movies_data.get("cast", []) if movies_data else [])[:20]:
        tmdb_id = str(movie.get("id"))
        if tmdb_id in local_movie_ids:
            li = xbmcgui.ListItem(movie.get("title", "Unknown"))
            poster = (
                f"{IMG_BASE_URL}w185{movie.get('poster_path')}"
                if movie.get("poster_path")
                else ""
            )
            li.setArt({"poster": poster})
            li.setInfo("video", {"title": movie.get("title"), "mediatype": "movie"})
            params = {
                "action": "play",
                "media_type": "movie",
                "tmdb_id": tmdb_id,
                "title": movie.get("title"),
            }
            url = f"{_BASE_URL}?{urlencode(params)}"
            xbmcplugin.addDirectoryItem(
                handle=_HANDLE, url=url, listitem=li, isFolder=False
            )

    for tv in (tv_data.get("cast", []) if tv_data else [])[:20]:
        tmdb_id = str(tv.get("id"))
        if tmdb_id in local_tv_ids:
            li = xbmcgui.ListItem(tv.get("name", "Unknown"))
            poster = (
                f"{IMG_BASE_URL}w185{tv.get('poster_path')}"
                if tv.get("poster_path")
                else ""
            )
            li.setArt({"poster": poster})
            li.setInfo("video", {"title": tv.get("name"), "mediatype": "tvshow"})
            params = {
                "action": "list_seasons",
                "tv_show_id": tmdb_id,
                "title": tv.get("name"),
            }
            url = f"{_BASE_URL}?{urlencode(params)}"
            xbmcplugin.addDirectoryItem(
                handle=_HANDLE, url=url, listitem=li, isFolder=True
            )

    xbmcplugin.endOfDirectory(_HANDLE)


def list_favorites_menu():
    xbmcplugin.setPluginCategory(_HANDLE, "Favorite")

    li_movies = xbmcgui.ListItem("Filme Favorite")
    li_movies.setArt({"icon": "DefaultMovies.png"})
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE,
        url=f"{_BASE_URL}?action=list_favorites&media_type=movie",
        listitem=li_movies,
        isFolder=True,
    )

    li_tv = xbmcgui.ListItem("Seriale Favorite")
    li_tv.setArt({"icon": "DefaultTVShows.png"})
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE,
        url=f"{_BASE_URL}?action=list_favorites&media_type=tv",
        listitem=li_tv,
        isFolder=True,
    )
    xbmcplugin.endOfDirectory(_HANDLE)


def list_favorites():
    media_type = _ARGS.get("media_type")
    xbmcplugin.setPluginCategory(
        _HANDLE, f"Favorite - {'Filme' if media_type == 'movie' else 'Seriale'}"
    )
    xbmcplugin.setContent(_HANDLE, "movies" if media_type == "movie" else "tvshows")

    favorites = client.get_favorites(media_type)
    if not favorites:
        xbmcgui.Dialog().notification(
            "MIAF", "Nu ai favorite salvate.", xbmcgui.NOTIFICATION_INFO
        )
        xbmcplugin.endOfDirectory(_HANDLE)
        return

    local_ids = get_movie_ids() if media_type == "movie" else get_tv_ids()

    for fav in favorites:
        tmdb_id = fav.get("id")
        if tmdb_id in local_ids:
            if media_type == "movie":
                item = _create_movie_item(
                    {"id": int(tmdb_id), "title": fav.get("title")}
                )
            else:
                item = _create_tv_show_item(
                    {"id": int(tmdb_id), "name": fav.get("title")}
                )
            if item:
                xbmcplugin.addDirectoryItem(
                    handle=_HANDLE, url=item[0], listitem=item[1], isFolder=item[2]
                )

    xbmcplugin.endOfDirectory(_HANDLE)


def toggle_favorite():
    media_type = _ARGS.get("media_type")
    tmdb_id = _ARGS.get("tmdb_id")
    title = _ARGS.get("title", "Unknown")

    if client.is_favorite(tmdb_id, media_type):
        client.remove_favorite(tmdb_id, media_type)
        xbmcgui.Dialog().notification(
            "MIAF", f"Eliminat din favorite: {title}", xbmcgui.NOTIFICATION_INFO
        )
    else:
        client.add_favorite(tmdb_id, media_type, title)
        xbmcgui.Dialog().notification(
            "MIAF", f"Adăugat la favorite: {title}", xbmcgui.NOTIFICATION_INFO
        )

    xbmc.executebuiltin("Container.Refresh()")


# --- Router ---
def router():
    action = _ARGS.get("action", "main_menu")

    # Allow certain actions without API key
    if action in ("toggle_favorite", "list_favorites_menu", "list_favorites"):
        pass  # Allow favorites without API key
    elif not client.get_api_key():
        xbmcgui.Dialog().notification(
            "Vix Movie", "Cheia API TMDb lipsește.", xbmcgui.NOTIFICATION_ERROR
        )
        xbmc.executebuiltin("Addon.OpenSettings(plugin.video.vixmovie)")
        return

    actions = {
        "play": play_media,
        "main_menu": list_main_menu,
        "list_search_menu": list_search_menu,
        "list_movies_menu": list_movies_menu,
        "list_tv_menu": list_tv_menu,
        "list_popular": list_popular,
        "list_top_rated": list_top_rated,
        "list_upcoming": list_upcoming,
        "list_now_playing": list_now_playing,
        "list_airing_today": list_airing_today,
        "list_on_the_air": list_on_the_air,
        "list_decades": list_decades,
        "list_by_decade": list_by_decade,
        "list_years": list_years,
        "list_by_year": list_by_year,
        "list_genres": list_genres,
        "list_by_genre": list_by_genre,
        "search": search,
        "list_search_results": list_search_results,
        "list_seasons": list_seasons,
        "list_episodes": list_episodes,
        "list_trending": list_trending,
        "list_collections": list_collections,
        "list_networks": list_networks,
        "list_by_network": list_by_network,
        "search_person": search_person,
        "list_person_results": list_person_results,
        "list_person_credits": list_person_credits,
        "list_favorites_menu": list_favorites_menu,
        "list_favorites": list_favorites,
        "toggle_favorite": toggle_favorite,
    }

    if action in actions:
        actions[action]()
    else:
        list_main_menu()

    # Persist any new cache entries to disk exactly once per plugin invocation
    client.flush_cache()


if __name__ == "__main__":
    router()
