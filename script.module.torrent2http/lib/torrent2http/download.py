#import sys
import os
import xbmc, xbmcgui, xbmcvfs, xbmcaddon
from .net import HTTP
try:
    import urllib2
    py3 = False
except ImportError:
    py3 = True

__libbaseurl__ = "https://github.com/xngsrs/script.module.torrent2http/raw/master/bin"
__settings__ = xbmcaddon.Addon(id='script.module.torrent2http')
__version__ = __settings__.getAddonInfo('version')
__plugin__ = __settings__.getAddonInfo('name') + " v." + __version__

def get_libname(platform):
    return ["torrent2http" + (".exe" if 'windows' in platform else "")]

def log(msg):
    loginfo = xbmc.LOGINFO if py3 else xbmc.LOGNOTICE
    try:
        xbmc.log("### [%s]: %s" % (__plugin__,msg,), level=loginfo )
    except UnicodeEncodeError:
        xbmc.log("### [%s]: %s" % (__plugin__,msg.encode("utf-8", "ignore"),), level=loginfo )
    except:
        xbmc.log("### [%s]: %s" % (__plugin__,'ERROR LOG',), level=loginfo )

def getSettingAsBool(setting):
    return __settings__.getSetting(setting).lower() == "true"

class LibraryManager():
    def __init__(self, dest_path, platform):
        self.dest_path = dest_path
        self.platform = platform

    def check_update(self):
        need_update=False
        if __settings__.getSetting('plugin_name')!=__plugin__:
            __settings__.setSetting('plugin_name', __plugin__)
            for libname in get_libname(self.platform):
                self.libpath = os.path.join(self.dest_path, libname)
                self.sizepath=os.path.join(self.dest_path, libname+'.size.txt')
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
        from . import patoolib
        xbmcvfs.mkdirs(self.dest_path)
        for libname in get_libname(self.platform):
            dest = os.path.join(self.dest_path, libname)
            log("try to fetch %s" % libname)
            url = "%s/%s/%s.zip" % (__libbaseurl__, self.platform, libname)
            try:
                self.http = HTTP()
                self.http.fetch(url, download=dest + ".zip", progress=True)
                log("%s -> %s" % (url, dest))
                xbmc.sleep(2000)
                try:
                    patoolib.extract_archive('%s.zip' % dest, outdir=self.dest_path)
                except:
                    xbmc.executebuiltin('Extract("%s.zip")' % (dest), True)
                xbmcvfs.delete(dest + ".zip")
            except BaseException as e:
                log(e)
                text = 'Failed download %s!' % libname
                xbmc.executebuiltin("Notification(%s,%s,%s)" % (__plugin__,text,750))
        return True
