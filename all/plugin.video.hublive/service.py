import os
import sys
import time
from urllib.parse import urlencode

import xbmc
import xbmcaddon
import xbmcgui

# Add resources/lib to path
_addon_path = xbmcaddon.Addon().getAddonInfo('path')
_lib_path = os.path.join(_addon_path, 'resources', 'lib')
if _lib_path not in sys.path:
    sys.path.insert(0, _lib_path)

from playback_state import clear_playback_state, load_playback_state, save_playback_state

ADDON_ID = "plugin.video.hublive"
ADDON = xbmcaddon.Addon(ADDON_ID)
NOTIFICATION_TITLE = "HubLive"
_RECONNECT_LAUNCH_GRACE_SECONDS = 5


def _log(message, level=xbmc.LOGINFO):
    xbmc.log(f"[HubLiveService] {message}", level=level)


def _setting_bool(setting_id, default=False):
    value = ADDON.getSetting(setting_id)
    if value == "":
        return default
    return value == "true"


def _setting_int(setting_id, default_value, minimum=0, maximum=None):
    try:
        value = int((ADDON.getSetting(setting_id) or "").strip())
    except (TypeError, ValueError):
        value = default_value

    value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _normalize_mac(mac):
    return (mac or "").strip().lower()


def _dedupe_macs(macs, limit=None):
    if limit is None:
        auth_attempts = _setting_int("auth_max_attempts", 6, minimum=1, maximum=12)
        reconnects = _setting_int("live_max_reconnect_attempts", 3, minimum=0, maximum=10)
        limit = max(auth_attempts * (reconnects + 1), auth_attempts)

    ordered = []
    seen = set()
    for mac in macs or []:
        norm_mac = _normalize_mac(mac)
        if norm_mac and norm_mac not in seen:
            ordered.append(mac)
            seen.add(norm_mac)
    return ordered[-limit:]


class HubLivePlayer(xbmc.Player):
    def __init__(self, service):
        super().__init__()
        self.service = service

    def onAVStarted(self):
        self.service.on_av_started()

    def onPlayBackEnded(self):
        self.service.on_playback_end("ended")

    def onPlayBackStopped(self):
        self.service.on_playback_stopped()

    def onPlayBackError(self):
        self.service.on_playback_end("error")


