"""Tune a Usenet provider: real connection limit, secure ports and speed.

Adapted from Lucent Video's tune.py (MIT), used with permission. The test
opens connections until the account refuses one, compares the secure ports,
then measures speed with more and more connections. It downloads at most
MAX_BYTES of test data; with a block account that counts. Nothing is applied
until the user confirms.
"""

import random
import threading
import time

import xbmc
import xbmcgui

from . import config, nntp

GROUPS = ("alt.binaries.boneless", "alt.binaries.multimedia", "alt.binaries.misc")
LIMIT_MAX = 60
MAX_BYTES = 800 * 1048576
STEP_SECONDS = 6.0
PORT_CONNECTIONS = 8
CLEARLY = 1.10
SETTLE = 10
BETWEEN = 6
PORT_CHOICE = {563: "0", 443: "1", 119: "2"}


class _Probe(nntp.Connection):

    def __init__(self, provider, port=None, timeout=15):
        nntp.Connection.__init__(
            self, provider["host"], port or provider["port"],
            provider.get("user", ""), provider.get("password", ""),
            provider.get("ssl", True), timeout)
        self.chunk = bytearray(262144)

    def group(self, name):
        code, text = self._command("GROUP " + name)
        if code != 211:
            raise nntp.NntpError("GROUP answered %d" % code)
        parts = text.split()
        return int(parts[1]), int(parts[2])

    def body_size(self, number):
        code, _text = self._command("BODY %d" % number)
        if code in (420, 423, 430):
            return 0
        if code != 222:
            raise nntp.NntpError("BODY answered %d" % code)
        size = len(self.buf)
        tail = bytes(self.buf[-4:]) if self.buf else b""
        whole = bytes(self.buf)
        if b"\r\n.\r\n" in whole or self.buf[:3] == b".\r\n":
            self.buf = bytearray()
            return size
        self.buf = bytearray()
        view = memoryview(self.chunk)
        while True:
            got = self.sock.recv_into(view)
            if not got:
                raise nntp.NntpError("connection closed")
            size += got
            edge = tail + bytes(view[max(0, got - 5):got])
            if edge.endswith(b"\r\n.\r\n") or edge == b".\r\n":
                return size
            tail = edge[-4:]


