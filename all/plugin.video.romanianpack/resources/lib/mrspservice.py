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
        self.active_resume_id = None
    
    
    def onPlayBackStarted(self):
        # Asteapta redarea reala, ignorand fisierele temporare
        while self.isPlaying() and not self.isPlayingVideo() and not xbmc.Monitor().abortRequested():
            xbmc.sleep(250)
        
        if not self.isPlayingVideo():
            return
            
        try:
            playing_file = self.getPlayingFile()
            if 'dummy.mp4' in playing_file:
                return
        except: pass
        
        log("[MRSP-SERVICE] onPlayBackStarted: Redare video detectată, se continuă execuția.")
        
        self.detalii = {}
        self.active_resume_id = None
        try:
            window = xbmcgui.Window(10000)
            
            data_str = window.getProperty('mrsp.data')
            if data_str:
                try:
                    import ast
                    self.detalii = ast.literal_eval(data_str)
                except:
                    import json
                    try: self.detalii = json.loads(data_str)
                    except: pass
                log('[MRSP-SERVICE] Context citit cu succes din mrsp.data')
            
            playback_info_str = window.getProperty('mrsp.playback.info')
            if playback_info_str:
                import json
                try: pb_data = json.loads(playback_info_str)
                except: pb_data = {}
                
                if pb_data.get('mrsp_resume_id'):
                    self.detalii['mrsp_resume_id'] = pb_data['mrsp_resume_id']
                    self.active_resume_id = pb_data['mrsp_resume_id']
                    log('[MRSP-SERVICE] ID Resume actualizat si capturat la start: %s' % self.active_resume_id)
                if pb_data.get('season'): self.detalii['season'] = pb_data['season']
                if pb_data.get('episode'): self.detalii['episode'] = pb_data['episode']
                
                window.clearProperty('mrsp.playback.info')

            # ===== RESUME UNIVERSAL: Elementum + t2h (dupa ce playerul a pornit) =====
            check_resume = window.getProperty('mrsp.check_resume')
            log('[MRSP-RESUME-SVC] Verificare flag check_resume: "%s"' % check_resume)
            
            if check_resume == 'true':
                window.clearProperty('mrsp.check_resume')
                log('[MRSP-RESUME-SVC] Flag gasit! Incep procesarea resume...')
                try:
                    # Asteptam ca redarea sa se stabilizeze complet
                    for _wait in range(30):
                        if self.isPlayingVideo():
                            try:
                                if self.getTotalTime() > 0:
                                    log('[MRSP-RESUME-SVC] Player stabil dupa %d iteratii' % _wait)
                                    break
                            except: pass
                        xbmc.sleep(500)
                    
                    xbmc.sleep(1500)  # Extra stabilizare Elementum/t2h
                    
                    if self.isPlayingVideo():
                        # 1. Obtinem numele REAL al fisierului
                        playing_file = ''
                        try: playing_file = self.getPlayingFile()
                        except: pass
                        
                        pf_label = xbmc.getInfoLabel('Player.Filename') or ''
                        pf_full = xbmc.getInfoLabel('Player.Filenameandpath') or ''
                        all_sources = '%s|%s|%s' % (playing_file, pf_label, pf_full)
                        log('[MRSP-RESUME-SVC] Fisier real: %s' % all_sources[:200])
                        
                        # 2. Extragem IMDb/TMDb
                        pb_info = self.detalii.get('info', {}) if isinstance(self.detalii.get('info'), dict) else {}
                        t_id = pb_info.get('tmdb_id') or self.detalii.get('tmdb_id')
                        i_id = (pb_info.get('imdb_id') or pb_info.get('imdb') or 
                                pb_info.get('IMDBNumber') or self.detalii.get('imdb_id'))
                        log('[MRSP-RESUME-SVC] IDs: tmdb=%s, imdb=%s' % (t_id, i_id))
                        
                        # 3. Extragem S##E## din fisierul REAL
                        s_val, e_val = None, None
                        m_ep = re.search(r'(?i)S(\d+)[._ -]*E(\d+)', all_sources)
                        if m_ep:
                            s_val, e_val = m_ep.group(1), m_ep.group(2)
                            log('[MRSP-RESUME-SVC] Episod din fisier: S%sE%s' % (s_val, e_val))
                        if not s_val:
                            s_val = pb_info.get('Season') or pb_info.get('season') or self.detalii.get('season')
                        if not e_val:
                            e_val = pb_info.get('Episode') or pb_info.get('episode') or self.detalii.get('episode')
                        
                        # 4. Construim resume_id
                        base_val = ""
                        if i_id: base_val = "imdb_%s" % i_id
                        elif t_id: base_val = "tmdb_%s" % t_id
                        
                        resume_id = ""
                        if base_val:
                            try:
                                if s_val and e_val:
                                    resume_id = "%s_S%02dE%02d" % (base_val, int(s_val), int(e_val))
                                elif s_val:
                                    resume_id = "%s_S%02d_pack" % (base_val, int(s_val))
                                else:
                                    resume_id = "%s_movie" % base_val
                            except:
                                resume_id = "%s_movie" % base_val
                        
                        if not resume_id:
                            resume_id = self.active_resume_id or self.detalii.get('mrsp_resume_id', '')
                        
                        log('[MRSP-RESUME-SVC] Resume ID: %s' % resume_id)
                        
                        if resume_id:
                            self.active_resume_id = resume_id
                            if self.detalii:
                                self.detalii['mrsp_resume_id'] = resume_id
                            
                            # 5. Verificam DB
                            from resources.functions import get_resume_time
                            resume_time, total_time = get_resume_time(resume_id)
                            log('[MRSP-RESUME-SVC] DB: resume=%.1f, total=%.1f' % (resume_time, total_time))
                            
                            if resume_time > 0 and total_time > 0:
                                pct = (resume_time / total_time) * 100
                                if 1 < pct < 95:
                                    import datetime
                                    time_str = str(datetime.timedelta(seconds=int(resume_time)))
                                    log('[MRSP-RESUME-SVC] *** DIALOG: %s (%.1f%%) ***' % (time_str, pct))
                                    
                                    self.pause()
                                    xbmc.sleep(400)
                                    ret = xbmcgui.Dialog().contextmenu(
                                        ['Reluare de la %s' % time_str, 'De la început'])
                                    if ret == 0:
                                        self.seekTime(float(resume_time))
                                        xbmc.sleep(600)
                                        log('[MRSP-RESUME-SVC] Seek la %s' % time_str)
                                    if self.isPlayingVideo():
                                        self.pause()
                                else:
                                    log('[MRSP-RESUME-SVC] Procent %.1f%% in afara 1-95%%' % pct)
                            else:
                                log('[MRSP-RESUME-SVC] Nimic salvat pentru: %s' % resume_id)
                    else:
                        log('[MRSP-RESUME-SVC] Playerul nu reda video')
                except Exception as e:
                    log('[MRSP-RESUME-SVC] EROARE: %s' % str(e))
                    import traceback
                    log('[MRSP-RESUME-SVC] %s' % traceback.format_exc())
            # ===== SFARSIT RESUME UNIVERSAL =====

        except Exception as e:
            log('[MRSP-SERVICE] Eroare critica la citirea contextului: %s' % str(e))

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
                
                self.data = self.detalii.copy() if self.detalii else {}
                
                info_child = self.data.get('info', {})
                if isinstance(info_child, dict):
                    if not self.data.get('tmdb_id') and info_child.get('tmdb_id'): self.data['tmdb_id'] = info_child['tmdb_id']
                    if not self.data.get('imdb_id') and info_child.get('imdb_id'): self.data['imdb_id'] = info_child['imdb_id']
                    if not self.data.get('season') and info_child.get('Season'): self.data['season'] = info_child['Season']
                    if not self.data.get('episode') and info_child.get('Episode'): self.data['episode'] = info_child['Episode']
                    if not self.data.get('mediatype') and info_child.get('mediatype'): self.data['mediatype'] = info_child['mediatype']
                
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
        self._cleanup_properties()  # <--- LINIE NOUA

    def onPlayBackResumed(self):
        self.wait = False

    def onPlayBackStopped(self):
        self.wait = False
        self.run = True
        if self.data: self.markwatch()
        self._cleanup_properties()  # <--- LINIE NOUA
    
    # --- FUNCTIE NOUA DE CURATARE ---
    def _cleanup_properties(self):
        try:
            window = xbmcgui.Window(10000)
            props_to_clear = [
                'tmdb_id', 'TMDb_ID', 'tmdb', 'VideoPlayer.TMDb',
                'imdb_id', 'IMDb_ID', 'imdb', 'VideoPlayer.IMDb', 'VideoPlayer.IMDBNumber',
                'mrsp.tmdb_id', 'mrsp.imdb_id',
                'tmdbmovies.release_name',
                'mrsp.data', 'mrsp.playback.info',
                'mrsp.check_resume', 'mrsp.pending_seek', 'mrsp.pending_seek_total'   # <--- ADĂUGAT
            ]
            for prop in props_to_clear:
                window.clearProperty(prop)
            log("[MRSP-SERVICE] Proprietatile Window au fost sterse cu succes.")
        except Exception as e:
            log("[MRSP-SERVICE] Eroare la stergerea proprietatilor: %s" % str(e))
    # --------------------------------
    
    def markwatch(self):
        if self.currentTime > 0 and self.totalTime > 0 and self.mon:
            log('[MRSP-MARKWATCH] Începe markwatch - currentTime=%s, totalTime=%s' % (self.currentTime, self.totalTime))
            
            total_percentage = (float(self.currentTime) / float(self.totalTime)) * 100
            totaltime = float(self.totalTime)
            elapsed = float(self.currentTime)
            
            log('[MRSP-MARKWATCH] Procent vizionat: %.2f%%' % total_percentage)

            try:
                watched_percent = int(addon_settings.getSetting('watched_percent'))
            except:
                watched_percent = 90
            
            log('[MRSP-MARKWATCH] Pragul setat în addon este: %s%%' % watched_percent)

            if total_percentage > 1:
                is_considered_watched = total_percentage >= watched_percent

                if is_considered_watched:
                    try:
                        if (addon_settings.getSetting('activateoutsidetrakt') == 'false' and self.detalii) or (addon_settings.getSetting('activateoutsidetrakt') == 'true'):
                            if addon_settings.getSetting('autotraktwatched') == 'true' and addon_settings.getSetting('trakt.user'):
                                
                                enriched_data = self.data.copy()
                                enriched_data.update(self.videolabels)

                                dbtype = self.data.get('kodi_dbtype')
                                dbid = self.data.get('kodi_dbid')

                                if dbtype and dbid:
                                    log('[MRSP-MARKWATCH] Item din bibliotecă detectat. Se preiau detaliile complete...')
                                    try:
                                        if dbtype == 'episode':
                                            json_query = {"jsonrpc": "2.0", "method": "VideoLibrary.GetEpisodeDetails", "params": {"episodeid": int(dbid), "properties": ["title", "season", "episode", "showtitle"]}, "id": 1}
                                            response = xbmc.executeJSONRPC(json.dumps(json_query))
                                            details = json.loads(response).get('result', {}).get('episodedetails', {})
                                            if details:
                                                library_details = {
                                                    'TVShowTitle': details.get('showtitle'),
                                                    'Season': details.get('season'),
                                                    'Episode': details.get('episode'),
                                                    'Title': details.get('title')
                                                }
                                                enriched_data.update(library_details)
                                        elif dbtype == 'movie':
                                            json_query = {"jsonrpc": "2.0", "method": "VideoLibrary.GetMovieDetails", "params": {"movieid": int(dbid), "properties": ["title", "year"]}, "id": 1}
                                            response = xbmc.executeJSONRPC(json.dumps(json_query))
                                            details = json.loads(response).get('result', {}).get('moviedetails', {})
                                            if details:
                                                library_details = {
                                                    'Title': details.get('title'),
                                                    'Year': details.get('year')
                                                }
                                                enriched_data.update(library_details)
                                    except Exception as e:
                                        log('[MRSP-MARKWATCH] Eroare la preluarea detaliilor din biblioteca Kodi: %s' % str(e))

                                log('[MRSP-MARKWATCH] Date finale trimise către Trakt: %s' % str(enriched_data))
                                info = trakt.getDataforTrakt(enriched_data)
                                
                                if info:
                                    info['progress'] = total_percentage
                                    complete = trakt.getTraktScrobble('stop', info)
                                    if complete and complete.get('action') == 'scrobble':
                                        log('[MRSP-MARKWATCH] Scrobble Trakt trimis cu succes.')
                                        if complete.get('movie'):
                                            showMessage("MRSP", "%s marcat vizionat in Trakt" % (complete.get('movie').get('title')), 3000)
                                        elif complete.get('episode'):
                                            showMessage("MRSP", "%s S%sE%s marcat vizionat in Trakt" % (complete.get('show').get('title'), str(complete.get('episode').get('season')), str(complete.get('episode').get('number'))), 3000)
                                else:
                                    log('[MRSP-MARKWATCH] AVERTISMENT: trakt.getDataforTrakt nu a returnat informații. Scrobble anulat.')

                    except Exception as e:
                        log('Eroare la scrobble Trakt: %s' % str(e))

                # --- START LOGICA RESUME UNIVERSALA ---
                try:
                    from resources.Core import Core
                    params_to_save = {}
                    
                    if self.detalii:
                        log('[MRSP-MARKWATCH] Cazul 1 Addon/Extern: Se salvează pe baza detaliilor primite.')
                        db_type = self.data.get('kodi_dbtype')
                        db_id = self.data.get('kodi_dbid')
                        
                        # =========================================================================
                        # 1. RECUPERAREA ID-ULUI EXACT PENTRU SALVARE
                        # =========================================================================
                        landing = None
                        
                        # A. Încercăm să citim din fereastră (Torrserver salvează aici la Faza 2)
                        try:
                            import json
                            win = xbmcgui.Window(10000)
                            saved_pb = win.getProperty('mrsp.playback.info')
                            if saved_pb:
                                pb_data = json.loads(saved_pb)
                                landing = pb_data.get('mrsp_resume_id')
                        except: pass

                        # B. Dacă nu a găsit în fereastră, încercăm memoria serviciului
                        if not landing:
                            landing = self.active_resume_id or self.detalii.get('mrsp_resume_id')
                            
                        # C. RE-EVALUAM EPISODUL DIN NUMELE FISIERULUI REAL DACA ESTE UN PACK
                        # (Asta salvează Elementum / MRSP Player, care nu au File Picker propriu)
                        try:
                            playing_file = self.playerlabels.get('Filenameandpath') or self.getPlayingFile()
                            if landing and playing_file and ('_pack' in landing or '_movie' in landing):
                                import re
                                m_ep = re.search(r'(?i)S(\d+)[._ -]*E(\d+)', playing_file)
                                if m_ep:
                                    s_real = int(m_ep.group(1))
                                    e_real = int(m_ep.group(2))
                                    landing = re.sub(r'_(?:pack|movie)$', '_S%02dE%02d' % (s_real, e_real), landing)
                                    log('[MRSP-MARKWATCH] ID actualizat la final din fisierul real: %s' % landing)
                        except: pass
                        
                        # D. Ultimul Fallback (Re-generam pe loc ID-ul daca tot lipseste)
                        if not landing:
                            log('[MRSP-MARKWATCH] Nu a primit mrsp_resume_id. Re-generam manual...')
                            info_data = self.detalii.get('info', {})
                            t_id = info_data.get('tmdb_id') or self.detalii.get('tmdb_id')
                            i_id = info_data.get('imdb_id') or info_data.get('imdb') or self.detalii.get('imdb_id')
                            
                            # Extragem iar S/E din numele fisierului jucat
                            s_val = info_data.get('Season') or info_data.get('season') or self.detalii.get('season')
                            e_val = info_data.get('Episode') or info_data.get('episode') or self.detalii.get('episode')
                            
                            try:
                                playing_file = self.playerlabels.get('Filenameandpath') or self.getPlayingFile()
                                import re
                                m_se = re.search(r'(?i)S(\d+)[._ -]*E(\d+)', playing_file)
                                if m_se:
                                    s_val = m_se.group(1)
                                    e_val = m_se.group(2)
                            except: pass
                            
                            base_val = ""
                            if i_id: base_val = "imdb_%s" % str(i_id)
                            elif t_id: base_val = "tmdb_%s" % str(t_id)
                            
                            if base_val:
                                try:
                                    if s_val and e_val: landing = "%s_S%02dE%02d" % (base_val, int(s_val), int(e_val))
                                    elif s_val: landing = "%s_S%02d_pack" % (base_val, int(s_val))
                                    else: landing = "%s_movie" % base_val
                                except: landing = "%s_movie" % base_val
                            else:
                                link_str = self.detalii.get('landing') or self.detalii.get('link') or ''
                                import re
                                btih_match = re.search(r'btih:([a-zA-Z0-9]+)', link_str, re.I)
                                
                                if btih_match:
                                    landing = 'hash_%s' % btih_match.group(1).lower()
                                    if e_val: landing += "_E%s" % e_val
                                elif 'id=' in link_str:
                                    id_match = re.search(r'id=(\d+)', link_str)
                                    if id_match: 
                                        landing = 'filelist_%s' % id_match.group(1)
                                        if e_val: landing += "_E%s" % e_val
                                elif link_str.startswith('http'):
                                    landing = link_str.split('?')[0]
                                else:
                                    md5_match = re.search(r'([a-f0-9]{32})\.torrent', link_str)
                                    if md5_match: 
                                        landing = 'local_%s' % md5_match.group(1)
                                        if e_val: landing += "_E%s" % e_val
                                    elif db_type and db_id: landing = 'kodi_library_item://%s/%s' % (db_type, db_id)
                                    elif link_str: landing = link_str

                        log('[MRSP-MARKWATCH] *** ID-UL FINAL UTILIZAT PENTRU SALVARE ESTE: %s ***' % landing)
                        # =========================================================================

                        # Curatam titlul

                        # Curatam titlul
                        clean_title = self.detalii.get('nume', self.videolabels.get('Title', ''))
                        import re
                        clean_title = re.sub(r'\[.*?\]', '', clean_title).strip()
                        self.detalii['nume'] = clean_title
                        
                        params_to_save = {'watched': 'save', 'watchedlink': landing, 'detalii': quote(str(self.detalii)), 'norefresh': '1'}

                    elif addon_settings.getSetting('enableoutsidewatched') == 'true':
                        log('[MRSP-MARKWATCH] Cazul 2 Local/PVR: Se salvează pe baza redării externe.')
                        detalii_externe = {'info': self.videolabels, 'link': self.playerlabels.get('Filenameandpath'), 'switch': 'playoutside', 'nume': (self.videolabels.get('Title') or '')}
                        params_to_save = {'watched': 'save', 'watchedlink': self.playerlabels.get('Filenameandpath'), 'norefresh': '1', 'detalii': detalii_externe}

                    # --- EXECUTARE SALVARE ---
                    if params_to_save:
                        if not is_considered_watched:
                            log('[MRSP-MARKWATCH] Pragul de %s%% NU a fost atins. Se salvează punctul de reluare. ID folosit: %s' % (watched_percent, params_to_save['watchedlink']))
                            params_to_save['elapsed'] = elapsed
                            params_to_save['total'] = totaltime
                        else:
                            log('[MRSP-MARKWATCH] Pragul de %s%% a fost atins. Se marchează ca vizionat complet.' % watched_percent)

                        if self.data.get('kodi_dbtype'):
                            params_to_save['kodi_dbtype'] = self.data.get('kodi_dbtype')
                            params_to_save['kodi_dbid'] = self.data.get('kodi_dbid')
                            params_to_save['kodi_path'] = self.data.get('kodi_path') 
                        
                        Core().watched(params_to_save)

                except Exception as e:
                    log("MRSP service mark watched error: %s" % str(e))

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

# === START MODIFICARE ===
def run():
    log('MRSP service started')
    startup_delay = 1
    if startup_delay:
        xbmc.sleep(startup_delay * 1000)

    Player = mrspPlayer()
    win = xbmcgui.Window(10000)

    while not xbmc.Monitor().abortRequested():
        # Citim setarea din addon si setam proprietatea ferestrei globale
        if xbmcaddon.Addon(id=aid).getSetting('enable_global_context') == 'true':
            win.setProperty('mrsp.context_menu_enabled', 'true')
        else:
            win.setProperty('mrsp.context_menu_enabled', 'false')

        # Verificam din 2 in 2 secunde in loc sa blocam sistemul
        if xbmc.Monitor().waitForAbort(2):
            break

    # we are shutting down
    log("MRSP service shutting down.")

    # delete player/monitor
    del Player
# === SFÂRȘIT MODIFICARE ===


