# -*- coding: utf-8 -*-
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

# ==============================================================================
# LISTA ADDON-URILOR ROMANESTI
# ==============================================================================
ROMANIAN_ADDONS = [
    "service.subtitles.subsro",
    "service.subtitles.regielive",
    "service.subtitles.titrariro",
    "service.subtitles.subtitrarinoiro"
    "service.subtitles.subsroteam"
]

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
                if not self.isPlaying(): return 

        movieFullPath = self.getPlayingFile()
        if self.isExcluded(movieFullPath):
            log("Video exclus de la cautare conform setarilor.")
            return

        # --- LOGICA DESTEAPTA DE VERIFICARE LIMBI ---
        current_addon_id = self.get_preferred_addon()
        availableLangs = self.getAvailableSubtitleStreams() # Ex: ['eng', 'fre', 'unknown']
        
        # 1. LISTA LIMBI PRIORITARE (ROMANA)
        priority_langs = []
        if current_addon_id in ROMANIAN_ADDONS:
            priority_langs.extend(['rum', 'ro', 'ron'])
        else:
            if __addon__.getSetting('check_for_specific') == 'true':
                lang_a = __addon__.getSetting('selected_languagea')
                try: priority_langs.append(xbmc.convertLanguage(lang_a, xbmc.ISO_639_2))
                except: pass
                
                if __addon__.getSetting('check_for_specificb') == 'true':
                    lang_b = __addon__.getSetting('selected_languageb')
                    try: priority_langs.append(xbmc.convertLanguage(lang_b, xbmc.ISO_639_2))
                    except: pass

        # 2. LISTA LIMBI FALLBACK (UNKNOWN)
        unknown_identifiers = []
        if __addon__.getSetting('check_for_external') == 'true':
            unknown_identifiers = ['und', 'unk', '', 'None', '(External)', 'External', 'external', 'Unknown', 'unknown']

        # 3. VERIFICARE SI DECIZIE
        should_search = False
        found_index = -1
        
        if not xbmc.getCondVisibility("VideoPlayer.HasSubtitles"):
            should_search = True
            log("Nu exista nicio subtitrare. Se cauta.")
        else:
            # A. Verificam intai daca exista ROMANA (Prioritate Maxima)
            for i, stream_lang in enumerate(availableLangs):
                if stream_lang in priority_langs:
                    found_index = i
                    log("Gasit subtitrare prioritara (Romana): '%s' la index %d" % (stream_lang, i))
                    break
            
            # B. Daca NU am gasit Romana, verificam UNKNOWN cu regula stricta
            if found_index == -1 and unknown_identifiers:
                # REGULA STRICTA: Acceptam Unknown DOAR daca este SINGURA subtitrare disponibila.
                # Daca sunt mai multe (ex: Eng + Unknown), presupunem ca Unknown e internal/gresit si cautam Romana.
                if len(availableLangs) == 1:
                    single_lang = availableLangs[0]
                    if single_lang in unknown_identifiers:
                        found_index = 0
                        log("Acceptat 'Unknown' ('%s') deoarece este SINGURA subtitrare disponibila (probabil External)." % single_lang)
                else:
                    # Avem mai multe subtitrari si niciuna nu e Romana.
                    # Chiar daca una e Unknown, o ignoram.
                    log("Exista fluxuri (%s) dar niciunul nu e Romana. Ignor 'Unknown' (fiindca sunt multiple) si caut." % availableLangs)

            # C. Executie
            if found_index >= 0:
                # Activam subtitrarea gasita
                self.setSubtitleStream(found_index)
                xbmc.executebuiltin('ShowSubtitles')
                if __addon__.getSetting('notify_found') == 'true':
                    xbmcgui.Dialog().notification("[B][COLOR FF00BFFF]Fast AutoSubs[/COLOR][/B]", "Activată subtitrarea existentă!", xbmcgui.NOTIFICATION_INFO, 2000)
            else:
                # Nu am gasit nimic satisfacator -> Cautam
                should_search = True

        if should_search:
            self.trigger_smart_subtitles(current_addon_id)

    def onPlayBackResumed(self):
        self.wait = False

    def onPlayBackStopped(self):
        self.wait = False
    
    def onPlayBackEnded(self):
        self.wait = False

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
            query = {"jsonrpc": "2.0", "method": "Settings.GetSettingValue", "params": {"setting": setting_key}, "id": 1}
            response = xbmc.executeJSONRPC(json.dumps(query))
            result = json.loads(response)
            if 'result' in result and 'value' in result['result']:
                return result['result']['value']
        except: pass
        return ""

    def isExcluded(self, movieFullPath):
        try:
            exclude_time = int(__addon__.getSetting('ExcludeTime')) * 60
            if self.getTotalTime() < exclude_time:
                log("Durata prea mica (< %s sec). Skip." % exclude_time)
                return True
        except: pass

        ignore_words = __addon__.getSetting('ignore_words').split(',')
        if any(word.lower() in movieFullPath.lower() for word in ignore_words if word):
            log("Calea contine cuvinte ignorate. Skip.")
            return True

        if not movieFullPath: return True
        if "youtube" in str(movieFullPath).lower(): return True
        if "pvr://" in movieFullPath and __addon__.getSetting('ExcludeLiveTV') == 'true': return True
        if "http://" in movieFullPath and __addon__.getSetting('ExcludeHTTP') == 'true': return True
        
        if __addon__.getSetting('ExcludeAddonOption') == 'true':
            ex_addon = __addon__.getSetting('ExcludeAddon')
            if ex_addon and ex_addon in movieFullPath: return True

        for i in ['', '2']:
            opt = 'ExcludePathOption' + i
            path_set = 'ExcludePath' + i
            if __addon__.getSetting(opt) == 'true':
                path = __addon__.getSetting(path_set)
                if path and path in movieFullPath: return True

        return False

if __name__ == '__main__':
    log("Serviciul Fast AutoSubs a pornit.")
    player = AutoSubsPlayer()
    monitor = xbmc.Monitor()

    while not monitor.abortRequested():
        if monitor.waitForAbort(1): break

    del player
    log("Serviciul Fast AutoSubs oprit.")