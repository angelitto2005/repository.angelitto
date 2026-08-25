import os
import time
from concurrent.futures import (
    ThreadPoolExecutor,
    TimeoutError as FuturesTimeoutError,
    as_completed,
)
from urllib.parse import quote_plus, urlencode

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

_SEARCH_CACHE_TTL = 120
_MEGA_SEARCH_MAX_WORKERS = 8
_MEGA_SEARCH_SERVER_TIMEOUT = 10
_search_cache = {}


def _get_saved_searches_file():
    addon = xbmcaddon.Addon()
    profile_path = addon.getAddonInfo("profile")
    try:
        resolved = xbmcvfs.translatePath(profile_path)
    except Exception:
        resolved = xbmc.translatePath(profile_path)

    if not os.path.exists(resolved):
        os.makedirs(resolved)
    return os.path.join(resolved, "saved_searches.json")


def load_saved_searches():
    try:
        import json

        with open(_get_saved_searches_file(), "r", encoding="utf-8") as handle:
            saved_searches = json.load(handle)
        return saved_searches if isinstance(saved_searches, list) else []
    except (FileNotFoundError, ValueError, TypeError):
        return []
    except Exception as exc:
        xbmc.log(
            f"[SavedSearches] Failed to load saved searches: {exc}",
            level=xbmc.LOGWARNING,
        )
        return []


def _save_saved_searches(saved_searches):
    import json

    with open(_get_saved_searches_file(), "w", encoding="utf-8") as handle:
        json.dump(saved_searches, handle, ensure_ascii=True, indent=2)


def _saved_search_key(search):
    return (
        (search.get("query") or "").strip().casefold(),
        search.get("search_type") or "",
        search.get("server") or "",
        search.get("main_mode") or "",
    )


def add_saved_search(query, search_type, server="", main_mode=""):
    query = (query or "").strip()
    if not query:
        return

    saved_search = {
        "query": query,
        "search_type": search_type or "live",
        "server": server or "",
        "main_mode": main_mode or "",
    }
    saved_searches = load_saved_searches()
    if _saved_search_key(saved_search) in {
        _saved_search_key(item) for item in saved_searches
    }:
        xbmcgui.Dialog().notification(
            "Căutări salvate",
            f'"{query}" este deja salvată',
            xbmcgui.NOTIFICATION_INFO,
            2000,
        )
        return

    saved_searches.append(saved_search)
    try:
        _save_saved_searches(saved_searches)
    except Exception as exc:
        xbmc.log(
            f"[SavedSearches] Failed to save search: {exc}",
            level=xbmc.LOGERROR,
        )
        xbmcgui.Dialog().notification(
            "Căutări salvate",
            "Căutarea nu a putut fi salvată",
            xbmcgui.NOTIFICATION_ERROR,
            2500,
        )
        return

    xbmcgui.Dialog().notification(
        "Căutări salvate",
        f'"{query}" a fost salvată',
        xbmcgui.NOTIFICATION_INFO,
        2000,
    )
    xbmc.executebuiltin("Container.Refresh")


def remove_saved_search(query, search_type, server="", main_mode=""):
    target = {
        "query": query or "",
        "search_type": search_type or "live",
        "server": server or "",
        "main_mode": main_mode or "",
    }
    saved_searches = load_saved_searches()
    remaining = [
        item
        for item in saved_searches
        if _saved_search_key(item) != _saved_search_key(target)
    ]
    if len(remaining) == len(saved_searches):
        return

    try:
        _save_saved_searches(remaining)
    except Exception as exc:
        xbmc.log(
            f"[SavedSearches] Failed to remove saved search: {exc}",
            level=xbmc.LOGERROR,
        )
        return

    xbmcgui.Dialog().notification(
        "Căutări salvate",
        f'"{query}" a fost ștearsă',
        xbmcgui.NOTIFICATION_INFO,
        2000,
    )
    xbmc.executebuiltin("Container.Refresh")


def _build_saved_search_url(base_url, search):
    search_type = search.get("search_type") or "live"
    params = {"query": search.get("query") or ""}

    if search_type.startswith("mega_"):
        params["mode"] = "mega_search_results"
        params["search_type"] = search_type[5:]
    elif search_type == "vod":
        params["mode"] = "search_results_vod"
        params["server"] = search.get("server") or "server1"
    elif search_type == "series":
        params["mode"] = "search_results_series"
        params["server"] = search.get("server") or "server1"
    else:
        params["mode"] = "search_results"
        params["server"] = search.get("server") or "server1"
        if search.get("main_mode"):
            params["main_mode"] = search["main_mode"]

    return f"{base_url}?{urlencode(params)}"


def list_saved_searches(base_url, handle):
    xbmcplugin.setPluginCategory(handle, "Căutări salvate")
    saved_searches = load_saved_searches()
    if not saved_searches:
        li = xbmcgui.ListItem(
            label="[COLOR yellow]Nu există căutări salvate.[/COLOR]"
        )
        xbmcplugin.addDirectoryItem(handle=handle, url="", listitem=li, isFolder=False)
        xbmcplugin.endOfDirectory(handle)
        return

    labels = {
        "live": "Live",
        "vod": "Film",
        "series": "Serial",
        "mega_live": "Mega Live",
        "mega_vod": "Mega Filme",
        "mega_series": "Mega Seriale",
    }
    for search in saved_searches:
        query = search.get("query") or ""
        search_type = search.get("search_type") or "live"
        server = search.get("server") or ""
        suffix = labels.get(search_type, search_type)
        if server:
            suffix = f"{suffix}, {server}"

        li = xbmcgui.ListItem(label=f'{query} [COLOR gray]({suffix})[/COLOR]')
        li.setArt(
            {"icon": "DefaultAddonsSearch.png", "thumb": "DefaultAddonsSearch.png"}
        )
        remove_params = {
            "mode": "remove_saved_search",
            "query": query,
            "search_type": search_type,
            "server": server,
            "main_mode": search.get("main_mode") or "",
        }
        li.addContextMenuItems(
            [
                (
                    "Șterge căutarea salvată",
                    f"RunPlugin({base_url}?{urlencode(remove_params)})",
                )
            ]
        )
        xbmcplugin.addDirectoryItem(
            handle=handle,
            url=_build_saved_search_url(base_url, search),
            listitem=li,
            isFolder=True,
        )

    xbmcplugin.endOfDirectory(handle)


