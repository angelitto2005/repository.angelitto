import sys
import xbmcaddon


def _open():
    aid = ''
    if len(sys.argv) > 1:
        aid = str(sys.argv[1]).strip()
    if not aid:
        return
    try:
        xbmcaddon.Addon(aid).openSettings()
    except Exception:
        pass


_open()
