"""NZB files: what is inside, which file is the film, and how a stored RAR
or 7z set is laid out.

An NZB is XML with one <file> per posted file and one <segment> per article.
Scene releases are usually a RAR or 7z set, so a player must understand the
headers of a *stored* (uncompressed) archive: compressed or encrypted archives
cannot be streamed at all, and we say so instead of serving garbage.
"""

import html
import re
import xml.etree.ElementTree as ET

VIDEO_EXT = ('.mkv', '.mp4', '.m4v', '.avi', '.ts', '.m2ts', '.mov', '.wmv', '.webm', '.mpg', '.mpeg',
             '.iso')
EXTRA_EXT = ('.par2', '.nfo', '.sfv', '.srr', '.nzb', '.jpg', '.jpeg', '.png', '.txt', '.url',
             '.srt', '.sub', '.idx', '.ass', '.ssa', '.exe', '.db', '.sfv')
_RAR_NAME = re.compile(r'\.(?:part\d+\.rar|rar|r\d{2,3}|\d{3})$', re.I)
_SEVEN = re.compile(r'\.7z(?:\.\d+)?$', re.I)
_SEVEN_VOLUME = re.compile(r'\.7z\.(\d+)$', re.I)
_YENC_SIZE = re.compile(r'yEnc\s+(\d+)\s+\((\d+)\s*/\s*(\d+)\)', re.I)
_NAMED = re.compile(r'[\[(](\d{1,5})\s*(?:/|of)\s*\d{1,5}[\])]')
_SAMPLE_FILE = re.compile(
    r'(^|[.\s_\-])(?:sampl(?:e)?|trailer|teaser|featurette|preview)([.\s_\-]|$)', re.I)
_QUOTED = re.compile(r'"([^"]+)"')
_FILE_TAG = re.compile(rb'<file(?=[\s>])')
_SUBJECT = re.compile(rb'\bsubject\s*=\s*(["\'])(.*?)\1', re.S)
_SEGMENT_TAG = re.compile(rb'<segment(?=[\s>])')
_SEGMENT_BYTES_FIRST = re.compile(
    rb'<segment\b[^>]*?\bbytes="(\d+)"[^>]*?\bnumber="(\d+)"[^>]*>([^<]+)</segment>')
_SEGMENT_NUMBER_FIRST = re.compile(
    rb'<segment\b[^>]*?\bnumber="(\d+)"[^>]*?\bbytes="(\d+)"[^>]*>([^<]+)</segment>')

MIN_INNER_VIDEO_BYTES = 20 * 1024 * 1024
_IMAGE_VIDEO_NAME = re.compile(
    r'\.(?:jpe?g|png|gif|webp|bmp|tiff?)\.'
    r'(?:mkv|mp4|m4v|avi|iso|ts|m2ts|mov|wmv|webm|mpg|mpeg)$', re.I)
_RELEASE_EXT = re.compile(
    r'\.(?:mkv|mp4|m4v|avi|iso|ts|m2ts|mov|wmv|webm|mpg|mpeg)$', re.I)


def release_key(title):
    """The same release can arrive from two indexers with a different ending."""
    text = (title or '').strip().lower()
    text = re.sub(r'[\s_]+', '.', text)
    text = _RELEASE_EXT.sub('', text)
    text = re.sub(r'\.{2,}', '.', text)
    return text.strip('.')


class NzbError(Exception):
    pass


class NzbFile(object):
    __slots__ = ('subject', 'name', 'segments', 'bytes', 'kind', 'order')

    def __init__(self, subject='', name='', segments=None, size=0):
        self.subject = subject
        self.name = name
        self.segments = segments or []          # [(number, bytes, message_id)] sorted
        self.bytes = size
        self.kind = kind_of(name)
        match = _NAMED.search(subject or '')
        self.order = int(match.group(1)) if match else 0


def name_of(subject):
    """The file name the poster put in the subject, else a name-looking token."""
    quoted = _QUOTED.search(subject or '')
    if quoted:
        return quoted.group(1).strip()
    found = re.search(r'([\w.\-\[\]() ]+\.(?:mkv|mp4|m4v|avi|ts|m2ts|mov|wmv|webm|mpg|mpeg|iso|rar|r\d{2,3}|\d{3}|par2|nfo|sfv|7z))\b',
                      subject or '', re.I)
    return found.group(1).strip() if found else ''


def kind_of(name):
    low = (name or '').lower()
    if low.endswith(VIDEO_EXT):
        return 'video'
    if low.endswith(EXTRA_EXT):
        return 'extra'
    if _SEVEN.search(low):
        return '7z'
    if _RAR_NAME.search(low):
        return 'rar'
    return 'unknown'


class _ScanFallback(Exception):
    pass


