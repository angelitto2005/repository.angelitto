import sys
import requests
import xbmcgui
import xbmcplugin
import xbmc
import urllib.parse
import os
import xbmcvfs
import xbmcaddon

def log(msg):
    xbmc.log(f"### [WyzieSub] {msg}", xbmc.LOGINFO)

def search():
    addon = xbmcaddon.Addon()
    handle = int(sys.argv[1])
    
    try:
        lang_setting = addon.getSetting('subs_languages')
        lang_index = int(lang_setting) if lang_setting else 0
    except:
        lang_index = 0
    
    languages = ["ro", "en", "es", "fr", "de", "it", "hu", "pt", "ru", "tr", "bg", "el", "pl", "cs", "nl"]
    selected_lang = languages[lang_index] if lang_index < len(languages) else "ro"
    
    imdb_id = xbmc.getInfoLabel('VideoPlayer.IMDBNumber')
    season = xbmc.getInfoLabel('VideoPlayer.Season')
    episode = xbmc.getInfoLabel('VideoPlayer.Episode')
    
    if not imdb_id:
        log("Nu s-a găsit IMDB ID.")
        xbmcplugin.endOfDirectory(handle)
        return

    if season and episode:
        api_url = f'https://sub.wyzie.ru/search?id={imdb_id}&season={season}&episode={episode}&language={selected_lang}'
        log(f"Căutare Episod: {imdb_id} S{season}E{episode} | Limbă: {selected_lang}")
    else:
        api_url = f'https://sub.wyzie.ru/search?id={imdb_id}&language={selected_lang}'
        log(f"Căutare Film: {imdb_id} | Limbă: {selected_lang}")
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(api_url, headers=headers, timeout=10)
        response.raise_for_status()
        subtitles = response.json()
        
        if subtitles:
            for sub in subtitles:
                filename = sub.get('fileName', 'Subtitrare')
                download_url = sub.get('url')

                list_item = xbmcgui.ListItem(label=filename)
                list_item.setArt({'icon': 'DefaultSubtitle.png'})
                list_item.setProperty('language', selected_lang)
                
                cmd = {
                    'action': 'download',
                    'url': download_url,
                    'filename': filename
                }
                
                url = f"{sys.argv[0]}?{urllib.parse.urlencode(cmd)}"
                xbmcplugin.addDirectoryItem(handle=handle, url=url, listitem=list_item, isFolder=False)
        
    except Exception as e:
        log(f"Eroare search: {str(e)}")
    
    xbmcplugin.endOfDirectory(handle)

def download(params):
    download_url = params.get('url')
    filename = params.get('filename', 'subtitle.srt')
    handle = int(sys.argv[1])
    
    if not download_url:
        return

    try:
        storage_path = xbmcvfs.translatePath('special://temp/')
        if not xbmcvfs.exists(storage_path):
            xbmcvfs.mkdir(storage_path)

        local_filename = "".join([c for c in filename if c.isalnum() or c in (' ', '.', '_')]).strip()
        if not local_filename.lower().endswith('.srt'):
            local_filename += '.srt'
            
        temp_path = os.path.join(storage_path, local_filename)
        
        log(f"Descarcare catre: {temp_path}")
        
        headers = {'User-Agent': 'Mozilla/5.0'}
        sub_response = requests.get(download_url, headers=headers, timeout=15)
        sub_response.raise_for_status()
        
        f = xbmcvfs.File(temp_path, 'wb')
        result = f.write(sub_response.content)
        f.close()

        if result:
            list_item = xbmcgui.ListItem(label=local_filename)
            xbmcplugin.addDirectoryItem(handle=handle, url=temp_path, listitem=list_item, isFolder=False)
        
    except Exception as e:
        log(f"Eroare download: {str(e)}")
    
    xbmcplugin.endOfDirectory(handle)


if __name__ == '__main__':
    params = dict(urllib.parse.parse_qsl(sys.argv[2][1:])) if len(sys.argv) > 2 else {}
    action = params.get('action')

    if action == 'download':
        download(params)
    else:
        search()
