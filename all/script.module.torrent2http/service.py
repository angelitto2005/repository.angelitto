# -*- coding: utf-8 -*-

import xbmc, sys

from lib.torrent2http.remote.server import Server
from lib.torrent2http.remote.log import debug


def main():
    debug('Starting server')
    
    server = Server()
    server.loop()
    monitor = xbmc.Monitor()
    
    #try:
    while not monitor.abortRequested():
        if monitor.waitForAbort(1):
            break
        #server.loop()
        xbmc.sleep(1000)
            
    #except KeyboardInterrupt:
        ## Exit on ctrl+C
        #debug('Exit')
        #server.stop()
        #sys.exit()
        
    debug('Exit')
    server.stop()

if __name__ == '__main__':
    from lib.torrent2http.remote.remotesettings import Settings
    s = Settings(None)

    if s.role == 'server' or s.mrsprole:
        main()
