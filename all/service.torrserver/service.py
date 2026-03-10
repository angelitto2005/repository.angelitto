import subprocess
import os
import stat
import sys
import json
import time
import platform
import urllib.request
import urllib.error
import threading
import base64
import xbmc
import xbmcaddon
import xbmcgui

_sys  = platform.system().lower()
_arch = platform.machine().lower()

IS_WINDOWS = _sys == 'windows'
IS_ANDROID = 'ANDROID_STORAGE' in os.environ or os.path.exists('/system/build.prop')
IS_ARM     = _arch in ('aarch64', 'armv8', 'arm64', 'armv7l', 'armv6l')

if IS_WINDOWS:
    BIN_NAME = 'TorrServer-windows-amd64.exe'
elif IS_ANDROID:
    if _arch in ('aarch64', 'arm64'):
        BIN_NAME = 'TorrServer-android-arm64'
    elif _arch in ('armv7l', 'armv7', 'armv6l'):
        BIN_NAME = 'TorrServer-android-arm7'
    elif _arch == 'x86_64':
        BIN_NAME = 'TorrServer-android-amd64'
    else:
        BIN_NAME = 'TorrServer-android-386'
elif IS_ARM:
    BIN_NAME = 'TorrServer-linux-arm64'
else:
    BIN_NAME = 'TorrServer-linux-amd64'

_addon     = xbmcaddon.Addon()
ADDON_ID   = _addon.getAddonInfo('id')
ADDON_PATH = _addon.getAddonInfo('path')

if IS_WINDOWS:
    _exe_dir  = os.path.dirname(sys.executable)
    _portable = os.path.join(_exe_dir, 'portable_data')
    _kodi_base = _portable if os.path.exists(_portable) else os.path.join(os.environ.get('APPDATA', ''), 'Kodi')
elif IS_ANDROID:
    _kodi_base = os.environ.get('KODI_HOME', '/sdcard/Android/data/org.xbmc.kodi/files/.kodi')
elif os.path.exists('/storage/.kodi'):
    _kodi_base = '/storage/.kodi'
else:
    _kodi_base = os.path.join(os.path.expanduser('~'), '.kodi')

ADDON_DATA = os.path.join(_kodi_base, 'userdata', 'addon_data', ADDON_ID)

if IS_ANDROID:
    TORRSERVER_PATH = os.path.join(ADDON_DATA, BIN_NAME)
else:
    TORRSERVER_PATH = os.path.join(ADDON_PATH, 'resources', 'bin', BIN_NAME)

PID_FILE        = os.path.join(ADDON_DATA, 'torrserver.pid')
GITHUB_API      = 'https://api.github.com/repos/YouROK/TorrServer/releases/latest'
GITHUB_DOWNLOAD = 'https://github.com/YouROK/TorrServer/releases/latest/download/'

xbmc.log(f"[{ADDON_ID}] Platforma: {_sys}/{_arch} | Android={IS_ANDROID} | Binar: {BIN_NAME}", xbmc.LOGINFO)
xbmc.log(f"[{ADDON_ID}] ADDON_DATA: {ADDON_DATA}", xbmc.LOGINFO)
xbmc.log(f"[{ADDON_ID}] TORRSERVER_PATH: {TORRSERVER_PATH}", xbmc.LOGINFO)


def s2i(val, default=0):
    try:
        return int(val) if val else default
    except (ValueError, TypeError):
        return default


def get_local_version(port):
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/echo", method="GET")
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.read().decode().strip()
    except Exception:
        return None


def get_latest_version():
    try:
        req = urllib.request.Request(GITHUB_API)
        req.add_header('User-Agent', 'Kodi-TorrServer-Addon')
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
            return data.get('tag_name', '').strip()
    except Exception as e:
        xbmc.log(f"[{ADDON_ID}] Eroare GitHub API: {str(e)}", xbmc.LOGERROR)
        return None