class _Run(object):

    def __init__(self, provider, progress):
        self.p = provider
        self.progress = progress
        self.bytes = 0
        self.range = None
        self.lock = threading.Lock()

    def cancelled(self):
        return (self.progress.iscanceled()
                or xbmc.Monitor().abortRequested()
                or self.bytes >= MAX_BYTES)

    def connect(self, port=None):
        return _Probe(self.p, port or self.p["port"])

    def limit(self):
        held, refused, reason = [], False, ""
        try:
            while len(held) < LIMIT_MAX and not refused and not self.cancelled():
                want = min(10, LIMIT_MAX - len(held))
                results = [None] * want

                def open_one(slot):
                    try:
                        results[slot] = self.connect()
                    except Exception as error:
                        results[slot] = error

                threads = [threading.Thread(target=open_one, args=(number,), daemon=True)
                           for number in range(want)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(30)
                for item in results:
                    if isinstance(item, nntp.Connection):
                        held.append(item)
                    else:
                        refused = True
                        reason = type(item).__name__ if item is not None else "timeout"
                self.progress.update(5 + int(20 * len(held) / LIMIT_MAX),
                                     "Opening connections: %d" % len(held))
        finally:
            for connection in held:
                connection.close()
        return len(held), refused, reason

    def articles(self):
        if self.range:
            return self.range
        connection = self.connect()
        try:
            for name in GROUPS:
                try:
                    first, last = connection.group(name)
                except nntp.NntpError:
                    continue
                if last - first > 1000:
                    low = max(first, last - 3000000)
                    high = max(low, last - 1000)
                    self.range = (name, low, high)
                    return self.range
        finally:
            connection.close()
        raise nntp.NntpError("no binary test group")

    def speed(self, connections, port=None, seconds=STEP_SECONDS):
        name, low, high = self.articles()
        got = [0] * connections
        stop = time.time() + seconds
        errors = []

        def work(slot):
            try:
                connection = self.connect(port)
            except Exception as error:
                errors.append(type(error).__name__)
                return
            try:
                connection.group(name)
                while time.time() < stop and self.bytes < MAX_BYTES:
                    size = connection.body_size(random.randint(low, high))
                    got[slot] += size
                    with self.lock:
                        self.bytes += size
            except Exception as error:
                errors.append(type(error).__name__)
            finally:
                connection.close()

        started = time.time()
        threads = [threading.Thread(target=work, args=(number,), daemon=True)
                   for number in range(connections)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(seconds + 40)
        elapsed = max(0.1, time.time() - started)
        return sum(got) / 1048576.0 / elapsed, len(errors)


def _pause(run, seconds):
    for _ in range(int(seconds * 10)):
        if run.cancelled() or xbmc.Monitor().waitForAbort(0.1):
            return


def _steps(limit):
    steps = [number for number in (4, 8, 12, 16, 20, 30, 40, 50, 60)
             if number <= limit]
    if limit not in steps:
        steps.append(limit)
    return steps


def _even(number):
    number = max(1, min(LIMIT_MAX, int(number)))
    return number if number < 2 else number // 2 * 2


def _suggest(current, limit, refused, speeds):
    if refused and current > limit:
        return _even(limit)
    if not speeds:
        return current
    top = max(speeds.values())
    fastest = min(number for number, speed in speeds.items()
                  if speed >= top * 0.95)
    at_current = max((speed for number, speed in speeds.items()
                      if number <= current), default=0.0)
    if fastest > current and top >= at_current * CLEARLY:
        return _even(fastest)
    return current


def measure(provider, progress):
    run = _Run(provider, progress)
    out = {"current_conns": provider["connections"],
           "current_port": provider["port"], "ssl": provider["ssl"]}
    progress.update(1, "Waiting for old connections to close...")
    for _ in range(SETTLE * 10):
        if run.cancelled() or xbmc.Monitor().waitForAbort(0.1):
            return out
    progress.update(2, "Logging in...")
    run.connect().close()
    _pause(run, BETWEEN)
    limit, refused, reason = run.limit()
    out.update(limit=limit, limit_reached=refused, limit_reason=reason)
    if run.cancelled() or limit < 1:
        return out
    if provider["ssl"]:
        ports = {}
        for number, port in enumerate(sorted(set([563, 443, provider["port"]]))):
            progress.update(30 + 8 * number, "Comparing port %d..." % port)
            _pause(run, BETWEEN)
            try:
                wanted = min(PORT_CONNECTIONS, limit)
                speed, failed = run.speed(wanted, port)
                ports[port] = speed if failed < wanted else 0.0
            except Exception:
                ports[port] = 0.0
            if run.cancelled():
                break
        out["ports"] = ports
        best = max(ports, key=ports.get) if ports else provider["port"]
        current = ports.get(provider["port"], 0.0)
        out["port"] = (best if ports.get(best, 0) >= current * CLEARLY
                       and best != provider["port"] else provider["port"])
    else:
        out["port"] = provider["port"]
    speeds, slower = {}, 0
    steps = _steps(limit)
    for number, connections in enumerate(steps):
        if run.cancelled():
            break
        progress.update(55 + int(40 * number / len(steps)),
                        "Speed with %d connections..." % connections)
        before = max(speeds.values()) if speeds else 0.0
        _pause(run, BETWEEN)
        speed, failed = run.speed(connections, out["port"])
        if failed:
            refused_at = out.setdefault("refused_at", {})
            refused_at[connections] = failed
            xbmc.log("[TMDb Movies] [Usenet] tune: %d of %d connections refused"
                     % (failed, connections), xbmc.LOGINFO)
            break
        speeds[connections] = speed
        slower = slower + 1 if speed < before * 1.03 else 0
        if slower >= 2:
            break
    out["speeds"] = speeds
    out["bytes"] = run.bytes
    out["conns"] = _suggest(provider["connections"], limit, refused, speeds)
    return out


def _report(result):
    lines = []
    limit = result.get("limit", 0)
    if result.get("limit_reached"):
        lines.append("Your account accepts [B]%d[/B] connections (set now: %d)."
                     % (limit, result["current_conns"]))
    else:
        lines.append("Your account accepts at least [B]%d[/B] connections "
                     "(more is not tested; set now: %d)."
                     % (limit, result["current_conns"]))
    if result.get("ports"):
        lines.append("Ports: " + ", ".join(
            ("%d: %.1f MB/s" % (port, speed)) if speed > 0
            else ("%d: does not work" % port)
            for port, speed in sorted(result["ports"].items())))
    if result.get("speeds"):
        lines.append("Speed: " + ", ".join(
            "%d: %.1f MB/s" % (number, speed)
            for number, speed in sorted(result["speeds"].items())))
    for connections, failed in sorted((result.get("refused_at") or {}).items()):
        lines.append("At %d connections the provider refused %d; "
                     "not measured beyond that." % (connections, failed))
    if result.get("bytes"):
        lines.append("Test data: %d MB." % (result["bytes"] >> 20))
    change = []
    if result.get("conns", result["current_conns"]) != result["current_conns"]:
        change.append("connections %d -> [B]%d[/B]"
                      % (result["current_conns"], result["conns"]))
    if result.get("port", result["current_port"]) != result["current_port"]:
        change.append("port %d -> [B]%d[/B]"
                      % (result["current_port"], result["port"]))
    lines.append("")
    if change:
        lines.append("Suggestion: " + ", ".join(change) + ".")
    else:
        lines.append("Suggestion: keep everything as it is.")
    return "[CR]".join(lines), bool(change)


def run(index):
    dialog = xbmcgui.Dialog()
    try:
        index = int(index)
    except (TypeError, ValueError):
        return
    if xbmc.Player().isPlaying():
        dialog.ok("Tune connections",
                  "Stop what is playing first: the test measures your full speed.")
        return
    if not config.provider_enabled(index):
        dialog.ok("Tune connections",
                  "Provider %d is off. Turn it on in Settings > Usenet > Providers." % index)
        return
    provider = config.provider(index)
    if not provider or not provider.get("host"):
        dialog.ok("Tune connections", "Set the host of provider %d first." % index)
        return
    if not provider.get("user") or not provider.get("password"):
        dialog.ok("Tune connections",
                  "Set the username and password of provider %d first." % index)
        return
    if not dialog.yesno(
            "Tune connections",
            "The test measures how many connections your account accepts, "
            "compares the secure ports and measures speed. It fetches up to "
            "about %d MB of test data; with a block account that counts. "
            "Do not play anything meanwhile; after stopping playback, wait "
            "about a minute so old connections close. Nothing changes until "
            "you press Apply.[CR][CR]Start?" % (MAX_BYTES >> 20)):
        return
    try:
        from resources.lib.usenet import server
        server.stop()
    except Exception:
        pass
    progress = xbmcgui.DialogProgress()
    progress.create("Tune connections", "Working...")
    try:
        result = measure(provider, progress)
    except nntp.AuthError:
        progress.close()
        dialog.ok("Tune connections",
                  "Login failed: check the username and password.")
        return
    except nntp.TooMany:
        progress.close()
        dialog.ok("Tune connections",
                  "The provider refused a connection. Close other Usenet programs "
                  "and wait a minute, then try again.")
        return
    except Exception as error:
        progress.close()
        xbmc.log("[TMDb Movies] [Usenet] tune failed: %s" % type(error).__name__,
                 xbmc.LOGWARNING)
        text = "The test did not work (%s)." % type(error).__name__
        if isinstance(error, nntp.NntpError) and "test group" in str(error):
            text = "No binary test group was available on this provider. Try again later."
        dialog.ok("Tune connections", text)
        return
    progress.close()
    xbmc.log("[TMDb Movies] [Usenet] tune provider %d: limit %d%s, ports %s, "
             "speeds %s, %d MB" % (
                 index, result.get("limit", 0),
                 "" if result.get("limit_reached") else "+",
                 ", ".join("%d %.1f" % item for item in
                           sorted((result.get("ports") or {}).items())),
                 ", ".join("%d %.1f" % item for item in
                           sorted((result.get("speeds") or {}).items())),
                 result.get("bytes", 0) >> 20), xbmc.LOGINFO)
    text, change = _report(result)
    if not change:
        dialog.ok("Tune connections", text)
        return
    if not dialog.yesno("Tune connections", text,
                        nolabel="Not now", yeslabel="Apply"):
        return
    addon = config.addon()
    addon.setSetting("usenet_nzb.provider%d.connections" % index,
                     str(result["conns"]))
    choice = PORT_CHOICE.get(int(result.get("port") or 0))
    if choice is not None:
        addon.setSetting("usenet_nzb.provider%d.port" % index, choice)
    xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]",
                                  "Provider %d settings applied." % index,
                                  xbmcgui.NOTIFICATION_INFO, 3000)
