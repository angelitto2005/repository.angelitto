# -*- coding: utf-8 -*-
import os
import re
import xbmc
import xbmcgui
import xbmcaddon
import xbmcvfs
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
    "service.subtitles.subtitrarinoiro",
    "service.subtitles.substudio"
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
EXTERNAL_ONLY_CODES = ['', '(External)', 'External', 'external']
EN_MISLABEL_CODES = ['en', 'eng', 'EN', 'ENG']

# ==============================================================================
# MOD SUBSTUDIO - OPENSUBTITLES (REST, ca TMDb Movies / SubStudio)
# ==============================================================================
SUBSTUDIO_ADDON_ID = "service.subtitles.substudio"

# Limba aleasa in SubStudio (setarea subs_languages) - ordinea din SubStudio
SUBSTUDIO_LANGS = ["ro", "en", "es", "fr", "de", "it", "hu", "pt", "ru", "tr", "bg", "el", "pl", "cs", "nl", "id", "ar"]

OS_REST_HEADERS = {'User-Agent': 'HotSubtitlesV1'}
OS_DL_PREFIX = 'https://subs5.strem.io/en/download/subencoding-stremio-utf8/src-api/file/'

# Normalizare ISO3 -> ISO1 pentru rezultatele OpenSubtitles
NORM_OS_LANG = {
    'rum': 'ro', 'ron': 'ro', 'ro': 'ro',
    'eng': 'en', 'en': 'en',
    'spa': 'es', 'es': 'es', 'spa_la': 'es',
    'fre': 'fr', 'fra': 'fr', 'fr': 'fr',
    'ger': 'de', 'de': 'de',
    'ita': 'it', 'it': 'it',
    'hun': 'hu', 'hu': 'hu',
    'por': 'pt', 'pt': 'pt', 'pb': 'pt', 'pob': 'pt',
    'rus': 'ru', 'ru': 'ru',
    'tur': 'tr', 'tr': 'tr',
    'bul': 'bg', 'bg': 'bg',
    'ell': 'el', 'gre': 'el', 'el': 'el',
    'pol': 'pl', 'pl': 'pl',
    'cze': 'cs', 'cs': 'cs',
    'dut': 'nl', 'nl': 'nl',
    'ara': 'ar', 'ar': 'ar',
    'chi': 'zh', 'zh': 'zh',
    'jpn': 'ja', 'ja': 'ja',
    'kor': 'ko', 'ko': 'ko',
    'swe': 'sv', 'sv': 'sv',
    'dan': 'da', 'da': 'da',
    'fin': 'fi', 'fi': 'fi',
    'nor': 'no', 'no': 'no',
    'hrv': 'hr', 'hr': 'hr',
    'srp': 'sr', 'sr': 'sr',
    'slv': 'sl', 'sl': 'sl',
    'slo': 'sk', 'sk': 'sk',
    'ukr': 'uk', 'uk': 'uk',
    'heb': 'he', 'he': 'he',
    'tha': 'th', 'th': 'th',
    'vie': 'vi', 'vi': 'vi',
    'ind': 'id', 'id': 'id',
    'may': 'ms', 'ms': 'ms',
    'hin': 'hi', 'hi': 'hi',
    'per': 'fa', 'fa': 'fa',
    'cat': 'ca', 'ca': 'ca',
    'baq': 'eu', 'eu': 'eu',
    'glg': 'gl', 'gl': 'gl',
    'est': 'et', 'et': 'et',
    'lav': 'lv', 'lv': 'lv',
    'lit': 'lt', 'lt': 'lt',
    'mac': 'mk', 'mk': 'mk',
    'alb': 'sq', 'sq': 'sq',
    'bos': 'bs', 'bs': 'bs',
    'ice': 'is', 'is': 'is'
}

# Cheie TMDb publica (folosita si de SubStudio) pentru rezolvarea titlu -> IMDb
TMDB_API_KEY = '8ad3c21a92a64da832c559d58cc63ab4'
TMDB_BASE_URL = 'https://api.themoviedb.org/3'

# Valori "junk" returnate de InfoLabels cand proprietatea nu e setata
JUNK_IDS = ('None', '', '0', 'VideoPlayer.TVShow.TMDbId', 'VideoPlayer.TMDbId', 'VideoPlayer.IMDBNumber')

# Folder temporar pentru srt-urile descarcate
OS_SUBS_FOLDER = 'special://temp/fastautosubs_subs/'


def log(msg):
    xbmc.log("### [%s] - %s" % (__scriptid__, msg), level=xbmc.LOGINFO)


