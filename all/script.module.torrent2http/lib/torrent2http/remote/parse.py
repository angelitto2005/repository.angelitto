import sys
import json
import base64
import os
try:
    from urlparse import urljoin
    from urllib import pathname2url
    py3 = False
except:
    from urllib.parse import urljoin
    from urllib.request import pathname2url
    import urllib.parse as urllib
    py3 = True

def path2url(path):
    return urljoin('file:', pathname2url(path))


def remote_t2h_torrent_path():
    if py3:
        import xbmcvfs
        return xbmcvfs.translatePath('special://temp/rt2h.torrent')
    else:
        import xbmc
        return xbmc.translatePath('special://temp/rt2h.torrent')

    
def parse(argv, s):

    args = None
    torrent_data = None
    data = None

    for i in argv:

        if i.startswith('args='):
            args = base64.b64decode(i[5:])
            args = json.loads(args)
        if i.startswith('torrent_data='):
            torrent_data = base64.b64decode(i[12:])
        if i.startswith('dict='):
            data = base64.b64decode(i[5:])
            data = json.loads(data)
            print(data)

    # import rpdb2
    # rpdb2.start_embedded_debugger('pw')

    torrent_path = None
    if torrent_data:
        torrent_path = remote_t2h_torrent_path()
        with open(torrent_path, 'wb') as t:
            t.write(torrent_data)

    start_index = None
    bind_port = None
    if args:
        try:
            i = args.index('--file-index') + 1
            start_index = int(args[i])
        except:
            pass

        try:
            i = args.index('--bind') + 1
            bind_port = int(args[i].split(':')[1])
        except:
            pass

        if torrent_path:
            try:
                i = args.index('--uri') + 1
                args[i] = path2url(torrent_path)
            except:
                args.append('--uri')
                args.append(path2url(torrent_path))


    if data:
        if torrent_path:
            data['uri'] = path2url(torrent_path)

        if s:
            data['download_path'] = s.storage_path
            data['binaries_path'] = s.binaries_path
            
        data['bind_host'] = s.remote_host
        if bind_port:
            data['bind_port'] = bind_port

        from .remoteengine import ServerEngine
        e = ServerEngine(**data)
        if data.get('cmdline_proc'):
            return e.start(start_index=start_index)
        e.start(start_index=start_index)

        print(e)
        
        return e
        
    return None
