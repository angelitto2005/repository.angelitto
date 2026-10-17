import datetime
import json
import os
import re
import socket
import sys

import xbmc
import xbmcaddon
import xbmcvfs

ADDON_ID = 'tmdbm.trailers'
ADDON = xbmcaddon.Addon(ADDON_ID)
ADDON_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo('path'))
ADDON_PROFILE = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
MEDIA_DIR = os.path.join(ADDON_PATH, 'resources', 'media')

if not os.path.isdir(ADDON_PROFILE):
    try:
        os.makedirs(ADDON_PROFILE)
    except OSError:
        pass


_CHROME_CIPHERS = ('TLS_AES_128_GCM_SHA256:TLS_AES_256_GCM_SHA384:'
                   'TLS_CHACHA20_POLY1305_SHA256:'
                   'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:'
                   'ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:'
                   'ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305')

TLS_PROFILES = (
    {'name': 'chrome', 'ciphers': _CHROME_CIPHERS,
     'curve': None, 'max_version': None},
    {'name': 'rsa-first',
     'ciphers': ('TLS_AES_128_GCM_SHA256:TLS_AES_256_GCM_SHA384:'
                 'TLS_CHACHA20_POLY1305_SHA256:'
                 'ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES128-GCM-SHA256:'
                 'ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-AES256-GCM-SHA384:'
                 'ECDHE-RSA-CHACHA20-POLY1305:ECDHE-ECDSA-CHACHA20-POLY1305'),
     'curve': 'prime256v1', 'max_version': None},
    {'name': 'no-chacha',
     'ciphers': ('TLS_AES_128_GCM_SHA256:TLS_AES_256_GCM_SHA384:'
                 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:'
                 'ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384'),
     'curve': None, 'max_version': None},
    {'name': 'tls12',
     'ciphers': _CHROME_CIPHERS, 'curve': 'X25519', 'max_version': '1.2'},
)


def apply_tls_profile(ctx, profile):
    """Apply one entry of TLS_PROFILES to an SSL context.

    Single source of truth: resources/lib/netcheck.py calls this too, so the
    diagnostic reports exactly the handshake the addon sends instead of its own
    copy of the logic. Returns the curve name that was accepted, '' for none.
    """
    curve = ''
    try:
        ctx.set_ciphers(profile['ciphers'])
    except Exception as exc:
        log('TLS profile {}: cipher list rejected ({})'.format(
            profile.get('name'), str(exc)[:70]), xbmc.LOGWARNING)
    if profile.get('curve'):
        # Python 3.8 hands the name to OpenSSL untouched, and OpenSSL 1.1.1
        # accepts only the lowercase spelling ('X25519' fails with
        # UNKNOWN_GROUP on Kodi's bundled runtime while working on newer).
        for name in (profile['curve'], str(profile['curve']).lower()):
            try:
                ctx.set_ecdh_curve(name)
                curve = name
                break
            except Exception:
                continue
        if not curve:
            log('TLS profile {}: curve {} not accepted by this OpenSSL'.format(
                profile.get('name'), profile['curve']), xbmc.LOGWARNING)
    if profile.get('max_version') == '1.2':
        try:
            import ssl as _ssl2
            ctx.maximum_version = _ssl2.TLSVersion.TLSv1_2
        except Exception:
            pass
    return curve


def new_session(profile=0):
    """requests.Session with a pinned cipher list per profile.

    What this actually does (measured with resources/lib/netcheck.py):
    set_ciphers only rewrites the TLS 1.2 cipher list. TLS 1.3 suites cannot
    be reordered or pinned through stdlib ssl at all - OpenSSL chooses them,
    so every profile still offers 4866/4867/4865 in that order and the
    negotiated suite is identical on Windows and Android. Extension order,
    supported curves, ALPN and GREASE also stay OpenSSL's, so the JA3 does
    NOT converge to a browser's and does NOT converge across platforms; each
    profile is simply a distinct OpenSSL handshake.

    Keep it for profile rotation, but do not expect it to change how the two
    platforms look to YouTube. The "not a bot" gate is decided per egress IP
    and per request pattern, not per ClientHello. Any failure falls back to
    the default session.
    """
    import requests as _rq
    session = _rq.Session()
    _patch_urllib3()
    try:
        import ssl as _ssl
        from requests.adapters import HTTPAdapter as _HA
        try:
            _prof = TLS_PROFILES[int(profile or 0) % len(TLS_PROFILES)]
        except Exception:
            _prof = TLS_PROFILES[0]

        class _ChromeTLSAdapter(_HA):
            def init_poolmanager(self, connections, maxsize, block=False,
                                 **pool_kwargs):
                try:
                    _ctx = _ssl.create_default_context()
                    apply_tls_profile(_ctx, _prof)
                    pool_kwargs['ssl_context'] = _ctx
                except Exception:
                    pass
                return super().init_poolmanager(
                    connections, maxsize, block=block, **pool_kwargs)

        session.mount('https://', _ChromeTLSAdapter())
    except Exception:
        pass
    return session


