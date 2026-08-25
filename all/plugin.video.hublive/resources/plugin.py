import os
import random
import re
import sys
import time
import traceback
import uuid
from concurrent.futures import (
    ThreadPoolExecutor,
    TimeoutError as FuturesTimeoutError,
    as_completed,
)
from urllib.parse import parse_qsl, quote_plus, urlencode

import requests
import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin

# Add resources/lib to path
_addon_path = xbmcaddon.Addon().getAddonInfo('path')
_lib_path = os.path.join(_addon_path, 'resources', 'lib')
if _lib_path not in sys.path:
    sys.path.insert(0, _lib_path)

from epg import format_epg_tooltip
from hublive_backend import (
    _CHANNELS_CACHE_TTL,
    _append_kodi_headers,
    _build_auth_headers_and_cookies,
    _selected_mac_override,
    _normalize_mac,
    check_server_online,
    clear_token_cache,
    clear_failed_mac,
    clean_category_title,
    clear_all_cache,
    clear_all_cache_for_all_servers,
    epg_contains,
    epg_contains_any,
    fetch_channels_by_category_from_server,
    fetch_server_categories,
    get_epg_items,
    get_candidate_macs,
    get_current_program,
    get_epg_manager,
    get_fetch_status,
    get_portal_url_for_server,
    get_random_mac_from_file,
    get_romanian_categories,
    get_server_auth,
    get_server_type,
    get_sport_categories,
    handshake,
    invalidate_server_auth,
    is_epg_enabled,
    iter_server_auth_candidates,
    json_dumps,
    json_loads,
    load_channels_cache,
    load_cached_category_channels,
    load_servers_config,
    load_epg_cache,
    note_failed_mac,
    reload_servers_config,
    save_epg_cache,
    set_server_auth,
    set_epg_current_server,
    set_fetch_status,
    get_session,
)
from hublive_favorites import (
    add_to_favorites,
    list_favorites,
    list_global_favorites,
    load_favorite_stream_ids,
    remove_from_favorites,
)
from hublive_search import (
    add_saved_search,
    clear_search_cache,
    fetch_stalker_search as search_fetch_stalker_search,
    list_saved_searches,
    mega_search_input as search_mega_search_input,
    mega_search_menu as render_mega_search_menu,
    remove_saved_search,
    search_input_dialog as render_search_input_dialog,
    search_input_dialog_series as render_search_input_dialog_series,
    search_input_dialog_vod as render_search_input_dialog_vod,
    show_mega_search_results as render_mega_search_results,
    show_search_results as render_search_results,
    show_series_search_results as render_series_search_results,
    show_vod_search_results as render_vod_search_results,
)
from hublive_vod_series import (
    clear_vod_series_cache,
    list_episodes as render_list_episodes,
    list_seasons as render_list_seasons,
    list_series_categories as render_list_series_categories,
    list_series_items as render_list_series_items,
    list_vod_categories as render_list_vod_categories,
    list_vod_items as render_list_vod_items,
    play_series as render_play_series,
    play_vod as render_play_vod,
)
from playback_state import clear_playback_state, load_playback_state, save_playback_state
from playlist_search import (
    get_playlist_categories,
    get_playlist_channels,
    search_playlist_index,
    update_playlist_index,
)
from world_cup_2026 import (
    list_world_cup_match_channels,
    list_world_cup_matches,
)

RE_STREAM_ID = re.compile(r"stream=(\d+)")
RE_MACPH_TOKENPH = re.compile(r"MACPH|TOKENPH")
RE_BOX_CHARS = re.compile(r"[\u2500-\u259F\u2500-\u257F]")
RE_CATEGORY_PREFIX = re.compile(r"^[\|\-\s]+ro[\|\s\:\-\[\(]?", re.IGNORECASE)
RE_EXTINF = re.compile(r"#EXTINF:", re.IGNORECASE)
RE_GROUP_TITLE = re.compile(r'group-title="?([^",]*)"?', re.IGNORECASE)
RE_TVG_LOGO = re.compile(r'tvg-logo=["\']([^"\']*)["\']', re.IGNORECASE)

TIMEOUTS = {
    "handshake": 5,
    "categories": 10,
    "channels": 20,
    "epg": 15,
    "playlink": 8,
    "playprobe": 6,
    "play": 15,
}

# Plugin version
PLUGIN_VERSION = "1.7.0"
MIN_KODI_VERSION = "19.0"
MIN_PYTHON_VERSION = (3, 6)


def check_version_compatibility():
    """Check if the plugin is compatible with the current environment."""
    checks_passed = True
    errors = []

    # Check Python version
    current_python = sys.version_info[:2]
    if current_python < MIN_PYTHON_VERSION:
        checks_passed = False
        errors.append(
            f"Python {MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]}+ required, found {current_python[0]}.{current_python[1]}"
        )

    # Check Kodi version
    try:
        kodi_version = xbmc.getInfoLabel("System.BuildVersion")
        kodi_major = int(kodi_version.split(".")[0]) if kodi_version else 0
        min_kodi_major = int(MIN_KODI_VERSION.split(".")[0])
        if kodi_major < min_kodi_major:
            checks_passed = False
            errors.append(f"Kodi {MIN_KODI_VERSION}+ required, found {kodi_version}")
    except Exception as e:
        xbmc.log(
            f"[Version] Could not determine Kodi version: {e}", level=xbmc.LOGWARNING
        )

    # Check required modules
    required_modules = ["requests"]
    for module in required_modules:
        try:
            __import__(module)
        except ImportError:
            checks_passed = False
            errors.append(f"Required module '{module}' not found")

    if not checks_passed:
        error_msg = " | ".join(errors)
        xbmc.log(
            f"[Version] Compatibility checks FAILED: {error_msg}", level=xbmc.LOGERROR
        )
        xbmcgui.Dialog().notification(
            "Eroare versiune",
            f"Pluginul poate să nu funcționeze corect: {error_msg}",
            xbmcgui.NOTIFICATION_ERROR,
            5000,
        )
        return False

    xbmc.log(
        f"[Version] Compatibility checks PASSED (Python {'.'.join(map(str, current_python))}, Kodi {kodi_version})",
        level=xbmc.LOGINFO,
    )
    return True


_ADDON = xbmcaddon.Addon()
_HANDLE = int(sys.argv[1])
_BASE_URL = sys.argv[0]


def is_server_check_enabled():
    return _ADDON.getSetting("server_check_enabled") == "true"


def is_live_auto_reconnect_enabled():
    return _ADDON.getSetting("live_auto_reconnect") == "true"


def get_live_catalog_source():
    value = (_ADDON.getSetting("live_catalog_source") or "0").strip()
    return value if value in ("0", "1", "2") else "0"


def _get_int_setting(setting_id, default_value, minimum=0, maximum=None):
    try:
        value = int((_ADDON.getSetting(setting_id) or "").strip())
    except (TypeError, ValueError):
        value = default_value

    value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def get_live_max_reconnect_attempts():
    return _get_int_setting("live_max_reconnect_attempts", 3, minimum=0, maximum=10)


def get_live_reconnect_delay():
    return _get_int_setting("live_reconnect_delay", 2, minimum=1, maximum=60)


def get_live_startup_timeout():
    return _get_int_setting("live_startup_timeout", 12, minimum=3, maximum=120)


def get_auth_max_attempts():
    return _get_int_setting("auth_max_attempts", 6, minimum=1, maximum=12)


def should_mega_search_fetch_missing_lists():
    return _ADDON.getSetting("mega_search_fetch_missing_lists") != "false"


def get_mega_search_fetch_batch_size():
    return _get_int_setting("mega_search_fetch_batch_size", 5, minimum=1, maximum=20)


def get_mega_search_mode():
    value = (_ADDON.getSetting("mega_search_mode") or "").strip().casefold()
    if value in ("1", "complet", "complete") or value.startswith("complet"):
        return "complete"
    return "rapid"


def should_retry_live_on_stopped():
    return _ADDON.getSetting("live_retry_on_stopped") == "true"


# Category mapping and sorting
CATEGORY_MAPPING = {
    # Server 1
    "RO| CANALE DE CINEMA": "Filme",
    "RO| CANALE DE DIVERTISMENT": "Divertisment",
    "RO| CANALE DE SPORT": "Sport",
    "RO| CANALE DOCUMENTARE": "Documentare",
    "RO| CANALE GENERALE": "Generale",
    "RO| CANALE MUZICALE": "Muzica",
    "RO| CANALE PENTRU COPII": "Pentru Copii",
    "RO| FOCUS SAT VIP": "Focus Sat",
    # Server 2
    "RO : ROMAINE": "Generale",
    "RO : COPİİ": "Pentru Copii",
    "RO : COPII": "Pentru Copii",
    "RO : DOCU & REALITATE": "Documentare",
    "RO : MUZICÄ": "Muzica",
    "RO : MUZICA": "Muzica",
    "RO : SPORT": "Sport",
    "RO : FILM": "Filme",
}

# Custom sort order for categories
CATEGORY_ORDER = [
    "Generale",
    "Divertisment",
    "Sport",
    "Filme",
    "Documentare",
    "Muzica",
    "Pentru Copii",
    "Focus Sat",
]

# Category icons (using Kodi's built-in icons)
CATEGORY_ICONS = {
    "Generale": "DefaultTVShows.png",
    "Divertisment": "DefaultMusicVideos.png",
    "Sport": "DefaultAddonGame.png",
    "Filme": "DefaultMovies.png",
    "Documentare": "DefaultAddonPVRClient.png",
    "Muzica": "DefaultMusicAlbums.png",
    "Pentru Copii": "DefaultAddonGame.png",
    "Focus Sat": "DefaultAddonService.png",
}


def map_category_name(original_name):
    """Map original category name to display name."""
    return CATEGORY_MAPPING.get(original_name, original_name)


def get_category_icon(category_name):
    """Get icon for a category."""
    return CATEGORY_ICONS.get(category_name, "DefaultFolder.png")


def get_category_sort_key(category_name):
    """Get sort key for a category. Returns index in CATEGORY_ORDER or 999 for unmapped."""
    try:
        return CATEGORY_ORDER.index(category_name)
    except ValueError:
        return 999  # Put unmapped categories at the end


def get_params():
    """Get the plugin parameters"""
    paramstring = sys.argv[2][1:]
    return dict(parse_qsl(paramstring))


