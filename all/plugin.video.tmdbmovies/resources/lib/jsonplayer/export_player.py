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
        # Get path to source file (tmdbmovies.json)
        source_path = xbmcvfs.translatePath('special://home/addons/plugin.video.tmdbmovies/resources/lib/jsonplayer/tmdbmovies.json')
        
        # Get path to destination folder (TMDb Helper players)
        dest_dir = xbmcvfs.translatePath('special://profile/addon_data/plugin.video.themoviedb.helper/players/')
        dest_path = os.path.join(dest_dir, 'tmdbmovies.json')

        # Check if destination folder exists, if not create it
        if not os.path.exists(dest_dir):
            os.makedirs(dest_dir)

        # Copy / overwrite JSON file
        shutil.copyfile(source_path, dest_path)

        # Show success notification
        dialog.notification("[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]", "[B][COLOR yellow]Player JSON[/COLOR][/B] exported successfully to [B][COLOR lightskyblue]TMDb Helper[/COLOR][/B]!", addon_icon, 4000)
        
    except Exception as e:
        # In case of error, show the reason
        dialog.notification("[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B] - [B][COLOR red]Error[/COLOR][/B]", f"Export failed: {str(e)}", xbmcgui.NOTIFICATION_ERROR, 5000)

if __name__ == '__main__':
    export_player()