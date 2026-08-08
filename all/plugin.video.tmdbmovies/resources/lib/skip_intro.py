# -*- coding: utf-8 -*-
"""
Skip Intro (stil POV) — fereastra mica in dreapta sus care intreaba
daca vrei sa sari peste generic. Datele vin din introdb.app +
theintrodb.org (aceleasi surse folosite de POV/Fen).

Flow:
  1. `execute_skip_intro(player)` e apelat dintr-un thread daemon la
     pornirea playback-ului unui episod.
  2. Se rezolva imdb_id (din player.imdb_id sau get_external_ids).
  3. SegmentScraper interogheaza ambele API-uri (primul raspuns valid castiga).
  4. Se asteapta ca pozitia curenta sa intre in intervalul intro.
  5. SkipIntroWindow apare in dreapta sus (Skip / No, countdown 10s).
  6. Skip -> seekTime(intro_end). No / timeout -> se inchide silentios.
"""

import threading
import xbmc
import xbmcgui
import requests

from resources.lib.config import ADDON
from resources.lib.utils import log

_HTTP_TIMEOUT = (3.05, 6.05)
_SKIP_COUNTDOWN_SEC = 15


# =============================================================================
# Segment Scraper (introdb + theintrodb)
# =============================================================================
class SegmentScraper:
    def __init__(self, imdb_id, season, episode):
        self.params = {'imdb_id': imdb_id, 'season': season, 'episode': episode}
        self.providers = (self.fetch_introdb, self.fetch_theintrodb)

    def fetch_introdb(self):
        result = {'intro': None}
        try:
            response = requests.get('https://api.introdb.app/segments', params=self.params, timeout=_HTTP_TIMEOUT)
            rjson = response.json()
            intro = rjson.get('intro') or {}
            intro_start, intro_end = intro.get('start_sec'), intro.get('end_sec')
            if intro_start is not None and intro_end is not None:
                result['intro'] = (int(intro_start), int(intro_end))
        except Exception as e:
            log(f"[SKIP-INTRO] introdb fetch error: {e}", xbmc.LOGWARNING)
        return result

    def fetch_theintrodb(self):
        result = {'intro': None}
        try:
            response = requests.get('https://api.theintrodb.org/v3/media', params=self.params, timeout=_HTTP_TIMEOUT)
            rjson = response.json()
            intro_list = rjson.get('intro') or []
            if intro_list:
                intro = next(iter(intro_list))
                intro_start, intro_end = intro.get('start_ms'), intro.get('end_ms')
                if intro_start is not None and intro_end is not None:
                    result['intro'] = (int(intro_start / 1000), int(intro_end / 1000))
        except Exception as e:
            log(f"[SKIP-INTRO] theintrodb fetch error: {e}", xbmc.LOGWARNING)
        return result

    def run(self):
        final_intro = None
        for fetch_api in self.providers:
            data = fetch_api()
            if final_intro is None and data.get('intro') is not None:
                final_intro = data['intro']
            if final_intro is not None:
                break
        return final_intro


