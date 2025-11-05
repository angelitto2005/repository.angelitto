# -*- coding: utf-8 -*-
import xbmc
import xbmcgui
import xbmcaddon
import re
from resources.functions import log,__settings__,quote,unquot,showMessage
from resources import trakt

aid = 'plugin.video.romanianpack'

videolabels = ['Title', #VideoPlayer
            'TVShowTitle',
            'Season',
            'Episode',
            'Genre',
            'Director',
            'Country',
            'Year',
            'Rating',
            'UserRating',
            'Votes',
            'mpaa',
            'IMDBNumber',
            'EpisodeName',
            'Album',
            'Studio',
            'Writer',
            'Tagline',
            'PlotOutline',
            'Plot']
playerlabels = ['Filename',#Player
                'FolderPath',
                'Filenameandpath']


class mrspPlayer(xbmc.Player):

    def __init__(self, *args, **kwargs):
        xbmc.Player.__init__(self)
        self.data = {}
        self.detalii = {}
        self.totalTime = 0
        self.currentTime = 0
        self.run = True
        self.wait = False
        self.videolabels = {}
        self.playerlabels = {}
        self.mon = False
    
    def onPlayBackStarted(self):
        self.detalii = {}
        self.enable_autosub = xbmcaddon.Addon(id=aid).getSetting('enable_autosub') == 'true'
        if self.run and self.enable_autosub:
            specs_lang = []
            while (not self.isPlayingVideo()) and (not xbmc.Monitor().abortRequested()):
                xbmc.sleep(500)
            if self.isPlayingVideo():
                if xbmc.getCondVisibility('System.HasAddon(service.autosubs)'):
                    #if xbmc.getCondVisibility('System.AddonIsEnabeled(service.autosubs)'):
                    #xbmcaddon.Addon('plugin.video.romanianpack').setSetting('enable_autosub',value='false')
                    xbmc.sleep(2500)
                    if xbmc.getCondVisibility('Player.Paused') == True:
                        self.wait = True
                while self.wait == True:
                    xbmc.sleep(500)
                check_for_specific = xbmcaddon.Addon(id=aid).getSetting('check_for_specific') == 'true'
                if xbmcaddon.Addon(id=aid).getSetting('check_for_external') == 'true':
                    specs_lang.append('(External)')
                specific_languagea = xbmcaddon.Addon(id=aid).getSetting('selected_languagea')
                specific_languagea = xbmc.convertLanguage(specific_languagea, xbmc.ISO_639_2)
                specs_lang.append(specific_languagea)
                check_for_specificb = xbmcaddon.Addon(id=aid).getSetting('check_for_specificb') == 'true'
                if check_for_specificb:
                    specific_languageb = xbmcaddon.Addon(id=aid).getSetting('selected_languageb')
                    specific_languageb = xbmc.convertLanguage(specific_languageb, xbmc.ISO_639_2)
                    specs_lang.append(specific_languageb)
                ExcludeTime = int(xbmcaddon.Addon(id=aid).getSetting('ExcludeTime'))*60
                ignore_words = xbmcaddon.Addon(id=aid).getSetting('ignore_words').split(',')
                movieFullPath = self.getPlayingFile()
                xbmc.sleep(1000)
                availableLangs = self.getAvailableSubtitleStreams()
                totalTime = self.getTotalTime()

            if (self.isPlayingVideo() and totalTime > ExcludeTime and ((not xbmc.getCondVisibility("VideoPlayer.HasSubtitles")) or (check_for_specific and not any(item in specs_lang for item in availableLangs))) and all(movieFullPath.find (v) <= -1 for v in ignore_words) and (self.isExcluded(movieFullPath)) ):
                self.run = False
                xbmc.sleep(1000)
                xbmc.executebuiltin('ActivateWindow(SubtitleSearch)')
            else:
                self.run = False
        else:
            while (not self.isPlayingVideo()) and (not xbmc.Monitor().abortRequested()):
                xbmc.sleep(500)
        if self.isPlayingVideo():
            if (not self.data) and (not self.getPlayingFile().find("pvr://") > -1):
                self.totalTime = self.getTotalTime()
                self.data = {}
                self.videolabels = {}
                self.playerlabels = {}
                for i in videolabels:
                    value = xbmc.getInfoLabel('VideoPlayer.%s' % (i))
                    if value:
                        self.videolabels[i] = value
                self.videolabels['Duration'] = self.totalTime
                for i in playerlabels:
                    value = xbmc.getInfoLabel('Player.%s' % (i))
                    if value:
                        self.playerlabels[i] = value
                get = xbmc.getInfoLabel
                fisier = get('Player.Filename')
                path = get('Player.FolderPath')
                fullpath = get('Player.Filenameandpath')
                title = get('VideoPlayer.Title')
                imdb = get('VideoPlayer.IMDBNumber')
                season = get('VideoPlayer.Season')
                episode = get('VideoPlayer.Episode')
                tvshow = get('VideoPlayer.TVShowTitle')
                year = get('VideoPlayer.Year')
                self.data = {'info': {'Path': path, 'File': fisier, 'Title': title, 'imdb': imdb, 'Season': season, 'Episode': episode, 'TVShowTitle': tvshow, 'Year': year, 'FullPath': fullpath}} if (path or title) else {}
                if self.data:
                    self.detalii = self.getVideoInfoTag().getCast()
                #else:
                    #log('MRSP Service no data')
            if not self.getPlayingFile().find("pvr://") > -1:
                self.mon = True
                self.looptime()
            else: self.mon = False
    
    def onPlayBackEnded(self):
        self.wait = False
        self.run = True
        if self.data: self.markwatch()
        
    def onPlayBackResumed(self):
        self.wait = False

    def onPlayBackStopped(self):
        self.wait = False
        self.run = True
        if self.data: self.markwatch()
    
    def onPlayBackError(self):
        self.wait = False
        self.run = True
        if self.data: self.markwatch()
        
    def looptime(self):
        while self.isPlayingVideo():
            self.currentTime = self.getTime()
            xbmc.sleep(2000)
            
    def markwatch(self):
        if self.currentTime > 0 and self.totalTime > 1000 and self.mon:
            #log('MRSP SErvice started markwatch')
            total = (float(self.currentTime)/float(self.totalTime))*100
            totaltime = float(self.totalTime)
            elapsed = float(self.currentTime)
            try: self.detalii = eval(str(self.detalii))
            except: pass
            landing = None
            if total > 10:
                #log('MRSP SErvice total bigger than 10')
                if total > 80:
                    #log('MRSP SErvice total bigger than 80')
                    try:
                        if (xbmcaddon.Addon(id=aid).getSetting('activateoutsidetrakt') == 'false' and isinstance(self.detalii,dict)) or (xbmcaddon.Addon(id=aid).getSetting('activateoutsidetrakt') == 'true'):
                            #log('MRSP Service starting trakt watch')
                            if xbmcaddon.Addon(id=aid).getSetting('autotraktwatched') == 'true' and xbmcaddon.Addon(id=aid).getSetting('trakt.user'):
                                trakton = '1'
                            else: trakton = '0'
                            #log('MRSP Service trakton: %s' % trakton)
                            if trakton == '1':
                                action = 'stop'
                                try: info = trakt.getDataforTrakt(self.data)
                                except: info = {}
                                info['progress'] = total
                                complete = trakt.getTraktScrobble(action, info)
                                #log('MRSP Service complete')
                                #log(complete)
                                if complete:
                                    if str(complete.get('action')) == str('scrobble'): 
                                        #log('is scrobble')
                                        if complete.get('movie'):
                                            showMessage("MRSP", "%s marcat vizionat in Trakt" % (complete.get('movie').get('title')), 3000)
                                        if complete.get('episode'):
                                            showMessage("MRSP", "%s S%sE%s marcat vizionat in Trakt" % (complete.get('show').get('title'), str(complete.get('episode').get('season')), str(complete.get('episode').get('number'))), 3000)
                                    else:
                                        #log('not scrobble')
                                        if complete.get('watched_at') and (complete.get('movie') or complete.get('episode')):
                                            #log('is watched_at')
                                            text = "%s marcat vizionat in Trakt" % (complete.get('movie').get('title')  if complete.get('movie') else complete.get('show').get('title'))
                                            showMessage("MRSP", text, 3000)
                    except BaseException as e:
                        log('MRSP service total bigger then 80, error')
                        log(e)
                        pass
                try:
                    from resources.Core import Core
                    if self.detalii and isinstance(self.detalii,dict):
                        try:
                            if self.playerlabels.get('Filename'):
                                fileplayed = 'Played file: %s \n' % (unquot(self.playerlabels.get('Filename')))
                                cleanplot = re.sub(r'(Played file:.+?\.(?:\w){2,3}\s\n)', '', self.detalii.get('info').get('Plot'))
                                #re.sub('(Played file:.+?\.(?:\w){2,3})', '', self.detalii.get('info').get('Plot').replace(fileplayed, ''))
                                self.detalii['info']['Plot'] = '%s%s' % (fileplayed , cleanplot)
                        except: pass
                        landing = self.detalii.get('landing') or self.detalii.get('link')
                        if landing:
                            if not self.detalii.get('torrent'):
                                self.detalii.update({'link': landing, 'switch' : self.detalii.get('switch')})
                            params = {'watched' : 'save', 'watchedlink' : landing, 'detalii': quote(str(self.detalii)), 'norefresh' : '1'}
                            if total <= 80:
                                params['elapsed'] = elapsed
                                params['total'] = totaltime
                            Core().watched(params)
                    else:
                        if xbmcaddon.Addon(id=aid).getSetting('enableoutsidewatched') == 'true':
                            try:
                                self.videolabels['Plot'] = 'Played file: %s \n%s' % (unquot(self.playerlabels.get('Filename')),self.videolabels.get('Plot'))
                            except: pass
                            detalii = {'info': self.videolabels, 'link': self.playerlabels.get('Filenameandpath'), 'switch': 'playoutside', 'nume': (self.videolabels.get('Title') or '')}
                            params = {'watched' : 'save', 'watchedlink' : self.playerlabels.get('Filenameandpath'), 'norefresh' : '1', 'detalii' : detalii, 'nodetails': '1'}
                            if total <= 80:
                                params['elapsed'] = elapsed
                                params['total'] = totaltime
                            Core().watched(params)
                except: # BaseException as e:
                    #log('MRSP service bigger then 10, error')
                    #log(e)
                    pass
            #else:
                #log('MRSP Service total lower than 10: %s' % total)
        self.data = {}
        self.videolabels = {}
        self.playerlabels = {}
    
    def isExcluded(self,movieFullPath):
        if not movieFullPath:
            log("isExcluded(): No movieFullPath")
            return False
        if (movieFullPath.find("pvr://") > -1) and xbmcaddon.Addon(id=aid).getSetting('ExcludeLiveTV') == 'true':
            log("isExcluded(): Video is playing via Live TV, which is currently set as excluded location.")
            return False

        if (movieFullPath.find("http://") > -1) and xbmcaddon.Addon(id=aid).getSetting('ExcludeHTTP') == 'true':
            log("isExcluded(): Video is playing via HTTP source, which is currently set as excluded location.")
            return False
        
        try:
            playingaddon = self.getVideoInfoTag().getPath()
            ExcludeAddon = xbmcaddon.Addon(id=aid).getSetting('ExcludeAddon')
            if ExcludeAddon and xbmcaddon.Addon(id=aid).getSetting('ExcludeAddonOption') == 'true':
                if (playingaddon.find(ExcludeAddon) > -1):
                    log("isExcluded(): Video is playing via an addon which is currently set as excluded location.")
                    return False
        except: pass

        ExcludePath = xbmcaddon.Addon(id=aid).getSetting('ExcludePath')
        if ExcludePath and xbmcaddon.Addon(id=aid).getSetting('ExcludePathOption') == 'true':
            if (movieFullPath.find(ExcludePath) > -1):
                log("isExcluded(): Video is playing from '%s', which is currently set as excluded path 1." % ExcludePath)
                return False

        ExcludePath2 = xbmcaddon.Addon(id=aid).getSetting('ExcludePath2')
        if ExcludePath2 and xbmcaddon.Addon(id=aid).getSetting('ExcludePathOption2') == 'true':
            if (movieFullPath.find(ExcludePath2) > -1):
                log("isExcluded(): Video is playing from '%s', which is currently set as excluded path 2." % ExcludePath2)
                return False

        ExcludePath3 = xbmcaddon.Addon(id=aid).getSetting('ExcludePath3')
        if ExcludePath3 and xbmcaddon.Addon(id=aid).getSetting('ExcludePathOption3') == 'true':
            if (movieFullPath.find(ExcludePath3) > -1):
                log("isExcluded(): Video is playing from '%s', which is currently set as excluded path 3." % ExcludePath3)
                return False

        ExcludePath4 = xbmcaddon.Addon(id=aid).getSetting('ExcludePath4')
        if ExcludePath4 and xbmcaddon.Addon(id=aid).getSetting('ExcludePathOption4') == 'true':
            if (movieFullPath.find(ExcludePath4) > -1):
                log("isExcluded(): Video is playing from '%s', which is currently set as excluded path 4." % ExcludePath4)
                return False

        ExcludePath5 = xbmcaddon.Addon(id=aid).getSetting('ExcludePath5')
        if ExcludePath5 and xbmcaddon.Addon(id=aid).getSetting('ExcludePathOption5') == 'true':
            if (movieFullPath.find(ExcludePath5) > -1):
                log("isExcluded(): Video is playing from '%s', which is currently set as excluded path 5." % ExcludePath5)
                return False

        return True
  
def run():
    log('MRSP service started')
    startup_delay = 1
    if startup_delay:
        xbmc.sleep(startup_delay * 1000)

    Player = mrspPlayer()

    while not xbmc.Monitor().abortRequested():
        if xbmc.Monitor().waitForAbort():
            break
        xbmc.sleep(1000)

    # we are shutting down
    log("MRSP service shutting down.")

    # delete player/monitor
    del Player
