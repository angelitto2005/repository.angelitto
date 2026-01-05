"""
SSL Proxy Server for Kodi Plugin
Bypasses SSL certificate errors by proxying HTTPS requests through HTTP
Optimized for VERY slow connections / servers:
- Threading HTTP server
- Proper Range support (206 Partial Content) for Kodi seeking/buffering
- Robust retries with exponential backoff
- Adaptive chunking + periodic flush
"""
import threading
import socket
import time
from http.server import BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from http.server import HTTPServer

import xbmc
import xbmcaddon

try:
    import requests
    import urllib3
    from urllib3.util.retry import Retry

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    _SESSION = requests.Session()

    # Real retries with backoff (important for slow/unstable servers)
    retry = Retry(
        total=6,
        connect=6,
        read=6,
        backoff_factor=0.6,  # exponential backoff: 0.6, 1.2, 2.4...
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD"]),
        raise_on_status=False,
        respect_retry_after_header=True,
    )

    adapter = requests.adapters.HTTPAdapter(
        pool_connections=20,
        pool_maxsize=50,
        max_retries=retry,
        pool_block=True,  # avoid unbounded growth under load
    )
    _SESSION.mount("http://", adapter)
    _SESSION.mount("https://", adapter)

except ImportError:
    xbmc.log("[SSL Proxy] requests module not available", xbmc.LOGERROR)
    requests = None
    _SESSION = None


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _extract_remote_url(headers, path):
    """
    Accept:
      - Header X-Original-Host: cool.upera.in  (or with protocol)
        and path is /1404/...
      - Or full URL in path:
        /https://cool.upera.in/1404/...
    Returns remote_url or None
    """
    original_host = headers.get("X-Original-Host")
    p = path

    if not original_host:
        if p.startswith("/https://") or p.startswith("/http://"):
            full_url = p[1:]
            # full_url is already full remote URL
            return full_url

    if not original_host:
        return None

    if not original_host.startswith("http"):
        original_host = "https://" + original_host

    # original_host may include protocol; p is regular path
    return original_host.rstrip("/") + p


class ProxyRequestHandler(BaseHTTPRequestHandler):
    # Reduce noise; log to Kodi
    def log_message(self, fmt, *args):
        xbmc.log(f"[SSL Proxy] {fmt % args}", xbmc.LOGDEBUG)

    def _addon_int(self, key, default):
        try:
            addon = xbmcaddon.Addon()
            v = addon.getSetting(key)
            return int(v) if v not in (None, "", "0") else default
        except Exception:
            return default

    def _addon_bool(self, key, default):
        try:
            addon = xbmcaddon.Addon()
            v = addon.getSetting(key)
            if v in ("true", "True", "1", "yes", "Yes", "on", "On"):
                return True
            if v in ("false", "False", "0", "no", "No", "off", "Off"):
                return False
            return default
        except Exception:
            return default

    def _proxy(self, method):
        if not requests:
            self.send_error(500, "requests module not available")
            return

        remote_url = _extract_remote_url(self.headers, self.path)
        if not remote_url:
            self.send_error(400, "Missing X-Original-Host header or full URL in path")
            return

        # Prepare outgoing headers
        out_headers = dict(self.headers)
        out_headers.pop("X-Original-Host", None)
        out_headers.pop("Host", None)
        # Kodi uses Range; keep it
        # Also keep User-Agent/Accept/Accept-Encoding etc.

        # Tunables for slow servers
        connect_timeout = self._addon_int("ssl_proxy_connect_timeout_s", 20)
        read_timeout = self._addon_int("ssl_proxy_read_timeout_s", 180)  # slow drip
        initial_buffer_kb = self._addon_int("ssl_proxy_buffer_kb", 256)  # smaller default for slow
        flush_every_kb = self._addon_int("ssl_proxy_flush_every_kb", 256)
        adaptive_chunks = self._addon_bool("ssl_proxy_adaptive_chunks", True)

        timeout = (connect_timeout, read_timeout)
        session = _SESSION if _SESSION else requests

        xbmc.log(f"[SSL Proxy] {method} {remote_url}", xbmc.LOGINFO)

        try:
            if method == "HEAD":
                resp = session.head(
                    remote_url,
                    headers=out_headers,
                    verify=False,
                    timeout=timeout,
                    allow_redirects=True,
                )
                self.send_response(resp.status_code)
                self._forward_headers(resp.headers)
                self.end_headers()
                return

            # GET (streaming)
            resp = session.get(
                remote_url,
                headers=out_headers,
                verify=False,
                stream=True,
                timeout=timeout,
                allow_redirects=True,
            )

            self.send_response(resp.status_code)
            self._forward_headers(resp.headers)
            self.end_headers()

            # If client requested Range, don't do big initial buffer
            client_range = self.headers.get("Range")
            do_initial_buffer = (client_range is None)

            min_buffer = max(64 * 1024, initial_buffer_kb * 1024) if do_initial_buffer else 0
            flush_every = max(64 * 1024, flush_every_kb * 1024)

            # Adaptive chunking: start smaller for slow servers, increase if stable
            chunk = 16 * 1024 if adaptive_chunks else 64 * 1024
            chunk_max = 256 * 1024

            buffered = bytearray()
            sent_since_flush = 0
            last_progress = time.time()

            for data in resp.iter_content(chunk_size=chunk):
                if not data:
                    continue

                # Update “progress” timestamp
                last_progress = time.time()

                if min_buffer > 0:
                    buffered.extend(data)
                    if len(buffered) >= min_buffer:
                        self._safe_write(buffered)
                        sent_since_flush += len(buffered)
                        buffered.clear()
                        min_buffer = 0  # done buffering
                else:
                    self._safe_write(data)
                    sent_since_flush += len(data)

                # Periodic flush helps slow devices/players
                if sent_since_flush >= flush_every:
                    try:
                        self.wfile.flush()
                    except Exception:
                        pass
                    sent_since_flush = 0

                # If we are streaming ok, increase chunk gradually
                if adaptive_chunks and chunk < chunk_max:
                    # after some successful writes, bump chunk
                    chunk = min(chunk_max, chunk + 8 * 1024)

            # Send remaining buffered data if any
            if buffered:
                self._safe_write(buffered)

            try:
                self.wfile.flush()
            except Exception:
                pass

            xbmc.log(f"[SSL Proxy] OK {remote_url}", xbmc.LOGDEBUG)

        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            xbmc.log("[SSL Proxy] Client disconnected", xbmc.LOGDEBUG)
            return
        except requests.RequestException as e:
            xbmc.log(f"[SSL Proxy] Request failed: {e}", xbmc.LOGERROR)
            try:
                self.send_error(502, f"Proxy error: {e}")
            except Exception:
                pass
        except Exception as e:
            xbmc.log(f"[SSL Proxy] Unexpected error: {e}", xbmc.LOGERROR)
            try:
                self.send_error(500, f"Internal proxy error: {e}")
            except Exception:
                pass

    def _forward_headers(self, headers):
        # Don’t forward hop-by-hop headers
        skip = {
            "transfer-encoding", "connection", "keep-alive",
            "proxy-authenticate", "proxy-authorization", "te",
            "trailers", "upgrade"
        }
        for k, v in headers.items():
            if k.lower() not in skip:
                self.send_header(k, v)

    def _safe_write(self, data: bytes):
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            raise
        except Exception:
            # Let upper handler decide
            raise

    def do_GET(self):
        self._proxy("GET")

    def do_HEAD(self):
        self._proxy("HEAD")


