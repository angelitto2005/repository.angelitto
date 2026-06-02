import json
import time
import os
import sys

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

# Add addon path to sys.path for imports
ADDON = xbmcaddon.Addon("plugin.video.vixmovie")
ADDON_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo("path"))
if ADDON_PATH not in sys.path:
    sys.path.insert(0, ADDON_PATH)

ADDON_PROFILE_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo("profile"))
FALLBACK_STATE_PATH = os.path.join(ADDON_PROFILE_PATH, "playback_fallback.json")
PLAYBACK_INFO_PATH = os.path.join(ADDON_PROFILE_PATH, "playback_info.json")
FALLBACK_TTL_SECONDS = 120
FALLBACK_DELAY_SECONDS = 12
RUNNING_PROP = "VixMovieFallbackServiceRunning"

# Progress save interval (seconds)
PROGRESS_SAVE_INTERVAL = 15


def log(msg, level=xbmc.LOGINFO):
    xbmc.log(f"[VIXMOVIE-SERVICE]: {msg}", level)


def _ensure_profile():
    if not os.path.exists(ADDON_PROFILE_PATH):
        os.makedirs(ADDON_PROFILE_PATH, exist_ok=True)


def _read_state():
    if not os.path.exists(FALLBACK_STATE_PATH):
        return None
    try:
        with open(FALLBACK_STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"Could not read fallback state: {e}", xbmc.LOGWARNING)
        return None


