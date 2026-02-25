# Dummy file to make this directory a package.
# -*- coding: utf-8 -*-
"""
Fereastră frumoasă de buffering TorrServer pentru MRSP Lite.
Înlocuiește DialogProgress cu un fullscreen window personalizat.
"""
import xbmc
import xbmcgui
import xbmcaddon
import os
import threading
import time

ADDON = xbmcaddon.Addon('plugin.video.romanianpack')
ADDON_PATH = ADDON.getAddonInfo('path')

# Calea către XML
XML_FILE = 'resolver_window.xml'
SKIN_PATH = os.path.join(ADDON_PATH, 'resources', 'skins', 'Default', '1080i')


class ResolverWindow(xbmcgui.WindowXML):
    """
    Fereastră fullscreen pentru buffering TorrServer.
    
    Folosește Window Properties pentru a comunica cu XML-ul:
      - fanart          : imaginea de background
      - clearlogo       : clearlogo film (opțional)
      - title           : titlul filmului
      - phase_text      : faza curentă (Metadate/Buffering/etc)
      - line1           : linia principală de info
      - line2           : linia secundară (viteză, peers)
      - filename        : numele fișierului (scroll)
      - percent_text    : procentul mare "45%"
      - buffering_active: spinner vizibil
      - buffering_done  : checkmark vizibil
    """

    PROGRESS_CONTROL_ID = 3001

    def __init__(self, *args, **kwargs):
        super(ResolverWindow, self).__init__(*args, **kwargs)
        self._cancelled = False
        self._closed = False
        self._lock = threading.Lock()
        self._percent = 0

    # ─── Lifecycle ────────────────────────────────────
    def onInit(self):
        self.setProperty('buffering_active', '1')
        self.setProperty('buffering_done', '')
        self._update_progress_control(0)

    def onAction(self, action):
        cancel_actions = (
            xbmcgui.ACTION_PREVIOUS_MENU,
            xbmcgui.ACTION_NAV_BACK,
            xbmcgui.ACTION_STOP,
            92,  # ACTION_PLAYER_STOP
        )
        if action.getId() in cancel_actions:
            self._cancelled = True
            self.close_window()

    def onClick(self, controlId):
        pass

    # ─── Public API ───────────────────────────────────

    def is_cancelled(self):
        return self._cancelled

    def is_closed(self):
        return self._closed

    def close_window(self):
        with self._lock:
            if not self._closed:
                self._closed = True
                try:
                    self.close()
                except:
                    pass

    def set_background(self, fanart="", clearlogo="", title=""):
        """Setează background-ul: fanart, clearlogo, titlu."""
        self.setProperty('fanart', fanart or '')
        self.setProperty('clearlogo', clearlogo or '')
        self.setProperty('title', title or '')

    def set_phase(self, text):
        """Setează faza curentă: 'Descarcă metadate...', 'Buffering...' etc."""
        self.setProperty('phase_text', text)

    def update(self, percent, line1="", line2="", filename=""):
        """Actualizează progresul și textele."""
        self._percent = max(0, min(100, int(percent)))
        self.setProperty('line1', line1)
        self.setProperty('line2', line2)
        if filename:
            self.setProperty('filename', filename)
        if self._percent > 0:
            self.setProperty('percent_text', '%d%%' % self._percent)
        else:
            self.setProperty('percent_text', '')
        self._update_progress_control(self._percent)

    def show_done(self, text="Stream gata!"):
        """Arată checkmark și mesajul de succes."""
        self.setProperty('buffering_active', '')
        self.setProperty('buffering_done', '1')
        self.setProperty('phase_text', text)
        self.setProperty('percent_text', '100%')
        self._update_progress_control(100)

    def _update_progress_control(self, percent):
        """Actualizează progress bar-ul (control 3001)."""
        try:
            ctrl = self.getControl(self.PROGRESS_CONTROL_ID)
            if ctrl:
                ctrl.setPercent(float(percent))
        except:
            pass


def create_resolver_window(fanart="", clearlogo="", title=""):
    """
    Creează și afișează fereastra de resolver.
    
    Returnează instanța ResolverWindow.
    """
    try:
        win = ResolverWindow(
            XML_FILE,
            ADDON_PATH,
            'Default',
            '1080i'
        )
        win.set_background(fanart, clearlogo, title)
        win.show()
        # Dăm un mic delay pentru ca fereastra să se inițializeze
        xbmc.sleep(200)
        return win
    except Exception as e:
        xbmc.log("[MRSP Lite] ResolverWindow create error: %s" % str(e),
                 xbmc.LOGERROR)
        return None