def parse(data):
    """NZB bytes -> [NzbFile] in the order the NZB lists them."""
    if isinstance(data, str):
        data = data.encode('utf-8', 'replace')
    # An NZB never declares entities: refuse one that does (entity expansion).
    if b'<!ENTITY' in data[:8192].upper():
        raise NzbError('the NZB declares XML entities')
    try:
        return _parse_scan(data)
    except _ScanFallback:
        return _parse_tree(data)


def _parse_scan(data):
    """Read the NZB text directly, file by file.

    Only files that can hold the film are kept: a release lists its par2
    blocks as ordinary files, and building elements for them costs more than
    everything else together.
    """
    chunks = _FILE_TAG.split(data)
    if len(chunks) < 2:
        raise _ScanFallback()
    files = []
    for chunk in chunks[1:]:
        end = chunk.find(b'</file>')
        if end < 0:
            raise _ScanFallback()
        body = chunk[:end]
        at = body.find(b'<segments')
        if at < 0:
            raise _ScanFallback()
        found = _SUBJECT.search(body[:at])
        if not found:
            raise _ScanFallback()
        subject = html.unescape(found.group(2).decode('utf-8', 'replace'))
        name = name_of(subject)
        if kind_of(name) == 'extra':
            continue
        block = body[at:]
        segments, total = _scan_segments(block)
        if not segments:
            continue
        segments.sort()
        files.append(NzbFile(subject, name, segments, total))
    if not files:
        raise _ScanFallback()
    return files


def _scan_segments(block):
    expected = len(_SEGMENT_TAG.findall(block))
    matches = _SEGMENT_BYTES_FIRST.findall(block)
    if len(matches) != expected:
        swapped = _SEGMENT_NUMBER_FIRST.findall(block)
        if len(swapped) != expected:
            raise _ScanFallback()
        matches = [(size, number, text) for number, size, text in swapped]
    segments = []
    total = 0
    for size, number, text in matches:
        size = int(size)
        total += size
        segments.append((int(number), size, text.strip().strip(b'<>').decode('utf-8', 'replace')))
    return segments, total


def _parse_tree(data):
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise NzbError('the indexer did not return a valid NZB (%s)' % exc)
    files = []
    for node in root.iter():
        if not node.tag.endswith('file'):
            continue
        subject = node.get('subject') or ''
        segments = []
        total = 0
        for segment in node.iter():
            if not segment.tag.endswith('segment') or not (segment.text or '').strip():
                continue
            try:
                number = int(segment.get('number') or 0)
                size = int(segment.get('bytes') or 0)
            except ValueError:
                number, size = 0, 0
            total += size
            segments.append((number, size, segment.text.strip().strip('<>')))
        if not segments:
            continue
        segments.sort()
        files.append(NzbFile(subject, name_of(subject), segments, total))
    if not files:
        raise NzbError('the NZB has no articles')
    return files


# -- picking the film ---------------------------------------------------------

def pick_media(files):
    """(NzbFile, kind) for the biggest real candidate, or (None, None)."""
    candidates = [f for f in files if f.kind in ('video', 'rar', '7z', 'unknown')]
    if not candidates:
        return None, None
    videos = [f for f in candidates if f.kind == 'video']
    real = [f for f in videos
            if not _SAMPLE_FILE.search(f.name or '')
            and not _SAMPLE_FILE.search(f.subject or '')]
    if real:
        return max(real, key=lambda f: f.bytes), 'video'
    rars = [f for f in candidates if f.kind == 'rar']
    if rars:
        volumes = rar_volumes(files)
        return (volumes[0], 'rar') if volumes else (max(rars, key=lambda f: f.bytes), 'rar')
    seven = [f for f in candidates if f.kind == '7z']
    if seven:
        volumes = seven_volumes(files)
        return (volumes[0], '7z') if volumes else (max(seven, key=lambda f: f.bytes), '7z')
    if videos:
        return None, 'sample'
    return max(candidates, key=lambda f: f.bytes), 'unknown'


def _volume_key(name):
    low = (name or '').lower()
    match = re.search(r'\.part(\d+)\.rar$', low)
    if match:
        return (0, int(match.group(1)))
    if low.endswith('.rar'):
        return (1, -1)
    match = re.search(r'\.([r-z])(\d{2})$', low)
    if match:
        return (1, (ord(match.group(1)) - ord('r')) * 100 + int(match.group(2)))
    match = re.search(r'\.(\d{3})$', low)
    if match:
        return (2, int(match.group(1)))
    return (9, 0)


def _volume_stem(name):
    low = (name or '').lower()
    for pattern in (r'\.part\d+\.rar$', r'\.[r-z]\d{2}$', r'\.\d{3}$'):
        match = re.search(pattern, low)
        if match:
            return low[:match.start()]
    return low[:-4] if low.endswith('.rar') else low


