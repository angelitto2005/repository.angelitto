"""NNTP transport for reading articles from a Usenet provider.

One Connection is one socket and is not thread safe: a worker uses it, then
gives it back to the pool. Only the commands an NZB player needs are here:
greeting, AUTHINFO, STAT (is the article still there?) and BODY (give me it).
STAT is pipelined: several requests go out before the answers are read, which
is what makes a 40-article availability check cost one round trip instead of
forty.
"""

import socket
import ssl
import threading

OK_GREETING = (200, 201)
OK_STAT = 223
OK_BODY = 222
MISSING_CODES = (420, 423, 430)
RECV_CHUNK = 262144
MAX_LINE = 65536


class NntpError(Exception):
    """The server answered something we cannot use."""


class AuthError(NntpError):
    """Bad username / password."""


class Missing(NntpError):
    """The article is not on this server (430)."""


class TooMany(NntpError):
    """The provider refused another connection (connection limit reached)."""


def _is_too_many(code, text):
    low = (text or '').lower()
    return code in (400, 481, 482, 502) and any(
        word in low for word in ('too many', 'connection', 'limit', 'session', 'max'))


AUTH_HINTS = (
    (('too many', 'connection', 'limit', 'session', 'max'),
     'the connection limit is reached - close other Usenet programs (SABnzbd, NZBGet) '
     'or lower "max connections"'),
    (('auth', 'password', 'passwd', 'login', 'credential', 'invalid', 'incorrect', 'failed',
      'unknown user', 'rejected'),
     'the username or password was refused - use the exact username the provider gave '
     'you (sometimes the full address, the password is case sensitive) and a host '
     'that belongs to the same provider as the account'),
    (('access', 'permission', 'not allowed', 'blocked', 'banned', 'disabled', 'expired',
      'not permitted', 'no posting'),
     'this account is not allowed to connect - check that the plan includes Usenet access '
     'and that your current IP is allowed (a VPN often is not)'),
)


def _explain(code, text):
    """Turn the server's own words into the thing the user has to change."""
    low = (text or '').lower()
    for words, hint in AUTH_HINTS:
        if any(word in low for word in words):
            return hint
    if code in (481, 482):
        return 'the username or password was refused'
    if code == 502:
        return ('the server refused the session - almost always a wrong username or password, '
                'an account without Usenet access, or an IP the account does not allow')
    return 'the login was refused'


def _server_name(greeting):
    """The greeting names the host: it catches an account from another provider."""
    for word in (greeting or '').replace('@', ' @').split():
        if word.startswith('@'):
            continue
        if '.' in word:
            return word[:45]
    return ''


_RESOLVED = {}
_RESOLVE_LOCKS = {}
_RESOLVE_LOCKS_GUARD = threading.Lock()
_TLS = None
_TLS_LOCK = threading.Lock()


def _resolve_lock(key):
    """One lock per host: resolving the backup must not wait for the primary."""
    with _RESOLVE_LOCKS_GUARD:
        lock = _RESOLVE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _RESOLVE_LOCKS[key] = lock
        return lock


def _tls_context():
    """The certificate store is loaded once for all 32 connections, not 32 times."""
    global _TLS
    with _TLS_LOCK:
        if _TLS is None:
            _TLS = ssl.create_default_context()
        return _TLS


def _addresses(host, port):
    """The host resolved once: forty connections must not mean forty DNS lookups.

    Android answers getaddrinfo slowly and the pool opens all connections at
    once, so the first article waited on a resolver queue. IPv4 is tried first:
    a box with broken IPv6 otherwise spends its timeout on the wrong family.
    """
    key = (host, port)
    found = _RESOLVED.get(key)
    if found is not None:
        return found
    with _resolve_lock(key):
        found = _RESOLVED.get(key)
        if found is None:
            found = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
            found.sort(key=lambda item: 0 if item[0] == socket.AF_INET else 1)
            _RESOLVED[key] = found
        return found


def _try(found, timeout):
    error = None
    for family, kind, proto, _name, address in found:
        sock = None
        try:
            sock = socket.socket(family, kind, proto)
            sock.settimeout(timeout)
            sock.connect(address)
            return sock, None
        except OSError as exc:
            error = exc
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass
    return None, error


def _connect(host, port, timeout):
    sock, error = _try(_addresses(host, port), timeout)
    if sock is not None:
        return sock
    with _resolve_lock((host, port)):
        _RESOLVED.pop((host, port), None)
    sock, again = _try(_addresses(host, port), timeout)
    if sock is not None:
        return sock
    raise again or error or OSError('no address for %s' % host)


