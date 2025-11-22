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

import os
import xbmc, xbmcgui, xbmcvfs, xbmcaddon
from net import HTTP

__libbaseurl__ = "https://github.com/DiMartinoXBMC/script.module.libtorrent/raw/master/python_libtorrent"
__settings__ = xbmcaddon.Addon(id='script.module.libtorrent')
__version__ = __settings__.getAddonInfo('version')
__plugin__ = __settings__.getAddonInfo('name') + " v." + __version__
__icon__=os.path.join(xbmc.translatePath('special://home'), 'addons',
                                   'script.module.libtorrent', 'icon.png')
__language__ = __settings__.getLocalizedString

from python_libtorrent.platform_pulsar import get_platform, get_libname

def log(msg):
    try:
        xbmc.log("### [%s]: %s" % (__plugin__,msg,), level=xbmc.LOGNOTICE )
    except UnicodeEncodeError:
        xbmc.log("### [%s]: %s" % (__plugin__,msg.encode("utf-8", "ignore"),), level=xbmc.LOGNOTICE )
    except:
        xbmc.log("### [%s]: %s" % (__plugin__,'ERROR LOG',), level=xbmc.LOGNOTICE )

def getSettingAsBool(setting):
    return __settings__.getSetting(setting).lower() == "true"

class LibraryManager():
    def __init__(self, dest_path, platform):
        self.dest_path = dest_path
        self.platform = platform
        self.root=os.path.dirname(os.path.dirname(__file__))

    def check_exist(self):
        for libname in get_libname(self.platform):
            if not xbmcvfs.exists(os.path.join(self.dest_path,libname)):
                return False
        return True

    def check_update(self):
        need_update=False
        for libname in get_libname(self.platform):
            if libname!='liblibtorrent.so':
                self.libpath = os.path.join(self.dest_path, libname)
                self.sizepath=os.path.join(self.root, self.platform['system'], self.platform['version'], libname+'.size.txt')
                size=str(os.path.getsize(self.libpath))
                size_old=open( self.sizepath, "r" ).read()
                if size_old!=size:
                    need_update=True
        return need_update

    def update(self):
        if self.check_update():
            for libname in get_libname(self.platform):
                self.libpath = os.path.join(self.dest_path, libname)
                xbmcvfs.delete(self.libpath)
            self.download()

    def download(self):
        xbmcvfs.mkdirs(self.dest_path)
        for libname in get_libname(self.platform):
            dest = os.path.join(self.dest_path, libname)
            log("try to fetch %s" % libname)
            url = "%s/%s/%s/%s.zip" % (__libbaseurl__, self.platform['system'], self.platform['version'], libname)
            if libname!='liblibtorrent.so':
                try:
                    self.http = HTTP()
                    self.http.fetch(url, download=dest + ".zip", progress=True)
                    log("%s -> %s" % (url, dest))
                    xbmc.executebuiltin('XBMC.Extract("%s.zip","%s")' % (dest, self.dest_path), True)
                    xbmcvfs.delete(dest + ".zip")
                except:
                    text = 'Failed download %s!' % libname
                    xbmc.executebuiltin("XBMC.Notification(%s,%s,%s,%s)" % (__plugin__,text,750,__icon__))
            else:
                xbmcvfs.copy(os.path.join(self.dest_path, 'libtorrent.so'), dest)
        return True

    def android_workaround(self, new_dest_path):
        for libname in get_libname(self.platform):
            libpath=os.path.join(self.dest_path, libname)
            size=str(os.path.getsize(libpath))
            new_libpath=os.path.join(new_dest_path, libname)

            if not xbmcvfs.exists(new_libpath):
                xbmcvfs.copy(libpath, new_libpath)
                log('Copied %s -> %s' %(libpath, new_libpath))
                if not xbmcvfs.exists(new_libpath):
                    log('Failed!')
            else:
                new_size=str(os.path.getsize(new_libpath))
                if size!=new_size:
                    xbmcvfs.delete(new_libpath)
                    xbmcvfs.copy(libpath, new_libpath)
                    log('Deleted and copied (%s) %s -> (%s) %s' %(size, libpath, new_size, new_libpath))
        return new_dest_path
