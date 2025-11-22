#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import chardet

try:
    from python_libtorrent import get_libtorrent
    lt=get_libtorrent()
    print('Imported libtorrent v%s from python_libtorrent' %(lt.version, ))
except Exception, e:
    print('Error importing python_libtorrent.Exception: %s' %(str(e),))
    try:
        import libtorrent as lt
    except Exception as e:
        strerror = e.args
        print(strerror)
        raise

from random import SystemRandom
import time
import urllib
import BaseHTTPServer
import SocketServer
import threading
import io
from util import localize_path, Struct, detect_media_type, uri2path, encode_msg



if os.getenv('ANDROID_ROOT'):
    from ctypes import *
    libc = CDLL('/system/lib/libc.so')
    libc.lseek64.restype = c_ulonglong
    libc.lseek64.argtypes = [c_uint, c_ulonglong, c_uint]
    libc.read.restype = c_long
    libc.read.argtypes = [c_uint, c_void_p, c_long]
    O_RDONLY = 0
    O_LARGEFILE = 0x8000

######################################################################################

if not hasattr(os, 'getppid'):
    import ctypes

    TH32CS_SNAPPROCESS = 0x02L
    CreateToolhelp32Snapshot = ctypes.windll.kernel32.CreateToolhelp32Snapshot
    GetCurrentProcessId = ctypes.windll.kernel32.GetCurrentProcessId

    MAX_PATH = 260

    _kernel32dll = ctypes.windll.Kernel32
    CloseHandle = _kernel32dll.CloseHandle

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.c_ulong),
            ("cntUsage", ctypes.c_ulong),
            ("th32ProcessID", ctypes.c_ulong),
            ("th32DefaultHeapID", ctypes.c_int),
            ("th32ModuleID", ctypes.c_ulong),
            ("cntThreads", ctypes.c_ulong),
            ("th32ParentProcessID", ctypes.c_ulong),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", ctypes.c_ulong),

            ("szExeFile", ctypes.c_wchar * MAX_PATH)
        ]

    Process32First = _kernel32dll.Process32FirstW
    Process32Next = _kernel32dll.Process32NextW

    def getppid():
        '''
        :return: The pid of the parent of this process.
        '''
        pe = PROCESSENTRY32()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
        mypid = GetCurrentProcessId()
        snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)

        result = 0
        try:
            have_record = Process32First(snapshot, ctypes.byref(pe))

            while have_record:
                if mypid == pe.th32ProcessID:
                    result = pe.th32ParentProcessID
                    break

                have_record = Process32Next(snapshot, ctypes.byref(pe))

        finally:
            CloseHandle(snapshot)

        return result

    os.getppid = getppid

#################################################################################

AVOID_HTTP_SERVER_EXCEPTION_OUTPUT = True
VERSION = "0.6.0"
#USER_AGENT = "pyrrent2http/" + VERSION + " libtorrent/" + lt.version
USER_AGENT = 'libtorrent/1.0.9.0'

VIDEO_EXTS={'.avi':'video/x-msvideo','.mp4':'video/mp4','.mkv':'video/x-matroska',
'.m4v':'video/mp4','.mov':'video/quicktime', '.mpg':'video/mpeg','.ogv':'video/ogg',
'.ogg':'video/ogg', '.webm':'video/webm', '.ts': 'video/mp2t', '.3gp':'video/3gpp'}
######################################################################################

class Ticker(object):
    def __init__(self, interval):
        self.tick = False
        self._timer     = None
        self.interval   = interval
        self.is_running = False
        self.start()
    @property
    def true(self):
        if self.tick:
            self.tick = False
            return True
        else:
            return False

    def _run(self):
        self.is_running = False
        self.start()
        self.tick = True

    def start(self):
        if not self.is_running:
            self._timer = threading.Timer(self.interval, self._run)
            self._timer.start()
            self.is_running = True

    def stop(self):
        self._timer.cancel()
        self.is_running = False

#######################################################################################

