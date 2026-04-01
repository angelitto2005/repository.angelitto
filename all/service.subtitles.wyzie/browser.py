# -*- coding: utf-8 -*-
import xbmc, sys

def open_url():
    # 1. Identificăm URL-ul pe baza argumentului primit
    args_str = " ".join(sys.argv).lower()
    
    if "gemini" in args_str:
        url = "https://aistudio.google.com/app/api-keys"
    elif "deepl" in args_str:
        # Trimitem utilizatorul direct la pagina de chei DeepL
        url = "https://www.deepl.com/en/your-account/keys"
    else:
        url = "https://sub.wyzie.io/redeem"

    # 2. SALVĂM SETĂRILE ACTUALE (Apasă OK automat)
    xbmc.executebuiltin('SendClick(28)')
    xbmc.sleep(500)

    # 3. DESCHIDEM BROWSERUL
    if xbmc.getCondVisibility('System.Platform.Android'):
        xbmc.executebuiltin('StartAndroidActivity(,"android.intent.action.VIEW","","{}")'.format(url))
    elif xbmc.getCondVisibility('System.Platform.Windows'):
        xbmc.executebuiltin('System.Exec("cmd.exe /c start {}")'.format(url))
        xbmc.executebuiltin('Minimize')
    else:
        xbmc.executebuiltin('System.Exec("open {}")'.format(url))

    # 4. PAUZĂ LUNGĂ ȘI REDESCHIDERE SETĂRI
    xbmc.sleep(2000)
    
    # Redeschidem setările pentru ca utilizatorul să aibă unde să dea "Paste"
    xbmc.executebuiltin('Addon.OpenSettings(service.subtitles.wyzie)')
    
    # 5. ÎL FACEM MIC DIN NOU IMEDIAT (pentru Windows)
    xbmc.sleep(800) 
    if xbmc.getCondVisibility('System.Platform.Windows'):
        xbmc.executebuiltin('Minimize')
    
    notify_msg = "Copiază cheia și revino în Kodi la rubrica DeepL"
    xbmc.executebuiltin('Notification("Browser API", "{}", 5000)'.format(notify_msg))

if __name__ == '__main__':
    open_url()
