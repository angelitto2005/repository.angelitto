import os
from urllib.parse import quote_plus

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

from hublive_backend import json_dumps, json_loads, reload_servers_config


def get_favorites_file(server):
    try:
        profile_path = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo("profile"))
    except Exception:
        profile_path = xbmc.translatePath(xbmcaddon.Addon().getAddonInfo("profile"))
    if not os.path.exists(profile_path):
        os.makedirs(profile_path)
    return os.path.join(profile_path, f"favorites_{server}.json")


def load_favorites(server):
    favorites_file = get_favorites_file(server)
    try:
        with open(favorites_file, "r", encoding="utf-8") as handle:
            favorites = json_loads(handle)
        return favorites if isinstance(favorites, list) else []
    except (FileNotFoundError, ValueError, TypeError):
        return []


def load_favorite_stream_ids(server):
    return {fav.get("stream_id") for fav in load_favorites(server) if fav.get("stream_id")}


def list_global_favorites(base_url, handle, get_session_server_statuses):
    xbmcplugin.setPluginCategory(handle, "Favorite")
    xbmcplugin.setContent(handle, "videos")

    servers_config = reload_servers_config()
    available_servers = servers_config.get("servers", [])
    server_statuses = get_session_server_statuses()
    all_favorites = []

    for server in available_servers:
        server_id = server.get("id")
        server_name = server.get("name", server_id)
        if server_statuses and not server_statuses.get(server_id, False):
            continue

        for favorite in load_favorites(server_id):
            favorite["_server_id"] = server_id
            favorite["_server_name"] = server_name
            all_favorites.append(favorite)

    if not all_favorites:
        li = xbmcgui.ListItem(
            label="[COLOR yellow]Nu există canale favorite (sau serverele sunt OFF).[/COLOR]"
        )
        xbmcplugin.addDirectoryItem(handle=handle, url="", listitem=li, isFolder=False)
        xbmcplugin.endOfDirectory(handle)
        return

    for favorite in all_favorites:
        display_label = (
            f"{favorite['name']} - [COLOR cyan]{favorite['_server_name']}[/COLOR]"
        )
        li = xbmcgui.ListItem(label=display_label)
        logo = favorite.get("logo", "")
        if logo:
            li.setArt({"thumb": logo, "icon": logo})
        li.setProperty("IsPlayable", "true")
        li.getVideoInfoTag().setTitle(favorite["name"])

        url = (
            f"{base_url}?mode=play&stream_id={favorite['stream_id']}"
            f"&name={quote_plus(favorite['name'])}&server={favorite['_server_id']}"
        )
        if favorite["_server_id"] == "server2" and favorite.get("url_template"):
            url += f"&url_template={quote_plus(favorite['url_template'])}"

        li.addContextMenuItems(
            [
                (
                    "Elimină din favorite",
                    f"RunPlugin({base_url}?mode=remove_from_favorites&stream_id={favorite['stream_id']}&server={favorite['_server_id']})",
                )
            ]
        )
        xbmcplugin.addDirectoryItem(handle=handle, url=url, listitem=li, isFolder=False)

    xbmcplugin.endOfDirectory(handle)


def list_favorites(base_url, handle, server="server1"):
    change_mac_button = xbmcgui.ListItem(label="[COLOR orange]Schimbă adresa MAC[/COLOR]")
    change_mac_button.setArt(
        {"icon": "DefaultIconInfo.png", "thumb": "DefaultIconInfo.png"}
    )
    change_mac_url = f"{base_url}?mode=change_mac&category=favorites&server={server}"
    xbmcplugin.addDirectoryItem(
        handle=handle,
        url=change_mac_url,
        listitem=change_mac_button,
        isFolder=False,
    )

    favorites = load_favorites(server)
    if not favorites:
        li = xbmcgui.ListItem(label="[COLOR yellow]Nu există canale favorite.[/COLOR]")
        li.setProperty("IsPlayable", "false")
        xbmcplugin.addDirectoryItem(handle=handle, url="", listitem=li, isFolder=False)
        xbmcplugin.endOfDirectory(handle)
        return

    for favorite in favorites:
        li = xbmcgui.ListItem(label=favorite["name"])
        li.setArt({"thumb": favorite.get("logo", ""), "icon": favorite.get("logo", "")})
        li.setProperty("IsPlayable", "true")

        url = (
            f"{base_url}?mode=play&stream_id={favorite['stream_id']}"
            f"&name={quote_plus(favorite['name'])}&server={server}"
        )
        if server == "server2" and favorite.get("url_template"):
            url += f"&url_template={quote_plus(favorite['url_template'])}"

        li.addContextMenuItems(
            [
                (
                    "Elimină din favorite",
                    f"RunPlugin({base_url}?mode=remove_from_favorites&stream_id={favorite['stream_id']}&server={server})",
                )
            ]
        )
        xbmcplugin.addDirectoryItem(handle=handle, url=url, listitem=li, isFolder=False)

    xbmcplugin.endOfDirectory(handle)


def add_to_favorites(stream_id, name, logo, server="server1", url_template=None):
    favorites = load_favorites(server)
    favorite_ids = {fav["stream_id"] for fav in favorites if fav.get("stream_id")}
    if stream_id not in favorite_ids:
        favorites.append(
            {
                "stream_id": stream_id,
                "name": name,
                "logo": logo,
                "url_template": url_template,
            }
        )
        with open(get_favorites_file(server), "w", encoding="utf-8") as handle:
            json_dumps(favorites, handle)
        xbmcgui.Dialog().notification(
            "Favorite",
            f"{name} a fost adăugat la favorite",
            xbmcgui.NOTIFICATION_INFO,
            2000,
        )
        return

    xbmcgui.Dialog().notification(
        "Favorite",
        f"{name} este deja în favorite",
        xbmcgui.NOTIFICATION_INFO,
        2000,
    )


def remove_from_favorites(stream_id, server="server1"):
    favorites = load_favorites(server)
    if not favorites:
        return

    favorites = [fav for fav in favorites if fav.get("stream_id") != stream_id]
    with open(get_favorites_file(server), "w", encoding="utf-8") as handle:
        json_dumps(favorites, handle)
    xbmcgui.Dialog().notification(
        "Favorite",
        "Canalul a fost eliminat din favorite",
        xbmcgui.NOTIFICATION_INFO,
        2000,
    )
    xbmc.executebuiltin("Container.Refresh")
