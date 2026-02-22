# -*- coding: utf-8 -*-
#default.py

import re
import sys
import urllib.parse

import xbmc
import xbmcgui
import xbmcplugin

from common import (
    log,
    http_get,
    BASE_URL,
    USER_AGENT,
    SITE_HEADERS,
    get_settings,
    get_categories,
    get_channels_by_category,
    get_epg_id,
    load_epg,
    build_epg_plot,
)

PLUGIN_URL = sys.argv[0]
HANDLE     = int(sys.argv[1])

CATEGORY_ICONS = {
    'Generale':    'cat_Generale.png',
    'Știri':       'cat_Stiri.png',
    'Sport':       'cat_Sport.png',
    'Filme':       'cat_Filme.png',
    'Documentare': 'cat_Documentare.png',
    'Muzică':      'cat_Muzica.png',
    'Copii':       'cat_Copii.png',
    'Religioase':  'cat_Religioase.png',
}


def build_url(params):
    return PLUGIN_URL + '?' + urllib.parse.urlencode(params)


def router(param_string):
    params = dict(urllib.parse.parse_qsl(param_string))
    mode   = params.get('mode')
    if mode == 'category':
        list_category(params.get('category', ''))
    elif mode == 'play':
        play_video(
            web_url=params.get('web_url', ''),
            name=params.get('name', ''),
            logo=params.get('logo', ''),
        )
    else:
        main_menu()


def main_menu():
    xbmcplugin.setContent(HANDLE, 'genres')
    categories = get_categories()
    if not categories:
        xbmcgui.Dialog().notification(
            'Rotv123', 'Catalog indisponibil. Verificați conexiunea.',
            xbmcgui.NOTIFICATION_ERROR, 4000
        )
        xbmcplugin.endOfDirectory(HANDLE, False)
        return
    for cat in categories:
        url  = build_url({'mode': 'category', 'category': cat})
        li   = xbmcgui.ListItem(label=cat)
        icon_file = CATEGORY_ICONS.get(cat)
        if icon_file:
            import xbmcaddon as _xa
            addon_path = _xa.Addon().getAddonInfo('path')
            import xbmcvfs as _xv
            icon = _xv.translatePath(f'{addon_path}/resources/icons/{icon_file}')
        else:
            icon = 'DefaultTVShows.png'
        li.setArt({'icon': icon, 'thumb': icon})
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=url, listitem=li, isFolder=True)
    xbmcplugin.endOfDirectory(HANDLE)


def list_category(category):
    xbmcplugin.setContent(HANDLE, 'videos')
    channels = get_channels_by_category(category)
    if not channels:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    settings = get_settings()
    source   = settings['epg_source']

    for ch in channels:
        name    = ch.get('title', '')
        web_url = ch.get('web_url', '')
        logo    = ch.get('logo', '')

        epg_id        = get_epg_id(ch, source)
        info          = load_epg(epg_id) if epg_id else None
        plot, tagline = build_epg_plot(info)

        if logo:
            clean  = logo.replace('https://', '').replace('http://', '')
            poster = f'https://images.weserv.nl/?url={clean}&w=320&h=450&fit=contain&bg=transparent'
        else:
            poster = ''

        url = build_url({'mode': 'play', 'web_url': web_url, 'name': name, 'logo': poster})
        li  = xbmcgui.ListItem(label=name)
        li.setArt({'thumb': poster, 'icon': poster, 'poster': poster})
        li.setInfo('video', {'title': name, 'plot': plot, 'tagline': tagline})
        li.setProperty('IsPlayable', 'true')
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=url, listitem=li, isFolder=False)

    xbmcplugin.endOfDirectory(HANDLE)


def _extract_stream_urls(html):
    m = re.search(r'const\s+streams\s*=\s*\{([^}]+)\}', html, re.DOTALL)
    if not m:
        return []
    pairs = re.findall(r'(\w+)\s*:\s*[\'\"]\s*([^\'\"\s,]+)', m.group(1))
    return [(key.replace('_', ' ').capitalize(), url.strip()) for key, url in pairs]


def _pick_stream(streams, preferred_idx, auto_mode):
    if not streams:
        return None, None
    if auto_mode:
        idx = preferred_idx if preferred_idx < len(streams) else 0
        return streams[idx]
    labels = [s[0] for s in streams]
    idx    = xbmcgui.Dialog().select('Alege sursa', labels)
    if idx == -1:
        return None, None
    return streams[idx]


def play_video(web_url, name, logo):
    if not web_url:
        xbmcgui.Dialog().notification('Rotv123', 'URL invalid', xbmcgui.NOTIFICATION_ERROR)
        return

    raw = http_get(web_url, extra_headers=SITE_HEADERS)
    if not raw:
        xbmcgui.Dialog().notification(
            'Rotv123', f'Nu s-a putut accesa pagina pentru {name}',
            xbmcgui.NOTIFICATION_ERROR, 4000
        )
        return

    html    = raw.decode('utf-8', errors='ignore')
    streams = _extract_stream_urls(html)

    if not streams:
        xbmcgui.Dialog().notification(
            'Rotv123', f'Niciun stream găsit pentru {name}',
            xbmcgui.NOTIFICATION_ERROR, 4000
        )
        log(f'play_video: niciun stream în pagina {web_url}', xbmc.LOGWARNING)
        return

    log(f'play_video: {len(streams)} surse pentru {name}: {[s[0] for s in streams]}')

    settings          = get_settings()
    label, stream_url = _pick_stream(
        streams,
        preferred_idx=settings['stream_priority'],
        auto_mode=settings['stream_mode_auto'],
    )
    if not stream_url:
        return

    log(f'play_video: [{label}] {stream_url}')

    inline_headers = (
        f'User-Agent={USER_AGENT}'
        f'&Referer={BASE_URL}/'
        f'&Origin={BASE_URL}'
    )

    play_item = xbmcgui.ListItem(label=name)
    if logo:
        play_item.setArt({'thumb': logo, 'icon': logo})
    play_item.setMimeType('application/x-mpegURL')
    play_item.setContentLookup(False)
    play_item.setPath(f'{stream_url}|{inline_headers}')
    xbmcplugin.setResolvedUrl(HANDLE, True, listitem=play_item)


if __name__ == '__main__':
    router(sys.argv[2][1:] if len(sys.argv) > 2 else '')
