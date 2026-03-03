# -*- coding: utf-8 -*-
try:
    from resources.lib import requests
    from resources.lib.requests.auth import HTTPBasicAuth
except ImportError:
    import requests
    from requests.auth import HTTPBasicAuth
from json import dumps
try:
    from urllib.parse import quote
except ImportError:
    from urllib import quote
import xbmc
import os
import hashlib
import base64
import re

try:
    from resources.lib import bencode
except ImportError:
    try:
        import bencode
    except:
        bencode = None


def log(msg):
    try:
        from resources.functions import log as central_log
        central_log(msg)
    except:
        pass
        

def get_magnet_from_file(file_path):
    try:
        if not bencode:
            return None, None
        with open(file_path, 'rb') as f:
            content = f.read()
        data = bencode.bdecode(content)
        info_dict = data.get(b'info') or data.get('info')
        if not info_dict:
            return None, None
        raw_info = bencode.bencode(info_dict)
        info_hash = hashlib.sha1(raw_info).hexdigest()
        trackers = []
        ann = data.get(b'announce') or data.get('announce')
        if ann:
            trackers.append(ann.decode('utf-8', 'ignore') if isinstance(ann, bytes) else ann)
        ann_list = data.get(b'announce-list') or data.get('announce-list')
        if ann_list:
            for sublist in ann_list:
                for tr in sublist:
                    t_url = tr.decode('utf-8', 'ignore') if isinstance(tr, bytes) else tr
                    if t_url not in trackers:
                        trackers.append(t_url)
        name_bytes = info_dict.get(b'name') or info_dict.get('name') or b'Stream'
        name = name_bytes.decode('utf-8', 'ignore') if isinstance(name_bytes, bytes) else name_bytes
        magnet = "magnet:?xt=urn:btih:%s&dn=%s" % (info_hash, quote(name))
        for tr in trackers:
            magnet += "&tr=%s" % quote(tr)
        return info_hash, magnet
    except Exception as e:
        log("### [TorrServer API] Bencode Error: %s" % str(e))
        return None, None


def extract_hash_from_magnet(magnet):
    try:
        match = re.search(r'btih:([a-fA-F0-9]{40})', magnet)
        if match:
            return match.group(1).lower()
        match = re.search(r'btih:([A-Za-z2-7]{32})', magnet)
        if match:
            decoded = base64.b32decode(match.group(1).upper())
            return decoded.hex()
    except:
        pass
    return None


def _normalize_response(data):
    if not data or not isinstance(data, dict):
        return data
    mappings = {
        'Hash': 'hash', 'Stat': 'stat', 'FileStats': 'file_stats',
        'Title': 'title', 'Poster': 'poster',
        'DownloadSpeed': 'download_speed', 'UploadSpeed': 'upload_speed',
        'ActivePeers': 'active_peers', 'TotalPeers': 'total_peers',
    }
    for pascal, lower in mappings.items():
        if pascal in data and lower not in data:
            data[lower] = data[pascal]
    file_stats = data.get('file_stats')
    if file_stats and isinstance(file_stats, list):
        for fs in file_stats:
            if isinstance(fs, dict):
                fs_map = {
                    'Id': 'id', 'Path': 'path', 'Length': 'length',
                    'PreloadedBytes': 'preloaded_bytes',
                    'PreloadSize': 'preload_size',
                }
                for p, l in fs_map.items():
                    if p in fs and l not in fs:
                        fs[l] = fs[p]
    return data


