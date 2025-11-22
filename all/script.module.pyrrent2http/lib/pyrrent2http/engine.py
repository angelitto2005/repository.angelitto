# -*- coding: utf-8 -*-
import os
import sys
import time
import pyrrent2http
import xbmc
from error import Error
from . import SessionStatus, FileStatus, PeerInfo, Encryption
from util import can_bind, find_free_port, localize_path, uri2path, detect_media_type
import threading
import urllib
import chardet

LOGGING = True

class Engine:
    """
    This is python binding class to pyrrent2http client.
    """
    def _log(self, message):
        if self.logger:
            self.logger(message)
        else:
            xbmc.log("[pyrrent2http] %s" % message)


    def __init__(self, uri=None, platform=None, download_path=".",
                 bind_host='127.0.0.1', bind_port=5001, connections_limit=None, download_kbps=None, upload_kbps=None,
                 enable_dht=True, enable_lsd=True, enable_natpmp=True, enable_upnp=True, enable_scrape=False,
                 log_stats=False, encryption=Encryption.ENABLED, keep_complete=False, keep_incomplete=False,
                 keep_files=False, log_files_progress=False, log_overall_progress=False, log_pieces_progress=False,
                 listen_port=6881, use_random_port=False, max_idle_timeout=None, no_sparse=False, resume_file='',
                 user_agent=None, startup_timeout=5, state_file='', enable_utp=True, enable_tcp=True,
                 debug_alerts=False, logger=None, torrent_connect_boost=50, connection_speed=50,
                 peer_connect_timeout=15, request_timeout=20, min_reconnect_time=60, max_failcount=3,
                 dht_routers=None, trackers=None):
        """
        Creates engine instance. It doesn't do anything except initializing object members. For starting engine use
        start() method.

        :param uri: Torrent URI (magnet://, file:// or http://)
        :param binaries_path: Path to torrent2http binaries
        :param platform: Object with two methods implemented: arch() and system()
        :param download_path: Torrent download path
        :param bind_host: Bind host of torrent2http
        :param bind_port: Bind port of torrent2http
        :param connections_limit: Set a global limit on the number of connections opened
        :param download_kbps: Max download rate (kB/s)
        :param upload_kbps: Max upload rate (kB/s)
        :param enable_dht: Enable DHT (Distributed Hash Table)
        :param enable_lsd: Enable LSD (Local Service Discovery)
        :param enable_natpmp: Enable NATPMP (NAT port-mapping)
        :param enable_upnp: Enable UPnP (UPnP port-mapping)
        :param enable_scrape: Enable sending scrape request to tracker (updates total peers/seeds count)
        :param log_stats: Log all stats (incl. log_overall_progress, log_files_progress, log_pieces_progress)
        :param encryption: Encryption: 0=forced 1=enabled (default) 2=disabled
        :param keep_complete: Keep complete files after exiting
        :param keep_incomplete: Keep incomplete files after exiting
        :param keep_files: Keep all files after exiting (incl. keep_complete and keep_incomplete)
        :param log_files_progress: Log files progress
        :param log_overall_progress: Log overall progress
        :param log_pieces_progress: Log pieces progress
        :param listen_port: Use specified port for incoming connections
        :param use_random_port: Use random listen port (49152-65535)
        :param max_idle_timeout: Automatically shutdown torrent2http if no connection are active after a timeout
        :param no_sparse: Do not use sparse file allocation
        :param resume_file: Use fast resume file
        :param user_agent: Set an user agent
        :param startup_timeout: torrent2http startup timeout
        :param state_file: Use file for saving/restoring session state
        :param enable_utp: Enable uTP protocol
        :param enable_tcp: Enable TCP protocol
        :param debug_alerts: Show debug alert notifications
        :param logger: Instance of logging.Logger
        :param torrent_connect_boost: The number of peers to try to connect to immediately when the first tracker
            response is received for a torrent
        :param connection_speed: The number of peer connection attempts that are made per second
        :param peer_connect_timeout: The number of seconds to wait after a connection attempt is initiated to a peer
        :param request_timeout: The number of seconds until the current front piece request will time out
        :param min_reconnect_time: The time to wait between peer connection attempts. If the peer fails, the time is
            multiplied by fail counter
        :param max_failcount: The maximum times we try to connect to a peer before stop connecting again
        :param dht_routers: List of additional DHT routers (host:port pairs)
        :param trackers: List of additional tracker URLs
        """
        self.dht_routers = dht_routers or []
        self.trackers = trackers or []
        self.max_failcount = max_failcount
        self.min_reconnect_time = min_reconnect_time
        self.request_timeout = request_timeout
        self.peer_connect_timeout = peer_connect_timeout
        self.connection_speed = connection_speed
        self.torrent_connect_boost = torrent_connect_boost
        self.platform = platform
        self.bind_host = bind_host
        self.bind_port = bind_port
        self.download_path = download_path
        self.connections_limit = connections_limit
        self.download_kbps = download_kbps
        self.upload_kbps = upload_kbps
        self.enable_dht = enable_dht
        self.enable_lsd = enable_lsd
        self.enable_natpmp = enable_natpmp
        self.enable_upnp = enable_upnp
        self.enable_scrape = enable_scrape
        self.log_stats = log_stats
        self.encryption = encryption
        self.keep_complete = keep_complete
        self.keep_incomplete = keep_incomplete
        self.keep_files = keep_files
        self.log_files_progress = log_files_progress
        self.log_overall_progress = log_overall_progress
        self.log_pieces_progress = log_pieces_progress
        self.listen_port = listen_port
        self.use_random_port = use_random_port
        self.max_idle_timeout = max_idle_timeout
        self.no_sparse = no_sparse
        self.resume_file = resume_file
        self.user_agent = user_agent
        self.startup_timeout = startup_timeout
        self.state_file = state_file
        self.wait_on_close_timeout = None
        self.enable_utp = enable_utp
        self.enable_tcp = enable_tcp
        self.debug_alerts = debug_alerts
        self.logger = logger
        self.uri = uri
        self.started = False

    @staticmethod
    def _validate_save_path(path):
        """
        Ensures download path can be accessed locally.

        :param path: Download path
        :return: Translated path
        """
        import xbmc
        path = xbmc.translatePath(path)
        if "://" in path:
            if sys.platform.startswith('win') and path.lower().startswith("smb://"):
                path = path.replace("smb:", "").replace("/", "\\")
            else:
                raise Error("Downloading to an unmounted network share is not supported", Error.INVALID_DOWNLOAD_PATH)
        if not os.path.isdir(localize_path(path)):
            raise Error("Download path doesn't exist (%s)" % path, Error.INVALID_DOWNLOAD_PATH)
        return localize_path(path)

    def start(self, start_index=None):
        """
        Starts pyrrent2http client with specified settings. If it can be started in startup_timeout seconds, exception
        will be raised.

        :param start_index: File index to start download instantly, if not specified, downloading will be paused, until
            any file requested
        """

        download_path = self._validate_save_path(self.download_path)
        if not can_bind(self.bind_host, self.bind_port):
            port = find_free_port(self.bind_host)
            if port is False:
                raise Error("Can't find port to bind pyrrent2http", Error.BIND_ERROR)
            self._log("Can't bind to %s:%s, so we found another port: %d" % (self.bind_host, self.bind_port, port))
            self.bind_port = port

        kwargs = {
            'torrentConnectBoost': self.torrent_connect_boost,
            'trackers': ",".join(self.trackers),
            'resumeFile': self.resume_file,
            'minReconnectTime': self.min_reconnect_time,
            'enableUPNP': self.enable_upnp,
            'showAllStats': self.log_stats,
            'debugAlerts': self.debug_alerts,
            'keepComplete': self.keep_complete,
            'dhtRouters': ",".join(self.dht_routers),
            'userAgent': self.user_agent,
            'enableLSD': self.enable_lsd,
            'uri': self.uri,
            'randomPort': self.use_random_port,
            'noSparseFile': self.no_sparse,
            'maxUploadRate': self.upload_kbps,
            'downloadPath': download_path,
            'showOverallProgress': self.log_overall_progress,
            'enableDHT': self.enable_dht,
            'showFilesProgress': self.log_files_progress,
            'requestTimeout': self.request_timeout,
            'bindAddress': "%s:%s" % (self.bind_host, self.bind_port),
            'maxDownloadRate': self.download_kbps,
            'connectionSpeed': self.connection_speed,
            'keepIncomplete': self.keep_incomplete,
            'enableTCP': self.enable_tcp,
            'listenPort': self.listen_port,
            'keepFiles': self.keep_files,
            'stateFile': self.state_file,
            'peerConnectTimeout': self.peer_connect_timeout,
            'maxFailCount': self.max_failcount,
            'showPiecesProgress': self.log_pieces_progress,
            'idleTimeout': self.max_idle_timeout,
            #'fileIndex': start_index,
            'connectionsLimit': self.connections_limit,
            'enableScrape': self.enable_scrape,
            'enableUTP': self.enable_utp,
            'encryption': self.encryption,
            'enableNATPMP': self.enable_natpmp

        }

        self._log("Invoking pyrrent2http")
        class Logging(object):
            def __init__(self, _log):
                self._log = _log
            def info(self, message):
                if LOGGING:
                    self._log('INFO: %s' % (message,))
            def error(self, message):
                if LOGGING:
                    self._log('ERROR: %s' % (message,))
        pyrrent2http.logging = Logging(self._log)
        
        self.pyrrent2http = pyrrent2http.Pyrrent2http(**kwargs)
        self.pyrrent2http.startSession()
        self.pyrrent2http.startServices()
        self.pyrrent2http.addTorrent()
        self.pyrrent2http.startHTTP()
        self.pyrrent2http_loop = threading.Thread(target = self.pyrrent2http.loop)
        self.pyrrent2http_loop.start()
        

        start = time.time()
        self.started = True
        initialized = False
        while (time.time() - start) < self.startup_timeout:
            time.sleep(0.1)
            if not self.is_alive():
                raise Error("Can't start pyrrent2http, see log for details", Error.PROCESS_ERROR)
            try:
                #self.status(1)
                initialized = True
                break
            except Error:
                pass

        if not initialized:
            self.started = False
            raise Error("Can't start pyrrent2http, time is out", Error.TIMEOUT)
        self._log("pyrrent2http successfully started.")

    def activate_file(self, index):
        self.pyrrent2http.TorrentFS.file(index)
    
    def pause(self):
        self.pyrrent2http.pause = True
    def resume(self):
        self.pyrrent2http.pause = False

    def check_torrent_error(self, status=None):
        """
        It is recommended to call this method periodically to check if any libtorrent errors occurred.
        Usually libtorrent sets error if it can't download or parse torrent file by specified URI.
        Note that pyrrent2http remains started after such error, so you need to shutdown it manually.

        :param status: Pass return of status() method if you don't want status() called twice
        """
        if not status:
            status = self.status()
        if status.error:
            raise Error("Torrent error: %s" % status.error, Error.TORRENT_ERROR, reason=status.error)

    def status(self, timeout=10):
        """
        Returns libtorrent session status. See SessionStatus named tuple.

        :rtype : SessionStatus
        :param timeout: pyrrent2http client request timeout
        """
        status = self.pyrrent2http.Status()
        status = SessionStatus(**status)
        return status

    

    def list(self, media_types=None, timeout=10):
        """
        Returns list of files in the torrent (see FileStatus named tuple).
        Note that it will return None if torrent file is not loaded yet by pyrrent2http client, so you may need to call
        this method periodically until results are returned.

        :param media_types: List of media types (see MediaType constants)
        :param timeout: pyrrent2http client request timeout
        :rtype : list of FileStatus
        :return: List of files of specified media types or None if torrent is not loaded yet
        """
        files = self.pyrrent2http.Ls()['files']
        if files:
            res = [FileStatus(index=index, **f) for index, f in enumerate(files)]
            if media_types is not None:
                res = filter(lambda fs: fs.media_type in media_types, res)
            return res
    def list_from_info(self, media_types=None):
        try:
            info = pyrrent2http.lt.torrent_info(uri2path(self.uri))
        except:
            return []
        files = []
        for i in range(info.num_files()):
            f = info.file_at(i)
            Url = 'http://' + "%s:%s" % (self.bind_host, self.bind_port) + '/files/' + urllib.quote(f.path)
            files.append({
                     'name':    localize_path(f.path),
                     'size':    f.size,
                     'offset':  f.offset,
                     'media_type': media_types and detect_media_type(f.path.decode(chardet.detect(f.path)['encoding'])) or '',
                     'download':   0,
                     'progress':   0.0,
                     'save_path':  '',
                     'url':        Url
                     })
        if files:
            res = [FileStatus(index=index, **f) for index, f in enumerate(files)]
        if media_types is not None:
                res = filter(lambda fs: fs.media_type in media_types, res)
        return res

    def file_status(self, file_index, timeout=10):
        """
        Returns file in the torrent with specified index (see FileStatus named tuple)
        Note that it will return None if torrent file is not loaded yet by pyrrent2http client, so you may need to call
        this method periodically until results are returned.

        :param file_index: Requested file's index
        :param timeout: pyrrent2http client request timeout
        :return: File with specified index
        :rtype: FileStatus
        """
        filestatus = self.pyrrent2http.Ls(file_index)
        try:
            return FileStatus(**filestatus)
        except:
            raise Error("Requested file index (%d) is invalid" % (file_index,), Error.INVALID_FILE_INDEX,
                            file_index=file_index)

    def peers(self, timeout=10):
        """
        Returns list of peers connected (see PeerInfo named tuple).

        :param timeout: pyrrent2http client request timeout
        :return: List of peers
        :rtype: list of PeerInfo
        """
        peers = self.pyrrent2http.Peers()['peers']
        if peers:
            return [PeerInfo(**p) for p in peers]

    def is_alive(self):
        return self.pyrrent2http_loop.is_alive()
    def wait_on_close(self, wait_timeout=10):
        """
        By default, close() method sends shutdown command to pyrrent2http, stops logging and returns immediately, not
        waiting while pyrrent2http exits. It can be handy to wait pyrrent2http to view log messages during shutdown.
        So call this method with reasonable timeout before calling close().

        :param wait_timeout: Time in seconds to wait until pyrrent2http client shut down
        """
        self.wait_on_close_timeout = wait_timeout

    def close(self):
        """
        Shuts down pyrrent2http and stops logging. If wait_on_close() was called earlier, it will wait until
        pyrrent2http successfully exits.
        """
        if self.is_alive():
            self._log("Shutting down pyrrent2http...")
            self.pyrrent2http.shutdown()
            finished = False
            if self.wait_on_close_timeout is not None:
                start = time.time()
                while (time.time() - start) < self.wait_on_close_timeout:
                    time.sleep(0.5)
                    if not self.is_alive():
                        finished = True
                        break
                if not finished:
                    self._log("PANIC: Timeout occurred while shutting down pyrrent2http thread")
                else:
                    self._log("pyrrent2http successfully shut down.")
                self.wait_on_close_timeout = None
            self._log("pyrrent2http successfully shut down.")
        self.started = False
        self.logpipe = None
        self.process = None
