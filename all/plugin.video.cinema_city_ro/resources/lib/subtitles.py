import os
import requests
import xbmcaddon
import xbmcvfs
import xbmc
import shutil
import time

addon = xbmcaddon.Addon()
profile_path = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
subs_path = os.path.join(profile_path, 'subs')

if os.path.exists(subs_path):
    try:
        shutil.rmtree(subs_path)
        xbmc.log(f"[WyzieSub] Folderul {subs_path} a fost șters.", xbmc.LOGINFO)
    except Exception as e:
        xbmc.log(f"[WyzieSub] Eroare la ștergerea folderului: {e}", xbmc.LOGERROR)

time.sleep(1)

SUB_LANGUAGES = addon.getSetting('subs_languages') or 'ro'
SUB_FORMAT = addon.getSetting('subs_format') or 'srt'

BASE_URL = 'https://sub.wyzie.ru/search'

def search_subtitles(imdb_id, season=None, episode=None):
    subtitles = []
    languages = [lang.strip() for lang in SUB_LANGUAGES.split(',') if lang.strip()]

    for lang in languages:
        params = {
            'id': imdb_id,
            'language': lang,
            'format': SUB_FORMAT
        }

        if season and episode:
            params['season'] = season
            params['episode'] = episode

        try:
            response = requests.get(BASE_URL, params=params, timeout=30)
            if response.ok:
                data = response.json()
                if isinstance(data, dict):
                    subtitles.append(data)
                elif isinstance(data, list):
                    subtitles.extend(data)
            else:
                xbmc.log(f"[WyzieSub] Eroare HTTP: {response.status_code}", xbmc.LOGERROR)
        except Exception as e:
            xbmc.log(f"[WyzieSub] Excepție: {e}", xbmc.LOGERROR)

    return subtitles

def download_subtitle(sub, folder_path):
    try:
        if not os.path.exists(folder_path):
            os.makedirs(folder_path)
    except Exception as e:
        xbmc.log(f"[Subtitles] Eroare creare folder subtitrări: {e}", xbmc.LOGERROR)
        return ''

    url = sub['url']
    filename = f"{sub['media']}.{sub['language']}.{sub['format']}"
    safe_filename = "".join(c for c in filename if c not in r'\/:*?"<>|')
    path = os.path.join(folder_path, safe_filename)

    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        with open(path, 'wb') as f:
            f.write(r.content)
        return path
    except Exception as e:
        xbmc.log(f"[Subtitles] Eroare descărcare: {e}", xbmc.LOGERROR)
        return ''
