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

    langs = ["ro","en","es","fr","de","it","hu","pt","ru","tr",
             "bg","el","pl","cs","nl"]
    try:
        target_lang = langs[_addon.getSettingInt('subs_languages')]
    except Exception:
        target_lang = "ro"

    profile_path = xbmcvfs.translatePath(
        'special://profile/addon_data/%s/' % sub_addon_id)

    try:
        res = xbmcvfs.listdir(profile_path)
        files = res[1] if isinstance(res, tuple) else res
    except Exception:
        return

    srt_files = [
        f for f in files
        if f.lower().endswith('.srt')
        and not f.lower().startswith('robot_tradus')
    ]

    if not srt_files:
        return

    sub_path = os.path.join(profile_path, srt_files[0])

    try:
        xbmc.sleep(500)
        xbmc.Player().setSubtitles(sub_path)
        xbmcgui.Dialog().notification(
            ADDON_NAME,
            'Subtitrare %s activată!' % target_lang.upper(),
            _get_addon_icon(), 3000)
    except Exception as e:
        xbmc.log("SUBSTUDIO LOADER ERROR: " + str(e), xbmc.LOGERROR)