class TorrentFile(object):
    tfs         =   None
    closed      =   True
    save_path    =   str()
    fileEntry   =   None
    index       =   0
    filePtr     =   None
    downloaded  =   0
    progress    =   0.0
    pdl_thread  =   None
    def __init__(self, tfs, fileEntry, savePath, index):
        self.tfs = tfs
        self.fileEntry = fileEntry
        self.name = self.fileEntry.path
        self.unicode_name = self.name.decode(chardet.detect(self.name)['encoding'])
        self.media_type = detect_media_type(self.unicode_name)
        self.save_path = savePath
        self.index = index
        self.piece_length = int(self.tfs.info.piece_length())
        self.size = self.fileEntry.size
        self.offset = self.fileEntry.offset
        self.startPiece, self.endPiece = self.Pieces()
        self.pieces_deadlined = [False] * (self.endPiece - self.startPiece)
        
    def Downloaded(self):
        return self.downloaded
    def Progress(self):
        return self.progress
    def __fileptr_(self):
        if self.closed:
            return None
        if self.filePtr is None:
            while not os.path.exists(self.save_path):
                logging.info('Waiting for file: %s' % (self.save_path,))
                self.tfs.handle.flush_cache()
                time.sleep(0.5)
            if os.getenv('ANDROID_ROOT'):
                self.filePtr = libc.open(self.save_path, O_RDONLY | O_LARGEFILE, 755)
            else:
                self.filePtr = io.open(self.save_path, 'rb')
        return self.filePtr
    def log(self, message):
        fnum = self.tfs.openedFiles.index(self)
        logging.info("[Thread No.%d] %s\n" % (fnum, message))
    def Pieces(self):
        startPiece, _ = self.pieceFromOffset(1)
        endPiece, _ = self.pieceFromOffset(self.size - 1)
        return startPiece, endPiece
    def SetPriority(self, priority):
        self.tfs.setPriority(self.index, priority)
    def readOffset(self):
        if os.getenv('ANDROID_ROOT'):
            return libc.lseek64(self.filePtr, 0, os.SEEK_CUR)
        else:
            return self.filePtr.seek(0, os.SEEK_CUR)
    def havePiece(self, piece):
        return self.tfs.handle.have_piece(piece)
    def pieceFromOffset(self, offset):
        piece = int((self.offset + offset) / self.piece_length)
        pieceOffset = int((self.offset + offset) % self.piece_length)
        return piece, pieceOffset
    def waitForPiece(self, piece):
        def set_deadlines(p):
            next_piece = p + 1
            BUF_SIZE = 2   # Лучшее враг хорошего
            for i in range(BUF_SIZE):
                if (next_piece + i < self.endPiece and 
                    not self.pieces_deadlined[(next_piece + i) - self.startPiece] and not self.havePiece(next_piece + i)):
                    self.tfs.handle.set_piece_deadline(next_piece + i, 70 + (20 * i))
                    self.pieces_deadlined[(next_piece + i) - self.startPiece] = True
        if not self.havePiece(piece):
            self.log('Waiting for piece %d' % (piece,))
            self.tfs.handle.set_piece_deadline(piece, 50)
        while not self.havePiece(piece):
            if self.tfs.handle.piece_priority(piece) == 0 or self.closed:
                return False
            time.sleep(0.1)
        if not isinstance(self.pdl_thread, threading.Thread) or not self.pdl_thread.is_alive():
            self.pdl_thread = threading.Thread(target = set_deadlines, args = (piece,))
            self.pdl_thread.start()
        return True
    def Close(self):
        if self.closed: return
        self.log('Closing %s...' % (self.name,))
        self.tfs.removeOpenedFile(self)
        self.closed = True
        if self.filePtr is not None:
            if os.getenv('ANDROID_ROOT'):
                libc.close(self.filePtr)
            else:
                self.filePtr.close()
            self.filePtr = None
    def ShowPieces(self):
        pieces = self.tfs.handle.status().pieces
        str_ = ''
        for i in range(self.startPiece, self.endPiece + 1):
            if pieces[i] == False:
                str_ += "-"
            else:
                str_ += "#"
        self.log(str_)
    def Read(self, buf):
        filePtr = self.__fileptr_()
        if filePtr is None:
            raise IOError
        toRead = len(buf)
        if toRead > self.piece_length:
            toRead = self.piece_length
        readOffset = self.readOffset()
        startPiece, _ = self.pieceFromOffset(readOffset)
        endPiece, _ = self.pieceFromOffset(readOffset + toRead)
        for i in range(startPiece,  endPiece + 1):
            if not self.waitForPiece(i):
                raise IOError
        if os.getenv('ANDROID_ROOT'):
            read = libc.read(self.filePtr, addressof(buf), toRead)
        else:
            read = filePtr.readinto(buf)
        return read
    def Seek(self, offset, whence):
        filePtr = self.__fileptr_()
        if filePtr is None: return
        if whence == os.SEEK_END:
            offset = self.size - offset
            whence = os.SEEK_SET
        if os.getenv('ANDROID_ROOT'):
            newOffset = libc.lseek64(self.filePtr, offset, whence)
        else:
            newOffset = filePtr.seek(offset, whence)
        self.log('Seeking to %d/%d' % (newOffset, self.size))
        return newOffset
    def IsComplete(self):
        return self.downloaded == self.size

