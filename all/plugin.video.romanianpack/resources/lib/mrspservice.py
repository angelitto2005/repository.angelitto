# -*- coding: utf-8 -*-
import xbmc
import xbmcgui
import xbmcaddon
import json
import re
import os
import hashlib
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
            # Căutăm numele în toate variantele posibile
            showname = playback_info.get('showname') or playback_info.get('TVShowTitle') or playback_info.get('tvshowtitle')
            
            # Dacă încă lipsește, verificăm în info sau Title
            if not showname:
                showname = playback_info.get('title') or (playback_info.get('info', {}).get('TVShowTitle') if isinstance(playback_info.get('info'), dict) else None)

            if not showname:
                log('[MRSP-SERVICE] EROARE: Numele serialului lipsește din toate sursele.')
                return None, None

            season_num = int(playback_info.get('season') or playback_info.get('Season') or 0)
            episode_num = int(playback_info.get('episode') or playback_info.get('Episode') or 0)
            
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
                    # Trebuie sa fie 120 pentru a astepta TorrServer/Elementum sa incarce buffer-ul
                    for _wait in range(120):
                        if self.isPlayingVideo():
                            try:
                                if self.getTotalTime() > 0: break
                            except: pass
                        xbmc.sleep(500)
                    
                    xbmc.sleep(1500)
                    
                    if self.isPlayingVideo():
                        playing_file = ''
                        try: playing_file = self.getPlayingFile()
                        except: pass
                        pf_label = xbmc.getInfoLabel('Player.Filename') or ''
                        pf_full = xbmc.getInfoLabel('Player.Filenameandpath') or ''
                        all_sources = '%s|%s|%s' % (playing_file, pf_label, pf_full)
                        log('[MRSP-RESUME-SVC] Fisier real: %s' % all_sources[:200])
                        
                        pb_info = self.detalii.get('info', {}) if isinstance(self.detalii.get('info'), dict) else {}
                        t_id = pb_info.get('tmdb_id') or self.detalii.get('tmdb_id')
                        i_id = (pb_info.get('imdb_id') or pb_info.get('imdb') or 
                                pb_info.get('IMDBNumber') or self.detalii.get('imdb_id'))
                        log('[MRSP-RESUME-SVC] IDs: tmdb=%s, imdb=%s' % (t_id, i_id))
                        
                        # AUTO-LOOKUP: Dacă lipsesc ID-urile, le căutăm pe TMDb din numele fișierului
                        if not t_id and not i_id and playing_file:
                            try:
                                from resources.lib import PTN
                                from resources.functions import get_show_ids_from_tmdb, get_movie_ids_from_tmdb
                                
                                clean_url = (playing_file or '').split('|')[0].split('?')[0]
                                fname = clean_url.rsplit('/', 1)[-1] if '/' in clean_url else clean_url.rsplit('\\', 1)[-1]
                                try:
                                    from urllib.parse import unquote as url_unq
                                except:
                                    from urllib import unquote as url_unq
                                fname = url_unq(fname)
                                
                                fname = url_unq(fname)
                                # FIX: Split by backslash to get actual filename, not folder
                                fname = fname.replace('\\', '/').rsplit('/', 1)[-1]
                                
                                parsed = PTN.parse(fname.replace('.', ' '))
                                title = parsed.get('title', '')
                                year = parsed.get('year')
                                is_show = bool(parsed.get('season') or s_val if 's_val' in dir() else parsed.get('season'))
                                
                                log('[MRSP-RESUME-SVC] Auto-lookup TMDb: "%s" year=%s show=%s' % (title, year, is_show))
                                
                                if title and len(title) > 2:
                                    if is_show:
                                        api_tmdb, api_imdb = get_show_ids_from_tmdb(title)
                                    else:
                                        api_tmdb, api_imdb = get_movie_ids_from_tmdb(title, year)
                                    
                                    if api_tmdb: t_id = str(api_tmdb)
                                    if api_imdb: i_id = str(api_imdb)
                                    
                                    if t_id or i_id:
                                        log('[MRSP-RESUME-SVC] Auto-lookup SUCCES: tmdb=%s, imdb=%s' % (t_id, i_id))
                                        # Salvăm în detalii pentru markwatch
                                        if self.detalii:
                                            if not self.detalii.get('info'):
                                                self.detalii['info'] = {}
                                            if isinstance(self.detalii.get('info'), dict):
                                                if t_id: self.detalii['info']['tmdb_id'] = t_id
                                                if i_id: self.detalii['info']['imdb_id'] = i_id
                                            if t_id: self.detalii['tmdb_id'] = t_id
                                            if i_id: self.detalii['imdb_id'] = i_id
                                        # Salvăm în data pentru Trakt
                                        if self.data:
                                            if t_id: self.data['tmdb_id'] = t_id
                                            if i_id: self.data['imdb_id'] = i_id
                                    else:
                                        log('[MRSP-RESUME-SVC] Auto-lookup: nimic gasit pentru "%s"' % title)
                            except Exception as e_lookup:
                                log('[MRSP-RESUME-SVC] Auto-lookup eroare: %s' % str(e_lookup))
                        
                        # Extragem S##E## din fisierul REAL
                        s_val, e_val = None, None
                        m_ep = re.search(r'(?i)S(\d+)[._ -]*E(\d+)', all_sources)
                        if m_ep:
                            s_val, e_val = m_ep.group(1), m_ep.group(2)
                            log('[MRSP-RESUME-SVC] Episod din fisier: S%sE%s' % (s_val, e_val))
                        if not s_val:
                            s_val = pb_info.get('Season') or pb_info.get('season') or self.detalii.get('season')
                        if not e_val:
                            e_val = pb_info.get('Episode') or pb_info.get('episode') or self.detalii.get('episode')
                        
                        # Construim base
                        base_val = ""
                        if i_id: base_val = "imdb_%s" % i_id
                        elif t_id: base_val = "tmdb_%s" % t_id
                        
                        # Construim sufixul
                        file_suffix = ""
                        if s_val and e_val:
                            try: file_suffix = "_S%02dE%02d" % (int(s_val), int(e_val))
                            except: file_suffix = "_S%sE%s" % (s_val, e_val)
                        elif base_val:
                            # ARE ID (imdb/tmdb) → e film identificat → _movie
                            file_suffix = "_movie"
                        else:
                            # NU are ID (local_) → verificăm dacă e multi-file
                            url_norm = (playing_file or '').split('?')[0].replace('%5C', '/').replace('\\', '/')
                            has_subfolder = url_norm.count('/files/') > 0 and url_norm.split('/files/')[-1].count('/') > 0
                            if has_subfolder:
                                try:
                                    fname = url_norm.rsplit('/', 1)[-1]
                                    try:
                                        from urllib.parse import unquote as url_unq
                                    except:
                                        from urllib import unquote as url_unq
                                    fname = url_unq(fname)
                                    if fname and len(fname) > 5:
                                        fhash = hashlib.md5(fname.encode('utf-8', 'ignore')).hexdigest()[:8]
                                        file_suffix = "_F%s" % fhash
                                        log('[MRSP-RESUME-SVC] File hash (local multi): %s (%s)' % (fhash, fname[:50]))
                                    else:
                                        file_suffix = "_movie"
                                except:
                                    file_suffix = "_movie"
                            else:
                                file_suffix = "_movie"
                        
                        # Construim ID-ul final
                        if base_val:
                            resume_id = base_val + file_suffix
                        else:
                            fallback_id = self.active_resume_id or self.detalii.get('mrsp_resume_id', '')
                            if fallback_id:
                                # Eliminăm sufixele vechi (_movie, _pack) și adăugăm cel nou
                                clean_base = re.sub(r'_(movie|pack|S\d+E\d+|S\d+_pack|F[a-f0-9]+)$', '', fallback_id)
                                resume_id = clean_base + file_suffix
                            else:
                                resume_id = ''
                        
                        # Actualizăm Window Properties cu episodul real detectat din fișier
                        if s_val or e_val:
                            try:
                                win = xbmcgui.Window(10000)
                                if s_val:
                                    for p in ['mrsp_season', 'VideoPlayer.Season', 'season']:
                                        win.setProperty(p, str(int(s_val)))
                                if e_val:
                                    for p in ['mrsp_episode', 'VideoPlayer.Episode', 'episode']:
                                        win.setProperty(p, str(int(e_val)))
                                # Actualizăm și playback.info dacă există
                                try:
                                    import json
                                    existing = win.getProperty('mrsp.playback.info')
                                    if existing:
                                        pb = json.loads(existing)
                                        if s_val: pb['season'] = str(int(s_val))
                                        if e_val: pb['episode'] = str(int(e_val))
                                        win.setProperty('mrsp.playback.info', json.dumps(pb))
                                except: pass
                                log('[MRSP-RESUME-SVC] Window Properties actualizate: S%s E%s' % (s_val, e_val))
                                # Setam autoselect pentru Elementum
                                win.setProperty('mrsp.elem.autoselect.season', str(int(s_val)))
                                win.setProperty('mrsp.elem.autoselect.episode', str(int(e_val)))
                                # Setam fanart/logo pentru buffering dialog Elementum
                                try:
                                    _info = self.detalii.get('info', {}) if isinstance(self.detalii.get('info'), dict) else {}
                                    _fanart = _info.get('Fanart') or _info.get('fanart') or _info.get('Poster') or ''
                                    _logo = _info.get('ClearLogo') or _info.get('clearlogo') or ''
                                    if _fanart:
                                        win.setProperty('info.fanart', str(_fanart))
                                    if _logo:
                                        win.setProperty('info.clearlogo', str(_logo))
                                except: pass
                            except: pass
                        
                        if resume_id:
                            self.active_resume_id = resume_id
                            if self.detalii:
                                self.detalii['mrsp_resume_id'] = resume_id
                            
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
                                # === FIX: INJECTARE CLEARLOGO + METADATA PE ITEM-UL CARE RULEAZĂ ===
                                # Rezolvă Elementum (care își creează propriul ListItem fără logo)
                                # și Torrent2HTTP (unde MRPlayer poate suprascrie titlul)
                                try:
                                    _win = xbmcgui.Window(10000)
                                    _clearlogo = _win.getProperty('info.clearlogo') or ''
                                    
                                    # Dacă nu avem clearlogo în properties, încercăm din detalii
                                    if not _clearlogo:
                                        _d_info = self.detalii.get('info', {}) if isinstance(self.detalii.get('info'), dict) else {}
                                        _clearlogo = _d_info.get('ClearLogo') or _d_info.get('clearlogo') or ''
                                    
                                    if _clearlogo or s_val:
                                        try:
                                            playing_item = self.getPlayingItem()
                                            
                                            # Injectăm clearlogo în artwork
                                            if _clearlogo:
                                                _current_art = {}
                                                for _ak in ['thumb', 'poster', 'fanart', 'clearlogo', 'icon']:
                                                    _av = playing_item.getArt(_ak)
                                                    if _av:
                                                        _current_art[_ak] = _av
                                                _current_art['clearlogo'] = _clearlogo
                                                
                                                # Adăugăm și fanart dacă lipsește
                                                _fanart_prop = _win.getProperty('info.fanart') or ''
                                                if _fanart_prop and not _current_art.get('fanart'):
                                                    _current_art['fanart'] = _fanart_prop
                                                
                                                playing_item.setArt(_current_art)
                                                log('[MRSP-INJECT] ClearLogo injectat: %s' % _clearlogo[:80])
                                            
                                            # Injectăm metadata episod
                                            if s_val and e_val:
                                                try:
                                                    _vtag = playing_item.getVideoInfoTag()
                                                    _vtag.setMediaType('episode')
                                                    _vtag.setSeason(int(s_val))
                                                    _vtag.setEpisode(int(e_val))
                                                    
                                                    _d_info = self.detalii.get('info', {}) if isinstance(self.detalii.get('info'), dict) else {}
                                                    _tvshow = _d_info.get('TVShowTitle') or _d_info.get('tvshowtitle') or ''
                                                    _epname = _d_info.get('EpisodeName') or _d_info.get('episode_name') or ''
                                                    
                                                    if _tvshow:
                                                        _vtag.setTvShowTitle(str(_tvshow))
                                                    if _epname:
                                                        _vtag.setTitle(str(_epname))
                                                    elif _d_info.get('Title'):
                                                        # Dacă Title nu e un filename de torrent, îl folosim
                                                        if not re.search(r'(?i)(720p|1080p|2160p|4K|WEB|BluRay|REMUX|x26)', str(_d_info['Title'])):
                                                            _vtag.setTitle(str(_d_info['Title']))
                                                    
                                                    log('[MRSP-INJECT] Metadata episod: %s S%02dE%02d - %s' % (_tvshow, int(s_val), int(e_val), _epname or _d_info.get('Title', '')))
                                                except Exception as _ev:
                                                    log('[MRSP-INJECT] Eroare metadata: %s' % str(_ev))
                                            
                                            # Aplicăm modificările pe itemul care rulează
                                            self.updateInfoTag(playing_item)
                                            log('[MRSP-INJECT] updateInfoTag aplicat cu succes')
                                            
                                        except AttributeError:
                                            # Kodi < 20: getPlayingItem/updateInfoTag nu există
                                            log('[MRSP-INJECT] Kodi < 20 detectat, skip injectare')
                                        except Exception as _ei:
                                            log('[MRSP-INJECT] Eroare injectare: %s' % str(_ei))
                                except Exception as _eo:
                                    log('[MRSP-INJECT] Eroare generală: %s' % str(_eo))
                                # === SFÂRȘIT FIX ===

                    else:
                        log('[MRSP-RESUME-SVC] Playerul nu reda video')
                except Exception as e:
                    log('[MRSP-RESUME-SVC] EROARE: %s' % str(e))
                    import traceback
                    log('[MRSP-RESUME-SVC] %s' % traceback.format_exc())
            # ===== SFARSIT RESUME UNIVERSAL =====

            # === FIX: INJECTARE CLEARLOGO + METADATA PE ITEMUL CARE RULEAZĂ ===
            if self.isPlayingVideo() and self.detalii:
                try:
                    xbmc.sleep(1500)
                    
                    if self.isPlayingVideo():
                        _win = xbmcgui.Window(10000)
                        _d_info = self.detalii.get('info', {}) if isinstance(self.detalii.get('info'), dict) else {}
                        
                        # --- COLECTARE DATE EXISTENTE ---
                        _clearlogo = (_win.getProperty('info.clearlogo') or 
                                     _d_info.get('ClearLogo') or _d_info.get('clearlogo') or '')
                        _fanart = (_win.getProperty('info.fanart') or 
                                  _d_info.get('Fanart') or _d_info.get('fanart') or '')
                        _poster = _d_info.get('Poster') or _d_info.get('poster') or ''
                        
                        _sv = (_d_info.get('Season') or _d_info.get('season') or 
                              self.detalii.get('season') or _win.getProperty('mrsp_season') or None)
                        _ev = (_d_info.get('Episode') or _d_info.get('episode') or 
                              self.detalii.get('episode') or _win.getProperty('mrsp_episode') or None)
                        _tvshow = _d_info.get('TVShowTitle') or _d_info.get('tvshowtitle') or ''
                        _epname = _d_info.get('EpisodeName') or _d_info.get('episode_name') or ''
                        _title = _d_info.get('Title') or ''
                        _plot = _d_info.get('Plot') or _d_info.get('plot') or ''
                        
                        # URL decode TVShowTitle
                        if _tvshow and '%' in _tvshow:
                            try:
                                from resources.functions import unquote as _uq
                                _tvshow = _uq(_tvshow)
                            except: pass
                        
                        # --- PRELUARE IDs ---
                        _t_id = (_d_info.get('tmdb_id') or self.detalii.get('tmdb_id') or 
                                _win.getProperty('tmdb_id') or _win.getProperty('TMDb_ID') or None)
                        _i_id = (_d_info.get('imdb_id') or _d_info.get('imdb') or 
                                self.detalii.get('imdb_id') or 
                                _win.getProperty('imdb_id') or _win.getProperty('IMDb_ID') or None)
                        
                        if str(_t_id).lower() in ('none', ''): _t_id = None
                        if str(_i_id).lower() in ('none', ''): _i_id = None
                        
                        # --- AUTO-LOOKUP DIN FILENAME DACĂ NU AVEM IDs ---
                        if not _t_id and not _i_id:
                            try:
                                playing_file = self.getPlayingFile()
                                clean_url = (playing_file or '').split('|')[0].split('?')[0]
                                try:
                                    from urllib.parse import unquote as url_unq
                                except:
                                    from urllib import unquote as url_unq
                                clean_url = url_unq(clean_url)
                                # FIX: Split by both / and \ to get actual filename
                                fname = clean_url.replace('\\', '/').rsplit('/', 1)[-1]
                                
                                from resources.lib import PTN
                                parsed = PTN.parse(fname.replace('.', ' '))
                                title_lookup = parsed.get('title', '')
                                year_lookup = parsed.get('year')
                                is_show = bool(parsed.get('season'))
                                
                                log('[MRSP-INJECT] Auto-lookup: fname="%s" -> title="%s", year=%s, show=%s' % (fname[:50], title_lookup, year_lookup, is_show))
                                
                                if title_lookup and len(title_lookup) > 2:
                                    from resources.functions import get_show_ids_from_tmdb, get_movie_ids_from_tmdb
                                    if is_show:
                                        api_tmdb, api_imdb = get_show_ids_from_tmdb(title_lookup)
                                    else:
                                        api_tmdb, api_imdb = get_movie_ids_from_tmdb(title_lookup, year_lookup)
                                    if api_tmdb: _t_id = str(api_tmdb)
                                    if api_imdb: _i_id = str(api_imdb)
                                    if _t_id or _i_id:
                                        log('[MRSP-INJECT] Auto-lookup SUCCESS: tmdb=%s, imdb=%s' % (_t_id, _i_id))
                            except Exception as _al:
                                log('[MRSP-INJECT] Auto-lookup error: %s' % str(_al))
                        
                        # --- CONVERT IMDb -> TMDb DACĂ LIPSEȘTE ---
                        if _i_id and not _t_id:
                            try:
                                from resources.functions import tmdb_key, fetchData
                                api_key = tmdb_key()
                                find_url = 'https://api.themoviedb.org/3/find/%s?api_key=%s&external_source=imdb_id' % (_i_id, api_key)
                                find_data = fetchData(find_url, rtype='json')
                                if find_data:
                                    if find_data.get('tv_results'):
                                        _t_id = str(find_data['tv_results'][0]['id'])
                                    elif find_data.get('movie_results'):
                                        _t_id = str(find_data['movie_results'][0]['id'])
                                    if _t_id:
                                        log('[MRSP-INJECT] IMDb->TMDb: %s -> %s' % (_i_id, _t_id))
                            except: pass
                        
                        # --- TMDb FETCH: ARTWORK + METADATA ---
                        if _t_id and (not _clearlogo or not _tvshow or not _epname or not _fanart):
                            try:
                                from resources.functions import tmdb_key, fetchData
                                api_key = tmdb_key()
                                is_tv = bool(_sv)
                                m_type = 'tv' if is_tv else 'movie'
                                
                                url_base = 'https://api.themoviedb.org/3/%s/%s?api_key=%s&language=ro-RO&append_to_response=images&include_image_language=ro,en,null' % (m_type, _t_id, api_key)
                                base_d = fetchData(url_base, rtype='json')
                                
                                if base_d:
                                    if not _tvshow:
                                        _tvshow = base_d.get('name') or base_d.get('title') or ''
                                    if not _title or re.search(r'(?i)(720p|1080p|2160p|WEB|BluRay)', str(_title)):
                                        _title = base_d.get('title') or base_d.get('name') or _title
                                    if not _plot:
                                        _plot = base_d.get('overview') or ''
                                    
                                    imgs = base_d.get('images', {})
                                    
                                    # Helper: prioritate RO > neutru > EN > rest
                                    def _img_lang_prio(img):
                                        iso = str(img.get('iso_639_1') or '').lower()
                                        if iso == 'ro': return (0, -img.get('vote_average', 0))
                                        elif iso in ('', 'xx', 'zxx') or img.get('iso_639_1') is None: return (1, -img.get('vote_average', 0))
                                        elif iso == 'en': return (2, -img.get('vote_average', 0))
                                        else: return (3, -img.get('vote_average', 0))
                                    
                                    # ClearLogo (RO prioritar, fallback EN)
                                    if not _clearlogo and imgs.get('logos'):
                                        logos = sorted(imgs['logos'], key=_img_lang_prio)
                                        if logos:
                                            _clearlogo = 'https://image.tmdb.org/t/p/w500' + logos[0]['file_path']
                                            _sel_iso = logos[0].get('iso_639_1', '?')
                                            log('[MRSP-INJECT] Logo selectat: lang=%s' % _sel_iso)
                                    
                                    # Fanart (neutru prioritar, apoi RO, apoi EN)
                                    if not _fanart:
                                        if imgs.get('backdrops'):
                                            def _bd_prio(img):
                                                iso = str(img.get('iso_639_1') or '').lower()
                                                if iso in ('', 'xx', 'zxx') or img.get('iso_639_1') is None: return (0, -img.get('vote_average', 0))
                                                elif iso == 'ro': return (1, -img.get('vote_average', 0))
                                                elif iso == 'en': return (2, -img.get('vote_average', 0))
                                                else: return (3, -img.get('vote_average', 0))
                                            bds = sorted(imgs['backdrops'], key=_bd_prio)
                                            if bds:
                                                _fanart = 'https://image.tmdb.org/t/p/original' + bds[0]['file_path']
                                        elif base_d.get('backdrop_path'):
                                            _fanart = 'https://image.tmdb.org/t/p/original' + base_d['backdrop_path']
                                    
                                    # Poster
                                    if not _poster and base_d.get('poster_path'):
                                        _poster = 'https://image.tmdb.org/t/p/w500' + base_d['poster_path']
                                
                                # Episod: nume + plot
                                if is_tv and _sv and _ev and not _epname:
                                    ep_url = 'https://api.themoviedb.org/3/tv/%s/season/%s/episode/%s?api_key=%s&language=ro-RO' % (_t_id, int(_sv), int(_ev), api_key)
                                    ep_d = fetchData(ep_url, rtype='json')
                                    if not ep_d or not ep_d.get('name'):
                                        ep_url_en = ep_url.replace('ro-RO', 'en-US')
                                        ep_d = fetchData(ep_url_en, rtype='json')
                                    if ep_d:
                                        if ep_d.get('name'):
                                            _epname = ep_d['name']
                                        if ep_d.get('overview') and not _plot:
                                            _plot = ep_d['overview']
                                
                                log('[MRSP-INJECT] TMDb enriched: logo=%s, show="%s", ep="%s", fanart=%s' % (
                                    'DA' if _clearlogo else 'NU', 
                                    _tvshow[:30] if _tvshow else '-', 
                                    _epname[:30] if _epname else '-',
                                    'DA' if _fanart else 'NU'))
                            except Exception as _te:
                                log('[MRSP-INJECT] TMDb lookup error: %s' % str(_te))
                        
                        # --- APLICARE PE ITEMUL CARE RULEAZĂ ---
                        needs_inject = bool(_clearlogo) or bool(_sv and _ev) or bool(_t_id)
                        
                        if needs_inject:
                            try:
                                playing_item = self.getPlayingItem()
                                
                                # 1. ARTWORK
                                _art = {}
                                for _ak in ['thumb', 'poster', 'fanart', 'clearlogo', 'icon', 'banner']:
                                    _av = playing_item.getArt(_ak)
                                    if _av: _art[_ak] = _av
                                
                                if _clearlogo: _art['clearlogo'] = _clearlogo
                                if _fanart: _art['fanart'] = _fanart
                                if _poster:
                                    _art['poster'] = _poster
                                    if not _art.get('thumb'): _art['thumb'] = _poster
                                
                                playing_item.setArt(_art)
                                
                                # 2. VIDEO INFO TAG
                                _vtag = playing_item.getVideoInfoTag()
                                
                                if _sv and _ev:
                                    try:
                                        _vtag.setMediaType('episode')
                                        _vtag.setSeason(int(_sv))
                                        _vtag.setEpisode(int(_ev))
                                    except: pass
                                
                                if _tvshow:
                                    _vtag.setTvShowTitle(str(_tvshow))
                                    self.data['showname'] = _tvshow # Salvăm numele pentru marcare ulterioară
                                
                                # Titlu: EpisodeName > Title (doar dacă nu e torrent name)
                                if _epname:
                                    _vtag.setTitle(str(_epname))
                                elif _title and not re.search(r'(?i)(720p|1080p|2160p|4K|WEB[.\-]?DL|BluRay|HDRip|REMUX|BRRip|x264|x265|HEVC|DSNP|AMZN|FLUX|playWEB|YTS|\.\w{2,4}$)', str(_title)):
                                    _vtag.setTitle(str(_title))
                                
                                if _plot:
                                    _vtag.setPlot(str(_plot))
                                
                                # 3. APLICARE
                                self.updateInfoTag(playing_item)
                                
                                # 4. SALVARE PENTRU WINDOW PROPERTIES (pt. servicii ulterioare)
                                if _clearlogo: _win.setProperty('info.clearlogo', str(_clearlogo))
                                if _fanart: _win.setProperty('info.fanart', str(_fanart))
                                if _t_id:
                                    _win.setProperty('tmdb_id', str(_t_id))
                                    _win.setProperty('TMDb_ID', str(_t_id))
                                if _i_id:
                                    _win.setProperty('imdb_id', str(_i_id))
                                    _win.setProperty('IMDb_ID', str(_i_id))
                                
                                log('[MRSP-INJECT] SUCCESS: logo=%s, show="%s", S%sE%s, title="%s"' % (
                                    'DA' if _clearlogo else 'NU',
                                    _tvshow[:30] if _tvshow else '-',
                                    str(_sv) if _sv else '?',
                                    str(_ev) if _ev else '?',
                                    (_epname or _title or '-')[:40]))
                            
                            except AttributeError:
                                log('[MRSP-INJECT] Skip (Kodi < 20)')
                            except Exception as _ei:
                                log('[MRSP-INJECT] Eroare aplicare: %s' % str(_ei))
                        else:
                            log('[MRSP-INJECT] Skip — nu avem date pentru injectare.')
                
                except Exception as _eo:
                    log('[MRSP-INJECT] Eroare generala: %s' % str(_eo))
            # === SFÂRȘIT FIX INJECTARE ===

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
                
                # Urgență: dacă lipsește showname dar avem TVShowTitle în info
                if not self.data.get('showname'):
                    if isinstance(info_child, dict):
                        self.data['showname'] = info_child.get('TVShowTitle') or info_child.get('tvshowtitle')
                        
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
                try: self._actual_playing_file = self.getPlayingFile()
                except: self._actual_playing_file = ''
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
            
            if window.getProperty('mrsp.next_episode_active') == 'true':
                window.clearProperty('mrsp.next_episode_active')
                log("[MRSP-SERVICE] Skip cleanup - next episode active")
                return
            
            props_to_clear = [
                'tmdb_id', 'TMDb_ID', 'tmdb', 'VideoPlayer.TMDb',
                'imdb_id', 'IMDb_ID', 'imdb', 'VideoPlayer.IMDb', 'VideoPlayer.IMDBNumber',
                'mrsp.tmdb_id', 'mrsp.imdb_id',
                'tmdbmovies.release_name',
                'mrsp.playback.info',
                'mrsp.check_resume', 'mrsp.pending_seek', 'mrsp.pending_seek_total',
                'mrsp_season', 'mrsp_episode',
                'VideoPlayer.Season', 'VideoPlayer.Episode',
                'info.fanart', 'info.clearlogo',
                'mrsp.elem.autoselect.season', 'mrsp.elem.autoselect.episode',
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

                                # Fix: Dacă TVShowTitle lipsește dar avem Season+Episode, 
                                # extragem numele serialului din titlul torrentului
                                if not enriched_data.get('TVShowTitle') and (enriched_data.get('Season') or enriched_data.get('season')):
                                    try:
                                        from resources.lib import PTN
                                        raw_title = enriched_data.get('Title') or enriched_data.get('title') or ''
                                        parsed_title = PTN.parse(raw_title.replace('.', ' '))
                                        show_name = parsed_title.get('title', '')
                                        if show_name and len(show_name) > 2:
                                            enriched_data['TVShowTitle'] = show_name
                                            enriched_data['TVshowtitle'] = show_name
                                            log('[MRSP-MARKWATCH] TVShowTitle extras din titlu torrent: %s' % show_name)
                                    except: pass

                                # Fix: Asigurăm că Season/Episode sunt INT, nu string '01'
                                for key in ['Season', 'season', 'Episode', 'episode']:
                                    if key in enriched_data:
                                        try: enriched_data[key] = int(enriched_data[key])
                                        except: pass

                                log('[MRSP-MARKWATCH] Date finale trimise către Trakt: %s' % str(enriched_data))
                                
                                # Fix: Dacă getDataforTrakt a eșuat dar avem IMDb ID, construim manual
                                info = None
                                imdb_fix = enriched_data.get('IMDBNumber') or enriched_data.get('imdb_id') or enriched_data.get('imdb')
                                
                                # Luăm S/E din fișierul real redat (cel mai precis)
                                s_fix = None
                                e_fix = None
                                try:
                                    pf_trakt = getattr(self, '_actual_playing_file', '') or self.playerlabels.get('Filenameandpath', '')
                                    m_trakt = re.search(r'(?i)S(\d+)[._ -]*E(\d+)', pf_trakt)
                                    if m_trakt:
                                        s_fix = int(m_trakt.group(1))
                                        e_fix = int(m_trakt.group(2))
                                except: pass
                                
                                # Fallback pe detalii
                                if not s_fix:
                                    try: s_fix = int(enriched_data.get('season') or enriched_data.get('Season') or 0)
                                    except: s_fix = None
                                if not e_fix:
                                    try: e_fix = int(enriched_data.get('episode') or enriched_data.get('Episode') or 0)
                                    except: e_fix = None
                                
                                # Fallback pe resume_id (cel mai precis)
                                if (not s_fix or not e_fix) and self.active_resume_id:
                                    m_rid = re.search(r'_S(\d+)E(\d+)$', self.active_resume_id)
                                    if m_rid:
                                        s_fix = int(m_rid.group(1))
                                        e_fix = int(m_rid.group(2))
                                
                                if imdb_fix:
                                    if not str(imdb_fix).startswith('tt'): imdb_fix = 'tt' + str(imdb_fix)
                                    if s_fix and e_fix:
                                        info = {
                                            'show': {'ids': {'imdb': imdb_fix}},
                                            'episode': {'season': s_fix, 'number': e_fix}
                                        }
                                    elif not s_fix and not e_fix:
                                        info = {'movie': {'ids': {'imdb': imdb_fix}}}
                                    log('[MRSP-MARKWATCH] Trakt construit cu IMDb: %s S%sE%s' % (imdb_fix, s_fix, e_fix))
                                
                                if not info:
                                    info = trakt.getDataforTrakt(enriched_data)

                                
                                if info:
                                    # Forțăm progress la 100 dacă am trecut pragul nostru
                                    if is_considered_watched:
                                        info['progress'] = 100
                                    else:
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
                            
                        # C. RE-EVALUAM EPISODUL/FISIERUL DIN NUMELE REAL
                        try:
                            playing_file = self.playerlabels.get('Filenameandpath') or getattr(self, '_actual_playing_file', '') or ''
                            
                            if landing and playing_file:
                                m_ep = re.search(r'(?i)S(\d+)[._ -]*E(\d+)', playing_file)
                                if m_ep:
                                    # SERIAL cu episod exact
                                    s_real = int(m_ep.group(1))
                                    e_real = int(m_ep.group(2))
                                    ep_suffix = '_S%02dE%02d' % (s_real, e_real)
                                    if '_pack' in landing or '_movie' in landing:
                                        landing = re.sub(r'_(?:pack|movie)$', ep_suffix, landing)
                                    elif ep_suffix not in landing:
                                        landing = landing + ep_suffix
                                    log('[MRSP-MARKWATCH] C: Episod: %s' % landing)
                                elif re.search(r'(?i)S\d+', playing_file):
                                    # Pack serial fără episod specific - file hash
                                    clean_url = playing_file.split('|')[0].split('?')[0].replace('%5C', '/').replace('\\', '/')
                                    fname = clean_url.rsplit('/', 1)[-1] if '/' in clean_url else clean_url
                                    try:
                                        from urllib.parse import unquote as url_unq
                                    except:
                                        from urllib import unquote as url_unq
                                    fname = url_unq(fname)
                                    if fname and len(fname) > 5:
                                        fhash = hashlib.md5(fname.encode('utf-8', 'ignore')).hexdigest()[:8]
                                        if ('_F' + fhash) not in landing:
                                            landing = re.sub(r'_(movie|pack)$', '', landing)
                                            landing = "%s_F%s" % (landing, fhash)
                                            log('[MRSP-MARKWATCH] C: File hash (serial pack): %s' % landing)
                                elif landing.startswith('local_'):
                                    # FĂRĂ S##E##, FĂRĂ ID → concert/compilație multi-file
                                    url_norm = playing_file.split('?')[0].replace('%5C', '/').replace('\\', '/')
                                    has_subfolder = url_norm.count('/files/') > 0 and url_norm.split('/files/')[-1].count('/') > 0
                                    if has_subfolder:
                                        clean_url = url_norm.rsplit('/', 1)[-1] if '/' in url_norm else ''
                                        try:
                                            from urllib.parse import unquote as url_unq
                                        except:
                                            from urllib import unquote as url_unq
                                        fname = url_unq(clean_url)
                                        if fname and len(fname) > 5:
                                            fhash = hashlib.md5(fname.encode('utf-8', 'ignore')).hexdigest()[:8]
                                            if ('_F' + fhash) not in landing:
                                                landing = re.sub(r'_(movie)$', '', landing)
                                                landing = "%s_F%s" % (landing, fhash)
                                                log('[MRSP-MARKWATCH] C: File hash (local multi): %s' % landing)
                                # else: FILM cu ID → nu facem nimic, păstrăm _movie
                        except Exception as ex_c:
                            log('[MRSP-MARKWATCH] Eroare bloc C: %s' % str(ex_c))
                        
                        # D. NORMALIZARE FINALA
                        if landing:
                            # Dacă nu are niciun sufix valid, adăugăm _movie
                            if not re.search(r'_(S\d+E\d+|F[a-f0-9]{8}|movie)$', landing):
                                landing = landing + '_movie'
                                log('[MRSP-MARKWATCH] D: Adaugat _movie: %s' % landing)

                        log('[MRSP-MARKWATCH] *** ID-UL FINAL UTILIZAT PENTRU SALVARE ESTE: %s ***' % landing)
                        # =========================================================================

                        # Salvăm baza resume-ului pentru ștergere ulterioară din context menu
                        try:
                            resume_base = re.sub(r'_(S\d+E\d+|F[a-f0-9]+|movie|pack|S\d+_pack)$', '', landing)
                            xbmcgui.Window(10000).setProperty('mrsp.last_resume_base', resume_base)
                        except: pass

                        # Curatam titlul
                        clean_title = self.detalii.get('nume', self.videolabels.get('Title', ''))
                        clean_title = re.sub(r'\[.*?\]', '', clean_title).strip()
                        self.detalii['nume'] = clean_title
                        
                        params_to_save = {'watched': 'save', 'watchedlink': landing, 'detalii': quote(str(self.detalii)), 'norefresh': '1'}

                    elif addon_settings.getSetting('enableoutsidewatched') == 'true':
                        log('[MRSP-MARKWATCH] Cazul 2 Local/PVR: Se salvează pe baza redării externe.')
                        detalii_externe = {'info': self.videolabels, 'link': self.playerlabels.get('Filenameandpath'), 'switch': 'playoutside', 'nume': (self.videolabels.get('Title') or '')}
                        params_to_save = {'watched': 'save', 'watchedlink': self.playerlabels.get('Filenameandpath'), 'norefresh': '1', 'detalii': detalii_externe}

                    # --- EXECUTARE SALVARE ---
                    if params_to_save:
                        if is_considered_watched:
                            # COMPLET VIZIONAT → salvăm în "watched" (apare în lista Văzute)
                            log('[MRSP-MARKWATCH] Pragul de %s%% a fost atins. Se marchează ca vizionat complet.' % watched_percent)
                        elif total_percentage >= 3:
                            # PARȚIAL (>3%) → salvăm doar punctul de reluare (NU apare în Văzute)
                            log('[MRSP-MARKWATCH] Procent %.1f%% (>3%%) — se salvează doar punctul de reluare. ID: %s' % (total_percentage, params_to_save['watchedlink']))
                            params_to_save['elapsed'] = elapsed
                            params_to_save['total'] = totaltime
                        else:
                            # SUB 3% → nu salvăm nimic (vizionare accidentală)
                            log('[MRSP-MARKWATCH] Procent %.1f%% (<3%%) — prea puțin, nu se salvează nimic.' % total_percentage)
                            params_to_save = {}

                        if params_to_save:
                            if self.data.get('kodi_dbtype'):
                                params_to_save['kodi_dbtype'] = self.data.get('kodi_dbtype')
                                params_to_save['kodi_dbid'] = self.data.get('kodi_dbid')
                                params_to_save['kodi_path'] = self.data.get('kodi_path') 
                            
                            Core().watched(params_to_save)

                except Exception as e:
                    log("MRSP service mark watched error: %s" % str(e))

                # --- NEXT EPISODE ---
                if is_considered_watched and self.detalii:
                    try:
                        # Nu rulăm next episode dacă t2h are propria logică activată
                        is_t2h = 'torrent2http' in str(getattr(self, '_actual_playing_file', '')) or '127.0.0.1:5001' in str(getattr(self, '_actual_playing_file', ''))
                        if xbmcaddon.Addon(id=aid).getSetting('torrserver_next_episode') == 'true' and not is_t2h:
                            e_curr = None
                            s_curr = None
                            try:
                                pf = getattr(self, '_actual_playing_file', '') or self.playerlabels.get('Filenameandpath', '')
                                m = re.search(r'(?i)S(\d+)[._ -]*E(\d+)', pf)
                                if m:
                                    s_curr = int(m.group(1))
                                    e_curr = int(m.group(2))
                            except: pass
                            
                            if not s_curr:
                                info_c = self.detalii.get('info', {})
                                if isinstance(info_c, dict):
                                    try: s_curr = int(info_c.get('Season') or info_c.get('season') or self.detalii.get('season') or 0)
                                    except: s_curr = 0
                                    try: e_curr = int(info_c.get('Episode') or info_c.get('episode') or self.detalii.get('episode') or 0)
                                    except: e_curr = 0
                            
                            if s_curr and e_curr:
                                info_c = self.detalii.get('info', {}) if isinstance(self.detalii.get('info'), dict) else {}
                                show_title = (self.videolabels.get('TVShowTitle') or info_c.get('TVShowTitle') or 
                                             info_c.get('Title') or self.detalii.get('nume') or '')
                                show_title = re.sub(r'\[.*?\]', '', show_title).strip()
                                
                                # Curățăm titlul de tag-uri torrent
                                from resources.lib import PTN
                                parsed_t = PTN.parse(show_title.replace('.', ' '))
                                clean_show = parsed_t.get('title', show_title)
                                
                                next_ep = e_curr + 1
                                pf_check = str(getattr(self, '_actual_playing_file', '')) + '|' + str(self.playerlabels.get('Filenameandpath', ''))
                                link_for_check = self.detalii.get('link') or self.detalii.get('landing', '')
                                pf_check_full = pf_check + '|' + str(link_for_check)
                                
                                # ============================================================
                                # VERIFICARE: Episodul următor există în pack-ul curent?
                                # ============================================================
                                ep_in_pack = True  # se va suprascrie mai jos
                                
                                # === FIX: site trebuie definit înainte de verificarea pack-ului ===
                                site = self.detalii.get('site', '')
                                
                                try:
                                    ep_patterns = [
                                        re.compile(r'(?i)S0*%d[._ -]*E0*%d(?:[^0-9]|$)' % (s_curr, next_ep)),
                                        re.compile(r'(?i)\b%dx%02d\b' % (s_curr, next_ep)),
                                        re.compile(r'(?i)(?:Episod|Ep|Episode)[._ -]*0?%d(?:[^0-9]|$)' % next_ep),
                                    ]
                                    
                                    def filename_matches(fname):
                                        return any(p.search(fname) for p in ep_patterns)
                                    
                                    def parse_torrent_files(torrent_path):
                                        """Parsează bencode fără dependențe externe."""
                                        def _bd(data, i):
                                            c = data[i:i+1]
                                            if c == b'd':
                                                d, i = {}, i + 1
                                                while data[i:i+1] != b'e':
                                                    k, i = _bd(data, i)
                                                    v, i = _bd(data, i)
                                                    d[k.decode('utf-8', 'ignore') if isinstance(k, bytes) else k] = v
                                                return d, i + 1
                                            elif c == b'l':
                                                lst, i = [], i + 1
                                                while data[i:i+1] != b'e':
                                                    v, i = _bd(data, i)
                                                    lst.append(v)
                                                return lst, i + 1
                                            elif c == b'i':
                                                e = data.index(b'e', i)
                                                return int(data[i+1:e]), e + 1
                                            else:
                                                j = data.index(b':', i)
                                                n = int(data[i:j])
                                                s = j + 1
                                                return data[s:s+n], s + n
                                        with open(torrent_path, 'rb') as f:
                                            raw = f.read()
                                        t, _ = _bd(raw, 0)
                                        info = t.get('info', {})
                                        names = []
                                        for fe in info.get('files', []):
                                            pp = fe.get('path', [])
                                            if pp:
                                                names.append('/'.join(
                                                    p.decode('utf-8', 'ignore') if isinstance(p, bytes) else str(p)
                                                    for p in pp))
                                        if not names:
                                            n = info.get('name', b'')
                                            if isinstance(n, bytes): n = n.decode('utf-8', 'ignore')
                                            if n: names.append(n)
                                        return names
                                    
                                    checked = False
                                        
                                    # --- 1. TorrServer: JSON-RPC cu urllib ---
                                    if not checked and ('127.0.0.1' in pf_check_full and 'link=' in pf_check_full):
                                        m_hash = re.search(r'link=([a-f0-9]{16,})', pf_check_full, re.I)
                                        m_port = re.search(r'127\.0\.0\.1:(\d+)', pf_check_full)
                                        if m_hash:
                                            ts_hash = m_hash.group(1)
                                            ts_port = m_port.group(1) if m_port else '8090'
                                            try:
                                                try:
                                                    from urllib.request import urlopen, Request
                                                except ImportError:
                                                    from urllib2 import urlopen, Request
                                                
                                                req_body = json.dumps({"action": "get", "hash": ts_hash}).encode('utf-8')
                                                req = Request('http://127.0.0.1:%s/torrents' % ts_port, data=req_body)
                                                req.add_header('Content-Type', 'application/json')
                                                resp = urlopen(req, timeout=5)
                                                data = json.loads(resp.read().decode('utf-8'))
                                                
                                                files = data.get('file_stats') or data.get('files') or []
                                                ep_in_pack = False
                                                for f in files:
                                                    fname = f.get('path', '') or f.get('name', '') or ''
                                                    if filename_matches(fname):
                                                        ep_in_pack = True
                                                        break
                                                checked = True
                                                log('[MRSP-NEXT] TorrServer: S%02dE%02d %s (%d fisiere)' % (
                                                    s_curr, next_ep,
                                                    'GASIT' if ep_in_pack else 'NU EXISTA',
                                                    len(files)))
                                            except Exception as ex:
                                                log('[MRSP-NEXT] Eroare TorrServer API: %s' % str(ex))
                                    
                                    # --- 2. Torrent2HTTP ---
                                    if not checked and '127.0.0.1:5001' in pf_check_full:
                                        try:
                                            try:
                                                from urllib.request import urlopen
                                            except ImportError:
                                                from urllib2 import urlopen
                                            
                                            resp = urlopen('http://127.0.0.1:5001/ls', timeout=5)
                                            data = json.loads(resp.read().decode('utf-8'))
                                            files = data.get('files') or []
                                            ep_in_pack = False
                                            for f in files:
                                                fname = f.get('name', '') or f.get('path', '') or ''
                                                if filename_matches(fname):
                                                    ep_in_pack = True
                                                    break
                                            checked = True
                                            log('[MRSP-NEXT] T2H: S%02dE%02d %s (%d fisiere)' % (
                                                s_curr, next_ep,
                                                'GASIT' if ep_in_pack else 'NU EXISTA',
                                                len(files)))
                                        except Exception as ex:
                                            log('[MRSP-NEXT] Eroare T2H: %s' % str(ex))
                                    
                                    # --- 3. Elementum / Orice: parsare .torrent local ---
                                    if not checked:
                                        torrent_path = None
                                        try:
                                            try:
                                                from urllib.parse import unquote as url_unq
                                            except:
                                                from urllib import unquote as url_unq
                                            
                                            # 3a. Din URL-ul Elementum (uri=C%3A%5C...)
                                            m_uri = re.search(r'uri=([^&|]+)', pf_check_full)
                                            if m_uri:
                                                decoded = url_unq(m_uri.group(1))
                                                if decoded.endswith('.torrent') and os.path.isfile(decoded):
                                                    torrent_path = decoded
                                            
                                            # 3b. Din link-ul original (poate fi encodat)
                                            if not torrent_path and link_for_check:
                                                decoded_link = url_unq(link_for_check)
                                                if decoded_link.endswith('.torrent') and os.path.isfile(decoded_link):
                                                    torrent_path = decoded_link
                                                elif decoded_link.startswith('file://'):
                                                    decoded = url_unq(decoded_link[7:])
                                                    if os.path.isfile(decoded):
                                                        torrent_path = decoded
                                            
                                            # 3c. Din %TEMP%/md5(link).torrent
                                            if not torrent_path and link_for_check:
                                                import tempfile
                                                link_hash = hashlib.md5(link_for_check.encode('utf-8', 'ignore')).hexdigest()
                                                tmp_path = os.path.join(tempfile.gettempdir(), link_hash + '.torrent')
                                                if os.path.isfile(tmp_path):
                                                    torrent_path = tmp_path
                                        except: pass
                                        
                                        if torrent_path:
                                            try:
                                                filenames = parse_torrent_files(torrent_path)
                                                ep_in_pack = False
                                                for fn in filenames:
                                                    if filename_matches(fn):
                                                        ep_in_pack = True
                                                        break
                                                checked = True
                                                log('[MRSP-NEXT] Bencode: S%02dE%02d %s (%d fisiere, %s)' % (
                                                    s_curr, next_ep,
                                                    'GASIT' if ep_in_pack else 'NU EXISTA',
                                                    len(filenames),
                                                    os.path.basename(torrent_path)))
                                            except Exception as ex:
                                                log('[MRSP-NEXT] Eroare Bencode: %s' % str(ex))
                                    
                                    # --- 4. FALLBACK SIGUR ---
                                    if not checked:
                                        # === START MODIFICARE: SUPORT NEXT EPISODE AIO / DEBRID ===
                                        is_http_debrid = str(link_for_check).startswith('http') and '127.0.0.1' not in str(link_for_check)
                                        if site == 'aiostreams' or is_http_debrid:
                                            ep_in_pack = True
                                            log('[MRSP-NEXT] HTTP/Debrid detectat (AIO). Permitem prompt-ul pt a declansa search fallback.')
                                        else:
                                            ep_in_pack = False
                                            log('[MRSP-NEXT] Nicio metoda nu a confirmat S%02dE%02d. STOP.' % (s_curr, next_ep))
                                        # === SFARSIT MODIFICARE ===
                                
                                except Exception as ex_pack:
                                    log('[MRSP-NEXT] Eroare verificare pack: %s' % str(ex_pack))
                                    ep_in_pack = False
                                # ============================================================
                                
                                if not ep_in_pack:
                                    log('[MRSP-NEXT] S%02dE%02d NU exista in pack! Auto-play OPRIT. (ultimul: S%02dE%02d)' % (
                                        s_curr, next_ep, s_curr, e_curr))
                                else:
                                    log('[MRSP-NEXT] Terminat S%02dE%02d. Propun S%02dE%02d' % (s_curr, e_curr, s_curr, next_ep))
                                    
                                    xbmc.sleep(500)
                                    ret = xbmcgui.Dialog().yesno(
                                        '[B][COLOR FFFDBD01]MRSP Lite[/COLOR][/B]',
                                        '[B][COLOR FF6AFB92]%s [/COLOR][/B][B][COLOR red]S%02dE%02d[/COLOR][/B] terminat.\n\nPornești [B][COLOR yellow]S%02dE%02d[/COLOR][/B]?' % (clean_show, s_curr, e_curr, s_curr, next_ep),
                                        yeslabel='Da', nolabel='Nu', autoclose=60000)
                                    
                                    if ret:
                                        log('[MRSP-NEXT] DA → S%02dE%02d' % (s_curr, next_ep))
                                        xbmcgui.Window(10000).setProperty('mrsp.next_episode_active', 'true')
                                        xbmcgui.Window(10000).setProperty('mrsp.elem.autoselect.season', str(s_curr))
                                        xbmcgui.Window(10000).setProperty('mrsp.elem.autoselect.episode', str(next_ep))
                                        
                                        t_id = info_c.get('tmdb_id') or self.detalii.get('tmdb_id', '')
                                        i_id = info_c.get('imdb_id') or info_c.get('imdb') or self.detalii.get('imdb_id', '')
                                        if t_id:
                                            xbmcgui.Window(10000).setProperty('tmdb_id', str(t_id))
                                            xbmcgui.Window(10000).setProperty('TMDb_ID', str(t_id))
                                        if i_id:
                                            xbmcgui.Window(10000).setProperty('imdb_id', str(i_id))
                                            xbmcgui.Window(10000).setProperty('IMDb_ID', str(i_id))

                                        try:
                                            _info = info_c if info_c else {}
                                            _fanart = _info.get('Fanart') or _info.get('fanart') or ''
                                            _logo = _info.get('ClearLogo') or _info.get('clearlogo') or ''
                                            if _fanart: xbmcgui.Window(10000).setProperty('info.fanart', str(_fanart))
                                            if _logo: xbmcgui.Window(10000).setProperty('info.clearlogo', str(_logo))
                                        except: pass
                                        
                                        link = self.detalii.get('link') or self.detalii.get('landing', '')
                                        
                                        new_info = info_c.copy() if info_c else {}
                                        new_info['Season'] = s_curr
                                        new_info['Episode'] = next_ep
                                        if t_id: new_info['tmdb_id'] = t_id
                                        if i_id: new_info['imdb_id'] = i_id
                                        
                                        # === FIX TMDB OVERLAP PENTRU TORRSERVER ===
                                        new_info['mediatype'] = 'episode'
                                        new_info['TVShowTitle'] = clean_show
                                        try:
                                            _fanart = info_c.get('Fanart') or info_c.get('fanart') or ''
                                            _logo = info_c.get('ClearLogo') or info_c.get('clearlogo') or ''
                                            if _fanart: new_info['Fanart'] = _fanart
                                            if _logo: new_info['ClearLogo'] = _logo
                                        except: pass
                                        # ==========================================
                                        
                                        next_detalii = self.detalii.copy()
                                        next_detalii['info'] = new_info
                                        next_detalii['season'] = str(s_curr)
                                        next_detalii['episode'] = str(next_ep)
                                        if i_id: next_detalii['mrsp_resume_id'] = 'imdb_%s_S%02dE%02d' % (i_id, s_curr, next_ep)
                                        elif t_id: next_detalii['mrsp_resume_id'] = 'tmdb_%s_S%02dE%02d' % (t_id, s_curr, next_ep)
                                        xbmcgui.Window(10000).setProperty('mrsp.data', str(next_detalii))
                                        
                                        try:
                                            xbmcgui.Window(10000).setProperty('mrsp.check_resume', 'true')
                                            
                                            from resources.functions import openTorrent as otFunc, quote as q
                                            
                                            orig_u = self.detalii.get('landing') or link
                                            
                                            # === START MODIFICARE: FORTARE SEARCH PENTRU AIO / DEBRID ===
                                            is_http_debrid = str(orig_u).startswith('http') and '127.0.0.1' not in str(orig_u)
                                            if site == 'aiostreams' or is_http_debrid:
                                                raise Exception("Link direct Debrid/HTTP -> Fortam cautare episod nou.")
                                            # === SFARSIT MODIFICARE ===
                                            
                                            otFunc({
                                                'Turl': q(link),
                                                'Tsite': site,
                                                'orig_url': orig_u,
                                                'info': q(str(new_info))
                                            })
                                        except Exception as e_play:
                                            log('[MRSP-NEXT] Eroare play direct: %s. Fallback căutare.' % str(e_play))
                                            search = '%s S%02dE%02d' % (clean_show, s_curr, next_ep)
                                            url = 'plugin://plugin.video.romanianpack/?action=searchSites&searchSites=cuvant&cuvant=%s&Stype=torrs' % search.replace(' ', '+')
                                            if t_id: url += '&tmdb_id=%s' % t_id
                                            if i_id: url += '&imdb_id=%s' % i_id
                                            xbmc.executebuiltin('RunPlugin(%s)' % url)
                    except Exception as e_next:
                        log('[MRSP-NEXT] Eroare: %s' % str(e_next))


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

    # Ștergere automată resume-uri vechi la pornirea Kodi
    try:
        if xbmcaddon.Addon(id=aid).getSetting('auto_clear_resume') == 'true':
            days = int(xbmcaddon.Addon(id=aid).getSetting('auto_clear_resume_days') or 30)
            import time
            try:
                from sqlite3 import dbapi2 as database
            except:
                from pysqlite2 import dbapi2 as database
            from resources.functions import addonCache, get_time
            
            cutoff = get_time() - (days * 86400)
            dbcon = database.connect(addonCache)
            dbcur = dbcon.cursor()
            dbcur.execute("SELECT count(*) FROM resume WHERE date < ?", (str(cutoff),))
            old_count = dbcur.fetchone()[0]
            if old_count > 0:
                dbcur.execute("DELETE FROM resume WHERE date < ?", (str(cutoff),))
                try: dbcur.execute("VACUUM")
                except: pass
                dbcon.commit()
                log('[MRSP-SERVICE] Auto-cleanup: %d resume-uri vechi șterse (>%d zile)' % (old_count, days))
    except Exception as e:
        log('[MRSP-SERVICE] Eroare auto-cleanup resume: %s' % str(e))

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


