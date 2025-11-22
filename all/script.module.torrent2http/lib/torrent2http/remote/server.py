# -*- coding: utf-8 -*-

import threading
from wsgiref.simple_server import make_server, WSGIRequestHandler

from .bottle import Bottle, ServerAdapter, response, redirect, abort
from .bottle import request #get, request, run, route # or route

import sys, xbmc, os
from .log import debug, print_tb, logs

from .parse import parse
from .remotesettings import Settings
s = Settings()

from . import bottle
bottle.BaseRequest.MEMFILE_MAX = 1024 * 1024 * 3

from . import filesystem


_JS_ = '''
function close_procces(pid) {
    var x = new XMLHttpRequest();

    x.open("GET", "/close_me?pid=" + pid, true);
    x.send(null);
}
function stop_procces(pid) {
    var x = new XMLHttpRequest();

    x.open("GET", "/stop_me?pid=" + pid, true);
    x.send(null);
}
function resume_procces(pid) {
    var x = new XMLHttpRequest();

    x.open("GET", "/resume_me?pid=" + pid, true);
    x.send(null);
}
'''

def _TD_(val):
    try:
        if isinstance(val, unicode):
            val = val.encode('utf-8')
    except:
        pass

    return "<td>" + str(val) + "</td>"


def _TH_(val):
    return "<th>" + str(val) + "</th>"


def _TR_(val):
    return "<tr>" + str(val) + "</tr>"


def statgui():
    current = os.path.dirname(__file__)

    text = ''
    try:
        with open(os.path.join(current, 'statgui.css'), 'r') as css:
            text = css.read()
    except:
        with open(os.path.join(current, 'statgui.css'), 'r', encoding="utf-8") as css:
            text = css.read()
    return text


def kill(pid):
    return '<a href="javascript:void(0)" onclick="close_procces(%d); return false;">Kill!</a>' % pid

def pstop(pid):
    return '<a href="javascript:void(0)" onclick="stop_procces(%d); return false;">Stop!</a>' % pid

def presume(pid):
    return '<a href="javascript:void(0)" onclick="resume_procces(%d); return false;">Resume</a>' % pid

def _HEAD_():
    res = '<head>'

    res += '<style>'
    res += statgui()
    res += '</style>'

    res += '<script type="text/javascript">'
    res += _JS_
    res += '</script>'

    res += '</head>'

    return res

def _2MB_(val):
    return '%.2f MB' % (float(val) / 1024 / 1024)

def _2MBit_s_(val):
    return '%d Mbit/s' % int(float(val) / 1024 * 8)

def _2percent_(val):
    return '%.1f%%' % (float(val) * 100)

