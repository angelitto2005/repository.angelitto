"""NZB files: what is inside, which file is the film, and how a stored RAR
or 7z set is laid out.

An NZB is XML with one <file> per posted file and one <segment> per article.
Scene releases are usually a RAR or 7z set, so a player must understand the
headers of a *stored* (uncompressed) archive: compressed or encrypted archives
cannot be streamed at all, and we say so instead of serving garbage.
"""

import html
import lzma
import re
import struct
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


_EPISODE_S = re.compile(r's(\d{1,2})\s*[._ -]?\s*e(\d{1,3})', re.I)
_EPISODE_X = re.compile(r'(?<!\d)(\d{1,2})x(\d{1,3})(?!\d)', re.I)
_EPISODE_NEXT = re.compile(r'[._ -]*e(\d{1,3})', re.I)
_EPISODE_RANGE = re.compile(r'\s*[-\u2013]\s*(?:e(\d{1,3})|(\d{1,2})(?!\d))', re.I)


def episode_pairs(title):
    """Every (season, episode) a release name declares: S01E01E02, S01E01-E02, 1x01-02."""
    text = str(title or '').lower()
    pairs = set()
    for pattern in (_EPISODE_S, _EPISODE_X):
        for match in pattern.finditer(text):
            season = int(match.group(1))
            pairs.add((season, int(match.group(2))))
            position = match.end()
            while True:
                more = _EPISODE_NEXT.match(text, position)
                if not more:
                    break
                pairs.add((season, int(more.group(1))))
                position = more.end()
            span = _EPISODE_RANGE.match(text, position)
            if span:
                pairs.add((season, int(span.group(1) or span.group(2))))
    return pairs


def select_media(files, season=None, episode=None, alt_season=None, alt_episode=None):
    """(NzbFile, kind) for the requested episode inside a pack.

    A pack is posted either as one video per episode or as one RAR/7z set per
    episode, and the names say which. alt_* is the same episode under an
    alternate numbering (anime), because one source list can mix both. When no
    candidate declares an episode the request cannot be matched, so the biggest
    file remains the choice.
    """
    if season is None or episode is None:
        return pick_media(files)
    wanted = [(int(season), int(episode))]
    try:
        alt = (int(alt_season), int(alt_episode))
    except (TypeError, ValueError):
        alt = None
    if alt and alt not in wanted:
        wanted.append(alt)
    choices = _media_choices(files)
    if not any(episode_pairs(' '.join(texts)) for _head, _kind, _size, texts in choices):
        return pick_media(files)
    matches = [choice for choice in choices
               if any(pair in episode_pairs(' '.join(choice[3])) for pair in wanted)]
    if not matches and len(choices) == 1:
        return choices[0][0], choices[0][1]
    if not matches:
        raise NzbError('the release has no file for S%02dE%02d' % wanted[0])
    videos = [choice for choice in matches if choice[1] == 'video']
    head, kind, _size, _texts = max(videos or matches, key=lambda choice: choice[2])
    return head, kind


def _media_choices(files):
    """(head, kind, size, texts) for every playable choice in the NZB."""
    choices = []
    for item in files:
        if item.kind not in ('video', 'unknown'):
            continue
        if _SAMPLE_FILE.search(item.name or '') or _SAMPLE_FILE.search(item.subject or ''):
            continue
        choices.append((item, item.kind, item.bytes, (item.name or '', item.subject or '')))
    for kind, groups in (('rar', _rar_groups(files)), ('7z', _seven_groups(files))):
        for group in groups:
            texts = (group[0].name or '', group[0].subject or '')
            choices.append((group[0], kind, sum(f.bytes for f in group), texts))
    return choices


def _groups(files, kind, stem):
    groups = {}
    for item in files:
        if item.kind == kind:
            groups.setdefault(stem(item.name), []).append(item)
    return list(groups.values())


