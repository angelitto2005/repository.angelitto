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

from functions import *
import xbmc, xbmcaddon
import sys
import os

__settings__ = xbmcaddon.Addon(id='script.module.libtorrent')
__version__ = __settings__.getAddonInfo('version')
__plugin__ = __settings__.getAddonInfo('name') + " v." + __version__
__language__ = __settings__.getLocalizedString
__root__ = os.path.dirname(os.path.dirname(__file__))

libtorrent=None
platform = get_platform()
set_dirname=__settings__.getSetting('dirname')
if getSettingAsBool('custom_dirname') and set_dirname:
    log('set_dirname:' +str(set_dirname))
    dirname=set_dirname
else:
    dirname = os.path.join(xbmc.translatePath('special://temp'), 'xbmcup', 'script.module.libtorrent',
                           'python_libtorrent')

log('dirname:' +str(dirname))

versions = ['0.16.19', '1.0.6', '1.0.7', '1.0.8', '1.0.9', '1.1.0', '1.1.1', '1.0.11']
default_path = versions[-2]
set_version = int(__settings__.getSetting('set_version'))
if getSettingAsBool('custom_version'):
    log('set_version:' +str(set_version)+' '+versions[set_version])
    platform['version'] = versions[set_version]
else:
    platform['version'] = default_path

sizefile_path = os.path.join(__root__, platform['system'], platform['version'])
if not os.path.exists(sizefile_path):
    log('set_version: no sizefile at %s back to default %s' % (sizefile_path, default_path))
    platform['version'] = default_path
    sizefile_path = os.path.join(__root__, platform['system'], platform['version'])
    if not os.path.exists(sizefile_path):
        log('set_version: no default at %s searching for any version' % sizefile_path)
        versions = os.listdir(os.path.join(__root__, platform['system']))
        for ver in versions:
            if not os.path.isdir(os.path.join(__root__, platform['system'], ver)):
                versions.remove(ver)

        if len(versions)>0:
            platform['version'] = versions[-1]
            log('set_version: chose %s out of %s' % (platform['version'], str(versions)))
        else:
            log('die because the folder is empty')
            exit()
dest_path = os.path.join(dirname, platform['system'], platform['version'])
sys.path.insert(0, dest_path)

lm=LibraryManager(dest_path, platform)
if not lm.check_exist():
    ok=lm.download()
    xbmc.sleep(2000)


if __settings__.getSetting('plugin_name')!=__plugin__:
    __settings__.setSetting('plugin_name', __plugin__)
    lm.update()

log('platform: ' + str(platform))
if platform['system'] not in ['windows']:
    log('os: '+str(os.uname()))
    log_text = 'ucs4' if sys.maxunicode > 65536 else 'ucs2'
    log_text += ' x64' if sys.maxint > 2147483647 else ' x86'
    log(log_text)

try:
    if platform['system'] in ['linux_x86', 'windows', 'linux_armv6', 'linux_armv7',
                              'linux_x86_64', 'linux_mipsel_ucs2', 'linux_mipsel_ucs4',
                              'linux_aarch64_ucs2', 'linux_aarch64_ucs4']:
        import libtorrent
    elif platform['system'] in ['darwin', 'ios_arm']:
        import imp
        path_list = [dest_path]
        log('path_list = ' + str(path_list))
        fp, pathname, description = imp.find_module('libtorrent', path_list)
        log('fp = ' + str(fp))
        log('pathname = ' + str(pathname))
        try:
            libtorrent = imp.load_module('libtorrent', fp, pathname, description)
        finally:
            if fp: fp.close()
    elif platform['system'] in ['android_armv7', 'android_x86']:
        import imp
        from ctypes import CDLL
        try:
            dll_path=os.path.join(dest_path, 'liblibtorrent.so')
            log('CDLL path = ' + dll_path)
            liblibtorrent=CDLL(dll_path)
            log('CDLL = ' + str(liblibtorrent))
        except:
            # If no permission in dest_path we need to go deeper!
            try:
                dest_path=lm.android_workaround(new_dest_path='/data/data/org.xbmc.kodi/lib/')
                dll_path=os.path.join(dest_path, 'liblibtorrent.so')
                log('NEW CDLL path = ' + dll_path)
                liblibtorrent=CDLL(dll_path)
                log('CDLL = ' + str(liblibtorrent))
            except:
                # http://i3.kym-cdn.com/photos/images/original/000/531/557/a88.jpg
                dest_path=lm.android_workaround(new_dest_path=xbmc.translatePath('special://xbmc'))
                dll_path=os.path.join(dest_path, 'liblibtorrent.so')
                log('NEW CDLL path = ' + dll_path)
                liblibtorrent=CDLL(dll_path)
                log('CDLL = ' + str(liblibtorrent))
        liblibtorrent=CDLL(dll_path)
        log('CDLL = ' + str(liblibtorrent))
        path_list = [dest_path]
        log('path_list = ' + str(path_list))
        fp, pathname, description = imp.find_module('libtorrent', path_list)
        log('fp = ' + str(fp))
        log('pathname = ' + str(pathname))
        try:
            libtorrent = imp.load_module('libtorrent', fp, pathname, description)
        finally:
            if fp: fp.close()

    log('Imported libtorrent v' + libtorrent.version + ' from "' + dest_path + '"')

except Exception, e:
    log('Error importing libtorrent from "' + dest_path + '". Exception: ' + str(e))
    pass

def get_libtorrent():
    return libtorrent