def parse_m3u_channels(m3u_file, server="server1"):
    """
    Parse M3U file and return list of channel dictionaries.
    Centralized M3U parsing to avoid code duplication.

    Args:
        m3u_file: Path to the M3U file
        server: 'server1' or 'server2'

    Returns:
        List of channel dicts with keys: name, group, logo, stream_id, url
    """
    channels = []

    try:
        with open(m3u_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        xbmc.log(f"[M3U] Failed to read {m3u_file}: {e}", level=xbmc.LOGERROR)
        return []

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if line.startswith("#EXTINF:") or RE_EXTINF.search(line):
            group_title_match = RE_GROUP_TITLE.search(line)
            tvg_logo_match = RE_TVG_LOGO.search(line)

            last_comma_pos = line.rfind(",")
            if last_comma_pos != -1:
                channel_name = line[last_comma_pos + 1 :].strip()
            else:
                channel_name = "Unknown Channel"

            group_title = (
                group_title_match.group(1).strip()
                if group_title_match
                else "Uncategorized"
            )
            tvg_logo = tvg_logo_match.group(1) if tvg_logo_match else ""
            group_title = map_category_name(group_title)

            if i + 1 < len(lines):
                url_line = lines[i + 1].strip()
                if url_line and not url_line.startswith("#"):
                    if RE_MACPH_TOKENPH.search(url_line):
                        stream_id = f"s2_{len(channels)}"
                        channels.append(
                            {
                                "name": channel_name,
                                "group": group_title,
                                "logo": tvg_logo,
                                "stream_id": stream_id,
                                "url": url_line,
                            }
                        )
                    else:
                        stream_id_match = RE_STREAM_ID.search(url_line)
                        if stream_id_match:
                            stream_id = stream_id_match.group(1)
                            channels.append(
                                {
                                    "name": channel_name,
                                    "group": group_title,
                                    "logo": tvg_logo,
                                    "stream_id": stream_id,
                                    "url": url_line,
                                }
                            )

        i += 1

    xbmc.log(
        f"[M3U] Parsed {len(channels)} channels from {os.path.basename(m3u_file)}",
        level=xbmc.LOGINFO,
    )
    return channels


def main_menu():
    """Render the main menu with Mega Search, LiveTV Romania, World, Sport, Filme, Seriale, Favorites, and Server Check."""
    items = [
        (
            "[COLOR gold]Mega Cautare[/COLOR]",
            "mega_search_menu",
            "DefaultAddonsSearch.png",
        ),
        ("LiveTV Romania", "romania", "DefaultTVShows.png"),
        ("LiveTV World", "world", "DefaultAddonPVRClient.png"),
        ("LiveTV Sport", "sport", "DefaultAddonGame.png"),
        (
            "[COLOR gold]World Cup 2026[/COLOR]",
            "world_cup_2026",
            "DefaultAddonGame.png",
        ),
        ("Filme", "vod", "DefaultMovies.png"),
        ("Seriale", "series", "DefaultTVShows.png"),
        ("[COLOR gold]Favorite[/COLOR]", "global_favorites", "DefaultFavourites.png"),
        ("[COLOR yellow]Verificare Servere[/COLOR]", "check", "DefaultNetwork.png"),
        ("[COLOR cyan]Setari[/COLOR]", "settings_menu", "DefaultAddonService.png"),
    ]

    for label, main_mode, icon in items:
        li = xbmcgui.ListItem(label=label)
        li.setArt({"icon": icon, "thumb": icon})
        is_folder = True

        if main_mode == "check":
            url = (
                f"{_BASE_URL}?mode=select_server&main_mode=verificare&force_check=true"
            )
            is_folder = False
        elif main_mode == "settings_menu":
            url = f"{_BASE_URL}?mode=settings_menu&is_main=true"
        elif main_mode == "mega_search_menu":
            url = f"{_BASE_URL}?mode=mega_search_menu"
        elif main_mode == "world_cup_2026":
            url = f"{_BASE_URL}?mode=world_cup_2026"
        elif main_mode == "global_favorites":
            url = f"{_BASE_URL}?mode=global_favorites"
        else:
            url = f"{_BASE_URL}?mode=open_section&main_mode={main_mode}"
            is_folder = False

        xbmcplugin.addDirectoryItem(
            handle=_HANDLE, url=url, listitem=li, isFolder=is_folder
        )

    xbmcplugin.endOfDirectory(_HANDLE)


def mega_search_menu():
    render_mega_search_menu(_BASE_URL, _HANDLE)


def get_session_server_statuses():
    """Get server statuses from Kodi window property (session cache)."""
    try:
        window = xbmcgui.Window(10000)
        data = window.getProperty("hublive_server_statuses")
        if data:
            return json_loads(data)
    except:
        pass
    return None


def set_session_server_statuses(statuses):
    """Save server statuses to Kodi window property."""
    try:
        window = xbmcgui.Window(10000)
        window.setProperty("hublive_server_statuses", json_dumps(statuses))
    except:
        pass


def select_server_dialog(main_mode, force_check=False):
    """Show a dialog to select a server and return the selected server ID.
    Uses session cache for statuses unless force_check is True.
    """
    servers_config = load_servers_config()
    available_servers = servers_config.get("servers", [])

    if not available_servers:
        xbmcgui.Dialog().ok("Eroare", "Nu există servere configurate în servers.json")
        return None

    # Try to get statuses from session cache
    server_statuses = get_session_server_statuses()

    # Determine if we need to perform a check
    should_check = force_check or (
        is_server_check_enabled() and server_statuses is None
    )

    if should_check:
        # Perform parallel check
        server_statuses = _check_all_servers_online(available_servers)
        # Update session cache
        set_session_server_statuses(server_statuses)

    # Safe capitalize for title
    title_suffix = main_mode.capitalize() if main_mode else "Verificare"

    labels = []
    for srv in available_servers:
        srv_name = srv.get("name", srv.get("id", "Unknown"))
        srv_id = srv.get("id")
        
        # Count MACs for this server
        macs = srv.get("macs", [])
        mac_count = len(macs)

        if server_statuses is not None:
            is_online = server_statuses.get(srv_id, False)
            status = (
                "[COLOR green]● ON[/COLOR]" if is_online else "[COLOR red]● OFF[/COLOR]"
            )
            labels.append(f"{srv_name} - {mac_count} MACs  {status}")
        else:
            labels.append(f"{srv_name} - {mac_count} MACs")

    selection = xbmcgui.Dialog().select(f"Alege Server - {title_suffix}", labels)

    if selection >= 0:
        return available_servers[selection].get("id")

    return None


def _build_selected_server_target(main_mode, selected_server):
    target_params = {"server": selected_server}
    if main_mode:
        target_params["main_mode"] = main_mode
    if main_mode == "vod":
        target_params["mode"] = "list_vod_categories"
    elif main_mode == "series":
        target_params["mode"] = "list_series_categories"
    else:
        target_params["mode"] = "list_channels"
    return f"{_BASE_URL}?{urlencode(target_params)}"


def list_vod_items(category_id, server="server1"):
    render_list_vod_items(_BASE_URL, _HANDLE, category_id, server=server, timeouts=TIMEOUTS)


def list_series_items(category_id, server="server1"):
    render_list_series_items(
        _BASE_URL, _HANDLE, category_id, server=server, timeouts=TIMEOUTS
    )


def list_seasons(movie_id, server="server1"):
    render_list_seasons(_BASE_URL, _HANDLE, movie_id, server=server, timeouts=TIMEOUTS)


def list_episodes(movie_id, season_id, server="server1"):
    render_list_episodes(
        _BASE_URL,
        _HANDLE,
        movie_id,
        season_id,
        server=server,
        timeouts=TIMEOUTS,
    )


def _normalize_playback_url(stream_url):
    """Normalize a playback URL returned by Stalker."""
    cleaned_url = (stream_url or "").strip()
    if cleaned_url.startswith("ffmpeg "):
        cleaned_url = cleaned_url.split(" ", 1)[1].strip()
    return cleaned_url


def _split_kodi_url_options(stream_url):
    """Split Kodi-style URL options from the actual stream URL."""
    cleaned_url = _normalize_playback_url(stream_url)
    if "|" not in cleaned_url:
        return cleaned_url, {}

    base_url, raw_options = cleaned_url.split("|", 1)
    option_headers = {}
    for key, value in parse_qsl(raw_options, keep_blank_values=True):
        if key:
            option_headers[key] = value
    return base_url, option_headers


def _probe_stream_url(stream_url, headers=None, timeout=None, allow_body_read=True):
    """Perform a lightweight probe before handing the URL to Kodi."""
    probe_url, option_headers = _split_kodi_url_options(stream_url)
    if not probe_url:
        return False, "Playback URL is empty.", None

    probe_headers = {
        "User-Agent": get_session().headers.get("User-Agent", ""),
        "X-User-Agent": get_session().headers.get("X-User-Agent", ""),
        "Accept": "*/*",
        "Accept-Encoding": "identity",
        "Connection": "close",
    }
    if headers:
        probe_headers.update({key: value for key, value in headers.items() if value})
    if option_headers:
        probe_headers.update(
            {key: value for key, value in option_headers.items() if value}
        )

    response = None
    try:
        response = get_session().get(
            probe_url,
            headers=probe_headers,
            timeout=timeout or TIMEOUTS["playprobe"],
            allow_redirects=True,
            stream=True,
            verify=False,
        )

        status_code = response.status_code
        final_url = response.url
        
        if status_code >= 400:
            return False, f"HTTP {status_code}", final_url

        content_type = (response.headers.get("Content-Type") or "").lower()
        if allow_body_read and "text/html" in content_type:
            sample = b""
            try:
                sample = next(response.iter_content(chunk_size=256), b"")
            except requests.exceptions.RequestException:
                sample = b""

            sample_text = sample.decode("utf-8", "ignore").lower()
            if any(
                marker in sample_text
                for marker in ("<html", "forbidden", "denied", "expired", "error")
            ):
                return False, f"Unexpected HTML response ({status_code})", final_url

        return True, f"HTTP {status_code}", final_url
    except requests.exceptions.RequestException as exc:
        return False, str(exc), None
    finally:
        if response is not None:
            response.close()


def _parse_attempted_macs_param(attempted_macs):
    if not attempted_macs:
        return []
    if isinstance(attempted_macs, (list, tuple, set)):
        raw_items = attempted_macs
    else:
        raw_items = str(attempted_macs).split(",")

    parsed = []
    seen = set()
    for item in raw_items:
        norm_mac = _normalize_mac(item)
        if norm_mac and norm_mac not in seen:
            parsed.append(item.strip())
            seen.add(norm_mac)
    return parsed


def _trim_attempted_macs(macs, limit=None):
    if limit is None:
        limit = max(
            get_auth_max_attempts() * (get_live_max_reconnect_attempts() + 1),
            get_auth_max_attempts(),
        )

    trimmed = []
    seen = set()
    for mac in macs or []:
        norm_mac = _normalize_mac(mac)
        if norm_mac and norm_mac not in seen:
            trimmed.append(mac)
            seen.add(norm_mac)
    return trimmed[-limit:]


def _build_plugin_play_url(mode, server, **params):
    query = {"mode": mode, "server": server}
    for key, value in params.items():
        if value is None or value == "":
            continue
        query[key] = value
    return f"{_BASE_URL}?{urlencode(query)}"


def _save_live_playback_session(
    stream_id,
    name,
    server,
    resolved_url,
    current_mac,
    url_template=None,
    attempted_macs=None,
    reconnect_count=0,
    session_id=None,
):
    if not is_live_auto_reconnect_enabled():
        clear_playback_state()
        return None

    session_id = session_id or uuid.uuid4().hex
    safe_attempted_macs = _trim_attempted_macs(
        list(_parse_attempted_macs_param(attempted_macs)) + [current_mac]
    )
    plugin_url = _build_plugin_play_url(
        "play",
        server,
        stream_id=stream_id,
        name=name,
        url_template=url_template,
        session_id=session_id,
        reconnect_count=reconnect_count,
        attempted_macs=",".join(safe_attempted_macs),
        autoplay_reconnect="true",
    )
    state = {
        "session_id": session_id,
        "kind": "live",
        "server": server,
        "stream_id": stream_id,
        "name": name,
        "url_template": url_template or "",
        "plugin_url": plugin_url,
        "resolved_url": resolved_url,
        "current_mac": current_mac,
        "attempted_macs": safe_attempted_macs,
        "reconnect_count": int(reconnect_count or 0),
        "max_reconnects": get_live_max_reconnect_attempts(),
        "reconnect_delay": get_live_reconnect_delay(),
        "startup_timeout": get_live_startup_timeout(),
        "status": "resolving",
        "playback_started": False,
        "reconnect_in_progress": False,
        "created_at": time.time(),
        "last_event_at": time.time(),
    }
    save_playback_state(state)
    return session_id


def _mark_playback_session_failed(
    session_id, kind, server, last_error, attempts=0, portal_online=None
):
    if kind != "live" or not session_id:
        return

    state = load_playback_state()
    if state.get("session_id") != session_id:
        return

    state.update(
        {
            "status": "failed",
            "last_error": last_error,
            "portal_online": portal_online,
            "attempts": attempts,
            "reconnect_in_progress": False,
            "last_event_at": time.time(),
        }
    )
    save_playback_state(state)


def _finalize_playback_failure(
    server, portal_url, attempts, last_error, title, session_id=None, kind="live"
):
    """Store playback status and show a clear user-facing notification."""
    portal_online = check_server_online(portal_url) if portal_url else False
    status = "portal_off" if portal_online is False else "play_failed"
    if portal_online is False:
        message = f"{title}: portalul serverului pare indisponibil."
    elif attempts:
        message = f"{title}: nu s-a gasit un MAC valid dupa {attempts} incercari."
    else:
        message = last_error or f"{title}: redarea nu a putut fi pornita."

    set_fetch_status(
        "playback",
        server,
        status=status,
        message=last_error or message,
        portal_online=portal_online,
        attempts=attempts,
        used_cache=False,
        stale_cache=False,
        item_count=0,
    )
    _mark_playback_session_failed(
        session_id,
        kind,
        server,
        last_error or message,
        attempts=attempts,
        portal_online=portal_online,
    )
    xbmcgui.Dialog().notification("Eroare", message, xbmcgui.NOTIFICATION_ERROR)


def _navigate_to_main_menu():
    main_menu_url = f"{_BASE_URL}?"
    xbmc.executebuiltin(f"Container.Update({main_menu_url})")
    xbmc.executebuiltin(f"ActivateWindow(Videos,{main_menu_url},return)")


def _handle_exhausted_mac_options(
    server,
    stream_id,
    name,
    attempted_macs,
    session_id=None,
    reconnect_count=0,
    url_template=None,
):
    auth_max_attempts = get_auth_max_attempts()
    remaining_candidates = get_candidate_macs(
        server, exclude_macs=list(attempted_macs), limit=auth_max_attempts
    )
    remaining_count = len(remaining_candidates)

    if not remaining_count:
        selection = xbmcgui.Dialog().select(
            "Nu mai sunt MAC-uri disponibile",
            [
                "Mergi la meniul principal",
                "Renunță",
            ],
        )
        if selection == 0:
            clear_playback_state(session_id)
            _navigate_to_main_menu()
            return True
        if selection == 1:
            clear_playback_state(session_id)
            return True
        return False

    next_count = min(auth_max_attempts, remaining_count)
    selection = xbmcgui.Dialog().select(
        f"Nu s-au găsit MAC-uri viabile ({len(attempted_macs)} încercate)",
        [
            f"Încearcă următoarele {next_count} MAC-uri",
            "Mergi la meniul principal",
            "Renunță",
        ],
    )

    if selection == 0:
        play_stream(
            stream_id,
            name,
            server=server,
            url_template=url_template,
            session_id=session_id,
            attempted_macs=",".join(sorted(attempted_macs)),
            reconnect_count=reconnect_count,
            autoplay_reconnect=False,
        )
        return True

    if selection == 1:
        clear_playback_state(session_id)
        _navigate_to_main_menu()
        return True

    if selection == 2:
        clear_playback_state(session_id)
        return True

    return False


def _handle_exhausted_vod_series_options(
    server,
    attempted_macs,
    kind="vod",
    movie_id=None,
    cmd=None,
    episode_num=None,
):
    """Handle exhausted MAC options for VOD and Series playback."""
    remaining_candidates = get_candidate_macs(
        server, exclude_macs=list(attempted_macs), limit=1
    )
    if not remaining_candidates:
        return False

    content_type = "filme" if kind == "vod" else "seriale"
    selection = xbmcgui.Dialog().select(
        f"Nu s-au găsit MAC-uri viabile pentru {content_type}",
        [
            "Încearcă un nou set de MAC-uri",
            "Mergi la meniul principal",
            "Renunță",
        ],
    )

    if selection == 0:
        # Retry with new MACs
        attempted_macs_str = ",".join(sorted(attempted_macs))
        if kind == "vod":
            play_vod(movie_id, server=server, attempted_macs=attempted_macs_str)
        else:  # series
            play_series(cmd, episode_num, server=server, attempted_macs=attempted_macs_str)
        return True

    if selection == 1:
        clear_playback_state()
        _navigate_to_main_menu()
        return True

    return False


def _record_live_playback_success(
    server,
    name,
    stream_id,
    resolved_url,
    random_mac,
    attempts,
    attempted_macs,
    reconnect_count,
    session_id,
    url_template=None,
    cache_token=None,
    random_val="0",
):
    clear_failed_mac(server, random_mac)
    if cache_token:
        set_server_auth(server, cache_token, random_mac, random_value=random_val)
    set_fetch_status(
        "playback",
        server,
        status="ok",
        message=f"Canal pornit cu MAC {random_mac}",
        portal_online=True,
        attempts=attempts,
        used_cache=False,
        stale_cache=False,
        item_count=1,
    )
    session_id = _save_live_playback_session(
        stream_id=stream_id,
        name=name,
        server=server,
        resolved_url=resolved_url,
        current_mac=random_mac,
        url_template=url_template,
        attempted_macs=list(attempted_macs),
        reconnect_count=reconnect_count,
        session_id=session_id,
    )
    
    # Fix HTTP 555 by appending headers for Kodi player
    portal_url = get_portal_url_for_server(server)
    url_with_headers = _append_kodi_headers(
        resolved_url, mac=random_mac, token=cache_token, portal_url=portal_url, random_val=random_val
    )
    
    play_item = xbmcgui.ListItem(path=url_with_headers)
    xbmcplugin.setResolvedUrl(_HANDLE, True, listitem=play_item)
    return session_id


def _handle_live_attempt_failure(server, random_mac, attempts, last_error, log_prefix):
    note_failed_mac(server, random_mac)
    invalidate_server_auth(server, mac=random_mac)
    xbmc.log(
        f"[{log_prefix}] Playback attempt {attempts} failed for MAC {random_mac}: {last_error}",
        level=xbmc.LOGWARNING,
    )


def _extract_live_returned_cmd(link_data):
    if isinstance(link_data, dict):
        js_data = link_data.get("js", {})
        if isinstance(js_data, dict):
            returned_cmd = js_data.get("cmd")
        elif isinstance(js_data, list):
            raise ValueError("MAC respins de server (raspuns js gol).")
        else:
            raise ValueError(f"Tip de raspuns js neasteptat: {type(js_data)}")
    elif isinstance(link_data, list):
        raise ValueError("MAC respins de server (lista goala la nivel root).")
    else:
        raise ValueError(f"Tip de raspuns neasteptat: {type(link_data)}")

    if not returned_cmd:
        raise ValueError("Serverul nu a returnat comanda de redare.")
    return returned_cmd


def _extract_play_token(returned_cmd, missing_message):
    play_token_match = re.search(r"play_token=([a-zA-Z0-9]+)", returned_cmd or "")
    if not play_token_match:
        raise ValueError(missing_message)
    return play_token_match.group(1)


def _run_live_playback_attempts(
    server,
    name,
    stream_id,
    attempted_mac_list,
    reconnect_count,
    session_id,
    attempt_provider,
    attempt_executor,
    url_template=None,
    total_attempts=4,
    progress_total=None,
    progress_message="Se încearcă conectarea...",
    failure_title="Redarea canalului",
    allow_retry_prompt=True,
):
    dp = xbmcgui.DialogProgress()
    dp.create("Se caută stream valid...", "Se testează streamul...")
    dp.update(0)
    attempted_macs = {
        _normalize_mac(mac) for mac in attempted_mac_list if _normalize_mac(mac)
    }
    attempts = 0
    last_error = "Niciun stream valid găsit."
    final_portal_url = get_portal_url_for_server(server)
    progress_divisor = progress_total or total_attempts or 1

    try:
        for attempt_entry in attempt_provider(attempted_macs):
            if dp.iscanceled():
                clear_playback_state(session_id)
                return None

            attempts += 1
            dp.update(
                int(((attempts - 1) / max(progress_divisor, 1)) * 100),
                progress_message,
            )

            random_mac = attempt_entry.get("mac")
            portal_url = attempt_entry.get("portal_url")
            final_portal_url = portal_url or final_portal_url

            norm_mac = _normalize_mac(random_mac)
            if norm_mac:
                attempted_macs.add(norm_mac)

            result = attempt_executor(attempt_entry, attempts, attempted_macs)
            if result.get("success"):
                return _record_live_playback_success(
                    server=server,
                    name=name,
                    stream_id=stream_id,
                    resolved_url=result["resolved_url"],
                    random_mac=random_mac,
                    attempts=attempts,
                    attempted_macs=attempted_macs,
                    reconnect_count=reconnect_count,
                    session_id=session_id,
                    url_template=url_template,
                    cache_token=result.get("cache_token"),
                    random_val=result.get("random", "0"),
                )

            last_error = result.get("error") or last_error
            if result.get("break"):
                break
    finally:
        dp.close()

    if allow_retry_prompt and _handle_exhausted_mac_options(
        server=server,
        stream_id=stream_id,
        name=name,
        attempted_macs=attempted_macs,
        session_id=session_id,
        reconnect_count=reconnect_count,
        url_template=url_template,
    ):
        return None

    _finalize_playback_failure(
        server,
        final_portal_url,
        attempts,
        last_error,
        failure_title,
        session_id=session_id,
    )
    return None


def play_vod(movie_id, server="server1", attempted_macs=""):
    """Play VOD with MAC retry support."""
    attempted_macs_list = attempted_macs.split(",") if attempted_macs else []
    
    result = render_play_vod(
        _HANDLE,
        movie_id,
        server=server,
        normalize_playback_url_fn=_normalize_playback_url,
        probe_stream_url_fn=_probe_stream_url,
        finalize_playback_failure_fn=_finalize_playback_failure,
        timeouts=TIMEOUTS,
        attempted_macs=attempted_macs_list,
    )
    
    # If playback failed and we have the attempted MACs, offer retry options
    if result and isinstance(result, dict) and not result.get("success"):
        attempted = result.get("attempted_macs", [])
        if attempted:
            _handle_exhausted_vod_series_options(
                server=server,
                movie_id=movie_id,
                attempted_macs=attempted,
                kind="vod",
            )


def play_series(cmd, episode_num, server="server1", attempted_macs=""):
    """Play series episode with MAC retry support."""
    attempted_macs_list = attempted_macs.split(",") if attempted_macs else []
    
    result = render_play_series(
        _HANDLE,
        cmd,
        episode_num,
        server=server,
        normalize_playback_url_fn=_normalize_playback_url,
        probe_stream_url_fn=_probe_stream_url,
        finalize_playback_failure_fn=_finalize_playback_failure,
        timeouts=TIMEOUTS,
        attempted_macs=attempted_macs_list,
    )
    
    # If playback failed and we have the attempted MACs, offer retry options
    if result and isinstance(result, dict) and not result.get("success"):
        attempted = result.get("attempted_macs", [])
        if attempted:
            _handle_exhausted_vod_series_options(
                server=server,
                cmd=cmd,
                episode_num=episode_num,
                attempted_macs=attempted,
                kind="series",
            )


def list_vod_categories(server="server1"):
    render_list_vod_categories(_BASE_URL, _HANDLE, server=server)


def list_series_categories(server="server1"):
    render_list_series_categories(_BASE_URL, _HANDLE, server=server)


def list_channels(
    server="server1",
    category=None,
    category_id=None,
    from_server=False,
    main_mode=None,
):
    """List channel categories from server."""
    # Check if portal URL exists
    portal_url = get_portal_url_for_server(server)
    if not portal_url:
        xbmc.log(f"[List] No portal URL configured for {server}", level=xbmc.LOGERROR)
        xbmcgui.Dialog().notification(
            "Eroare",
            f"Nu este configurat niciun portal URL pentru {server}",
            xbmcgui.NOTIFICATION_ERROR,
        )
        return

    # Get params for backward compatibility
    params = get_params()
    if category is None:
        category = params.get("category")
    if category_id is None:
        category_id = params.get("cat_id")
    if not from_server:
        from_server = params.get("from_server") == "true"
    if main_mode is None:
        main_mode = params.get("main_mode")

    xbmc.log(
        f"[List] Listing channels for server={server}, main_mode={main_mode}",
        level=xbmc.LOGINFO,
    )

    # If a category is selected, list channels in that category
    if category:
        list_channels_in_category(
            [],
            category,
            server=server,
            category_id=category_id,
            from_server=from_server,
            main_mode=main_mode,
        )
    else:
        # List all available categories
        list_categories([], server=server, main_mode=main_mode)


def list_categories(channels, server="server1", main_mode=None):
    """List all available channel categories with Get Full EPG button."""
    # Add "Search" button at the top - Action item, not a folder
    search_button = xbmcgui.ListItem(label="[COLOR yellow]Cauta[/COLOR]")
    search_button.setArt(
        {"icon": "DefaultAddonsSearch.png", "thumb": "DefaultAddonsSearch.png"}
    )
    search_button.setProperty("IsPlayable", "false")
    search_button_url = f"{_BASE_URL}?mode=search_input&server={server}&main_mode={main_mode if main_mode else ''}"
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE, url=search_button_url, listitem=search_button, isFolder=False
    )

    # Add "Favorites" button at the top
    favorites_button = xbmcgui.ListItem(label="[COLOR gold]Favorite[/COLOR]")
    favorites_button.setArt(
        {"icon": "DefaultFavourites.png", "thumb": "DefaultFavourites.png"}
    )
    favorites_button_url = f"{_BASE_URL}?mode=favorites&server={server}&main_mode={main_mode if main_mode else ''}"
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE,
        url=favorites_button_url,
        listitem=favorites_button,
        isFolder=True,
    )

    # Get server type
    server_type = get_server_type(server)

    # Add "Get Full EPG" button (only if EPG is enabled and server type supports it)
    if is_epg_enabled() and server_type in ["stalker", "stalker_v2"]:
        epg_button = xbmcgui.ListItem(label="[COLOR yellow]Get Full EPG[/COLOR]")
        epg_button.setArt(
            {"icon": "DefaultAddonPVRClient.png", "thumb": "DefaultAddonPVRClient.png"}
        )
        epg_button_url = f"{_BASE_URL}?mode=get_full_epg&server={server}&main_mode={main_mode if main_mode else ''}"
        xbmcplugin.addDirectoryItem(
            handle=_HANDLE, url=epg_button_url, listitem=epg_button, isFolder=False
        )

    # Add "Refresh Cache" button
    refresh_button = xbmcgui.ListItem(label="[COLOR cyan]Reîmprospătează Lista[/COLOR]")
    refresh_button.setArt(
        {"icon": "DefaultAddonService.png", "thumb": "DefaultAddonService.png"}
    )
    refresh_button_url = f"{_BASE_URL}?mode=refresh_cache&server={server}&main_mode={main_mode if main_mode else ''}"
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE, url=refresh_button_url, listitem=refresh_button, isFolder=False
    )

    server_cat_list = []
    all_server_cats = []
    catalog_source = get_live_catalog_source()
    catalog_label = "portal"

    if catalog_source != "1":
        available_servers = load_servers_config().get("servers", [])
        all_server_cats = get_playlist_categories(server, available_servers)
        if all_server_cats:
            catalog_label = "ratb"

    # Portal-only mode, or automatic fallback when the RATB catalog is absent.
    if (
        not all_server_cats
        and catalog_source != "2"
        and server_type in ["stalker", "stalker_v2"]
    ):
        all_server_cats = fetch_server_categories(server)
        catalog_label = "portal"

    if all_server_cats:
        if main_mode == "world":
            server_cat_list = all_server_cats
        elif main_mode == "sport":
            server_cat_list = get_sport_categories(all_server_cats)
        else:
            server_cat_list = get_romanian_categories(all_server_cats)

        if (
            catalog_label == "ratb"
            and not server_cat_list
            and catalog_source == "0"
            and server_type in ["stalker", "stalker_v2"]
        ):
            xbmc.log(
                f"[Categories] RATB has no matches for mode {main_mode}; "
                "using portal fallback",
                level=xbmc.LOGINFO,
            )
            all_server_cats = fetch_server_categories(server)
            catalog_label = "portal"
            if main_mode == "world":
                server_cat_list = all_server_cats
            elif main_mode == "sport":
                server_cat_list = get_sport_categories(all_server_cats)
            else:
                server_cat_list = get_romanian_categories(all_server_cats)

        if (
            catalog_label == "portal"
            and not server_cat_list
            and get_fetch_status("categories", server).get("used_cache")
        ):
            xbmc.log(
                f"[Categories] Cached categories produced no matches for mode "
                f"{main_mode}; forcing refresh",
                level=xbmc.LOGINFO,
            )
            all_server_cats = fetch_server_categories(server, force_refresh=True)
            if main_mode == "world":
                server_cat_list = all_server_cats
            elif main_mode == "sport":
                server_cat_list = get_sport_categories(all_server_cats)
            else:
                server_cat_list = get_romanian_categories(all_server_cats)

        xbmc.log(
            f"[Categories] Using {catalog_label} categories for {server}: "
            f"{len(server_cat_list)} found (mode: {main_mode})",
            level=xbmc.LOGINFO,
        )

    # Determine which categories to display
    if server_cat_list:
        # If only one category, show channels directly
        if len(server_cat_list) == 1:
            cat = server_cat_list[0]
            xbmc.log(
                f"[Categories] Single category detected: {cat['title']}, showing channels directly",
                level=xbmc.LOGINFO,
            )
            list_channels_in_category(
                [],
                clean_category_title(cat["title"]),
                server=server,
                category_id=cat["id"],
                from_server=True,
                main_mode=main_mode,
            )
            return

        # Multiple categories - show the list
        categories_to_show = []
        for cat in server_cat_list:
            display_name = clean_category_title(cat["title"])
            # Map to our display format if possible
            mapped = map_category_name(display_name)
            categories_to_show.append(
                {"display": mapped, "original": display_name, "id": cat["id"]}
            )

        # Sort by custom order
        if main_mode != "world":
            categories_to_show.sort(key=lambda x: get_category_sort_key(x["display"]))
        else:
            categories_to_show.sort(key=lambda x: x["display"])

        for cat_info in categories_to_show:
            li = xbmcgui.ListItem(label=cat_info["display"])
            icon = get_category_icon(cat_info["display"])
            li.setArt({"icon": icon, "thumb": icon})

            # Use original category name for server query
            category_url = f"{_BASE_URL}?category={quote_plus(cat_info['original'])}&server={server}&cat_id={cat_info['id']}&from_server=true&main_mode={main_mode if main_mode else ''}"

            xbmcplugin.addDirectoryItem(
                handle=_HANDLE, url=category_url, listitem=li, isFolder=True
            )
    else:
        # No categories from server - show error
        status = get_fetch_status("categories", server)
        xbmc.log(
            f"[Categories] No categories found for {server}. Status: {status}",
            level=xbmc.LOGERROR,
        )

        if all_server_cats:
            primary_label = "[COLOR red]Nu exista categorii pentru sectiunea selectata[/COLOR]"
            secondary_label = "[COLOR yellow]Incearca alta sectiune sau alt server[/COLOR]"
        elif status.get("portal_online") is False:
            primary_label = "[COLOR red]Nu se pot incarca categoriile[/COLOR]"
            secondary_label = "[COLOR yellow]Portalul serverului pare indisponibil[/COLOR]"
        elif status.get("attempts", 0) > 0:
            primary_label = "[COLOR red]Nu se pot incarca categoriile[/COLOR]"
            secondary_label = (
                f"[COLOR yellow]S-au incercat {status['attempts']} MAC-uri diferite. "
                "Incearca din nou sau schimba MAC-ul[/COLOR]"
            )
        else:
            primary_label = "[COLOR red]Nu se pot incarca categoriile[/COLOR]"
            secondary_label = "[COLOR yellow]Verifica serverul sau conexiunea la internet[/COLOR]"

        li = xbmcgui.ListItem(label=primary_label)
        li.setProperty("IsPlayable", "false")
        xbmcplugin.addDirectoryItem(handle=_HANDLE, url="", listitem=li, isFolder=False)

        li2 = xbmcgui.ListItem(label=secondary_label)
        xbmcplugin.addDirectoryItem(
            handle=_HANDLE, url="", listitem=li2, isFolder=False
        )

    # Add Settings folder at the end
    settings_folder = xbmcgui.ListItem(label="[COLOR cyan]Setari[/COLOR]")
    settings_folder.setArt(
        {"icon": "DefaultAddonService.png", "thumb": "DefaultAddonService.png"}
    )
    settings_folder_url = f"{_BASE_URL}?mode=settings_menu&server={server}"
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE, url=settings_folder_url, listitem=settings_folder, isFolder=True
    )

    xbmcplugin.endOfDirectory(_HANDLE)


