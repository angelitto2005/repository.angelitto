# -*- coding: utf-8 -*-
import os
import xbmc
import xbmcgui
import xbmcaddon
import json
import time

# ==============================================================================
# CONFIGURARE ADDON
# ==============================================================================
__scriptid__ = 'script.service.fastautosubs'
__addon__ = xbmcaddon.Addon(id=__scriptid__)

ADDON_PATH = __addon__.getAddonInfo('path')
FAS_ICON = os.path.join(ADDON_PATH, 'icon.png')

# ==============================================================================
# LISTA ADDON-URILOR ROMANESTI
# ==============================================================================
ROMANIAN_ADDONS = [
    "service.subtitles.subsro",
    "service.subtitles.regielive",
    "service.subtitles.titrariro",
    "service.subtitles.subtitrarinoiro",  # <-- LIPSEA VIRGULA AICI!
    "service.subtitles.subsroteam"
]

# ==============================================================================
# TAG-URI SURSE ROMANESTI (Filelist + Speedapp)
# ==============================================================================
ROMANIAN_SOURCE_TAGS = [
    # Filelist
    "playweb", "playhd", "playsd", "playtv",
    # Speedapp
    "sphd", "spdvd", "spweb", "spsd", "sptv", "bbad"
]

# ==============================================================================
# CODURI LIMBA ROMANA
# ==============================================================================
ROMANIAN_LANG_CODES = ['rum', 'ro', 'ron', 'romanian']

# ==============================================================================
# CODURI PENTRU SUBTITRARI NECUNOSCUTE/EXTERNE
# ==============================================================================
UNKNOWN_EXTERNAL_CODES = ['und', 'unk', '', 'None', '(External)', 'External', 'external', 'Unknown', 'unknown']


def log(msg):
    xbmc.log("### [%s] - %s" % (__scriptid__, msg), level=xbmc.LOGINFO)


