# -*- coding: utf-8 -*-

import os
import sys
import xbmcaddon

__settings__ = xbmcaddon.Addon()
__version__ = __settings__.getAddonInfo('version')
__plugin__ = __settings__.getAddonInfo('name') + " v." + __version__
__root__ = __settings__.getAddonInfo('path')
__media__ = os.path.join(__root__, 'resources', 'media')

if __name__ == "__main__":
    from resources import Core

    core = Core.Core()
    if not sys.argv[2]:
        # MODIFICARE: Intrare directă în meniul de Torrente
        # Ignorăm setările vechi și intrăm direct în modul torenți
        core.TorrentsMenu()
    else:
        params = core.getParameters(sys.argv[2])
        
        # --- INTERCEPȚIE PENTRU LOG ȘI DONAȚII ---
        action = params.get('action')
        if action == 'upload_log':
            from resources.lib import utils
            utils.upload_logfile()
        elif action == 'show_donate':
            from resources.lib import utils
            utils.show_donate_link()
        else:
            core.executeAction(params)
    # del core