class HTTP:
    engines = []
    
    def test(self):
        debug('test')
        return "<p>Test - Ok</p>"

    def stat(self):

        page = '<html>'

        page += _HEAD_()

        page += "<body><table>"
        # Head

        page += _TR_(_TH_('pid') 
            + _TH_('name') 
            + _TH_('state') 
            + _TH_('progress') 
            + _TH_('download_rate') 
            + _TH_('upload_rate') 
            + _TH_('total_download') 
            + _TH_('total_upload') 
            + _TH_('peers') 
            + _TH_('seeds') 
            + _TH_('total_seeds') 
            + _TH_('total_peers')
            + _TH_('hash_string')
            + _TH_('session_status')
            + _TH_('host')
            + _TH_('port') 
            + _TH_('action')
            + _TH_('action2')
            + _TH_('action3'))

        #N = 1
        for eng in self.engines:
            try:
                s = eng.status()
                pid = eng.pid()
                page += _TR_(_TD_('<a href="/status?pid=%d">%d</a>' % (pid, pid)) 
                    + _TD_(s.name) 
                    + _TD_(s.state_str) 
                    + _TD_(_2percent_(s.progress)) 
                    + _TD_(_2MBit_s_(s.download_rate))
                    + _TD_(_2MBit_s_(s.upload_rate)) 
                    + _TD_(_2MB_(s.total_download)) 
                    + _TD_(_2MB_(s.total_upload)) 
                    + _TD_(s.num_peers) 
                    + _TD_(s.num_seeds) 
                    + _TD_(s.total_seeds) 
                    + _TD_(s.total_peers)
                    + _TD_(s.hash_string)
                    + _TD_(s.session_status)
                    + _TD_(eng.bind_host)
                    + _TD_(eng.bind_port)
                    + _TD_(kill(pid))
                    + _TD_(pstop(pid))
                    + _TD_(presume(pid))) 
            except BaseException as e:
                if str(e) == str('torrent2http has crashed.'):
                    engn = self.engine_by(eng.pid())
                    self.engines.remove(engn)
                pass

            #N += 1

        page += "</table></body></html>"

        return page
    
    def statjson(self):
        data = []
        for eng in self.engines:
            try:
                s = eng.status()
                pid = eng.pid()
                data.append({"pid": pid, 
                             "name": s.name, 
                             "state_str": s.state_str, 
                             "progress": s.progress, 
                             "download_rate": s.download_rate, 
                             "upload_rate": s.upload_rate, 
                             "total_download": s.total_download, 
                             "total_upload": s.total_upload, 
                             "num_peers": s.num_peers, 
                             "num_seeds": s.num_seeds, 
                             "total_seeds": s.total_seeds, 
                             "total_peers": s.total_peers,
                             "hash_string": s.hash_string,
                             "bind_host": eng.bind_host,
                             "bind_port": eng.bind_port})
            except:
                pass
        return dict(data=data)
    
    def statusjson(self):
        data = []
        try:
            t = next((engn for engn in self.engines if engn.pid() == int(request.params.get('pid'))), None)
            s = t.list()
            pid = t.pid()
            for fb in s:
                data.append({"pid": pid,
                        "name": fb.name,
                        "save_path": fb.save_path, 
                        "url": fb.url, 
                        "size": fb.size, 
                        "offset": fb.offset, 
                        "download": fb.download, 
                        "progress": fb.progress, 
                        "index": fb.index, 
                        "media_type": fb.media_type})
        except:
            pass
        return dict(data=data)

    def status(self):
        response = ''
        page = '<html>'
        page += _HEAD_()
        page += "<body><table>"
        page += _TR_(_TH_('pid') 
            + _TH_('name') 
            + _TH_('save_path') 
            + _TH_('url') 
            + _TH_('size') 
            + _TH_('offset') 
            + _TH_('download') 
            + _TH_('progress') 
            + _TH_('index') 
            + _TH_('media type')
            + _TH_('priority')) 
        try:
            t = next((engn for engn in self.engines if engn.pid() == int(request.params.get('pid'))), None)
            s = t.list()
            pid = t.pid()
            for fb in s:
                page += _TR_(_TD_(pid)
                    + _TD_(fb.name)
                    + _TD_(fb.save_path)
                    + _TD_(fb.url)
                    + _TD_(fb.size)
                    + _TD_(fb.offset)
                    + _TD_(fb.download)
                    + _TD_(fb.progress)
                    + _TD_(fb.index)
                    + _TD_(fb.media_type)
                    + _TD_(fb.priority))
        except:
            pass
        page += "</table></body></html>"
        return page
        
    def engine_by(self, pid):
        return next((engn for engn in self.engines if engn.pid() == pid), None)
        
    def engine(self):
        try:
            pid = int(request.params.get('pid'))
            return self.engine_by(pid)
        except:
            return None
        
    def do_popen(self):
        import base64
        import json
        try:
            debug('do_popen')
            
            args_str    = request.forms.get('args')
            tdata       = request.forms.get('torrent_data')
            dict_str    = request.forms.get("dict")

            argv = ['args=' + args_str,
                    'torrent_data=' + tdata,
                    'dict=' + dict_str]

            engn = parse(argv, s)
            cmdp = base64.b64decode(dict_str)
            cmdp = json.loads(cmdp)
            cmdps = cmdp.get('cmdline_proc') or None
            if cmdps:
                return engn
            self.engines.append(engn)

            return str(engn.pid()) + '.' + str(engn.bind_port)
        except BaseException as e:
            print_tb(e)
            return "None"
            
    def close(self):
        engn = self.engine()
        self.engines.remove(engn)

    def close_me(self):
        engn = self.engine()
        #engn.process.terminate()
        engn.wait_on_close(1)
        engn.close()
        self.engines.remove(engn)
        
    def stop_me(self):
        engn = self.engine()
        engn.stop()
        
    def resume_me(self):
        engn = self.engine()
        engn.resume()
        
    def poll(self):
        try:
            return str(self.engine().process.poll())
        except BaseException as e:
            print_tb(e)
            return "None"
            
    def wait(self):
        try:
            return str(self.engine().process.wait())
        except BaseException as e:
            print_tb(e)
            return "0"

    def terminate(self):
        try:
            return self.engine().process.terminate()
        except BaseException as e:
            print_tb(e)
            return "Fail"

    def kill(self):
        try:
            return self.engine().process.kill()
        except BaseException as e:
            print_tb(e)
            return "Fail"
            
    def do_can_bind(self):
        try:
            from ..util import can_bind

            host = ''
            port = request.forms.get('port')
            debug('can_bind: ' + port)
            return str(can_bind(host, int(port)))
        except BaseException as e:
            print_tb(e)
            return "False"
        
    def do_find_free_port(self):
        try:
            from ..util import find_free_port
            
            host = ''
            debug('find_free_port: ')
            return str(find_free_port(host))
        except BaseException as e:
            print_tb(e)
            return "0"
        
