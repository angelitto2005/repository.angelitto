#-*- coding: utf-8 -*-
'''
    python-libtorrent for Kodi (script.module.libtorrent)
    Copyright (C) 2015-2016 DiMartino, srg70, RussakHH, aisman

    Permission is hereby granted, free of charge, to any person obtaining
    a copy of this software and associated documentation files (the
    "Software"), to deal in the Software without restriction, including
    without limitation the rights to use, copy, modify, merge, publish,
    distribute, sublicense, and/or sell copies of the Software, and to
    permit persons to whom the Software is furnished to do so, subject to
    the following conditions:

    The above copyright notice and this permission notice shall be
    included in all copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
    EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
    MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
    NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
    LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
    OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
    WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
'''

from python_libtorrent.python_libtorrent import get_libtorrent, log
from python_libtorrent.platform_pulsar import get_platform
import xbmcgui
import xbmcaddon, xbmc

sucsess=False
version=''
p=get_platform()
dialog = xbmcgui.Dialog()

try:
    libtorrent=get_libtorrent()

    log('Imported libtorrent v' + libtorrent.version + ' from get_libtorrent()')
    version=str(libtorrent.version)
    sucsess=True
except Exception, e:
    log('Error importing from get_libtorrent(). Exception: ' + str(e))


line2='python-libtorrent %s IMPORTED successfully' % version if sucsess else 'Failed to import python-libtorrent!'
dialog.ok('Libtorrent','OS:'+p['os']+' arch:'+p['arch'], line2)

__settings__ = xbmcaddon.Addon(id='script.module.libtorrent')
__language__ = __settings__.getLocalizedString
if __settings__.getSetting('ask_dirname')=='true':
    set_dirname=__settings__.getSetting('dirname')
    __settings__.setSetting('ask_dirname','false')
    keyboard = xbmc.Keyboard(set_dirname, __language__(1002))
    keyboard.doModal()
    path_keyboard = keyboard.getText()
    if path_keyboard and keyboard.isConfirmed():
        __settings__.setSetting('dirname', path_keyboard)