def pack_info(files):
    """What the NZB really carries: {'pack', 'episodes', 'per_episode'}.

    A pack can be posted under the first episode's name, so the file names are
    the only place that says how many episodes are inside.
    """
    sizes = {}
    for item in files:
        if item.kind == 'video':
            _add_pairs(sizes, item.name or item.subject, item.bytes)
    for groups in (_rar_groups(files), _seven_groups(files)):
        for group in groups:
            total = sum(f.bytes for f in group)
            _add_pairs(sizes, group[0].name or group[0].subject, total)
    pairs = sorted(sizes)
    return {
        'pack': len(pairs) > 1,
        'episodes': len(pairs),
        'per_episode': dict(('S%02dE%02d' % pair, sizes[pair]) for pair in pairs),
    }


def _add_pairs(sizes, text, size):
    for pair in episode_pairs(text):
        sizes[pair] = sizes.get(pair, 0) + size


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


def _rar_groups(files):
    return _groups(files, 'rar', _volume_stem)


def rar_volumes(files, head=None):
    """The volumes of the archive, in order; head selects one set of a pack."""
    groups = _rar_groups(files)
    if groups:
        for group in groups:
            if head is not None and head in group:
                return sorted(group, key=lambda f: _volume_key(f.name))
        best = max(groups, key=lambda group: sum(f.bytes for f in group))
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


def rar_names_unsorted(volumes):
    """True when the names carry no usable order (obfuscated repacks)."""
    keys = [_volume_key(item.name) for item in volumes]
    return len(set(keys)) < len(keys) or any(key[0] == 9 for key in keys)


def rar5_volume(head):
    """The volume number from a RAR5 main header, or None when it has none."""
    if not head.startswith(RAR5):
        return None
    try:
        position = len(RAR5) + 4
        header_size, cursor = _varint(head, position)
        header_start = cursor
        kind, cursor = _varint(head, cursor)
        if kind != 1:
            return None
        flags, cursor = _varint(head, cursor)
        if flags & 0x01:
            _extra, cursor = _varint(head, cursor)
        if flags & 0x02:
            _data, cursor = _varint(head, cursor)
        archive_flags, cursor = _varint(head, cursor)
        if not archive_flags & 0x02:
            return None
        number, cursor = _varint(head, cursor)
        return number if header_start + header_size >= cursor else None
    except Unsupported:
        return None


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


def _seven_groups(files):
    return _groups(files, '7z', _seven_stem)


def seven_volumes(files, head=None):
    """The volumes of the 7z set, in order; head selects one set of a pack."""
    groups = _seven_groups(files)
    if not groups:
        return []
    for group in groups:
        if head is not None and head in group:
            return sorted(group, key=lambda f: _seven_key(f.name))
    best = max(groups, key=lambda group: sum(f.bytes for f in group))
    return sorted(best, key=lambda f: _seven_key(f.name))


def _seven_number(data, pos):
    """One 7z variable-length number: (value, new position)."""
    first = data[pos]
    pos += 1
    mask = 0x80
    value = 0
    for index in range(8):
        if not (first & mask):
            value |= (first & (mask - 1)) << (8 * index)
            return value, pos
        value |= data[pos] << (8 * index)
        pos += 1
        mask >>= 1
    return value, pos


