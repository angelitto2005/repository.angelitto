#!/usr/bin/env python3
"""Network-identity diagnostic for the TMDbM Trailers addon.

Run this on every device that shows different YouTube behaviour (a Windows
PC, an Android TV box, a phone) and compare the output side by side. It dumps
the things that actually decide YouTube's "Sign in to confirm you're not a
bot" gate for an anonymous InnerTube client:

  * the egress public IP for IPv4 AND IPv6 (they are usually different, and
    for IPv6 they are different per device even on one Wi-Fi);
  * which address families the OS prefers for youtube.com (Happy Eyeballs);
  * the Python/OpenSSL/requests/urllib3 stack and which TLS version, cipher
    and ALPN each configured handshake actually negotiates;
  * the raw ClientHello fingerprint (JA3) of the default handshake and of
    every TLS profile in config.TLS_PROFILES - this is what must be identical
    on two devices for the "the TLS handshake is the difference" theory to
    even be testable.

Usage
-----
Windows / desktop (Kodi's own interpreter is not needed):
    python resources/lib/netcheck.py
    python resources/lib/netcheck.py --api dQw4w9WgXcQ   # + one API probe

Anything running the addon (Android TV, Fire TV, LibreELEC, ...):
    the addon exposes it as a route, so it runs inside Kodi and every line
    lands in kodi.log. Enable Settings > Services > Control > Allow remote
    control on the device, then from another machine:

    curl -s -H 'Content-Type: application/json' \
      -d '{"jsonrpc":"2.0","id":1,"method":"Files.GetDirectory",
           "params":{"directory":"plugin://plugin.video.tmdbm.trailers/?mode=netcheck"}}' \
      http://<device-ip>:8080/jsonrpc

    (same call as JSON-RPC "Files.GetDirectory" in any Kodi remote app; add
    &video=<id> to also run the single player API probe)

The --api probe sends exactly one anonymous youtubei/v1/player request with
the same client the addon uses and prints the playabilityStatus it gets back,
so you can see whether the current IP is gated right now.
"""

import argparse
import hashlib
import json
import os
import platform
import socket
import ssl
import sys
import threading

TIMEOUT = 8

# --------------------------------------------------------------------------
# logging: Kodi log when running inside Kodi, stdout anywhere else
# --------------------------------------------------------------------------
try:
    import xbmc  # noqa: F401

    _LOG = True
except Exception:
    _LOG = False


_REPORT = []


def emit(line=''):
    line = str(line)
    _REPORT.append(line)
    try:
        print(line)
    except Exception:
        pass
    if _LOG:
        try:
            import xbmc
            xbmc.log('[tmdbm.trailers.netcheck] {}'.format(line), xbmc.LOGINFO)
        except Exception:
            pass


def section(title):
    emit('')
    emit('=== {} ==='.format(title))


# --------------------------------------------------------------------------
# TLS profiles: reuse the real ones when importable, else mirror config.py
# --------------------------------------------------------------------------
_CHROME_CIPHERS = ('TLS_AES_128_GCM_SHA256:TLS_AES_256_GCM_SHA384:'
                   'TLS_CHACHA20_POLY1305_SHA256:'
                   'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:'
                   'ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:'
                   'ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305')

_FALLBACK_PROFILES = (
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


def load_profiles():
    for candidate in (os.path.dirname(os.path.abspath(__file__)),
                      os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   '..', 'resources', 'lib')):
        if os.path.isdir(candidate) and candidate not in sys.path:
            sys.path.insert(0, candidate)
    try:
        import config  # noqa: F401  (needs xbmc; only works inside Kodi)
        return list(config.TLS_PROFILES)
    except Exception:
        return list(_FALLBACK_PROFILES)