def rar_volumes(files):
    """The volumes of the archive, in order."""
    named = [f for f in files if f.kind == 'rar']
    if named:
        groups = {}
        for item in named:
            groups.setdefault(_volume_stem(item.name), []).append(item)
        best = max(groups.values(), key=lambda group: sum(f.bytes for f in group))
        return sorted(best, key=lambda f: _volume_key(f.name))
    # Obfuscated names: use the poster's counter "[03/45]" and keep the run of
    # large files plus the one smaller file that closes the set.
    unknown = [f for f in files if f.kind == 'unknown']
    if not unknown:
        return []
    groups = {}
    for item in unknown:
        groups.setdefault(item.name, []).append(item)
    best = max(groups.values(), key=lambda group: sum(f.bytes for f in group))
    if len(best) >= 2 and sum(f.bytes for f in best) >= 0.5 * sum(f.bytes for f in unknown):
        unknown = best
    ordered = sorted(enumerate(unknown), key=lambda pair: pair[1].order or pair[0])
    ordered = [item for _, item in ordered]
    if not ordered:
        return []
    biggest = max(f.bytes for f in ordered)
    volumes, closed = [], False
    for item in ordered:
        if item.bytes >= 0.9 * biggest:
            if closed:
                break
            volumes.append(item)
        elif volumes:
            volumes.append(item)
            closed = True
    return volumes


# -- stored RAR ---------------------------------------------------------------

RAR4 = b'Rar!\x1a\x07\x00'
RAR5 = b'Rar!\x1a\x07\x01\x00'


class Unsupported(Exception):
    """Compressed, encrypted or not a RAR: cannot be served as a video."""


def _varint(data, position):
    value = 0
    shift = 0
    while position < len(data):
        byte = data[position]
        position += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, position
        shift += 7
    raise Unsupported('truncated RAR header')


def rar_layout(head):
    """Where the stored file's data sits inside one volume.

    Returns {'fmt', 'offset', 'length', 'unp_size', 'store', 'encrypted',
    'name', 'first', 'more', 'next_offset'} - 'more' means the file continues
    in the next volume; 'next_offset' is where that next volume's data starts
    (main header + this file's header), without any poster in front of it.
    """
    if head.startswith(RAR5):
        return _layout_rar5(head)
    if head.startswith(RAR4):
        return _layout_rar4(head)
    raise Unsupported('not a RAR volume')


def _inner_kind(name):
    low = (name or '').lower()
    if _IMAGE_VIDEO_NAME.search(low):
        return ''
    if low.endswith(VIDEO_EXT):
        return 'video'
    if low.endswith(EXTRA_EXT):
        return ''
    if _SEVEN.search(low) or _RAR_NAME.search(low):
        return 'archive'
    return 'unknown'


def _pick_inner(entries):
    """The film, not the poster or a sample that sits first in the volume."""
    def size_of(entry):
        try:
            return int(entry.get('unp_size') or 0)
        except (TypeError, ValueError):
            return 0

    video = [entry for entry in entries
             if _inner_kind(entry.get('name')) == 'video'
             and not _SAMPLE_FILE.search(entry.get('name') or '')
             and size_of(entry) >= MIN_INNER_VIDEO_BYTES]
    if video:
        return max(video, key=size_of)
    for kind in ('unknown', 'archive'):
        found = [entry for entry in entries
                 if _inner_kind(entry.get('name')) == kind
                 and size_of(entry) >= MIN_INNER_VIDEO_BYTES]
        if found:
            return max(found, key=size_of)
    raise Unsupported('no video file in the first RAR volume')


def _layout_rar4(data):
    import struct
    position = len(RAR4)
    first = True
    main_end = 0
    entries = []
    while position + 7 <= len(data):
        _crc, kind, flags, head_size = struct.unpack_from('<HBHH', data, position)
        if head_size < 7:
            break
        extra = 0
        if flags & 0x8000 and kind != 0x74:
            extra = struct.unpack_from('<I', data, position + 7)[0]
        if kind == 0x73:                                   # main header
            if flags & 0x0080:
                raise Unsupported('the RAR set has encrypted headers')
            if flags & 0x0001:
                first = bool(flags & 0x0100) if flags & 0x0010 else first
            main_end = position + head_size + extra
        elif kind == 0x74:                                 # file header
            packed, unpacked = struct.unpack_from('<II', data, position + 7)
            method = data[position + 25]
            name_size = struct.unpack_from('<H', data, position + 26)[0]
            name_at = position + 32
            if flags & 0x0100:
                high_packed, high_unpacked = struct.unpack_from('<II', data, position + 32)
                packed += high_packed << 32
                unpacked += high_unpacked << 32
                name_at += 8
            name = data[name_at:name_at + name_size].split(b'\x00')[0].decode('utf-8', 'replace')
            if flags & 0x0004:
                raise Unsupported('this RAR is password protected')
            entries.append({'fmt': 4, 'offset': position + head_size, 'length': packed,
                            'unp_size': unpacked, 'store': method == 0x30,
                            'encrypted': False, 'name': name, 'first': first,
                            'header_len': head_size,
                            'more': bool(flags & 0x0002)})
            position += head_size + packed
            continue
        elif kind == 0x7B:                                 # end of archive
            break
        position += head_size + extra
    if not entries:
        raise Unsupported('no file header in the first RAR volume')
    movie = _pick_inner(entries)
    movie['next_offset'] = (main_end + movie['header_len']) if main_end else movie['offset']
    return movie