IP_FAMILY_AUTO = 'auto'
_IP_FAMILY_VALUES = ('auto', 'ipv4', 'ipv6')
_IP_FAMILY_FILE = 'ip_family.json'
_IP_FORCED = [0]          # socket.AF_INET / AF_INET6 while forced, 0 = OS choice
_IP_ORIGINALS = {}
_IP_LAST_LOGGED = [None]


def ip_family_setting():
    """The visible setting, normalised to auto / ipv4 / ipv6."""
    try:
        raw = str(get_setting('ip_family', '') or '').strip().lower()
    except Exception:
        raw = ''
    for value in _IP_FAMILY_VALUES:
        if value in raw:
            return value
    return IP_FAMILY_AUTO


def learned_ip_family():
    """Family that last got past the anti-bot gate on this device, if any."""
    try:
        with open(profile_path(_IP_FAMILY_FILE)) as _fh:
            family = str((json.load(_fh) or {}).get('family') or '').lower()
    except Exception:
        return ''
    return family if family in ('ipv4', 'ipv6') else ''


def learn_ip_family(family):
    """Remember the family that worked so auto mode starts with it.

    Only ever called after a family switch produced a successful extraction,
    so it records evidence, not a guess.
    """
    if family not in ('ipv4', 'ipv6'):
        return False
    if learned_ip_family() == family:
        return True
    try:
        with open(profile_path(_IP_FAMILY_FILE), 'w') as _fh:
            json.dump({'family': family}, _fh)
    except Exception as exc:
        log('IP family not stored: {}'.format(str(exc)[:80]), xbmc.LOGWARNING)
        return False
    log('IP family learned: {} keeps the anonymous player API working'.format(
        family), always=True)
    enforce_ip_family()
    return True


def forget_learned_ip_family():
    """Drop what was learned, so auto goes back to the platform default.

    Called whenever the setting itself changes: an explicit choice by the user
    must not be overridden by a value learned in another situation.
    """
    removed = False
    try:
        if os.path.isfile(profile_path(_IP_FAMILY_FILE)):
            os.remove(profile_path(_IP_FAMILY_FILE))
            removed = True
    except Exception as exc:
        log('IP family memory not cleared: {}'.format(str(exc)[:80]),
            xbmc.LOGWARNING)
    if removed:
        log('IP family memory cleared (setting changed)', always=True)
        enforce_ip_family()
    return removed


def ip_family_preference():
    """auto / ipv4 / ipv6: the setting decides, auto follows what was learned."""
    setting = ip_family_setting()
    if setting != IP_FAMILY_AUTO:
        return setting
    return learned_ip_family() or IP_FAMILY_AUTO


def current_ip_family():
    """What the addon uses right now: ipv4 / ipv6 / auto (OS picks)."""
    if _IP_FORCED[0] == socket.AF_INET6:
        return 'ipv6'
    if _IP_FORCED[0] == socket.AF_INET:
        return 'ipv4'
    return IP_FAMILY_AUTO


def _patch_urllib3():
    """Pin urllib3's own family choice, but only when urllib3 is already loaded.

    urllib3.create_connection() calls socket.getaddrinfo() with the family
    allowed_gai_family() returns, and AF_UNSPEC is 0, so the patched resolver
    above already decides the family. Importing urllib3 here just to rewrite
    that function cost more (urllib3 + ssl + socket + email + logging) than the
    whole listing, so this is the second line of defence and never the first.
    """
    module = sys.modules.get('urllib3.util.connection')
    if module is None or 'allowed_gai_family' in _IP_ORIGINALS:
        return
    try:
        _IP_ORIGINALS['allowed_gai_family'] = module.allowed_gai_family

        def _family_allowed_gai_family():
            if _IP_FORCED[0]:
                return _IP_FORCED[0]
            return _IP_ORIGINALS['allowed_gai_family']()

        module.allowed_gai_family = _family_allowed_gai_family
    except Exception:
        pass


