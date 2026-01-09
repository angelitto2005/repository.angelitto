# -*- coding: utf-8 -*-
import os
import sys
import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs
import requests
from urllib.parse import unquote, urlencode, parse_qsl

__addon__ = xbmcaddon.Addon()
__id__ = __addon__.getAddonInfo('id')
# HANDLE-ul trebuie să fie argv[1] în format integer
HANDLE = int(sys.argv[1]) if len(sys.argv) > 1 else 0

def search():
    base_url = 'https://sub.wyzie.ru/search'
    v_id = xbmc.getInfoLabel("VideoPlayer.IMDBNumber") or xbmc.getInfoLabel("ListItem.Property(tmdb_id)")
    if not v_id: return

    # --- SCHIMBARE LIMBĂ DIN SETĂRI ---
    langs = ["ro", "en", "es", "fr", "de", "it", "hu", "pt", "ru", "tr", "bg", "el", "pl", "cs", "nl"]
    lang_names = ["Romanian", "English", "Spanish", "French", "German", "Italian", "Hungarian", "Portuguese", "Russian", "Turkish", "Bulgarian", "Greek", "Polish", "Czech", "Dutch"]
    
    try:
        idx = __addon__.getSettingInt('subs_languages')
        l_code = langs[idx]
        l_display = lang_names[idx]
    except:
        l_code = "ro"
        l_display = "Romanian"

    params = {'id': v_id, 'language': l_code}
    s, e = xbmc.getInfoLabel("VideoPlayer.Season"), xbmc.getInfoLabel("VideoPlayer.Episode")
    if s and s != "0": params.update({'season': s, 'episode': e})

    try:
        r = requests.get(base_url, params=params, timeout=10)
        if r.ok:
            results = r.json()
            if not isinstance(results, list): results = [results]
            for sub in results:
                api_filename = sub.get('fileName', 'subtitle.srt')
                # Folosim label-ul limbii selectate
                listitem = xbmcgui.ListItem(label=l_display, label2=api_filename)
                listitem.setArt({'icon': f'resource://resource.images.languageflags.colour/{l_display}.png'})
                
                # Pasăm l_code și l_display către download pentru a păstra consistența
                d_params = {'action': 'download', 'url': sub['url'], 'filename': api_filename, 'l_code': l_code, 'l_display': l_display}
                url = f"{sys.argv[0]}?{urlencode(d_params)}"
                xbmcplugin.addDirectoryItem(handle=HANDLE, url=url, listitem=listitem, isFolder=False)
    except: pass
    xbmcplugin.endOfDirectory(HANDLE)

def download(params):
    try:
        url = unquote(params.get('url', ''))
        raw_filename = unquote(params.get('filename', 'subtitle.srt'))
        l_code = params.get('l_code', 'ro')
        l_display = params.get('l_display', 'Romanian')
        
        # 1. Folder profil
        dest_dir = xbmcvfs.translatePath(__addon__.getAddonInfo('profile'))
        if not xbmcvfs.exists(dest_dir): xbmcvfs.mkdirs(dest_dir)
        
        # 2. Curățare fișiere vechi
        _, files = xbmcvfs.listdir(dest_dir)
        for f in files:
            if f.endswith(".srt"): xbmcvfs.delete(os.path.join(dest_dir, f))

        # 3. Nume fișier cu codul limbii alese din setări
        clean_name = raw_filename.replace(" ", "-")
        name, _ = os.path.splitext(clean_name)
        final_filename = f"{name}.{l_code}.srt"
        dest_path = os.path.join(dest_dir, final_filename)

        # 4. Descărcare
        r = requests.get(url, timeout=20)
        if r.ok:
            with open(dest_path, 'wb') as f:
                f.write(r.content)
            
            # Folosim numele limbii selectate pentru a evita "Unknown"
            listitem = xbmcgui.ListItem(label=l_display)
            xbmcplugin.addDirectoryItem(handle=HANDLE, url=dest_path, listitem=listitem, isFolder=False)
            
            xbmc.Player().setSubtitles(dest_path)
            
    except Exception as e:
        xbmc.log(f"DOWNLOAD ERROR: {str(e)}", xbmc.LOGERROR)
    
    xbmcplugin.endOfDirectory(HANDLE)

if __name__ == '__main__':
    p = dict(parse_qsl(sys.argv[2].lstrip('?'))) if len(sys.argv) > 2 else {}
    if p.get('action') == 'download':
        download(p)
    else:
        search()
