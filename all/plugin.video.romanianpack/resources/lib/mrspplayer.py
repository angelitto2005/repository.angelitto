# -*- coding: utf-8 -*-

import sys
import os
import re
import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon
import xbmcvfs
import hashlib
from collections import namedtuple
try:
    import urllib
    from urlparse import urljoin
    from urllib import pathname2url
    from contextlib import nested
    py3 = False
except:
    from urllib.parse import urljoin
    from urllib.request import pathname2url
    import urllib.parse as urllib
    py3 = True
from torrent2http import State, Engine, MediaType, s, Error
from contextlib import contextmanager, closing
import mimetypes

from resources.functions import log,cutFileNames,unescape,ensure_str,get_ids_video,isSubtitle,showMessage,is_writable, requests, get_ip, check_torrent2http, pbar

SessionStatus = namedtuple('SessionStatus', "name, state, state_str, error, progress, download_rate, upload_rate, "
                                            "total_download, total_upload, num_peers, num_seeds, total_seeds, "
                                            "total_peers, hash_string, session_status")

FileStatus = namedtuple('FileStatus', "name, save_path, url, size, offset, download, progress, index, media_type, priority")

PeerInfo = namedtuple('PeerInfo', "ip, flags, source, up_speed, down_speed, total_upload, total_download, "
                                  "country, client")

FileInfo = namedtuple('FileInfo', "name, save_path, url, size, bufferx, download, progress, state, total_download, total_upload, "
                                  "download_rate, upload_rate, num_peers, num_seeds, total_seeds, total_peers")


ROOT = xbmcaddon.Addon(id='plugin.video.romanianpack').getAddonInfo('path')
RESOURCES_PATH = os.path.join(ROOT, 'resources')

WINDOW_FULLSCREEN_VIDEO = 12005
XBFONT_LEFT = 0x00000000
XBFONT_RIGHT = 0x00000001
XBFONT_CENTER_X = 0x00000002
XBFONT_CENTER_Y = 0x00000004
XBFONT_TRUNCATED = 0x00000008
XBFONT_JUSTIFY = 0x00000010
VIEWPORT_WIDTH = 1920.0
VIEWPORT_HEIGHT = 1088.0
STATE_STRS = [
    'Queued',
    'Se verifică',
    'Descărcare Metadata',
    'Downloading',
    'Finished',
    'Seeding',
    'Alocare spațiu',
    'Alocare fișier & Verificare'
]

def getset(name):
    try: setting = xbmcaddon.Addon(id='plugin.video.torrenter').getSetting(name)
    except: setting = ''
    return setting

def mrgetset(name):
    return xbmcaddon.Addon(id='plugin.video.romanianpack').getSetting(name)

if mrgetset('pauseinfo') == '0':
    OVERLAY_WIDTH = int(VIEWPORT_WIDTH * 0.9)  # 90% size
else:
    OVERLAY_WIDTH = int(VIEWPORT_WIDTH * 0.7)  # 70% size
OVERLAY_HEIGHT = 160


def convert_tmdb_to_imdb(tmdb_id, media_type='movie'):
    """
    Convertește TMDb ID în IMDb ID folosind API-ul TMDb.
    """
    if not tmdb_id:
        return None
    try:
        api_key = "f090bb54758cabf231fb605d3e3e0468"  # Cheie publică standard
        url = "https://api.themoviedb.org/3/%s/%s/external_ids?api_key=%s" % (media_type, tmdb_id, api_key)
        
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            imdb_id = data.get('imdb_id')
            if imdb_id:
                log('[MRSP-PLAYER] Conversie TMDb->IMDb reusita: %s -> %s' % (tmdb_id, imdb_id))
                return imdb_id
    except Exception as e:
        log('[MRSP-PLAYER] Eroare conversie TMDb->IMDb: %s' % str(e))
    return None