def _seven_digests_length(data, pos, count):
    defined = data[pos]
    pos += 1
    if defined:
        return pos + 4 * count
    flags = data[pos:pos + (count + 7) // 8]
    pos += len(flags)
    for index in range(count):
        if flags[index // 8] & (0x80 >> (index % 8)):
            pos += 4
    return pos


def _seven_pack_info(data, pos):
    pack_pos, pos = _seven_number(data, pos)
    count, pos = _seven_number(data, pos)
    sizes = [0] * count
    while True:
        prop = data[pos]
        pos += 1
        if prop == 0x00:
            break
        if prop == 0x09:
            for index in range(count):
                sizes[index], pos = _seven_number(data, pos)
        elif prop == 0x0A:
            pos = _seven_digests_length(data, pos, count)
        else:
            raise Unsupported('unsupported 7z pack property')
    return {'pack_pos': pack_pos, 'sizes': sizes}, pos


def _seven_unpack_info(data, pos):
    prop = data[pos]
    pos += 1
    if prop != 0x0B:
        raise Unsupported('unsupported 7z folder layout')
    count, pos = _seven_number(data, pos)
    if data[pos]:
        raise Unsupported('this 7z keeps its folder list outside the archive')
    pos += 1
    folders = []
    for _ in range(count):
        coders_count, pos = _seven_number(data, pos)
        coders = []
        total_in = total_out = 0
        for _ in range(coders_count):
            flags = data[pos]
            pos += 1
            size = flags & 0x0F
            method = data[pos:pos + size]
            pos += size
            if flags & 0x10:
                num_in, pos = _seven_number(data, pos)
                num_out, pos = _seven_number(data, pos)
            else:
                num_in = num_out = 1
            props = b''
            if flags & 0x20:
                length, pos = _seven_number(data, pos)
                props = data[pos:pos + length]
                pos += length
            coders.append({'method': method, 'props': props,
                           'num_in': num_in, 'num_out': num_out})
            total_in += num_in
            total_out += num_out
        for _ in range(max(0, total_out - 1)):
            _, pos = _seven_number(data, pos)
            _, pos = _seven_number(data, pos)
        packed_streams = total_in - max(0, total_out - 1)
        if packed_streams > 1:
            for _ in range(packed_streams):
                _, pos = _seven_number(data, pos)
        folders.append({'coders': coders, 'num_in': total_in,
                        'num_out': total_out, 'unpack': 0})
    while True:
        prop = data[pos]
        pos += 1
        if prop == 0x00:
            break
        if prop == 0x0C:
            for folder in folders:
                sizes_out = []
                for _ in range(folder['num_out']):
                    value, pos = _seven_number(data, pos)
                    sizes_out.append(value)
                folder['unpack'] = sizes_out[-1] if sizes_out else 0
        elif prop == 0x0A:
            pos = _seven_digests_length(data, pos, len(folders))
        else:
            raise Unsupported('unsupported 7z unpack property 0x%02x' % prop)
    return folders, pos


def _seven_substreams(data, pos, folders):
    counts = [1] * len(folders)
    while True:
        prop = data[pos]
        pos += 1
        if prop == 0x00:
            break
        if prop == 0x0D:
            for index in range(len(folders)):
                counts[index], pos = _seven_number(data, pos)
        elif prop == 0x09:
            for folder, count in zip(folders, counts):
                sizes = []
                for _ in range(count - 1):
                    value, pos = _seven_number(data, pos)
                    sizes.append(value)
                sizes.append(folder.get('unpack', 0) - sum(sizes))
                folder['stream_sizes'] = sizes
        elif prop == 0x0A:
            pos = _seven_digests_length(data, pos, sum(counts))
        else:
            raise Unsupported('unsupported 7z substream property')
    for folder, count in zip(folders, counts):
        folder['num_streams'] = count
    return pos


def seven_streams(data, pos):
    """Pack, folder and substream tables of one 7z StreamsInfo block."""
    result = {'pack_pos': 0, 'sizes': [], 'folders': []}
    while True:
        prop = data[pos]
        pos += 1
        if prop == 0x00:
            break
        if prop == 0x06:
            pack, pos = _seven_pack_info(data, pos)
            result['pack_pos'] = pack['pack_pos']
            result['sizes'] = pack['sizes']
        elif prop == 0x07:
            result['folders'], pos = _seven_unpack_info(data, pos)
        elif prop == 0x08:
            pos = _seven_substreams(data, pos, result['folders'])
        else:
            raise Unsupported('unsupported 7z stream property')
    for folder in result['folders']:
        folder.setdefault('num_streams', 1)
    return result, pos


def _seven_lzma(packed, filters, size):
    """7z streams have no end marker: stop at the announced size."""
    engine = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=filters)
    out = engine.decompress(packed, max_length=size)
    while len(out) < size and not engine.eof:
        more = engine.decompress(b'', max_length=size - len(out))
        if not more:
            break
        out += more
    return out


def seven_decode_pack(packed, folder):
    """Decode the packed 7z header with the standard library only."""
    if len(folder.get('coders') or []) != 1:
        raise Unsupported('this 7z header uses a filter chain')
    coder = folder['coders'][0]
    method = coder['method']
    props = coder['props'] or b''
    size = folder['unpack']
    if method == b'\x00':
        return packed[:size]
    if method == b'\x03\x01\x01' and len(props) >= 5:
        value = props[0]
        filters = [{'id': lzma.FILTER_LZMA1,
                    'dict_size': struct.unpack('<I', props[1:5])[0],
                    'lc': value % 9, 'lp': (value // 9) % 5, 'pb': value // 45}]
        return _seven_lzma(packed, filters, size)
    if method == b'\x21' and len(props) == 1:
        value = props[0]
        dict_size = (0xFFFFFFFF if value >= 40
                     else (2 | (value & 1)) << (value // 2 + 11))
        filters = [{'id': lzma.FILTER_LZMA2, 'dict_size': dict_size}]
        return _seven_lzma(packed, filters, size)
    raise Unsupported('unsupported 7z header compression')


def seven_read_header(next_bytes, read_pack):
    """The real 7z header from the next-header block at the archive end."""
    kind = next_bytes[:1]
    if kind == b'\x01':
        return next_bytes
    if kind != b'\x17':
        raise Unsupported('unknown 7z header type')
    streams, _ = seven_streams(next_bytes, 1)
    folders = streams.get('folders') or []
    sizes = streams.get('sizes') or []
    if len(folders) != 1 or len(sizes) != 1 or folders[0].get('num_in') != 1:
        raise Unsupported('this 7z header uses an unsupported layout')
    packed = read_pack(streams.get('pack_pos', 0), sizes[0])
    header = seven_decode_pack(packed, folders[0])
    if header[:1] != b'\x01':
        raise Unsupported('the 7z header did not decode')
    return header


def seven_header_streams(header):
    """The main StreamsInfo of a plain 7z header."""
    pos = 0
    if header[:1] != b'\x01':
        raise Unsupported('not a 7z header')
    pos += 1
    while True:
        prop = header[pos]
        pos += 1
        if prop == 0x00:
            break
        if prop == 0x02:
            while True:
                inner = header[pos]
                pos += 1
                if inner == 0x00:
                    break
                size, pos = _seven_number(header, pos)
                pos += size
        elif prop == 0x03:
            _, pos = seven_streams(header, pos)
        elif prop == 0x04:
            return seven_streams(header, pos)[0]
        elif prop == 0x05:
            break
        else:
            raise Unsupported('unsupported 7z header property')
    raise Unsupported('this 7z archive has no file streams')


def seven_stored_streams(streams):
    """Every stored (Copy) file stream, in header order: offset, length, packed."""
    sizes = streams.get('sizes') or []
    folders = streams.get('folders') or []
    pack = 0
    consumed = 0
    items = []
    for folder in folders:
        used = folder.get('num_in') or 0
        packed = sum(sizes[pack:pack + used])
        coders = folder.get('coders') or []
        single = (len(coders) == 1 and coders[0]['num_in'] == 1
                  and coders[0]['num_out'] == 1)
        stored = (single and coders[0]['method'] == b'\x00'
                  and packed == folder.get('unpack'))
        if stored:
            sizes_in = folder.get('stream_sizes')
            if sizes_in is None and folder.get('num_streams', 1) == 1:
                sizes_in = [folder.get('unpack', 0)]
            position = streams.get('pack_pos', 0) + consumed
            for size_in in sizes_in or []:
                items.append({'offset': position, 'length': size_in, 'packed': packed})
                position += size_in
        pack += used
        consumed += packed
    return items


def seven_stored_stream(streams):
    """The biggest stored (Copy) video file: offset after the start header, length."""
    best = None
    for item in seven_stored_streams(streams):
        if item['length'] >= MIN_INNER_VIDEO_BYTES and (
                best is None or item['length'] > best['length']):
            best = item
    return best


def _seven_bit_vector(data, pos, count):
    """7z bit vector: the most significant bit first, 1 bits first."""
    flags = []
    value = 0
    mask = 0
    for _index in range(count):
        if mask == 0:
            value = data[pos]
            pos += 1
            mask = 0x80
        flags.append(bool(value & mask))
        mask >>= 1
    return flags, pos


def _seven_names(block):
    """The Name property: UTF-16LE names separated by a zero."""
    if not block or block[0] != 0x00:
        return []          # external names live in a sidecar we do not have
    try:
        text = block[1:].decode('utf-16-le', 'replace')
    except Exception:
        return []
    return [part for part in text.split('\x00') if part]


def seven_file_names(header):
    """Names of the files that carry data, in header order (directories skipped)."""
    if header[:1] != b'\x01':
        raise Unsupported('not a 7z header')
    pos = 1
    names = []
    empty = []
    while True:
        prop = header[pos]
        pos += 1
        if prop == 0x00:
            break
        if prop == 0x02:
            while True:
                inner = header[pos]
                pos += 1
                if inner == 0x00:
                    break
                size, pos = _seven_number(header, pos)
                pos += size
        elif prop in (0x03, 0x04):
            _, pos = seven_streams(header, pos)
        elif prop == 0x05:
            count, pos = _seven_number(header, pos)
            while True:
                inner = header[pos]
                pos += 1
                if inner == 0x00:
                    break
                size, pos = _seven_number(header, pos)
                end = pos + size
                if inner == 0x0E:
                    empty, _ = _seven_bit_vector(header, pos, count)
                elif inner == 0x11:
                    names = _seven_names(header[pos:end])
                pos = end
        else:
            break
    if not names:
        return []
    if not empty:
        return names
    return [name for index, name in enumerate(names)
            if index >= len(empty) or not empty[index]]


def seven_pick_stream(streams, names, season=None, episode=None,
                      alt_season=None, alt_episode=None):
    """(stream, name, ambiguous) for the wanted episode inside a stored 7z.

    Inner names decide when the archive carries them; obfuscated archives that
    hold several episodes are refused instead of playing the wrong one.
    """
    items = seven_stored_streams(streams)
    videos = [item for item in items if item['length'] >= MIN_INNER_VIDEO_BYTES]
    if not videos:
        return None, '', False
    pairs = list(zip(names, items)) if names and len(names) == len(items) else []
    wanted = set()
    for season_value, episode_value in ((season, episode), (alt_season, alt_episode)):
        try:
            if season_value is not None and episode_value is not None:
                wanted.add((int(season_value), int(episode_value)))
        except (TypeError, ValueError):
            continue
    if wanted:
        matches = []
        for name, item in pairs:
            if item['length'] < MIN_INNER_VIDEO_BYTES:
                continue
            if not (name or '').lower().endswith(VIDEO_EXT):
                continue
            if wanted & episode_pairs(name):
                matches.append((name, item))
        if matches:
            name, item = max(matches, key=lambda pair: pair[1]['length'])
            return item, name, False
        if len(videos) > 1:
            return None, '', True
        return videos[0], '', False
    best = max(videos, key=lambda item: item['length'])
    name = ''
    for pair_name, item in pairs:
        if item is best:
            name = pair_name
            break
    return best, name, False