def list_channels_in_category(
    all_channels,
    selected_category,
    server="server1",
    category_id=None,
    from_server=False,
    main_mode=None,
):
    """List channels within a specific category."""
    favorite_stream_ids = load_favorite_stream_ids(server)

    # Handle server categories
    if from_server and category_id:
        # Fetch channels from server by category
        xbmc.log(
            f"[Categories] Fetching channels for category ID: {category_id} (mode: {main_mode})",
            level=xbmc.LOGINFO,
        )
        catalog_source = get_live_catalog_source()
        server_channels = []
        if str(category_id).startswith("ratb:") and catalog_source != "1":
            available_servers = load_servers_config().get("servers", [])
            server_channels = get_playlist_channels(
                server,
                category_id,
                available_servers,
            )
            if not server_channels and catalog_source == "0":
                portal_categories = fetch_server_categories(server)
                selected_key = clean_category_title(
                    selected_category
                ).casefold()
                portal_category = next(
                    (
                        item
                        for item in portal_categories or []
                        if clean_category_title(
                            item.get("title") or ""
                        ).casefold()
                        == selected_key
                    ),
                    None,
                )
                if portal_category:
                    xbmc.log(
                        f"[Categories] RATB category empty; using portal "
                        f"fallback {portal_category.get('id')}",
                        level=xbmc.LOGWARNING,
                    )
                    server_channels = fetch_channels_by_category_from_server(
                        portal_category.get("id"),
                        server,
                    )
        else:
            server_channels = fetch_channels_by_category_from_server(
                category_id,
                server,
            )

        if server_channels:
            # Convert server channels to our format
            channels_in_category = []
            for idx, ch in enumerate(server_channels):
                name = clean_category_title(
                    ch.get("name") or ch.get("title") or "Unknown"
                )
                cmd = ch.get("cmd") or ch.get("stream_url") or ""
                logo = ch.get("logo") or ""
                if logo and RE_BOX_CHARS.search(logo):
                    logo = ""

                stream_id_match = RE_STREAM_ID.search(cmd)
                if stream_id_match:
                    stream_id = stream_id_match.group(1)
                else:
                    # Fallback 1: Use direct 'id' field if numeric
                    srv_id_field = str(ch.get("id", ""))
                    if srv_id_field and srv_id_field.isdigit():
                        stream_id = srv_id_field
                    else:
                        # Fallback 2: Try to find ANY number in the cmd
                        any_digit_match = re.search(r"(\d+)", cmd)
                        stream_id = any_digit_match.group(1) if any_digit_match else f"unknown_{idx}"

                channels_in_category.append(
                    {
                        "name": name,
                        "group": selected_category,
                        "logo": logo,
                        "stream_id": stream_id,
                        "url": cmd,
                    }
                )
            xbmc.log(
                f"[Categories] Got {len(channels_in_category)} channels from server",
                level=xbmc.LOGINFO,
            )
        else:
            channels_in_category = []
    else:
        # Filter channels by the selected category from M3U
        channels_in_category = [
            ch for ch in all_channels if ch["group"] == selected_category
        ]

    # Add "Change MAC" button at the top
    change_mac_button = xbmcgui.ListItem(
        label="[COLOR orange]Schimbă adresa MAC[/COLOR]"
    )
    change_mac_button.setArt(
        {"icon": "DefaultIconInfo.png", "thumb": "DefaultIconInfo.png"}
    )
    change_mac_url = f"{_BASE_URL}?mode=change_mac&category={quote_plus(selected_category)}&server={server}&main_mode={main_mode if main_mode else ''}"
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE, url=change_mac_url, listitem=change_mac_button, isFolder=False
    )

    if not channels_in_category:
        if from_server and category_id:
            status = get_fetch_status("channels", server)
            xbmc.log(
                f"[Channels] No channels for {server}/{category_id}. Status: {status}",
                level=xbmc.LOGWARNING,
            )
            if status.get("portal_online") is False:
                primary_label = "[COLOR red]Nu se poate incarca lista de canale[/COLOR]"
                secondary_label = "[COLOR yellow]Portalul serverului pare indisponibil[/COLOR]"
            elif status.get("attempts", 0) > 0 and status.get("status") != "ok":
                primary_label = "[COLOR red]Nu se poate incarca lista de canale[/COLOR]"
                secondary_label = (
                    f"[COLOR yellow]S-au incercat {status['attempts']} MAC-uri diferite. "
                    "Încearcă din nou sau schimbă adresa MAC[/COLOR]"
                )
            else:
                primary_label = (
                    f'[COLOR red]Nu exista canale in categoria "{selected_category}"[/COLOR]'
                )
                secondary_label = "[COLOR yellow]Încearcă altă categorie sau alt server[/COLOR]"
        else:
            primary_label = (
                f'[COLOR red]Nu exista canale in categoria "{selected_category}"[/COLOR]'
            )
            secondary_label = "[COLOR yellow]Încearcă altă categorie sau alt server[/COLOR]"

        li = xbmcgui.ListItem(label=primary_label)
        li.setProperty("IsPlayable", "false")
        xbmcplugin.addDirectoryItem(handle=_HANDLE, url="", listitem=li, isFolder=False)
        li2 = xbmcgui.ListItem(label=secondary_label)
        xbmcplugin.addDirectoryItem(handle=_HANDLE, url="", listitem=li2, isFolder=False)
        xbmcplugin.endOfDirectory(_HANDLE)
        return

    # Only load and request EPG if enabled
    manager = get_epg_manager()
    if manager:
        # Set current server for EPG operations
        set_epg_current_server(server)

        # Reconfigure EPG manager for the current server
        portal_url = get_portal_url_for_server(server)
        if portal_url:
            manager.reconfigure(base_url=portal_url)

        # Load EPG cache first
        load_epg_cache()

        xbmc.log(
            f"[EPG] Category '{selected_category}' has {len(channels_in_category)} channels",
            level=xbmc.LOGINFO,
        )

        # Count how many channels already have EPG from cache
        channels_with_cached_epg = sum(
            1 for ch in channels_in_category if epg_contains(ch["stream_id"])
        )
        xbmc.log(
            f"[EPG] {channels_with_cached_epg}/{len(channels_in_category)} channels have cached EPG",
            level=xbmc.LOGINFO,
        )

        # Request EPG data for ALL channels in the category
        for channel in channels_in_category:
            manager.request(channel, size=10)

        # Calculate adaptive timeout based on number of channels and cache coverage
        num_channels = len(channels_in_category)
        cache_coverage = (
            channels_with_cached_epg / num_channels if num_channels > 0 else 0
        )

        if cache_coverage >= 0.8:
            # Good cache — give it a short window to fill missing entries.
            max_wait_time = min(2000, num_channels * 35)
            no_progress_limit = 500
            xbmc.log(
                f"[EPG] Good cache coverage ({cache_coverage:.0%}), waiting up to {max_wait_time}ms",
                level=xbmc.LOGINFO,
            )
        elif cache_coverage >= 0.3:
            # Partial cache — wait briefly, but favor fast list rendering.
            max_wait_time = min(1000, num_channels * 25)
            no_progress_limit = 500
            xbmc.log(
                f"[EPG] Partial cache coverage ({cache_coverage:.0%}), waiting up to {max_wait_time}ms",
                level=xbmc.LOGINFO,
            )
        else:
            # No local EPG cache: give the first fetch a realistic chance to populate.
            max_wait_time = min(1800, max(800, num_channels * 35))
            no_progress_limit = 1200
            xbmc.log(
                f"[EPG] Fetching fresh EPG, waiting up to {max_wait_time}ms",
                level=xbmc.LOGINFO,
            )

        wait_interval = 100
        waited = 0
        last_count = channels_with_cached_epg
        no_progress_since = 0

        while waited < max_wait_time:
            xbmc.sleep(wait_interval)
            waited += wait_interval

            channels_with_epg = sum(
                1 for ch in channels_in_category if epg_contains(ch["stream_id"])
            )

            if channels_with_epg != last_count:
                xbmc.log(
                    f"[EPG] Progress: {channels_with_epg}/{num_channels} ({waited}ms)",
                    level=xbmc.LOGDEBUG,
                )
                last_count = channels_with_epg
                no_progress_since = 0
            else:
                no_progress_since += wait_interval

            # All channels have EPG — no need to wait further
            if channels_with_epg >= num_channels:
                xbmc.log(
                    "[EPG] All channels have EPG, proceeding early", level=xbmc.LOGDEBUG
                )
                break

            # Stop waiting as soon as EPG stops progressing.
            if no_progress_since >= no_progress_limit:
                xbmc.log(
                    f"[EPG] No new EPG for {no_progress_limit}ms, proceeding with {channels_with_epg}/{num_channels}",
                    level=xbmc.LOGDEBUG,
                )
                break

        # Final count
        final_count = sum(
            1 for ch in channels_in_category if epg_contains(ch["stream_id"])
        )
        final_coverage = final_count / num_channels if num_channels > 0 else 0
        xbmc.log(
            f"[EPG] Final: {final_count}/{num_channels} channels ({final_coverage:.0%}) have EPG",
            level=xbmc.LOGINFO,
        )

        # Save updated EPG to cache
        save_epg_cache()

    # Create list items with EPG data
    for channel in channels_in_category:
        # Build channel label with current program
        channel_label = channel["name"]

        # Add current program to label if EPG available and enabled
        if is_epg_enabled() and epg_contains(channel["stream_id"]):
            epg_items = get_epg_items(channel["stream_id"])
            current_prog = get_current_program(epg_items)
            if current_prog:
                channel_label = f"{channel['name']} - {current_prog}"

        li = xbmcgui.ListItem(label=channel_label)

        # Set thumbnail from tvg-logo if available
        if channel["logo"]:
            li.setArt({"thumb": channel["logo"], "icon": channel["logo"]})

        li.setProperty("IsPlayable", "true")

        # Set EPG data if available and enabled
        if is_epg_enabled() and epg_contains(channel["stream_id"]):
            epg_items = get_epg_items(channel["stream_id"])
            plot = format_epg_tooltip(epg_items)
            li.setInfo("video", {"plot": plot})

        # Create URL to play this specific channel
        url = f"{_BASE_URL}?mode=play&stream_id={channel['stream_id']}&name={quote_plus(channel['name'])}&server={server}"
        if server == "server2" and channel.get("url"):
            url += f"&url_template={quote_plus(channel['url'])}"

        # Add context menu for favorites
        context_menu = []
        if channel["stream_id"] in favorite_stream_ids:
            context_menu.append(
                (
                    "Elimină din favorite",
                    f"RunPlugin({_BASE_URL}?mode=remove_from_favorites&stream_id={channel['stream_id']}&server={server})",
                )
            )
        else:
            add_fav_url = f"{_BASE_URL}?mode=add_to_favorites&stream_id={channel['stream_id']}&name={quote_plus(channel['name'])}&logo={quote_plus(channel['logo'])}&server={server}"
            if server == "server2" and channel.get("url"):
                add_fav_url += f"&url_template={quote_plus(channel['url'])}"
            context_menu.append(("Adaugă la favorite", f"RunPlugin({add_fav_url})"))
        li.addContextMenuItems(context_menu)

        xbmcplugin.addDirectoryItem(
            handle=_HANDLE, url=url, listitem=li, isFolder=False
        )

    xbmcplugin.endOfDirectory(_HANDLE)