def make_context(profile=None, alpn=None):
    """Same construction the addon uses, with an optional ALPN list.

    urllib3 >= 1.26 sets ALPN ['http/1.1'] on the context it configures, so a
    platform whose bundled urllib3 is older offers no ALPN at all - a real
    handshake difference the addon cannot compensate for.
    """
    ctx = ssl.create_default_context()
    if profile:
        applied = False
        try:
            import config
            config.apply_tls_profile(ctx, profile)   # the addon's own logic
            applied = True
        except Exception:
            applied = False
        if not applied:
            # Standalone run (no Kodi importable): mirror the same logic,
            # curve spellings included, so the report stays faithful.
            try:
                ctx.set_ciphers(profile['ciphers'])
            except Exception as exc:
                emit('    set_ciphers failed for {}: {}'.format(profile['name'], exc))
            if profile.get('curve'):
                for name in (profile['curve'], str(profile['curve']).lower()):
                    try:
                        ctx.set_ecdh_curve(name)
                        break
                    except Exception:
                        continue
            if profile.get('max_version') == '1.2':
                try:
                    ctx.maximum_version = ssl.TLSVersion.TLSv1_2
                except Exception:
                    pass
    if alpn:
        try:
            ctx.set_alpn_protocols(alpn)
        except Exception:
            pass
    return ctx


# --------------------------------------------------------------------------
# ClientHello capture -> JA3
# --------------------------------------------------------------------------
def _parse_client_hello(blob):
    try:
        if len(blob) < 44 or blob[0] != 22 or blob[5] != 1:  # TLS handshake / ClientHello
            return {'error': 'not a ClientHello record ({} bytes)'.format(len(blob))}
        props = {}
        version = int.from_bytes(blob[9:11], 'big')
        # 5 record hdr + 1 msg type + 3 msg length + 2 client_version + 32 random
        p = 5 + 1 + 3 + 2 + 32
        sid = blob[p]
        p += 1 + sid
        n = int.from_bytes(blob[p:p + 2], 'big')
        p += 2
        ciphers = [int.from_bytes(blob[p + i:p + i + 2], 'big')
                   for i in range(0, n, 2)]
        p += n
        comp = blob[p]
        p += 1 + comp
        ext_len = int.from_bytes(blob[p:p + 2], 'big')
        p += 2
        end = min(p + ext_len, len(blob))
        exts, curves, ecpf = [], [], []
        while p + 4 <= end:
            et = int.from_bytes(blob[p:p + 2], 'big')
            el = int.from_bytes(blob[p + 2:p + 4], 'big')
            body = blob[p + 4:p + 4 + el]
            exts.append(et)
            if et == 10 and len(body) >= 2:
                cl = int.from_bytes(body[0:2], 'big')
                curves = [int.from_bytes(body[2 + i:4 + i], 'big')
                          for i in range(0, cl, 2)]
            elif et == 11 and body:
                n2 = body[0]
                ecpf = list(body[1:1 + n2])
            p += 4 + el

        def no_grease(seq):
            return [v for v in seq if (v & 0x0f0f) != 0x0a0a]

        ciphers = no_grease(ciphers)
        exts = no_grease(exts)
        curves = no_grease(curves)
        ja3 = ','.join((
            str(version),
            '-'.join(str(c) for c in ciphers),
            '-'.join(str(e) for e in exts),
            '-'.join(str(c) for c in curves),
            '-'.join(str(f) for f in ecpf),
        ))
        props['ja3'] = ja3
        props['ja3_md5'] = hashlib.md5(ja3.encode()).hexdigest()
        props['ciphers'] = ciphers
        props['extensions'] = exts
        props['curves'] = curves
        return props
    except Exception as exc:
        return {'error': str(exc)}