class TorrServer(object):
    def __init__(self, host, port, username, password, ssl_enabled=False):
        self._base_url = "{}://{}:{}".format(
            "https" if ssl_enabled else "http", host, port
        )
        self._username = username
        self._password = password
        self._auth = HTTPBasicAuth(self._username, self._password)
        self._session = requests.Session()
        self._info_cache = {}
        self._cache_time = {}

    def log(self, msg):
        log("### [TorrServer API]: %s" % msg)

    # ══════════════════════════════════════════════════════════════
    #  CLEANUP INTELIGENT
    # ══════════════════════════════════════════════════════════════

    def list_torrents(self):
        """Lista TOATE torrentele din TorrServer DB."""
        try:
            payload = {"action": "list"}
            res = self._post("/torrents",
                             data=dumps(payload),
                             headers={'Content-Type': 'application/json'})
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list):
                    return [_normalize_response(item) for item in data
                            if isinstance(item, dict)]
                return []
            return []
        except Exception as e:
            self.log("list_torrents error: %s" % str(e))
            return []

    def cleanup_tracked_hashes(self, addon):
        """
        Șterge DOAR torrentele pe care le-am adăugat NOI.
        
        Citește hash-urile salvate în addon settings și le șterge.
        NU afectează torrentele adăugate manual în TorrServer.
        
        Salvăm multiple hash-uri (separate cu |) pentru cazul
        în care utilizatorul a navigat rapid între torrente.
        """
        try:
            saved = addon.getSetting('torrserver_tracked_hashes') or ''
            if not saved:
                return 0

            hashes = [h.strip() for h in saved.split('|') if h.strip()]
            removed = 0

            for h in hashes:
                try:
                    if self.remove_torrent(h):
                        self.log("Cleanup: removed %s" % h[:16])
                        removed += 1
                    else:
                        self.log("Cleanup: failed to remove %s (may not exist)" % h[:16])
                except:
                    pass

            # Curăță settings-urile
            addon.setSetting('torrserver_tracked_hashes', '')
            addon.setSetting('torrserver_current_hash', '')

            if removed:
                self.log("Cleanup complet: %d torrent(e) sterse" % removed)
            return removed

        except Exception as e:
            self.log("cleanup_tracked error: %s" % str(e))
            return 0

    def save_hash_to_settings(self, addon, info_hash):
        """
        Salvează hash-ul în addon settings pentru cleanup ulterior.
        Adaugă la lista existentă (nu suprascrie).
        """
        try:
            # Hash curent (pentru cleanup la playback stop)
            addon.setSetting('torrserver_current_hash', info_hash)

            # Lista completă (pentru cleanup la următorul apel)
            existing = addon.getSetting('torrserver_tracked_hashes') or ''
            hashes = [h.strip() for h in existing.split('|') if h.strip()]

            if info_hash not in hashes:
                hashes.append(info_hash)

            # Păstrăm doar ultimele 5 (safety)
            hashes = hashes[-5:]
            addon.setSetting('torrserver_tracked_hashes', '|'.join(hashes))

            self.log("Hash saved to settings: %s (total tracked: %d)" % (
                info_hash[:16], len(hashes)))

        except Exception as e:
            self.log("save_hash error: %s" % str(e))

    def cleanup_current(self, addon):
        """
        Cleanup rapid: șterge doar hash-ul CURENT.
        Apelat la playback stop.
        """
        try:
            current = addon.getSetting('torrserver_current_hash') or ''
            if current:
                self.remove_torrent(current)
                self.log("Cleanup current: %s" % current[:16])
                addon.setSetting('torrserver_current_hash', '')

                # Scoatem și din lista tracked
                existing = addon.getSetting('torrserver_tracked_hashes') or ''
                hashes = [h.strip() for h in existing.split('|')
                          if h.strip() and h.strip() != current]
                addon.setSetting('torrserver_tracked_hashes', '|'.join(hashes))
        except Exception as e:
            self.log("cleanup_current error: %s" % str(e))

    # ══════════════════════════════════════════════════════════════
    #  VERIFICARE STREAM
    # ══════════════════════════════════════════════════════════════

    def verify_stream(self, info_hash, file_path, file_id, timeout=12):
        url = self.get_stream_url(info_hash, file_path, file_id)
        try:
            self.log("Verify stream: bytes 0-65535...")
            res = self._session.get(
                url, stream=True, timeout=timeout,
                headers={'Range': 'bytes=0-65535'},
                auth=self._auth)
            if res.status_code in (200, 206):
                data = res.raw.read(4096)
                res.close()
                if data and len(data) > 0:
                    self.log("✓ Stream VERIFIED: %d bytes" % len(data))
                    return True
                return False
            res.close()
            return False
        except requests.exceptions.Timeout:
            self.log("✗ Stream verify: TIMEOUT")
            return False
        except Exception as e:
            self.log("✗ Stream verify: %s" % str(e)[:80])
            return False

    # ══════════════════════════════════════════════════════════════
    #  TORRENT CACHE (magnete publice)
    # ══════════════════════════════════════════════════════════════

    def _try_torrent_cache(self, info_hash):
        cache_urls = [
            "https://itorrents.org/torrent/%s.torrent" % info_hash.upper(),
            "http://bt.t-ru.org/dl/%s" % info_hash.lower(),
        ]
        for url in cache_urls:
            try:
                res = self._session.get(url, timeout=4, verify=False)
                if res.status_code == 200 and len(res.content) > 200:
                    if res.content[:1] == b'd':
                        self.log("✓ Cache HIT: %d bytes" % len(res.content))
                        return res.content
            except:
                continue
        return None

    # ══════════════════════════════════════════════════════════════
    #  ADĂUGARE TORRENT
    # ══════════════════════════════════════════════════════════════

    def add_magnet(self, magnet, title="", poster="", torrent_data_b64=""):
        try:
            payload = {
                "action": "add",
                "link": magnet,
                "title": title,
                "poster": poster,
                "save_to_db": False,
            }
            if torrent_data_b64:
                payload["data"] = torrent_data_b64

            res = self._post("/torrents",
                             data=dumps(payload),
                             headers={'Content-Type': 'application/json'})
            if res.status_code == 200:
                result = _normalize_response(res.json())
                h = result.get("hash")
                self.log("add_magnet OK: %s" % h)
                return h
            else:
                self.log("add_magnet EROARE: HTTP %s" % res.status_code)
                return None
        except Exception as e:
            self.log("add_magnet EXCEPTIE: %s" % str(e))
            return None

    def add_magnet_fast(self, magnet, title="", poster=""):
        info_hash = extract_hash_from_magnet(magnet)
        if info_hash:
            cached = self._try_torrent_cache(info_hash)
            if cached:
                b64 = base64.b64encode(cached).decode('ascii')
                result = self._upload_multipart_raw(cached, info_hash, title, poster)
                if result:
                    return result
                result = self._add_with_data_hash_only(info_hash, b64, title, poster)
                if result:
                    return result
                result = self.add_magnet(magnet, title, poster, b64)
                if result:
                    return result
        return self.add_magnet(magnet, title, poster)

    def _upload_multipart_raw(self, raw_data, name="torrent", title="", poster=""):
        try:
            if not isinstance(name, str) or '.' not in name:
                name = "%s.torrent" % name
            files = {'file': (name, raw_data, 'application/x-bittorrent')}
            form_data = {'title': title, 'poster': poster, 'save': 'false'}
            res = self._session.post(
                self._base_url + '/torrent/upload',
                files=files, data=form_data, auth=self._auth, timeout=30)
            if res.status_code == 200:
                try:
                    result = _normalize_response(res.json())
                    h = result.get('hash')
                    if h:
                        self.log("Upload OK: %s" % h)
                        return h
                except:
                    pass
            return None
        except:
            return None

    def _add_with_data_hash_only(self, info_hash, torrent_b64, title, poster):
        try:
            payload = {
                "action": "add", "link": info_hash,
                "title": title, "poster": poster,
                "data": torrent_b64, "save_to_db": False,
            }
            res = self._post("/torrents", data=dumps(payload),
                             headers={'Content-Type': 'application/json'})
            if res.status_code == 200:
                result = _normalize_response(res.json())
                return result.get("hash")
            return None
        except:
            return None

    def add_file(self, file_path, title="", poster=""):
        filename = os.path.basename(file_path)
        self.log("═══ Procesare: %s ═══" % filename)
        try:
            with open(file_path, 'rb') as f:
                raw_torrent = f.read()
            self.log("Citit: %d bytes" % len(raw_torrent))
            info_hash, magnet_link = get_magnet_from_file(file_path)
            if not info_hash:
                return None
            torrent_b64 = base64.b64encode(raw_torrent).decode('ascii')
            result = self._upload_multipart_raw(raw_torrent, filename, title, poster)
            if result:
                return result
            result = self._add_with_data_hash_only(info_hash, torrent_b64, title, poster)
            if result:
                return result
            result = self.add_magnet(magnet_link, title, poster, torrent_b64)
            if result:
                return result
            return self.add_magnet(magnet_link, title, poster)
        except Exception as e:
            self.log("add_file EXCEPTIE: %s" % str(e))
            return None

    # ══════════════════════════════════════════════════════════════
    #  INFORMAȚII TORRENT
    # ══════════════════════════════════════════════════════════════

    def get_torrent_info_api(self, info_hash):
        try:
            payload = {"action": "get", "hash": info_hash}
            res = self._post("/torrents", data=dumps(payload),
                             headers={'Content-Type': 'application/json'})
            if res.status_code == 200:
                return _normalize_response(res.json())
        except:
            pass
        return None

    def get_torrent_info(self, info_hash):
        try:
            import time as _time
            now = _time.time()
            cache_key = "s_%s" % info_hash
            if cache_key in self._info_cache:
                if now - self._cache_time.get(cache_key, 0) < 0.5:
                    return self._info_cache[cache_key]
            res = self._get("/stream", params={"link": info_hash, "stat": "true"})
            if res.status_code == 200:
                data = _normalize_response(res.json())
                self._info_cache[cache_key] = data
                self._cache_time[cache_key] = now
                return data
        except:
            pass
        return None

    def get_torrent_file_info(self, link, file_index=1):
        try:
            res = self._get("/stream",
                            params={"link": link, "index": file_index, "stat": "true"})
            if res.status_code == 200:
                return _normalize_response(res.json())
        except:
            pass
        return None

    def preload_torrent(self, link, file_id=1, title=""):
        try:
            return self._get("/stream", params={
                "link": link, "index": file_id, "title": title,
                "stat": "true", "preload": "true"
            })
        except:
            return None

    def get_stream_url(self, link, path, file_id):
        return "%s/stream/%s?link=%s&index=%s&play" % (
            self._base_url, quote(path, safe='/'), link, file_id)

    def remove_torrent(self, info_hash):
        try:
            for key in list(self._info_cache.keys()):
                if info_hash in key:
                    del self._info_cache[key]
                    self._cache_time.pop(key, None)
            return self._post(
                "/torrents", data=dumps({"action": "rem", "hash": info_hash}),
                headers={'Content-Type': 'application/json'}
            ).status_code == 200
        except:
            return False

    def _post(self, url, **kwargs):
        return self._request("post", url, **kwargs)

    def _get(self, url, **kwargs):
        return self._request("get", url, **kwargs)

    def _request(self, method, url, **kwargs):
        return self._session.request(
            method, self._base_url + url, auth=self._auth, **kwargs)