class Server:
    def __init__(self):
        self.server = None
        self.http = HTTP()
        
        self.run()

    def loop(self):
        pass
    
    def run(self):
        debug('Run')
        threading.Thread(target=self._run).start()
        import xbmcaddon
        from .remoteengine import ClientEngine as Engine

        if s.mrsprole:
            try: storagepath = s.storage_path.decode()
            except: storagepath = s.storage_path
            try: resumefolder = filesystem.join(storagepath, '.resume').decode()
            except: resumefolder = filesystem.join(storagepath, '.resume')
            if filesystem.exists(resumefolder):
                try: allresume = [f for f in filesystem.listdir(resumefolder) if filesystem.isfile(filesystem.join(resumefolder, f).decode())]
                except: allresume = [f for f in filesystem.listdir(resumefolder) if filesystem.isfile(filesystem.join(resumefolder, f))]
                for i in allresume:
                    try: filet = filesystem.join(resumefolder, i).decode()
                    except: filet = filesystem.join(resumefolder, i)
                    encryption = int(s.mrgetset('encryption'))
                    upload_limit = int(s.mrgetset('upload_limit')) if s.mrgetset('upload_limit') != '' else 0
                    download_limit = int(s.mrgetset('download_limit')) if s.mrgetset('download_limit') != '' else 0
                    if s.mrgetset('connections_limit') not in ["",0,"0"]:
                        connections_limit = int(s.mrgetset('connections_limit'))
                    else: connections_limit = None
                    use_random_port = s.mrgetset('use_random_port') == 'true'
                    listen_port = int(s.mrgetset('listen_port')) if s.mrgetset('listen_port') != '' else 6881
                    keep_complete = True
                    keep_incomplete = True
                    keep_files = True
                    resume_file = filet
                    
                    enable_dht = s.mrgetset('enable_dht') == 'true'
                    enable_lsd = s.mrgetset('enable_lsd') == 'true'
                    enable_upnp = s.mrgetset('enable_upnp') == 'true'
                    enable_natpmp = s.mrgetset('enable_natpmp') == 'true'
                    enable_utp = s.mrgetset('enable_utp') == 'true'
                    enable_tcp = s.mrgetset('enable_tcp') == 'true'
                    enable_scrape = s.mrgetset('enable_scrape') == 'true'
                    no_sparse = s.mrgetset('no_sparse') == 'true'
                    dht_routers = ["router.bittorrent.com:6881","router.utorrent.com:6881"]
                    tuned_storage = s.mrgetset('tuned_storage') == 'true'
                    connection_speed = int(s.mrgetset('connection_speed')) if s.mrgetset('connection_speed') else 100
                    user_agent = ''#'Transmission/2.12 (234)'
                    engine = Engine(uri=filet, download_path=s.mrgetset('storage'),
                                        connections_limit=connections_limit, download_kbps=download_limit, upload_kbps=upload_limit,
                                        encryption=encryption, keep_complete=keep_complete, keep_incomplete=keep_incomplete,
                                        connection_speed=connection_speed, tuned_storage=tuned_storage,
                                        dht_routers=dht_routers, use_random_port=use_random_port, listen_port=listen_port,
                                        keep_files=keep_files, user_agent=user_agent, resume_file=resume_file, enable_dht=enable_dht,
                                        enable_lsd=enable_lsd, enable_upnp=enable_upnp, enable_natpmp=enable_natpmp,
                                        no_sparse=no_sparse, enable_utp=enable_utp, enable_scrape=enable_scrape, enable_tcp=enable_tcp)
                    if s.mrspstartpaused: 
                        engine.start(-1)
                    else:
                        engine.start(9999)

    def _run(self):
        debug('Running in thread')
        app = Bottle()
        app.route('/test', callback=self.http.test)
        app.route('/stat', callback=self.http.stat)
        app.route('/stat/json', callback=self.http.statjson)

        
        app.route('/popen', method='POST', callback=self.http.do_popen)
        app.route('/can_bind', method='POST', callback=self.http.do_can_bind)
        app.route('/find_free_port', method='POST', callback=self.http.do_find_free_port)
        
        app.route('/poll', callback=self.http.poll)
        app.route('/wait', callback=self.http.wait)
        app.route('/terminate', callback=self.http.terminate)
        app.route('/kill', callback=self.http.kill)

        app.route('/close', callback=self.http.close)
        app.route('/close_me', callback=self.http.close_me)
        app.route('/stop_me', callback=self.http.stop_me)
        app.route('/resume_me', callback=self.http.resume_me)
        app.route('/status', callback=self.http.status)
        app.route('/status/json', callback=self.http.statusjson)

        #debug('host: ' + s.remote_host)
        #debug('port: ' + s.remote_port)
        self.server = BottleServer(host=s.remote_host, port=s.remote_port)
        try:
            app.run(server=self.server)
        except Exception as e:
            print_tb(e)
        debug('Server stopped')
        self.server = None

    def stop(self):
        if self.http.engines:
            for eng in self.http.engines:
                eng.wait_on_close(1)
                eng.close()
        if self.server:
            self.server.stop()
            while self.server:
                xbmc.sleep(300)


# BOTTLE WEB SERVER

class QuietHandler(WSGIRequestHandler):
    def log_request(*args, **kwargs):
        pass


class BottleServer(ServerAdapter):
    server = None

    def run(self, handler):
        if self.quiet:
            self.options['handler_class'] = QuietHandler
        self.server = make_server(self.host, self.port, handler, **self.options)
        self.server.serve_forever()

    def stop(self):
        self.server.shutdown()