class AutoSubsPlayer(xbmc.Player):
    def __init__(self):
        super(AutoSubsPlayer, self).__init__()
        self.wait = False

    def onPlayBackStarted(self):
        timeout = 0
        while self.isPlaying() and not self.isPlayingVideo() and timeout < 20:
            xbmc.sleep(250)
            timeout += 0.25
        
        if not self.isPlayingVideo():
            return

        if __addon__.getSetting('enable_autosub') != 'true':
            return

        log("Redare detectata. Verific conditiile pentru AutoSub...")
        xbmc.sleep(2500)

        if xbmc.getCondVisibility('Player.Paused'):
            self.wait = True
            while self.wait:
                xbmc.sleep(500)
                if not self.isPlaying(): 
                    return 

        movieFullPath = self.getPlayingFile()
        if self.isExcluded(movieFullPath):
            log("Video exclus de la cautare conform setarilor.")
            return

        # --- LOGICA NOUA DE VERIFICARE LIMBI ---
        current_addon_id = self.get_preferred_addon()
        availableLangs = self.getAvailableSubtitleStreams()
        
        # Determinam tipul sursei
        is_local = self.is_local_source(movieFullPath)
        is_romanian_source = self.is_romanian_online_source(movieFullPath)
        
        log("Analiza sursa: Cale='%s' | Local=%s | SursaRO=%s" % (movieFullPath, is_local, is_romanian_source))
        log("Subtitrari disponibile: %s" % availableLangs)
        
        # Construim lista limbilor acceptate
        accepted_langs = []

        # 1. INTOTDEAUNA acceptam subtitrari cu cod explicit de limba romana
        accepted_langs.extend(ROMANIAN_LANG_CODES)

        # 2. Acceptam "unknown/external" DOAR pentru surse locale SAU surse online romanesti
        allow_unknown = False
        if __addon__.getSetting('check_for_external') == 'true':
            if is_local:
                allow_unknown = True
                log("Sursa LOCALA detectata - accept subtitrari unknown/external")
            elif is_romanian_source:
                allow_unknown = True
                log("Sursa ROMANEASCA ONLINE detectata - accept subtitrari unknown/external")
            else:
                log("Sursa ONLINE STRAINA - NU accept subtitrari unknown/external")
        
        if allow_unknown:
            accepted_langs.extend(UNKNOWN_EXTERNAL_CODES)

        # 3. Adaugam alte limbi daca addon-ul nu e romanesc
        if current_addon_id not in ROMANIAN_ADDONS:
            if __addon__.getSetting('check_for_specific') == 'true':
                lang_a = __addon__.getSetting('selected_languagea')
                try: 
                    accepted_langs.append(xbmc.convertLanguage(lang_a, xbmc.ISO_639_2))
                except: 
                    pass
                
                if __addon__.getSetting('check_for_specificb') == 'true':
                    lang_b = __addon__.getSetting('selected_languageb')
                    try: 
                        accepted_langs.append(xbmc.convertLanguage(lang_b, xbmc.ISO_639_2))
                    except: 
                        pass

        log("Limbi acceptate finale: %s" % accepted_langs)

        # 4. VERIFICARE FINALA
        should_search = False
        
        if not xbmc.getCondVisibility("VideoPlayer.HasSubtitles"):
            should_search = True
            log("Nu exista nicio subtitrare. Se cauta.")
        else:
            found = False
            found_lang = ""
            found_index = -1
            
            for i, stream_lang in enumerate(availableLangs):
                # Verificam daca limba curenta e in lista acceptata
                if stream_lang in accepted_langs:
                    # VERIFICARE SUPLIMENTARA: daca e unknown/external la sursa online straina, SKIP
                    if stream_lang in UNKNOWN_EXTERNAL_CODES and not allow_unknown:
                        log("Ignoram subtitrare '%s' (unknown/external la sursa online straina)" % stream_lang)
                        continue
                    
                    found = True
                    found_lang = stream_lang
                    found_index = i
                    break
            
            if not found:
                should_search = True
                log("Limbile dorite %s lipsesc din fluxurile existente %s. Se initiaza cautarea." % (accepted_langs, availableLangs))
            else:
                log("S-a gasit limba acceptata: '%s' la index %d. Nu este necesara cautarea." % (found_lang, found_index))
                self.force_internal_subtitle(accepted_langs, allow_unknown)

        if should_search:
            self.trigger_smart_subtitles(current_addon_id)

    def onPlayBackResumed(self):
        self.wait = False

    def onPlayBackStopped(self):
        self.wait = False
    
    def onPlayBackEnded(self):
        self.wait = False

    # ==========================================================================
    # METODE NOI PENTRU DETECTIE TIP SURSA
    # ==========================================================================
    
    def is_local_source(self, path):
        """
        Verifica daca sursa este locala (fisier pe HDD/biblioteca Kodi).
        Returneaza True pentru: /path/to/file, C:\path\to\file, smb://, nfs://
        Returneaza False pentru: http://, https://, plugin://, pvr://
        """
        if not path:
            return False
        
        path_lower = path.lower()
        
        # Protocoale online -> NU e local
        online_protocols = ['http://', 'https://', 'plugin://', 'pvr://', 'upnp://', 'ftp://']
        for protocol in online_protocols:
            if path_lower.startswith(protocol):
                return False
        
        # Verificam daca e cale locala sau retea locala (SMB/NFS)
        # Cai Linux/Mac: incep cu /
        # Cai Windows: litera:\
        # Cai retea locala: smb://, nfs://
        local_indicators = ['smb://', 'nfs://']
        
        if path.startswith('/'):
            return True
        if len(path) > 2 and path[1] == ':':  # C:\, D:\, etc.
            return True
        for indicator in local_indicators:
            if path_lower.startswith(indicator):
                return True
        
        # Verificam si daca e continut din biblioteca Kodi
        if xbmc.getCondVisibility('!String.IsEmpty(VideoPlayer.DBID)'):
            log("Fisier din biblioteca Kodi detectat")
            return True
        
        return False

    def is_romanian_online_source(self, path):
        """
        Verifica daca sursa online are tag-uri romanesti (Filelist/Speedapp).
        Tag-uri: playWEB, playHD, playSD, playTV, SPHD, SPDVD, SPWEB, SPSD, SPTV, BBAD
        """
        if not path:
            return False
        
        path_lower = path.lower()
        
        for tag in ROMANIAN_SOURCE_TAGS:
            if tag.lower() in path_lower:
                log("Tag romanesc gasit: '%s' in '%s'" % (tag, path))
                return True
        
        return False

    # ==========================================================================
    # METODA ACTUALIZATA PENTRU ACTIVARE SUBTITRARE
    # ==========================================================================
    
    def force_internal_subtitle(self, target_langs, allow_unknown=False):
        """
        Activeaza subtitrarea interna potrivita.
        Prioritate: limba romana explicita > unknown (daca e permis)
        """
        try:
            available = self.getAvailableSubtitleStreams()
            idx_to_select = -1
            
            # PRIORITATE 1: Cautam subtitrare cu limba romana explicita
            for i, lang in enumerate(available):
                if lang in ROMANIAN_LANG_CODES:
                    idx_to_select = i
                    log("Gasita subtitrare ROMANA la index %d (cod: %s)" % (i, lang))
                    break
            
            # PRIORITATE 2: Daca nu am gasit romana si e permis, cautam unknown/external
            if idx_to_select < 0 and allow_unknown:
                for i, lang in enumerate(available):
                    if lang in UNKNOWN_EXTERNAL_CODES:
                        idx_to_select = i
                        log("Gasita subtitrare unknown/external la index %d (cod: %s)" % (i, lang))
                        break
            
            # PRIORITATE 3: Alte limbi din lista acceptata
            if idx_to_select < 0:
                for i, lang in enumerate(available):
                    if lang in target_langs and lang not in UNKNOWN_EXTERNAL_CODES:
                        idx_to_select = i
                        log("Gasita subtitrare alternativa la index %d (cod: %s)" % (i, lang))
                        break
            
            if idx_to_select >= 0:
                log("Activare subtitrare interna index: %d (%s)" % (idx_to_select, available[idx_to_select]))
                self.setSubtitleStream(idx_to_select)
                xbmc.executebuiltin('ShowSubtitles')
                
                # VERIFICARE SETARE PENTRU NOTIFICARE
                if __addon__.getSetting('notify_found') == 'true':
                    xbmcgui.Dialog().notification(
                        "[B][COLOR FF00BFFF]Fast AutoSubs[/COLOR][/B]", 
                        "Activată subtitrarea existentă!", 
                        FAS_ICON, 
                        2000
                    )
            else:
                log("Nu s-a gasit nicio subtitrare potrivita pentru activare")
                
        except Exception as e:
            log("Eroare la force_internal_subtitle: %s" % str(e))

    def trigger_smart_subtitles(self, current_addon_id):
        # Citim setarea din meniu (True sau False)
        pause_enabled = __addon__.getSetting('pause_on_search') == 'true'

        if current_addon_id in ROMANIAN_ADDONS:
            log("Rulare RunScript (Background) pentru: %s" % current_addon_id)
            
            # --- CAZUL 1: NU PUNEM PAUZA (Modul vechi / Rapid) ---
            if not pause_enabled:
                xbmc.executebuiltin('RunScript(%s, -1, ?action=search&languages=Romanian)' % current_addon_id)
                return

            # --- CAZUL 2: PUNEM PAUZA (Modul nou / Smart) ---
            
            # 1. Punem pauza
            if not xbmc.getCondVisibility('Player.Paused'):
                log("Initiez cautarea. Pun pauza la video...")
                self.pause()

            # 2. Memoram nr. subtitrari existente
            try:
                initial_subs_count = len(self.getAvailableSubtitleStreams())
            except:
                initial_subs_count = 0

            # 3. Lansam cautarea
            xbmc.executebuiltin('RunScript(%s, -1, ?action=search&languages=Romanian)' % current_addon_id)
            
            # 4. Bucla de asteptare
            log("Astept descarcarea subtitrarii (Max 15 sec)...")
            waited = 0
            timeout = 15 
            
            while waited < timeout:
                xbmc.sleep(1000)
                waited += 1
                
                # Daca utilizatorul a dat Play manual, iesim
                if not xbmc.getCondVisibility('Player.Paused'):
                    log("Utilizatorul a reluat redarea manual. Iesim.")
                    return

                # Verificam daca a aparut subtitrarea
                try:
                    current_subs_count = len(self.getAvailableSubtitleStreams())
                except:
                    current_subs_count = 0

                if current_subs_count > initial_subs_count:
                    log("Subtitrare noua detectata! Reluam filmul.")
                    self.setSubtitleStream(current_subs_count - 1)
                    xbmc.executebuiltin('ShowSubtitles')
                    break
            
            # 5. Reluam redarea (scoatem pauza daca inca e activa)
            if xbmc.getCondVisibility('Player.Paused'):
                self.pause()

        else:
            # PENTRU ADDON-URI STANDARD (GUI)
            log("Rulare Standard GUI pentru: %s" % current_addon_id)
            
            # Optional: Punem pauza si aici daca setarea e activa
            if pause_enabled and not xbmc.getCondVisibility('Player.Paused'):
                self.pause()
                
            xbmc.executebuiltin('ActivateWindow(SubtitleSearch)')

    def get_preferred_addon(self):
        try:
            is_tv = xbmc.getCondVisibility('VideoPlayer.Content(tvshows)')
            setting_key = "subtitles.tv" if is_tv else "subtitles.movie"
            query = {
                "jsonrpc": "2.0", 
                "method": "Settings.GetSettingValue", 
                "params": {"setting": setting_key}, 
                "id": 1
            }
            response = xbmc.executeJSONRPC(json.dumps(query))
            result = json.loads(response)
            if 'result' in result and 'value' in result['result']:
                return result['result']['value']
        except: 
            pass
        return ""

    def isExcluded(self, movieFullPath):
        # ======================================================================
        # 1. Verificare Durata (pentru filme normale)
        # ======================================================================
        try:
            # Daca e LiveTV veritabil, duration e adesea 0 sau foarte mare, 
            # dar la VOD din PVR are durata corecta. Verificam totusi.
            exclude_time = int(__addon__.getSetting('ExcludeTime')) * 60
            total_time = self.getTotalTime()
            if total_time > 0 and total_time < exclude_time:
                log("Durata prea mica (< %s sec). Skip." % exclude_time)
                return True
        except: 
            pass

        # ======================================================================
        # 2. EXCLUDERE LIVE TV / PVR (Verificare Extinsa)
        # ======================================================================
        if __addon__.getSetting('ExcludeLiveTV') == 'true':
            # A. Verificam Flag-ul intern Kodi
            if xbmc.getCondVisibility('VideoPlayer.Content(livetv)'):
                log("Detectat Live TV (Content Flag). Skip.")
                return True

            # B. Verificam InfoLabels (Aici apare pvr:// chiar daca ruleaza http)
            li_path = xbmc.getInfoLabel('ListItem.Path')
            li_file = xbmc.getInfoLabel('ListItem.FileNameAndPath')
            
            # Logam aceste valori ca sa fim siguri ce vede scriptul
            log("DEBUG PVR Check -> ListItem.Path: '%s' | ListItem.FileNameAndPath: '%s'" % (li_path, li_file))

            # Verificam daca apare 'pvr://' sau semnatura iptvsimple
            if "pvr://" in li_path or "pvr://" in li_file:
                log("Detectat PVR in ListItem (pvr://). Skip.")
                return True
            
            if "iptvsimple" in li_path or "iptvsimple" in li_file:
                log("Detectat IPTV Simple Client in ListItem. Skip.")
                return True
            
            # C. Verificam calea directa (just in case)
            if "pvr://" in movieFullPath:
                log("Detectat PVR in MovieFullPath. Skip.")
                return True

        # ======================================================================
        # 3. Verificare Cuvinte Ignorate
        # ======================================================================
        ignore_words = __addon__.getSetting('ignore_words').split(',')
        if any(word.strip().lower() in movieFullPath.lower() for word in ignore_words if word.strip()):
            log("Calea contine cuvinte ignorate. Skip.")
            return True

        if not movieFullPath: 
            return True
            
        # ======================================================================
        # 4. Alte excluderi standard
        # ======================================================================
        if "youtube" in str(movieFullPath).lower(): 
            return True
        if "http://" in movieFullPath and __addon__.getSetting('ExcludeHTTP') == 'true': 
            # ATENTIE: Aici ar putea intra VOD-ul daca nu e detectat sus ca PVR.
            # Dar daca detectia PVR de sus functioneaza, nu ajunge aici.
            log("Sursa HTTP exclusa conform setarilor.")
            return True
        
        # ======================================================================
        # 5. LISTA EXCLUDERI ADDON-URI (Playlist & Path)
        # ======================================================================
        excluded_addons = []
        if __addon__.getSetting('ExcludeAddonOption') == 'true':
            excluded_addons.append(__addon__.getSetting('ExcludeAddon'))
        if __addon__.getSetting('ExcludeAddonOption2') == 'true':
            excluded_addons.append(__addon__.getSetting('ExcludeAddon2'))
        if __addon__.getSetting('ExcludeAddonOption3') == 'true':
            excluded_addons.append(__addon__.getSetting('ExcludeAddon3'))
        
        excluded_addons = [x for x in excluded_addons if x]

        if excluded_addons:
            # Verificare in path curent
            for ex_id in excluded_addons:
                if ex_id in movieFullPath:
                    log("Addon exclus detectat in Calea Fisiereului (%s). Skip." % ex_id)
                    return True
            
            # Verificare in path original (ListItem)
            combined_labels = xbmc.getInfoLabel('ListItem.Path') + xbmc.getInfoLabel('ListItem.FileNameAndPath')
            for ex_id in excluded_addons:
                if ex_id in combined_labels:
                     log("Addon exclus detectat in InfoLabels (%s). Skip." % ex_id)
                     return True

            # Verificare in Playlist (Fallback)
            try:
                playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
                if playlist.size() > 0:
                    position = playlist.getposition()
                    if position != -1:
                        item = playlist.__getitem__(position)
                        playlist_path = item.getPath()
                        for ex_id in excluded_addons:
                            if ex_id in playlist_path:
                                log("Addon exclus detectat in Playlist (%s). Skip." % ex_id)
                                return True
            except:
                pass

        # ======================================================================
        # 6. Verificare Cai Folder (Local)
        # ======================================================================
        for i in ['', '2']:
            opt = 'ExcludePathOption' + i
            path_set = 'ExcludePath' + i
            if __addon__.getSetting(opt) == 'true':
                path = __addon__.getSetting(path_set)
                if path and path in movieFullPath: 
                    return True

        return False

if __name__ == '__main__':
    log("Serviciul Fast AutoSubs a pornit.")
    player = AutoSubsPlayer()
    monitor = xbmc.Monitor()

    while not monitor.abortRequested():
        if monitor.waitForAbort(1): 
            break

    del player
    log("Serviciul Fast AutoSubs oprit.")