class Connection(object):
    """One NNTP session."""

    def __init__(self, host, port=563, user='', password='', use_ssl=True, timeout=20):
        self.host = host
        self.port = int(port)
        self.timeout = timeout
        self.closed = False
        raw = _connect(host, self.port, timeout)
        if use_ssl:
            context = _tls_context()
            raw = context.wrap_socket(raw, server_hostname=host)
        raw.settimeout(timeout)
        self.sock = raw
        self.buf = bytearray()
        code, text = self._reply()
        self.greeting = text
        if code not in OK_GREETING:
            self.close()
            reason = 'server said %d %s' % (code, text[:80])
            if _is_too_many(code, text):
                raise TooMany(reason)
            raise NntpError('%s - %s' % (reason, _explain(code, text)))
        if user:
            code, text = self._command('AUTHINFO USER ' + user)
            if code == 381:
                code, text = self._command('AUTHINFO PASS ' + password)
            if code != 281:
                self.close()
                reason = 'login refused: %d %s' % (code, text[:60])
                if _is_too_many(code, text):
                    raise TooMany(reason)
                _who = _server_name(getattr(self, 'greeting', ''))
                raise AuthError('%s - %s%s' % (reason, _explain(code, text),
                                               (' (this server is %s)' % _who) if _who else ''))

    # -- low level ---------------------------------------------------------

    def _fill(self):
        chunk = self.sock.recv(RECV_CHUNK)
        if not chunk:
            raise NntpError('the server closed the connection')
        self.buf += chunk

    def _readline(self):
        while True:
            end = self.buf.find(b'\r\n')
            if end >= 0:
                break
            if len(self.buf) > MAX_LINE:
                raise NntpError('reply line too long')
            self._fill()
        line = bytes(self.buf[:end])
        del self.buf[:end + 2]
        return line

    def _reply(self):
        line = self._readline()
        try:
            code = int(line[:3])
        except ValueError:
            raise NntpError('bad reply %r' % line[:40])
        return code, line[4:].decode('latin-1', 'replace')

    def _command(self, text):
        self.sock.sendall(text.encode('latin-1', 'replace') + b'\r\n')
        return self._reply()

    # -- commands ----------------------------------------------------------

    @staticmethod
    def _angle(message_id):
        return '<%s>' % str(message_id).strip().strip('<>')

    def stat(self, message_id):
        code, _ = self._command('STAT ' + self._angle(message_id))
        return code

    def stat_many(self, message_ids):
        """Pipelined STAT: [(message_id, code)] in the order given."""
        wanted = list(message_ids)
        if not wanted:
            return []
        payload = b''.join(b'STAT ' + self._angle(mid).encode('latin-1') + b'\r\n' for mid in wanted)
        self.sock.sendall(payload)
        return [(mid, self._reply()[0]) for mid in wanted]

    def body(self, message_id):
        """The article as the server sent it (still yEnc)."""
        code, text = self._command('BODY ' + self._angle(message_id))
        if code in MISSING_CODES:
            raise Missing('article %s is gone' % self._angle(message_id))
        if code != OK_BODY:
            raise NntpError('BODY answered %d %s' % (code, text[:60]))
        return self._payload()

    def body_many(self, message_ids):
        """Pipelined BODY: [(message_id, code, article or None)] in the order given.

        Every command goes out before the first answer is read, so the second
        article waits for its own transfer only, not for another round trip.
        A missing article has no body; any other unexpected answer means the
        stream is out of step and the caller must drop the connection.
        """
        wanted = list(message_ids)
        if not wanted:
            return []
        commands = b''.join(b'BODY ' + self._angle(mid).encode('latin-1') + b'\r\n'
                            for mid in wanted)
        self.sock.sendall(commands)
        found = []
        for mid in wanted:
            code, text = self._reply()
            if code in MISSING_CODES:
                found.append((mid, code, None))
                continue
            if code != OK_BODY:
                raise NntpError('BODY answered %d %s' % (code, text[:60]))
            found.append((mid, code, self._payload()))
        return found

    def _payload(self):
        if self.buf[:3] == b'.\r\n':
            del self.buf[:3]
            return b''
        scanned = 0
        while True:
            end = self.buf.find(b'\r\n.\r\n', max(0, scanned - 4))
            if end >= 0:
                break
            scanned = len(self.buf)
            self._fill()
        data = bytes(self.buf[:end])
        del self.buf[:end + 5]
        # NNTP dot stuffing: a body line starting with '.' arrives as '..'
        if data.startswith(b'..'):
            data = data[1:]
        return data.replace(b'\r\n..', b'\r\n.')

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            # Short timeout: a dead provider must not delay Kodi shutting down.
            self.sock.settimeout(0.4)
        except Exception:
            pass
        try:
            self.sock.sendall(b'QUIT\r\n')
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass


    def abort(self):
        """Close the socket with no QUIT: shutdown must not wait on a provider."""
        self.closed = True
        try:
            self.sock.close()
        except Exception:
            pass


def probe(provider, timeout=None):
    """Connect, authenticate and run one STAT. Returns a human readable report.

    Used by the 'Test provider' button: it tells apart a wrong password, a
    blocked port, a TLS problem and a connection limit, which are the four
    failures people actually hit.
    """
    timeout = timeout or provider.get('timeout') or 20
    started = _now()
    target = '%s:%s %s' % (provider.get('host'), provider.get('port'),
                           'TLS' if provider.get('ssl') else 'plain')
    try:
        conn = Connection(provider.get('host'), provider.get('port'), provider.get('user', ''),
                          provider.get('password', ''), provider.get('ssl', True), timeout)
    except AuthError as exc:
        return False, '%s - %s' % (target, exc)
    except TooMany as exc:
        return False, ('%s - %s. Close other Usenet programs or lower "max connections".'
                       % (target, exc))
    except socket.gaierror:
        return False, '%s - the host name could not be resolved' % target
    except ssl.SSLError as exc:
        return False, '%s - TLS refused (%s). Try the other port or turn SSL off.' % (target, exc)
    except (socket.timeout, TimeoutError):
        return False, '%s - no answer in %ds. Try port 443 or 119.' % (target, timeout)
    except Exception as exc:
        return False, '%s - %s' % (target, str(exc)[:90])
    try:
        elapsed = _now() - started
        return True, '%s - logged in in %.1fs, %d connections' % (
            target, elapsed, provider.get('connections') or 1)
    finally:
        conn.close()


def _now():
    import time
    return time.time()