class LiveReconnectService:
    def __init__(self):
        self.monitor = xbmc.Monitor()
        self.player = HubLivePlayer(self)
        self.last_notice_at = 0

    def run(self):
        _log("Live auto-reconnect service started")
        while not self.monitor.abortRequested():
            try:
                self._check_startup_timeout()
                self._process_pending_reconnect()
            except Exception as exc:
                _log(f"Service loop error: {exc}", level=xbmc.LOGWARNING)

            if self.monitor.waitForAbort(1):
                break
        _log("Live auto-reconnect service stopped")

    def _is_enabled(self):
        return _setting_bool("live_auto_reconnect", default=True)

    def _retry_on_stopped(self):
        return _setting_bool("live_retry_on_stopped", default=False)

    def _load_live_state(self):
        state = load_playback_state()
        if not isinstance(state, dict):
            return {}
        if state.get("kind") != "live":
            return {}
        return state

    def _save_state(self, state):
        state["last_event_at"] = time.time()
        save_playback_state(state)

    def _get_current_file(self):
        try:
            return self.player.getPlayingFile()
        except Exception:
            return ""

    def _notify(self, message, icon=xbmcgui.NOTIFICATION_INFO):
        now = time.time()
        if now - self.last_notice_at < 3:
            return
        self.last_notice_at = now
        xbmcgui.Dialog().notification(NOTIFICATION_TITLE, message, icon, 3000)

    def _clear_live_state(self, state, reason):
        session_id = state.get("session_id")
        _log(f"Clearing live reconnect state for session {session_id}: {reason}")
        clear_playback_state(session_id)

    def _is_launch_in_progress(self, state):
        if not state.get("launch_in_progress"):
            return False

        launch_started_at = float(state.get("launch_started_at") or 0)
        if not launch_started_at:
            return False

        return (time.time() - launch_started_at) < _RECONNECT_LAUNCH_GRACE_SECONDS

    def on_av_started(self):
        state = self._load_live_state()
        if not state:
            return

        current_file = self._get_current_file()
        if (
            state.get("status") == "playing"
            and state.get("resolved_url")
            and current_file
            and current_file != state["resolved_url"]
        ):
            _log("Different playback started; clearing stale live reconnect state")
            clear_playback_state(state.get("session_id"))
            return

        state.update(
            {
                "status": "playing",
                "playback_started": True,
                "reconnect_in_progress": False,
                "pending_reason": "",
                "next_retry_at": 0,
                "last_started_at": time.time(),
                "last_playing_file": current_file or state.get("resolved_url", ""),
                "launch_in_progress": False,
                "launch_started_at": 0,
            }
        )
        self._save_state(state)
        _log(f"Playback confirmed for session {state.get('session_id')}")

    def on_playback_end(self, reason):
        state = self._load_live_state()
        if not state or not self._is_enabled():
            return
        self._schedule_reconnect(state, reason)

    def on_playback_stopped(self):
        state = self._load_live_state()
        if not state or not self._is_enabled():
            return

        pending_reason = state.get("pending_reason")
        if state.get("reconnect_in_progress") and pending_reason in (
            "error",
            "ended",
            "startup_timeout",
            "startup_stop",
        ):
            _log(
                f"Ignoring stopped event because reconnect is already scheduled ({pending_reason})"
            )
            return

        if self._is_launch_in_progress(state):
            _log("Ignoring stopped event during reconnect launch grace period")
            return

        if (
            state.get("status") == "resolving"
            and not state.get("playback_started")
        ):
            self._schedule_reconnect(state, "startup_stop")
            return

        if self._retry_on_stopped():
            self._schedule_reconnect(state, "stopped")
            return

        self._clear_live_state(state, "stopped event treated as manual or ambiguous")

    def _check_startup_timeout(self):
        state = self._load_live_state()
        if not state or not self._is_enabled():
            return

        if state.get("status") != "resolving" or state.get("reconnect_in_progress"):
            return

        created_at = float(state.get("created_at") or 0)
        if not created_at:
            return

        startup_timeout = int(
            state.get("startup_timeout")
            or _setting_int("live_startup_timeout", 12, minimum=3, maximum=120)
        )
        if time.time() - created_at >= startup_timeout and not self.player.isPlaying():
            self._schedule_reconnect(state, "startup_timeout")

    def _schedule_reconnect(self, state, reason):
        if state.get("reconnect_in_progress"):
            return

        reconnect_count = int(state.get("reconnect_count") or 0)
        max_reconnects = int(
            state.get("max_reconnects")
            or _setting_int("live_max_reconnect_attempts", 3, minimum=0, maximum=10)
        )
        if reconnect_count >= max_reconnects:
            state.update(
                {
                    "status": "failed",
                    "reconnect_in_progress": False,
                    "pending_reason": "",
                    "next_retry_at": 0,
                    "last_reason": reason,
                    "last_error": "Reconnect limit reached.",
                }
            )
            self._save_state(state)
            self._notify(
                "Reconectarea automata a ajuns la limita configurata.",
                xbmcgui.NOTIFICATION_ERROR,
            )
            return

        delay = int(
            state.get("reconnect_delay")
            or _setting_int("live_reconnect_delay", 2, minimum=1, maximum=60)
        )
        state.update(
            {
                "status": "scheduled",
                "reconnect_in_progress": True,
                "pending_reason": reason,
                "next_retry_at": time.time() + delay,
                "last_reason": reason,
            }
        )
        self._save_state(state)
        _log(
            f"Reconnect scheduled in {delay}s for session {state.get('session_id')} ({reason})"
        )
        self._notify("Se incearca reconectarea streamului live...")

    def _build_reconnect_url(self, state, attempted_macs, reconnect_count):
        query = {
            "mode": "play",
            "server": state.get("server", "server1"),
            "stream_id": state.get("stream_id", ""),
            "name": state.get("name", "Unknown"),
            "session_id": state.get("session_id", ""),
            "reconnect_count": reconnect_count,
            "attempted_macs": ",".join(_dedupe_macs(attempted_macs)),
            "autoplay_reconnect": "true",
        }
        if state.get("url_template"):
            query["url_template"] = state["url_template"]
        return f"plugin://{ADDON_ID}/?{urlencode(query)}"

    def _process_pending_reconnect(self):
        state = self._load_live_state()
        if not state or not self._is_enabled():
            return

        if not state.get("reconnect_in_progress"):
            return

        next_retry_at = float(state.get("next_retry_at") or 0)
        if time.time() < next_retry_at:
            return

        if self.player.isPlaying():
            current_file = self._get_current_file()
            resolved_url = state.get("resolved_url") or ""
            last_playing_file = state.get("last_playing_file") or ""
            if current_file and current_file in (resolved_url, last_playing_file):
                state.update(
                    {
                        "status": "playing",
                        "reconnect_in_progress": False,
                        "pending_reason": "",
                        "next_retry_at": 0,
                        "launch_in_progress": False,
                        "launch_started_at": 0,
                    }
                )
                self._save_state(state)
                return

            self._clear_live_state(
                state,
                "different media is already playing while reconnect was pending",
            )
            return

        attempted_macs = list(state.get("attempted_macs") or [])
        current_mac = state.get("current_mac")
        if current_mac:
            attempted_macs.append(current_mac)
        attempted_macs = _dedupe_macs(attempted_macs)

        reconnect_count = int(state.get("reconnect_count") or 0) + 1
        plugin_url = self._build_reconnect_url(state, attempted_macs, reconnect_count)

        state.update(
            {
                "attempted_macs": attempted_macs,
                "reconnect_count": reconnect_count,
                "status": "resolving",
                "reconnect_in_progress": False,
                "pending_reason": "",
                "next_retry_at": 0,
                "playback_started": False,
                "created_at": time.time(),
                "launch_in_progress": True,
                "launch_started_at": time.time(),
            }
        )
        self._save_state(state)
        _log(
            f"Launching reconnect attempt {reconnect_count}/{state.get('max_reconnects')} for session {state.get('session_id')}"
        )
        try:
            self.player.play(plugin_url)
        except Exception as exc:
            _log(f"Player.play failed, falling back to PlayMedia: {exc}")
            xbmc.executebuiltin(f"PlayMedia({plugin_url})")


if __name__ == "__main__":
    try:
        LiveReconnectService().run()
    except Exception as exc:
        _log(f"Fatal service error: {exc}", level=xbmc.LOGERROR)