#######################################################################################

class TorrentFS(object):
    handle      =       None
    info        =       None
    priorities  =       list()
    openedFiles =       list()
    lastOpenedFile =    None
    shuttingDown   =    False
    fileCounter =       int()
    progresses  =       list()
    save_path   =       None

    def __init__(self, root, handle):
        self.root = root
        self.handle = handle
        self.waitForMetadata()
        self.save_path = localize_path(self.root.torrentParams['save_path'])
        self.priorities = list(self.handle.file_priorities())
        self.files = {}
        num_files = self.info.num_files()
        for i in range(num_files):
            self.setPriority(i, 0)
    def file(self, index):
        for name in self.files.keys():
            if self.files[name].index == index:
                return self.files[name]
        file_ = self.__file_at_(index)
        self.files[file_.name] = file_
        #self.handle.set_piece_deadline(self.files[startIndex].startPiece, 50)
        self.setPriority(index, 1)
        return file_

    def Shutdown(self):
        self.shuttingDown = True
        if len(self.openedFiles) > 0:
            logging.info('Closing %d opened file(s)' % (len(self.openedFiles),))
            for f in self.openedFiles:
                f.Close()
    def addOpenedFile(self, file_):
        self.openedFiles.append(file_)    
    def setPriority(self, index, priority):
        if self.priorities[index] != priority:
            logging.info('Setting %s priority to %d' % (self.info.file_at(index).path, priority))
            self.priorities[index] = priority
            self.handle.file_priority(index, priority)
    def findOpenedFile(self, file):
        for i, f in enumerate(self.openedFiles):
            if f == file:
                return i
        return -1
    def removeOpenedFile(self, file):
        pos = self.findOpenedFile(file)
        if pos >= 0:
            del self.openedFiles[pos]
    def waitForMetadata(self):
        if not self.handle.status().has_metadata:
            time.sleep(0.1)
        try:
            self.info = self.handle.torrent_file()
        except:
            self.info = self.handle.get_torrent_info()
    def HasTorrentInfo(self):
        return self.info is not None
    def LoadFileProgress(self):
        self.progresses = self.handle.file_progress()
        for k in self.files.keys():
            self.files[k].downloaded = self.getFileDownloadedBytes(self.files[k].index)
            if self.files[k].size > 0: self.files[k].progress = float(self.files[k].downloaded) / float(self.files[k].size)
    def getFileDownloadedBytes(self, i):
        try:
            bytes_ = self.progresses[i]
        except IndexError:
            bytes_ = 0
        return bytes_
    def __files_(self):
        info = self.info
        files_ = []
        for i in range(info.num_files()):
            file_ = self.__file_at_(i)
            file_.downloaded = self.getFileDownloadedBytes(i)
            if file_.size > 0:
                file_.progress = float(file_.downloaded)/float(file_.size)
            files_.append(file_)
        return files_
    def __file_at_(self, index):
        info = self.info
        fileEntry = info.file_at(index)
        fe_path = fileEntry.path
        path = os.path.abspath(os.path.join(self.save_path, localize_path(fe_path)))
        return TorrentFile(
                           self,
                           fileEntry,
                           path,
                           index
                           )
    def FileByName(self, name):
        for i, f in enumerate(self.info.files()):
            if f.path == name:
                return self.__file_at_(i)
        raise IOError
    def Open(self, name):
        if self.shuttingDown or not self.HasTorrentInfo():
            raise IOError
        return self.OpenFile(name)
    def checkPriorities(self):
        for index, priority in enumerate(self.priorities):
            if priority == 0:
                continue
            found = False
            for f in self.openedFiles:
                if f.index == index:
                    found = True
                    break
            if not found:
                self.setPriority(index, 0)
    def OpenFile(self, name):
        try:
            tf = self.FileByName(name)
        except IOError:
            return
        tf.closed = False
        self.fileCounter += 1
        tf.num = self.fileCounter
        self.addOpenedFile(tf)
        tf.log('Opened %s...' % (tf.name,))
        tf.SetPriority(1)
        self.handle.set_piece_deadline(tf.startPiece, 50)
        self.lastOpenedFile = tf
        self.files[tf.name] = tf
        self.checkPriorities()
        return tf
        
#############################################################

class ThreadingHTTPServer(SocketServer.ThreadingMixIn, BaseHTTPServer.HTTPServer):
    def handle_error(self, *args, **kwargs):
        '''Обходим злосчастный "Broken Pipe" и прочие трейсы'''
        if not AVOID_HTTP_SERVER_EXCEPTION_OUTPUT:
            BaseHTTPServer.HTTPServer.handle_error(self, *args, **kwargs)

