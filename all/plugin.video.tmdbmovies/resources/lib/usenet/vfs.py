"""Hand a release to the native vfs.tmdbm add-on instead of the local server.

The VFS add-on reads Usenet itself in C++, so the film never passes through
Python or a local HTTP socket. The Python side only downloads the NZB, reads the
first article to learn the container and the RAR layout, and writes a small plan
file that the VFS add-on follows:

    tmdbm://<key>/<name>

The local HTTP server stays as the fallback when the VFS add-on is missing or
the plan cannot be written.
"""

import base64
import hashlib
import os
import time
import zlib
from urllib.parse import quote

from . import config, engine, indexer

ADDON_ID = 'vfs.tmdbm'
SCHEME = 'tmdbm'
FOLDER = 'usenet-vfs/'
KEEP_SECONDS = 12 * 3600
PLAN_VERSION = 5


def enabled():
    return config.flag('usenet_nzb.vfs', True)


def available():
    try:
        import xbmc
        return bool(xbmc.getCondVisibility('System.AddonIsEnabled(%s)' % ADDON_ID))
    except Exception:
        return False


def _folder():
    base = config.profile_dir()
    if not base:
        return ''
    path = base + FOLDER
    try:
        if not os.path.isdir(path):
            os.makedirs(path)
    except Exception:
        return ''
    return path


def cleanup(max_age=KEEP_SECONDS):
    folder = _folder()
    if not folder:
        return
    now = time.time()
    try:
        names = os.listdir(folder)
    except Exception:
        return
    for name in names:
        if not name.endswith(('.plan', '.first', '.first2', '.tmp')):
            continue
        path = folder + name
        try:
            if now - os.path.getmtime(path) > max_age:
                os.remove(path)
        except Exception:
            pass


def _b64(value):
    encoded = base64.b64encode(str(value or '').encode('utf-8')).decode('ascii')
    return encoded or '===='


def _plan_text(session, info, providers, digest=''):
    lines = ['tmdbm-plan 1']
    if digest:
        lines.append('# meta ' + digest)
    lines.extend([
             'token ' + session.key,
             'name ' + (info.get('name') or 'video.mkv'),
             'container ' + (session.container or 'mkv'),
             'length ' + str(int(session.length)),
             'timeout ' + str(int(session.timeout)),
             'prefetch ' + str(int(session.prefetch_bytes)),
             'cache ' + str(int(session.cache_limit)),
             'pipeline ' + str(int(session.pipeline)),
             'workers ' + str(int(session.worker_target)),
             'holefilling ' + ('1' if session.hole_filling else '0'),
             'holepercent ' + ('%g' % session.hole_percent),
             'holeconsecutive ' + str(int(session.hole_consecutive))])
    for provider in providers:
        lines.append('server %s %d %d %d %d %s %s %s' % (
            provider.get('host') or '',
            int(provider.get('port') or 563),
            1 if provider.get('ssl', True) else 0,
            max(1, int(provider.get('connections') or 1)),
            1 if provider.get('backup') else 0,
            _b64(provider.get('user')),
            _b64(provider.get('password')),
            _b64(provider.get('label') or provider.get('host'))))
    for part in session.parts:
        lines.append('part %d %d %d %d' % (part['id'], int(part.get('skip') or 0),
                                           int(part['length']),
                                           int(part.get('part_size') or 0)))
        for message_id in part['segments']:
            lines.append('a %d %s' % (part['id'], message_id))
    return '\n'.join(lines) + '\n'


def _fingerprint(session, path, providers):
    try:
        stat = os.stat(path)
    except Exception:
        return ''
    bits = ['plan %d' % PLAN_VERSION,
            'nzb %d %d' % (stat.st_size, stat.st_mtime_ns),
            'opts %d %d %d %d %d %d %s %d' % (
                int(session.timeout), int(session.prefetch_bytes),
                int(session.cache_limit), int(session.pipeline),
                int(session.worker_target), 1 if session.hole_filling else 0,
                '%g' % session.hole_percent, int(session.hole_consecutive))]
    for provider in providers:
        bits.append('srv %s %d %d %d %d %s %s %s' % (
            provider.get('host') or '',
            int(provider.get('port') or 563),
            1 if provider.get('ssl', True) else 0,
            max(1, int(provider.get('connections') or 1)),
            1 if provider.get('backup') else 0,
            provider.get('user') or '',
            provider.get('password') or '',
            provider.get('label') or provider.get('host') or ''))
    return hashlib.sha256('\n'.join(bits).encode('utf-8')).hexdigest()


