# -*- coding: utf-8 -*-
"""The audio and subtitle tracks that are really in a Matroska (MKV) file: read from the first megabytes of the
release, before you play it. Only the track list (Tracks) is read: no picture, no sound.

Matroska is EBML: every element is an id (1-4 bytes) and a size (1-8 bytes), both with a length marker in the first
byte. The Segment holds Tracks; every TrackEntry has a TrackType (2 = audio, 17 = subtitles) and a Language (three
letters, 'eng' when it is missing) or LanguageBCP47.

Adapted from Lucent Video's nzb/tracks.py (MIT), used with permission.
"""
SEGMENT, TRACKS, ENTRY = 0x18538067, 0x1654AE6B, 0xAE
TYPE, LANGUAGE, BCP47, CLUSTER = 0x83, 0x22B59C, 0x22B59D, 0x1F43B675
NUMBER, CODEC, PRIVATE = 0xD7, 0x86, 0x63A2
ADD_MAPPING, ADD_TYPE, ADD_DATA = 0x41E4, 0x41E7, 0x41ED
SIMPLE_BLOCK, BLOCK_GROUP, BLOCK = 0xA3, 0xA0, 0xA1
DOVI_CONFIG = (0x64766343, 0x64767643)  # 'dvcC', 'dvvC': the Dolby Vision configuration record
UNKNOWN = -1
# Dolby Vision profile 7 (UHD Blu-ray) has an enhancement layer (EL) next to the picture: FEL carries real picture
# data, MEL is almost empty. Measured over the first frames: the EL's share of the video bytes.
MEL_BELOW, FEL_ABOVE, FRAMES_NEEDED = 0.01, 0.03, 4

THREE = {"dut": "nl", "nld": "nl", "eng": "en", "ger": "de", "deu": "de", "fre": "fr", "fra": "fr", "spa": "es", "ita": "it",
         "por": "pt", "rum": "ro", "ron": "ro", "pol": "pl", "swe": "sv", "dan": "da", "nor": "no", "nob": "no", "nno": "no",
         "fin": "fi", "hun": "hu", "cze": "cs", "ces": "cs", "tur": "tr", "rus": "ru", "jpn": "ja", "kor": "ko", "chi": "zh",
         "zho": "zh", "ukr": "uk", "gre": "el", "ell": "el", "heb": "he", "ara": "ar", "hin": "hi", "tha": "th", "vie": "vi"}


def _vint(data, at, keep_marker):
    first = data[at]
    length = 1
    while length <= 8 and not first & (0x80 >> (length - 1)):
        length += 1
    if length > 8 or at + length > len(data):
        raise ValueError("bad vint")
    value = first if keep_marker else first & (0xFF >> length)
    for byte in data[at + 1:at + length]:
        value = (value << 8) | byte
    if not keep_marker and value == (1 << (7 * length)) - 1:
        value = UNKNOWN                         # 'unknown size' (live-style files): runs to the end of its parent
    return value, at + length


def _children(data, start, end):
    at = start
    while at < end:
        ident, at = _vint(data, at, True)
        size, at = _vint(data, at, False)
        stop = end if size == UNKNOWN else at + size
        yield ident, at, min(stop, end), stop
        at = stop


def _code(entry_lang, bcp47):
    if bcp47:
        return bcp47.split("-")[0].lower()[:2]
    lang = (entry_lang or "eng").lower()
    return THREE.get(lang, lang[:2])


def _video(fields, data):
    """(track number, NAL length size, Dolby Vision profile or 0) of an HEVC video TrackEntry."""
    number, nal_size, profile = 0, 4, 0
    for field, fstart, fend, _fstop in fields:
        raw = data[fstart:fend]
        if field == NUMBER:
            number = int.from_bytes(raw, "big")
        elif field == PRIVATE and len(raw) > 21:
            nal_size = (raw[21] & 3) + 1          # hvcC: lengthSizeMinusOne
        elif field == ADD_MAPPING:
            kind, extra = 0, b""
            for inner, istart, iend, _istop in _children(data, fstart, fend):
                if inner == ADD_TYPE:
                    kind = int.from_bytes(data[istart:iend], "big")
                elif inner == ADD_DATA:
                    extra = data[istart:iend]
            if kind in DOVI_CONFIG and len(extra) >= 4:
                profile = extra[2] >> 1
    return number, nal_size, profile