def get_full_epg():
    """Fetch EPG for ALL channels from server."""
    # Get server from params
    params = get_params()
    server = params.get("server", "server1")
    set_epg_current_server(server)

    manager = get_epg_manager()
    if not manager:
        xbmcgui.Dialog().notification(
            "EPG dezactivat",
            "Activează EPG în setările addonului",
            xbmcgui.NOTIFICATION_INFO,
        )
        return

    portal_url = get_portal_url_for_server(server)
    if portal_url:
        manager.reconfigure(base_url=portal_url)

    # Get all channels from server
    xbmc.log(f"[EPG] Fetching all channels from {server}", level=xbmc.LOGINFO)

    # Fetch all channels from server
    all_channels = []
    server_cats = fetch_server_categories(server)

    if not server_cats:
        xbmcgui.Dialog().notification(
            "EPG", "Nu s-au putut încărca categoriile", xbmcgui.NOTIFICATION_WARNING
        )
        return

    # Fetch channels for each category
    for cat in server_cats[:5]:  # Limit to first 5 categories to avoid long loading
        cat_id = cat.get("id")
        channels = fetch_channels_by_category_from_server(cat_id, server)
        all_channels.extend(channels)
        xbmc.log(
            f"[EPG] Got {len(channels)} channels from category {cat.get('title')}",
            level=xbmc.LOGDEBUG,
        )

    if not all_channels:
        xbmcgui.Dialog().notification(
            "EPG", "Nu au fost găsite canale", xbmcgui.NOTIFICATION_WARNING
        )
        return

    total_channels = len(all_channels)
    xbmc.log(f"[EPG] Get Full EPG: Found {total_channels} channels", level=xbmc.LOGINFO)

    # Count how many already cached
    load_epg_cache()
    channels_with_cached_epg = sum(
        1
        for ch in all_channels
        if epg_contains_any(str(ch.get("id")), str(ch.get("tv_genre_id")))
    )
    xbmc.log(
        f"[EPG] {channels_with_cached_epg}/{total_channels} channels already have cached EPG",
        level=xbmc.LOGDEBUG,
    )

    # Create progress dialog
    progress = xbmcgui.DialogProgress()
    progress.create(
        "Descărcare EPG complet",
        f"Se solicită EPG pentru {total_channels} canale...",
    )

    # Request EPG for all channels
    for idx, channel in enumerate(all_channels):
        if progress.iscanceled():
            xbmc.log("[EPG] User cancelled full EPG fetch", level=xbmc.LOGDEBUG)
            progress.close()
            return

        manager.request(channel, size=10)

        # Update progress every 10 channels
        if (idx + 1) % 10 == 0:
            percent = int(((idx + 1) / total_channels) * 30)
            progress.update(
                percent,
                f"S-a solicitat EPG pentru {idx + 1}/{total_channels} canale...",
            )

    progress.update(30, "Se așteaptă datele EPG de la server...")

    # Calculate timeout based on total channels
    max_wait_time = min(300000, total_channels * 400)
    wait_interval = 500  # Check every 500ms
    waited = 0
    last_count = channels_with_cached_epg

    xbmc.log(
        f"[EPG] Waiting up to {max_wait_time}ms for {total_channels} channels",
        level=xbmc.LOGDEBUG,
    )

    while waited < max_wait_time:
        if progress.iscanceled():
            xbmc.log(
                "[EPG] User cancelled full EPG fetch during wait", level=xbmc.LOGDEBUG
            )
            progress.close()
            save_epg_cache()
            return

        xbmc.sleep(wait_interval)
        waited += wait_interval

        # Check progress
        channels_with_epg = sum(
            1 for ch in all_channels if epg_contains(str(ch.get("id", "")))
        )

        # Update progress dialog (30% to 95%)
        progress_percent = 30 + int(((channels_with_epg / total_channels) * 65))
        coverage_percent = int((channels_with_epg / total_channels) * 100)
        progress.update(
            progress_percent,
            f"Received EPG for {channels_with_epg}/{total_channels} channels ({coverage_percent}%)\nElapsed: {waited // 1000}s / {max_wait_time // 1000}s",
        )

        # Log progress if changed
        if channels_with_epg != last_count:
            xbmc.log(
                f"[EPG] Full EPG Progress: {channels_with_epg}/{total_channels} ({coverage_percent}%) - {waited}ms elapsed",
                level=xbmc.LOGDEBUG,
            )
            last_count = channels_with_epg

        # Exit only if no progress for 10 seconds
        if waited >= 10000 and channels_with_epg == channels_with_cached_epg:
            xbmc.log(
                f"[EPG] No new EPG after 10s, finishing with {channels_with_epg}/{total_channels}",
                level=xbmc.LOGDEBUG,
            )
            break

    # Final save
    progress.update(95, "Se salvează EPG în cache...")
    save_epg_cache()

    # Final stats
    final_count = sum(1 for ch in all_channels if epg_contains(str(ch.get("id", ""))))
    final_coverage = int((final_count / total_channels) * 100)

    progress.update(
        100,
        f"Complet! EPG pentru {final_count}/{total_channels} canale ({final_coverage}%)",
    )
    xbmc.sleep(1500)  # Show final message for 1.5 seconds
    progress.close()

    xbmc.log(
        f"[EPG] Full EPG fetch complete: {final_count}/{total_channels} ({final_coverage}%)",
        level=xbmc.LOGDEBUG,
    )
    xbmcgui.Dialog().notification(
        "EPG complet",
        f"EPG disponibil pentru {final_count}/{total_channels} canale ({final_coverage}%)",
        xbmcgui.NOTIFICATION_INFO,
        3000,
    )