class TorrServerService(xbmc.Monitor):
    def __init__(self):
        xbmc.Monitor.__init__(self)
        self.process = None
        self._ignore_settings_change = 0
        self.read_settings()
        xbmc.log(f"[{ADDON_ID}] Service pornit", xbmc.LOGINFO)

    def read_settings(self):
        a = xbmcaddon.Addon(ADDON_ID)
        self.port                 = s2i(a.getSetting('torrserver_port'), 8090)
        self.download_path        = a.getSetting('download_path')
        self.disconnect_timeout   = s2i(a.getSetting('torrent_disconnect_timeout'), 30)
        self.responsive_mode      = a.getSetting('responsive_mode') == 'true'
        self.remove_cache_on_drop = a.getSetting('remove_cache_on_drop') == 'true'
        self.enable_debug         = a.getSetting('enable_debug') == 'true'
        cache_mb                  = s2i(a.getSetting('cache_size'), 64)
        self.cache_size           = cache_mb * 1024 * 1024
        self.use_ram              = a.getSetting('use_ram') == 'true'
        self.reader_read_ahead    = s2i(a.getSetting('reader_read_ahead'), 95)
        self.preload_cache        = s2i(a.getSetting('preload_cache'), 50)
        self.retrackers_mode      = s2i(a.getSetting('retrackers_mode'), 1)
        self.force_encrypt        = a.getSetting('force_encrypt') == 'true'
        self.enable_dht           = a.getSetting('enable_dht') == 'true'
        self.enable_upnp          = a.getSetting('enable_upnp') == 'true'
        self.disable_pex          = a.getSetting('disable_pex') == 'true'
        self.disable_tcp          = a.getSetting('disable_tcp') == 'true'
        self.disable_utp          = a.getSetting('disable_utp') == 'true'
        self.disable_upload       = a.getSetting('disable_upload') == 'true'
        self.enable_ipv6          = a.getSetting('enable_ipv6') == 'true'
        self.connections_limit    = s2i(a.getSetting('connections_limit'), 25)
        self.peers_listen_port    = s2i(a.getSetting('peers_listen_port'), 0)
        self.download_rate        = s2i(a.getSetting('download_rate'), 0)
        self.upload_rate          = s2i(a.getSetting('upload_rate'), 0)
        self.enable_dlna          = a.getSetting('enable_dlna') == 'true'
        self.friendly_name        = a.getSetting('friendly_name') or 'TorrServer'
        self.enable_auth          = a.getSetting('enable_auth') == 'true'
        self.username             = a.getSetting('username')
        self.password             = a.getSetting('password')
        xbmc.log(f"[{ADDON_ID}] Setari: Port={self.port} Cache={cache_mb}MB RAM={self.use_ram} DHT={self.enable_dht} UPnP={self.enable_upnp}", xbmc.LOGINFO)

    def _update_version_setting(self):
        def _worker():
            time.sleep(2)
            try:
                ver = get_local_version(self.port) or '—'
                xbmcgui.Dialog().notification('TorrServer', f'Running version: {ver}', xbmcgui.NOTIFICATION_INFO, 3000, False)
            except Exception:
                pass
        threading.Thread(target=_worker, daemon=True).start()

    def _auth_header(self):
        if self.enable_auth and self.username and self.password:
            token = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
            return {"Authorization": f"Basic {token}"}
        return {}

    def _post(self, payload, timeout=5):
        data = json.dumps(payload).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/settings", data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        for k, v in self._auth_header().items():
            req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode()

    def wait_for_server(self, timeout=20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self._post({"action": "get"})
                xbmc.log(f"[{ADDON_ID}] Serverul este gata", xbmc.LOGINFO)
                return True
            except Exception:
                time.sleep(1)
        xbmc.log(f"[{ADDON_ID}] Serverul nu a raspuns in {timeout}s", xbmc.LOGERROR)
        return False

    def apply_settings_via_api(self):
        try:
            raw = self._post({"action": "get"})
            current = json.loads(raw)
            current["CacheSize"]                = self.cache_size
            current["UseDisk"]                  = not self.use_ram
            current["ReaderReadAHead"]          = self.reader_read_ahead
            current["PreloadCache"]             = self.preload_cache
            current["RemoveCacheOnDrop"]        = self.remove_cache_on_drop
            current["ForceEncrypt"]             = self.force_encrypt
            current["RetrackersMode"]           = self.retrackers_mode
            current["TorrentDisconnectTimeout"] = self.disconnect_timeout
            current["EnableDebug"]              = self.enable_debug
            current["ResponsiveMode"]           = self.responsive_mode
            current["EnableDLNA"]               = self.enable_dlna
            current["FriendlyName"]             = self.friendly_name
            current["EnableIPv6"]               = self.enable_ipv6
            current["DisableTCP"]               = self.disable_tcp
            current["DisableUTP"]               = self.disable_utp
            current["DisableUPNP"]              = not self.enable_upnp
            current["DisableDHT"]               = not self.enable_dht
            current["DisablePEX"]               = self.disable_pex
            current["DisableUpload"]            = self.disable_upload
            current["DownloadRateLimit"]        = self.download_rate
            current["UploadRateLimit"]          = self.upload_rate
            current["ConnectionsLimit"]         = self.connections_limit
            current["PeersListenPort"]          = self.peers_listen_port
            if self.download_path:
                current["TorrentsSavePath"] = self.download_path
            self._post({"action": "set", "sets": current})
            xbmc.log(f"[{ADDON_ID}] Setari aplicate prin API cu succes", xbmc.LOGINFO)
            return True
        except Exception as e:
            xbmc.log(f"[{ADDON_ID}] Eroare aplicare setari API: {str(e)}", xbmc.LOGERROR)
            return False

    def download_binary(self):
        xbmc.log(f"[{ADDON_ID}] Descarcare {BIN_NAME} ...", xbmc.LOGINFO)
        xbmcgui.Dialog().notification('TorrServer', f'Downloading {BIN_NAME}, please wait...', xbmcgui.NOTIFICATION_INFO, 10000)
        try:
            url = f"{GITHUB_DOWNLOAD}{BIN_NAME}"
            os.makedirs(os.path.dirname(TORRSERVER_PATH), exist_ok=True)
            tmp_path = TORRSERVER_PATH + '.tmp'
            xbmc.log(f"[{ADDON_ID}] Download din: {url}", xbmc.LOGINFO)
            urllib.request.urlretrieve(url, tmp_path)
            if os.path.exists(TORRSERVER_PATH):
                os.remove(TORRSERVER_PATH)
            os.rename(tmp_path, TORRSERVER_PATH)
            xbmc.log(f"[{ADDON_ID}] Descarcare completa: {TORRSERVER_PATH}", xbmc.LOGINFO)
            return True
        except Exception as e:
            xbmc.log(f"[{ADDON_ID}] Eroare la descarcare: {str(e)}", xbmc.LOGERROR)
            tmp_path = TORRSERVER_PATH + '.tmp'
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            return False

    def ensure_executable(self):
        if not os.path.exists(TORRSERVER_PATH):
            if not self.download_binary():
                return False
        if not IS_WINDOWS:
            st = os.stat(TORRSERVER_PATH)
            if not (st.st_mode & stat.S_IEXEC):
                os.chmod(TORRSERVER_PATH, st.st_mode | stat.S_IEXEC)
                xbmc.log(f"[{ADDON_ID}] +x adaugat la binar", xbmc.LOGINFO)
        return True

    def _check_update_on_start(self):
        time.sleep(5)
        try:
            local_ver = get_local_version(self.port)
            if not local_ver:
                return
            latest_ver = get_latest_version()
            if not latest_ver:
                return
            if local_ver == latest_ver:
                xbmc.log(f"[{ADDON_ID}] TorrServer este la zi: {local_ver}", xbmc.LOGINFO)
                return
            xbmc.log(f"[{ADDON_ID}] Update disponibil: {local_ver} -> {latest_ver}", xbmc.LOGINFO)
            confirmed = xbmcgui.Dialog().yesno("TorrServer Update", f"New version available. Current: {local_ver}. New: {latest_ver}. Download and install now?")
            if confirmed:
                self.check_and_update_binary()
        except Exception as e:
            xbmc.log(f"[{ADDON_ID}] Eroare check update la pornire: {str(e)}", xbmc.LOGERROR)

    def check_and_update_binary(self):
        xbmc.log(f"[{ADDON_ID}] Verificare update binar...", xbmc.LOGINFO)
        local_ver = get_local_version(self.port)
        if not local_ver:
            xbmcgui.Dialog().notification('TorrServer', 'Server not responding. Start the service first.', xbmcgui.NOTIFICATION_WARNING, 4000)
            return
        latest_ver = get_latest_version()
        if not latest_ver:
            xbmcgui.Dialog().notification('TorrServer', 'Could not check version. Check internet connection.', xbmcgui.NOTIFICATION_ERROR, 4000)
            return
        xbmc.log(f"[{ADDON_ID}] Versiune locala: {local_ver} | Ultima versiune: {latest_ver}", xbmc.LOGINFO)
        if local_ver == latest_ver:
            xbmcgui.Dialog().notification('TorrServer', f'Up to date! Version {local_ver} is the latest.', xbmcgui.NOTIFICATION_INFO, 4000)
            return
        confirmed = xbmcgui.Dialog().yesno('TorrServer Update', f'New version available!\n\nCurrent: {local_ver}\nNew: {latest_ver}\n\nDownload and install now?')
        if not confirmed:
            xbmc.log(f"[{ADDON_ID}] Update anulat de utilizator", xbmc.LOGINFO)
            return
        xbmcgui.Dialog().notification('TorrServer', f'Downloading {latest_ver}...', xbmcgui.NOTIFICATION_INFO, 3000)
        self.stop_torrserver()
        time.sleep(1)
        if self.download_binary():
            if not IS_WINDOWS:
                st = os.stat(TORRSERVER_PATH)
                os.chmod(TORRSERVER_PATH, st.st_mode | stat.S_IEXEC)
            self.start_torrserver()
            xbmcgui.Dialog().notification('TorrServer', f'Updated to {latest_ver} successfully!', xbmcgui.NOTIFICATION_INFO, 4000)
        else:
            xbmcgui.Dialog().notification('TorrServer', 'Download failed. Please try again.', xbmcgui.NOTIFICATION_ERROR, 4000)
            self.start_torrserver()

    def start_torrserver(self):
        try:
            if not self.ensure_executable():
                xbmc.log(f"[{ADDON_ID}] Binarul nu e disponibil, abort", xbmc.LOGERROR)
                return
            os.makedirs(ADDON_DATA, exist_ok=True)
            cmd = [TORRSERVER_PATH, "--path", ADDON_DATA, "--port", str(self.port)]
            if self.enable_auth:
                cmd.append("--httpauth")
            kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL}
            if IS_WINDOWS:
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            self.process = subprocess.Popen(cmd, **kwargs)
            with open(PID_FILE, 'w') as f:
                f.write(str(self.process.pid))
            xbmc.log(f"[{ADDON_ID}] TorrServer pornit PID={self.process.pid} Port={self.port}", xbmc.LOGINFO)
            if self.wait_for_server(timeout=20):
                self._update_version_setting()
                if not self.apply_settings_via_api():
                    xbmc.log(f"[{ADDON_ID}] Setarile API au esuat", xbmc.LOGWARNING)
                threading.Thread(target=self._check_update_on_start, daemon=True).start()
                threading.Thread(target=self._check_update_on_start, daemon=True).start()
            else:
                xbmc.log(f"[{ADDON_ID}] Serverul nu a pornit in timp util", xbmc.LOGERROR)
        except Exception as e:
            xbmc.log(f"[{ADDON_ID}] Eroare la pornire: {str(e)}", xbmc.LOGERROR)

    def stop_torrserver(self):
        if self.process:
            try:
                if self.process.poll() is None:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
            except Exception as e:
                xbmc.log(f"[{ADDON_ID}] Eroare oprire proces: {str(e)}", xbmc.LOGWARNING)
            xbmc.log(f"[{ADDON_ID}] TorrServer oprit", xbmc.LOGINFO)
            self.process = None
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)


    def onSettingsChanged(self):
        if self._ignore_settings_change > 0:
            self._ignore_settings_change -= 1
            return
        xbmc.log(f"[{ADDON_ID}] Setari modificate, restart server", xbmc.LOGINFO)
        self._ignore_settings_change += 1
        self.stop_torrserver()
        time.sleep(2)
        self.read_settings()
        self.start_torrserver()

    def run(self):
        self.start_torrserver()
        while not self.abortRequested():
            if self.waitForAbort(5):
                break
        self.stop_torrserver()
        xbmc.log(f"[{ADDON_ID}] Serviciu oprit complet", xbmc.LOGINFO)


if __name__ == '__main__':
    service = TorrServerService()
    service.run()