class _Bits:
    """Reads bits, Exp-Golomb numbers and signed Exp-Golomb numbers from a byte string (MSB first)."""

    def __init__(self, data):
        self.data, self.at = data, 0

    def bits(self, count):
        value = 0
        for _ in range(count):
            byte = self.data[self.at >> 3]
            value = (value << 1) | ((byte >> (7 - (self.at & 7))) & 1)
            self.at += 1
        return value

    def ue(self):
        zeros = 0
        while not self.bits(1):
            zeros += 1
            if zeros > 31:
                raise ValueError("bad Exp-Golomb number")
        return (1 << zeros) - 1 + self.bits(zeros)

    def se(self):
        value = self.ue()
        return (value + 1) // 2 if value & 1 else -(value // 2)


def _unescape(payload):
    """Removes the start code emulation prevention bytes (00 00 03 -> 00 00)."""
    out, zeros = bytearray(), 0
    for byte in payload:
        if zeros >= 2 and byte == 3:
            zeros = 0
            continue
        out.append(byte)
        zeros = zeros + 1 if byte == 0 else 0
    return bytes(out)


def rpu_layer(nal):
    """'fel', 'mel' or '' from one Dolby Vision RPU (HEVC NAL type 62), the way the Dolby specification, dovi_tool and
    CoreELEC tell them apart: MEL when the non-linear quantization (NLQ) of all three components is a no-op (offset 0,
    vdr_in_max 1, dead zone 0), FEL otherwise. '' for an RPU that refers to an earlier one or is not profile 7."""
    data = nal
    if data[:2] == b"\x7c\x01":
        data = data[2:]
    data = _unescape(data)
    if not data or data[0] != 25:                   # rpu_nal_prefix
        return ""
    r = _Bits(data[1:])
    if r.bits(6) != 2:                              # rpu_type
        return ""
    rpu_format = r.bits(11)
    r.bits(4)                                       # vdr_rpu_profile
    r.bits(4)                                       # vdr_rpu_level
    if not r.bits(1):                               # vdr_seq_info_present_flag
        return ""
    r.bits(1)                                       # chroma_resampling_explicit_filter_flag
    data_type = r.bits(2)                           # coefficient_data_type
    denom = r.ue() if data_type == 0 else 32        # coefficient_log2_denom
    r.bits(2)                                       # vdr_rpu_normalized_idc
    r.bits(1)                                       # bl_video_full_range_flag
    if rpu_format & 0x700:
        return ""
    bl_depth = r.ue() + 8
    el_depth = (r.ue() & 0xFF) + 8
    r.ue()                                          # vdr_bit_depth_minus8
    r.bits(1)                                       # spatial_resampling_filter_flag
    r.bits(3)                                       # reserved_zero_3bits
    r.bits(1)                                       # el_spatial_resampling_filter_flag
    no_residual = r.bits(1)                         # disable_residual_flag
    r.bits(1)                                       # vdr_dm_metadata_present_flag
    if r.bits(1):                                   # use_prev_vdr_rpu_flag: the mapping is in an earlier RPU
        return ""
    if no_residual:
        return ""                                   # no enhancement layer residual at all: not profile 7 FEL/MEL
    r.ue()                                          # vdr_rpu_id
    r.ue()                                          # mapping_color_space
    r.ue()                                          # mapping_chroma_format_idc
    pieces = []
    for _cmp in range(3):
        pivots = r.ue() + 2
        if pivots > 9:
            return ""
        for _ in range(pivots):
            r.bits(bl_depth)
        pieces.append(pivots - 1)
    nlq_method = r.bits(3)
    if nlq_method != 0:
        return ""
    r.bits(bl_depth)
    r.bits(bl_depth)                                # nlq_pred_pivot_value (2)
    r.ue()                                          # num_x_partitions_minus1
    r.ue()                                          # num_y_partitions_minus1
    for count in pieces:
        for _ in range(count):
            method = r.ue()
            if method == 0:                         # polynomial
                order = r.ue()
                if order > 1:
                    return ""
                if order == 0 and r.bits(1):        # linear_interp_flag: not seen in practice
                    return ""
                for _j in range(order + 2):
                    if data_type == 0:
                        r.se()
                    r.bits(denom)
            elif method == 1:                       # MMR
                order = r.bits(2)
                if order > 2:
                    return ""
                if data_type == 0:
                    r.se()
                r.bits(denom)
                for _j in range((order + 1) * 7):
                    if data_type == 0:
                        r.se()
                    r.bits(denom)
            else:
                return ""
    mel = True
    for _cmp in range(3):
        offset = r.bits(el_depth)
        in_max_int = r.ue() if data_type == 0 else 1
        in_max = r.bits(denom)
        slope_int = r.ue() if data_type == 0 else 0
        slope = r.bits(denom)
        threshold_int = r.ue() if data_type == 0 else 0
        threshold = r.bits(denom)
        if offset or in_max_int != 1 or in_max or slope_int or slope or threshold_int or threshold:
            mel = False
    return "mel" if mel else "fel"


