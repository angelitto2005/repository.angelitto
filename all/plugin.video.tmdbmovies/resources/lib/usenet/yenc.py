"""yEnc decoding.

An article carries a =ybegin header, optionally a =ypart header (which part of
the file this is), the encoded bytes and a =yend line with a CRC32. Decoding is
`byte - 42`, except after an escape '=' where the byte goes back by another 64.

Everything here is bytes operations (split / translate), because a 4 GB film is
a few thousand articles and a pure-Python loop per byte would cap playback.
"""

import re
import zlib

BEGIN = b'=ybegin'
PART = b'=ypart'
END = b'=yend'

_DECODE = bytes((value - 42) & 0xFF for value in range(256))
_ESCAPED = bytes((value - 106) & 0xFF for value in range(256))
_FIELD = re.compile(rb'([A-Za-z]+)=(\S+)')


class YencError(Exception):
    """The article is not yEnc (or is broken beyond use)."""


def _header(line):
    """'=ybegin part=1 total=5 line=128 size=1234 name=a.mkv' -> dict."""
    values = {}
    name = re.search(rb'\bname=(.*)$', line)
    if name:
        values['name'] = name.group(1).decode('utf-8', 'replace').strip()
        line = line[:name.start()]
    for key, value in _FIELD.findall(line):
        try:
            values[key.decode('ascii', 'ignore').lower()] = value.decode('ascii', 'ignore')
        except Exception:
            continue
    return values


def _unescape(data):
    """Drop yEnc escapes and undo the +42 in one pass."""
    if b'=' not in data:
        return data.translate(_DECODE)
    pieces = data.split(b'=')
    out = [pieces[0].translate(_DECODE)]
    for piece in pieces[1:]:
        if not piece:
            continue
        out.append(_ESCAPED[piece[0]:piece[0] + 1])
        out.append(piece[1:].translate(_DECODE))
    return b''.join(out)


def decode(article):
    """Decode one article.

    Returns {'data', 'begin' (0-based offset in the file), 'size' (file size),
    'name', 'part_end', 'crc_ok'}.
    """
    if not article:
        raise YencError('empty article')
    start = article.find(BEGIN)
    if start < 0:
        raise YencError('no =ybegin in this article')
    eol = article.find(b'\n', start)
    if eol < 0:
        raise YencError('truncated =ybegin')
    begin_values = _header(article[start:eol])
    position = eol + 1
    part_values = {}
    if article.startswith(PART, position):
        eol = article.find(b'\n', position)
        if eol < 0:
            raise YencError('truncated =ypart')
        part_values = _header(article[position:eol])
        position = eol + 1
    end_at = article.rfind(END)
    end_values = {}
    if end_at >= 0:
        end_values = _header(article[end_at:].split(b'\n', 1)[0])
        body = article[position:end_at]
    else:
        body = article[position:]
    body = body.replace(b'\r', b'').replace(b'\n', b'')
    data = _unescape(body)
    if not data:
        raise YencError('no payload')
    try:
        size = int(begin_values.get('size') or 0)
    except ValueError:
        size = 0
    if part_values:
        try:
            begin = int(part_values.get('begin', '1')) - 1
        except ValueError:
            begin = 0
        try:
            part_end = int(part_values.get('end', str(begin + len(data))))
        except ValueError:
            part_end = begin + len(data)
    else:
        begin, part_end = 0, len(data)
    crc_ok = True
    wanted = end_values.get('pcrc32') if part_values else (end_values.get('crc32') or '')
    if wanted:
        try:
            crc_ok = (zlib.crc32(data) & 0xFFFFFFFF) == int(wanted, 16)
        except ValueError:
            crc_ok = True
    return {'data': data, 'begin': begin, 'size': size or part_end, 'name': begin_values.get('name', ''),
            'part_end': part_end, 'crc_ok': crc_ok}
