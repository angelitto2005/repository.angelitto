# -*- coding: utf-8 -*-
import xbmc, xbmcgui, xbmcvfs
import os, sys

def run_false(sub_addon_id):
    import xbmcaddon
    _addon = xbmcaddon.Addon(sub_addon_id)

    # --- PRELUARE COD LIMBĂ DIN SETĂRI ---
    langs = ["ro", "en", "es", "fr", "de", "it", "hu", "pt", "ru", "tr", "bg", "el", "pl", "cs", "nl"]
    try:
        idx = _addon.getSettingInt('subs_languages')
        target_lang = langs[idx]
    except:
        target_lang = "ro"

    profile_path = xbmcvfs.translatePath('special://profile/addon_data/%s/' % sub_addon_id)
    res = xbmcvfs.listdir(profile_path)
    # Gestionare listdir pentru Kodi 2026 (v21+)
    files = res[1] if isinstance(res, tuple) else res
    
    # Căutăm fișierul original
    srt_files = [f for f in files if f.lower().endswith('.srt') and ".tradus." not in f.lower()]

    if not srt_files:
        return

    original_file_name = srt_files[0]
    sub_path = os.path.join(profile_path, original_file_name)
    
    # Generăm numele nou: Film.srt -> Film.ro.srt
    base_name = os.path.splitext(original_file_name)[0]
    new_file_name = "%s.%s.srt" % (base_name, target_lang)
    output_path = os.path.join(profile_path, new_file_name)

    try:
        # Citim conținutul BRUT al fișierului original
        f = xbmcvfs.File(sub_path)
        content = f.read()
        f.close()
        
        # Scrim conținutul IDENTIC în noul fișier (fără nicio modificare de text)
        f = xbmcvfs.File(output_path, 'w')
        f.write(content)
        f.close()
        
        # Încărcăm noul fișier în Player-ul Kodi
        xbmc.Player().setSubtitles(output_path)
        
        # Notificare finală
        xbmcgui.Dialog().notification('Robot', 'Subtitrare %s activată!' % target_lang.upper(), 3000)
        
    except Exception as e:
        xbmc.log("ROBOT FATAL ERROR: " + str(e), xbmc.LOGERROR)
