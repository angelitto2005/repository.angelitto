# -*- coding: utf-8 -*-
import xbmc
import xbmcgui
import xbmcaddon
import json
import re
from resources.functions import log,__settings__,quote,unquot,showMessage
from resources import trakt

aid = 'plugin.video.romanianpack'
addon_settings = xbmcaddon.Addon(id=aid)

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

def execute_jsonrpc(method, params):
    try:
        request = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": 1
        }
        response = xbmc.executeJSONRPC(json.dumps(request))
        return json.loads(response)
    except Exception as e:
        log("JSONRPC Error: %s" % str(e))
        return None

def get_dbid_from_tmdb_info(playback_info):
    """
    Rezolvă DBID-ul intern Kodi pe baza informațiilor primite.
    """
    try:
        # Cazul 1: Am primit direct DBID-ul (de la meniul contextual)
        if 'kodi_dbid' in playback_info and 'kodi_dbtype' in playback_info:
            log('[MRSP-SERVICE] DBID primit direct: dbtype=%s, dbid=%s' % (playback_info['kodi_dbtype'], playback_info['kodi_dbid']))
            return playback_info['kodi_dbtype'], playback_info['kodi_dbid']
        
        # Cazul 2: Trebuie să rezolvăm DBID-ul (de la TMDb Helper)
        mediatype = playback_info.get('mediatype')
        
        if mediatype == 'movie':
            tmdb_id = int(playback_info.get('tmdb_id'))
            json_req = {
                "jsonrpc": "2.0", "id": 1, "method": "VideoLibrary.GetMovies",
                "params": {"properties": ["title"], "filter": {"field": "tmdb_id", "operator": "is", "value": str(tmdb_id)}}
            }
            response = xbmc.executeJSONRPC(json.dumps(json_req))
            data = json.loads(response)
            if data.get('result', {}).get('movies'):
                movie_id = data['result']['movies'][0]['movieid']
                log('[MRSP-SERVICE] DBID Rezolvat pentru film: %s' % movie_id)
                return 'movie', movie_id
                
        elif mediatype == 'episode':
            showname = playback_info.get('showname')
            season_num = int(playback_info.get('season'))
            episode_num = int(playback_info.get('episode'))
            
            if not showname:
                log('[MRSP-SERVICE] Numele serialului (showname) lipsește din playback_info.')
                return None, None

            log('[MRSP-SERVICE] Căutare TV Show în bibliotecă după titlu: "%s"' % showname)
            json_req_show = {
                "jsonrpc": "2.0", "id": 1, "method": "VideoLibrary.GetTVShows",
                "params": {"properties": ["title"], "filter": {"field": "title", "operator": "is", "value": showname}}
            }
            response_show = xbmc.executeJSONRPC(json.dumps(json_req_show))
            data_show = json.loads(response_show)
            
            if data_show.get('result', {}).get('tvshows'):
                tvshow_id = data_show['result']['tvshows'][0]['tvshowid']
                log('[MRSP-SERVICE] TV Show găsit! ID intern (tvshowid): %s' % tvshow_id)
                
                json_req_ep = {
                    "jsonrpc": "2.0", "id": 1, "method": "VideoLibrary.GetEpisodes",
                    "params": {"tvshowid": tvshow_id, "season": season_num, "properties": ["episode", "playcount"], "filter": {"field": "episode", "operator": "is", "value": str(episode_num)}}
                }
                response_ep = xbmc.executeJSONRPC(json.dumps(json_req_ep))
                data_ep = json.loads(response_ep)

                if data_ep.get('result', {}).get('episodes'):
                    episode_id = data_ep['result']['episodes'][0]['episodeid']
                    log('[MRSP-SERVICE] Episod găsit! ID intern (episodeid): %s' % episode_id)
                    return 'episode', episode_id
                else:
                    log('[MRSP-SERVICE] EROARE: Serialul a fost găsit, dar episodul S%sE%s nu există în bibliotecă pentru acest serial.' % (season_num, episode_num))
            else:
                log('[MRSP-SERVICE] EROARE: Niciun serial cu numele "%s" nu a fost găsit în biblioteca Kodi.' % showname)

    except Exception as e:
        log('[MRSP-SERVICE] EROARE CRITICĂ la rezolvarea DBID prin JSON-RPC: %s' % str(e))
        
    return None, None

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
        # Asteapta redarea reala, ignorand fisierele temporare
        while self.isPlaying() and not self.isPlayingVideo() and not xbmc.Monitor().abortRequested():
            xbmc.sleep(250)
        
        if not self.isPlayingVideo():
            return
        
        log("[MRSP-SERVICE] onPlayBackStarted: Redare video detectată, se continuă execuția.")
        
        # ===== START MODIFICARE: Logica simplificata de preluare context =====
        self.detalii = {}
        try:
            window = xbmcgui.Window(10000)
            
            # Cautam proprietatea UNICA setata de searchSites
            playback_info_str = window.getProperty('mrsp.playback.info')
            
            if playback_info_str:
                log('[MRSP-SERVICE] Context de redare gasit in proprietatea mrsp.playback.info: %s' % playback_info_str)
                import ast
                self.detalii = ast.literal_eval(playback_info_str)
                # Curatam imediat proprietatea pentru a nu afecta redarile viitoare
                window.clearProperty('mrsp.playback.info')
                log('[MRSP-SERVICE] Proprietatea mrsp.playback.info a fost stearsa.')
            else:
                log('[MRSP-SERVICE] AVERTISMENT: Niciun context de redare (mrsp.playback.info) nu a fost gasit.')

        except Exception as e:
            log('[MRSP-SERVICE] Eroare critica la citirea contextului: %s' % str(e))
        # ===== SFÂRȘIT MODIFICARE =====

        self.enable_autosub = xbmcaddon.Addon(id=aid).getSetting('enable_autosub') == 'true'
        if self.run and self.enable_autosub:
            specs_lang = []
            if self.isPlayingVideo():
                if xbmc.getCondVisibility('System.HasAddon(service.autosubs)'):
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
                    if value: self.videolabels[i] = value
                self.videolabels['Duration'] = self.totalTime
                for i in playerlabels:
                    value = xbmc.getInfoLabel('Player.%s' % (i))
                    if value: self.playerlabels[i] = value
                
                # Combinam datele: `self.detalii` (din proprietatea unica) are prioritate
                self.data = self.detalii.copy() if self.detalii else {}
                
                # Rezolvam DBID-ul folosind informatiile finale
                dbtype, dbid = get_dbid_from_tmdb_info(self.data)
                if dbtype and dbid:
                    self.data['kodi_dbtype'] = dbtype
                    self.data['kodi_dbid'] = dbid
                    log('[MRSP-SERVICE] Context final pentru marcare: dbtype=%s, dbid=%s' % (dbtype, dbid))
                else:
                    log('[MRSP-SERVICE] AVERTISMENT: Nu s-a putut determina un DBID pentru marcare din contextul final.')
            
            if not self.getPlayingFile().find("pvr://") > -1:
                self.mon = True
                self.looptime()
            else:
                self.mon = False

    def looptime(self):
        while self.isPlayingVideo():
            self.currentTime = self.getTime()
            xbmc.sleep(2000)
    
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
    
    def markwatch(self):
        if self.currentTime > 0 and self.totalTime > 1000 and self.mon:
            log('[MRSP-MARKWATCH] Începe markwatch - currentTime=%s, totalTime=%s' % (self.currentTime, self.totalTime))
            
            total = (float(self.currentTime) / float(self.totalTime)) * 100
            totaltime = float(self.totalTime)
            elapsed = float(self.currentTime)
            
            log('[MRSP-MARKWATCH] Procent vizionat: %.2f%%' % total)

            try:
                watched_percent = int(addon_settings.getSetting('watched_percent'))
            except:
                watched_percent = 80 # Valoare implicită (80%) în caz de eroare
            
            # ===== START MODIFICARE: Logică simplificată de marcare =====
            if total > 1: # Un prag mic pentru a evita salvări accidentale
                
                # --- Logica pentru Trakt (rămâne neschimbată) ---
                if total > 80:
                    try:
                        if (addon_settings.getSetting('activateoutsidetrakt') == 'false' and self.detalii) or (addon_settings.getSetting('activateoutsidetrakt') == 'true'):
                            if addon_settings.getSetting('autotraktwatched') == 'true' and addon_settings.getSetting('trakt.user'):
                                info = trakt.getDataforTrakt(self.data)
                                info['progress'] = total
                                complete = trakt.getTraktScrobble('stop', info)
                                if complete and complete.get('action') == 'scrobble':
                                    if complete.get('movie'):
                                        showMessage("MRSP", "%s marcat vizionat in Trakt" % (complete.get('movie').get('title')), 3000)
                                    elif complete.get('episode'):
                                        showMessage("MRSP", "%s S%sE%s marcat vizionat in Trakt" % (complete.get('show').get('title'), str(complete.get('episode').get('season')), str(complete.get('episode').get('number'))), 3000)
                    except Exception as e:
                        log('Eroare la scrobble Trakt: %s' % str(e))

                # --- Logica pentru salvarea stării în addon ---
                try:
                    from resources.Core import Core
                    params_to_save = {}
                    
                    # Cazul 1: Redare inițiată prin addon (intern, Meniu Contextual, TMDb Helper)
                    # Acum, `self.detalii` va fi populat corect în toate aceste scenarii.
                    if self.detalii:
                        log('[MRSP-MARKWATCH] Cazul 1 Addon/Extern: Se salvează pe baza detaliilor primite.')
                        landing = self.detalii.get('landing') or self.detalii.get('link') or 'kodi_library_item://%s/%s' % (self.data.get('kodi_dbtype'), self.data.get('kodi_dbid'))
                        params_to_save = {'watched': 'save', 'watchedlink': landing, 'detalii': quote(str(self.detalii)), 'norefresh': '1'}

                    # Cazul 2: Redare din afara addon-ului (fișier local, etc.)
                    elif self.data and addon_settings.getSetting('enableoutsidewatched') == 'true':
                        log('[MRSP-MARKWATCH] Cazul 2 Local/PVR: Se salvează pe baza redării externe.')
                        detalii_externe = {'info': self.videolabels, 'link': self.playerlabels.get('Filenameandpath'), 'switch': 'playoutside', 'nume': (self.videolabels.get('Title') or '')}
                        params_to_save = {'watched': 'save', 'watchedlink': self.playerlabels.get('Filenameandpath'), 'norefresh': '1', 'detalii': detalii_externe}

                    if params_to_save:
                        # Dacă procentul vizionat depășește pragul, se marchează ca vizionat.
                        # Altfel, se salvează punctul de reluare.
                        if total <= watched_percent:
                            log('[MRSP-MARKWATCH] Pragul de %s%% NU a fost atins. Se salvează punctul de reluare.' % watched_percent)
                            params_to_save['elapsed'] = elapsed
                            params_to_save['total'] = totaltime
                        else:
                            log('[MRSP-MARKWATCH] Pragul de %s%% atins. Se marchează ca vizionat complet.' % watched_percent)

                        # Adăugăm datele Kodi (dacă există) pentru a fi salvate în baza de date
                        # și pentru a fi folosite la marcarea în biblioteca Kodi.
                        if self.data.get('kodi_dbtype'):
                            params_to_save['kodi_dbtype'] = self.data.get('kodi_dbtype')
                            params_to_save['kodi_dbid'] = self.data.get('kodi_dbid')
                            params_to_save['kodi_path'] = self.data.get('kodi_path') 
                        
                        Core().watched(params_to_save)

                except Exception as e:
                    log("MRSP service mark watched error: %s" % str(e))
            # ===== SFÂRȘIT MODIFICARE =====

        self.data = {}
        self.detalii = {}
        self.videolabels = {}
        self.playerlabels = {}
    
    def isExcluded(self,movieFullPath):
        log("<<<<< EXECUTING MODIFIED isExcluded FUNCTION v6 (FINAL) >>>>>")
        log("isExcluded: Verific calea: -----> %s <-----" % str(movieFullPath))

        if not movieFullPath:
            log("isExcluded(): Calea este goala. Se exclude.")
            return False

        # --- MODIFICAREA CHEIE ESTE AICI ---
        # Cautam "youtube" in loc de "plugin.video.youtube"
        if "youtube" in str(movieFullPath).lower():
            log("isExcluded(): Cale YouTube DETECTATA. Se exclude.")
            return False

        if (movieFullPath.find("pvr://") > -1) and xbmcaddon.Addon(id=aid).getSetting('ExcludeLiveTV') == 'true':
            log("isExcluded(): Video is playing via Live TV, which is currently set as excluded location.")
            return False

        if (movieFullPath.find("http://") > --1) and xbmcaddon.Addon(id=aid).getSetting('ExcludeHTTP') == 'true':
            log("isExcluded(): Video is playing via HTTP source, which is currently set as excluded location.")
            return False
        
        try:
            ExcludeAddon = xbmcaddon.Addon(id=aid).getSetting('ExcludeAddon')
            if ExcludeAddon and xbmcaddon.Addon(id=aid).getSetting('ExcludeAddonOption') == 'true':
                if (movieFullPath.find(ExcludeAddon) > -1):
                    log("isExcluded(): Video is playing via an addon which is currently set as excluded location.")
                    return False
        except: 
            pass

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

        log("isExcluded(): Nicio regula de excludere nu s-a potrivit. NU se exclude.")
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