def _frames(data, start, end, number, nal_size, share):
    """Adds the bytes of the enhancement layer (NAL type 63) and of the rest of the video, frame by frame."""
    for ident, bstart, bend, bstop in _children(data, start, end):
        if bstop > len(data):
            return
        if ident == BLOCK_GROUP:
            _frames(data, bstart, bend, number, nal_size, share)
            continue
        if ident not in (SIMPLE_BLOCK, BLOCK):
            continue
        track, at = _vint(data, bstart, False)
        if track != number or data[at + 2] & 0x06:
            continue                                # another track, or laced (never for video)
        at += 3
        while at + nal_size < bend:
            length = int.from_bytes(data[at:at + nal_size], "big")
            at += nal_size
            if length <= 0 or at + length > bend:
                break
            kind = (data[at] >> 1) & 0x3F
            key = "el" if kind == 63 else "bl"
            share[key] += length
            if kind == 62 and len(share.setdefault("rpu", [])) < 8:
                share["rpu"].append(bytes(data[at:at + length]))     # the Dolby Vision metadata of this frame
            at += length
        share["frames"] += 1


def dolby(data, number, nal_size, start):
    """'fel', 'mel' or '' (not sure) for a profile 7 file, from the clusters that are in these bytes."""
    share = {"el": 0, "bl": 0, "frames": 0}
    try:
        for ident, cstart, cend, cstop in _children(data, start, len(data)):
            if ident == CLUSTER:
                _frames(data, cstart, min(cend, len(data)), number, nal_size, share)
            if cstop > len(data) or share["frames"] >= 24:
                break
    except (ValueError, IndexError):
        pass
    # what the Dolby Vision metadata itself says, as CoreELEC reads it (rc1.36: the size of the enhancement layer called
    # a MEL release 'FEL': The Last of Us S02E01 MULTi VFi REMUX, CoreELEC played it as 'minimum enhancement layer')
    said = set()
    for nal in share.get("rpu") or []:
        try:
            said.add(rpu_layer(nal))
        except (ValueError, IndexError):
            continue
    said.discard("")
    if said:
        return "fel" if "fel" in said else "mel"
    total = share["el"] + share["bl"]
    if share["frames"] < FRAMES_NEEDED or not total:
        return ""
    part = share["el"] / total
    return "mel" if part < MEL_BELOW else ("fel" if part > FEL_ABOVE else "")


INFO, SCALE, DURATION, CHAPTERS, EDITION, ATOM = 0x1549A966, 0x2AD7B1, 0x4489, 0x1043A770, 0x45B9, 0xB6
NAME, FORCED, AUDIO, CHANNELS, VIDEO = 0x536E, 0x55AA, 0xE1, 0x9F, 0xE0
WIDTH, HEIGHT, COLOUR, BITS, TRANSFER = 0xB0, 0xBA, 0x55B0, 0x55B2, 0x55BA
# Matroska codec ids of sound, as the source labels name them (DTS is one id for DTS, DTS-HD and DTS:X)
AUDIO_CODECS = {"A_TRUEHD": "TRUEHD", "A_EAC3": "DD+", "A_AC3": "DD", "A_DTS": "DTS", "A_AAC": "AAC", "A_FLAC": "FLAC",
                "A_OPUS": "OPUS", "A_PCM": "PCM", "A_MPEG/L3": "MP3"}


def _uint(raw):
    return int.from_bytes(raw, "big")


def _float(raw):
    import struct
    if len(raw) == 4:
        return struct.unpack(">f", raw)[0]
    if len(raw) == 8:
        return struct.unpack(">d", raw)[0]
    return 0.0


def _text(raw):
    return raw.decode("utf-8", "replace").strip("\x00 ")


def _audio_kind(codec, name):
    kind = next((v for k, v in AUDIO_CODECS.items() if codec.startswith(k)), "")
    low = name.lower()
    if kind == "DTS":
        if "dts:x" in low or "dts-x" in low or "dtsx" in low:
            kind = "DTS-X"
        elif "ma" in low.replace("-", " ").split() or "master audio" in low or "dts-hd ma" in low:
            kind = "DTS-HDMA"
    return kind


