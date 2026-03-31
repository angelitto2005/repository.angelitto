# -*- coding: utf-8 -*-
import xbmc, sys

def open_url():
    # 1. Identificăm URL-ul
    args_str = " ".join(sys.argv).lower()
    url = "https://aistudio.google.com/app/api-keys" if "gemini" in args_str else "https://sub.wyzie.io/redeem"

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
    # Așteptăm 2 secunde să se încarce browserul în fundal
    xbmc.sleep(2000)
    
    # Redeschidem setările (asta va aduce Kodi în față pentru o secundă)
    xbmc.executebuiltin('Addon.OpenSettings(service.subtitles.wyzie)')
    
    # 5. ÎL FACEM MIC DIN NOU IMEDIAT
    # După ce setările s-au deschis, forțăm minimizarea ca browserul să rămână vizibil
    xbmc.sleep(800) 
    if xbmc.getCondVisibility('System.Platform.Windows'):
        xbmc.executebuiltin('Minimize')
    
    xbmc.executebuiltin('Notification(Browser, Copiază cheia și dă click pe Kodi în bară, 5000)')

if __name__ == '__main__':
    open_url()
