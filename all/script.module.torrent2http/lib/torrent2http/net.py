# -*- coding: utf-8 -*-

import os
import time
import re
import base64

import xbmc
import xbmcgui
import xbmcvfs
import requests
try:
    import urllib2
    py3 = False
except ImportError:
    py3 = True

def log(msg):
    loginfo = xbmc.LOGINFO if py3 else xbmc.LOGNOTICE
    try:
        xbmc.log("### [%s]: %s" % ('torrent2http net',msg,), level=loginfo )
    except UnicodeEncodeError:
        xbmc.log("### [%s]: %s" % ('torrent2http net',msg.encode("utf-8", "ignore"),), level=loginfo )
    except:
        xbmc.log("### [%s]: %s" % ('torrent2http net','ERROR LOG',), level=loginfo )

class HTTP:
    def __init__(self):
        if py3: self._dirname = xbmcvfs.translatePath('special://temp')
        else: self._dirname = xbmc.translatePath('special://temp')
        for subdir in ('xbmcup', 'script.module.libtorrent'):
            self._dirname = os.path.join(self._dirname, subdir)
            if not xbmcvfs.exists(self._dirname):
                xbmcvfs.mkdir(self._dirname)

    def fetch(self, request, **kwargs):
        self.request =  request
        self.progress = True
        self.dest = kwargs.get('download')
        s = requests.Session()
        r = s.head(self.request, allow_redirects=False)
        if 'location' in r.headers:
            r = s.get(r.headers.get('location'))
        if self.progress:
            self.progres = xbmcgui.DialogProgressBG()
            self.progres.create(u'Download', 'torrent2http loading...')

        bs = 1024 * 8
        size = -1
        read = 0
        name = "Torrent2http.zip"
        fd = open(self.dest, 'wb')
        if self.progress:
            if 'content-length' in r.headers:
                size = int(r.headers.get('content-length'))
        
        with open(self.dest, 'wb') as fd:
            for buf in r.iter_content(chunk_size=bs):
                if buf:
                    if self.progress:
                        read += len(buf)
                        self.progres.update(*self._progress(read, size, name))
                    fd.write(buf)

        if self.progress:
            self.progres.close()
            self.progres = None

        return True  

    def _progress(self, read, size, name):
        res = []
        res2 = ''
        if size < 0:
            res.append(1)
        else:
            res.append(int(float(read) / (float(size) / 100.0)))
        if name:
            res2 += u'File: %s \n' % name
        if size != -1:
            res2 += u'Size: %s \n' % self._human(size)
        res2 += u'Load: %s' % self._human(read)
        res.append(res2)
        return res

    def _human(self, size):
        power = 2**10
        n = 0
        power_labels = {0 : 'B', 1: 'KB', 2: 'MB', 3: 'GB', 4: 'TB'}
        while size > power:
            size /= power
            n += 1
        return '{:.2f}{}'.format(size, power_labels[n])