class MRPlayer(xbmc.Player):

    torrentFilesDirectory = 'torrents'
    torrentFile = None
    seedingtransmission = False
    seedingmrsp = False
    seedingtorrenter = False
    trakton = False
    externaddon = False
    contentidforseed = 0
    seeding_status = False
    seeding_run = False
    ids_video = None
    episodeId = None
    fullSize = 0
    watchedTime = 0
    totalTime = 1
    seek = 0
    basename = ''
    files = None
    subfiles = []
    subs = []
    iterator = 0
    download = False
    predownload_next = mrgetset('predownload_next') == 'true'
    keep_complete_files = mrgetset('keep_complete_files') == 'true'
    startednext = False
    
    def f_b(self, B):
        B = B * 1024
        B = float(B)
        KB = float(1024)
        MB = float(KB ** 2) # 1,048,576
        GB = float(KB ** 3) # 1,073,741,824
        TB = float(KB ** 4) # 1,099,511,627,776

        if B < KB:
            return '{0:.1f}B'.format(B)
        elif KB <= B < MB:
            return '{0:.2f}KB'.format(B/KB)
        elif MB <= B < GB:
            return '{0:.2f}MB'.format(B/MB)
        elif GB <= B < TB:
            return '{0:.2f}GB'.format(B/GB)
        elif TB <= B:
            return '{0:.2f}TB'.format(B/TB)
    
    def start(self,uri,path='',cid=None,params={},files=None,browse=False,download=False):
        self.download = download
        self.browse = browse
        self.files = files
        
        # =====================================================================
        # FIX: Curățăm Window Properties vechi LA ÎNCEPUT
        # =====================================================================
        try:
            home_window = xbmcgui.Window(10000)
            for prop in ['TMDb_ID', 'tmdb_id', 'tmdb', 'VideoPlayer.TMDb',
                         'IMDb_ID', 'imdb_id', 'imdb', 'VideoPlayer.IMDb', 
                         'VideoPlayer.IMDBNumber']:
                home_window.clearProperty(prop)
            log('[MRSP-PLAYER] Window Properties vechi curățate la start')
        except:
            pass
        # =====================================================================
        
        handle = int(sys.argv[1])
        self.params = params
        self.mrget = self.params.get
        self.cmdline_proc = self.mrget('cmdline_proc')
        self.seek_time = self.mrget('seek_time')
        self.played_file = self.mrget('played_file')
        self.binaries_path = self.mrget('binaries_path') or mrgetset('torrent_bin_path') or  None
        self.userStorageDirectory = path or mrgetset('storage') or getset('storage')
        self.sub = mrgetset('download_sub') == 'true'
        self.torrentUrl = uri
        if not self.cmdline_proc:
            self.progressBar = xbmcgui.DialogProgress()
            self.progressBar.create('[B][COLOR FFFDBD01]MRSPPlayer:[/COLOR][/B] Așteaptă...', 'Pornire')
        self.init()
        self.contentId = int(cid) if cid else None
        if not re.match("^magnet\:.+$", self.torrentUrl) and not self.torrentUrl.startswith('file:'):
            self.savetorrent()
        self.setup_engine()
        if self.cmdline_proc:
            return self.engine.start(-1)
        stop = False
        file_status = None
        self.subs = None
        ready = False
        filelist = []
        if self.download:
            self.engine.start(self.contentId or 9999)
            self.progressBar.close()
            showMessage('MRSP', 'Torrent adăugat la download!', forced=True)
        else:
            self.torrent_exists(play=True)
            while True:
                xbmc.sleep(500)
                self.status = self.engine.status()
                if not self.progressBar:
                    self.progressBar = xbmcgui.DialogProgress()
                    self.progressBar.create('[MRSPPlayer] Așteaptă...', 'Pornire')
                if self.status.state == State.DOWNLOADING_METADATA:
                    while self.status.state == State.DOWNLOADING_METADATA:
                        self.status = self.engine.status()
                        getSeeds, getPeers = self.status.num_seeds, self.status.num_peers
                        totalseeds, totalpeers = self.status.total_seeds, self.status.total_peers
                        self.progressBar.update(*pbar(0, 'Pornire', 'Descărcare Metadata', '[S: %s/%s; P: %s/%s]' % (getSeeds, totalseeds, getPeers, totalpeers)))
                        if self.progressBar.iscanceled():
                            break
                        xbmc.sleep(500)
                self.status = self.engine.status()
                if self.browse:
                    if not self.files:
                        while not self.files:
                            files = self.engine.list()
                            if self.progressBar.iscanceled():
                                self.files = None
                                break
                            if files:
                                for fs in files:
                                    fsurl = fs.url
                                    if s.role == 'client' and (not s.mrsprole):
                                        fsurl = fs.url.replace('0.0.0.0', s.remote_host)
                                    stringdata = {"title": ensure_str(fs.name), "size": fs.size, "ind": fs.index, 'save_path': ensure_str(fs.save_path), 'file_url': fsurl}
                                    filelist.append(stringdata)
                                self.files = filelist
                            xbmc.sleep(500)
                        if not self.files: break
                    self.progressBar.close()
                    if self.files:
                        break
                    else:
                        continue
                if self.status.state == State.ALLOCATING:
                    self.progressBar.update(*pbar(0, 'Pornire', 'Alocare spațiu'))
                elif self.status.state == State.CHECKING_FILES:
                    while self.status.state == State.CHECKING_FILES:
                        self.status = self.engine.status()
                        iterator = int(self.status.progress*100)
                        if iterator > 99: iterator = 99
                        progres = 'Progres: %s %%' % (str(int(self.status.progress*100)))
                        self.progressBar.update(*pbar(iterator, 'Se verifică fișierele existente...', progres, 'Așteaptă...ne grăbim undeva?'))
                        if self.progressBar.iscanceled():
                            break
                        xbmc.sleep(500)
                elif self.status.state == State.SEEDING:
                    self.progressBar.update(*pbar(0, 'Pornire', 'Torrent existent in seed'))
                self.status = self.engine.status()
                if self.progressBar.iscanceled():
                    break
                if not self.files:
                    while not self.files:
                        files = self.engine.list()
                        if self.progressBar.iscanceled():
                            self.files = None
                            break
                        if files:
                            for fs in files:
                                fsurl = fs.url
                                if s.role == 'client' and (not s.mrsprole):
                                    fsurl = fs.url.replace('0.0.0.0', s.remote_host)
                                stringdata = {"title": ensure_str(fs.name), "size": fs.size, "ind": fs.index, 'save_path': ensure_str(fs.save_path), 'file_url': fsurl}
                                filelist.append(stringdata)
                            self.files = filelist
                        xbmc.sleep(500)
                    if not self.files: break
                if self.browse: 
                    self.progressBar.close()
                    if self.files:
                        break
                while self.contentId is None:
                    self.status = self.engine.status()
                    if self.status:
                        getSeeds, getPeers = self.status.num_seeds, self.status.num_peers
                        totalseeds, totalpeers = self.status.total_seeds, self.status.total_peers
                        self.progressBar.update(*pbar(0, 'Pornire','Preluare listă fișiere','[S: %s/%s; P: %s/%s]' % (getSeeds, totalseeds, getPeers, totalpeers)))
                        items, filess, contentList, sizes = [], [], [], {}
                        if self.progressBar.iscanceled():
                            break
                        if self.played_file:
                            d = dict((i.get('title'), i.get('ind')) for i in self.files)
                            if py3: ditems = d.items()
                            else: ditems = d.iteritems()
                            has_key = [value for key, value in ditems if self.played_file in key]
                            if has_key:
                                actions = []
                                next_index = 0
                                try: self.ids_video = self.get_ids()
                                except: pass
                                if mrgetset('seenaskall') == 'true':
                                    if self.seek_time:
                                        actions.append('Pornește de la început')
                                        actions.append('Reia de unde am rămas')
                                    if self.ids_video and len(self.ids_video)>1:
                                        actions.append('Aleg alt episod')
                                        if not self.seek_time:
                                            actions.append('Reia același episod văzut')
                                        next_index = self.ids_video.index(str(has_key[0])) + 1
                                        if len(self.ids_video) > next_index:
                                            actions.append('Pornește următorul episod nevăzut')
                                    else:
                                        if not self.seek_time:
                                            actions = ['Reia același episod văzut']
                                else:
                                    if mrgetset('seenaskmultiple') == 'true':
                                        actions = ['Reia același episod văzut']
                                        if self.ids_video and len(self.ids_video)>1:
                                            actions.append('Aleg alt episod')
                                            next_index = self.ids_video.index(str(has_key[0])) + 1
                                            if len(self.ids_video) > next_index:
                                                actions.append('Pornește următorul episod nevăzut')
                                    else:
                                        if mrgetset('seenstartsame') == 'true':
                                            actions = ['Reia același episod văzut']
                                        if self.ids_video and len(self.ids_video)>1:
                                            if mrgetset('seenchoseanother') == 'true':
                                                actions = ['Aleg alt episod']
                                            if mrgetset('seenstartnext') == 'true':
                                                next_index = self.ids_video.index(str(has_key[0])) + 1
                                                if len(self.ids_video) > next_index:
                                                    actions = ['Pornește următorul episod nevăzut']
                                    if self.seek_time:
                                        if mrgetset('seenask') == 'false':
                                            if mrgetset('seekstartfrombegining') == 'true':
                                                actions = ['Pornește de la început']
                                            if mrgetset('seekresume') == 'true':
                                                actions = ['Reia de unde am rămas']
                                            if self.ids_video and len(self.ids_video)>1:
                                                if mrgetset('seekchoseanother') == 'true':
                                                    actions = ['Aleg alt episod']
                                                if mrgetset('seekstartnext') == 'true':
                                                    next_index = self.ids_video.index(str(has_key[0])) + 1
                                                    if len(self.ids_video) > next_index:
                                                        actions = ['Pornește următorul episod nevăzut']
                                        else:
                                            actions = ['Reia de unde am rămas','Pornește de la început']
                                            if self.ids_video and len(self.ids_video)>1:
                                                actions.append('Aleg alt episod')
                                                next_index = self.ids_video.index(str(has_key[0])) + 1
                                                if len(self.ids_video) > next_index:
                                                    actions.append('Pornește următorul episod nevăzut')
                                            
                                
                                if len(actions) > 1:
                                    d = xbmcgui.Dialog()
                                    ret = d.select('Alege acțiunea', actions)
                                else:
                                    ret = 0
                                if ret == -1 :
                                    self.contentId = ret
                                    continue
                                if actions[ret] == 'Reia de unde am rămas' or actions[ret] == 'Pornește de la început' or actions[ret] == 'Reia același episod văzut':
                                    self.contentId = int(has_key[0])
                                    if actions[ret] == 'Pornește de la început':
                                        self.seek_time = None
                                elif actions[ret] == 'Pornește următorul episod nevăzut':
                                    self.contentId = int(self.ids_video[next_index])
                                    self.seek_time = None
                                elif actions[ret] == 'Aleg alt episod':
                                    self.played_file = None
                                    self.seek_time = None
                                    continue
                                else:
                                    self.contentId = -1
                            else:
                                self.played_file = None
                        else:
                            for filedict in self.files:
                                fileTitle = ''
                                if filedict.get('size'):
                                    sizes[str(filedict.get('ind'))]='[%d MB] ' % (filedict.get('size') / 1024 / 1024)
                                title = os.path.join(os.path.basename(os.path.dirname(filedict.get('title'))), os.path.basename(filedict.get('title')))
                                fileTitle = fileTitle + '[%s]%s' % (title[len(title) - 3:], title)
                                contentList.append((unescape(fileTitle), str(filedict.get('ind'))))
                            contentList = sorted(contentList, key=lambda x: x[0])
                            EXTS=['avi','mp4','mkv','flv','mov','vob','wmv','ogm','asx','mpg','mpeg','avc','vp3','fli','flc','m4v','iso','mp3','m2ts','3gp', 'ts']
                            for title, identifier in contentList:
                                if py3:
                                    try: titled = title.decode().split('.')[-1].lower()
                                    except: titled = title.split('.')[-1].lower()
                                else:
                                    titled = title.decode('utf-8').split('.')[-1].lower()
                                if titled in EXTS:
                                    items.append(title)
                                    filess.append(identifier)
                            if len(items) > 1:
                                if len(sizes)==0: items = cutFileNames(items)
                                else:
                                    cut = cutFileNames(items)
                                    items=[]
                                    x=-1
                                    for i in filess:
                                        x=x+1
                                        fileTitle=sizes[str(i)]+cut[x]
                                        items.append(fileTitle)
                            if len(items) == 1:
                                ret = 0
                            else: ret = xbmcgui.Dialog().select('Search results:', items)
                            if ret >= 0:
                                ret = int(filess[ret])
                            self.contentId = ret
                    if self.contentId == -1:
                        break
                if self.contentId == -1:
                        break
                if self.sub:
                    sub_format = ['aqt', 'gsub', 'jss', 'sub',
                                    'ttxt', 'pjs', 'psb', 'rt',
                                    'smi', 'stl', 'ssf', 'srt',
                                    'ssa', 'ass', 'usf', 'idx',
                                    'mpsub', 'rum', 'sbt', 'sbv',
                                    'sup', 'w32', 'smil', 'mpl2',
                                    'mks']
                    filename = ''
                    subs = []
                    ids_video = self.get_ids()
                    if ids_video and len(ids_video)<2:
                        othersub = True
                    else: othersub = False
                    if self.files:
                        if not self.subs:
                            for i in self.files:
                                if i.get('ind') == self.contentId:
                                    filename = os.path.basename(i.get('title'))
                                    break
                            for i in self.files:
                                if i.get('title').split('.')[-1].lower() in sub_format:
                                    if not othersub == True:
                                        if isSubtitle(filename, os.path.basename(i.get('title'))):
                                            subs.append(i)
                                    else:
                                        subs.append(i)
                            if subs:
                                items=[]
                                for i in subs:
                                    items.append(os.path.basename(i.get('title')))
                                for j in subs:
                                    jsub = j.get('file_url')
                                    if s.role == 'client' and (not s.mrsprole):
                                        jsub = jsub.replace('0.0.0.0', s.remote_host)
                                    self.subfiles.append(jsub)
                                #if len(subs) > 1:
                                    #log(subs)
                                #else:
                                #self.subs = subs[0]
                                self.subs = subs
                    if self.subs:
                        self.status = self.engine.status()
                        getSeeds, getPeers = self.status.num_seeds, self.status.num_peers
                        totalseeds, totalpeers = self.status.total_seeds, self.status.total_peers
                        self.progressBar.update(*pbar(0, 'Pornire','Descărcare Subtitrare din torrent','[S: %s/%s; P: %s/%s]' % (getSeeds, totalseeds, getPeers, totalpeers)))
                        #self.engine.check_torrent_error(self.status)
                        for subtodownload in self.subs:
                            sub_status = self.engine.file_status(subtodownload.get('ind'))
                            if sub_status:
                                self.engine.priority(subtodownload.get('ind'), '7')
                                while sub_status.progress < 1 and not xbmc.Monitor().abortRequested():
                                    sub_status = self.engine.file_info()
                                    fullSize = int(sub_status.size / 1024)
                                    downloadedSize = sub_status.download / 1024
                                    getDownloadRate = self.f_b(sub_status.download_rate)
                                    getUploadRate = self.f_b(sub_status.upload_rate)
                                    getSeeds, getPeers = sub_status.num_seeds, sub_status.num_peers
                                    totalseeds, totalpeers = sub_status.total_seeds, sub_status.total_peers
                                    iterator = int(round(float(sub_status.download) / self.pre_buffer_bytes, 2) * 100)
                                    dialogText = 'Subtitrare: ' + "%d kB / %d kB" % \
                                                                                (int(downloadedSize), fullSize)
                                    peersText = ' [%s: %s/%s; %s: %s/%s]' % (
                                        'Seeds', getSeeds, totalseeds, 'Peers', getPeers, totalpeers)
                                    speedsText = '%s: %s/s; %s: %s/s' % (
                                        'Downloading', getDownloadRate,
                                        'Uploading', getUploadRate)
                                    self.progressBar.update(*pbar(iterator, 'Descărcare subtitrare.%s' % peersText,'%s' % dialogText,'%s' % speedsText))
                                    xbmc.sleep(500)
                                    if self.progressBar.iscanceled():
                                        break
                if (self.contentId is not None) and (self.files):
                    file_info = self.engine.file_info()
                    if self.progressBar.iscanceled():
                        self.iterator = 0
                        ready = False
                        break
                    if file_info:
                        self.setup_nextep()
                        self.engine.priority(self.contentId, '7')
                        file_info = self.engine.file_info()
                        while (file_info.bufferx < 1) and (not xbmc.Monitor().abortRequested()):
                            if not self.progressBar:
                                self.progressBar = xbmcgui.DialogProgress()
                                self.progressBar.create('[MRSPPlayer] Așteaptă...', 'Pornire')
                            file_info = self.engine.file_info()
                            fullSize = int(file_info.size / 1024 / 1024)
                            downloadedSize = file_info.bufferx / 1024 / 1024
                            getDownloadRate = self.f_b(file_info.download_rate)
                            getUploadRate = self.f_b(file_info.upload_rate)
                            getSeeds, getPeers = file_info.num_seeds, file_info.num_peers
                            totalseeds, totalpeers = file_info.total_seeds, file_info.total_peers
                            iterator = int(round(float(file_info.bufferx), 2) * 100)
                            dialogText = 'Buffer: ' + "%s %% - %s" % (str(round((float(file_info.bufferx) * 100), 2)), self.f_b(file_info.download / 1024))
                            peersText = ' [%s: %s/%s; %s: %s/%s]' % (
                                'Seeds', getSeeds, totalseeds, 'Peers', getPeers, totalpeers)
                            speedsText = '%s: %s/s; %s: %s/s \n%s' % (
                                'Downloading', getDownloadRate,
                                'Uploading', getUploadRate, os.path.basename(file_info.name))
                            self.progressBar.update(*pbar(iterator, 'Seeds searching.%s' % peersText,'%s' % dialogText,'%s' % speedsText))
                            if self.progressBar.iscanceled():
                                self.iterator = 0
                                ready = False
                                break
                            xbmc.sleep(1000)
                        if file_info.bufferx >= 1:
                            ready = True
                if self.progressBar.iscanceled():
                    break
                if ready:
                    if py3: self.progressBar.update(100, 'Pornire\nSe inițializează redarea')
                    else: self.progressBar.update(100, 'Pornire', 'Se inițializează redarea', ' ')
                    xbmc.sleep(500)
                    self.iterator = 0
                    iterator = 0
                    self.watchedTime = 0
                    self.totalTime = 1
                    url = file_info.url
                    if s.role == 'client' and (not s.mrsprole):
                        url = url.replace('0.0.0.0', s.remote_host)
                    label = os.path.basename(file_info.name)
                    self.display_name = label
                    self.seeding_run = False
                    if self.next_dl:
                        next_contentId_index = self.ids_video.index(str(self.contentId)) + 1
                        if len(self.ids_video) > next_contentId_index:
                            self.next_contentId = int(self.ids_video[next_contentId_index])
                        else:
                            self.next_contentId = False
                    
                    # ==============================================================================
                    # SETARE METADATE FĂRĂ WARNING (Kodi 20+)
                    # ==============================================================================

                    # 1. Recuperam parametrii ID
                    p_tmdb = self.mrget('tmdb_id')
                    p_imdb = self.mrget('imdb_id')

                    # 2. CONVERSIE: Dacă avem TMDb dar NU avem IMDb, convertim
                    if p_tmdb and (not p_imdb or str(p_imdb) == 'None'):
                        media_type = 'movie'
                        if self.ids_video and len(self.ids_video) > 1:
                            media_type = 'tv'
                        if self.mrget('season') or self.mrget('episode'):
                            media_type = 'tv'
                        
                        converted_imdb = convert_tmdb_to_imdb(p_tmdb, media_type)
                        if converted_imdb:
                            p_imdb = converted_imdb
                            log('[MRSP-PLAYER] IMDb obtinut din conversie: %s' % p_imdb)

                    # 3. Cream ListItem
                    listitem = xbmcgui.ListItem(label)

                    # 4. Setam metadate folosind DOAR InfoTagVideo (fara setInfo)
                    try:
                        info_tag = listitem.getVideoInfoTag()
                        info_tag.setTitle(label)
                        
                        # Setam UniqueIDs
                        uids = {}
                        if p_tmdb and str(p_tmdb) != 'None': 
                            uids['tmdb'] = str(p_tmdb)
                        if p_imdb and str(p_imdb) != 'None': 
                            uids['imdb'] = str(p_imdb)
                        
                        if uids:
                            info_tag.setUniqueIDs(uids)
                            if 'imdb' in uids:
                                info_tag.setIMDBNumber(uids['imdb'])
                            log('[MRSP-PLAYER] UniqueIDs setate cu succes: %s' % str(uids))
                            
                    except AttributeError:
                        # Fallback pentru Kodi < 20
                        log('[MRSP-PLAYER] Kodi vechi detectat, folosesc setInfo')
                        std_info = {'Title': label}
                        if p_imdb: 
                            std_info['imdbnumber'] = str(p_imdb)
                        listitem.setInfo('video', std_info)

                    # 5. WINDOW PROPERTIES - Citite de addon-ul de subtitrări
                    home_window = xbmcgui.Window(10000)

                    for prop in ['TMDb_ID', 'tmdb_id', 'tmdb', 'VideoPlayer.TMDb', 
                                 'IMDb_ID', 'imdb_id', 'imdb', 'VideoPlayer.IMDb', 'VideoPlayer.IMDBNumber']:
                        home_window.clearProperty(prop)

                    if p_tmdb and str(p_tmdb) != 'None':
                        home_window.setProperty('TMDb_ID', str(p_tmdb))
                        home_window.setProperty('tmdb_id', str(p_tmdb))
                        home_window.setProperty('tmdb', str(p_tmdb))
                        home_window.setProperty('VideoPlayer.TMDb', str(p_tmdb))
                        log('[MRSP-PLAYER] Window Property TMDb setat: %s' % str(p_tmdb))

                    if p_imdb and str(p_imdb) != 'None':
                        home_window.setProperty('IMDb_ID', str(p_imdb))
                        home_window.setProperty('imdb_id', str(p_imdb))
                        home_window.setProperty('imdb', str(p_imdb))
                        home_window.setProperty('VideoPlayer.IMDb', str(p_imdb))
                        home_window.setProperty('VideoPlayer.IMDBNumber', str(p_imdb))
                        log('[MRSP-PLAYER] Window Property IMDb setat: %s' % str(p_imdb))

                    # 6. ListItem Properties (backup)
                    if p_tmdb:
                        listitem.setProperty('tmdb_id', str(p_tmdb))
                        listitem.setProperty('TMDb_ID', str(p_tmdb))
                    if p_imdb:
                        listitem.setProperty('imdb_id', str(p_imdb))
                        listitem.setProperty('IMDb_ID', str(p_imdb))

                    listitem.setContentLookup(False)
                    listitem.setPath(url)

                    if self.subs:
                        listitem.setSubtitles(self.subfiles)

                    self.progressBar.close()
                    self.progressBar = False

                    self._playback_tmdb = p_tmdb
                    self._playback_imdb = p_imdb

                    self.play(url, listitem)
                    # ==============================================================================
                    
                    i=0
                    while not xbmc.Monitor().abortRequested() and not self.isPlaying() and i < 450:
                        xbmc.sleep(200)
                        i += 1
                    self.loop()
                    while not xbmc.Monitor().abortRequested() and self.isPlaying():
                        self.totalTime = self.getTotalTime()
                        self.watchedTime = self.getTime()
                        xbmc.sleep(1000)
                    #if self.iterator < 100:
                        #ready = False
                    self.seed()
                    if self.next_dl and self.next_contentId != False and isinstance(self.next_contentId, int):
                        if self.next_play:
                            
                            if not xbmcgui.Dialog().yesno(
                                '[MRSP Player] ',
                                'Vrei să pornesc următorul episod?'):
                                    break
                            self.contentId = self.next_contentId
                            ready = False
                            self.iterator = 0
                            self.startednext = False
                            self.seek_time = ''
                            self.played_file = ''
                            continue
                        else:
                            xbmc.sleep(1000)
                            self.contentId = self.next_contentId
                            ready = False
                            self.iterator = 0
                            self.startednext = False
                            self.seek_time = ''
                            self.played_file = ''
                            continue
                    else:
                        break
            if self.browse:
                try: self.engine.close()
                except: pass
                if self.files:
                    return self.torrentFile or self.torrentUrl, self.files
                else: return None,None
            else:
                if not self.seedingmrsp:
                    try:
                        if not self.browse: self.engine.wait_on_close(20)
                        self.engine.close()
                    except: pass
    
    def init(self):
        self.next_contentId = False
        self.display_name = ''
        self.downloadedSize = 0
        self.on_playback_started = []
        self.on_playback_resumed = []
        self.on_playback_paused = []
        self.on_playback_stopped = []
        self.torrentUrl = self.torrentUrl
        self.torrentFilesPath = os.path.join(self.userStorageDirectory, self.torrentFilesDirectory) + os.sep
        if not self.userStorageDirectory:
            xbmcgui.Dialog().ok('MRSP Player',
            'Folderul de Download nu există![CR]Adaugă-l în Setări -> MRSP Torrent Player![CR]Torrent Download Folder: "%s"' % (self.userStorageDirectory))
            sys.exit(1)
        if not is_writable(self.userStorageDirectory):
            xbmcgui.Dialog().ok('MRSP Player',
                    'Folderul de Download nu are drepturi de scriere sau nu este local![CR]Schimbă-l în Setări -> MRSP Torrent Player![CR]Torrent Download Folder: "%s"' % (self.userStorageDirectory))
            sys.exit(1)
        xbmcvfs.mkdirs(os.path.join(self.userStorageDirectory, '.resume'))

    def torrent_exists(self, play=False, seed=False):
        if not self.browse:
            if self.progressBar:
                self.progressBar.update(*pbar(0, 'Pornire', 'Verific dacă torrentul există deja în server'))
            hashtorrent = None
            if not re.match("^magnet\:.+$", self.torrentUrl):
                from resources.lib import bencode
                import hashlib
                f = open(self.torrentFile, 'rb')
                torrent = f.read()
                f.close()
                metainfo = bencode.bdecode(torrent)
                info = metainfo.get('info')
                hashtorrent = hashlib.sha1(bencode.bencode(info)).hexdigest() 
            else:
                hashtorrent = re.findall('btih\:(.+?)&', self.torrentUrl)[0]
            processes = check_torrent2http()
            listprocesses = []
            if processes:
                for resume, process in processes:
                    try:
                        data = requests.get('http://%s/status' % process).json()
                        listprocesses.append((process, data))
                    except:
                        showMessage('Atentie', 'Ai un process zombi, restarteaza kodi sau aparatul', forced=True)
            have = False
            for proc, i in listprocesses:
                if i.get('hash_string').lower() == hashtorrent.lower():
                    have = True
                    self.engine = CustEngine(combined=proc)
                    break
        else:
            have = False
        if not have:
            if self.browse:
                self.engine.start(-1)
            else:
                self.engine.start(self.contentId or 0)
    
    def setup_engine(self):
        encryption = int(mrgetset('encryption'))
        upload_limit = int(mrgetset('upload_limit')) if mrgetset('upload_limit') != '' else 0
        download_limit = int(mrgetset('download_limit')) if mrgetset('download_limit') != '' else 0
        if mrgetset('connections_limit') not in ["",0,"0"]:
            connections_limit = int(mrgetset('connections_limit'))
        else: connections_limit = None
        connection_speed = int(mrgetset('connection_speed')) if mrgetset('connection_speed') else 100
        tuned_storage = mrgetset('tuned_storage') == 'true'
        use_random_port = mrgetset('use_random_port') == 'true'
        listen_port = int(mrgetset('listen_port')) if mrgetset('listen_port') != '' else 6881
        site = self.mrget('site')
        exit_on_finish = False
        if self.download: 
            exit_on_finish = True
        if mrgetset('seedtransmission') == 'true' or mrgetset('%sseedtransmission' % site) == 'true' or mrgetset('seedmrsp') == 'true' or mrgetset('%sseedmrsp' % site) == 'true' or self.download or self.keep_complete_files:
            if mrgetset('seedtransmission') == 'true' or mrgetset('%sseedtransmission' % site) == 'true' or mrgetset('seedmrsp') == 'true' or mrgetset('%sseedmrsp' % site) == 'true' or self.keep_complete_files:
                exit_on_finish = False
            keep_complete = True
            keep_incomplete = False
            keep_files = False
            resume_file = None
            if not self.download:
                if mrgetset('seedtransmission') == 'true' or mrgetset('%sseedtransmission' % site) == 'true':
                    self.seedingtransmission = True
                elif mrgetset('seedmrsp') == 'true' or mrgetset('%sseedmrsp' % site) == 'true':
                    self.seedingmrsp = True
                    resume_file=os.path.join(self.userStorageDirectory, '.resume', self.md5(self.torrentUrl) +'.resume_data')
                if not self.keep_complete_files:
                    keep_incomplete = True
                    keep_files = True
        else:
            keep_complete = False
            keep_incomplete = False
            keep_files = False
            resume_file = None
        if self.browse:
            self.seedingtransmission = False
            self.seedingmrsp = False
            keep_complete = True
            keep_incomplete = True
            keep_files = True
            resume_file = None
        self.resume_file = resume_file
        enable_dht = mrgetset('enable_dht') == 'true'
        enable_lsd = mrgetset('enable_lsd') == 'true'
        enable_upnp = mrgetset('enable_upnp') == 'true'
        enable_natpmp = mrgetset('enable_natpmp') == 'true'
        enable_utp = mrgetset('enable_utp') == 'true'
        enable_tcp = mrgetset('enable_tcp') == 'true'
        enable_scrape = mrgetset('enable_scrape') == 'true'
        no_sparse = mrgetset('no_sparse') == 'true'
        dht_routers = ["router.bittorrent.com:6881","router.utorrent.com:6881"]
        user_agent = ''#'Transmission/2.12 (234)'
        filetoload = self.torrentUrl.replace(';tr=','&tr=')
        #if s.role == 'client' and (not s.mrsprole):
            #if not re.match("^magnet\:.+$", self.torrentUrl):
                ##filetoload = self.torr2magnet(self.torrentFile)
                #filetoload = self.torrentFile
        self.pre_buffer_bytes = 20*1024*1024
        #self.start_buffer = int(mrgetset('pre_buffer_bytes'))*1024*1024
        self.engine = Engine(uri=filetoload, download_path=self.userStorageDirectory, binaries_path=self.binaries_path,
                            connections_limit=connections_limit, download_kbps=download_limit, upload_kbps=upload_limit,
                            encryption=encryption, keep_complete=keep_complete, keep_incomplete=keep_incomplete,
                            connection_speed=connection_speed, tuned_storage=tuned_storage,
                            dht_routers=dht_routers, use_random_port=use_random_port, listen_port=listen_port,
                            keep_files=keep_files, user_agent=user_agent, resume_file=resume_file, enable_dht=enable_dht,
                            enable_lsd=enable_lsd, enable_upnp=enable_upnp, enable_natpmp=enable_natpmp, no_sparse=no_sparse,
                            enable_utp=enable_utp, enable_scrape=enable_scrape, enable_tcp=enable_tcp, cmdline_proc=self.cmdline_proc, exit_on_finish=exit_on_finish)
    
    def try_start_next(self):
        if self.predownload_next and (not self.startednext):
            if self.next_contentId and isinstance(self.next_contentId, int) and self.isPlaying():
                xbmc.sleep(1000)
                yes = self.engine.priority(self.next_contentId, '7')
                self.startednext = True
            else:
                self.startednext = False
    
    def loop(self):
        debug_counter = 0
        try: self.showSubtitles(True)
        except: pass
        if py3:
            with closing(
                    OverlayText(w=OVERLAY_WIDTH, h=OVERLAY_HEIGHT, alignment=XBFONT_CENTER_X | XBFONT_CENTER_Y)) as overlay:
                with self.attach(overlay.show, self.on_playback_paused), self.attach(overlay.hide, self.on_playback_resumed, self.on_playback_stopped):
                    while not xbmc.Monitor().abortRequested() and self.isPlaying():
                        file_status = self.engine.file_info()
                        try: 
                            self.watchedTime = self.getTime()
                        except: pass
                        if self.iterator == 100 and debug_counter < 100:
                            debug_counter += 1
                        else:
                            try:
                                self.totalTime = self.getTotalTime()
                            except: pass
                            debug_counter=0

                        overlay.text = "\n".join(self._get_status_lines(file_status))

                        self.iterator = int(file_status.progress * 100)
                        
                        if (self.iterator == 100 or file_status.state in [4,5]) and (not self.startednext):
                            self.try_start_next()
                        xbmc.sleep(1000)
                        if self.seek_time: 
                            self.seekTime(float(self.seek_time) - 30)
                            self.seek_time = False
        else:
            with closing(
                    OverlayText(w=OVERLAY_WIDTH, h=OVERLAY_HEIGHT, alignment=XBFONT_CENTER_X | XBFONT_CENTER_Y)) as overlay:
                with nested(self.attach(overlay.show, self.on_playback_paused),
                            self.attach(overlay.hide, self.on_playback_resumed, self.on_playback_stopped)):
                    while not xbmc.Monitor().abortRequested() and self.isPlaying():
                        file_status = self.engine.file_info()
                        try: 
                            self.watchedTime = self.getTime()
                        except: pass
                        if self.iterator == 100 and debug_counter < 100:
                            debug_counter += 1
                        else:
                            try:
                                self.totalTime = self.getTotalTime()
                            except: pass
                            debug_counter=0

                        overlay.text = "\n".join(self._get_status_lines(file_status))

                        self.iterator = int(file_status.progress * 100)
                            #log('[loop]: xbmc.Player().pause()')
                        if (self.iterator == 100 or file_status.state in [4,5]) and (not self.startednext):
                            self.try_start_next()
                        xbmc.sleep(1000)
                        if self.seek_time:
                            self.seekTime(float(self.seek_time) - 30)
                            self.seek_time = False
    
    def setup_nextep(self):
        self.contentidforseed = self.contentId
        try: self.ids_video = self.get_ids()
        except: pass
        
        if mrgetset('next_dl') == 'true' and self.ids_video and len(self.ids_video)>1:
            self.next_dl = True
        else:
            self.next_dl = False
        self.next_play = mrgetset('next_play') == 'true'
        log('[MRSP Player]: next_dl - %s, next_play - %s, ids_video - %s' % (str(self.next_dl), str(self.next_play), str(self.ids_video)))
    
    def savetorrent(self):
        if not xbmcvfs.exists(self.torrentFilesPath): xbmcvfs.mkdirs(self.torrentFilesPath)
        torrentFile = os.path.join(self.torrentFilesPath, self.md5(self.torrentUrl) + '.torrent.added')
        xbmcvfs.copy(self.torrentUrl, torrentFile)
        if xbmcvfs.exists(torrentFile) and not os.path.exists(torrentFile):
            if not xbmcvfs.exists(self.torrentFilesPath): xbmcvfs.mkdirs(self.torrentFilesPath)
            xbmcvfs.copy(self.torrentUrl, torrentFile)
        if os.path.exists(torrentFile):
            self.torrentFile = torrentFile
        self.torrentUrl = urljoin('file:', pathname2url(torrentFile))
        
    def torr2magnet(self, torrentUrl):
        from resources.lib import bencode
        import hashlib
        self.userStorageDirectory = mrgetset('storage') or getset('storage')
        self.torrentFilesPath = os.path.join(self.userStorageDirectory, self.torrentFilesDirectory) + os.sep
        if not xbmcvfs.exists(self.torrentFilesPath): xbmcvfs.mkdirs(self.torrentFilesPath)
        torrentFile = os.path.join(self.torrentFilesPath, self.md5(torrentUrl) + '.torrent.added')
        xbmcvfs.copy(torrentUrl, torrentFile)
        if xbmcvfs.exists(torrentFile) and not os.path.exists(torrentFile):
            if not xbmcvfs.exists(self.torrentFilesPath): xbmcvfs.mkdirs(self.torrentFilesPath)
            xbmcvfs.copy(torrentUrl, torrentFile)
        if os.path.exists(torrentFile):
            self.torrentFile = torrentFile
        f = open(torrentUrl, 'rb')
        torrent = f.read()
        f.close()
        try:
            metainfo = bencode.bdecode(torrent)
        except:
            return False
        info = metainfo.get('info')
        hashtorrent = hashlib.sha1(bencode.bencode(info)).hexdigest()
        tracker_list = ''
        name = ''
        length = ''
        if metainfo.get('announce-list'):
            for t in metainfo.get('announce-list'):
                for s in t:
                    tracker_list += '&tr=%s' % urllib.quote_plus(s)
        if metainfo.get('announce'):
            tracker_list += '&tr='+urllib.quote_plus(metainfo.get('announce'))
        if metainfo.get('trackers'):
            for t in metainfo.get('trackers'):
                for s in t:
                    tracker_list += '&tr=%s' % urllib.quote_plus(s)
        if info.get('name'):
            name += '&dn=%s' % urllib.quote_plus(info.get('name'))
        if info.get('length'):
            length += '&xl=%s' % info.get('length')

        result = ''.join([hashtorrent, name, length, tracker_list])

        self.torrentUrl = 'magnet:?xt=urn:btih:%s' % result
        return self.torrentUrl
    
    def seed(self):
        if self.seedingtransmission:
            tid = None
            wanted = None
            hashtorrent = None
            from resources.lib.utorrent.net import Download
            lists = Download().list()
            fileforseed = self.torrentFile or self.torrentUrl
            #fileforseed = self.torr2magnet(fileforseed)
            files = self.files
            if not re.match("^magnet\:.+$", self.torrentUrl):
                from resources.lib import bencode
                import hashlib
                f = open(self.torrentFile, 'rb')
                torrent = f.read()
                f.close()
                metainfo = bencode.bdecode(torrent)
                info = metainfo.get('info')
                hashtorrent = hashlib.sha1(bencode.bencode(info)).hexdigest() 
            else:
                hashtorrent = re.findall('btih\:(.+?)&', self.torrentUrl)[0]
            numberfiles = []
            i = -1
            for x in files:
                i += 1
                numberfiles.append(i)
            if lists not in [False, None]:
                for each in lists:
                    hashString = each.get('hashString')
                    if hashString.lower() == hashtorrent.lower():
                        showMessage('Transmission', 'Torrent deja in seed!', forced=True)
                        log('torrent exists in transmission, getting id')
                        tid = each.get('id')
                        wanted = each.get('wanted')
                        break
                if tid:
                    try:
                        if str(wanted[int(self.contentidforseed)]) == '0':
                            Download().set_wanted(tid, self.contentidforseed)
                            log('torrent existing added to seed')
                            showMessage('Transmission', 'Fișier adăugat la seed!', forced=True)
                    except BaseException as e:
                        log(e)
                        pass
                else:
                    host_ip = get_ip()
                    import base64
                    setip = Download().get_torrent_client().get('host')
                    localhosts = ['127.0.0.1', '0.0.0.0', host_ip]
                    if not setip in localhosts:
                        if not re.match("^magnet\:.+$", fileforseed):
                            with open(fileforseed, 'rb') as binary_file:
                                binary_file_data = binary_file.read()
                                base64_encoded_data = base64.b64encode(binary_file_data)
                            fileforseed = base64_encoded_data
                            Download().add(fileforseed, mrgetset('torrent_dir'), numberfiles, [int(self.contentidforseed)])
                        else:
                            fileforseed = base64.b64encode(fileforseed)
                            Download().add(fileforseed, mrgetset('torrent_dir'), numberfiles, [int(self.contentidforseed)])
                    else:
                        Download().addnew_url(fileforseed, self.userStorageDirectory, numberfiles, [int(self.contentidforseed)])
                    showMessage('Transmission', 'Adăugat la seed!', forced=True)
        if self.seedingtorrenter:
            exec_str = 'RunPlugin(%s)' % \
                    ('%s?action=%s&url=%s&storage=%s&ind=%s') % \
                    (sys.argv[0], 'downloadLibtorrent', urllib.quote_plus(fileforseed),
                        urllib.quote_plus(self.userStorageDirectory), str(self.contentidforseed))
            xbmc.executebuiltin(exec_str)
        if self.seedingmrsp:
            showMessage('MRSP', 'Torrent păstrat la seed!', forced=True)
            
    
    def get_ids(self):
        contentList = []
        try:
            if not self.files:
                iterator = 0
                while not self.files and not xbmc.Monitor().abortRequested() and iterator < 100:
                    files = self.engine.list()
                    xbmc.sleep(300)
                    iterator += 1
                fileslist = []
                for fb in self.files:
                    fburl = fb.url
                    if s.role == 'client' and (not s.mrsprole):
                        fburl = fb.url.replace('0.0.0.0', s.remote_host)
                    stringdata = {"title": ensure_str(fb.name), "size": fb.size, "ind": fb.index, 'save_path': ensure_str(fb.save_path), 'file_url': fburl}
                    fileslist.append(stringdata)
                self.files = fileslist
            for fs in self.files:
                contentList.append((fs.get('title'), str(fs.get('ind'))))
            contentList = sorted(contentList, key=lambda x: x[0])
            return get_ids_video(contentList)
        except: 
            return None
    
    def sleepp(self,time):
        while time > 0 and not xbmc.Monitor().abortRequested():
            xbmc.sleep(min(100, time))
            time = time - 100
    
    def idleForPlayback(self):
        for i in range(0, 400):
            if xbmc.getCondVisibility('Window.IsActive(busydialog)') == 1:
                self.sleepp(100)
            else:
                xbmc.executebuiltin('Dialog.Close(all,true)')
                break
    
    def md5(self, string):
        hasher = hashlib.md5()
        try:
            hasher.update(string)
        except:
            hasher.update(string.encode('utf-8', 'ignore'))
        return hasher.hexdigest()
    
    def onPlayBackStarted(self):
        try:
            p_tmdb = getattr(self, '_playback_tmdb', None) or self.mrget('tmdb_id')
            p_imdb = getattr(self, '_playback_imdb', None) or self.mrget('imdb_id')
            
            if p_tmdb or p_imdb:
                xbmc.sleep(300)
                
                # Re-setăm Window Properties (pentru siguranță)
                home_window = xbmcgui.Window(10000)
                
                if p_tmdb and str(p_tmdb) != 'None':
                    home_window.setProperty('TMDb_ID', str(p_tmdb))
                    home_window.setProperty('tmdb_id', str(p_tmdb))
                    home_window.setProperty('tmdb', str(p_tmdb))
                    home_window.setProperty('VideoPlayer.TMDb', str(p_tmdb))
                
                if p_imdb and str(p_imdb) != 'None':
                    home_window.setProperty('IMDb_ID', str(p_imdb))
                    home_window.setProperty('imdb_id', str(p_imdb))
                    home_window.setProperty('imdb', str(p_imdb))
                    home_window.setProperty('VideoPlayer.IMDb', str(p_imdb))
                    home_window.setProperty('VideoPlayer.IMDBNumber', str(p_imdb))
                
                # Încercăm și pe VideoInfoTag
                try:
                    tag = self.getVideoInfoTag()
                    uids = {}
                    if p_tmdb: uids['tmdb'] = str(p_tmdb)
                    if p_imdb: uids['imdb'] = str(p_imdb)
                    if uids:
                        tag.setUniqueIDs(uids)
                        if p_imdb: tag.setIMDBNumber(str(p_imdb))
                except:
                    pass
                
                log('[MRSP-EVENT] onPlayBackStarted: IDs setate - TMDb: %s, IMDb: %s' % (p_tmdb, p_imdb))
        except Exception as e:
            log('[MRSP-EVENT] Eroare: %s' % str(e))

        for f in self.on_playback_started:
            f()
        self.idleForPlayback()

    def onPlayBackResumed(self):
        for f in self.on_playback_resumed:
            f()
        self.onPlayBackStarted()

    def onPlayBackPaused(self):
        for f in self.on_playback_paused:
            f()
        #log('[onPlayBackPaused]: '+(str(("video", "pause", self.display_name))))

    def onPlayBackEnded(self):
        # Curățăm și când filmul se termină normal
        try:
            home_window = xbmcgui.Window(10000)
            for prop in ['TMDb_ID', 'tmdb_id', 'tmdb', 'VideoPlayer.TMDb',
                         'IMDb_ID', 'imdb_id', 'imdb', 'VideoPlayer.IMDb', 
                         'VideoPlayer.IMDBNumber']:
                home_window.clearProperty(prop)
            log('[MRSP-PLAYER] Window Properties curățate la end')
        except:
            pass

    def onPlayBackStopped(self):
        for f in self.on_playback_stopped:
            f()
        
        # =====================================================================
        # FIX: Curățăm Window Properties la oprirea redării
        # =====================================================================
        try:
            home_window = xbmcgui.Window(10000)
            for prop in ['TMDb_ID', 'tmdb_id', 'tmdb', 'VideoPlayer.TMDb',
                         'IMDb_ID', 'imdb_id', 'imdb', 'VideoPlayer.IMDb', 
                         'VideoPlayer.IMDBNumber']:
                home_window.clearProperty(prop)
            log('[MRSP-PLAYER] Window Properties curățate la stop')
        except:
            pass
        # =====================================================================
        
        self.stop()
    
    @contextmanager
    def attach(self, callback, *events):
        for event in events:
            event.append(callback)
        yield
        for event in events:
            event.remove(callback)

    def _get_status_lines(self, f):
        out = []
        orig_name = ensure_str(self.display_name)
        try: new_name = ensure_str(os.path.basename(f.name))
        except: new_name = ''
        out.append(ensure_str(self.display_name))
        if (orig_name != new_name):
            try: out.append("Next: %s" % ensure_str(os.path.basename(f.name)))
            except: out.append("Waiting for next name")
        try: out.append("%.2f%% %s/%s %s" % (f.progress * 100, self.f_b(f.download / 1024), self.f_b(f.size / 1024), STATE_STRS[f.state]))
        except: out.append("waiting for download data info")
        try: out.append("D:%s/s U:%s/s S:%d/%d P:%d/%d" % (self.f_b(f.download_rate),
                                                    self.f_b(f.upload_rate),
                                                    f.num_seeds,
                                                    f.total_seeds,
                                                    f.num_peers,
                                                    f.total_peers))
        except: out.append("waiting for peers data")
        return out
    

