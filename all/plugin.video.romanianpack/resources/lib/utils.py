# Dummy file to make this directory a package.
# -*- coding: utf-8 -*-
import xbmc
import xbmcgui
import xbmcvfs

def upload_logfile():
    """Citește fișierul kodi.log și îl încarcă pe paste.kodi.tv"""
    import requests
    dialog = xbmcgui.Dialog()
    
    log_file = xbmcvfs.translatePath('special://logpath/kodi.log')
    url = 'https://paste.kodi.tv/'
    
    if not xbmcvfs.exists(log_file):
        dialog.ok("Eroare", "Fișierul Log nu a fost găsit.")
        return

    if not dialog.yesno("Încărcare Log", "Vrei să încarci jurnalul (log-ul) Kodi pe paste.kodi.tv?\nEste util pentru raportarea erorilor."):
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
            dialog.ok("Încărcare Reușită", f"Log-ul a fost încărcat cu succes!\nLink: {colored_link}")
        else:
            dialog.ok("Eroare", "Încărcarea a eșuat. Verifică log-ul Kodi.")
            
    except Exception as e:
        xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
        xbmc.log(f"MRSP LITE: Upload Log Error: {e}", xbmc.LOGERROR)
        dialog.ok("Eroare", f"Eroare la încărcare: {str(e)}")


def show_donate_link():
    """Afișează un dialog cu link-ul de donație către Ko-fi"""
    dialog = xbmcgui.Dialog()
    
    text = (
        "Susține dezvoltarea addonului cumpărându-mi o cafea!\n"
        "Link: [B][COLOR FF6AFB92]https://ko-fi.com/angelitto[/COLOR][/B]\n"
        "Îți mulțumesc pentru sprijin!"
    )
    
    dialog.ok("Susține Proiectul", text)