def HttpHandlerFactory():
    class HttpHandler(BaseHTTPServer.BaseHTTPRequestHandler):
        def do_GET(self):
            #print ('---Headers---\n%s\n' % (self.headers,))
            #print ('---Request---\n%s\n' % (self.path,))
            if self.path.startswith('/files/'):
                self.filesHandler()
            else:
                self.send_error(404, 'Not found')
                self.end_headers()
        def filesHandler(self):
            f, start_range, end_range = self.send_head()
            if not f.closed:
                f.Seek(start_range, 0)
                chunk = f.piece_length
                total = 0
                if os.getenv('ANDROID_ROOT'):
                    buf = create_string_buffer(chunk)
                else:
                    buf = bytearray(chunk)
                while chunk > 0:
                    if start_range + chunk > end_range:
                        chunk = end_range - start_range
                        if os.getenv('ANDROID_ROOT'):
                            buf = create_string_buffer(chunk)
                        else:
                            buf = bytearray(chunk)
                    try:
                        if f.Read(buf) < 1: break
                        while self.server.root_obj.pause:
                            time.sleep(0.1)
                            continue
                        if os.getenv('ANDROID_ROOT'):
                            self.wfile.write(buf.raw)
                        else:
                            self.wfile.write(buf)
                    except:
                        break
                    total += chunk
                    start_range += chunk
                f.Close()
        def send_head(self):
            fname = urllib.unquote(self.path.lstrip('/files/'))
            try:
                f =  self.server.root_obj.TorrentFS.Open(fname)
            except IOError:
                self.send_error(404, "File not found")
                return (None, 0, 0)
            _, ext = os.path.splitext(fname)
            ctype = (ext != '' and ext in VIDEO_EXTS.keys())and VIDEO_EXTS[ext] or 'application/octet-stream'
            if "Range" in self.headers:
                self.send_response(206, 'Partial Content')
            else:
                self.send_response(200)
            self.send_header("Content-type", ctype)
            self.send_header('transferMode.dlna.org', 'Streaming')
            size = f.size
            start_range = 0
            end_range = size
            self.send_header("Accept-Ranges", "bytes")
            if "Range" in self.headers:
                s, e = self.headers['range'][6:].split('-', 1)
                sl = len(s)
                el = len(e)
                if sl > 0:
                    start_range = int(s)
                    if el > 0:
                        end_range = int(e) + 1
                elif el > 0:
                    ei = int(e)
                    if ei < size:
                        start_range = size - ei
            self.send_header("Content-Range", 'bytes ' + str(start_range) + '-' + str(end_range - 1) + '/' + str(size))
            self.send_header("Content-Length", end_range - start_range)
            self.send_header("Last-Modified", self.date_time_string(f.fileEntry.mtime))
            self.end_headers()
            #print "Sending Bytes ",start_range, " to ", end_range, "...\n"
            return (f, start_range, end_range)
        # Вырубаем access-log
        def log_message(self, format, *args):
            return
    return HttpHandler

