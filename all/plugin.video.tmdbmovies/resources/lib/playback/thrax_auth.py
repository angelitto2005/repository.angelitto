import json
import os
import time
import urllib.request
import urllib.error

try:
    import xbmc
    import xbmcvfs
    _DIR = xbmcvfs.translatePath("special://profile/addon_data/thrax.auth/")
except Exception:
    xbmc = None
    _DIR = os.path.join(os.path.expanduser("~"), ".thrax_auth")

BASE = "https://api.derzis.xyz"
_FISIER = os.path.join(_DIR, "token.json")
_VERIFICARE_S = 86400
_PAUZA_DUPA_ESEC_S = 300

_cache = None


def _log(msg):
    if xbmc is not None:
        try:
            xbmc.log("[thrax_auth] " + msg, xbmc.LOGINFO)
        except Exception:
            pass


def _citeste():
    try:
        with open(_FISIER, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _scrie(d):
    try:
        os.makedirs(_DIR, exist_ok=True)
        tmp = _FISIER + ".tmp"
        with open(tmp, "w") as f:
            json.dump(d, f)
        os.replace(tmp, _FISIER)
    except Exception as e:
        _log("nu pot salva tokenul: %s" % e)


def _cerere(metoda, cale, corp=None, token=None):
    date = json.dumps(corp).encode() if corp is not None else None
    req = urllib.request.Request(BASE + cale, data=date, method=metoda)
    req.add_header("User-Agent", "Kodi thrax_auth/1")
    req.add_header("Accept", "application/json")
    if date is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("X-Thrax-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _inregistreaza(d):
    if time.time() - d.get("esec", 0) < _PAUZA_DUPA_ESEC_S:
        return None
    model = ""
    if xbmc is not None:
        try:
            model = xbmc.getInfoLabel("System.FriendlyName") or ""
        except Exception:
            pass
    try:
        cod, text = _cerere("POST", "/auth/register",
                            {"platform": "kodi", "model": model[:60], "version": "kodi"})
        token = json.loads(text).get("token") if cod == 200 else None
    except Exception as e:
        cod, token = str(e), None
    if not token:
        _log("inregistrare esuata (%s)" % cod)
        d["esec"] = time.time()
        _scrie(d)
        return None
    _log("aparat inregistrat")
    _scrie({"token": token, "verificat": time.time()})
    return token


def token():
    global _cache
    if _cache:
        return _cache
    d = _citeste()
    tok = d.get("token")
    if not tok:
        tok = _inregistreaza(d)
    elif time.time() - d.get("verificat", 0) > _VERIFICARE_S:
        try:
            cod, _ = _cerere("GET", "/auth/account", token=tok)
        except Exception:
            cod = 0
        if cod == 401:
            _log("tokenul nu mai e recunoscut, cer altul")
            tok = _inregistreaza({})
        elif cod:
            d["verificat"] = time.time()
            _scrie(d)
    _cache = tok
    return tok


def client():
    try:
        import xbmcaddon
        a = xbmcaddon.Addon()
        return "%s/%s" % (a.getAddonInfo("id"), a.getAddonInfo("version"))
    except Exception:
        return "kodi"


def headers():
    tok = token()
    h = {"X-Thrax-Client": client()}
    if tok:
        h["X-Thrax-Token"] = tok
    return h


def uita():
    global _cache
    _cache = None
    _scrie({})