def generate_random_mac():
    """Generate a random MAC address in the format 00:1A:79:XX:XX:XX"""
    # Using the same manufacturer prefix as existing MACs in the file
    prefix = "00:1A:79"
    # Generate 3 random bytes for the last part
    suffix = ":".join([f"{random.randint(0, 255):02X}" for _ in range(3)])
    return f"{prefix}:{suffix}"


def change_mac(category=None, server="server1"):
    """Change to a new random MAC address and clear token cache."""
    # Get a new random MAC from file
    new_mac = get_random_mac_from_file(server)
    if not new_mac:
        xbmcgui.Dialog().notification(
            "Eroare", "Nu s-a putut obține o adresă MAC nouă", xbmcgui.NOTIFICATION_ERROR
        )
        return

    # Clear token cache to force new handshake with new MAC
    clear_token_cache()
    invalidate_server_auth(server)
    _selected_mac_override[server] = new_mac

    xbmc.log(f"[MAC] Changed to new MAC: {new_mac}", level=xbmc.LOGDEBUG)
    xbmcgui.Dialog().notification(
        "Adresă MAC schimbată", f"Noua adresă MAC: {new_mac}", xbmcgui.NOTIFICATION_INFO, 3000
    )

    # Refresh the category view if we came from a category
    if category:
        xbmc.executebuiltin(f"Container.Refresh")


