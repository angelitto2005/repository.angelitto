"""Probe one article from a tmdbm plan.

Usage: probe_tail.py <plan> <index> [<index> ...]

Reads the plan, connects to the first working provider, fetches the given
article indexes (0-based) and prints yEnc/CRC and MKV header details.
Credentials are never printed.
"""

import base64
import re
import socket
import ssl
import sys
import zlib

CRLF = b'\r\n'


def read_line(sock, buf):
    while CRLF not in buf:
        chunk = sock.recv(65536)
        if not chunk:
            raise IOError('connection closed')
        buf += chunk
    line, _, buf = buf.partition(CRLF)
    return line, buf


def read_multiline(sock, buf):
    lines = []
    while True:
        line, buf = read_line(sock, buf)
        if line == b'.':
            return lines, buf
        if line.startswith(b'..'):
            line = line[1:]
        lines.append(line)


def decode_b64(value):
    if not value or value == '====':
        return ''
    value += '=' * (-len(value) % 4)
    return base64.b64decode(value).decode('utf-8')


def parse_plan(path):
    servers = []
    articles = []
    length = 0
    with open(path, 'r', encoding='utf-8') as handle:
        for raw in handle:
            raw = raw.rstrip('\n')
            if raw.startswith('server '):
                fields = raw.split(' ')
                servers.append({
                    'host': fields[1],
                    'port': int(fields[2]),
                    'ssl': fields[3] == '1',
                    'backup': fields[5] == '1',
                    'user': decode_b64(fields[6]),
                    'password': decode_b64(fields[7]),
                })
            elif raw.startswith('a '):
                articles.append(raw.split(' ', 2)[2])
            elif raw.startswith('length '):
                length = int(raw.split(' ', 1)[1])
    return servers, articles, length


class Conn(object):
    def __init__(self, server):
        raw = socket.create_connection((server['host'], server['port']), 20)
        if server['ssl']:
            context = ssl.create_default_context()
            raw = context.wrap_socket(raw, server_hostname=server['host'])
        self.sock = raw
        self.buf = b''
        greeting, self.buf = read_line(self.sock, self.buf)
        if not greeting.startswith(b'200') and not greeting.startswith(b'201'):
            raise IOError('greeting: %r' % greeting[:80])
        self.command('AUTHINFO USER %s' % server['user'], b'381', (b'281',))
        self.command('AUTHINFO PASS %s' % server['password'], b'281')

    def command(self, text, first, also=()):
        self.sock.sendall(text.encode('utf-8') + CRLF)
        line, self.buf = read_line(self.sock, self.buf)
        if not (line.startswith(first) or any(line.startswith(x) for x in also)):
            raise IOError('command %s failed: %r' % (text.split(' ')[0], line[:120]))
        return line

    def body(self, message_id):
        line = self.command('BODY <%s>' % message_id, b'222')
        lines, self.buf = read_multiline(self.sock, self.buf)
        return b'\r\n'.join(lines)

    def close(self):
        try:
            self.sock.sendall(b'QUIT\r\n')
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass


def yenc_decode(article):
    head = re.search(rb'=ybegin[^\r\n]*', article)
    if not head:
        raise ValueError('no =ybegin')
    head_text = head.group(0).decode('latin-1')
    size = int(re.search(r'size=(\d+)', head_text).group(1))
    begin = 1
    part = int(re.search(r'part=(\d+)', head_text).group(1)) if 'part=' in head_text else 1
    end = size
    part_head = re.search(rb'=ypart[^\r\n]*', article)
    if part_head:
        part_text = part_head.group(0).decode('latin-1')
        begin = int(re.search(r'begin=(\d+)', part_text).group(1))
        end = int(re.search(r'end=(\d+)', part_text).group(1))
    start = article.find(b'\r\n', part_head.end() if part_head else head.end()) + 2
    tail = article.find(b'=yend', start)
    data = bytearray()
    i = start
    while i < tail:
        ch = article[i]
        if ch == 13 or ch == 10:
            i += 1
            continue
        if ch == 61:
            if i + 1 >= tail:
                break
            data.append((article[i + 1] - 64 - 42) & 0xFF)
            i += 2
            continue
        data.append((ch - 42) & 0xFF)
        i += 1
    end_head = re.search(rb'=yend[^\r\n]*', article[tail:])
    end_text = end_head.group(0).decode('latin-1') if end_head else ''
    print('  trailer: %s' % end_text)
    declared = re.search(r'pcrc32=([0-9a-fA-F]+)', end_text)
    actual = zlib.crc32(bytes(data)) & 0xFFFFFFFF
    ok = declared is None or int(declared.group(1), 16) == actual
    return {
        'size': size, 'begin': begin, 'end': end, 'part': part,
        'decoded': len(data), 'data': bytes(data),
        'crc_declared': declared.group(1).lower() if declared else '',
        'crc_actual': '%08x' % actual, 'crc_ok': ok,
        'data_offset': begin - 1,
    }