class SSLProxyServer:
    def __init__(self, port=8765):
        self.port = port
        self.server = None
        self.thread = None
        self.running = False
        self._lock = threading.Lock()

    def _find_available_port(self, start_port, max_attempts=20):
        for port in range(start_port, start_port + max_attempts):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.bind(("localhost", port))
                s.close()
                return port
            except OSError:
                continue
        return None

    def start(self):
        with self._lock:
            if self.running:
                xbmc.log("[SSL Proxy] Proxy already running", xbmc.LOGWARNING)
                return True

            try:
                available = self._find_available_port(self.port)
                if available is None:
                    xbmc.log(f"[SSL Proxy] No free port starting from {self.port}", xbmc.LOGERROR)
                    return False
                if available != self.port:
                    xbmc.log(f"[SSL Proxy] Port {self.port} busy, using {available}", xbmc.LOGINFO)
                    self.port = available

                self.server = ThreadingHTTPServer(("localhost", self.port), ProxyRequestHandler)

                # Socket tuning (helpful on slow links)
                self.server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 512 * 1024)
                self.server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 512 * 1024)
                self.server.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

                self.thread = threading.Thread(target=self._run, daemon=True)
                self.thread.start()
                self.running = True
                xbmc.log(f"[SSL Proxy] Started on http://localhost:{self.port}", xbmc.LOGINFO)
                return True

            except Exception as e:
                xbmc.log(f"[SSL Proxy] Failed to start: {e}", xbmc.LOGERROR)
                return False

    def _run(self):
        try:
            self.server.serve_forever()
        except Exception as e:
            xbmc.log(f"[SSL Proxy] Server thread error: {e}", xbmc.LOGERROR)

    def stop(self):
        with self._lock:
            if not self.running:
                return
            try:
                if self.server:
                    self.server.shutdown()
                    self.server.server_close()
                if self.thread and self.thread.is_alive():
                    self.thread.join(timeout=2.0)
            finally:
                self.running = False
                xbmc.log("[SSL Proxy] Stopped", xbmc.LOGINFO)

    def is_running(self):
        return self.running

    def get_proxy_url(self, original_url):
        if not self.running:
            return original_url
        # keep same behavior as your script: embed full url in path
        if original_url.startswith("http://") or original_url.startswith("https://"):
            return f"http://localhost:{self.port}/{original_url}"
        return original_url