def play_stream(
    stream_id,
    name,
    server="server1",
    url_template=None,
    session_id=None,
    attempted_macs=None,
    reconnect_count=0,
    autoplay_reconnect=False,
):
    """Get the token and MAC dynamically and resolve the URL for a single stream."""
    try:
        reconnect_count = int(reconnect_count or 0)
    except (TypeError, ValueError):
        reconnect_count = 0

    if not session_id:
        clear_playback_state()

    attempted_mac_list = _parse_attempted_macs_param(attempted_macs)
    auth_max_attempts = get_auth_max_attempts()
    portal_url = get_portal_url_for_server(server)
    if not portal_url:
        _finalize_playback_failure(
            server,
            portal_url,
            0,
            "Portal URL is not set in settings.",
            "Redarea canalului",
            session_id=session_id,
        )
        return

    # Check if this is a Server 2 stream (stream_id starts with s2_)
    if stream_id.startswith("s2_"):
        xbmc.log(f"--- SERVER 2 PLAYBACK START: {name} ---", level=xbmc.LOGDEBUG)

        url_line = url_template
        # Fallback if url_template was not provided (e.g., from old favorites)
        if not url_line:
            addon_path = _ADDON.getAddonInfo("path")
            m3u_file = os.path.join(addon_path, "mag.txt")
            xbmc.log(
                f"[Server 2] Falling back to read M3U file from {m3u_file}",
                level=xbmc.LOGDEBUG,
            )

            try:
                with open(m3u_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()

                channel_index = int(stream_id.split("_")[1])
                channel_count = 0

                for i, line in enumerate(lines):
                    line = line.strip()
                    if line.startswith("#EXTINF:") or "#EXTINF:" in line.upper():
                        if i + 1 < len(lines):
                            pot_url = lines[i + 1].strip()
                            if (
                                pot_url
                                and not pot_url.startswith("#")
                                and "MACPH" in pot_url
                                and "TOKENPH" in pot_url
                            ):
                                if channel_count == channel_index:
                                    url_line = pot_url
                                    break
                                channel_count += 1
            except Exception as e:
                clear_playback_state(session_id)
                xbmcgui.Dialog().notification(
                    "Eroare", f"Nu s-a putut încărca mag.txt: {e}", xbmcgui.NOTIFICATION_ERROR
                )
                return

        if not url_line:
            clear_playback_state(session_id)
            xbmcgui.Dialog().notification(
                "Eroare",
                "Canalul nu a fost găsit sau lipsește șablonul URL",
                xbmcgui.NOTIFICATION_ERROR,
            )
            return

        # Found our channel! Extract stream ID from URL
        stream_id_match = RE_STREAM_ID.search(url_line)
        if stream_id_match:
            actual_stream_id = stream_id_match.group(1)

            # Perform handshake to get token
            # Extract portal URL from the URL template
            portal_match = re.match(r"(https?://[^/]+)", url_line)
            if portal_match:
                server2_portal_url = portal_match.group(1)
                candidate_macs = get_candidate_macs(
                    server, exclude_macs=attempted_mac_list, limit=auth_max_attempts
                )

                if not candidate_macs:
                    _finalize_playback_failure(
                        server,
                        server2_portal_url,
                        0,
                        "Nu exista MAC-uri configurate pentru acest server.",
                        "Redarea canalului",
                        session_id=session_id,
                    )
                    return

                def _server2_attempt_provider(_attempted_macs):
                    for random_mac in candidate_macs:
                        yield {"mac": random_mac, "portal_url": server2_portal_url}

                def _server2_attempt_executor(attempt_entry, attempts, attempted_macs):
                    random_mac = attempt_entry["mac"]
                    session_token, random_val = handshake(
                        server2_portal_url, random_mac, server=server
                    )
                    if not session_token:
                        last_error = f"Handshake failed for MAC {random_mac}"
                        note_failed_mac(server, random_mac)
                        xbmc.log(
                            f"[{server}] {last_error}",
                            level=xbmc.LOGWARNING,
                        )
                        return {
                            "success": False,
                            "error": last_error,
                            "break": not check_server_online(server2_portal_url),
                        }

                    headers, cookies = _build_auth_headers_and_cookies(
                        server2_portal_url, random_mac, session_token, random_val
                    )
                    create_link_url = f"{server2_portal_url}/portal.php?action=create_link&type=itv&cmd={actual_stream_id}&JsHttpRequest=1-xml"

                    try:
                        response = get_session().get(
                            create_link_url,
                            headers=headers,
                            cookies=cookies,
                            timeout=TIMEOUTS["playlink"],
                            verify=False,
                        )
                        response.raise_for_status()
                        link_data = response.json()
                        returned_cmd = _extract_live_returned_cmd(link_data)
                        play_token = _extract_play_token(
                            returned_cmd, "Raspunsul nu contine play_token valid."
                        )

                        final_url = url_line.replace("MACPH", random_mac).replace(
                            "TOKENPH", play_token
                        )
                        
                        is_valid, probe_reason, redirected_url = _probe_stream_url(
                            final_url,
                            headers=headers,
                            allow_body_read=False,
                        )
                        if not is_valid:
                            raise ValueError(
                                f"Linkul final a picat la verificare: {probe_reason}"
                            )
                        return {
                            "success": True,
                            "resolved_url": final_url,
                            "cache_token": session_token,
                            "random": random_val,
                        }
                    except Exception as e:
                        last_error = str(e) or "Niciun stream valid găsit."
                        _handle_live_attempt_failure(
                            server,
                            random_mac,
                            attempts,
                            last_error,
                            server,
                        )
                        return {
                            "success": False,
                            "error": last_error,
                            "break": not check_server_online(server2_portal_url),
                        }

                session_id = _run_live_playback_attempts(
                    server=server,
                    name=name,
                    stream_id=stream_id,
                    attempted_mac_list=attempted_mac_list,
                    reconnect_count=reconnect_count,
                    session_id=session_id,
                    attempt_provider=_server2_attempt_provider,
                    attempt_executor=_server2_attempt_executor,
                    url_template=url_template,
                    total_attempts=auth_max_attempts,
                    progress_total=len(candidate_macs),
                    allow_retry_prompt=True,
                )
                return
            else:
                clear_playback_state(session_id)
                xbmcgui.Dialog().notification(
                    "Eroare",
                    "Nu s-a putut extrage URL-ul portalului din șablon",
                    xbmcgui.NOTIFICATION_ERROR,
                )
                return
        else:
            clear_playback_state(session_id)
            xbmcgui.Dialog().notification(
                "Eroare",
                "Nu s-a putut extrage ID-ul streamului din URL",
                xbmcgui.NOTIFICATION_ERROR,
            )
            return

    def _server1_attempt_provider(attempted_macs):
        for token, headers, cookies, portal_url, random_mac, random_val in iter_server_auth_candidates(
            server=server,
            use_cached=True,
            exclude_macs=list(attempted_macs),
            max_attempts=auth_max_attempts,
        ):
            yield {
                "token": token,
                "headers": headers,
                "cookies": cookies,
                "portal_url": portal_url,
                "mac": random_mac,
                "random": random_val,
            }

    def _server1_attempt_executor(attempt_entry, attempts, attempted_macs):
        headers = attempt_entry["headers"]
        cookies = attempt_entry["cookies"]
        portal_url = attempt_entry["portal_url"]
        random_mac = attempt_entry["mac"]
        token = attempt_entry["token"]
        random_val = attempt_entry["random"]
        
        xbmc.log(
            f"[Server1] Attempt {attempts}/{auth_max_attempts} with MAC: {random_mac}",
            level=xbmc.LOGINFO,
        )

        # Use create_link first. The handshake token authenticates the portal
        # request; the stream URL needs a per-stream play_token from create_link.
        create_link_url = f"{portal_url.rstrip('/')}/portal.php?type=itv&action=create_link&cmd={stream_id}&JsHttpRequest=1-xml"

        try:
            response = get_session().get(
                create_link_url,
                headers=headers,
                cookies=cookies,
                timeout=TIMEOUTS["playlink"],
                verify=False,
            )
            response.raise_for_status()
            link_data = response.json()
            returned_cmd = _extract_live_returned_cmd(link_data)
            play_token = _extract_play_token(
                returned_cmd, "Raspunsul nu contine play_token valid."
            )
            final_url = f"{portal_url.rstrip('/')}/play/live.php?mac={random_mac}&stream={stream_id}&extension=ts&play_token={play_token}"

            is_valid, probe_reason, redirected_url = _probe_stream_url(
                final_url,
                headers=headers,
                allow_body_read=False,
            )
            if not is_valid:
                raise ValueError(
                    f"create_link a returnat URL invalid pentru Kodi: {probe_reason}"
                )

            xbmc.log(
                f"[Server1] Successfully created play URL via create_link with MAC: {random_mac}",
                level=xbmc.LOGINFO,
            )
            return {
                "success": True,
                "resolved_url": redirected_url or final_url,
                "cache_token": token,
                "random": random_val,
            }

        except Exception as e:
            xbmc.log(
                f"[Server1] create_link failed for MAC {random_mac}: {e}",
                level=xbmc.LOGDEBUG,
            )

        fallback_urls = [
            (
                f"{portal_url.rstrip('/')}/play/live.php?mac={random_mac}&stream={stream_id}&extension=ts",
                "direct no token",
            ),
            (
                f"{portal_url.rstrip('/')}/play/live.php?mac={random_mac}&stream={stream_id}&extension=ts&play_token={token}",
                "direct session token",
            ),
        ]
        last_error = "Niciun stream valid găsit."
        for test_url, label in fallback_urls:
            is_valid, probe_reason, redirected_url = _probe_stream_url(
                test_url,
                headers=headers,
                allow_body_read=False,
            )
            if is_valid:
                xbmc.log(
                    f"[Server1] Direct playback valid ({label}) for MAC: {random_mac}",
                    level=xbmc.LOGINFO,
                )
                return {
                    "success": True,
                    "resolved_url": redirected_url or test_url,
                    "cache_token": token,
                    "random": random_val,
                }

            last_error = f"{label}: {probe_reason}"
            xbmc.log(
                f"[Server1] Direct playback failed ({label}, {probe_reason}) for MAC: {random_mac}",
                level=xbmc.LOGDEBUG,
            )

        _handle_live_attempt_failure(server, random_mac, attempts, last_error, "Server1")
        return {
            "success": False,
            "error": last_error,
            "break": not check_server_online(portal_url),
        }

    _run_live_playback_attempts(
        server=server,
        name=name,
        stream_id=stream_id,
        attempted_mac_list=attempted_mac_list,
        reconnect_count=reconnect_count,
        session_id=session_id,
        attempt_provider=_server1_attempt_provider,
        attempt_executor=_server1_attempt_executor,
        url_template=url_template,
        total_attempts=auth_max_attempts,
        allow_retry_prompt=True,
    )


def show_settings_menu(server="server1", is_main=False):
    """Show settings submenu."""
    # Setari addon
    settings_item = xbmcgui.ListItem(label="Setari addon")
    settings_item.setArt(
        {"icon": "DefaultAddonService.png", "thumb": "DefaultAddonService.png"}
    )
    settings_url = f"{_BASE_URL}?mode=settings&server={server}"
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE, url=settings_url, listitem=settings_item, isFolder=False
    )

    if not is_main:
        # Sterge cache (pt. acest server)
        clear_cache_item = xbmcgui.ListItem(label="Sterge cache (pt. acest server)")
        clear_cache_item.setArt(
            {
                "icon": "DefaultAddonRepository.png",
                "thumb": "DefaultAddonRepository.png",
            }
        )
        clear_cache_url = f"{_BASE_URL}?mode=clear_cache&server={server}"
        xbmcplugin.addDirectoryItem(
            handle=_HANDLE,
            url=clear_cache_url,
            listitem=clear_cache_item,
            isFolder=False,
        )

    # Sterge tot cache (Clear Cache)
    label_clear = "Sterge tot cache" if not is_main else "Clear Cache"
    clear_all_cache_item = xbmcgui.ListItem(label=label_clear)
    clear_all_cache_item.setArt(
        {"icon": "DefaultAddonRepository.png", "thumb": "DefaultAddonRepository.png"}
    )
    clear_all_cache_url = f"{_BASE_URL}?mode=clear_all_cache"
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE,
        url=clear_all_cache_url,
        listitem=clear_all_cache_item,
        isFolder=False,
    )

    xbmcplugin.endOfDirectory(_HANDLE)