def _write_state(state):
    try:
        _ensure_profile()
        with open(FALLBACK_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception as e:
        log(f"Could not write fallback state: {e}", xbmc.LOGWARNING)


def _clear_state():
    try:
        if os.path.exists(FALLBACK_STATE_PATH):
            os.remove(FALLBACK_STATE_PATH)
    except Exception as e:
        log(f"Could not clear fallback state: {e}", xbmc.LOGWARNING)


def _read_playback_info():
    """Read playback metadata written by addon.py."""
    if not os.path.exists(PLAYBACK_INFO_PATH):
        return None
    try:
        with open(PLAYBACK_INFO_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Only use if fresh (less than 5 minutes old)
        created = data.get("created", 0)
        if time.time() - created > 300:
            return None
        return data
    except Exception:
        return None


def _clear_playback_info():
    """Clear playback info file."""
    try:
        if os.path.exists(PLAYBACK_INFO_PATH):
            os.remove(PLAYBACK_INFO_PATH)
    except Exception:
        pass


def _state_is_fresh(state):
    try:
        return (time.time() - float(state.get("created", 0))) <= FALLBACK_TTL_SECONDS
    except Exception:
        return False


def _trigger_fallback(state):
    if not state or state.get("attempted"):
        return

    if not _state_is_fresh(state):
        _clear_state()
        return

    plugin_url = state.get("plugin_url")
    if not plugin_url:
        _clear_state()
        return

    state["attempted"] = True
    state["attempted_at"] = time.time()
    _write_state(state)

    title = state.get("title", "")
    log(f"Playback failed for scraper 1, falling back to scraper 2: {title}")
    xbmc.executebuiltin("Dialog.Close(okdialog)")
    xbmc.executebuiltin("Dialog.Close(all,true)")
    xbmc.sleep(100)
    xbmc.executebuiltin(f"PlayMedia({plugin_url})")


def _save_progress(media_type, tmdb_id, title, season, episode, position, total, show_title=""):
    """Save playback progress to the watch database."""
    if not tmdb_id or position <= 0:
        return

    try:
        from resources.lib import watchdb

        if media_type == "movie":
            watchdb.record_movie_progress(tmdb_id, title or "", position, total)
        elif media_type == "episode" and season and episode:
            watchdb.record_episode_progress(
                tmdb_id, int(season), int(episode),
                title or "", show_title or title or "", position, total
            )
        log(f"Saved progress: {title} pos={position}/{total}")
    except Exception as e:
        log(f"Could not save progress: {e}", xbmc.LOGWARNING)


class VixMoviePlayer(xbmc.Player):
    def __init__(self):
        super().__init__()
        self._tracking = False
        self._media_type = None
        self._tmdb_id = None
        self._title = None
        self._show_title = None
        self._season = None
        self._episode = None
        self._session_id = None
        self._position = 0
        self._total = 0
        self._last_save_time = 0

    def _load_playback_info(self):
        """Load playback metadata from the shared file written by addon.py."""
        info = _read_playback_info()
        if info:
            self._media_type = info.get("media_type")
            self._tmdb_id = info.get("tmdb_id")
            self._title = info.get("title", "")
            self._show_title = info.get("show_title") or ""
            self._season = info.get("season")
            self._episode = info.get("episode")
            self._session_id = info.get("session_id") or None
            self._tracking = True
            log(f"Loaded playback info: type={self._media_type} tmdb={self._tmdb_id} "
                f"title={self._title} s={self._season} e={self._episode} "
                f"session={self._session_id}")
            return True
        return False

    def _do_save_progress(self):
        """Save current progress."""
        if not self._tracking or not self._tmdb_id:
            return
        _save_progress(
            self._media_type, self._tmdb_id, self._title,
            self._season, self._episode, self._position, self._total,
            self._show_title or ""
        )

    def onPlayBackError(self):
        self._do_save_progress()
        self._tracking = False
        state = _read_state()
        _trigger_fallback(state)

    def onPlayBackEnded(self):
        was_tracking = self._tracking
        # Mark as fully watched
        if self._tracking and self._total > 0:
            self._position = self._total
        self._do_save_progress()
        self._tracking = False
        _clear_playback_info()
        if not was_tracking:
            _clear_state()

    def onPlayBackStopped(self):
        was_tracking = self._tracking
        # Save current position
        try:
            self._position = int(self.getTime())
            self._total = int(self.getTotalTime())
        except Exception:
            pass
        self._do_save_progress()
        self._tracking = False
        _clear_playback_info()
        if not was_tracking:
            _clear_state()

    def onPlayBackStarted(self):
        pass

    def onAVStarted(self):
        _clear_state()
        # Try to load playback info from addon
        if self._load_playback_info():
            try:
                self._total = int(self.getTotalTime())
            except Exception:
                pass
            log(f"AV started, tracking: {self._title}")
        else:
            self._tracking = False


if __name__ == "__main__":
    window = xbmcgui.Window(10000)
    if window.getProperty(RUNNING_PROP) == "true":
        log("Service already running, exiting")
        raise SystemExit

    window.setProperty(RUNNING_PROP, "true")
    monitor = xbmc.Monitor()
    player = VixMoviePlayer()
    log("Service started")

    save_counter = 0

    try:
        while not monitor.abortRequested():
            # Fallback logic
            state = _read_state()
            if state:
                if not _state_is_fresh(state):
                    _clear_state()
                elif not state.get("attempted") and not player.isPlaying() and not player._tracking:
                    age = time.time() - float(state.get("created", 0))
                    if age >= FALLBACK_DELAY_SECONDS:
                        _trigger_fallback(state)

            # Periodically update and save playback progress
            if player._tracking and player.isPlaying():
                try:
                    player._position = int(player.getTime())
                    player._total = int(player.getTotalTime())
                except Exception:
                    # Player might have stopped between isPlaying() check and getTime()
                    pass

                # Save every PROGRESS_SAVE_INTERVAL seconds
                save_counter += 1
                if save_counter >= PROGRESS_SAVE_INTERVAL:
                    save_counter = 0
                    player._do_save_progress()
            else:
                save_counter = 0

            if monitor.waitForAbort(1):
                break
    finally:
        # Save final progress on shutdown
        if player._tracking:
            player._do_save_progress()
        window.clearProperty(RUNNING_PROP)
        del player
        log("Service stopped")
