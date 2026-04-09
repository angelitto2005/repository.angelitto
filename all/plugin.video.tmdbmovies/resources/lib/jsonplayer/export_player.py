# -*- coding: utf-8 -*-
import os
import shutil
import xbmcvfs
import xbmcgui
import xbmcaddon

def export_player():
    addon = xbmcaddon.Addon('plugin.video.tmdbmovies')
    addon_icon = addon.getAddonInfo('icon')
    dialog = xbmcgui.Dialog()

    try:
        # Preluăm calea către fișierul sursă (tmdbmovies.json)
        source_path = xbmcvfs.translatePath('special://home/addons/plugin.video.tmdbmovies/resources/lib/jsonplayer/tmdbmovies.json')
        
        # Preluăm calea către folderul destinație (TMDb Helper players)
        dest_dir = xbmcvfs.translatePath('special://profile/addon_data/plugin.video.themoviedb.helper/players/')
        dest_path = os.path.join(dest_dir, 'tmdbmovies.json')

        # Verificăm dacă folderul destinație există, dacă nu, îl creăm
        if not os.path.exists(dest_dir):
            os.makedirs(dest_dir)

        # Copiem/suprascriem fișierul JSON
        shutil.copyfile(source_path, dest_path)

        # Afișăm o notificare de succes
        dialog.notification("[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]", "[B][COLOR yellow]Player JSON[/COLOR][/B] exportat cu succes în [B][COLOR blue]TMDb Helper[/COLOR][/B]!", addon_icon, 4000)
        
    except Exception as e:
        # În caz de eroare, afișăm motivul
        dialog.notification("[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B] - [B][COLOR red]Eroare[/COLOR][/B]", f"Export eșuat: {str(e)}", xbmcgui.NOTIFICATION_ERROR, 5000)

if __name__ == '__main__':
    export_player()