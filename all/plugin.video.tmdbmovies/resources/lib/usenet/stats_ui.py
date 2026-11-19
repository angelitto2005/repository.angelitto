"""The Usenet statistics window: data per day, providers and indexers.

Adapted from Lucent Video's statistics screen (MIT), used with permission."""

import xbmcgui

from resources.lib.core.config import ADDON_PATH
from resources.lib.usenet import config, stats

COLORS = ["FF8C7BFF", "FF5ED38A", "FFFFB84D", "FF4FC3F7",
          "FFFF7A6B", "FFC792EA", "FF7FD8C4", "FFE6A1C0"]
PERIODS = {101: 30, 102: 7, 106: 90, 103: 0}


def _dec(value, digits=1):
    return "%.*f" % (digits, value)


def _bytes(value):
    value = float(value or 0)
    if value >= 1e12:
        return _dec(value / 1e12, 2) + " TB"
    if value >= 1e11:
        return "%d GB" % round(value / 1e9)
    if value >= 1e9:
        return _dec(value / 1e9) + " GB"
    if value >= 1e6:
        return "%d MB" % round(value / 1e6)
    return "%d KB" % max(1, round(value / 1e3)) if value else "0"


def _count(value):
    value = int(value or 0)
    if value >= 1e6:
        return _dec(value / 1e6) + "M"
    if value >= 1e4:
        return "%dK" % round(value / 1e3)
    return str(value)


def _ms(seconds):
    seconds = float(seconds or 0)
    if seconds >= 1:
        return _dec(seconds, 2) + " s"
    return "%d ms" % round(seconds * 1000)


def _pct(part, whole, digits=None):
    if not whole:
        return "–"
    if not part:
        return "0%"
    value = 100.0 * part / whole
    if digits is None:
        digits = 2 if value < 0.1 else (1 if value < 100 else 0)
    return _dec(value, digits) + "%"


def _bar(fraction):
    return "usenet/stat/h_%03d.png" % (
        int(round(max(0.0, min(1.0, fraction)) * 20)) * 5)


