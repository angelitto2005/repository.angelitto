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

import sys
import os
try:
    import xbmc, xbmcaddon
    __settings__ = xbmcaddon.Addon(id='script.module.libtorrent')
    __version__ = __settings__.getAddonInfo('version')
    __plugin__ = __settings__.getAddonInfo('name') + " v." + __version__
except:
    __plugin__ = 'script.module.libtorrent'
    pass

def log(msg):
    try:
        xbmc.log("### [%s]: %s" % (__plugin__,msg,), level=xbmc.LOGNOTICE )
    except UnicodeEncodeError:
        xbmc.log("### [%s]: %s" % (__plugin__,msg.encode("utf-8", "ignore"),), level=xbmc.LOGNOTICE )
    except:
        try:
            xbmc.log("### [%s]: %s" % (__plugin__,'ERROR LOG',), level=xbmc.LOGNOTICE )
        except:
            print msg

def get_libname(platform):
    libname=[]
    if platform['system'] in ['darwin', 'linux_x86', 'linux_arm', 'linux_armv6',
                              'linux_armv7', 'linux_x86_64', 'ios_arm',
                              'linux_mipsel_ucs2', 'linux_mipsel_ucs4', 'linux_aarch64_ucs2', 'linux_aarch64_ucs4']:
        libname=['libtorrent.so']
    elif platform['system'] == 'windows':
        libname=['libtorrent.pyd']
    elif platform['system'] in ['android_armv7', 'android_x86']:
        libname=['libtorrent.so', 'liblibtorrent.so']
    return libname

def get_platform():
    __settings__ = xbmcaddon.Addon(id='script.module.libtorrent')
    __version__ = __settings__.getAddonInfo('version')
    __plugin__ = __settings__.getAddonInfo('name') + " v." + __version__
    __language__ = __settings__.getLocalizedString

    if __settings__.getSetting('custom_system').lower() == "true":
        system = int(__settings__.getSetting('set_system'))
        log('USE CUSTOM SYSTEM: '+__language__(1100+system))

        ret={}

        if system==0:
            ret["os"] = "windows"
            ret["arch"] = "x86"
        elif system==1:
            ret["os"] = "linux"
            ret["arch"] = "x86"
        elif system==2:
            ret["os"] = "linux"
            ret["arch"] = "x64"
        elif system==3:
            ret["os"] = "linux"
            ret["arch"] = "armv7"
        elif system==4:
            ret["os"] = "linux"
            ret["arch"] = "armv6"
        elif system==5:
            ret["os"] = "android"
            ret["arch"] = "arm"
        elif system==6:
            ret["os"] = "android"
            ret["arch"] = "x86"
        elif system==7:
            ret["os"] = "darwin"
            ret["arch"] = "x64"
        elif system==8:
            ret["os"] = "ios"
            ret["arch"] = "arm"
        elif system==9:
            ret["os"] = "ios"
            ret["arch"] = "arm"
        elif system==10:
            ret["os"] = "linux"
            ret["arch"] = "mipsel_ucs2"
        elif system==11:
            ret["os"] = "linux"
            ret["arch"] = "mipsel_ucs4"
        elif system == 12:
            ret["os"] = "linux"
            ret["arch"] = "linux_aarch64_ucs2"
        elif system == 13:
            ret["os"] = "linux"
            ret["arch"] = "linux_aarch64_ucs4"
    else:

        ret = {
            "arch": sys.maxsize > 2 ** 32 and "x64" or "x86",
        }
        if xbmc.getCondVisibility("system.platform.android"):
            ret["os"] = "android"
            if "arm" in os.uname()[4] or "aarch64" in os.uname()[4]:
                ret["arch"] = "arm"
        elif xbmc.getCondVisibility("system.platform.linux"):
            ret["os"] = "linux"
            uname=os.uname()[4]
            if "arm" in uname:
                if "armv7" in uname:
                    ret["arch"] = "armv7"
                elif "armv6" in uname:
                    ret["arch"] = "armv6"
                else:
                    ret["arch"] = "arm"
            elif "mips" in uname:
                if sys.maxunicode > 65536:
                    ret["arch"] = 'mipsel_ucs4'
                else:
                    ret["arch"] = 'mipsel_ucs2'
            elif "aarch64" in uname:
                if sys.maxint > 2147483647: #is_64bit_system
                    if sys.maxunicode > 65536:
                        ret["arch"] = 'aarch64_ucs4'
                    else:
                        ret["arch"] = 'aarch64_ucs2'
                else:
                    ret["arch"] = "armv7" #32-bit userspace
        elif xbmc.getCondVisibility("system.platform.windows"):
            ret["os"] = "windows"
        elif xbmc.getCondVisibility("system.platform.osx"):
            ret["os"] = "darwin"
        elif xbmc.getCondVisibility("system.platform.ios"):
            ret["os"] = "ios"
            ret["arch"] = "arm"

    ret=get_system(ret)
    return ret

def get_system(ret):
    ret["system"] = ''
    ret["message"] = ['', '']

    if ret["os"] == 'windows':
        ret["system"] = 'windows'
        ret["message"] = ['Windows has static compiled python-libtorrent included.',
                          'You should install "script.module.libtorrent" from "MyShows.me Kodi Repo"']
    elif ret["os"] == "linux" and ret["arch"] == "x64":
        ret["system"] = 'linux_x86_64'
        ret["message"] = ['Linux x64 has not static compiled python-libtorrent included.',
                          'You should install it by "sudo apt-get install python-libtorrent"']
    elif ret["os"] == "linux" and ret["arch"] == "x86":
        ret["system"] = 'linux_x86'
        ret["message"] = ['Linux has static compiled python-libtorrent included but it didn\'t work.',
                          'You should install it by "sudo apt-get install python-libtorrent"']
    elif ret["os"] == "linux" and "aarch64" in ret["arch"]:
        ret["system"] = 'linux_' + ret["arch"]
        ret["message"] = ['Linux has static compiled python-libtorrent included but it didn\'t work.',
                          'You should install it by "sudo apt-get install python-libtorrent"']
    elif ret["os"] == "linux" and ("arm" or "mips" in ret["arch"]):
        ret["system"] = 'linux_'+ret["arch"]
        ret["message"] = ['As far as I know you can compile python-libtorrent for ARMv6-7.',
                          'You should search for "OneEvil\'s OpenELEC libtorrent" or use Ace Stream.']
    elif ret["os"] == "android":
        if ret["arch"]=='arm':
            ret["system"] = 'android_armv7'
        else:
            ret["system"] = 'android_x86'
        ret["message"] = ['Please contact DiMartino on kodi.tv forum. We compiled python-libtorrent for Android,',
                          'but we need your help with some tests on different processors.']
    elif ret["os"] == "darwin":
        ret["system"] = 'darwin'
        ret["message"] = ['It is possible to compile python-libtorrent for OS X.',
                          'But you would have to do it by yourself, there is some info on github.com.']
    elif ret["os"] == "ios" and ret["arch"] == "arm":
        ret["system"] = 'ios_arm'
        ret["message"] = ['It is probably NOT possible to compile python-libtorrent for iOS.',
                          'But you can use torrent-client control functions.']

    return ret