def read(data):
    """What the start of an MKV file says, or None when the track list is not in these bytes (or it is not Matroska):
    {'audio': ['nl', 'en'], 'subs': [...] (full subtitles), 'forced': [...] (only forced ones), 'sound': [[lang, kind,
    channels, atmos], ...] (commentary left out), 'seconds', 'width', 'height', 'bits', 'transfer' (16 PQ / 18 HLG / 1 SDR,
    0 not said), 'chapters', 'dv': profile, 'video': (number, NAL size), 'after': where the clusters start}."""
    if data[:4] != b"\x1a\x45\xdf\xa3":
        return None
    try:
        for ident, start, end, stop in _children(data, 0, len(data)):
            if ident != SEGMENT:
                continue
            out, scale, duration, chapters = None, 1000000, 0.0, 0
            for inner, istart, iend, istop in _children(data, start, end):
                if inner == CLUSTER:
                    break                       # the picture starts: what is not there yet does not come
                if istop > len(data):
                    break                       # longer than what was read
                if inner == INFO:
                    for field, fstart, fend, _fstop in _children(data, istart, iend):
                        if field == SCALE:
                            scale = _uint(data[fstart:fend]) or scale
                        elif field == DURATION:
                            duration = _float(data[fstart:fend])
                elif inner == CHAPTERS:
                    for edition, estart, eend, _e in _children(data, istart, iend):
                        if edition == EDITION:
                            chapters = max(chapters, sum(1 for a, *_r in _children(data, estart, eend) if a == ATOM))
                elif inner == TRACKS and out is None:
                    out = _tracks(data, istart, iend, istop)
            if out is None:
                return None
            out["seconds"] = int(duration * scale / 1e9) if duration else 0
            out["chapters"] = chapters
            out["segment"] = (start, end)
            return out
    except (ValueError, IndexError):
        return None
    return None


def _tracks(data, istart, iend, istop):
    out = {"audio": [], "subs": [], "forced": [], "sound": [], "dv": 0, "video": None, "after": istop,
           "width": 0, "height": 0, "bits": 0, "transfer": 0}
    for entry, estart, eend, _estop in _children(data, istart, iend):
        if entry != ENTRY:
            continue
        kind, lang, bcp, codec, name, forced, channels = 0, None, None, "", "", False, 0
        fields = list(_children(data, estart, eend))
        for field, fstart, fend, _fstop in fields:
            raw = data[fstart:fend]
            if field == TYPE:
                kind = _uint(raw)
            elif field == LANGUAGE:
                lang = raw.decode("ascii", "replace").strip("\x00 ")
            elif field == BCP47:
                bcp = raw.decode("ascii", "replace").strip("\x00 ")
            elif field == CODEC:
                codec = raw.decode("ascii", "replace").strip("\x00 ")
            elif field == NAME:
                name = _text(raw)
            elif field == FORCED:
                forced = bool(_uint(raw))
            elif field == AUDIO:
                for a, astart, aend, _a in _children(data, fstart, fend):
                    if a == CHANNELS:
                        channels = _uint(data[astart:aend])
            elif field == VIDEO and kind in (0, 1) and not out["height"]:
                for v, vstart, vend, _v in _children(data, fstart, fend):
                    if v == WIDTH:
                        out["width"] = _uint(data[vstart:vend])
                    elif v == HEIGHT:
                        out["height"] = _uint(data[vstart:vend])
                    elif v == COLOUR:
                        for c, cstart, cend, _c in _children(data, vstart, vend):
                            if c == BITS:
                                out["bits"] = _uint(data[cstart:cend])
                            elif c == TRANSFER:
                                out["transfer"] = _uint(data[cstart:cend])
        if kind == 1 and out["video"] is None:
            number, nal_size, profile = _video(fields, data)
            out["video"], out["dv"] = (number, nal_size), profile
        if kind not in (2, 17):
            continue
        code = _code(lang, bcp)
        if not code or code == "un":
            continue
        low = name.lower()
        if kind == 2:
            if code not in out["audio"]:
                out["audio"].append(code)
            if "comment" not in low and "descri" not in low:      # commentary and audio description do not count
                out["sound"].append([code, _audio_kind(codec, name), channels, "atmos" in low])
        else:
            forced = forced or "forced" in low or "geforceerd" in low
            bucket = out["forced" if forced else "subs"]
            if code not in bucket:
                bucket.append(code)
    out["forced"] = [c for c in out["forced"] if c not in out["subs"]]
    return out
