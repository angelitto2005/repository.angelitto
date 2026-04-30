import json
import time

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs


ADDON = xbmcaddon.Addon("plugin.video.vixmovie")
ADDON_PROFILE_PATH = ADDON.getAddonInfo("profile")
FALLBACK_STATE_PATH = f"{ADDON_PROFILE_PATH}/playback_fallback.json"
FALLBACK_TTL_SECONDS = 120
FALLBACK_DELAY_SECONDS = 2
RUNNING_PROP = "VixMovieFallbackServiceRunning"


def log(msg, level=xbmc.LOGINFO):
    xbmc.log(f"[VIXMOVIE-SERVICE]: {msg}", level)


def _read_state():
    if not xbmcvfs.exists(FALLBACK_STATE_PATH):
        return None
    f = None
    try:
        f = xbmcvfs.File(FALLBACK_STATE_PATH, "r")
        content = f.read()
        if not content:
            return None
        return json.loads(content)
    except Exception as e:
        log(f"Could not read fallback state: {e}", xbmc.LOGWARNING)
        return None
    finally:
        if f:
            f.close()


def _write_state(state):
    f = None
    try:
        if not xbmcvfs.exists(ADDON_PROFILE_PATH):
            xbmcvfs.mkdirs(ADDON_PROFILE_PATH)
        f = xbmcvfs.File(FALLBACK_STATE_PATH, "w")
        f.write(json.dumps(state))
    except Exception as e:
        log(f"Could not write fallback state: {e}", xbmc.LOGWARNING)
    finally:
        if f:
            f.close()


def _clear_state():
    try:
        if xbmcvfs.exists(FALLBACK_STATE_PATH):
            xbmcvfs.delete(FALLBACK_STATE_PATH)
    except Exception as e:
        log(f"Could not clear fallback state: {e}", xbmc.LOGWARNING)


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


class VixMoviePlayer(xbmc.Player):
    def onPlayBackError(self):
        state = _read_state()
        _trigger_fallback(state)

    def onPlayBackEnded(self):
        _trigger_fallback(_read_state())

    def onPlayBackStopped(self):
        _trigger_fallback(_read_state())

    def onPlayBackStarted(self):
        pass

    def onAVStarted(self):
        _clear_state()


if __name__ == "__main__":
    window = xbmcgui.Window(10000)
    if window.getProperty(RUNNING_PROP) == "true":
        log("Service already running")
        raise SystemExit

    window.setProperty(RUNNING_PROP, "true")
    monitor = xbmc.Monitor()
    player = VixMoviePlayer()
    log("Service started")

    try:
        while not monitor.abortRequested():
            state = _read_state()
            if state:
                if not _state_is_fresh(state):
                    _clear_state()
                elif not state.get("attempted"):
                    age = time.time() - float(state.get("created", 0))
                    if age >= FALLBACK_DELAY_SECONDS:
                        _trigger_fallback(state)
            if monitor.waitForAbort(1):
                break
    finally:
        window.clearProperty(RUNNING_PROP)
        del player
        log("Service stopped")
