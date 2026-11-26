"""The feature inside a full-disc image.

A DVD or Blu-ray ISO is not a video file: the film sits in VIDEO_TS/VTS_01_x.VOB
or BDMV/STREAM/*.m2ts. The image's own filesystem is read here, so the engine
can serve just the feature's bytes instead of the whole image.
"""

import re
import struct

SECTOR = 2048
MAX_ENTRIES = 4000
CLIP_EXT = ('.m2ts', '.vob', '.mpg', '.mpeg', '.ts')


def _u16(data, at):
    return struct.unpack_from('<H', data, at)[0]


def _u32(data, at):
    return struct.unpack_from('<I', data, at)[0]


def _u64(data, at):
    return struct.unpack_from('<Q', data, at)[0]


# -- ISO9660 (DVD-video, and the bridge every disc carries) --------------------

def _iso_names(read, lba, size):
    """(name, extent lba, bytes, is_dir) for the entries of one directory."""
    data = read(lba * SECTOR, min(max(size, SECTOR), 4 * 1024 * 1024))
    out = []
    position = 0
    while position + 34 <= len(data) and len(out) < MAX_ENTRIES:
        length = data[position]
        if length == 0:
            position = (position // SECTOR + 1) * SECTOR
            continue
        if position + length > len(data):
            break
        record = data[position:position + length]
        extent = _u32(record, 2)
        count = _u32(record, 10)
        flags = record[25]
        name_size = record[32]
        name = record[33:33 + name_size]
        position += length
        if name[:1] in (b'\x00', b'\x01') or not name:
            continue
        text = name.decode('latin-1').split(';')[0]
        out.append((text, extent, count, bool(flags & 2)))
    return out


def _iso_dir(read, root_lba, root_size, wanted):
    for name, extent, count, is_dir in _iso_names(read, root_lba, root_size):
        if is_dir and name.strip().lower() in wanted:
            return name.strip(), extent, count
    return None


# -- UDF (Blu-ray, and most modern images) -------------------------------------

class _Space(object):
    """One UDF partition seen as a flat stream: the image, or a metadata file."""

    def __init__(self, read, extents):
        self.read = read
        self.extents = [(offset, length) for offset, length in extents if length > 0]
        self.total = sum(length for _offset, length in self.extents)

    def at(self, offset, count):
        out = []
        left = count
        walked = 0
        for image_offset, length in self.extents:
            if left <= 0 or offset >= walked + length:
                walked += length
                continue
            inner = max(0, offset - walked)
            take = min(left, length - inner)
            if take <= 0:
                break
            out.append(self.read(image_offset + inner, take))
            offset += take
            left -= take
            walked += length
        return b''.join(out)


def _udf_layout(read, size):
    """The main volume descriptor sequence, from the anchor."""
    sectors = [256, 512]
    if size > SECTOR * 512:
        sectors.append(size // SECTOR - 256)
    for sector in sectors:
        block = read(sector * SECTOR, SECTOR)
        if len(block) < 24 or block[0:2] != b'\x02\x00':
            continue
        length = _u32(block, 16)
        location = _u32(block, 20)
        if not length or not location:
            continue
        return read(location * SECTOR, min(max(length, SECTOR), 64 * SECTOR))
    return b''


def _udf_entry(spaces, ref, block, block_size=SECTOR):
    """The file entry at this block: extents, size, and whether it is a folder."""
    if ref >= len(spaces):
        return None
    data = spaces[ref].at(block * block_size, 8 * SECTOR)
    if len(data) < 208:
        return None
    tag = _u16(data, 0)
    if tag not in (261, 266):
        return None
    info = 56 if tag == 261 else 64
    ea = 168 if tag == 261 else 208
    ads = 176 if tag == 261 else 216
    total = _u64(data, info) if len(data) >= info + 8 else 0
    extra = _u32(data, ea) if len(data) >= ea + 4 else 0
    is_dir = data[27] == 4
    kind = _u16(data, 34) & 0x07
    position = ads + extra
    if kind == 3:
        return {'extents': [], 'size': total, 'dir': is_dir,
                'inline': data[position:position + total]}
    step = 8 if kind == 0 else 16
    extents = []
    while position + step <= len(data) and len(extents) < 64:
        length = _u32(data, position)
        lba = _u32(data, position + 4)
        item_ref = _u16(data, position + 8) if step == 16 else ref
        if length == 0 and lba == 0:
            break
        if (length >> 30) == 3:
            break
        length &= 0x3FFFFFFF
        if length and lba:
            extents.append((item_ref, lba * block_size, length))
        position += step
    return {'extents': extents, 'size': total, 'dir': is_dir, 'inline': None}


def _udf_mount(read, size):
    """(spaces, root reference, root block, block size) or None."""
    sequence = _udf_layout(read, size)
    if not sequence:
        return None
    starts = {}
    lvd = b''
    for at in range(0, len(sequence) - 15, SECTOR):
        block = sequence[at:at + SECTOR]
        if len(block) < 200:
            break
        tag = _u16(block, 0)
        if tag == 5:
            starts[_u16(block, 22)] = (_u32(block, 188), _u32(block, 192))
        elif tag == 6:
            lvd = block
    if not lvd:
        return None
    block_size = _u32(lvd, 212) or SECTOR
    maps_len = _u32(lvd, 264)
    limit = min(len(lvd), 440 + maps_len) if maps_len else len(lvd)
    spaces = []
    position = 440
    while position + 4 <= limit:
        kind = lvd[position]
        length = lvd[position + 1]
        if length < 2:
            break
        if kind == 1:
            start, count = starts.get(_u16(lvd, position + 4), (0, 0))
            spaces.append(_Space(read, [(start * block_size, count * block_size)]))
        elif kind == 2:
            number = _u16(lvd, position + 38)
            start, count = starts.get(number, (0, 0))
            physical = _Space(read, [(start * block_size, count * block_size)])
            meta = _udf_entry([physical], 0, _u32(lvd, position + 40), block_size)
            if not meta or not meta['extents']:
                return None
            spaces.append(_Space(read, [(offset, length) for _ref, offset, length
                                       in meta['extents']]))
        position += length
    if not spaces:
        return None
    fsd_ref = _u16(lvd, 256)
    if fsd_ref >= len(spaces):
        fsd_ref = 0
    fsd = spaces[fsd_ref].at(_u32(lvd, 252) * block_size, block_size)
    if len(fsd) < 420:
        return None
    root_ref = _u16(fsd, 408)
    if root_ref >= len(spaces):
        root_ref = fsd_ref
    return spaces, root_ref, _u32(fsd, 404), block_size


def _udf_name(raw):
    if len(raw) < 2:
        return ''
    compression = raw[0]
    body = raw[1:]
    try:
        text = body.decode('utf-16-be') if compression == 16 else body.decode('latin-1')
    except Exception:
        text = body.decode('latin-1', 'replace')
    return text.rstrip('\x00').strip()


def _udf_names(mount):
    """(name, reference, block) for the entries of one directory."""
    spaces, ref, block, block_size = mount
    entry = _udf_entry(spaces, ref, block, block_size)
    if not entry:
        return []
    data = entry['inline']
    if data is None:
        data = b''.join(spaces[item_ref].at(offset, length)
                        for item_ref, offset, length in entry['extents'][:16]
                        if item_ref < len(spaces))
    if not data:
        return []
    out = []
    position = 0
    while position + 38 <= len(data) and len(out) < MAX_ENTRIES:
        if _u16(data, position) != 257:
            break
        named = data[position + 19]
        inner = _u16(data, position + 36)
        size = 38 + inner + named
        if size < 38 or position + size > len(data):
            break
        step = (size + 3) & ~3
        child_ref = _u16(data, position + 28)
        child = _u32(data, position + 24)
        start = position + 38 + inner
        name = _udf_name(data[start:start + named]) if named else ''
        position += step
        if name:
            out.append((name, child_ref, child))
    return out


def _udf_dir(mount, wanted):
    for name, ref, block in _udf_names(mount):
        if name.strip().lower() not in wanted:
            continue
        entry = _udf_entry(mount[0], ref, block, mount[3])
        if entry and entry['dir']:
            return name.strip(), (mount[0], ref, block, mount[3])
    return None


# -- the feature ---------------------------------------------------------------

def _largest(files):
    best = None
    for name, extents in files:
        total = sum(length for _offset, length in extents)
        if total and (best is None or total > best[0]):
            best = (total, name, extents)
    if best is None:
        return None
    return {'name': best[1], 'extents': best[2]}


def _vob_feature(files):
    """The main VTS: its VOBs in order, one film split over several of them."""
    groups = {}
    for name, extents in files:
        match = re.search(r'vts_(\d{1,2})_(\d{1,2})\.vob$', name.lower().replace('\\', '/'))
        if not match:
            continue
        groups.setdefault(int(match.group(1)), []).append((int(match.group(2)), name, extents))
    best = None
    for number, parts in groups.items():
        parts.sort(key=lambda item: item[0])
        total = sum(length for _part, _name, extents in parts for _offset, length in extents)
        if not total:
            continue
        rank = (number == 1, total)
        if best is None or rank > best[0]:
            best = (rank, parts)
    if best is None:
        return None
    parts = best[1]
    extents = [extent for _part, _name, part_extents in parts for extent in part_extents]
    return {'name': re.sub(r'_\d+\.vob$', '', parts[0][1], flags=re.I) + '.vob',
            'extents': extents}


def _iso_disc(read, size):
    pvd = read(16 * SECTOR, SECTOR)
    if len(pvd) < 190 or pvd[1:6] != b'CD001':
        return None
    root_lba = _u32(pvd, 158)
    root_size = _u32(pvd, 166)
    bdmv = _iso_dir(read, root_lba, root_size, ('bdmv',))
    if bdmv:
        stream = _iso_dir(read, bdmv[1], bdmv[2], ('stream',))
        if stream:
            files = [(name, [(extent * SECTOR, count)])
                     for name, extent, count, is_dir in _iso_names(read, stream[1], stream[2])
                     if not is_dir and name.strip().lower().endswith('.m2ts') and count]
            found = _largest(files)
            if found:
                return found
    video_ts = _iso_dir(read, root_lba, root_size, ('video_ts',))
    if video_ts:
        files = [(name, [(extent * SECTOR, count)])
                 for name, extent, count, is_dir in _iso_names(read, video_ts[1], video_ts[2])
                 if not is_dir and name.strip().lower().endswith('.vob') and count]
        found = _vob_feature(files)
        if found:
            return found
    return None


def _udf_clips(mount, folder, suffix):
    found = []
    for name, ref, block in _udf_names(mount):
        if not name.lower().endswith(suffix):
            continue
        entry = _udf_entry(mount[0], ref, block, mount[3])
        if not entry or entry['dir'] or not entry['extents']:
            continue
        found.append((name, [(offset, length) for _ref, offset, length in entry['extents']]))
    return found


def _udf_disc(read, size):
    mount = _udf_mount(read, size)
    if not mount:
        return None
    bdmv = _udf_dir(mount, ('bdmv',))
    if bdmv:
        stream = _udf_dir(bdmv[1], ('stream',))
        if stream:
            found = _largest(_udf_clips(stream[1], 'stream', '.m2ts'))
            if found:
                return found
    video_ts = _udf_dir(mount, ('video_ts',))
    if video_ts:
        found = _vob_feature(_udf_clips(video_ts[1], 'video_ts', '.vob'))
        if found:
            return found
    return None


def feature(read, size):
    """{'name', 'extents'} for the film on this disc image, or None.

    read(offset, bytes) returns image bytes, so the image may live inside a RAR
    set as well as in one posted file.
    """
    for parser in (_iso_disc, _udf_disc):
        try:
            found = parser(read, size)
        except Exception:
            found = None
        if found and found.get('extents'):
            return found
    return None


def entries(read, size):
    """Every name found at the disc's top level, for diagnostics."""
    try:
        pvd = read(16 * SECTOR, SECTOR)
        if len(pvd) >= 190 and pvd[1:6] == b'CD001':
            return [name for name, _e, _c, _d in
                    _iso_names(read, _u32(pvd, 158), _u32(pvd, 166))]
    except Exception:
        pass
    try:
        mount = _udf_mount(read, size)
        if mount:
            return [name for name, _ref, _block in _udf_names(mount)]
    except Exception:
        pass
    return []
