import xbmc, xbmcgui, xbmcvfs
import os, sys
def run_false(sub_addon_id):
    import xbmcaddon
    _addon = xbmcaddon.Addon(sub_addon_id)
    langs = ["ro", "en", "es", "fr", "de", "it", "hu", "pt", "ru", "tr", "bg", "el", "pl", "cs", "nl"]
    try:
        idx = _addon.getSettingInt('subs_languages')
        target_lang = langs[idx]
    except:
        target_lang = "ro"
    profile_path = xbmcvfs.translatePath('special://profile/addon_data/%s/' % sub_addon_id)
    res = xbmcvfs.listdir(profile_path)
    files = res[1] if isinstance(res, tuple) else res
    srt_files = [f for f in files if f.lower().endswith('.srt') and ".tradus." not in f.lower()]
    if not srt_files:
        return
    original_file_name = srt_files[0]
    sub_path = os.path.join(profile_path, original_file_name)
    base_name = os.path.splitext(original_file_name)[0]
    new_file_name = "%s.%s.srt" % (base_name, target_lang)
    output_path = os.path.join(profile_path, new_file_name)
    try:
        f = xbmcvfs.File(sub_path)
        content = f.read()
        f.close()
        f = xbmcvfs.File(output_path, 'w')
        f.write(content)
        f.close()
        xbmc.Player().setSubtitles(output_path)
        xbmcgui.Dialog().notification('Robot', 'Subtitrare %s activată!' % target_lang.upper(), 3000)
    except Exception as e:
        xbmc.log("ROBOT FATAL ERROR: " + str(e), xbmc.LOGERROR)