def vint_length(first):
    mask = 0x80
    length = 1
    while length <= 8 and not (first & mask):
        mask >>= 1
        length += 1
    if length > 8:
        raise ValueError('bad vint')
    return length, mask


def read_id(data, pos):
    length, _ = vint_length(data[pos])
    return int.from_bytes(data[pos:pos + length], 'big'), length


def read_size(data, pos):
    length, mask = vint_length(data[pos])
    value = data[pos] & (mask - 1)
    for i in range(1, length):
        value = (value << 8) | data[pos + i]
    return value, length


def ebml_children(data, start, end):
    pos = start
    while pos < end:
        eid, n = read_id(data, pos)
        pos += n
        size, n = read_size(data, pos)
        pos += n
        unknown = size == (1 << (7 * n)) - 1
        yield eid, pos, size, unknown
        if unknown:
            return
        pos += size


def seek_entries(data, start, size):
    entries = {}
    for eid, pos, inner, unknown in ebml_children(data, start, start + size):
        if eid == 0x4DBB:
            seek_id = None
            seek_pos = None
            for cid, cpos, csize, _ in ebml_children(data, pos, pos + inner):
                if cid == 0x53AB:
                    seek_id = data[cpos:cpos + csize].hex()
                elif cid == 0x53AC:
                    seek_pos = int.from_bytes(data[cpos:cpos + csize], 'big')
            if seek_id is not None:
                entries[seek_id] = seek_pos
    return entries


def main():
    plan, indexes = sys.argv[1], [int(x) for x in sys.argv[2:]]
    servers, articles, length = parse_plan(plan)
    print('plan: %d articles, length %d, %d server(s)' % (len(articles), length, len(servers)))
    payload = {}
    for index in indexes:
        if index < 0:
            index += len(articles)
        message_id = articles[index]
        for server in servers:
            try:
                conn = Conn(server)
                raw = conn.body(message_id)
                conn.close()
                decoded = yenc_decode(raw)
                print('article %d: decoded %d bytes (begin %d end %d), crc declared %s actual %s %s [%s]'
                      % (index, decoded['decoded'], decoded['begin'], decoded['end'],
                         decoded['crc_declared'], decoded['crc_actual'],
                         'OK' if decoded['crc_ok'] else 'MISMATCH',
                         'backup' if server['backup'] else 'primary'))
                payload[index] = decoded['data']
                break
            except Exception as exc:
                print('article %d: provider failed: %s' % (index, exc))
        else:
            print('article %d: no provider could fetch it' % index)
    for index in sorted(payload):
        if index < 0:
            continue
        cues_at = payload[index].find(b'\x1c\x53\xbb\x6b')
        if cues_at >= 0:
            print('cues marker found in article %d at byte %d of the article'
                  % (index, cues_at))
    head = b''
    if 0 in payload:
        head = payload[0]
        if 1 in payload:
            head += payload[1]
    print('header starts with %s' % head[:16].hex())
    if head.startswith(b'\x1a\x45\xdf\xa3'):
        header_size, n = read_size(head, 4)
        pos = 4 + n + header_size
        seg_id, seg_n = read_id(head, pos)
        print('after ebml header: id 0x%X at %d' % (seg_id, pos))
        if seg_id == 0x18538067:
            seg_data = pos + seg_n
            seg_size, seg_n2 = read_size(head, seg_data)
            print('segment data at %d, size %d' % (seg_data + seg_n2, seg_size))
            entries = {}
            for eid, epos, esize, unknown in ebml_children(head, seg_data + seg_n2, len(head)):
                if unknown:
                    break
                if eid == 0x114D9B74:
                    print('seekhead at %d size %d' % (epos, esize))
                    entries.update(seek_entries(head, epos, esize))
                elif eid not in (0x1F43B675,):
                    print('top element 0x%X at %d size %d' % (eid, epos, esize))
            for hex_id, position in sorted(entries.items(), key=lambda item: item[1] or 0):
                print('seek entry 0x%s -> %s%s' % (hex_id, position,
                      ' (Cues)' if hex_id == '1c53bb6b' else ''))
            tail_start = length - 357479
            for hex_id, position in entries.items():
                if hex_id == '1c53bb6b':
                    print('cues at %s, damaged tail starts at %d, cues %s the damaged range'
                          % (position, tail_start,
                             'inside' if position >= tail_start else 'outside'))
    else:
        print('could not read the MKV header from the fetched articles')


if __name__ == '__main__':
    main()
