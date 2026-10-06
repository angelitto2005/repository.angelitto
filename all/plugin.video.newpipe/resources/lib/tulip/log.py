# -*- coding: utf-8 -*-

'''
    Tulip library
    Author Twilight0

    SPDX-License-Identifier: GPL-3.0-only
    See LICENSES/GPL-3.0-only for more information.
'''

import xbmc
from tulip import kodi


def log(msg, level=xbmc.LOGDEBUG):

    try:
        xbmc.log('{0}, {1}:: {2}'.format(kodi.addonInfo('name'), kodi.addonInfo('version'), msg), level)
    except Exception:
        try:
            xbmc.log('{0}'.format(msg), level)
        except Exception as reason:
            xbmc.log('Logging Failure: {0}' % reason, level)
