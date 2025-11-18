import logging

import xbmc
import xbmcaddon
import xbmcgui

from lib.utils import PY3, str_to_unicode

ADDON = xbmcaddon.Addon()

if PY3:
    from xbmcvfs import translatePath

    translate = ADDON.getLocalizedString
else:
    from xbmc import translatePath

    def translate(*args, **kwargs):
        return ADDON.getLocalizedString(*args, **kwargs).encode("utf-8")

ADDON_ID = ADDON.getAddonInfo("id")
ADDON_NAME = ADDON.getAddonInfo("name")
ADDON_PATH = str_to_unicode(ADDON.getAddonInfo("path"))
ADDON_ICON = str_to_unicode(ADDON.getAddonInfo("icon"))
ADDON_DATA = str_to_unicode(translatePath(ADDON.getAddonInfo("profile")))


def notification(message, heading=ADDON_NAME, icon=ADDON_ICON, time=5000, sound=True):
    xbmcgui.Dialog().notification(heading, message, icon, time, sound)


def get_repository_port():
    return int(ADDON.getSetting("repository_port"))


class KodiLogHandler(logging.Handler):
    levels = {
        logging.CRITICAL: xbmc.LOGFATAL,
        logging.ERROR: xbmc.LOGERROR,
        logging.WARNING: xbmc.LOGWARNING,
        logging.INFO: xbmc.LOGINFO,
        logging.DEBUG: xbmc.LOGDEBUG,
        logging.NOTSET: xbmc.LOGNONE,
    }

    def __init__(self):
        super(KodiLogHandler, self).__init__()
        self.setFormatter(logging.Formatter("[{}] %(message)s".format(ADDON_ID)))

    def emit(self, record):
        xbmc.log(self.format(record), self.levels[record.levelno])


def set_logger(name=None, level=logging.NOTSET):
    logger = logging.getLogger(name)
    logger.handlers = [KodiLogHandler()]
    logger.setLevel(level)