class OverlayText(object):
    def __init__(self, w, h, *args, **kwargs):
        self.window = xbmcgui.Window(WINDOW_FULLSCREEN_VIDEO)
        viewport_w, viewport_h = self._get_skin_resolution()
        # Adjust size based on viewport, we are using 1080p coordinates
        h = int(h * viewport_h / VIEWPORT_HEIGHT)
        if mrgetset('pauseinfo') == '0':
            w = int(viewport_w -20)
            x = 10 
            y = 10
        else:
            w = int(w * viewport_w / VIEWPORT_WIDTH)
            x = int(round((viewport_w - w)/2)) #orizontal
            y = int(round((viewport_h - h)/2)) #vertical
        self._shown = False
        self._text = ""
        self._label = xbmcgui.ControlLabel(x, y, w, h, self._text, *args, **kwargs)
        self._background = xbmcgui.ControlImage(x, y, w, h, os.path.join(RESOURCES_PATH, "media", "black.png"))
        self._background.setColorDiffuse("0xD0000000")

    def show(self):
        if not self._shown:
            self.window.addControls([self._background, self._label])
            self._shown = True
            self._background.setColorDiffuse("0xD0000000")

    def hide(self):
        if self._shown:
            self._shown = False
            self.window.removeControls([self._background, self._label])
            self._background.setColorDiffuse("0xFF000000")

    def close(self):
        self.hide()

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, text):
        self._text = text
        if self._shown:
            self._label.setLabel(self._text)

    # This is so hackish it hurts.
    def _get_skin_resolution(self):
        import xml.etree.ElementTree as ET

        if py3: skin_path = xbmcvfs.translatePath("special://skin/")
        else: skin_path = xbmc.translatePath("special://skin/")
        tree = ET.parse(os.path.join(skin_path, "addon.xml"))
        res = None
        for element in tree.findall("./extension/res"):
            if element.attrib["default"] == 'true':
                res = element
                break
        if res is None: res = tree.findall("./extension/res")[0]
        return int(res.attrib["width"]), int(res.attrib["height"])
    