# =============================================================================
# Skip Intro Window (dreapta sus, stil POV: transparent, fanart + butoane)
# =============================================================================
class SkipIntroWindow(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        self.title = kwargs.get('title', '')
        self.poster = kwargs.get('poster', '')
        self.timer = int(kwargs.get('timer', _SKIP_COUNTDOWN_SEC))
        self.result = False
        self.is_closed = False
        self._ready = False

    def onInit(self):
        self._ready = True
        try:
            self.setProperty('tmdbmovies.si_title', self.title)
            self.setProperty('tmdbmovies.si_poster', self.poster)
            self.setProperty('tmdbmovies.si_countdown', str(self.timer))
            self.setFocusId(3011)
        except:
            pass
        threading.Thread(target=self._countdown, daemon=True).start()

    def _countdown(self):
        while self.timer > 0 and not self.is_closed:
            try:
                self.setProperty('tmdbmovies.si_countdown', str(self.timer))
                self.getControl(5000).setPercent(int((self.timer / float(_SKIP_COUNTDOWN_SEC)) * 100))
            except:
                pass
            xbmc.sleep(1000)
            self.timer -= 1
        if not self.is_closed and self.timer <= 0:
            self.result = False
            self.close()

    def onClick(self, controlId):
        if controlId == 3011:
            self.result = True
        self.is_closed = True
        self.close()

    def onAction(self, action):
        try:
            if action.getId() in (9, 10, 13, 92, 110):  # Back/Stop/Escape etc.
                self.is_closed = True
                self.result = False
                self.close()
        except:
            pass

    def close(self):
        self.is_closed = True
        try:
            xbmcgui.WindowXMLDialog.close(self)
        except:
            pass


def _show_modal(dialog):
    """doModal care se inchide automat la shutdown Kodi."""
    mon = xbmc.Monitor()

    def _watch():
        while not mon.abortRequested():
            threading.Event().wait(0.5)
        try:
            dialog.close()
        except:
            pass

    threading.Thread(target=_watch, daemon=True).start()
    dialog.doModal()


# =============================================================================
# Worker principal
# =============================================================================
def execute_skip_intro(player):
    try:
        if ADDON.getSetting('skip_intro.enable') == 'false':
            return
        if player.content_type not in ('tv', 'episode'):
            return
        if not player.season or not player.episode:
            return

        # Asteptam ca video-ul sa fie CHIAR vizibil (fullscreenvideo activ).
        # Fara asta, pe surse lente (deschidere 10-20s), IsPlaying() e true in
        # timp ce ecranul inca arata lista -> fereastra de skip aparea in dreapta
        # sus inainte sa porneasca imaginea. Iesim daca playback-ul se opreste.
        for _ in range(120):  # max ~60s; de regula fullscreen apare in <2s
            try:
                if xbmc.getCondVisibility('Window.IsActive(fullscreenvideo)'):
                    break
            except Exception:
                break
            if not player.isPlaying():
                return
            xbmc.sleep(500)

        if not player.isPlaying():
            return

        imdb_id = getattr(player, 'imdb_id', '') or ''
        if not imdb_id:
            try:
                from resources.lib.scraper import get_external_ids
                ext = get_external_ids('tv', player.tmdb_id) or {}
                imdb_id = ext.get('imdb_id', '')
            except Exception as e:
                log(f"[SKIP-INTRO] get_external_ids error: {e}", xbmc.LOGWARNING)
        if not imdb_id:
            log("[SKIP-INTRO] No imdb_id available, skipping")
            return

        log(f"[SKIP-INTRO] Fetching intro segments for {imdb_id} S{player.season}E{player.episode}")
        intro = SegmentScraper(imdb_id, player.season, player.episode).run()
        if intro is None:
            log("[SKIP-INTRO] No intro data found for this episode")
            return
        intro_start, intro_end = intro
        log(f"[SKIP-INTRO] Intro window: {intro_start}s - {intro_end}s")

        while player.isPlaying():
            try:
                current_time = player.getTime()
            except Exception:
                break
            if current_time > intro_end:
                break
            if intro_start <= current_time <= intro_end:
                _prompt_and_maybe_skip(player, intro_end)
                return
            xbmc.sleep(500)
    except Exception as e:
        log(f"[SKIP-INTRO] Worker error: {e}", xbmc.LOGERROR)


def _prompt_and_maybe_skip(player, intro_end):
    try:
        show_title = getattr(player, 'tvshowtitle', '') or getattr(player, 'title', '')
        ep_name = _fetch_episode_name(player)
        title = f"{show_title} - S{int(player.season):02d}E{int(player.episode):02d} - {ep_name}" if ep_name else f"{show_title} - S{int(player.season):02d}E{int(player.episode):02d}"
        poster = _fetch_poster(player)
        win = SkipIntroWindow(
            'skip_intro.xml', ADDON.getAddonInfo('path'), 'Default', '1080i',
            title=title, poster=poster, timer=_SKIP_COUNTDOWN_SEC
        )
        _show_modal(win)
        do_skip = win.result
        try:
            win.close()
        except:
            pass
        if not do_skip:
            return
        log(f"[SKIP-INTRO] User chose SKIP -> seeking to {intro_end}s")
        try:
            player.seekTime(intro_end)
        except Exception as e:
            log(f"[SKIP-INTRO] Seek failed (stream not seekable?): {e}", xbmc.LOGWARNING)
    except Exception as e:
        log(f"[SKIP-INTRO] Prompt error: {e}", xbmc.LOGERROR)


def _fetch_episode_name(player):
    """Numele episodului curent din TMDb (pentru titlul complet)."""
    try:
        from resources.lib.tmdb_api import get_smart_season_details
        season_data = get_smart_season_details(player.tmdb_id, player.season)
        if not season_data:
            return ''
        for ep in season_data.get('episodes', []):
            try:
                if int(ep.get('episode_number', 0)) == int(player.episode):
                    return ep.get('name', '') or ''
            except:
                continue
        return ''
    except Exception as e:
        log(f"[SKIP-INTRO] Episode name fetch error: {e}", xbmc.LOGWARNING)
        return ''


def _fetch_poster(player):
    """Posterul serialului din TMDb pentru afisare in dialog."""
    try:
        from resources.lib.tmdb_api import get_tmdb_item_details
        from resources.lib.config import IMG_BASE
        details = get_tmdb_item_details(player.tmdb_id, 'tv', lightweight=True) or {}
        if details.get('poster_path'):
            return f"{IMG_BASE}{details['poster_path']}"
        return ''
    except Exception as e:
        log(f"[SKIP-INTRO] Poster fetch error: {e}", xbmc.LOGWARNING)
        return ''