def _layout_rar5(data):
    position = len(RAR5)
    first = True
    volume = 0
    has_volume = False
    main_end = 0
    entries = []
    while position + 6 < len(data):
        crc_at = position
        position += 4                                      # header CRC32
        header_size, cursor = _varint(data, position)
        header_start = cursor
        kind, cursor = _varint(data, cursor)
        flags, cursor = _varint(data, cursor)
        extra = 0
        data_size = 0
        if flags & 0x01:
            extra, cursor = _varint(data, cursor)
        if flags & 0x02:
            data_size, cursor = _varint(data, cursor)
        header_end = header_start + header_size
        if kind == 1:                                      # main header
            archive_flags, cursor = _varint(data, cursor)
            has_volume = bool(archive_flags & 0x02)
            if has_volume:
                volume, cursor = _varint(data, cursor)
                first = volume == 0
            main_end = header_end + data_size
        elif kind == 4:
            raise Unsupported('the RAR set has encrypted headers')
        elif kind == 2:                                    # file header
            file_flags, cursor = _varint(data, cursor)
            unpacked, cursor = _varint(data, cursor)
            _attributes, cursor = _varint(data, cursor)
            if file_flags & 0x02:
                cursor += 4
            if file_flags & 0x04:
                cursor += 4
            compression, cursor = _varint(data, cursor)
            _host, cursor = _varint(data, cursor)
            name_size, cursor = _varint(data, cursor)
            name = data[cursor:cursor + name_size].decode('utf-8', 'replace')
            encrypted = False
            record = header_end - extra
            while extra and record < header_end:
                record_size, record_cursor = _varint(data, record)
                record_kind, _ = _varint(data, record_cursor)
                if record_kind == 1:
                    encrypted = True
                record = record_cursor + record_size
            if encrypted:
                raise Unsupported('this RAR is password protected')
            entries.append({'fmt': 5, 'offset': header_end, 'length': data_size,
                            'unp_size': unpacked,
                            'store': ((compression >> 7) & 0x07) == 0,
                            'encrypted': False, 'name': name, 'first': first,
                            'volume': volume, 'volfield': has_volume,
                            'header_len': header_end - crc_at,
                            'more': bool(flags & 0x10)})
            position = header_end + data_size
            continue
        elif kind == 5:
            break
        position = header_end + data_size
    if not entries:
        raise Unsupported('no file header in the first RAR volume')
    movie = _pick_inner(entries)
    movie['next_offset'] = (main_end + movie['header_len']) if main_end else movie['offset']
    return movie


# -- stored 7z ----------------------------------------------------------------

SEVEN = b'7z\xbc\xaf\x27\x1c'


def file_size(item):
    """The exact decoded size of one posted file when the subject says it."""
    match = _YENC_SIZE.search(item.subject or '')
    if match:
        declared = int(match.group(1))
        if declared >= item.bytes * 0.9:
            return declared
    return item.bytes


def _seven_stem(name):
    low = (name or '').lower()
    match = _SEVEN_VOLUME.search(low)
    if match:
        return low[:match.start()]
    return low[:-3] if low.endswith('.7z') else low


def _seven_key(name):
    low = (name or '').lower()
    match = _SEVEN_VOLUME.search(low)
    return (0, int(match.group(1))) if match else (1, 0)


def seven_volumes(files):
    """The volumes of the 7z set, in order (a plain .7z is a one-volume set)."""
    named = [f for f in files if f.kind == '7z']
    if not named:
        return []
    groups = {}
    for item in named:
        groups.setdefault(_seven_stem(item.name), []).append(item)
    best = max(groups.values(), key=lambda group: sum(f.bytes for f in group))
    return sorted(best, key=lambda f: _seven_key(f.name))


def seven_layout(head):
    """The stored file data starts after the 32-byte start header."""
    if not head.startswith(SEVEN) or len(head) < 32:
        raise Unsupported('not a 7z archive')
    import struct
    next_offset, next_size = struct.unpack_from('<QQ', head, 12)
    if next_offset <= 0:
        raise Unsupported('this 7z archive has no file data')
    if next_size <= 0:
        raise Unsupported('the 7z header is missing from the first volume')
    return {'offset': 32, 'length': next_offset, 'header_size': next_size}