class Pyrrent2http(object):
    pause = False
    def __init__(self, uri = '', bindAddress = 'localhost:5001', downloadPath = '.',
                    idleTimeout = -1, keepComplete = False, 
                    keepIncomplete = False, keepFiles = False, showAllStats = False, 
                    showOverallProgress = False, showFilesProgress = False, 
                    showPiecesProgress = False, debugAlerts = False,
                    exitOnFinish = False, resumeFile = '', stateFile = '',
                    userAgent = USER_AGENT, dhtRouters = '', trackers = '',
                    listenPort = 6881, torrentConnectBoost = 50, connectionSpeed = 50,
                    peerConnectTimeout = 15, requestTimeout = 20, maxDownloadRate = -1,
                    maxUploadRate = -1, connectionsLimit = 200, encryption = 1,
                    minReconnectTime = 60, maxFailCount = 3, noSparseFile = False,
                    randomPort = False, enableScrape = False, enableDHT = True,
                    enableLSD = True, enableUPNP = True, enableNATPMP = True, enableUTP = True, enableTCP = True):
        self.torrentHandle = None
        self.forceShutdown = False
        self.session = None
        self.magnet = False

        self.config = Struct()
        self.config.uri = uri
        self.config.bindAddress = bindAddress
        self.config.downloadPath = downloadPath
        self.config.idleTimeout = idleTimeout
        #self.config.fileIndex = fileIndex
        self.config.keepComplete = keepComplete
        self.config.keepIncomplete = keepIncomplete
        self.config.keepFiles = keepFiles
        self.config.showAllStats = showAllStats
        self.config.showOverallProgress = showOverallProgress
        self.config.showFilesProgress = showFilesProgress
        self.config.showPiecesProgress = showPiecesProgress
        self.config.debugAlerts = debugAlerts
        self.config.exitOnFinish = exitOnFinish
        self.config.resumeFile = resumeFile
        self.config.stateFile = stateFile
        self.config.userAgent = userAgent
        self.config.dhtRouters = dhtRouters
        self.config.trackers = trackers
        self.config.listenPort = listenPort
        self.config.torrentConnectBoost = torrentConnectBoost
        self.config.connectionSpeed = connectionSpeed
        self.config.peerConnectTimeout = peerConnectTimeout
        self.config.requestTimeout = requestTimeout
        self.config.maxDownloadRate = maxDownloadRate
        self.config.maxUploadRate = maxUploadRate
        self.config.connectionsLimit = connectionsLimit
        self.config.encryption = encryption
        self.config.minReconnectTime = minReconnectTime
        self.config.maxFailCount = maxFailCount
        self.config.noSparseFile = noSparseFile
        self.config.randomPort = randomPort
        self.config.enableScrape = enableScrape
        self.config.enableDHT = enableDHT
        self.config.enableLSD = enableLSD
        self.config.enableUPNP = enableUPNP
        self.config.enableNATPMP = enableNATPMP
        self.config.enableUTP = enableUTP
        self.config.enableTCP = enableTCP
        if self.config.uri == '':
            raise Exception("uri is empty string")
        if self.config.uri.startswith('magnet:'):
            self.magnet = True
        if self.config.resumeFile is None: self.config.resumeFile = ''
        if self.config.resumeFile != '' and not self.config.keepFiles:
            raise Exception('Не должно быть файла восстановления, если мы не храним файлы')
        
    def buildTorrentParams(self, uri):
        try:
            absPath = uri2path(uri)
            logging.info('Opening local torrent file: %s' % (encode_msg(absPath),))
            torrent_info = lt.torrent_info(lt.bdecode(open(absPath, 'rb').read()))
        except Exception as e:
            strerror = e.args
            logging.error('Build torrent params error is (%s)' % (strerror,))
            raise
        torrentParams = {}
        torrentParams['ti'] = torrent_info
        logging.info('Setting save path: %s' % (encode_msg(self.config.downloadPath),))
        torrentParams['save_path'] = self.config.downloadPath
        
        if os.path.exists(self.config.resumeFile):
            logging.info('Loading resume file: %s' % (encode_msg(self.config.resumeFile),))
            try:
                with open(self.config.resumeFile, 'rb') as f:
                    torrentParams["auto_managed"] = True
                    torrentParams['resume_data'] = f.read()
            except Exception as e:
                strerror = e.args
                logging.error(strerror)
        if self.config.noSparseFile or self.magnet:
            logging.info('Disabling sparse file support...')
            torrentParams["storage_mode"] = lt.storage_mode_t.storage_mode_allocate
        return torrentParams
    
    def addTorrent(self):
        self.torrentParams = self.buildTorrentParams(self.config.uri)
        logging.info('Adding torrent')
        self.torrentHandle = self.session.add_torrent(self.torrentParams)
        self.torrentHandle.set_sequential_download(False)
        #
        # Хороший флаг, но не в нашем случае. Мы сами указываем, какие куски нам нужны (handle.set_piece_deadline)
        # Также, у нас перемотка. Т.е. произвольный доступ.
        # Значит, последовательная загрузка нам будет только вредить
        #
        self.torrentHandle.set_max_connections(60)
        if self.config.trackers != '':
            trackers    = self.config.trackers.split(',')
            startTier   = 256 - len(trackers)
            for n in range(len(trackers)):
                tracker = trackers[n].strip()
                logging.info('Adding tracker: %s' % (tracker,) )
                self.torrentHandle.add_tracker(tracker, startTier + n)
        if self.config.enableScrape:
            logging.info('Sending scrape request to tracker')
            self.torrentHandle.scrape_tracker()
        try:
            info = self.torrentHandle.torrent_file()
        except:
            info = self.torrentHandle.get_torrent_info()
        logging.info('Downloading torrent: %s' % (info.name(),))
        try:
            self.TorrentFS = TorrentFS(self, self.torrentHandle)
        except Exception as e:
            logging.error(e.args)
        #_ = self.TorrentFS.file(self.config.fileIndex)
        name = self.TorrentFS.info.name()
        self.torrent_name = name.decode(chardet.detect(name)['encoding'])
    
    def startHTTP(self):
        #def http_server_loop(listener, alive):
        #    while alive.is_set():
        #        print('+++handle request+++')
        #        listener.handle_request()
        #    listener.server_close()
        #self.main_alive = threading.Event()
        #self.main_alive.set()
        logging.info('Starting HTTP Server...')
        handler = HttpHandlerFactory()
        logging.info('Listening HTTP on %s...\n' % (self.config.bindAddress,))
        host, strport = self.config.bindAddress.split(':')
        if len(strport) > 0:
            srv_port = int(strport)
        self.httpListener = ThreadingHTTPServer((host, srv_port), handler)
        self.httpListener.root_obj = self
        #self.httpListener.timeout = 0.5
        #thread = threading.Thread(target = http_server_loop, args = (self.httpListener, self.main_alive))
        thread = threading.Thread(target = self.httpListener.serve_forever)
        thread.start()
    
    def startServices(self):
        if self.config.enableDHT:
            logging.info('Starting DHT...')
            self.session.start_dht()
        if self.config.enableLSD:
            logging.info('Starting LSD...')
            self.session.start_lsd()
        if self.config.enableUPNP:
            logging.info('Starting UPNP...')
            self.session.start_upnp()
        if self.config.enableNATPMP:
            logging.info('Starting NATPMP...')
            self.session.start_natpmp()
    
    def startSession(self):
        logging.info('Starting session...')
        self.session = lt.session(lt.fingerprint('LT', lt.version_major, lt.version_minor, 0, 0),
                             flags=int(lt.session_flags_t.add_default_plugins))
        alertMask = (lt.alert.category_t.error_notification | 
                     lt.alert.category_t.storage_notification | 
                     lt.alert.category_t.tracker_notification |
                     lt.alert.category_t.status_notification)
        if self.config.debugAlerts:
            alertMask |= lt.alert.category_t.debug_notification
        self.session.set_alert_mask(alertMask)
        
        settings = self.session.get_settings()
        settings["request_timeout"] = self.config.requestTimeout
        settings["peer_connect_timeout"] = self.config.peerConnectTimeout
        settings["announce_to_all_trackers"] = True
        settings["announce_to_all_tiers"] = True
        settings["torrent_connect_boost"] = self.config.torrentConnectBoost
        settings["connection_speed"] = self.config.connectionSpeed
        settings["min_reconnect_time"] = self.config.minReconnectTime
        settings["max_failcount"] = self.config.maxFailCount
        settings["recv_socket_buffer_size"] = 1024 * 1024
        settings["send_socket_buffer_size"] = 1024 * 1024
        settings["rate_limit_ip_overhead"] = True
        settings["min_announce_interval"] = 60
        settings["tracker_backoff"] = 0
        self.session.set_settings(settings)
        
        if self.config.stateFile != '':
            logging.info('Loading session state from %s' % (self.config.stateFile,))
            try:
                with open(self.config.stateFile, 'rb') as f:
                    bytes__ = f.read()
            except IOError as e:
                strerror = e.args
                logging.error(strerror)
            else:
                self.session.load_state(lt.bdecode(bytes__))
        
        rand = SystemRandom(time.time())
        portLower = self.config.listenPort
        if self.config.randomPort:
            portLower = rand.randint(0, 16374) + 49151
        portUpper = portLower + 10
        try:
            self.session.listen_on(portLower, portUpper)
        except IOError as e:
            strerror = e.args
            logging.error(strerror)
            raise
        
        settings = self.session.get_settings()
        if self.config.userAgent != '':
            settings['user_agent'] = self.config.userAgent
        if self.config.connectionsLimit >= 0:
            settings['connections_limit'] = self.config.connectionsLimit
        if self.config.maxDownloadRate >= 0:
            settings['download_rate_limit'] = self.config.maxDownloadRate * 1024
        if self.config.maxUploadRate >= 0:
            settings['upload_rate_limit'] = self.config.maxUploadRate * 1024
        settings['enable_incoming_tcp'] = self.config.enableTCP
        settings['enable_outgoing_tcp'] = self.config.enableTCP
        settings['enable_incoming_utp'] = self.config.enableUTP
        settings['enable_outgoing_utp'] = self.config.enableUTP
        self.session.set_settings(settings)
        
        if self.config.dhtRouters != '':
            routers = self.config.dhtRouters.split(',')
            for router in routers:
                router = router.strip()
                if router != '':
                    hostPort = router.split(':')
                    host = hostPort[0].strip()
                    try:
                        port = len(hostPort) > 1 and int(hostPort[1].strip()) or 6881
                    except ValueError as e:
                        strerror = e.args
                        logging.error(strerror)
                        raise
                    self.session.add_dht_router(host, port)
                    logging.info('Added DHT router: %s:%d' % (host, port))
        logging.info('Setting encryption settings')
        try:
            encryptionSettings = lt.pe_settings()
            encryptionSettings.out_enc_policy = lt.enc_policy(self.config.encryption)
            encryptionSettings.in_enc_policy = lt.enc_policy(self.config.encryption)
            encryptionSettings.allowed_enc_level = lt.enc_level.both
            encryptionSettings.prefer_rc4 = True
            self.session.set_pe_settings(encryptionSettings)
        except Exception as e:
            logging.info('Encryption not supported: %s' % (e.args,))
    
    def Status(self):
        info = self.TorrentFS.info
        #tstatus = self.torrentHandle.status()
        #tstatus = self.TorrentFS.handle.status()
        tstatus = self.torrentHandle.status()

        status = {
                     'name'           :   self.torrent_name,
                     'state'          :   int(tstatus.state),
                     'state_str'       :   str(tstatus.state),
                     'error'          :   tstatus.error,
                     'progress'       :   tstatus.progress,
                     'download_rate'   :   tstatus.download_rate / 1024,
                     'upload_rate'     :   tstatus.upload_rate / 1024,
                     'total_download'  :   tstatus.total_download,
                     'total_upload'    :   tstatus.total_upload,
                     'num_peers'       :   tstatus.num_peers,
                     'num_seeds'       :   tstatus.num_seeds,
                     'total_seeds'     :   tstatus.num_complete,
                     'total_peers'     :   tstatus.num_incomplete
                     }
        return status
    def Ls(self, index):
        fi = {}
        if self.TorrentFS.HasTorrentInfo():
            x = [n for n in self.TorrentFS.files.keys() if self.TorrentFS.files[n].index == index]
            name = x[0]
            files = self.TorrentFS.files
            Url = 'http://' + self.config.bindAddress + '/files/' + urllib.quote(name)
            fi = {
                  'index':      files[name].index,
                  'name':       files[name].unicode_name,
                  'media_type': files[name].media_type,
                  'size':       files[name].size,
                  'offset':     files[name].offset,
                  'download':   files[name].downloaded,
                  'progress':   files[name].progress,
                  'save_path':  files[name].save_path,
                  'url':        Url
                  }
        return fi
    def Peers(self):
        peers = {'peers': []}
        for peer in self.torrentHandle.get_peer_info():
            if peer.flags & peer.connecting or peer.flags & peer.handshake:
                continue
            pi = {
                   'Ip':            peer.ip,
                   'Flags':         peer.flags,
                   'Source':        peer.source,
                   'UpSpeed':       peer.up_speed/1024,
                   'DownSpeed':     peer.down_speed/1024,
                   'TotalDownload': peer.total_download,
                   'TotalUpload':   peer.total_upload,
                   'Country':       peer.country,
                   'Client':        peer.client
                   }
            peers['peers'].append(pi)
        return peers
    '''def stats(self):
        status = self.torrentHandle.status()
        dhtStatusStr = ''
        if not status.has_metadata:
            return
        if self.config.showAllStats or self.config.showOverallProgress:
            sessionStatus = self.session.status()
            if self.session.is_dht_running():
                dhtStatusStr = ', DHT nodes: %d' % (sessionStatus.dht_nodes,)
            errorStr = ''
            if len(status.error) > 0:
                errorStr = ' (%s)' % (status.error,)
            logging.info('%s, overall progress: %.2f%%, dl/ul: %.3f/%.3f kbps, peers/seeds: %d/%d'  % (
                          str(status.state),
                          status.progress * 100,
                          float(status.download_rate)/1024,
                          float(status.upload_rate)/1024,
                          status.num_peers,
                          status.num_seeds
                          ) + dhtStatusStr + errorStr
                         )
            if self.config.showFilesProgress or self.config.showAllStats:
                str_ = 'Files: '
                for i, f in enumerate(self.TorrentFS.files):
                    str_ += '[%d] %.2f%% ' % (i, f.Progress()*100)
                logging.info(str_)
            if (self.config.showPiecesProgress or self.config.showAllStats) and self.TorrentFS.lastOpenedFile != None:
                self.TorrentFS.lastOpenedFile.ShowPieces()
'''
    def consumeAlerts(self):
        alerts = self.session.pop_alerts()
        for alert in alerts:
            if type(alert) == lt.save_resume_data_alert:
                self.processSaveResumeDataAlert(alert)
                break
    def waitForAlert(self, alert_type, timeout):
        start = time.time()
        while True:
            alert = self.session.wait_for_alert(100)
            if (time.time() - start) > timeout:
                return None
            if alert is not None:
                alert = self.session.pop_alert()
                if type(alert) == alert_type:
                    return alert
    def loop(self):
        #self.statsTicker = Ticker(30)
        self.saveResumeDataTicker = Ticker(5)
        time_start = time.time()
        while True:
            if self.forceShutdown:
                return
            if time.time() - time_start > 0.5:
                self.consumeAlerts()
                self.TorrentFS.LoadFileProgress()
                state = self.torrentHandle.status().state
                if self.config.exitOnFinish and (state == state.finished or state == state.seeding):
                    self.forceShutdown = True
                if os.getppid() == 1:
                    self.forceShutdown = True
                time_start = time.time()
            #if self.statsTicker.true:
            #    self.stats()
            if self.saveResumeDataTicker.true:
                self.saveResumeData(True)
            time.sleep(0.3)

    def processSaveResumeDataAlert(self, alert):
        logging.info('Saving resume data to: %s' % (encode_msg(self.config.resumeFile),))
        data = lt.bencode(alert.resume_data)
        try:
            with open(self.config.resumeFile, 'wb') as f:
                f.write(data)
        except IOError as e:
            strerror = e.args
            logging.error(strerror)
    def saveResumeData(self, async = False):
        if not self.torrentHandle.status().need_save_resume or self.config.resumeFile == '':
            return False
        self.torrentHandle.save_resume_data(lt.save_resume_flags_t.flush_disk_cache)
        if not async:
            alert = self.waitForAlert(lt.save_resume_data_alert, 5)
            if alert == None:
                return False
            self.processSaveResumeDataAlert(alert)
        return True
    def saveSessionState(self):
        if self.config.stateFile == '':
            return
        entry = self.session.save_state()
        data = lt.bencode(entry)
        logging.info('Saving session state to: %s' % (encode_msg(self.config.stateFile),))
        try:
            logging.info('Saving session state to: %s' % (encode_msg(self.config.stateFile),))
            with open(self.config.stateFile, 'wb') as f:
                f.write(data)
        except IOError as e:
            strerror = e.args
            logging.error(strerror)
    def removeFiles(self, files):
        for file in files:
            try:
                os.remove(file)
            except Exception as e:
                strerror = e.args
                logging.error(strerror)
            else:
                path = os.path.dirname(file)
                savePath = os.path.abspath(self.config.downloadPath)
                savePath = savePath[-1] == os.path.sep and savePath[:-1] or savePath
                while path != savePath:
                    os.remove(path)
                    path_ = os.path.dirname(path)
                    path = path_[-1] == os.path.sep and path_[:-1] or path_
    def filesToRemove(self):
        files = []
        if self.TorrentFS.HasTorrentInfo():
            for i, f in enumerate(self.torrentHandle.files()):
                isComplete = self.TorrentFS.progresses[i] == f.size
                if (not self.config.keepComplete or not isComplete) and (not self.config.keepIncomplete or isComplete):
                    path = os.path.abspath(os.path.join(self.TorrentFS.save_path, localize_path(f.path)))
                    if os.path.exists(path):
                        files.append(path)
        return files
    def removeTorrent(self):
        files = []
        flag = 0
        state = self.torrentHandle.status().state
        if state != state.checking_files and not self.config.keepFiles:
            if not self.config.keepComplete and not self.config.keepIncomplete:
                flag = int(lt.options_t.delete_files)
            else:
                files = self.filesToRemove()
        logging.info('Removing the torrent')
        self.session.remove_torrent(self.torrentHandle, flag)
        if flag > 0 or len(files) > 0:
            logging.info('Waiting for files to be removed')
            self.waitForAlert(lt.torrent_deleted_alert, 15)
            self.removeFiles(files)
    def shutdown(self):
        logging.info('Stopping pyrrent2http...')
        self.forceShutdown = True
        #self.statsTicker.stop()
        self.saveResumeDataTicker.stop()
        self.httpListener.shutdown()
        self.TorrentFS.Shutdown()
        if self.session != None:
            self.session.pause()
            self.waitForAlert(lt.torrent_paused_alert, 10)
            if self.torrentHandle is not None:
                self.saveResumeData(False)
                self.saveSessionState()
                self.removeTorrent()
            logging.info('Aborting the session')
            del self.session
        logging.info('Bye bye')