def _buckets(days, most=30):
    """At most `most` bars: long periods are added up per few days."""
    if len(days) <= most:
        return days
    size = -(-len(days) // most)
    out = []
    for start in range(0, len(days), size):
        chunk = days[start:start + size]
        out.append((chunk[0][0], sum(value for _day, value in chunk)))
    return out


def _provider_label(host, backup):
    name = config.provider_name({"host": host}) or host
    return name + (" (backup)" if host == backup else "")


def _indexer_names():
    names = set()
    try:
        names = {entry.get("name") for entry in config.indexers()
                 if entry.get("name")}
    except Exception:
        pass
    try:
        from resources.lib.api import easynews_direct
        if easynews_direct.available():
            names.add("EasyNews Direct")
    except Exception:
        pass
    return names


class Screen(xbmcgui.WindowXMLDialog):

    def onInit(self):
        self.period = 30
        self._headers()
        self._show()
        self.setFocusId(101)

    def _headers(self):
        self.setProperty("title", "Usenet Statistics")
        self.setProperty("p30", "30 days")
        self.setProperty("p7", "7 days")
        self.setProperty("p90", "90 days")
        self.setProperty("pall", "All")
        self.setProperty("wipe", "Clear")
        self.setProperty("close", "Close")
        self.setProperty("h_day", "DATA PER DAY")
        self.setProperty("h_prov", "NNTP PROVIDERS")
        self.setProperty("h_ix", "INDEXERS")
        self.setProperty("h_name", "PROVIDER")
        self.setProperty("h_iname", "INDEXER")
        self.setProperty("h_share", "SHARE")
        self.setProperty("h_data", "DATA")
        self.setProperty("h_speed", "SPEED")
        self.setProperty("h_articles", "ARTICLES")
        self.setProperty("h_wait", "LATENCY")
        self.setProperty("h_errors", "ERRORS")
        self.setProperty("h_missing", "MISSING")
        self.setProperty("h_searches", "SEARCHES")
        self.setProperty("h_nzbs", "NZB'S")
        self.setProperty("h_ok", "SUCCESS")
        self.setProperty("h_bad", "FAILED")
        self.setProperty("h_resp", "RESPONSE")

    def _show(self):
        self.setProperty("period", str(self.period))
        data = stats.summary(self.period)
        self._days(data.get("days") or [])
        self._providers(data.get("providers") or {})
        self._indexers(data.get("indexers") or {})
        self.setProperty(
            "foot",
            "Counters only, no titles, links or keys. Success: the NZB could be "
            "prepared for playback. Latency: time until the provider starts "
            "answering. Storage: %s, kept for a year." % _bytes(data.get("storage")))

    def _days(self, days):
        total = sum(value for _day, value in days)
        shown = len(days)
        if self.period == 7:
            control, bars = self.getControl(401), days
            self.setProperty("bars", "7")
        else:
            control, bars = self.getControl(400), _buckets(days)
            self.setProperty("bars", "30")
            bars = ([("", 0)] * (30 - len(bars))) + bars
        top = max([value for _day, value in bars] + [1])
        items = []
        for _day, value in bars:
            item = xbmcgui.ListItem("")
            item.setProperty("bar", _bar(value / top))
            items.append(item)
        for control_id in (400, 401):
            self.getControl(control_id).reset()
        control.addItems(items)
        if total and shown:
            self.setProperty("nodays", "")
            self.setProperty("daysum", "%s in %d days · %s per day"
                             % (_bytes(total), shown, _bytes(total / shown)))
        else:
            self.setProperty("daysum", "")
            self.setProperty("nodays",
                             "Nothing watched over Usenet in this period")

    def _providers(self, providers):
        control = self.getControl(200)
        control.reset()
        backup = config.provider(2)
        backup = backup.get("host") if backup and backup.get("backup") else ""
        try:
            current = {item.get("host") for item in config.providers()}
        except Exception:
            current = set()
        total = sum(value.get("b", 0) for value in providers.values())
        items = []
        order = sorted(providers.items(), key=lambda pair: -pair[1].get("b", 0))
        for number, (host, value) in enumerate(order):
            item = xbmcgui.ListItem(_provider_label(host, backup))
            if host not in current:
                item.setProperty("gone", "1")
            asked = value.get("a", 0) + value.get("m", 0)
            busy = value.get("busy", 0)
            item.setProperty("color", COLORS[number % len(COLORS)])
            item.setProperty("sbar", _bar(value.get("b", 0) / total if total else 0))
            item.setProperty("share", _pct(value.get("b", 0), total))
            item.setProperty("data", _bytes(value.get("b", 0)))
            item.setProperty("speed", (_dec(value.get("b", 0) / busy / 1e6)
                                       + " MB/s") if busy > 1 else "–")
            item.setProperty("articles", _count(value.get("a", 0)))
            item.setProperty("wait", _ms(value.get("ls", 0) / value["ln"])
                             if value.get("ln") else "–")
            item.setProperty("errors", _pct(value.get("e", 0),
                                            asked + value.get("e", 0)))
            item.setProperty("missing", _pct(value.get("m", 0), asked))
            items.append(item)
        control.addItems(items)
        self.setProperty("noprov", "" if items else
                         "No data from your provider yet")

    def _indexers(self, indexers):
        control = self.getControl(300)
        control.reset()
        names = _indexer_names()
        total = sum(value.get("g", 0) for value in indexers.values())
        items = []
        order = sorted(indexers.items(),
                       key=lambda pair: (-pair[1].get("g", 0),
                                         -pair[1].get("s", 0), pair[0]))
        for number, (name, value) in enumerate(order):
            item = xbmcgui.ListItem(name)
            if name not in names:
                item.setProperty("gone", "1")
            item.setProperty("color", COLORS[number % len(COLORS)])
            item.setProperty("sbar", _bar(value.get("g", 0) / total if total else 0))
            item.setProperty("share", _pct(value.get("g", 0), total))
            item.setProperty("searches", _count(value.get("s", 0)))
            item.setProperty("nzbs", _count(value.get("g", 0)))
            done = value.get("ok", 0) + value.get("bad", 0)
            item.setProperty("ok", _pct(value.get("ok", 0), done, 1))
            if done:
                rate = 100.0 * value.get("ok", 0) / done
                item.setProperty("okc", "g" if rate >= 92 else
                                 ("a" if rate >= 85 else "r"))
            item.setProperty("bad", _count(value.get("bad", 0)))
            answered = value.get("s", 0) - value.get("se", 0)
            item.setProperty("resp", _ms(value.get("ss", 0) / answered)
                             if answered > 0 else "–")
            items.append(item)
        control.addItems(items)
        self.setProperty("ixmore", "%d indexers · scroll down for the rest"
                         % len(items) if len(items) > 8 else "")
        self.setProperty("noix", "" if items else
                         "No searches at your indexers yet")

    def onClick(self, controlId):
        if controlId in PERIODS:
            self.period = PERIODS[controlId]
            self._show()
            return
        if controlId == 104:
            if xbmcgui.Dialog().yesno(
                    "Clear statistics",
                    "Clear all Usenet statistics? This cannot be undone."):
                stats.clear()
                self._show()
            return
        if controlId == 105:
            self.close()

    def onAction(self, action):
        if action.getId() in (9, 10, 13, 92, 110, 117):
            self.close()


def run():
    window = Screen("usenet_stats.xml", ADDON_PATH, "Default", "1080i")
    try:
        window.doModal()
    finally:
        del window
