import xbmc, sys
def open_url():
    args_str = " ".join(sys.argv).lower()
    if "gemini" in args_str:
        url = "https://aistudio.google.com/app/api-keys"
        notify_msg = "Copy the Gemini key and return to Kodi at R3"
    else:
        url = "https://www.deepl.com/en/your-account/keys"
        notify_msg = "Copy the DeepL key and return to Kodi at R4"
    xbmc.executebuiltin('SendClick(28)')
    xbmc.sleep(500)
    if xbmc.getCondVisibility('System.Platform.Android'):
        xbmc.executebuiltin('StartAndroidActivity(,"android.intent.action.VIEW","","{}")'.format(url))
    elif xbmc.getCondVisibility('System.Platform.Windows'):
        xbmc.executebuiltin('System.Exec("cmd.exe /c start {}")'.format(url))
        xbmc.executebuiltin('Minimize')
    else:
        xbmc.executebuiltin('System.Exec("open {}")'.format(url))
    xbmc.sleep(2000)
    xbmc.executebuiltin('Addon.OpenSettings(service.subtitles.opensub)')
    xbmc.sleep(800)
    if xbmc.getCondVisibility('System.Platform.Windows'):
        xbmc.executebuiltin('Minimize')
    xbmc.executebuiltin('Notification("Browser API", "{}", 5000)'.format(notify_msg))
if __name__ == '__main__':
    open_url()