"""Probe a multi-volume 7z release from the add-on caches.

Usage: probe_7z.py <title fragment>

Reads the cached NZB for the release, groups the .7z.NNN volumes, fetches the
first and last articles from the providers in settings.xml and prints the 7z
start header plus the first data bytes. Credentials are never printed.
"""

import hashlib
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from probe_tail import Conn, yenc_decode

PROFILE = r'C:\Users\Angelitto\AppData\Roaming\Kodi\userdata\addon_data\plugin.video.tmdbmovies'
SETTINGS = os.path.join(PROFILE, 'settings.xml')
CACHE = os.path.join(PROFILE, 'usenet_cache.json')
NZB_DIR = os.path.join(PROFILE, 'usenet', 'nzb')


def settings():
    root = ET.parse(SETTINGS).getroot()
    values = {}
    for node in root.iter('setting'):
        values[node.get('id') or ''] = (node.text or '').strip()
    providers = []
    for index in (1, 2, 3, 4, 5, 6):
        prefix = 'usenet_nzb.provider%d.' % index
        if values.get(prefix + 'enabled', 'false').lower() != 'true':
            continue
        if not values.get(prefix + 'host'):
            continue
        providers.append({
            'host': values.get(prefix + 'host'),
            'port': int(('563', '443', '119')[int(values.get(prefix + 'port') or 0)]),
            'ssl': values.get(prefix + 'ssl', 'true').lower() in ('true', '1'),
            'backup': values.get(prefix + 'backup', 'false').lower() in ('true', '1'),
            'user': values.get(prefix + 'user', ''),
            'password': values.get(prefix + 'password', ''),
        })
    return providers


def find_nzb(fragment):
    cache = json.load(open(CACHE, encoding='utf-8'))
    rows = []
    for entry in cache.values():
        rows.extend(entry.get('rows') or [])
    matches = [r for r in rows if fragment.lower() in (r.get('title') or '').lower()]
    if not matches:
        raise SystemExit('no cached release matches %r' % fragment)
    row = max(matches, key=lambda r: r.get('size') or 0)
    key = hashlib.md5((row.get('nzb_url') or '').encode('utf-8')).hexdigest()
    path = os.path.join(NZB_DIR, key + '.nzb')
    if not os.path.exists(path):
        raise SystemExit('the NZB is not cached: %s' % path)
    return row, path


def nzb_files(path):
    root = ET.parse(path).getroot()
    files = []
    for node in root.iter():
        if not node.tag.endswith('file'):
            continue
        subject = node.get('subject') or ''
        quoted = re.search(r'"([^"]+)"', subject)
        name = quoted.group(1).strip() if quoted else ''
        declared = re.search(r'yEnc\s+(\d+)\s+\((\d+)/(\d+)\)', subject)
        size = int(declared.group(1)) if declared else 0
        segments = []
        for segment in node.iter():
            if not segment.tag.endswith('segment'):
                continue
            text = (segment.text or '').strip().strip('<>')
            if not text:
                continue
            segments.append((int(segment.get('number') or 0), int(segment.get('bytes') or 0), text))
        segments.sort()
        files.append({'name': name, 'size': size, 'segments': segments})
    return files


def volumes(files):
    found = []
    for item in files:
        match = re.search(r'\.7z\.(\d{3,})$', item['name'], re.I)
        if match:
            found.append((int(match.group(1)), item))
    found.sort()
    return [item for _, item in found]


def fetch(providers, message_id):
    for server in providers:
        try:
            conn = Conn(server)
            try:
                raw = conn.body(message_id)
            finally:
                conn.close()
            return yenc_decode(raw), server
        except Exception as exc:
            print('  provider %s failed: %s' % (server['host'], exc))
    return None, None


def main():
    fragment = sys.argv[1] if len(sys.argv) > 1 else 'FraMeSToR'
    row, path = find_nzb(fragment)
    files = nzb_files(path)
    vols = volumes(files)
    if not vols:
        raise SystemExit('no .7z.NNN volumes in the NZB')
    total = sum(v['size'] for v in vols)
    print('release: %s' % row.get('title'))
    print('nzb: %d files, %d 7z volumes, declared total %.2f GB'
          % (len(files), len(vols), total / 1e9))
    for vol in vols[:2] + vols[-2:]:
        print('  %s | %d bytes | %d segments' % (vol['name'], vol['size'], len(vol['segments'])))

    providers = settings()
    print('providers: %s' % ', '.join(p['host'] for p in providers))

    first = fetch(providers, vols[0]['segments'][0][2])
    if not first[0]:
        raise SystemExit('could not fetch the first article')
    head = first[0]['data']
    print('first article: %d bytes (begin %d end %d)' % (len(head), first[0]['begin'], first[0]['end']))
    print('bytes 0..32: %s' % head[:32].hex())
    print('bytes 32..48: %s' % head[32:48].hex())
    print('bytes 32..36 == EBML magic: %s' % (head[32:36] == b'\x1a\x45\xdf\xa3'))
    if head[:6] == b'7z\xbc\xaf\x27\x1c':
        import struct
        version = struct.unpack_from('<H', head, 6)[0]
        start_crc = struct.unpack_from('<I', head, 8)[0]
        nh_offset, nh_size, nh_crc = struct.unpack_from('<QQI', head, 12)
        print('7z version %d.%d, start header crc %08x' % (version // 100, version % 100, start_crc))
        print('next header offset %d, size %d, crc %08x' % (nh_offset, nh_size, nh_crc))
        print('data region: 32 .. %d (%.2f GB)' % (32 + nh_offset, nh_offset / 1e9))

        last = vols[-1]
        before = sum(v['size'] for v in vols[:-1])
        local = 32 + nh_offset - before
        print('next header starts at volume %s local byte %d' % (last['name'], local))
        article = None
        for segment in last['segments']:
            article = segment
        found, _ = fetch(providers, article[2])
        if found:
            begin, end = found['begin'], found['end']
            print('last article: bytes %d..%d of %s' % (begin, end, last['name']))
            data = found['data']
            if begin <= local < end and local + nh_size <= end:
                header = data[local - begin:local - begin + nh_size]
                print('next header first bytes: %s' % header[:24].hex())
                print('next header kind: 0x%02x' % header[0])
            else:
                print('next header is not fully inside the last article')
    else:
        print('not a 7z signature')


if __name__ == '__main__':
    main()