def _list_servers_page(available_servers, server_statuses=None):
    """Render the server selection directory page.

    Args:
        available_servers: list of server dicts from servers.json
        server_statuses:   dict {srv_id: bool} or None.
                           When None, no ON/OFF badge is shown (fast path).
    Always appends an on-demand 'Verificare servere' button at the bottom.
    """
    for srv in available_servers:
        srv_name = srv.get("name", srv.get("id", "Unknown"))
        srv_id = srv.get("id", "server1")
        
        # Count MACs for this server
        macs = srv.get("macs", [])
        mac_count = len(macs)

        if server_statuses is not None:
            is_online = server_statuses.get(srv_id, False)
            status = (
                "[COLOR green]● ON[/COLOR]" if is_online else "[COLOR red]● OFF[/COLOR]"
            )
            label = f"{srv_name} - {mac_count} MACs  {status}"
        else:
            label = f"{srv_name} - {mac_count} MACs"

        li = xbmcgui.ListItem(label=label)
        li.setArt({"icon": "DefaultNetwork.png", "thumb": "DefaultNetwork.png"})
        xbmcplugin.addDirectoryItem(
            handle=_HANDLE,
            url=f"{_BASE_URL}?mode=open_server&server={srv_id}",
            listitem=li,
            isFolder=False,
        )

    # On-demand check button — always visible regardless of the auto-check setting
    check_btn = xbmcgui.ListItem(label="[COLOR cyan]>> Verificare servere[/COLOR]")
    check_btn.setArt(
        {"icon": "DefaultAddonRepository.png", "thumb": "DefaultAddonRepository.png"}
    )
    xbmcplugin.addDirectoryItem(
        handle=_HANDLE,
        url=f"{_BASE_URL}?mode=check_servers",
        listitem=check_btn,
        isFolder=True,
    )

    xbmcplugin.endOfDirectory(_HANDLE)


def _check_all_servers_online(servers_list):
    """Check all servers online status in parallel. Returns dict {srv_id: bool}."""
    if not servers_list:
        return {}

    def _check(srv):
        srv_id = srv.get("id", "")
        portal_url = srv.get("portal_url", "")
        return srv_id, check_server_online(portal_url)

    statuses = {srv.get("id", ""): False for srv in servers_list}
    executor = ThreadPoolExecutor(max_workers=min(len(servers_list), 10))
    try:
        futures = {executor.submit(_check, srv): srv for srv in servers_list}
        try:
            for future in as_completed(futures, timeout=8):
                try:
                    srv_id, is_online = future.result()
                    statuses[srv_id] = is_online
                except Exception as exc:
                    srv = futures[future]
                    xbmc.log(
                        f"[ServerCheck] {srv.get('id', '?')} probe error: {exc}",
                        level=xbmc.LOGWARNING,
                    )
        except FuturesTimeoutError:
            xbmc.log(
                "[ServerCheck] 8s global timeout reached; slow servers marked offline",
                level=xbmc.LOGWARNING,
            )
    finally:
        executor.shutdown(wait=False)
    return statuses


