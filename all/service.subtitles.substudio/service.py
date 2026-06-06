# -*- coding: utf-8 -*-
import sys, os, xbmcaddon, xbmcvfs
lib_path = xbmcvfs.translatePath(os.path.join(xbmcaddon.Addon().getAddonInfo('path'), 'resources', 'lib'))
service_file = os.path.join(lib_path, 'service.py')
with open(service_file, 'r', encoding='utf-8') as f:
    code = f.read()
exec(compile(code, service_file, 'exec'))
