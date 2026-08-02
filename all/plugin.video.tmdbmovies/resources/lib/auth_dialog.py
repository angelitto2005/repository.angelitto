# -*- coding: utf-8 -*-
"""
Dialog de autorizare cu QR code (stil Umbrella) — WindowXMLDialog.

Pattern Kodi 21 — identic cu TraktRatingWindow (input dovedit functional):
- __init__ FARA super().__init__() (doar atribute din kwargs)
- proprietati setate in onInit() + setFocusId()
- doModal() pe MAIN THREAD (input garantat); polling-ul ruleaza in thread daemon
- onAction cu action.getId()
- onInit/onClick/onAction sunt apelate automat de Kodi la open/click/tasta
"""

import time
import threading
import xbmc
import xbmcgui

_CLOSING_ACTIONS = (9, 10, 13, 92, 110, 511, 7, 100)  # ParentDir, PrevMenu, Stop, NavBack, Escape, Delete, Enter, Select


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
            self.setProperty('tmdbmovies.auth_heading', self.heading)
            self.setProperty('tmdbmovies.auth_icon', self.icon)
            self.setProperty('tmdbmovies.auth_addon_icon', self.addon_icon)
            self.setProperty('tmdbmovies.auth_qr', self.qr_image)
            self.setProperty('tmdbmovies.auth_percent', str(self.percent))
            if self.content:
                self.update(self.percent, self.content)
            self.setFocusId(1000)
        except:
            pass

    def onClick(self, controlID):
        if controlID == 1000:
            self.doClose()

    def onAction(self, action):
        try:
            if action.getId() in _CLOSING_ACTIONS:
                self.doClose()
        except:
            pass

    def doClose(self):
        if self._closed:
            return
        self._closed = True
        try:
            self.close()
        except:
            pass

    def iscanceled(self):
        return self._closed

    def close(self):
        self._closed = True
        try:
            xbmcgui.WindowXMLDialog.close(self)
        except:
            pass

    def update(self, percent=0, content=''):
        # Fereastra (si controalele) exista doar dupa onInit — pana atunci
        # getControl ar arunca "Non-Existent Control" in log.
        if not self._ready:
            return
        try:
            self.setProperty('tmdbmovies.auth_percent', str(int(percent)))
            self.getControl(2001).setText(content)
            self.getControl(5000).setPercent(percent)
        except:
            pass


def run_modal_main_thread(dialog):
    """doModal() pe main thread (input garantat, ca TraktRatingWindow);
    se inchide automat la shutdown Kodi (ca _show_modal_abortable din player.py)."""
    mon = xbmc.Monitor()

    def _watch():
        while not mon.abortRequested():
            time.sleep(0.5)
        try:
            dialog.close()
        except:
            pass

    threading.Thread(target=_watch, daemon=True).start()
    dialog.doModal()
