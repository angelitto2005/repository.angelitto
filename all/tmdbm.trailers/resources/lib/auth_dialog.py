import time
import threading
import xbmc
import xbmcgui

_CLOSING_ACTIONS = (9, 10, 13, 92, 110, 511, 7, 100)


class QRProgressDialog(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        self._closed = False
        self.expired = False
        self._ready = False
        self.heading = kwargs.get('heading', 'Authorization')
        self.qr_image = kwargs.get('qr_image') or ''
        self.icon = kwargs.get('icon') or ''
        self.addon_icon = kwargs.get('addon_icon') or ''
        self.content = kwargs.get('content', '')
        self.percent = kwargs.get('percent', 100)

    def onInit(self):
        self._ready = True
        try:
            self.setProperty('tmdbm.auth_heading', self.heading)
            self.setProperty('tmdbm.auth_icon', self.icon)
            self.setProperty('tmdbm.auth_addon_icon', self.addon_icon)
            self.setProperty('tmdbm.auth_qr', self.qr_image)
            self.setProperty('tmdbm.auth_percent', str(self.percent))
            if self.content:
                self.update(self.percent, self.content)
            self.setFocusId(1000)
        except Exception:
            pass

    def onClick(self, controlID):
        if controlID == 1000:
            self.doClose()

    def onAction(self, action):
        try:
            if action.getId() in _CLOSING_ACTIONS:
                self.doClose()
        except Exception:
            pass

    def doClose(self):
        if self._closed:
            return
        self._closed = True
        try:
            self.close()
        except Exception:
            pass

    def iscanceled(self):
        return self._closed

    def close(self):
        self._closed = True
        try:
            xbmcgui.WindowXMLDialog.close(self)
        except Exception:
            pass

    def update(self, percent=0, content=''):
        if not self._ready:
            return
        try:
            self.setProperty('tmdbm.auth_percent', str(int(percent)))
            self.getControl(2001).setText(content)
            self.getControl(5000).setPercent(percent)
        except Exception:
            pass


def run_modal_main_thread(dialog):
    mon = xbmc.Monitor()
    _done = {'flag': False}

    def _watch():
        while not mon.abortRequested() and not _done['flag']:
            time.sleep(0.5)
        if mon.abortRequested():
            try:
                dialog.close()
            except Exception:
                pass

    threading.Thread(target=_watch, daemon=True).start()
    dialog.doModal()
    _done['flag'] = True
