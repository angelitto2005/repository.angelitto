# -*- coding: utf-8 -*-
import xbmc, xbmcgui, xbmcvfs, xbmcaddon
import os

def upload_logfile():
    """Reads the kodi.log file and uploads it to paste.kodi.tv"""
    import requests
    dialog = xbmcgui.Dialog()
    
    log_file = xbmcvfs.translatePath('special://logpath/kodi.log')
    url = 'https://paste.kodi.tv/'
    
    if not xbmcvfs.exists(log_file):
        dialog.ok("Error", "Log file not found.")
        return

    if not dialog.yesno("Upload Log", "Do you want to upload the Kodi log to paste.kodi.tv?\nThis is useful for bug reporting."):
        return

    xbmc.executebuiltin('ActivateWindow(busydialognocancel)')
    try:
        f = xbmcvfs.File(log_file, 'r')
        text = f.read()
        f.close()
        
        if isinstance(text, str):
            text = text.encode('utf-8', errors='ignore')
            
        response = requests.post(f"{url}documents", data=text, timeout=10.0).json()
        xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
        
        if 'key' in response:
            link = f"{url}{response['key']}"
            colored_link = f"[B][COLOR FF6AFB92]{link}[/COLOR][/B]"
            dialog.ok("Upload Successful", f"The log was successfully uploaded!\nLink: {colored_link}")
        else:
            dialog.ok("Error", "Upload failed. Check the Kodi log.")
            
    except Exception as e:
        xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
        xbmc.log(f"SUBSTUDIO: Upload Log Error: {e}", xbmc.LOGERROR)
        dialog.ok("Error", f"Upload error: {str(e)}")


def show_donate_link():
    """Displays a dialog with the donation link to Ko-fi"""
    dialog = xbmcgui.Dialog()
    
    text = (
        "Support the development of the addon by buying me a coffee!\n"
        "Link: [B][COLOR FF6AFB92]https://ko-fi.com/angelitto[/COLOR][/B]\n"
        "Thank you for your support!"
    )
    
    dialog.ok("Support the Project", text)


def migrate_saved_folder():
    """Automatically migrates the old Romanian folder to the new English one."""
    try:
        addon = xbmcaddon.Addon()
        profile_path = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
        
        old_folder = os.path.join(profile_path, 'Subtitrari traduse')
        new_folder = os.path.join(profile_path, 'Translated Subtitles')
        
        # Check if the old folder exists
        if xbmcvfs.exists(old_folder + os.sep):
            # Ensure the new folder exists
            if not xbmcvfs.exists(new_folder + os.sep):
                xbmcvfs.mkdirs(new_folder + os.sep)
            
            # Read files from the old folder
            dirs, files = xbmcvfs.listdir(old_folder)
            
            moved_count = 0
            for f in files:
                old_file = os.path.join(old_folder, f)
                new_file = os.path.join(new_folder, f)
                
                # Copy file to new destination
                xbmcvfs.copy(old_file, new_file)
                # Delete the old file
                xbmcvfs.delete(old_file)
                moved_count += 1
                
            # Remove the now empty old folder
            xbmcvfs.rmdir(old_folder)
            xbmc.log(f"SUBSTUDIO: Migration complete. Moved {moved_count} files to 'Translated Subtitles'.", xbmc.LOGINFO)
            
    except Exception as e:
        xbmc.log(f"SUBSTUDIO: Migration error: {str(e)}", xbmc.LOGERROR)