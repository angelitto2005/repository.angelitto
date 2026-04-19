# -*- coding: utf-8 -*-
import xbmc, xbmcgui, xbmcvfs, xbmcaddon
import os

ADDON_NAME = '[B][COLOR FFB048B5]Sub[/COLOR][COLOR FF00BFFF]Studio[/COLOR][/B]'

def _get_addon_icon():
    try:
        return os.path.join(xbmcaddon.Addon().getAddonInfo('path'), 'icon.png')
    except Exception:
        return ''

def run_false(sub_addon_id):
    try:
        _addon = xbmcaddon.Addon(sub_addon_id)
    except Exception:
        return

    langs = ["ro","en","es","fr","de","it","hu","pt","ru","tr","bg","el","pl","cs","nl"]
    try:
        target_lang = langs[_addon.getSettingInt('subs_languages')]
    except Exception:
        target_lang = "ro"

    profile_path = xbmcvfs.translatePath(
        'special://profile/addon_data/%s/Subtitrari traduse/' % sub_addon_id)

    try:
        res = xbmcvfs.listdir(profile_path)
        files = res[1] if isinstance(res, tuple) else res
    except Exception:
        return

    srt_files = [f for f in files if f.lower().endswith('.srt')]

    if not srt_files:
        return

    sub_path = os.path.join(profile_path, srt_files[0])
    
    # FIX PERMISIUNI KODI C++: Clona in TEMP pentru loader
    temp_dir = xbmcvfs.translatePath('special://temp/')
    temp_sub = os.path.join(temp_dir, 'Loader_Active_Sub.srt')

    try:
        xbmcvfs.copy(sub_path, temp_sub)
    except Exception:
        pass

    try:
        xbmc.sleep(500)
        xbmc.Player().setSubtitles(temp_sub)
        xbmcgui.Dialog().notification(
            ADDON_NAME,
            'Subtitrare salvată %s activată!' % target_lang.upper(),
            _get_addon_icon(), 3000)
    except Exception as e:
        xbmc.log("SUBSTUDIO LOADER ERROR: " + str(e), xbmc.LOGERROR)