def capture_ja3(ctx):
    """Ask this machine for the ClientHello it would send to youtube.com."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('127.0.0.1', 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    seen = []

    def serve():
        try:
            conn, _ = srv.accept()
            conn.settimeout(1.5)
            blob = b''
            while len(blob) < 20000:
                try:
                    chunk = conn.recv(65536)
                except Exception:
                    break
                if not chunk:
                    break
                blob += chunk
                if len(blob) >= 5 and len(blob) >= 5 + int.from_bytes(blob[3:5], 'big'):
                    break
            seen.append(blob)
            conn.close()
        except Exception:
            pass

    thread = threading.Thread(target=serve)
    thread.daemon = True
    thread.start()
    try:
        raw = socket.create_connection(('127.0.0.1', port), timeout=3)
        try:
            ctx.wrap_socket(raw, server_hostname='www.youtube.com')
        except Exception:
            pass
    except Exception:
        pass
    finally:
        thread.join(3)
        srv.close()
    return _parse_client_hello(seen[0]) if seen else {'error': 'no ClientHello seen'}


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------
def check_stack():
    section('stack')
    emit('platform      : {} / {}'.format(platform.platform(), platform.machine()))
    emit('python        : {}'.format(sys.version.split()[0]))
    try:
        import xbmc
        emit('kodi          : {} (build {})'.format(
            xbmc.getInfoLabel('System.BuildVersion'),
            xbmc.getInfoLabel('System.BuildVersionCode')))
    except Exception:
        pass
    emit('openssl       : {}'.format(ssl.OPENSSL_VERSION))
    emit('TLS 1.3 / ALPN: {} / {}'.format(ssl.HAS_TLSv1_3, ssl.HAS_ALPN))
    try:
        import requests
        emit('requests      : {}'.format(requests.__version__))
    except Exception as exc:
        emit('requests      : MISSING ({})'.format(exc))
    try:
        import urllib3
        emit('urllib3       : {}'.format(urllib3.__version__))
    except Exception as exc:
        emit('urllib3       : MISSING ({})'.format(exc))


def _text_get(url, timeout=TIMEOUT):
    import requests
    return requests.get(url, timeout=timeout).text.strip()


def check_egress():
    section('egress IP (the gate is keyed on this, not on "the network")')
    for family, url in (('ipv4', 'https://ipv4.icanhazip.com'),
                        ('ipv6', 'https://ipv6.icanhazip.com')):
        try:
            emit('{}          : {}'.format(family, _text_get(url)))
        except Exception as exc:
            emit('{}          : unavailable ({})'.format(
                family, str(exc)[:90]))
    emit('note          : same Wi-Fi does NOT mean same public IP.')
    emit('                IPv6 is per-device (often a rotating privacy')
    emit('                address); only IPv4 NAT is shared.')


def check_dns():
    section('DNS view of www.youtube.com (Happy Eyeballs picks the order)')
    try:
        infos = socket.getaddrinfo('www.youtube.com', 443, proto=socket.IPPROTO_TCP)
    except Exception as exc:
        emit('getaddrinfo failed: {}'.format(exc))
        return
    order = []
    for info in infos:
        fam = 'IPv6' if info[0] == socket.AF_INET6 else 'IPv4'
        if fam not in order:
            order.append(fam)
    counts = {'IPv4': 0, 'IPv6': 0}
    for info in infos:
        counts['IPv6' if info[0] == socket.AF_INET6 else 'IPv4'] += 1
    emit('addresses     : IPv4 x{}, IPv6 x{}'.format(counts['IPv4'], counts['IPv6']))
    emit('preferred     : {}'.format(' > '.join(order) or 'none'))
    emit('               first attempt goes out on {}'.format(order[0] if order else '?'))


def check_transport(host='www.youtube.com', port=443):
    """Which source address this device really uses towards YouTube.

    "Same Wi-Fi" only decides the LAN. What YouTube keys its anti-bot gate on
    is the address the connection arrives from, and that can differ per device
    (IPv6 is per device; a router only shares the IPv4 NAT). This connects to
    youtube.com over each family separately and prints the local address, so
    the two devices' reports answer it without guessing.
    """
    section('source address used towards youtube.com')
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except Exception as exc:
        emit('getaddrinfo failed: {}'.format(str(exc)[:90]))
        return
    first = {}
    for info in infos:
        fam = 'IPv6' if info[0] == socket.AF_INET6 else 'IPv4'
        first.setdefault(fam, info[4][0])
    for fam in ('IPv4', 'IPv6'):
        addr = first.get(fam)
        if not addr:
            emit('{:<5s} : no address for this family'.format(fam))
            continue
        raw = None
        try:
            raw = socket.socket(
                socket.AF_INET6 if fam == 'IPv6' else socket.AF_INET,
                socket.SOCK_STREAM)
            raw.settimeout(TIMEOUT)
            raw.connect((addr, port))
            emit('{:<5s} : local {} -> peer {}  (reachable)'.format(
                fam, raw.getsockname()[0], raw.getpeername()[0]))
        except Exception as exc:
            emit('{:<5s} : FAILED ({})'.format(fam, str(exc)[:70]))
        finally:
            if raw is not None:
                try:
                    raw.close()
                except Exception:
                    pass
    raw = None
    try:
        raw = socket.create_connection((host, port), timeout=TIMEOUT)
        local = raw.getsockname()[0]
        emit('default: {} / {} -> peer {}'.format(
            'IPv6' if ':' in local else 'IPv4', local, raw.getpeername()[0]))
        emit('         this is the address YouTube sees for the addon too;')
        emit('         compare it with the other device\'s report')
    except Exception as exc:
        emit('default: FAILED ({})'.format(str(exc)[:90]))
    finally:
        if raw is not None:
            try:
                raw.close()
            except Exception:
                pass


def _handshake(ctx, host='www.youtube.com'):
    raw = socket.create_connection((host, 443), timeout=TIMEOUT)
    try:
        ssock = ctx.wrap_socket(raw, server_hostname=host)
        try:
            alpn = ssock.selected_alpn_protocol()
        except Exception:
            alpn = '?'
        return ssock.version(), ssock.cipher(), alpn
    finally:
        try:
            raw.close()
        except Exception:
            pass


def check_handshake(profiles):
    section('negotiated handshake (what the server actually sees)')
    ctx = make_context()
    try:
        emit('default       : {} {} alpn={}'.format(*_handshake(ctx)))
    except Exception as exc:
        emit('default       : FAILED ({})'.format(str(exc)[:110]))
    ctx = make_context(alpn=['http/1.1'])  # what urllib3 >= 1.26 does
    try:
        emit('default+alpn  : {} {} alpn={}'.format(*_handshake(ctx)))
    except Exception as exc:
        emit('default+alpn  : FAILED ({})'.format(str(exc)[:110]))
    for prof in profiles:
        try:
            emit('{:14s}: {} {} alpn={}'.format(prof['name'],
                                                *_handshake(make_context(prof))))
        except Exception as exc:
            emit('{:14s}: FAILED ({})'.format(prof['name'], str(exc)[:110]))


def check_fingerprints(profiles):
    section('ClientHello fingerprint / JA3 (one per handshake)')
    ref = capture_ja3(make_context(alpn=['http/1.1']))
    if ref.get('ja3'):
        emit('default+alpn  : {}'.format(ref['ja3_md5']))
        emit('                ciphers   : {}'.format(ref['ciphers']))
        emit('                ext order : {}'.format(ref['extensions']))
        emit('                curves    : {}'.format(ref['curves']))
    else:
        emit('default+alpn  : {}'.format(ref))
    seen = {}
    for prof in profiles:
        # ALPN is part of the real handshake: urllib3 sets it on the context the
        # addon hands it, so the profiles are measured with it too.
        fp = capture_ja3(make_context(prof, alpn=['http/1.1']))
        if fp.get('ja3'):
            seen.setdefault(fp['ja3_md5'], []).append(prof['name'])
            emit('{:14s}: {} ciphers={} curves={}'.format(
                prof['name'], fp['ja3_md5'], fp['ciphers'][:6],
                fp['curves'][:2]))
        else:
            emit('{:14s}: {}'.format(prof['name'], fp))
    section('verdict')
    emit('distinct JA3  : {} of {} profiles'.format(len(seen), len(profiles)))
    if ref.get('ja3') and len(seen) == 1 and ref['ja3_md5'] in seen:
        emit('the pinning changes NOTHING on this device')
    emit('compare this block across devices: if the md5 lines differ, the')
    emit('two platforms really do send different handshakes.')
    emit('these md5s come from a plain ssl context plus ALPN, which is what')
    emit('the addon builds; the "TLS fingerprint:" line the addon logs is the')
    emit('same handshake routed through urllib3 - closer to what YouTube')
    emit('sees - so compare devices on that line first.')


def check_api(video_id):
    section('live player API probe (one anonymous IOS request)')
    import requests
    cpn = 'netcheckdiag0001'
    payload = {
        'context': {'client': {
            'clientName': 'IOS', 'clientVersion': '20.20.7',
            'deviceMake': 'Apple', 'deviceModel': 'iPhone16,2',
            'osName': 'iOS', 'osVersion': '18.5.0.22F76',
            'platform': 'MOBILE', 'hl': 'en', 'gl': 'US'}},
        'cpn': cpn, 'params': '2AMB', 'videoId': video_id,
        'contentCheckOk': True, 'racyCheckOk': True,
    }
    headers = {
        'Origin': 'https://m.youtube.com',
        'User-Agent': ('com.google.ios.youtube/20.20.7'
                       ' (iPhone16,2; U; CPU iOS 18_5_0 like Mac OS X)'),
        'X-YouTube-Client-Name': '5',
        'X-YouTube-Client-Version': '20.20.7',
        'Content-Type': 'application/json',
    }
    session = requests.Session()
    try:
        resp = session.post('https://www.youtube.com/youtubei/v1/player?prettyPrint=false',
                            data=json.dumps(payload), headers=headers, timeout=25)
        body = resp.json()
    except Exception as exc:
        emit('request failed: {}'.format(str(exc)[:150]))
        return
    ps = body.get('playabilityStatus') or {}
    emit('http          : {}'.format(resp.status_code))
    emit('status        : {}'.format(ps.get('status')))
    emit('reason        : {}'.format(ps.get('reason') or '-'))
    emit('formats       : {}'.format(
        len((body.get('streamingData') or {}).get('adaptiveFormats') or [])))
    cookies = session.cookies.get_dict() if session else {}
    emit('cookies set   : {}'.format(sorted(cookies) or 'none'))
    emit('hint          : LOGIN_REQUIRED + "not a bot" = the gate this device')
    emit('                is hitting; OK = this IP is not gated right now.')


def run(api_video=None):
    """Print, log and return the whole report. Used by the route below too."""
    del _REPORT[:]
    # Measure the device as it really is, not as the addon's family setting
    # makes it look: the natural family is what the report exists to show.
    setting, preference, learned = 'auto', 'auto', '-'
    try:
        import config
        config.force_ip_family(0)
        setting = config.ip_family_setting()
        preference = config.ip_family_preference()
        learned = config.learned_ip_family() or '-'
    except Exception:
        pass
    profiles = load_profiles()
    emit('')
    emit('#' * 62)
    emit('# TMDbM Trailers netcheck - run on BOTH devices and diff')
    emit('#' * 62)
    check_stack()
    emit('addon family  : {} (setting {}, learned {})'.format(
        preference, setting, learned))
    emit('                measured with the setting released, so the')
    emit('                addresses below are what this device really uses')
    check_egress()
    check_dns()
    check_transport()
    check_handshake(profiles)
    check_fingerprints(profiles)
    if api_video:
        check_api(api_video)
    try:
        import config
        config.enforce_ip_family()   # put the setting back after measuring
    except Exception:
        pass
    section('done')
    emit('Copy this whole block from each device into one diff.')
    return '\n'.join(_REPORT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api', metavar='VIDEO_ID',
                       help='send one anonymous player API request for VIDEO_ID')
    args = parser.parse_args()
    run(api_video=args.api)


if __name__ == '__main__':
    main()