class AutoSubsPlayer(xbmc.Player):
    def __init__(self):
        super(AutoSubsPlayer, self).__init__()
        self.wait = False

    def onAVStarted(self):
        timeout = 0
        while self.isPlaying() and not self.isPlayingVideo() and timeout < 120:
            xbmc.sleep(250)
            timeout += 1
        
        if not self.isPlayingVideo():
            return

        if __addon__.getSetting('enable_autosub') != 'true':
            return

        log("Redare detectata. Verific conditiile pentru AutoSub...")
        xbmc.sleep(3000)

        if xbmc.getCondVisibility('Player.Paused'):
            self.wait = True
            while self.wait:
                xbmc.sleep(500)
                if not self.isPlaying(): 
                    return 

        movieFullPath = ""
        retry_path = 0
        while retry_path < 20:
            try:
                movieFullPath = self.getPlayingFile()
                if movieFullPath:
                    break
            except RuntimeError:
                pass
            xbmc.sleep(250)
            retry_path += 1

        if not movieFullPath:
            log("EROARE: Nu s-a putut obtine calea fisierului (RuntimeError).")
            return
        if self.isExcluded(movieFullPath):
            log("Video exclus de la cautare conform setarilor.")
            return

        # --- LOGICA NOUA DE VERIFICARE LIMBI ---
        current_addon_id = self.get_preferred_addon()
        try:
            availableLangs = self.getAvailableSubtitleStreams()
        except:
            availableLangs = []

        # Optiune noua: accept_any_external (override, implicit OFF)
        # Daca exista deja vreo subtitrare incarcata (orice limba: unknown, EN, RO, DE, etc.),
        # o acceptam si nu mai cautam online. Subtitrarea ramane exact cum a lasat-o Kodi.
        accept_external = __addon__.getSetting('accept_any_external') == 'true'
        external_streams = [l for l in availableLangs if l in EXTERNAL_ONLY_CODES]
        is_torrserver = self.is_torrserver_source(movieFullPath)
        torrserver_en_only = (is_torrserver and len(availableLangs) > 0
                              and all(l in EN_MISLABEL_CODES for l in availableLangs))
        if accept_external and (external_streams or torrserver_en_only):
            if external_streams:
                log("accept_any_external: subtitrare externa detectata %s (toate fluxurile: %s) - nu mai cautam online" % (external_streams, availableLangs))
            else:
                log("accept_any_external: sursa TorrServer cu subtitrari doar eng %s (posibil RO etichetat gresit) - nu mai cautam online" % (availableLangs,))
            # NOTIFICARE NOUA - doar pentru optiunea accept_any_external
            if __addon__.getSetting('notify_found') == 'true':
                xbmcgui.Dialog().notification(
                    "[B][COLOR FF00BFFF]Fast AutoSubs[/COLOR][/B]",
                    "Activată subtitrarea externă existentă!",
                    FAS_ICON,
                    3000
                )
            return
        if accept_external:
            log("accept_any_external: doar fluxuri cu limba cunoscuta %s - continui logica normala" % availableLangs)

        # Determinam tipul sursei
        is_local = self.is_local_source(movieFullPath)
        is_romanian_source = self.is_romanian_online_source(movieFullPath)
        
        log("Analiza sursa: Cale='%s' | Local=%s | SursaRO=%s" % (movieFullPath, is_local, is_romanian_source))
        log("Subtitrari disponibile: %s" % availableLangs)
        
        # Construim lista limbilor acceptate
        accepted_langs = []

        # Determinam providerul activ (Subs.ro / SubStudio)
        provider = __addon__.getSetting('subtitle_provider')
        is_substudio = (provider == '1') or ('substudio' in str(provider).lower())

        if is_substudio:
            # --- MOD SUBSTUDIO (useri din toata lumea): prioritatea o are limba aleasa in SubStudio ---
            sub_lang = self.get_substudio_language()
            if not sub_lang:
                sub_lang = self.get_fastas_language()
            if not sub_lang:
                sub_lang = 'ro'
            accepted_langs.append(sub_lang)                                            # ex: es
            accepted_langs.append(sub_lang.upper())                                    # ex: ES
            try:
                accepted_langs.append(xbmc.convertLanguage(sub_lang, xbmc.ISO_639_2))  # ex: spa
            except:
                pass
            try:
                name = xbmc.convertLanguage(sub_lang, xbmc.ENGLISH_NAME)               # ex: Spanish
                if name:
                    accepted_langs.append(name)
            except:
                pass
            log("Mod SubStudio: limba prioritara pentru subtitrari existente: %s" % accepted_langs)
        else:
            # --- MOD SUBS.RO (doar romani): romana are prioritate ---
            accepted_langs.extend(ROMANIAN_LANG_CODES)

            # Alte limbi doar daca addon-ul implicit nu e romanesc
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

        # Acceptam "unknown/external" DOAR pentru surse locale SAU surse online romanesti
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
        Returneaza True pentru: /path/to/file, C:/path/to/file, smb://, nfs://
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

    def is_torrserver_source(self, path):
        if not path:
            return False
        path_lower = path.lower()
        if ':8090/' in path_lower or 'torrserver' in path_lower or path_lower.endswith('.m3u'):
            log("Sursa TorrServer detectata: '%s'" % path)
            return True
        return False

    # ==========================================================================
    # METODA ACTUALIZATA PENTRU ACTIVARE SUBTITRARE
    # ==========================================================================
    
    def force_internal_subtitle(self, target_langs, allow_unknown=False):
        """
        Activeaza subtitrarea interna potrivita.
        Prioritate: limba prioritara a providerului (romana la Subs.ro, limba SubStudio la SubStudio) > unknown (daca e permis) > alte limbi acceptate
        """
        try:
            available = self.getAvailableSubtitleStreams()
            idx_to_select = -1

            # Determinam providerul activ (Subs.ro / SubStudio)
            provider = __addon__.getSetting('subtitle_provider')
            is_substudio = (provider == '1') or ('substudio' in str(provider).lower())

            if is_substudio:
                # MOD SUBSTUDIO (useri din toata lumea): prioritatea o are limba aleasa in SubStudio
                sub_lang = self.get_substudio_language()
                if not sub_lang:
                    sub_lang = self.get_fastas_language()
                if not sub_lang:
                    sub_lang = 'ro'
                priority_codes = [sub_lang, sub_lang.upper()]
                try:
                    priority_codes.append(xbmc.convertLanguage(sub_lang, xbmc.ISO_639_2))
                except:
                    pass
                log("Mod SubStudio: caut subtitrare existenta in limba prioritara %s" % priority_codes)
            else:
                # MOD SUBS.RO (doar romani): romana are prioritate
                priority_codes = list(ROMANIAN_LANG_CODES)

            # PRIORITATE 1: Cautam subtitrare in limba prioritara a providerului
            for i, lang in enumerate(available):
                if lang in priority_codes:
                    idx_to_select = i
                    log("Gasita subtitrare in limba prioritara la index %d (cod: %s)" % (i, lang))
                    break

            # PRIORITATE 2: Daca nu am gasit limba prioritara si e permis, cautam unknown/external
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
                if __addon__.getSetting('notify_found') == 'true':
                    xbmcgui.Dialog().notification(
                        "[B][COLOR FF00BFFF]Fast AutoSubs[/COLOR][/B]",
                        "Activată subtitrarea existentă!",
                        FAS_ICON,
                        2000
                    )
        except Exception as e:
            log("Eroare la force_internal_subtitle: %s" % str(e))

    def trigger_smart_subtitles(self, current_addon_id):
        # Citim providerul din setari: '0' = Subs.ro (romana), '1' = SubStudio (toate limbile)
        provider = __addon__.getSetting('subtitle_provider')
        # Kodi poate salva fie indexul ('1'), fie eticheta colorata a optiunii
        is_substudio = (provider == '1') or ('substudio' in str(provider).lower())

        if is_substudio:
            log("Provider SubStudio activ. Mod OpenSubtitles direct (ca TMDb Movies)...")
            self.trigger_opensubtitles()
            return

        # Provider Subs.ro (implicit) - doar limba romana
        log("Provider Subs.ro activ. Rulez subs.ro (doar limba romana)")
        current_addon_id = 'service.subtitles.subsro'

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

    # ==========================================================================
    # MOD SUBSTUDIO - OPENSUBTITLES DIRECT (ca TMDb Movies)
    # ==========================================================================

    def trigger_opensubtitles(self):
        try:
            import requests
        except ImportError:
            log("Modulul requests nu este disponibil. Deschid fereastra de subtitrari.")
            xbmc.executebuiltin('ActivateWindow(SubtitleSearch)')
            return

        # 1. Limba tinta: SubStudio decide (fallback: fastAS, apoi ro)
        target_lang = self.get_substudio_language()
        if not target_lang:
            target_lang = self.get_fastas_language()
        if not target_lang:
            target_lang = 'ro'
        log("Limba tinta OpenSubtitles: %s" % target_lang)

        pause_enabled = __addon__.getSetting('pause_on_search') == 'true'
        if pause_enabled and not xbmc.getCondVisibility('Player.Paused'):
            log("Pun pauza pentru cautarea OpenSubtitles...")
            self.pause()

        try:
            # 2. Identificare video (IMDb / sezon / episod)
            imdb_id, season, episode = self.get_video_identity(requests)
            if not imdb_id:
                log("Nu am putut identifica videoul (IMDb). Deschid fereastra de subtitrari.")
                self.open_subtitle_search(pause_enabled)
                return

            # 3. Cautare pe OpenSubtitles
            subs_list = self.os_search(requests, imdb_id, season, episode, target_lang)
            if not subs_list:
                log("Nicio subtitrare in limba '%s' pe OpenSubtitles. Deschid fereastra de subtitrari." % target_lang)
                self.open_subtitle_search(pause_enabled)
                return

            # 4. Curatam folderul de subtitrari vechi si descarcam TOATE srt-urile
            self.cleanup_os_folder()
            downloaded = []
            for i, sub in enumerate(subs_list):
                path = self.os_download(requests, sub, i)
                if path:
                    downloaded.append(path)

            if not downloaded:
                log("Niciun srt nu a putut fi descarcat. Deschid fereastra de subtitrari.")
                self.open_subtitle_search(pause_enabled)
                return

            # 4b. Subtitrari locale salvate de SubStudio (Translated Subtitles) — langa cele OS
            local_subs = []
            try:
                local_subs = self.find_substudio_local(imdb_id, season, episode) or []
            except Exception as e:
                log("Eroare integrare locala SubStudio: %s" % str(e))
            all_subs = list(downloaded) + [p for p in local_subs if p not in downloaded]

            # 5. Aplicare: toate pe video (OS + local), prima OS activata (ca TMDb Movies)
            self.apply_os_subtitles(all_subs)

            # 6. Notificare (mereu la succes, ca TMDb Movies)
            xbmcgui.Dialog().notification(
                "[B][COLOR FF00BFFF]Fast AutoSubs[/COLOR][/B]",
                "Adăugate: [B][COLOR yellow]%d[/COLOR][/B] [B][COLOR orange]%s[/COLOR][/B] — [B][COLOR FF00BFFF]OpenSubtitles[/COLOR][/B]%s" % (len(downloaded), target_lang.upper(), " + [B][COLOR lime]%d local[/COLOR][/B]" % len(local_subs) if local_subs else ""),
                FAS_ICON,
                4000
            )
        except Exception as e:
            log("Eroare in modul OpenSubtitles: %s" % str(e))
            self.open_subtitle_search(pause_enabled)
            return

        # 7. Reluam redarea daca am pus noi pauza
        if pause_enabled and xbmc.getCondVisibility('Player.Paused'):
            log("Reluare redare dupa cautarea OpenSubtitles.")
            self.pause()

    def open_subtitle_search(self, pause_enabled):
        # Daca am pus noi pauza si utilizatorul nu a reluat manual, reluam redarea
        if pause_enabled and xbmc.getCondVisibility('Player.Paused'):
            self.pause()
        xbmc.executebuiltin('ActivateWindow(SubtitleSearch)')

    def get_substudio_language(self):
        """Citeste limba aleasa in setarile SubStudio (subs_languages) -> cod ISO 639-1."""
        try:
            sub_addon = xbmcaddon.Addon(id=SUBSTUDIO_ADDON_ID)
            idx = int(sub_addon.getSetting('subs_languages') or 0)
            code = SUBSTUDIO_LANGS[idx]
            log("Limba din setarile SubStudio (index %d): %s" % (idx, code))
            return code
        except Exception as e:
            log("Nu am putut citi limba din SubStudio: %s" % str(e))
            return None

    def get_fastas_language(self):
        """Fallback: limba principala din setarile fastAS -> cod ISO 639-1."""
        try:
            if __addon__.getSetting('check_for_specific') == 'true':
                lang_a = __addon__.getSetting('selected_languagea')
                code = xbmc.convertLanguage(lang_a, xbmc.ISO_639_1)
                if code:
                    log("Limba fallback fastAS: %s" % code)
                    return code.lower()
        except Exception as e:
            log("Nu am putut citi limba din fastAS: %s" % str(e))
        return None

    def get_video_identity(self, requests):
        """Determina (imdb_id, season, episode) din InfoLabels, proprietati, URL sau TMDb."""
        imdb_id = None
        season = '0'
        episode = '0'

        # 1. InfoLabels standard Kodi
        try:
            cand = xbmc.getInfoLabel('VideoPlayer.IMDBNumber')
            if cand and str(cand) not in JUNK_IDS:
                imdb_id = str(cand).strip()
        except:
            pass
        if not imdb_id:
            try:
                cand = xbmc.getInfoLabel('ListItem.Property(imdb_id)')
                if cand and str(cand) not in JUNK_IDS:
                    imdb_id = str(cand).strip()
            except:
                pass

        # 2. Proprietati fereastra (setate de unele addon-uri)
        if not imdb_id:
            try:
                home = xbmcgui.Window(10000)
                for prop in ('IMDb_ID', 'imdb_id', 'imdb', 'VideoPlayer.IMDb', 'VideoPlayer.IMDBNumber'):
                    cand = home.getProperty(prop)
                    if cand and str(cand) not in JUNK_IDS:
                        imdb_id = str(cand).strip()
                        break
            except:
                pass

        # 3. Regula directa in link-ul fisierului redat (ex. media_id=tt1234567)
        if not imdb_id:
            try:
                file_path = self.getPlayingFile() or ''
                match_imdb = re.search(r'(?:media_id|imdb|imdb_id|title)=([^&]+)', file_path, re.IGNORECASE)
                if match_imdb and match_imdb.group(1).startswith('tt'):
                    imdb_id = match_imdb.group(1)
                    log("IMDb extras din link-ul video: %s" % imdb_id)
            except:
                pass

        # Sezon / episod (pentru seriale)
        try:
            season = xbmc.getInfoLabel('VideoPlayer.Season') or '0'
            episode = xbmc.getInfoLabel('VideoPlayer.Episode') or '0'
        except:
            pass

        is_tv = str(season) not in ('0', '', 'None')

        if not is_tv:
            try:
                base = os.path.basename(self.getPlayingFile() or '')
                m = re.search(r'[Ss](\d{1,2})[Ee](\d{1,3})', base)
                if m:
                    season = str(int(m.group(1)))
                    episode = str(int(m.group(2)))
                    is_tv = True
                    log("Sezon/episod din fisier: S%sE%s" % (season, episode))
            except:
                pass

        # 4. TMDbId -> IMDb (daca avem doar TMDb)
        if not imdb_id:
            try:
                tmdb_id = xbmc.getInfoLabel('VideoPlayer.TMDbId')
                if tmdb_id and str(tmdb_id) not in JUNK_IDS and str(tmdb_id).isdigit():
                    media_type = 'tv' if is_tv else 'movie'
                    imdb_id = self.tmdb_to_imdb(requests, str(tmdb_id), media_type)
            except:
                pass

        # 5. Titlu + an -> IMDb prin cautare TMDb (metoda folosita si de SubStudio)
        if not imdb_id:
            try:
                title = (xbmc.getInfoLabel('VideoPlayer.TVShowTitle') or
                         xbmc.getInfoLabel('VideoPlayer.OriginalTitle') or
                         xbmc.getInfoLabel('VideoPlayer.Title') or
                         xbmc.getInfoLabel('ListItem.Title'))
                year = (xbmc.getInfoLabel('VideoPlayer.Year') or
                        xbmc.getInfoLabel('ListItem.Year') or
                        xbmc.getInfoLabel('ListItem.Premiered'))
                if title:
                    imdb_id = self.title_to_imdb(requests, title, is_tv, year)
            except:
                pass

        # 5b. Fallback: titlu + an parsate din numele fisierului (library fara IMDb/InfoLabels)
        if not imdb_id:
            try:
                file_path = self.getPlayingFile() or ''
                fname_title, fname_year = self.title_year_from_filename(file_path)
                if fname_title:
                    log("Titlu din fisier: '%s' (%s)" % (fname_title, fname_year or '?'))
                    imdb_id = self.title_to_imdb(requests, fname_title, is_tv, fname_year)
            except Exception as e:
                log("Eroare fallback titlu din fisier: %s" % str(e))

        if not imdb_id:
            return None, season, episode

        if not str(imdb_id).startswith('tt') and str(imdb_id).isdigit():
            imdb_id = 'tt%s' % imdb_id

        log("Identificare video: IMDb=%s Season=%s Episode=%s" % (imdb_id, season, episode))
        return imdb_id, season, episode

    def tmdb_to_imdb(self, requests, tmdb_id, media_type):
        try:
            url = '%s/%s/%s/external_ids?api_key=%s' % (TMDB_BASE_URL, media_type, tmdb_id, TMDB_API_KEY)
            r = requests.get(url, timeout=8)
            if r.status_code == 200:
                data = r.json()
                imdb_id = data.get('imdb_id')
                if imdb_id:
                    log("Conversie TMDb %s -> IMDb %s" % (tmdb_id, imdb_id))
                    return imdb_id
        except Exception as e:
            log("Eroare conversie TMDb->IMDb: %s" % str(e))
        return None

    _FNAME_TAG_RE = re.compile(
        r'^(2160p|1080p|720p|480p|4k|uhd|hd|8k|3d|bluray|brrip|bdrip|hdtv|dvdrip|dvdscr|web-?dl|webrip|webcap|remux|'
        r'hdr10?|dolbyvision|dolby|vision|atmos|dts-?hd|dts|truehd|ac3|eac3|aac|flac|mp3|x26[45]|h26[45]|hevc|avc|vc-?1|'
        r'xvid|divx|extended|unrated|directors|theatrical|final|cut|imax|proper|repack|rerip|subbed|dubbed|multi|dual|'
        r'internal|limited|festival|screener|r5|r6|telesync|ts|telecine|tc|cam|hdcam|hdts|vhsrip|workprint|ppv|nfofix|'
        r'retail|oan|ro|en|eng|hun|sr|hr|bg|de|fr|es|it)$', re.IGNORECASE)

    @staticmethod
    def title_year_from_filename(file_path):
        try:
            base = os.path.basename(file_path or '')
            base = os.path.splitext(base)[0]
            if not base:
                return None, None
            tokens = re.split(r'[._\-\s\[\]\(\)]+', base)
            tokens = [t for t in tokens if t]
            year = None
            cut = len(tokens)
            for i, t in enumerate(tokens):
                if re.match(r'^(19|20)\d{2}$', t) and 1900 < int(t) < 2100:
                    year = t
                    cut = i
                    break
            title_tokens = tokens[:cut]
            while title_tokens and AutoSubsPlayer._FNAME_TAG_RE.match(title_tokens[-1]):
                title_tokens.pop()
            title = ' '.join(title_tokens).strip()
            if len(title) < 2:
                return None, None
            return title, year
        except:
            return None, None

    @staticmethod
    def _norm_title(s):
        try:
            import unicodedata
            s = unicodedata.normalize('NFKD', str(s or ''))
            s = ''.join(c for c in s if not unicodedata.combining(c))
        except:
            s = str(s or '')
        s = re.sub(r'[._\-]', ' ', s.lower())
        return re.sub(r'\s+', ' ', s).strip()

    def find_substudio_local(self, imdb_id, season, episode):
        """Cauta srt-uri salvate de SubStudio (Translated Subtitles + index.json) pentru video-ul curent."""
        matches = []
        try:
            sub_addon = xbmcaddon.Addon(id=SUBSTUDIO_ADDON_ID)
            profile = xbmcvfs.translatePath(sub_addon.getAddonInfo('profile'))
        except Exception:
            return matches
        try:
            saved_dir = os.path.join(profile, 'Translated Subtitles')
            try:
                _, files = xbmcvfs.listdir(saved_dir)
            except Exception:
                return matches
            srt_files = [f for f in (files or []) if f.lower().endswith('.srt')]
            if not srt_files:
                return matches
            index = {}
            index_path = os.path.join(saved_dir, 'index.json')
            if xbmcvfs.exists(index_path):
                try:
                    fh = xbmcvfs.File(index_path)
                    raw = fh.read()
                    fh.close()
                    if isinstance(raw, bytes):
                        raw = raw.decode('utf-8', errors='replace')
                    if raw:
                        index = json.loads(raw) or {}
                except Exception as e:
                    log("Eroare citire index SubStudio: %s" % str(e))
            title = (xbmc.getInfoLabel('VideoPlayer.TVShowTitle') or
                     xbmc.getInfoLabel('VideoPlayer.OriginalTitle') or
                     xbmc.getInfoLabel('VideoPlayer.Title') or
                     xbmc.getInfoLabel('ListItem.Title') or '')
            if not title:
                try:
                    title, _y = self.title_year_from_filename(self.getPlayingFile() or '')
                except:
                    title = ''
            n_title = self._norm_title(title)
            is_tv = str(season) not in ('0', '', 'None') and str(episode) not in ('0', '', 'None')
            for filename, info in (index or {}).items():
                try:
                    if not isinstance(info, dict) or not info.get('complete', False):
                        continue
                    full_path = os.path.join(saved_dir, filename)
                    if not xbmcvfs.exists(full_path):
                        continue
                    hit = False
                    if imdb_id and info.get('imdb') and str(imdb_id).lower().strip() == str(info['imdb']).lower().strip():
                        hit = True
                    elif n_title and info.get('title'):
                        n_idx = self._norm_title(info['title'])
                        if n_idx and (n_idx == n_title or n_idx.startswith(n_title) or n_title.startswith(n_idx)):
                            hit = True
                    if hit and is_tv:
                        info_s = str(info.get('season', ''))
                        info_e = str(info.get('episode', ''))
                        if info_s and info_e and (str(season) != info_s or str(episode) != info_e):
                            hit = False
                    if hit:
                        matches.append(full_path)
                except:
                    continue
            for f in srt_files:
                try:
                    if os.path.join(saved_dir, f) in matches:
                        continue
                    hit = False
                    if imdb_id and str(imdb_id).lower().replace('tt', '') in f.lower():
                        hit = True
                    elif n_title:
                        fn = self._norm_title(os.path.splitext(f)[0])
                        cw = n_title.split()[:3]
                        sw = fn.split()[:3]
                        if cw and cw == sw:
                            hit = True
                        elif len(n_title) >= 3 and (n_title in fn or fn in n_title):
                            hit = True
                    if hit and is_tv:
                        ep1 = "s%02de%02d" % (int(season), int(episode))
                        ep2 = "%dx%02d" % (int(season), int(episode))
                        if ep1 not in f.lower() and ep2 not in f.lower():
                            hit = False
                    if hit:
                        matches.append(os.path.join(saved_dir, f))
                except:
                    continue
        except Exception as e:
            log("Eroare cautare locala SubStudio: %s" % str(e))
        log("SubStudio local: %d subtitrari potrivite" % len(matches))
        return matches

    def title_to_imdb(self, requests, title, is_tv, year=None):
        """Cauta titlul pe TMDb si returneaza IMDb (metoda folosita si de SubStudio)."""
        try:
            clean_name = re.sub(r'\s+S\d+E\d+.*|\s+Season.*', '', title, flags=re.IGNORECASE).strip()
            if not clean_name:
                return None

            media_type = 'tv' if is_tv else 'movie'
            params = {'api_key': TMDB_API_KEY, 'query': clean_name}
            if year and str(year).isdigit() and 1900 < int(year) < 2100:
                if is_tv:
                    params['first_air_date_year'] = str(year)
                else:
                    params['primary_release_year'] = str(year)

            r = requests.get('%s/search/%s' % (TMDB_BASE_URL, media_type), params=params, timeout=8)
            if r.status_code != 200:
                return None
            results = r.json().get('results', [])
            if not results and ('primary_release_year' in params or 'first_air_date_year' in params):
                params.pop('primary_release_year', None)
                params.pop('first_air_date_year', None)
                log("Cautare TMDb fara an pentru '%s'" % clean_name)
                r = requests.get('%s/search/%s' % (TMDB_BASE_URL, media_type), params=params, timeout=8)
                if r.status_code != 200:
                    return None
                results = r.json().get('results', [])
            if not results:
                return None

            best = results[0]
            ext = requests.get('%s/%s/%s/external_ids?api_key=%s' % (TMDB_BASE_URL, media_type, best['id'], TMDB_API_KEY), timeout=8)
            if ext.status_code == 200:
                imdb_id = ext.json().get('imdb_id')
                if imdb_id:
                    log("Titlu '%s' -> TMDb %s -> IMDb %s" % (clean_name, best['id'], imdb_id))
                    return imdb_id
        except Exception as e:
            log("Eroare cautare TMDb dupa titlu: %s" % str(e))
        return None

    def os_search(self, requests, imdb_id, season, episode, target_lang):
        """Cauta pe OpenSubtitles REST toate srt-urile in limba tinta (ca TMDb Movies)."""
        found = []
        seen_urls = set()
        try:
            numeric_id = str(imdb_id).replace('tt', '')
            is_tv = season and episode and str(season) != '0' and str(episode) != '0'

            if is_tv:
                query_path = 'episode-%s/imdbid-%s/season-%s' % (episode, numeric_id, season)
            else:
                query_path = 'imdbid-%s' % numeric_id

            os_url = 'https://rest.opensubtitles.org/search/%s' % query_path
            log("Cautare OpenSubtitles: %s (limba: %s)" % (os_url, target_lang))
            r = requests.get(os_url, headers=OS_REST_HEADERS, timeout=15)

            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    for item in data:
                        file_id = item.get('IDSubtitleFile')
                        if not file_id:
                            continue

                        url = OS_DL_PREFIX + str(file_id)
                        if url in seen_urls:
                            continue

                        sub_lang_raw = item.get('ISO639', 'en')
                        sub_lang = NORM_OS_LANG.get(sub_lang_raw, str(sub_lang_raw)[:2])

                        if sub_lang == target_lang:
                            seen_urls.add(url)
                            raw_fname = item.get('SubFileName', 'subtitle_%s.srt' % file_id)
                            release = raw_fname[:-4] if raw_fname.lower().endswith('.srt') else raw_fname
                            found.append({
                                'url': url,
                                'language': sub_lang,
                                'release': release,
                                'format': 'srt',
                                'source': 'OpenSubtitles'
                            })
        except Exception as e:
            log("Eroare cautare OpenSubtitles: %s" % str(e))
        log("OpenSubtitles: %d subtitrari gasite in limba '%s'" % (len(found), target_lang))
        return found

    def cleanup_os_folder(self):
        """Sterge srt-urile vechi din folderul temporar fastautosubs."""
        try:
            folder = xbmcvfs.translatePath(OS_SUBS_FOLDER)
            if xbmcvfs.exists(folder):
                dirs, files = xbmcvfs.listdir(folder)
                for f in files:
                    xbmcvfs.delete(os.path.join(folder, f))
        except Exception as e:
            log("Eroare curatare folder srt: %s" % str(e))

    def os_download(self, requests, sub_data, index):
        """Descarca un srt de pe OpenSubtitles si il salveaza UTF-8 cu BOM."""
        try:
            url = sub_data.get('url')
            if not url:
                return None

            folder = xbmcvfs.translatePath(OS_SUBS_FOLDER)
            if not xbmcvfs.exists(folder):
                xbmcvfs.mkdirs(folder)

            ext = sub_data.get('format', 'srt')
            lang_code = sub_data.get('language', 'unk')
            release_name = sub_data.get('release', 'Sub_%s' % index)

            raw_filename = '%s.%02d.%s.%s' % (release_name, index, lang_code, ext)
            safe_filename = ''.join(c for c in raw_filename if c not in r'\/:*?"<>|')
            filepath = os.path.join(folder, safe_filename)

            r = requests.get(url, timeout=15, headers=OS_REST_HEADERS)
            if r.status_code == 200:
                raw_content = r.content
                if b'<html' in raw_content.lower():
                    return None

                try:
                    text = raw_content.decode('utf-8')
                except UnicodeDecodeError:
                    try:
                        text = raw_content.decode('cp1250')
                    except UnicodeDecodeError:
                        try:
                            text = raw_content.decode('iso-8859-2')
                        except UnicodeDecodeError:
                            text = raw_content.decode('utf-8', errors='replace')

                utf8_content = b'\xef\xbb\xbf' + text.encode('utf-8')

                f = xbmcvfs.File(filepath, 'wb')
                f.write(utf8_content)
                f.close()

                return filepath
        except Exception as e:
            log("Eroare descarcare srt: %s" % str(e))
        return None

    def apply_os_subtitles(self, downloaded_paths):
        """Pune toate subtitrariile pe video, prima activata (ca TMDb Movies)."""
        try:
            downloaded_paths.reverse()
            for sub_path in downloaded_paths:
                try:
                    self.setSubtitles(sub_path)
                    xbmc.sleep(350)
                except Exception as e:
                    log("Eroare adaugare subtitrare: %s" % str(e))
            self.showSubtitles(True)
        except Exception as e:
            log("Eroare aplicare subtitrari: %s" % str(e))

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
        # 1. VERIFICARE DURATA (Prima data!)
        # ======================================================================
        try:
            # Citim limita din setari (in minute) si transformam in secunde
            exclude_minutes = int(__addon__.getSetting('ExcludeTime'))
            exclude_seconds = exclude_minutes * 60
            
            # Obtinem durata totala a videoului
            total_time = self.getTotalTime()
            
            log("Verificare durata: Video=%s sec | Limita setata=%s sec" % (total_time, exclude_seconds))

            # Daca durata e mai mica decat limita (inclusiv 0 pentru Live TV), dam SKIP
            if total_time < exclude_seconds:
                log("Durata prea mica sau Live Stream (0). Skip.")
                return True
                
        except Exception as e: 
            log("Eroare la verificarea duratei: %s" % str(e))
            # Daca nu putem citi durata, nu excludem pe baza asta, continuam verificarile
            pass

        # ======================================================================
        # 2. EXCLUDERE LIVE TV / PVR (Verificare Extinsa)
        # ======================================================================
        if __addon__.getSetting('ExcludeLiveTV') == 'true':
            # A. Verificam Flag-ul intern Kodi
            if xbmc.getCondVisibility('VideoPlayer.Content(livetv)'):
                log("Detectat Live TV (Content Flag). Skip.")
                return True

            # B. Verificam InfoLabels (ListItem)
            li_path = xbmc.getInfoLabel('ListItem.Path')
            li_file = xbmc.getInfoLabel('ListItem.FileNameAndPath')
            
            if "pvr://" in li_path or "pvr://" in li_file:
                log("Detectat PVR in ListItem (pvr://). Skip.")
                return True
            
            if "iptvsimple" in li_path or "iptvsimple" in li_file:
                log("Detectat IPTV Simple Client in ListItem. Skip.")
                return True
            
            # C. Verificam calea directa
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
        if "rotv123" in str(movieFullPath).lower(): 
            return True
        if "http://" in movieFullPath and __addon__.getSetting('ExcludeHTTP') == 'true': 
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