def _install_ip_family_patches():
    """Route every address lookup this process makes through one family.

    socket.getaddrinfo() is the single resolver requests/urllib3/http.client/
    yt-dlp all go through, so patching it covers them; urllib3 gets its own
    hook too when it happens to be loaded already. Lookups that ask for a
    specific family (diagnostics, IPv6 literals) are left alone.
    """
    if _IP_ORIGINALS.get('getaddrinfo'):
        _patch_urllib3()
        return
    _IP_ORIGINALS['getaddrinfo'] = socket.getaddrinfo

    def _family_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        if _IP_FORCED[0] and not family:
            family = _IP_FORCED[0]
        return _IP_ORIGINALS['getaddrinfo'](host, port, family, type, proto, flags)

    socket.getaddrinfo = _family_getaddrinfo
    _patch_urllib3()


def force_ip_family(family):
    """Force a family now: 'ipv4' / 'ipv6' / 'auto' (or 0). Not persistent."""
    try:
        if family in (0, None, '', IP_FAMILY_AUTO):
            _IP_FORCED[0] = 0
            return IP_FAMILY_AUTO
        wanted = socket.AF_INET6 if family == 'ipv6' else socket.AF_INET
        _install_ip_family_patches()
        _IP_FORCED[0] = wanted
        return 'ipv6' if wanted == socket.AF_INET6 else 'ipv4'
    except Exception:
        return current_ip_family()


_IP_PROBE = {}
_IP_PROBE_TTL = 300
_IP_PROBE_FILE = 'ip_family_probe.json'
_IP_PROBE_DISK_TTL = 7200
_IP_PROBE_TIMEOUT = 1.2