def _plan_reuse(path, digest):
    try:
        if time.time() - os.path.getmtime(path) > KEEP_SECONDS:
            return ''
        with open(path, 'r', encoding='utf-8', errors='replace') as handle:
            head = handle.read(8192)
    except Exception:
        return ''
    meta = ''
    name = ''
    for line in head.splitlines():
        if line.startswith('# meta '):
            meta = line[7:].strip()
        elif line.startswith('name ') and not name:
            name = line[5:].strip()
        elif line.startswith('part '):
            break
    if not name or meta != digest:
        return ''
    return name


def _write(path, text):
    temp = path + '.tmp'
    with open(temp, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write(text)
    os.replace(temp, path)


def _write_first(path, session):
    """Keep the article prepare() already decoded, so the VFS need not fetch it."""
    data = session.first_article()
    segments = session.parts[0]['segments'] if session.parts else []
    if not data or not segments or not session.first_crc_ok:
        return False
    header = 'tmdbm-first 1 %s %d %08x\n' % (
        segments[0], len(data), zlib.crc32(data) & 0xffffffff)
    temp = path + '.tmp'
    with open(temp, 'wb') as handle:
        handle.write(header.encode('utf-8'))
        handle.write(data)
    os.replace(temp, path)
    return True


def _write_warm(path, session):
    """Keep the first few articles prepare() already decoded beside the plan."""
    articles = session.warm
    if not articles or not session.first_crc_ok:
        return False
    total = sum(len(item[2]) for item in articles)
    lines = ['tmdbm-warm 1 %d %d' % (len(articles), total)]
    for index, message_id, data in articles:
        lines.append('%d %s %d %08x' % (
            index, message_id, len(data), zlib.crc32(data) & 0xffffffff))
    temp = path + '.tmp'
    with open(temp, 'wb') as handle:
        handle.write(('\n'.join(lines) + '\n').encode('utf-8'))
        for _index, _message_id, data in articles:
            handle.write(data)
    os.replace(temp, path)
    return True


def prepare_stream(nzb_url):
    """(url, error, retry_with_server).

    retry_with_server is True only when the plan itself could not be produced,
    so the caller may repeat the release through the local HTTP server. A
    release that simply has no working articles is not retried there.
    """
    if not nzb_url:
        return '', 'this source has no NZB link', False
    try:
        cleanup()
        config.cleanup_nzb()
    except Exception:
        pass
    key = config.nzb_key(nzb_url)
    if not indexer.fetch_nzb(nzb_url, key):
        return '', 'the NZB could not be downloaded from the indexer', False
    path = config.nzb_path(key)
    providers = config.primary_providers() + config.backup_providers()
    try:
        session = engine.Session(key, b'', providers, config.player_options())
    except engine.SessionError as exc:
        return '', str(exc), False
    except Exception as exc:
        return '', 'the release could not be opened (%s)' % str(exc)[:90], False
    try:
        folder = _folder()
        digest = _fingerprint(session, path, providers) if folder else ''
        if digest:
            name = _plan_reuse(folder + key + '.plan', digest)
            if name:
                engine._log('plan reused for %s' % key)
                return '%s://%s/%s' % (SCHEME, key, quote(name)), '', False
        try:
            with open(path, 'rb') as handle:
                data = handle.read()
        except Exception as exc:
            return '', 'the NZB could not be read (%s)' % exc, False
        session.data = data
        try:
            info = session.prepare()
        except engine.SessionError as exc:
            if getattr(exc, 'bad_nzb', False):
                try:
                    os.remove(path)
                except Exception:
                    pass
            return '', str(exc), False
        except Exception as exc:
            return '', 'the release could not be opened (%s)' % str(exc)[:90], False
        try:
            if not folder:
                return '', 'the profile folder is not writable', True
            if not digest:
                digest = _fingerprint(session, path, providers)
            cleanup()
            try:
                if not _write_first(folder + key + '.first', session):
                    engine._log('first article not cached for %s' % key)
            except Exception as exc:
                engine._log('first article cache failed (%s)' % str(exc)[:90])
                try:
                    os.remove(folder + key + '.first')
                except Exception:
                    pass
            try:
                _write_warm(folder + key + '.first2', session)
            except Exception as exc:
                engine._log('warm article cache failed (%s)' % str(exc)[:90])
                try:
                    os.remove(folder + key + '.first2')
                except Exception:
                    pass
            _write(folder + key + '.plan', _plan_text(session, info, providers, digest))
        except Exception as exc:
            return '', 'the VFS plan could not be written (%s)' % str(exc)[:90], True
        name = info.get('name') or 'video.mkv'
        return '%s://%s/%s' % (SCHEME, key, quote(name)), '', False
    finally:
        session.close()