def router(params):
    """Router function with global error handling"""
    try:
        xbmc.log(f"[Router] params: {params}", level=xbmc.LOGDEBUG)
        server = params.get("server")
        mode = params.get("mode")

        # If no server specified and no mode, show main menu
        if server is None and mode is None:
            main_menu()
            return

        # Static World Cup pages do not depend on servers, authentication, or
        # the playlist search index. Keep them usable on a clean installation.
        if mode == "world_cup_2026":
            list_world_cup_matches(_BASE_URL, _HANDLE)
            return

        if mode == "world_cup_match":
            list_world_cup_match_channels(
                _BASE_URL, _HANDLE, params.get("match_id")
            )
            return

        # Keep servers.json cached for a short TTL instead of refetching on every request.
        servers_config = load_servers_config()
        available_servers = servers_config.get("servers", [])

        # Handle clear_all_cache mode early (doesn't require server)
        if mode == "clear_all_cache":
            xbmc.log("[Router] Processing clear_all_cache mode", level=xbmc.LOGINFO)
            clear_all_cache_for_all_servers()
            clear_vod_series_cache()
            clear_search_cache()
            xbmc.executebuiltin("Container.Refresh")
            return

        if mode == "open_section":
            main_mode = params.get("main_mode")
            force_check = params.get("force_check") == "true"
            selected_server = select_server_dialog(main_mode, force_check=force_check)
            if selected_server:
                xbmc.executebuiltin(
                    f"Container.Update({_build_selected_server_target(main_mode, selected_server)},replace)"
                )
            return

        if mode == "open_server":
            target = _build_selected_server_target(None, server)
            xbmcplugin.endOfDirectory(
                _HANDLE, succeeded=True, updateListing=False, cacheToDisc=False
            )
            xbmc.executebuiltin(f"Container.Update({target},replace)")
            return

        # Handle select_server mode
        if mode == "select_server":
            main_mode = params.get("main_mode")
            force_check = params.get("force_check") == "true"
            selected_server = select_server_dialog(main_mode, force_check=force_check)

            if selected_server:
                xbmcplugin.endOfDirectory(
                    _HANDLE, succeeded=True, updateListing=False, cacheToDisc=False
                )
                xbmc.executebuiltin(
                    f"Container.Update({_build_selected_server_target(main_mode, selected_server)},replace)"
                )
            else:
                # If user cancelled dialog, we must end the directory listing to stop the spinner
                xbmcplugin.endOfDirectory(_HANDLE, succeeded=False)
            return

        # Handle VOD and Series specific modes
        if mode == "list_vod_items":
            list_vod_items(params.get("category_id"), server=server)
            return
        elif mode == "list_series_items":
            list_series_items(params.get("category_id"), server=server)
            return
        elif mode == "list_seasons":
            list_seasons(params.get("movie_id"), server=server)
            return
        elif mode == "list_episodes":
            list_episodes(
                params.get("movie_id"), params.get("season_id"), server=server
            )
            return
        elif mode == "play_vod":
            play_vod(params.get("movie_id"), server=server)
            return
        elif mode == "play_series":
            play_series(params.get("cmd"), params.get("episode"), server=server)
            return
        elif mode == "list_vod_categories":
            list_vod_categories(server=server)
            return
        elif mode == "list_series_categories":
            list_series_categories(server=server)
            return

        # Handle modes that don't strictly require a pre-selected server or handle it themselves
        if mode == "settings_menu":
            is_main = params.get("is_main") == "true"
            show_settings_menu(server=server if server else "server1", is_main=is_main)
            return
        elif mode == "settings":
            _ADDON.openSettings()
            xbmc.executebuiltin("Container.Refresh")
            return
        elif mode == "favorites":
            list_favorites(_BASE_URL, _HANDLE, server=server if server else "server1")
            return
        elif mode == "mega_search_menu":
            mega_search_menu()
            return
        elif mode == "reindex_ratb":
            progress = xbmcgui.DialogProgress()
            progress.create(
                "Index ratb",
                "Se verifică indexul remote...",
            )
            try:
                def update_progress(percent, message):
                    if progress.iscanceled():
                        raise InterruptedError("Actualizarea a fost anulată.")
                    progress.update(percent, message)

                result = update_playlist_index(
                    force=True,
                    progress_callback=update_progress,
                    session=get_session(),
                )
                clear_search_cache()
                manifest = result.get("manifest") or {}
                if result.get("updated"):
                    message = (
                        f"{manifest.get('playlist_count', 0)} playlisturi, "
                        f"{manifest.get('channel_count', 0)} canale"
                    )
                else:
                    message = "Indexul ratb este deja actualizat"
                xbmcgui.Dialog().notification(
                    "Index ratb",
                    message,
                    xbmcgui.NOTIFICATION_INFO,
                    5000,
                )
            except InterruptedError:
                xbmcgui.Dialog().notification(
                    "Index ratb",
                    "Reindexarea a fost anulată",
                    xbmcgui.NOTIFICATION_INFO,
                    3000,
                )
            except Exception as exc:
                xbmc.log(
                    f"[PlaylistSearch] Manual remote update failed: {exc}",
                    level=xbmc.LOGERROR,
                )
                xbmcgui.Dialog().notification(
                    "Eroare index ratb",
                    str(exc),
                    xbmcgui.NOTIFICATION_ERROR,
                    5000,
                )
            finally:
                progress.close()
            return
        elif mode == "mega_search_input":
            mega_search_input(params.get("search_type"))
            return
        elif mode == "mega_search_results":
            show_mega_search_results(
                params.get("query"),
                params.get("search_type"),
                batch_start=params.get("batch_start", 0),
                skip_api=params.get("skip_api") == "true",
            )
            return
        elif mode == "saved_searches":
            list_saved_searches(_BASE_URL, _HANDLE)
            return
        elif mode == "add_saved_search":
            add_saved_search(
                params.get("query"),
                params.get("search_type"),
                server=params.get("server"),
                main_mode=params.get("main_mode"),
            )
            return
        elif mode == "remove_saved_search":
            remove_saved_search(
                params.get("query"),
                params.get("search_type"),
                server=params.get("server"),
                main_mode=params.get("main_mode"),
            )
            return
        elif mode == "global_favorites":
            list_global_favorites(_BASE_URL, _HANDLE, get_session_server_statuses)
            return
        elif mode == "search_input":
            search_input_dialog(server=server, main_mode=params.get("main_mode"))
            return
        elif mode == "search_results":
            # Display search results (can be called with query or search_query param)
            query = params.get("query") or params.get("search_query")
            if query:
                show_search_results(
                    query,
                    server=server,
                    main_mode=params.get("main_mode"),
                )
            else:
                # No query, show search input dialog
                search_input_dialog(server=server)
            return
        elif mode == "search_input_vod":
            search_input_dialog_vod(server=server)
            return
        elif mode == "search_results_vod":
            # Display VOD search results
            query = params.get("query") or params.get("search_query")
            if query:
                show_vod_search_results(query, server=server)
            else:
                search_input_dialog_vod(server=server)
            return
        elif mode == "search_input_series":
            search_input_dialog_series(server=server)
            return
        elif mode == "search_results_series":
            # Display Series search results
            query = params.get("query") or params.get("search_query")
            if query:
                show_series_search_results(query, server=server)
            else:
                search_input_dialog_series(server=server)
            return

        # On-demand server check (triggered by the 'Verificare servere' button)
        if mode == "check_servers":
            xbmc.log("[Router] On-demand server check triggered", level=xbmc.LOGINFO)
            server_statuses = _check_all_servers_online(available_servers)
            xbmc.log(
                f"[Router] On-demand statuses: {server_statuses}", level=xbmc.LOGINFO
            )
            _list_servers_page(available_servers, server_statuses)
            return

        # If no server specified, fallback to first server or list servers page
        if server is None:
            if len(available_servers) > 1:
                if is_server_check_enabled():
                    xbmc.log(
                        "[Router] Auto server check enabled, checking status...",
                        level=xbmc.LOGINFO,
                    )
                    server_statuses = _check_all_servers_online(available_servers)
                    xbmc.log(
                        f"[Router] Server statuses: {server_statuses}",
                        level=xbmc.LOGINFO,
                    )
                else:
                    server_statuses = None
                _list_servers_page(available_servers, server_statuses)
                return
            elif len(available_servers) == 1:
                server = available_servers[0].get("id", "server1")
            else:
                # Fallback to default
                server = "server1"

        params["server"] = server

        mode = params.get("mode")

        xbmc.log(f"[Router] params: {params}", level=xbmc.LOGDEBUG)
        xbmc.log(f"[Router] mode: {mode}", level=xbmc.LOGDEBUG)

        if mode in (
            "play",
            "add_to_favorites",
            "remove_from_favorites",
        ):
            if "stream_id" not in params:
                xbmc.log(
                    f"[Router] Missing stream_id for mode: {mode}", level=xbmc.LOGERROR
                )
                xbmcgui.Dialog().notification(
                    "Eroare", "Lipsește ID-ul streamului", xbmcgui.NOTIFICATION_ERROR
                )
                return

        if mode == "play":
            play_stream(
                params.get("stream_id"),
                params.get("name", "Unknown"),
                server=server,
                url_template=params.get("url_template"),
                session_id=params.get("session_id"),
                attempted_macs=params.get("attempted_macs"),
                reconnect_count=params.get("reconnect_count", 0),
                autoplay_reconnect=params.get("autoplay_reconnect") == "true",
            )
        elif mode == "add_to_favorites":
            add_to_favorites(
                params.get("stream_id"),
                params.get("name", "Unknown"),
                params.get("logo", ""),
                server=server,
                url_template=params.get("url_template"),
            )
        elif mode == "remove_from_favorites":
            remove_from_favorites(params.get("stream_id"), server=server)

        if server == "both" and mode is None:
            if is_server_check_enabled():
                server_statuses = _check_all_servers_online(available_servers)
            else:
                server_statuses = None
            _list_servers_page(available_servers, server_statuses)
            return

        if mode is None or mode == "list_channels":
            list_channels(
                server=server,
                category=params.get("category"),
                category_id=params.get("cat_id"),
                from_server=params.get("from_server") == "true",
                main_mode=params.get("main_mode"),
            )
        elif mode == "get_full_epg":
            get_full_epg()
        elif mode == "refresh_cache":
            # Refresh cache for current server
            server = params.get("server", "server1")
            main_mode = params.get("main_mode")
            
            # Clear cache for this server
            clear_all_cache(server)
            clear_vod_series_cache(server=server)
            clear_search_cache(server=server)
            
            # Show notification
            xbmcgui.Dialog().notification(
                "Cache Reîmprospătat",
                f"Cache-ul pentru {server} a fost șters",
                xbmcgui.NOTIFICATION_INFO,
                2000
            )
            
            # Refresh the container to reload the list
            xbmc.executebuiltin("Container.Refresh")
        elif mode == "change_mac":
            change_mac(params.get("category"), server=server)
        elif mode == "clear_cache":
            clear_all_cache(server=server if server else "server1")
            clear_vod_series_cache(server=server if server else "server1")
            clear_search_cache(server=server if server else "server1")
            xbmc.executebuiltin("Container.Refresh")

    except KeyError as e:
        xbmc.log(
            f"[Router] KeyError: {e}, mode: {params.get('mode')}, params: {params}",
            level=xbmc.LOGERROR,
        )
        xbmcgui.Dialog().notification(
            "Eroare", f"Lipsește parametrul: {e}", xbmcgui.NOTIFICATION_ERROR
        )
    except Exception as e:
        xbmc.log(
            f"[Router] Unexpected error: {type(e).__name__}: {e}", level=xbmc.LOGERROR
        )
        xbmc.log(
            f"[Router] Traceback:\n{traceback.format_exc()}",
            level=xbmc.LOGERROR,
        )
        xbmcgui.Dialog().notification(
            "Eroare",
            f"A apărut o eroare neașteptată: {type(e).__name__}",
            xbmcgui.NOTIFICATION_ERROR,
        )


def mega_search_input(search_type):
    search_mega_search_input(_BASE_URL, search_type)


def show_mega_search_results(query, search_type, batch_start=0, skip_api=False):
    render_mega_search_results(
        _BASE_URL,
        _HANDLE,
        query,
        search_type,
        load_servers_config,
        fetch_stalker_search,
        fetch_channels_by_category_from_server,
        load_channels_cache,
        load_cached_category_channels,
        _CHANNELS_CACHE_TTL,
        should_mega_search_fetch_missing_lists(),
        get_mega_search_fetch_batch_size(),
        batch_start,
        skip_api,
        RE_STREAM_ID,
        search_playlist_index,
        get_mega_search_mode(),
    )


def search_input_dialog(server="server1", main_mode=None):
    render_search_input_dialog(_BASE_URL, _HANDLE, server=server, main_mode=main_mode)


def search_input_dialog_vod(server="server1"):
    render_search_input_dialog_vod(_BASE_URL, _HANDLE, server=server)


def search_input_dialog_series(server="server1"):
    render_search_input_dialog_series(_BASE_URL, _HANDLE, server=server)


def fetch_stalker_search(type_param, query, server="server1"):
    return search_fetch_stalker_search(
        type_param,
        query,
        server,
        get_server_auth,
        get_session,
        TIMEOUTS,
        json_loads,
    )


def show_search_results(query, server="server1", main_mode=None):
    render_search_results(
        _BASE_URL,
        _HANDLE,
        query,
        server,
        main_mode,
        fetch_stalker_search,
        fetch_server_categories,
        get_romanian_categories,
        get_sport_categories,
        load_channels_cache,
        load_cached_category_channels,
        _CHANNELS_CACHE_TTL,
        load_favorite_stream_ids,
        is_epg_enabled,
        epg_contains,
        get_epg_items,
        get_current_program,
        format_epg_tooltip,
        RE_STREAM_ID,
    )


def show_vod_search_results(query, server="server1"):
    render_vod_search_results(
        _BASE_URL, _HANDLE, query, server, fetch_stalker_search
    )


def show_series_search_results(query, server="server1"):
    render_series_search_results(
        _BASE_URL, _HANDLE, query, server, fetch_stalker_search
    )


def run():
    global _BASE_URL, _HANDLE
    _BASE_URL = sys.argv[0]
    _HANDLE = int(sys.argv[1])
    check_version_compatibility()
    router(get_params())
