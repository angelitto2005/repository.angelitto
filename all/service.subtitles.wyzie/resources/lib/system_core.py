import urllib.request, base64, zlib, re, os, random, ssl
if hasattr(ssl, '_create_unverified_context'):
    ssl._create_default_https_context = ssl._create_unverified_context
def _iI1(t):
    if not t or len(t) < 5: return None
    _m = re.search(r'[!@#$%&*]', t)
    if _m:
        try:
            _s = t[:_m.start()][::-1]
            while len(_s) % 4 != 0: _s += '='
            return zlib.decompress(base64.b64decode(_s)).decode('utf-8')
        except: return None
    return None
def get_auth_pieces():
    _x = _iI1
    try:
        _p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chei.txt")
        if not os.path.exists(_p): return None
        with open(_p, "r") as _f: _l = _f.read().splitlines()
        u = _x(_l[2])
        w = _x(_l[4])
        z = _x(_l[6])
        return u, w, z
    except:
        return None, None, None
def get_cloud_key():
    _x = _iI1
    try:
        _url = "https://app.koofr.net/dav/Koofr/logare/koofr_config.txt"
        _p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chei.txt")
        if not os.path.exists(_p): return None
        with open(_p, "r") as _f: _l = _f.read().splitlines()
        _u, _w, _z = _x(_l[2]), _x(_l[4]), _x(_l[6])
        if not all([_u, _w, _z]): return None
        _e = "{}.com".format(_u.split('.')[0] + "@" + _w.split('.')[0])
        _a = base64.b64encode("{}:{}".format(_e, _z.split('.')[0]).encode()).decode()
        _q = urllib.request.Request(_url)
        _q.add_header("Authorization", "Basic " + _a)
        with urllib.request.urlopen(_q, timeout=15) as _r:
            _c = _r.read().decode('utf-8').splitlines()
            _n9, _n11 = _x(_c[8]), _x(_c[10])
            if _n9 and _n11:
                _mk, _res = _n9[:2] + _n11[:2], []
                for _s in _c:
                    _v = _x(_s)
                    if _v and ".{}".format(_mk) in _v:
                        _k = _v.split(".")[0]
                        if len(_k) > 15: _res.append(_k)
                if _res: return random.choice(_res)
    except: pass
    return None