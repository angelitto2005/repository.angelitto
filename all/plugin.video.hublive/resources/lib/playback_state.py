import os

import xbmc
import xbmcaddon
import xbmcvfs

try:
    import orjson

    def _json_loads(raw_text):
        return orjson.loads(raw_text)

    def _json_dumps(payload):
        dumped = orjson.dumps(payload)
        return dumped.decode("utf-8") if isinstance(dumped, bytes) else dumped
except ImportError:
    import json

    def _json_loads(raw_text):
        return json.loads(raw_text)

    def _json_dumps(payload):
        return json.dumps(payload, ensure_ascii=True)


ADDON_ID = "plugin.video.hublive"
PLAYBACK_STATE_FILE = "playback_state.json"


def _get_addon():
    try:
        return xbmcaddon.Addon(ADDON_ID)
    except Exception:
        return xbmcaddon.Addon()


def get_profile_dir():
    addon = _get_addon()
    profile_path = addon.getAddonInfo("profile")
    try:
        resolved = xbmcvfs.translatePath(profile_path)
    except Exception:
        resolved = xbmc.translatePath(profile_path)

    if not os.path.exists(resolved):
        os.makedirs(resolved)
    return resolved


def get_playback_state_path():
    return os.path.join(get_profile_dir(), PLAYBACK_STATE_FILE)


def load_playback_state():
    state_path = get_playback_state_path()
    if not os.path.exists(state_path):
        return {}

    try:
        with open(state_path, "r", encoding="utf-8") as handle:
            raw_text = handle.read().strip()
        if not raw_text:
            return {}
        payload = _json_loads(raw_text)
        return payload if isinstance(payload, dict) else {}
    except Exception as exc:
        xbmc.log(
            f"[PlaybackState] Failed to load state: {exc}", level=xbmc.LOGWARNING
        )
        return {}


def save_playback_state(payload):
    state_path = get_playback_state_path()
    temp_path = f"{state_path}.tmp"
    try:
        serialized = _json_dumps(payload if isinstance(payload, dict) else {})
        with open(temp_path, "w", encoding="utf-8") as handle:
            handle.write(serialized)
        os.replace(temp_path, state_path)
        return True
    except Exception as exc:
        xbmc.log(
            f"[PlaybackState] Failed to save state: {exc}", level=xbmc.LOGWARNING
        )
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass
        return False


def clear_playback_state(session_id=None):
    state_path = get_playback_state_path()
    if not os.path.exists(state_path):
        return

    if session_id:
        current_state = load_playback_state()
        if current_state.get("session_id") != session_id:
            return

    try:
        os.remove(state_path)
    except OSError as exc:
        xbmc.log(
            f"[PlaybackState] Failed to clear state: {exc}", level=xbmc.LOGWARNING
        )