class CustEngine(Engine):
    
    SUBTITLES_FORMATS = ['.aqt', '.gsub', '.jss', '.sub', '.ttxt', '.pjs', '.psb', '.rt', '.smi', '.stl',
                         '.ssf', '.srt', '.ssa', '.ass', '.usf', '.idx']
    
    t = True
    
    def __init__(self, host=None, port=None, combined=None):
        self.bind_host = host 
        self.bind_port = port
        self.combined = combined

    def list(self, media_types=None, timeout=10):
        files = self._request('ls', timeout).json()['files']
        if files:
            res = [FileStatus(index=index, media_type=self._detect_media_type(f['name']), **f)
                   for index, f in enumerate(files)]
            if media_types is not None:
                res = filter(lambda fs: fs.media_type in media_types, res)
            return res
        
    def status(self, timeout=10):
        status = self._request('status', timeout).json()
        status = SessionStatus(**status)
        return status

    def file_status(self, file_index, timeout=10):
        res = self.list(timeout=timeout)
        if res:
            try:
                return next((f for f in res if f.index == file_index))
            except StopIteration:
                raise Error("Requested file index (%d) is invalid" % file_index, Error.INVALID_FILE_INDEX,
                            file_index=file_index)
            
    def file_info(self, timeout=10):
        filex = self._request('lsfile', timeout).json()['file'][0]
        res = FileInfo(**filex)
        return res

    def peers(self, timeout=10):
        peers = self._request('peers', timeout).json()['peers']
        if peers:
            return [PeerInfo(**p) for p in peers]
    
    def stop(self):
        self._request('stop')
    
    def resume(self):
        self._request('resume')

    def priority(self, index, priority):
        return self._request('priority?index=%s&priority=%s' % (index, priority))

    def _request(self, cmd, timeout=None):
        if self.combined:
            return requests.get('http://%s/%s' % (self.combined, cmd))
        else:
            return requests.get('http://%s:%s/%s' % (self.bind_host, self.bind_port, cmd))
    
    def _detect_media_type(self, name):
        ext = os.path.splitext(name)[1]
        if ext in self.SUBTITLES_FORMATS:
            return 'subtitle'
        else:
            mime_type = mimetypes.guess_type(name)[0]
            if not mime_type:
                return 'unknown'
            mime_type = mime_type.split("/")[0]
            if mime_type == 'audio':
                return 'audio'
            elif mime_type == 'video':
                return 'video'
            else:
                return 'unknown'
    