def _add_save_search_item(
    base_url, handle, query, search_type, server="", main_mode=""
):
    params = {
        "mode": "add_saved_search",
        "query": query or "",
        "search_type": search_type or "live",
        "server": server or "",
        "main_mode": main_mode or "",
    }
    li = xbmcgui.ListItem(label="[COLOR gold]Salvează această căutare[/COLOR]")
    li.setArt(
        {"icon": "DefaultFavourites.png", "thumb": "DefaultFavourites.png"}
    )
    xbmcplugin.addDirectoryItem(
        handle=handle,
        url=f"{base_url}?{urlencode(params)}",
        listitem=li,
        isFolder=False,
    )


def _get_search_cache_file():
    addon = xbmcaddon.Addon()
    profile_path = addon.getAddonInfo("profile")
    try:
        resolved = xbmcvfs.translatePath(profile_path)
    except Exception:
        resolved = xbmc.translatePath(profile_path)

    if not os.path.exists(resolved):
        os.makedirs(resolved)
    return os.path.join(resolved, "search_cache.json")


def _load_persisted_search_cache():
    cache_file = _get_search_cache_file()
    try:
        if not os.path.exists(cache_file):
            return
        import json

        with open(cache_file, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            return
        now = time.time()
        for raw_key, entry in payload.items():
            if not isinstance(entry, dict):
                continue
            timestamp = float(entry.get("timestamp", 0) or 0)
            if not timestamp or (now - timestamp) >= _SEARCH_CACHE_TTL:
                continue
            try:
                server, type_param, query = raw_key.split("||", 2)
            except ValueError:
                continue
            _search_cache[(server, type_param, query)] = entry
    except Exception as exc:
        xbmc.log(f"[SearchCache] Failed to load persisted cache: {exc}", level=xbmc.LOGWARNING)


def _persist_search_cache():
    cache_file = _get_search_cache_file()
    try:
        import json

        payload = {}
        now = time.time()
        for key, entry in list(_search_cache.items()):
            timestamp = float(entry.get("timestamp", 0) or 0)
            if not timestamp or (now - timestamp) >= _SEARCH_CACHE_TTL:
                _search_cache.pop(key, None)
                continue
            payload["||".join(key)] = entry
        with open(cache_file, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True)
    except Exception as exc:
        xbmc.log(f"[SearchCache] Failed to persist cache: {exc}", level=xbmc.LOGWARNING)


_load_persisted_search_cache()


def _search_cache_key(server, type_param, query):
    return (server or "", type_param or "", (query or "").strip().lower())


def _get_cached_search_results(server, type_param, query):
    cache_key = _search_cache_key(server, type_param, query)
    entry = _search_cache.get(cache_key)
    if not entry:
        return None
    if (time.time() - entry.get("timestamp", 0)) >= _SEARCH_CACHE_TTL:
        _search_cache.pop(cache_key, None)
        _persist_search_cache()
        return None
    return entry.get("results")


def _set_cached_search_results(server, type_param, query, results):
    _search_cache[_search_cache_key(server, type_param, query)] = {
        "results": results,
        "timestamp": time.time(),
    }
    _persist_search_cache()


def clear_search_cache(server=None):
    if server is None:
        _search_cache.clear()
        cache_file = _get_search_cache_file()
        try:
            if os.path.exists(cache_file):
                os.remove(cache_file)
        except Exception as exc:
            xbmc.log(
                f"[SearchCache] Failed to clear search cache: {exc}",
                level=xbmc.LOGWARNING,
            )
        return

    for cache_key in list(_search_cache):
        cache_server = cache_key[0] if cache_key else ""
        if cache_server in (server, "mega_search"):
            _search_cache.pop(cache_key, None)
    _persist_search_cache()


def _dedupe_search_results(items, search_type):
    unique_items = []
    seen = set()

    for item in items or []:
        server_id = item.get("_server_id") or item.get("server") or ""
        if search_type == "live":
            cmd = item.get("cmd", "")
            item_id = item.get("id") or item.get("stream_id") or cmd
        else:
            item_id = item.get("id") or item.get("movie_id") or item.get("name")

        dedupe_key = (server_id, str(item_id))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        unique_items.append(item)

    return unique_items


def _copy_item_with_server(item, server_name, server_id):
    copied = dict(item or {})
    copied["_server_name"] = server_name
    copied["_server_id"] = server_id
    return copied


def _load_live_channels_from_cache(server_id, load_channels_cache_fn, cache_ttl):
    if not server_id or not load_channels_cache_fn:
        return []

    try:
        cached = load_channels_cache_fn(server_id)
    except Exception as exc:
        xbmc.log(
            f"[MegaSearch] Failed to inspect channels cache for {server_id}: {exc}",
            level=xbmc.LOGWARNING,
        )
        return []

    if not cached:
        xbmc.log(
            f"[MegaSearch] No channels cache found for {server_id}",
            level=xbmc.LOGDEBUG,
        )
        return []

    timestamp = float(cached.get("timestamp", 0) or 0)
    channels = cached.get("channels") or []
    if not channels:
        xbmc.log(
            f"[MegaSearch] Empty channels cache for {server_id}",
            level=xbmc.LOGDEBUG,
        )
        return []

    import time

    age = time.time() - timestamp
    if age >= float(cache_ttl or 0):
        xbmc.log(
            f"[MegaSearch] Channels cache expired for {server_id} ({int(age)}s)",
            level=xbmc.LOGDEBUG,
        )
        return []

    xbmc.log(
        f"[MegaSearch] Using cached channel list for local search on {server_id}",
        level=xbmc.LOGDEBUG,
    )
    return channels


def _build_allowed_category_ids(
    server,
    main_mode,
    fetch_server_categories_fn,
    get_romanian_categories_fn,
    get_sport_categories_fn,
):
    if not main_mode or main_mode == "world":
        return None

    try:
        all_categories = fetch_server_categories_fn(server)
    except Exception as exc:
        xbmc.log(
            f"[Search] Failed to load categories for mode filtering on {server}: {exc}",
            level=xbmc.LOGWARNING,
        )
        return None

    if not all_categories:
        return set()

    if main_mode == "sport":
        filtered_categories = get_sport_categories_fn(all_categories)
    else:
        filtered_categories = get_romanian_categories_fn(all_categories)
    return {
        str(cat.get("id"))
        for cat in filtered_categories or []
        if cat.get("id") is not None and cat.get("id") != ""
    }


def _filter_live_results_by_mode(items, allowed_category_ids):
    if allowed_category_ids is None:
        return list(items or [])
    if not allowed_category_ids:
        return []
    return [
        item
        for item in items or []
        if str(item.get("tv_genre_id", "")) in allowed_category_ids
    ]


def _search_live_channels_locally(
    query,
    server,
    server_name,
    load_channels_cache_fn,
    load_cached_category_channels_fn,
    channels_cache_ttl,
    allowed_category_ids=None,
    return_cache_status=False,
):
    search_term_lower = (query or "").lower()
    all_channels = _load_live_channels_from_cache(
        server, load_channels_cache_fn, channels_cache_ttl
    )
    if not all_channels and load_cached_category_channels_fn:
        try:
            all_channels = load_cached_category_channels_fn(
                server,
                allowed_category_ids=allowed_category_ids,
                cache_ttl=channels_cache_ttl,
            )
        except Exception as exc:
            xbmc.log(
                f"[MegaSearch] Failed to inspect category channel caches for {server}: {exc}",
                level=xbmc.LOGWARNING,
            )
            all_channels = []
    if not all_channels:
        return ([], False) if return_cache_status else []

    filtered_channels = _filter_live_results_by_mode(all_channels, allowed_category_ids)
    matches = []
    for item in filtered_channels:
        name = item.get("name", "")
        if name and search_term_lower in name.lower():
            matches.append(_copy_item_with_server(item, server_name, server))
    return (matches, True) if return_cache_status else matches


def mega_search_menu(base_url, handle):
    items = [
        ("Căutări salvate", "saved", "DefaultFavourites.png"),
        ("Cauta Live", "live", "DefaultAddonPVRClient.png"),
        ("Cauta Filme", "vod", "DefaultMovies.png"),
        ("Cauta Seriale", "series", "DefaultTVShows.png"),
        (
            "[COLOR yellow]Verifică indexul ratb[/COLOR]",
            "reindex_ratb",
            "DefaultAddonService.png",
        ),
    ]

    for label, search_type, icon in items:
        li = xbmcgui.ListItem(label=label)
        li.setArt({"icon": icon, "thumb": icon})
        if search_type == "saved":
            url = f"{base_url}?mode=saved_searches"
            is_folder = True
        elif search_type == "reindex_ratb":
            url = f"{base_url}?mode=reindex_ratb"
            is_folder = False
        else:
            url = f"{base_url}?mode=mega_search_input&search_type={search_type}"
            is_folder = False
        xbmcplugin.addDirectoryItem(
            handle=handle, url=url, listitem=li, isFolder=is_folder
        )

    xbmcplugin.endOfDirectory(handle)


def mega_search_input(base_url, search_type):
    xbmc.executebuiltin("Dialog.Close(all,true)")
    labels = {"live": "Canal Live", "vod": "Film", "series": "Serial"}
    search_term = xbmcgui.Dialog().input(
        f"Mega Cautare {labels.get(search_type)}", type=xbmcgui.INPUT_ALPHANUM
    )

    if search_term:
        url = (
            f"{base_url}?mode=mega_search_results&query={quote_plus(search_term)}"
            f"&search_type={search_type}"
        )
        xbmc.executebuiltin(f"Container.Update({url})")


def fetch_stalker_search(
    type_param,
    query,
    server,
    get_server_auth,
    get_session,
    timeouts,
    json_loads,
):
    cached_results = _get_cached_search_results(server, type_param, query)
    if cached_results is not None:
        xbmc.log(
            f"[Stalker] Using cached search results for {server}/{type_param}/{query}",
            level=xbmc.LOGDEBUG,
        )
        return cached_results

    xbmc.log(
        f"[Stalker] Search request: server={server}, type={type_param}, query={query}",
        level=xbmc.LOGINFO,
    )

    token, headers, cookies, portal_url, random_val = get_server_auth(server)
    if not token or not portal_url:
        xbmc.log(
            f"[Stalker] No auth for {server}, returning empty", level=xbmc.LOGWARNING
        )
        return []

    url = f"{portal_url}/portal.php"
    params = {
        "type": type_param,
        "action": "search",
        "q": query,
        "token": token,
        "JsHttpRequest": "1-xml",
    }

    try:
        session = get_session()
        session.cookies.clear()

        response = session.get(
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=timeouts["play"],
            verify=False,
        )


        if response.status_code != 200:
            xbmc.log(
                f"[Stalker] Server {server} returned status {response.status_code} for {type_param} search",
                level=xbmc.LOGWARNING,
            )
            return []

        raw_text = response.text
        if not raw_text or len(raw_text.strip()) < 5:
            xbmc.log(
                f"[Stalker] Response too short from {server} for {type_param}: '{raw_text[:100] if raw_text else 'empty'}'",
                level=xbmc.LOGWARNING,
            )

            if type_param in ["vod", "series"]:
                xbmc.log(
                    f"[Stalker] Trying fallback get_ordered_list search for {type_param} on {server}",
                    level=xbmc.LOGINFO,
                )
                fallback_params = {
                    "type": type_param,
                    "action": "get_ordered_list",
                    "search": query,
                    "token": token,
                    "JsHttpRequest": "1-xml",
                }
                try:
                    response = session.get(
                        url,
                        params=fallback_params,
                        headers=headers,
                        cookies=cookies,
                        timeout=timeouts["channels"],
                    )
                    if response.status_code == 200 and response.text and len(
                        response.text.strip()
                    ) >= 5:
                        raw_text = response.text
                        xbmc.log(
                            f"[Stalker] Fallback search successful for {server}",
                            level=xbmc.LOGINFO,
                        )
                    else:
                        return []
                except Exception:
                    return []
            else:
                return []

        xbmc.log(
            f"[Stalker] Raw response from {server}: {raw_text[:200]}",
            level=xbmc.LOGDEBUG,
        )

        if "{" in raw_text:
            raw_text = raw_text[raw_text.find("{") :]
        if "}" in raw_text:
            raw_text = raw_text[: raw_text.rfind("}") + 1]

        try:
            data = json_loads(raw_text)
            results = []
            if isinstance(data, dict):
                js_data = data.get("js", {})
                if isinstance(js_data, dict):
                    res_data = js_data.get("data", [])
                    if isinstance(res_data, dict):
                        results = res_data.get("data", [])
                    else:
                        results = res_data
                elif isinstance(js_data, list):
                    results = js_data
            elif isinstance(data, list):
                results = data

            if not isinstance(results, list):
                results = []
            _set_cached_search_results(server, type_param, query, results)
            return results
        except ValueError as exc:
            xbmc.log(
                f"[Stalker] JSON decode failed for {server}: {exc}",
                level=xbmc.LOGERROR,
            )
            return []
    except Exception as exc:
        xbmc.log(
            f"[Stalker] Search failed for {server} ({type_param}): {exc}",
            level=xbmc.LOGWARNING,
        )
        return []


def _shutdown_executor_without_waiting(executor):
    try:
        executor.shutdown(wait=False, cancel_futures=True)
    except TypeError:
        executor.shutdown(wait=False)


def _run_mega_search_call_with_timeout(call, server_id, operation):
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(call)
    try:
        return future.result(timeout=_MEGA_SEARCH_SERVER_TIMEOUT)
    except FuturesTimeoutError:
        future.cancel()
        xbmc.log(
            f"[MegaSearch] Skipping slow server {server_id}: {operation} exceeded "
            f"{_MEGA_SEARCH_SERVER_TIMEOUT}s",
            level=xbmc.LOGWARNING,
        )
        return None
    finally:
        _shutdown_executor_without_waiting(executor)


def show_mega_search_results(
    base_url,
    handle,
    query,
    search_type,
    load_servers_config,
    fetch_stalker_search_fn,
    fetch_channels_by_category_from_server,
    load_channels_cache_fn,
    load_cached_category_channels_fn,
    channels_cache_ttl,
    fetch_missing_channel_lists,
    fetch_batch_size,
    batch_start,
    skip_api_search,
    re_stream_id,
    playlist_search_fn=None,
    search_mode="rapid",
):
    xbmc.log(
        f"[MegaSearch] Starting with query='{query}', search_type='{search_type}'",
        level=xbmc.LOGINFO,
    )

    if not query:
        xbmc.log("[MegaSearch] No query provided, exiting", level=xbmc.LOGWARNING)
        xbmcplugin.endOfDirectory(handle, succeeded=False)
        return

    servers_config = load_servers_config()
    available_servers = servers_config.get("servers", [])
    available_servers_count = len(available_servers)
    fetch_batch_size = max(1, int(fetch_batch_size or 1))
    batch_start = max(0, int(batch_start or 0))
    search_mode = "complete" if search_mode == "complete" else "rapid"
    effective_search_mode = search_mode if search_type == "live" else "complete"

    # Check if we have cached results for this exact search
    cache_key = (
        f"mega_v2_{search_type}_{query}_{batch_start}_{skip_api_search}"
        f"_{effective_search_mode}"
    )
    cached_data = _get_cached_search_results("mega_search", cache_key, query)
    
    if cached_data is not None:
        # Extract results and metadata from cache
        if isinstance(cached_data, dict) and "results" in cached_data:
            cached_results = cached_data.get("results", [])
            cached_servers_count = cached_data.get("servers_count", available_servers_count)
            cached_batch_size = cached_data.get("batch_size", fetch_batch_size)
            
            xbmc.log(
                f"[MegaSearch] Using cached results for '{query}' ({len(cached_results)} items)",
                level=xbmc.LOGINFO,
            )
            # Render cached results directly
            _render_mega_search_results(
                base_url,
                handle,
                query,
                search_type,
                cached_results,
                batch_start,
                skip_api_search,
                re_stream_id,
                available_servers_count=cached_servers_count,
                fetch_batch_size=cached_batch_size,
            )
            return
        else:
            # Old cache format (just results array), use current server info
            xbmc.log(
                f"[MegaSearch] Using cached results (old format) for '{query}' ({len(cached_data)} items)",
                level=xbmc.LOGINFO,
            )
            _render_mega_search_results(
                base_url,
                handle,
                query,
                search_type,
                cached_data,
                batch_start,
                skip_api_search,
                re_stream_id,
                available_servers_count=available_servers_count,
                fetch_batch_size=fetch_batch_size,
            )
            return

    xbmc.log(
        f"[MegaSearch] Found {available_servers_count} servers: {[s.get('id') for s in available_servers]}",
        level=xbmc.LOGINFO,
    )

    if not available_servers:
        li = xbmcgui.ListItem(
            label='[COLOR red]Nu exista servere configurate pentru cautare.[/COLOR]'
        )
        xbmcplugin.addDirectoryItem(handle=handle, url="", listitem=li, isFolder=False)
        xbmcplugin.endOfDirectory(handle)
        return

    type_mapping = {"live": "itv", "vod": "vod", "series": "series"}
    stalker_type = type_mapping.get(search_type, "itv")
    all_results = []
    timed_out_server_ids = set()
    playlist_covered_server_keys = set()

    if search_type == "live" and playlist_search_fn:
        try:
            playlist_results, playlist_covered_server_keys = playlist_search_fn(
                query, available_servers
            )
            all_results.extend(playlist_results or [])
        except Exception as exc:
            xbmc.log(
                f"[MegaSearch] Playlist index failed: {exc}",
                level=xbmc.LOGWARNING,
            )
            playlist_covered_server_keys = set()

    if not skip_api_search and effective_search_mode == "complete":
        dp = xbmcgui.DialogProgress()
        dp.create("Mega Cautare", "Se cauta pe toate serverele...")

        def worker(server):
            server_id = server.get("id")
            server_name = server.get("name", server_id)
            try:
                results = fetch_stalker_search_fn(stalker_type, query, server=server_id)
                xbmc.log(
                    f"[MegaSearch] Got {len(results) if results else 0} results from {server_id}",
                    level=xbmc.LOGINFO,
                )
                if results:
                    return [
                        _copy_item_with_server(item, server_name, server_id)
                        for item in results
                    ]
            except Exception as exc:
                xbmc.log(
                    f"[MegaSearch] Worker failed for {server_id}: {exc}",
                    level=xbmc.LOGWARNING,
                )
            return []

        api_servers = [
            server
            for server in available_servers
            if (
                server.get("id") or "",
                server.get("name") or "",
                (server.get("portal_url") or "").rstrip("/"),
            )
            not in playlist_covered_server_keys
        ]
        max_workers = min(len(api_servers), _MEGA_SEARCH_MAX_WORKERS)
        executor = None
        try:
            future_to_server = {}
            if api_servers:
                executor = ThreadPoolExecutor(max_workers=max_workers or 1)
                future_to_server = {
                    executor.submit(worker, server): server for server in api_servers
                }

            completed = 0
            total = len(api_servers)
            search_timeout = _MEGA_SEARCH_SERVER_TIMEOUT
            try:
                for future in as_completed(future_to_server, timeout=search_timeout):
                    if dp.iscanceled():
                        break

                    result = future.result()
                    if result:
                        all_results.extend(result)

                    completed += 1
                    progress = int((completed / total) * 100)
                    server = future_to_server[future]
                    dp.update(
                        progress,
                        f"Finalizat: [COLOR yellow]{server.get('name')}[/COLOR] ({completed}/{total})",
                    )
            except FuturesTimeoutError:
                slow_servers = []
                for future, server in future_to_server.items():
                    if future.done():
                        continue
                    future.cancel()
                    server_id = server.get("id")
                    if server_id:
                        timed_out_server_ids.add(server_id)
                    slow_servers.append(server.get("name", server_id))

                xbmc.log(
                    f"[MegaSearch] Search timeout after {search_timeout}s; "
                    f"skipping slow servers: {slow_servers}",
                    level=xbmc.LOGWARNING,
                )
        finally:
            if executor is not None:
                _shutdown_executor_without_waiting(executor)
            dp.close()
        all_results = _dedupe_search_results(all_results, search_type)

    next_batch_start = None
    next_batch_count = 0
    if (
        not all_results
        and search_type == "live"
        and effective_search_mode == "complete"
    ):
        if skip_api_search:
            xbmc.log(
                f"[MegaSearch] Continuing sequential live fallback from portal #{batch_start + 1}",
                level=xbmc.LOGINFO,
            )
        else:
            xbmc.log(
                "[MegaSearch] No results from API, trying sequential local/fetch fallback for live",
                level=xbmc.LOGINFO,
            )

        fallback_servers = [
            server
            for server in available_servers
            if (
                server.get("id") or "",
                server.get("name") or "",
                (server.get("portal_url") or "").rstrip("/"),
            )
            not in playlist_covered_server_keys
        ]
        batch_servers = fallback_servers[
            batch_start : batch_start + fetch_batch_size
        ]
        next_batch_start = batch_start + len(batch_servers)
        if next_batch_start < len(fallback_servers):
            next_batch_count = min(
                fetch_batch_size, len(fallback_servers) - next_batch_start
            )
        dp = xbmcgui.DialogProgress()
        dp.create("Mega Căutare", "Se caută secvențial pe portaluri...")
        try:
            total_servers = len(batch_servers) or 1
            for idx, server in enumerate(batch_servers, start=1):
                if dp.iscanceled():
                    break

                server_id = server.get("id")
                server_name = server.get("name", server_id)
                server_key = (
                    server_id or "",
                    server_name or "",
                    (server.get("portal_url") or "").rstrip("/"),
                )
                if server_key in playlist_covered_server_keys:
                    continue
                if server_id in timed_out_server_ids:
                    xbmc.log(
                        f"[MegaSearch] Skipping fallback for timed-out server {server_id}",
                        level=xbmc.LOGWARNING,
                    )
                    continue

                dp.update(
                    int(((idx - 1) / total_servers) * 100),
                    f"Portal {batch_start + idx}: [COLOR yellow]{server_name}[/COLOR] ({idx}/{total_servers})",
                )
                try:
                    matches, had_cache = _search_live_channels_locally(
                        query,
                        server_id,
                        server_name,
                        load_channels_cache_fn,
                        load_cached_category_channels_fn,
                        channels_cache_ttl,
                        return_cache_status=True,
                    )
                    if matches:
                        all_results.extend(matches)
                        continue

                    if not fetch_missing_channel_lists:
                        continue

                    if not had_cache:
                        fetched_channels = _run_mega_search_call_with_timeout(
                            lambda: fetch_channels_by_category_from_server(
                                None, server_id
                            ),
                            server_id,
                            "channel list fetch",
                        )
                        if not fetched_channels:
                            continue
                        matches = _search_live_channels_locally(
                            query,
                            server_id,
                            server_name,
                            load_channels_cache_fn,
                            load_cached_category_channels_fn,
                            channels_cache_ttl,
                        )
                        if matches:
                            all_results.extend(matches)
                except Exception as exc:
                    xbmc.log(
                        f"[MegaSearch] Sequential fallback failed for {server_id}: {exc}",
                        level=xbmc.LOGWARNING,
                    )
        finally:
            dp.close()
        all_results = _dedupe_search_results(all_results, search_type)

    # Cache the results with metadata before rendering
    cache_data = {
        "results": all_results,
        "servers_count": available_servers_count,
        "batch_size": fetch_batch_size,
    }
    _set_cached_search_results("mega_search", cache_key, query, cache_data)
    
    # Render the results
    _render_mega_search_results(
        base_url,
        handle,
        query,
        search_type,
        all_results,
        batch_start,
        skip_api_search,
        re_stream_id,
        next_batch_start=next_batch_start,
        next_batch_count=next_batch_count,
        available_servers_count=available_servers_count,
        fetch_batch_size=fetch_batch_size,
    )


def _render_mega_search_results(
    base_url,
    handle,
    query,
    search_type,
    all_results,
    batch_start,
    skip_api_search,
    re_stream_id,
    next_batch_start=None,
    next_batch_count=None,
    available_servers_count=None,
    fetch_batch_size=None,
):
    """Render mega search results from cached or fresh data."""
    _add_save_search_item(base_url, handle, query, f"mega_{search_type}")
    
    # Calculate next batch info if not provided (for cached results)
    if next_batch_start is None and available_servers_count and fetch_batch_size:
        batch_start = max(0, int(batch_start or 0))
        fetch_batch_size = max(1, int(fetch_batch_size or 1))
        next_batch_start = batch_start + fetch_batch_size
        if next_batch_start < available_servers_count:
            next_batch_count = min(
                fetch_batch_size, available_servers_count - next_batch_start
            )
        else:
            next_batch_count = 0
    
    if not all_results:
        xbmc.log(f"[MegaSearch] No results found for '{query}'", level=xbmc.LOGINFO)
        if search_type == "live" and next_batch_count and next_batch_count > 0 and next_batch_start is not None:
            li = xbmcgui.ListItem(
                label=(
                    f'[COLOR red]Nu s-a gasit nimic pentru "{query}" in lotul curent.[/COLOR]'
                )
            )
            xbmcplugin.addDirectoryItem(handle=handle, url="", listitem=li, isFolder=False)
            next_li = xbmcgui.ListItem(
                label=(
                    f"[COLOR yellow]Continua cautarea in urmatoarele {next_batch_count} portaluri[/COLOR]"
                )
            )
            next_url = (
                f"{base_url}?mode=mega_search_results&query={quote_plus(query)}"
                f"&search_type={search_type}&batch_start={next_batch_start}&skip_api=true"
            )
            xbmcplugin.addDirectoryItem(
                handle=handle, url=next_url, listitem=next_li, isFolder=True
            )
            xbmcplugin.endOfDirectory(handle)
            return

        li = xbmcgui.ListItem(
            label=f'[COLOR red]Nu s-a gasit nimic pentru "{query}" pe niciun server.[/COLOR]'
        )
        xbmcplugin.addDirectoryItem(handle=handle, url="", listitem=li, isFolder=False)
        xbmcplugin.endOfDirectory(handle)
        return

    for item in all_results:
        name = item.get("name", "Unknown")
        server_name = item.get("_server_name")
        server_id = item.get("_server_id")
        display_label = f"{name} - [COLOR cyan]{server_name}[/COLOR]"
        li = xbmcgui.ListItem(label=display_label)

        logo = item.get("logo") or ""
        if logo:
            li.setArt({"thumb": logo, "icon": logo})

        description = item.get("description", "")
        year = item.get("year", "")
        video_info = li.getVideoInfoTag()
        video_info.setTitle(name)
        video_info.setPlot(description)
        if year and year.isdigit():
            video_info.setYear(int(year))

        if search_type == "live":
            cmd = item.get("cmd", "")
            stream_id_match = re_stream_id.search(cmd)
            stream_id = stream_id_match.group(1) if stream_id_match else item.get("id")
            if not stream_id:
                continue
            url = (
                f"{base_url}?mode=play&stream_id={stream_id}"
                f"&name={quote_plus(name)}&server={server_id}"
            )
            li.setProperty("IsPlayable", "true")
            is_folder = False
        elif search_type == "vod":
            movie_id = item.get("id")
            url = f"{base_url}?mode=play_vod&movie_id={movie_id}&server={server_id}"
            li.setProperty("IsPlayable", "true")
            is_folder = False
        else:
            series_id = item.get("id")
            movie_id = str(series_id).split(":")[0] if series_id else ""
            url = (
                f"{base_url}?mode=list_seasons&movie_id={movie_id}&server={server_id}"
            )
            is_folder = True

        xbmcplugin.addDirectoryItem(
            handle=handle, url=url, listitem=li, isFolder=is_folder
        )

    if search_type == "live" and next_batch_count and next_batch_count > 0 and next_batch_start is not None:
        next_li = xbmcgui.ListItem(
            label=(
                f"[COLOR yellow]Continua cautarea in urmatoarele {next_batch_count} portaluri[/COLOR]"
            )
        )
        next_url = (
            f"{base_url}?mode=mega_search_results&query={quote_plus(query)}"
            f"&search_type={search_type}&batch_start={next_batch_start}&skip_api=true"
        )
        xbmcplugin.addDirectoryItem(
            handle=handle, url=next_url, listitem=next_li, isFolder=True
        )

    xbmcplugin.endOfDirectory(handle)


def search_input_dialog(base_url, handle, server="server1", main_mode=None):
    xbmc.executebuiltin("Dialog.Close(all,true)")
    search_term = xbmcgui.Dialog().input("Cauta canal", type=xbmcgui.INPUT_ALPHANUM)
    if search_term:
        xbmcplugin.endOfDirectory(handle)
        xbmc.sleep(200)
        search_url = (
            f"{base_url}?mode=search_results&query={quote_plus(search_term)}"
            f"&server={server}"
        )
        if main_mode:
            search_url += f"&main_mode={quote_plus(main_mode)}"
        xbmc.executebuiltin(f"Container.Update({search_url})")
    else:
        xbmcplugin.endOfDirectory(handle, succeeded=False)


def search_input_dialog_vod(base_url, handle, server="server1"):
    xbmc.executebuiltin("Dialog.Close(all,true)")
    search_term = xbmcgui.Dialog().input("Cauta film", type=xbmcgui.INPUT_ALPHANUM)
    if search_term:
        xbmcplugin.endOfDirectory(handle)
        xbmc.sleep(200)
        search_url = (
            f"{base_url}?mode=search_results_vod&query={quote_plus(search_term)}"
            f"&server={server}"
        )
        xbmc.executebuiltin(f"Container.Update({search_url})")
    else:
        xbmcplugin.endOfDirectory(handle, succeeded=False)


def search_input_dialog_series(base_url, handle, server="server1"):
    xbmc.executebuiltin("Dialog.Close(all,true)")
    search_term = xbmcgui.Dialog().input("Cauta serial", type=xbmcgui.INPUT_ALPHANUM)
    if search_term:
        xbmcplugin.endOfDirectory(handle)
        xbmc.sleep(200)
        search_url = (
            f"{base_url}?mode=search_results_series&query={quote_plus(search_term)}"
            f"&server={server}"
        )
        xbmc.executebuiltin(f"Container.Update({search_url})")
    else:
        xbmcplugin.endOfDirectory(handle, succeeded=False)


def show_search_results(
    base_url,
    handle,
    query,
    server,
    main_mode,
    fetch_stalker_search_fn,
    fetch_server_categories_fn,
    get_romanian_categories_fn,
    get_sport_categories_fn,
    load_channels_cache_fn,
    load_cached_category_channels_fn,
    channels_cache_ttl,
    load_favorite_stream_ids,
    is_epg_enabled,
    epg_contains,
    get_epg_items,
    get_current_program,
    format_epg_tooltip,
    re_stream_id,
):
    if not query:
        xbmcplugin.endOfDirectory(handle, succeeded=False)
        return

    # Check cache first
    cache_key = f"live_{server}_{main_mode or 'all'}"
    cached_channels = _get_cached_search_results(server, cache_key, query)
    
    if cached_channels is not None:
        xbmc.log(
            f"[Search] Using cached live results for '{query}' on {server} ({len(cached_channels)} items)",
            level=xbmc.LOGINFO,
        )
        matching_channels = cached_channels
    else:
        # Perform search
        allowed_category_ids = _build_allowed_category_ids(
            server,
            main_mode,
            fetch_server_categories_fn,
            get_romanian_categories_fn,
            get_sport_categories_fn,
        )

        matching_channels = _filter_live_results_by_mode(
            fetch_stalker_search_fn("itv", query, server), allowed_category_ids
        )
        if not matching_channels:
            dp = xbmcgui.DialogProgress()
            dp.create("Căutare", "Se verifică și lista locală de canale...")
            try:
                matching_channels = _search_live_channels_locally(
                    query,
                    server,
                    "",
                    load_channels_cache_fn,
                    load_cached_category_channels_fn,
                    channels_cache_ttl,
                    allowed_category_ids,
                )
            finally:
                dp.close()

        matching_channels = _dedupe_search_results(matching_channels, "live")
        
        # Cache the results
        _set_cached_search_results(server, cache_key, query, matching_channels)

    xbmcplugin.setPluginCategory(handle, f"Cautare: {query}")
    xbmcplugin.setContent(handle, "videos")
    _add_save_search_item(
        base_url, handle, query, "live", server=server, main_mode=main_mode
    )
    favorite_stream_ids = load_favorite_stream_ids(server)

    for channel in matching_channels:
        name = channel.get("name", "Unknown")
        logo = channel.get("logo") or ""
        cmd = channel.get("cmd", "")

        stream_id_match = re_stream_id.search(cmd)
        stream_id = (
            stream_id_match.group(1) if stream_id_match else channel.get("id")
        )
        if not stream_id:
            continue

        channel_label = name
        plot = ""
        if is_epg_enabled() and epg_contains(stream_id):
            epg_items = get_epg_items(stream_id)
            current_prog = get_current_program(epg_items)
            if current_prog:
                channel_label = f"{name} - {current_prog}"
            plot = format_epg_tooltip(epg_items)

        li = xbmcgui.ListItem(label=channel_label)
        if logo:
            li.setArt({"thumb": logo, "icon": logo})
        li.setProperty("IsPlayable", "true")
        video_info = li.getVideoInfoTag()
        video_info.setTitle(name)
        video_info.setPlot(plot)

        url = (
            f"{base_url}?mode=play&stream_id={stream_id}&name={quote_plus(name)}"
            f"&server={server}&search_query={quote_plus(query)}"
        )

        context_menu = []
        if stream_id in favorite_stream_ids:
            context_menu.append(
                (
                    "Elimină din favorite",
                    f"RunPlugin({base_url}?mode=remove_from_favorites&stream_id={stream_id}&server={server})",
                )
            )
        else:
            add_fav_url = (
                f"{base_url}?mode=add_to_favorites&stream_id={stream_id}"
                f"&name={quote_plus(name)}&logo={quote_plus(logo)}&server={server}"
            )
            context_menu.append(("Adaugă la favorite", f"RunPlugin({add_fav_url})"))
        li.addContextMenuItems(context_menu)

        xbmcplugin.addDirectoryItem(
            handle=handle, url=url, listitem=li, isFolder=False
        )

    if not matching_channels:
        li = xbmcgui.ListItem(
            label=f'[COLOR red]Nu am gasit niciun canal pentru "{query}"[/COLOR]'
        )
        xbmcplugin.addDirectoryItem(handle=handle, url="", listitem=li, isFolder=False)

    xbmcplugin.endOfDirectory(handle)


def show_vod_search_results(base_url, handle, query, server, fetch_stalker_search_fn):
    if not query:
        xbmcplugin.endOfDirectory(handle, succeeded=False)
        return

    # Check cache first
    cache_key = f"vod_{server}"
    cached_items = _get_cached_search_results(server, cache_key, query)
    
    if cached_items is not None:
        xbmc.log(
            f"[Search] Using cached VOD results for '{query}' on {server} ({len(cached_items)} items)",
            level=xbmc.LOGINFO,
        )
        matching_items = cached_items
    else:
        # Perform search
        matching_items = _dedupe_search_results(
            fetch_stalker_search_fn("vod", query, server), "vod"
        )
        
        # Cache the results
        _set_cached_search_results(server, cache_key, query, matching_items)
    
    xbmcplugin.setPluginCategory(handle, f"Cautare Filme: {query}")
    xbmcplugin.setContent(handle, "movies")
    _add_save_search_item(base_url, handle, query, "vod", server=server)

    for item in matching_items:
        name = item.get("name", "Unknown")
        movie_id = item.get("id")
        year = item.get("year", "")
        description = item.get("description", "")

        li = xbmcgui.ListItem(label=f"{name} ({year})")
        li.setProperty("IsPlayable", "true")
        video_info = li.getVideoInfoTag()
        video_info.setTitle(name)
        video_info.setPlot(description)
        video_info.setYear(int(year) if year and year.isdigit() else 0)

        url = (
            f"{base_url}?mode=play_vod&movie_id={movie_id}&server={server}"
            f"&search_query={quote_plus(query)}"
        )
        xbmcplugin.addDirectoryItem(
            handle=handle, url=url, listitem=li, isFolder=False
        )

    if not matching_items:
        li = xbmcgui.ListItem(
            label=f'[COLOR red]Nu am gasit niciun film pentru "{query}"[/COLOR]'
        )
        xbmcplugin.addDirectoryItem(handle=handle, url="", listitem=li, isFolder=False)

    xbmcplugin.endOfDirectory(handle)


def show_series_search_results(base_url, handle, query, server, fetch_stalker_search_fn):
    if not query:
        xbmcplugin.endOfDirectory(handle, succeeded=False)
        return

    # Check cache first
    cache_key = f"series_{server}"
    cached_items = _get_cached_search_results(server, cache_key, query)
    
    if cached_items is not None:
        xbmc.log(
            f"[Search] Using cached series results for '{query}' on {server} ({len(cached_items)} items)",
            level=xbmc.LOGINFO,
        )
        matching_items = cached_items
    else:
        # Perform search
        matching_items = _dedupe_search_results(
            fetch_stalker_search_fn("series", query, server), "series"
        )
        
        # Cache the results
        _set_cached_search_results(server, cache_key, query, matching_items)
    
    xbmcplugin.setPluginCategory(handle, f"Cautare Seriale: {query}")
    xbmcplugin.setContent(handle, "tvshows")
    _add_save_search_item(base_url, handle, query, "series", server=server)

    for item in matching_items:
        name = item.get("name", "Unknown")
        series_id = item.get("id")
        year = item.get("year", "")
        description = item.get("description", "")

        li = xbmcgui.ListItem(label=f"{name} ({year})")
        video_info = li.getVideoInfoTag()
        video_info.setTitle(name)
        video_info.setPlot(description)
        video_info.setYear(int(year) if year and year.isdigit() else 0)

        movie_id = str(series_id).split(":")[0] if series_id else ""
        url = (
            f"{base_url}?mode=list_seasons&movie_id={movie_id}&server={server}"
            f"&search_query={quote_plus(query)}"
        )
        xbmcplugin.addDirectoryItem(handle=handle, url=url, listitem=li, isFolder=True)

    if not matching_items:
        li = xbmcgui.ListItem(
            label=f'[COLOR red]Nu am gasit niciun serial pentru "{query}"[/COLOR]'
        )
        xbmcplugin.addDirectoryItem(handle=handle, url="", listitem=li, isFolder=False)

    xbmcplugin.endOfDirectory(handle)