def _probe_verdicts():
    try:
        with open(profile_path(_IP_PROBE_FILE)) as _fh:
            data = json.load(_fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _remember_verdict(family, reachable):
    try:
        import time as _time
        data = _probe_verdicts()
        data[family] = [int(_time.time()), bool(reachable)]
        with open(profile_path(_IP_PROBE_FILE), 'w') as _fh:
            json.dump(data, _fh)
    except Exception:
        pass


def family_reachable(family, fresh=False):
    """True when this device really reaches YouTube over that family.

    Pinning a family the network cannot carry would make every YouTube request
    fail, so a specific family is only applied after one TCP connect to a
    resolved address of that family succeeds. The verdict is kept on disk for
    two hours: a fresh interpreter (plugin, service, playback) would otherwise
    repeat the blocking connect before it can show the first listing.

    fresh=True ignores both caches and probes now. Callers that have to act on
    the answer immediately pass it - the anti-bot gate picks the other family
    from this, and a two hour old "reachable" would send playback into a family
    the network stopped carrying in the meantime.
    """
    import time as _time
    now = _time.time()
    known = _IP_PROBE.get(family)
    if not fresh and known and now - known[0] < _IP_PROBE_TTL:
        return known[1]
    stored = None if fresh else _probe_verdicts().get(family)
    try:
        usable = isinstance(stored, (list, tuple)) and len(stored) == 2 \
            and now - float(stored[0]) < _IP_PROBE_DISK_TTL
    except (TypeError, ValueError):
        usable = False
    if usable:
        _IP_PROBE[family] = (now, bool(stored[1]))
        return bool(stored[1])
    reachable = False
    try:
        af = socket.AF_INET6 if family == 'ipv6' else socket.AF_INET
        lookup = _IP_ORIGINALS.get('getaddrinfo', socket.getaddrinfo)
        infos = lookup('www.youtube.com', 443, af, socket.SOCK_STREAM)
        if infos:
            probe = socket.socket(af, socket.SOCK_STREAM)
            probe.settimeout(_IP_PROBE_TIMEOUT)
            try:
                probe.connect(infos[0][4][:2])
                reachable = True
            finally:
                probe.close()
    except Exception:
        reachable = False
    _IP_PROBE[family] = (now, reachable)
    _remember_verdict(family, reachable)
    return reachable


def enforce_ip_family(probe=True):
    """Apply setting plus learned value to the process. Safe to call often.

    probe=False pins the family without testing it first, for callers that
    make no network call of their own (listing routes): the family is still
    applied, it is only not validated, which keeps a folder from waiting on a
    TCP handshake it does not need.
    """
    try:
        preference = ip_family_preference()
        if preference != IP_FAMILY_AUTO and probe \
                and not family_reachable(preference):
            log('IP family {} is not usable on this network; staying on auto'.format(
                preference), xbmc.LOGWARNING)
            preference = IP_FAMILY_AUTO
        effective = force_ip_family(preference)
        marker = (preference, effective)
        if _IP_LAST_LOGGED[0] != marker:
            _IP_LAST_LOGGED[0] = marker
            log('IP family for YouTube: {} (setting {}, learned {})'.format(
                effective, ip_family_setting(),
                learned_ip_family() or '-'), always=True)
        return effective
    except Exception:
        return current_ip_family()


def log(msg, level=xbmc.LOGINFO, always=False):
    try:
        if level == xbmc.LOGINFO and not always and not get_bool('debug', False):
            level = xbmc.LOGDEBUG
        xbmc.log('[{}] {}'.format(ADDON_ID, msg), level)
    except Exception:
        pass


def debug(msg):
    log(msg, xbmc.LOGDEBUG)


SNAPSHOT_PROP = 'tmdbm.trailers.settings'
SNAPSHOT_KEYS = ('ip_family', 'content_country', 'content_language',
                 'content_country_custom', 'content_language_custom',
                 'trending_category', 'live_category', 'trailer_audio',
                 'trailer_max_res', 'subtitles', 'subtitle_language',
                 'results_per_page', 'feed_per_channel', 'autoplay_next',
                 'shuffle_play', 'playback_mode', 'debug', 'extract_cache_ttl',
                  'trending_query_custom', 'hide_shorts', 'ui_language',
                 'prefetch_lists')
_SNAP_RAW = ['']
_SNAP_DATA = [None]
_RPC_WORKS = [None]


def _snapshot():
    try:
        import xbmcgui as _xg
        raw = _xg.Window(10000).getProperty(SNAPSHOT_PROP) or ''
    except Exception:
        return None
    if raw == _SNAP_RAW[0]:
        return _SNAP_DATA[0]
    _SNAP_RAW[0] = raw
    try:
        data = json.loads(raw)
    except Exception:
        data = None
    _SNAP_DATA[0] = data if isinstance(data, dict) else None
    return _SNAP_DATA[0]


def get_setting(name, default='', _use_snapshot=True):
    """Read a setting fresh at call time.

    With reuselanguageinvoker the single ADDON object caches values at import
    time, so settings changed while the interpreter stays alive are not seen.
    Reading through JSON-RPC (Settings Manager) bypasses that stale C++ cache.
    """
    if _use_snapshot:
        try:
            snap = _snapshot()
            if snap is not None and name in snap:
                return str(snap[name])
        except Exception:
            pass
    if _RPC_WORKS[0] is False:
        try:
            return ADDON.getSetting(name)
        except Exception:
            return default
    try:
        res = xbmc.executeJSONRPC(
            '{{"jsonrpc":"2.0","method":"Settings.GetSettingValue",'
            '"params":{{"setting":"{}.{}"}},"id":1}}'.format(ADDON_ID, name))
        val = json.loads(res).get('result', {}).get('value')
        if val is not None:
            _RPC_WORKS[0] = True
            return str(val)
        _RPC_WORKS[0] = False
    except Exception:
        pass
    try:
        return ADDON.getSetting(name)
    except Exception:
        return default


def get_int(name, default=0):
    try:
        return int(str(get_setting(name, default)).strip())
    except (TypeError, ValueError):
        return default


def get_bool(name, default=False):
    return str(get_setting(name, 'true' if default else 'false')).lower() == 'true'


_LANG_CODES = ('en', 'ro', 'hu', 'de', 'es', 'fr', 'id', 'it', 'nl', 'pt-br', 'pt-pt')
_LANG_DIRS = {
              'en': 'resource.language.en_gb',
              'ro': 'resource.language.ro_ro',
              'hu': 'resource.language.hu_hu',
              'de': 'resource.language.de_de',
              'es': 'resource.language.es_es',
              'fr': 'resource.language.fr_fr',
              'id': 'resource.language.id_id',
              'it': 'resource.language.it_it',
              'nl': 'resource.language.nl_nl',
              'pt-br': 'resource.language.pt_br',
              'pt-pt': 'resource.language.pt_pt',
}

_LANG_PACKS = {}


def _load_lang_pack(code):
    if code in _LANG_PACKS:
        return _LANG_PACKS[code]
    pack = {}
    try:
        import re as _re
        path = os.path.join(ADDON_PATH, 'resources', 'language',
                            _LANG_DIRS.get(code, ''), 'strings.po')
        text = open(path, encoding='utf-8').read()
        cur_id = None
        cur_str = None
        for line in text.split('\n'):
            line = line.strip()
            if line.startswith('msgctxt'):
                m = _re.search(r'#(\d+)', line)
                cur_id = int(m.group(1)) if m else None
                cur_str = None
            elif line.startswith('msgstr'):
                m = _re.search(r'"(.*)"', line)
                cur_str = m.group(1) if m else ''
                if cur_id is not None:
                    pack[cur_id] = cur_str.replace('\\"', '"').replace(
                        '\\n', '\n')
                    cur_id = None
    except Exception:
        pass
    _LANG_PACKS[code] = pack
    return pack


def T(string_id):
    try:
        code = str(get_setting('ui_language', '') or '').strip().lower()
    except Exception:
        code = ''
    if code not in _LANG_CODES:
        code = ''
    if code and code != 'en':
        pack = _load_lang_pack(code)
        base = _load_lang_pack('en')
        if string_id in pack and pack[string_id]:
            return pack[string_id]
        if string_id in base:
            return base[string_id]
    try:
        text = ADDON.getLocalizedString(string_id)
        if text:
            return text
    except Exception:
        pass
    base = _load_lang_pack('en')
    return base.get(string_id, '')


def icon(name):
    path = os.path.join(MEDIA_DIR, str(name) + '.png')
    return path if os.path.isfile(path) else ''


def addon_icon():
    path = os.path.join(ADDON_PATH, 'icon.png')
    return path if os.path.isfile(path) else ''


def profile_path(name):
    return os.path.join(ADDON_PROFILE, name)


def relative_date(value):
    """Date for the info column: "3 months ago", "1 year ago".

    YouTube already sends that text for most results, so it is passed through;
    a raw 20240104 or 2024-01-04 is turned into the same wording.
    """
    text = str(value or '').strip()
    if not text:
        return ''

    def _eu(match):
        try:
            month, day = int(match.group(1)), int(match.group(2))
            year = match.group(3)
            if 1 <= month <= 12 and 1 <= day <= 31:
                return '{:02d}.{:02d}.{}'.format(day, month, year)
        except (TypeError, ValueError):
            pass
        return match.group(0)

    converted = re.sub(r'(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})', _eu, text)
    if converted != text:
        return converted
    if not text.isdigit() and '-' not in text:
        return text
    digits = ''.join(ch for ch in text if ch.isdigit())
    if len(digits) < 8:
        return text
    try:
        stamp = datetime.datetime(int(digits[0:4]), int(digits[4:6]),
                                  int(digits[6:8]))
    except ValueError:
        return text
    delta = datetime.datetime.now() - stamp
    days = delta.days
    if days < 0:
        return text
    if days < 1:
        return 'today'
    if days == 1:
        return '1 day ago'
    if days < 7:
        return '{} days ago'.format(days)
    if days < 31:
        weeks = days // 7
        return '{} week{} ago'.format(weeks, '' if weeks == 1 else 's')
    if days < 365:
        months = max(1, days // 30)
        return '{} month{} ago'.format(months, '' if months == 1 else 's')
    years = max(1, days // 365)
    return '{} year{} ago'.format(years, '' if years == 1 else 's')


def ensure_dir(path):
    try:
        if not os.path.isdir(path):
            os.makedirs(path)
    except OSError:
        pass
    return path


# Applied at import so every entry point (plugin, service, playback) reaches
# YouTube over the family the setting - or the last successful attempt - asks
# for, instead of each caller having to remember it. The probe verdict comes
# from disk, so this stays a file read instead of a connect.
try:
    enforce_ip_family(probe=False)
except Exception:
    pass