# resources/lib/windows/results_window.py

import re
import os
import json
import time
import xbmc
import xbmcgui
import xbmcaddon

QUALITY_COLORS = {
    '4K':    'FFFF00FF',
    '1080p': 'FF7CFC00',
    '720p':  'FFFFD700',
    'SD':    'FFD3D3D3',
}

QUALITY_ICONS = {
    '4K':    'flag4k.png',
    '1080p': 'flag1080p.png',
    '720p':  'flag720p.png',
    'SD':    'flagsd.png',
}

QUALITY_PATTERNS = [
    (r'(?:2160[pi]|4K|UHD)',        '4K'),
    (r'(?:1080[pi]|FHD|FULL\s*HD)', '1080p'),
    (r'(?:720[pi])',                 '720p'),
]

CODEC_PATTERNS = [
    ('HEVC|[Xx]\.?265|[Hh]\.?265', 'HEVC'),
    ('[Xx]\.?264|[Hh]\.?264',       'x264'),
    ('AV1',                         'AV1'),
]

SOURCE_PATTERNS = [
    'Remux', 'BluRay', 'BDRip', 'BRRip',
    'WEB-DL', 'WEBRip', 'WEB',
    'HDTV', 'HDRip', 'DVDRip', 'DVDScr',
    'HDCAM', 'CAM', 'TeleSync', 'TS',
]

HDR_PATTERNS = [
    (r'HDR10\+',                  'HDR10+'),
    (r'HDR10',                    'HDR10'),
    (r'\bHDR\b',                  'HDR'),
    (r'\bSDR\b',                  'SDR'),
    (r'Dolby[.\s]?Vision|\.DV\.', 'DV'),
    (r'D/VISION',                 'DV'),
]

AUDIO_PATTERNS = [
    (r'(?i)Atmos',              'Atmos'),
    (r'(?i)TrueHD',             'TrueHD'),
    (r'(?i)DTS[\-\.]?HD(?:[\-\.]?MA)?',   'DTS-HD'),
    (r'(?i)\bDTS\b',            'DTS'),
    (r'(?i)DDP\s?5[\. ]?1|DD\+\s?5[\. ]?1|EAC3\s?5[\. ]?1', 'DDP 5.1'),
    (r'(?i)\bDDP\b|DD\+|EAC3',      'DDP'),
    (r'(?i)DD\s?5[\. ]?1|AC3\s?5[\. ]?1', 'DD 5.1'),
    (r'(?i)\bAC3\b|\bDD\b',            'AC3'),
    (r'(?i)AAC\s?5[\. ]?1', 'AAC 5.1'),
    (r'(?i)\bAAC\b',            'AAC'),
    (r'(?i)\bFLAC\b',           'FLAC'),
    (r'(?i)6CH|\b5[\. ]?1\b',   '5.1'),
    (r'(?i)2\.0|2CH',           '2.0'),
]

TRACKER_TAG_PATTERNS = [
    (r'\bFREE(?:LEECH)?\b',
     '[COLOR FF00FF00][B]FREE[/B][/COLOR]'),
    (r'\bDoubleUP\b|\bDouble\s*Upload\b|\b2x\s*(?:Upload|UP)\b|\bDU\b',
     '[COLOR FFFFD700][B]2xUP[/B][/COLOR]'),
    (r'\bInternal\b|\bINT\b',
     '[COLOR FF00BFFF][B]INT[/B][/COLOR]'),
    (r'\bVIP\b',
     '[COLOR FFEE82EE][B]VIP[/B][/COLOR]'),
    (r'\bPROMOVAT\b|\bRecomandat\b|\bRecommended\b',
     '[COLOR FFFFA500][B]PROMO[/B][/COLOR]'),
    (r'\bVerificat\b',
     '[COLOR FF90EE90]VERIF[/COLOR]'),
    (r'\bAur\b',
     '[COLOR FFFFD700][B]AUR[/B][/COLOR]'),
    (r'(?i)\bRO[\.\-\s]?Dub(?:bed|lat)?\b|\bDublat[\.\-\s]?(?:RO)?\b|\bRomanian[\.\-\s]?Dub(?:bed)?\b|\bRO[\.\-\s]?Audio\b|\bMulti[\.\-\s]?Audio\b.*\bRO\b',
     '[COLOR yellow][B]RO DUB[/B][/COLOR]'),
]

# Provideri JSON/Stremio
JSON_PROVIDERS = ['torrentio', 'meteor', 'comet', 'mediafusion', 'heartive', 'corncastle', 'aiostreams']

# Culori per addon AIO (pentru randul 2)
AIO_ADDON_COLORS = {
    'comet':          'FF00BFFF',
    'mediafusion':    'FFFF4500',
    'torrentio':      'FF7B68EE',
    'jackettio':      'FF32CD32',
    'orionoid':       'FFFFA500',
    'easynews':       'FF00CED1',
    'debridio':       'FFEE82EE',
    'annatar':        'FFFFD700',
    'zilean':         'FF20B2AA',
    'stremio-gdrive': 'FF87CEEB',
}

# Numele providerilor pt. display
PROVIDER_NAMES = {
    'torrentio': 'Torrentio', 'meteor': 'Meteor', 'comet': 'Comet',
    'mediafusion': 'MediaFusion', 'heartive': 'Heartive',
    'corncastle': 'CornCastle', 'aiostreams': 'AIO Streams',
    'filelist': 'FileList', 'speedapp': 'SpeedApp',
    'uindex': 'UIndex', 'yts': 'YTS'
}


class ResultsWindow(xbmcgui.WindowXMLDialog):

    def __init__(self, *args, **kwargs):
        self.results = kwargs.get('results', [])
        self.meta = kwargs.get('meta', {})
        self.selected = None

    def onInit(self):
        self._set_window_properties()
        self._populate_list()
        try:
            ctrl = self.getControl(2000)
            if ctrl:
                self.setFocusId(2000)
        except:
            pass

    def _format_size(self, size_raw):
        try:
            if 'GB' in str(size_raw) or 'MB' in str(size_raw): return str(size_raw)
            bytes_val = float(size_raw)
            for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                if bytes_val < 1024.0: return "%3.2f %s" % (bytes_val, unit)
                bytes_val /= 1024.0
            return "%.2f PB" % bytes_val
        except: return str(size_raw)

    def _set_window_properties(self):
        title = self._find_meta_value(
            'Title', 'title', 'tvshowtitle', 'originaltitle')
        self.setProperty('mrsp.title', title)

        poster = self._find_meta_value(
            'Poster', 'poster', 'thumb', 'Thumb',
            'icon', 'image', 'clearart')
        self.setProperty('mrsp.poster', poster)

        plot = self._find_meta_value(
            'Plot', 'plot', 'overview', 'Overview',
            'description', 'Description', 'synopsis')
        self.setProperty('mrsp.plot', plot)

        fanart = self._find_meta_value(
            'Fanart', 'fanart', 'banner', 'Banner') or poster
        self.setProperty('mrsp.fanart', fanart)

        self.setProperty('mrsp.total_results', str(len(self.results)))

        try:
            ap = xbmcaddon.Addon(
                'plugin.video.romanianpack').getAddonInfo('path')
            self.setProperty('mrsp.icon', os.path.join(ap, 'icon.png'))
        except:
            self.setProperty('mrsp.icon', '')

        counts = {'4K': 0, '1080p': 0, '720p': 0, 'SD': 0}
        for r in self.results:
            try:
                if len(r) > 5 and r[5] == 'system':
                    continue
                n = r[0] if r and r[0] else ''
                q = self._detect_quality(self._strip_tags(n), r[4] if len(r) > 4 else None)
                counts[q] = counts.get(q, 0) + 1
            except:
                pass

        self.setProperty('mrsp.count_4k',    str(counts['4K']))
        self.setProperty('mrsp.count_1080p', str(counts['1080p']))
        self.setProperty('mrsp.count_720p',  str(counts['720p']))
        self.setProperty('mrsp.count_sd',    str(counts['SD']))

    def _find_meta_value(self, *keys):
        for k in keys:
            v = self.meta.get(k)
            if v and str(v).strip():
                return str(v).strip()
        return ''

    def _populate_list(self):
        global_poster = self.meta.get('Poster', '')
        global_plot = self.meta.get('Plot', '')

        is_search_mode = False
        if global_poster and 'http' in global_poster:
            is_search_mode = True

        items = []
        for idx, result in enumerate(self.results):
            try:
                raw_name = result[0] or ''
                clean    = self._strip_tags(raw_name)
                link     = result[1] if len(result) > 1 else ''
                imagine  = result[2] if len(result) > 2 else ''
                switch   = result[3] if len(result) > 3 else ''
                info     = result[4] if len(result) > 4 else {}
                site_id  = result[5] if len(result) > 5 else ''
                site_nm_raw = result[6] if len(result) > 6 else ''
                site_nm = re.sub(r'\[[^\]]*\]', '', str(site_nm_raw)).strip().upper()

                is_next = (site_id == 'system')
                is_aio  = (site_id == 'aiostreams')

                # === AIO STREAMS: site_nm = "AIO STREAMS" colorat cu culoarea calitatii ===
                if is_aio:
                    site_nm = 'AIO STREAMS'

                quality   = self._detect_quality(clean, info) if not is_next else ''
                highlight = QUALITY_COLORS.get(quality, QUALITY_COLORS['SD']) if not is_next else 'FFFFFFFF'
                icon      = QUALITY_ICONS.get(quality, '') if not is_next else ''

                tracker_tags = self._extract_tracker_tags(raw_name)
                seeds  = self._extract_seeds(raw_name)
                # Fallback seederi AIO din dict info
                if not seeds and is_aio and isinstance(info, dict) and info.get('seeders'):
                    seeds = str(info['seeders'])

                raw_size = self._extract_size(clean, info)
                size = self._format_size(raw_size)
                codec  = self._extract_codec(clean)
                source = self._extract_source(clean)
                hdr_tags  = self._extract_hdr(clean)
                audio_tags = self._extract_audio(clean)

                # --- CULORI CODECURI ---
                if codec:
                    cod_up = codec.upper()
                    if 'HEVC' in cod_up or '265' in cod_up:
                        codec = '[B][COLOR FF008080]HEVC[/COLOR][/B]'
                    elif '264' in cod_up:
                        codec = '[B][COLOR FFA52A2A]x264[/COLOR][/B]'

                # --- CULORI SURSE ---
                if source:
                    src_up = source.upper()
                    if 'REMUX' in src_up:
                        source = '[COLOR FFFF0000][B]REMUX[/B][/COLOR]'
                    elif 'BLURAY' in src_up or 'BLU-RAY' in src_up:
                        source = '[COLOR FF00BFFF][B]BluRay[/B][/COLOR]'
                    elif 'WEBRIP' in src_up:
                        source = '[COLOR FF20B2AA][B]WebRip[/B][/COLOR]'
                    elif 'WEB' in src_up:
                        source = '[COLOR FF00FA9A][B]WEB-DL[/B][/COLOR]'

                # --- CONSTRUIRE info_parts ---
                info_parts = []

                if is_aio:
                    # === AIO STREAMS: CACHED / CLOUD ===
                    if isinstance(info, dict) and info.get('is_cached'):
                        info_parts.append('[COLOR lime][B]RD[/B][/COLOR]')
                    if isinstance(info, dict) and info.get('is_cloud'):
                        info_parts.append('[COLOR cyan][B]CLOUD[/B][/COLOR]')

                    if isinstance(info, dict):
                        src_addon = str(info.get('source_addon', '') or '').strip()
                        indexer_raw = str(info.get('indexer', '') or '').strip()
                        # Filtram "None" ca string
                        if src_addon.lower() == 'none': src_addon = ''
                        if indexer_raw.lower() == 'none': indexer_raw = ''

                        # === ADDON (Comet, MediaFusion, etc.) - PRIMUL pe rand ===
                        if src_addon:
                            addon_color = AIO_ADDON_COLORS.get(src_addon.lower(), 'FF00BFFF')
                            info_parts.append('[COLOR %s][B]%s[/B][/COLOR]' % (addon_color, src_addon))

                        # === INDEXER - curatat de numele addonului ===
                        if indexer_raw:
                            indexer_display = indexer_raw

                            if src_addon:
                                # "Comet|BitMagnet" -> "BitMagnet"
                                if indexer_raw.startswith(src_addon + '|'):
                                    indexer_display = indexer_raw[len(src_addon) + 1:]
                                # "BitMagnet|Comet" -> "BitMagnet"
                                elif indexer_raw.endswith('|' + src_addon):
                                    indexer_display = indexer_raw[:-(len(src_addon) + 1)]
                                # "Comet" singur = identic cu addon, nu mai afisam
                                elif indexer_raw.lower() == src_addon.lower():
                                    indexer_display = ''
                                # "Comet TheRARBG" (fara pipe) -> "TheRARBG"
                                elif indexer_raw.lower().startswith(src_addon.lower() + ' '):
                                    indexer_display = indexer_raw[len(src_addon):].strip()
                                elif indexer_raw.lower().startswith(src_addon.lower()):
                                    indexer_display = indexer_raw[len(src_addon):].strip()
                                    if indexer_display.startswith('|') or indexer_display.startswith(' '):
                                        indexer_display = indexer_display[1:].strip()

                            # Afisam indexerul curatat cu acelasi stil bold + culoare gold
                            if indexer_display:
                                info_parts.append('[COLOR FFFFD700][B]%s[/B][/COLOR]' % indexer_display)

                    # === LIMBI ===
                    if isinstance(info, dict):
                        langs = info.get('languages', [])
                        if langs:
                            if len(langs) > 1:
                                info_parts.append('[COLOR yellow][B]MULTI[/B][/COLOR]')
                            def _fmt_lang(l):
                                s = str(l).strip().upper()
                                # Păstrăm cuvinte speciale întregi, altele le trunchiem la 3
                                if s in ('MULTI', 'MULTILANGUAGE', 'DUAL'):
                                    return s[:5]  # MULTI
                                return s[:3]
                            info_parts.append('[COLOR orange]%s[/COLOR]' % (','.join([_fmt_lang(l) for l in langs if l])))

                elif site_id in JSON_PROVIDERS:
                    # === Provideri JSON/Stremio: sursa originala din Genre ===
                    orig_prov = info.get('Genre') if isinstance(info, dict) else ''
                    if orig_prov:
                        info_parts.append('[COLOR cyan][B]%s[/B][/COLOR]' % orig_prov)

                # Tracker tags (FileList, SpeedApp, etc.)
                if tracker_tags:
                    info_parts.append(tracker_tags)
                if size:
                    info_parts.append('[COLOR FF00CED1][B]%s[/B][/COLOR]' % size)
                if source:
                    info_parts.append(source)
                if codec:
                    info_parts.append(codec)

                # HDR/DV
                for htag in hdr_tags:
                    info_parts.append('[COLOR FFFFCC00][B]%s[/B][/COLOR]' % htag)

                # Audio - culori per tip
                for atag in audio_tags:
                    aud_up = atag.upper()
                    if 'ATMOS' in aud_up:
                        info_parts.append('[COLOR FFFF4500][B]Atmos[/B][/COLOR]')
                    elif 'TRUEHD' in aud_up:
                        info_parts.append('[COLOR FFFF4500][B]TrueHD[/B][/COLOR]')
                    elif 'DTS' in aud_up:
                        info_parts.append('[COLOR FF1E90FF][B]%s[/B][/COLOR]' % atag)
                    elif 'DDP' in aud_up or 'DD+' in aud_up or 'EAC' in aud_up:
                        info_parts.append('[COLOR FFADFF2F][B]%s[/B][/COLOR]' % atag)
                    elif 'AC3' in aud_up:
                        info_parts.append('[COLOR FF7CFC00][B]%s[/B][/COLOR]' % atag)
                    elif 'AAC' in aud_up:
                        info_parts.append('[COLOR FFFFFFFF][B]%s[/B][/COLOR]' % atag)
                    elif 'FLAC' in aud_up:
                        info_parts.append('[COLOR FF00CED1][B]FLAC[/B][/COLOR]')
                    else:
                        info_parts.append('[COLOR FF7CFC00][B]%s[/B][/COLOR]' % atag)

                if seeds and seeds != '0':
                    info_parts.append('[B][COLOR FF87CEEB]S: %s[/COLOR][/B]' % seeds)

                info_line = ' | '.join(info_parts)

                # Display name: AIO pastreaza raw_name, restul se curata
                if is_aio:
                    display_name = raw_name
                else:
                    display_name = self._clean_display_name(clean)

                li = xbmcgui.ListItem(display_name)

                prov_icon = os.path.join(
                    xbmcaddon.Addon('plugin.video.romanianpack').getAddonInfo('path'),
                    'resources', 'media', site_id + '.png')

                if is_next:
                    display_name = '[COLOR orange]>>> %s[/COLOR]' % display_name.replace('>>> ', '').replace('► ', '')
                    highlight = 'FFFFA500'
                    info_line = 'Afiseaza restul de rezultate disponibile...'
                    site_nm = ''
                    li.setProperty('mrsp.provider_icon', os.path.join(
                        xbmcaddon.Addon('plugin.video.romanianpack').getAddonInfo('path'),
                        'resources', 'media', 'next.png'))
                    li.setProperty('mrsp.is_next', 'true')
                    li.setProperty('mrsp.poster', '')
                    li.setProperty('mrsp.plot', '')
                else:
                    li.setProperty('mrsp.provider_icon', prov_icon)

                    if is_search_mode:
                        li.setProperty('mrsp.poster', global_poster)
                        li.setProperty('mrsp.plot', global_plot)
                    else:
                        poster_item = info.get('Poster') if isinstance(info, dict) else ''
                        if poster_item:
                            li.setProperty('mrsp.poster', poster_item)
                        else:
                            li.setProperty('mrsp.poster', prov_icon)
                        li.setProperty('mrsp.plot', info.get('Plot', '') if isinstance(info, dict) else '')

                li.setProperty('mrsp.name',         display_name)
                li.setProperty('mrsp.quality',      quality)
                li.setProperty('mrsp.highlight',    highlight)
                li.setProperty('mrsp.quality_icon', icon)
                li.setProperty('mrsp.provider',     site_nm)
                li.setProperty('mrsp.info_line',    info_line)
                li.setProperty('mrsp.data',         self._serialize_item(site_id, link, switch, raw_name, info))
                items.append(li)
            except: pass
        self.getControl(2000).addItems(items)


    def _detect_quality(self, name, info=None):
        for pattern, quality in QUALITY_PATTERNS:
            if re.search(pattern, name, re.I):
                return quality
        if info and isinstance(info, dict):
            meta_text = str(info.get('Genre', '')) + " " + str(info.get('Plot', ''))
            for pattern, quality in QUALITY_PATTERNS:
                if re.search(pattern, meta_text, re.I):
                    return quality
        return 'SD'

    def _extract_tracker_tags(self, raw_name):
        text = re.sub(r'\[[^\]]*\]', '', raw_name)
        tags = []
        for pattern, styled in TRACKER_TAG_PATTERNS:
            if re.search(pattern, text, re.I):
                tags.append(styled)
        return ' '.join(tags)

    def _extract_seeds(self, name):
        m = re.search(r'\[S(?:/L)?:\s*(\d[\d,.]*)', name)
        if m:
            return m.group(1).replace(',', '')
        m = re.search(r'Seeds?[:\s]+(\d+)', name, re.I)
        if m:
            return m.group(1)
        return ''

    def _extract_size(self, name, info):
        m = re.search(
            r'(\d+(?:[.,]\d+)?)\s*(GB|MB|TB)', name, re.I)
        if m:
            return '%s %s' % (m.group(1), m.group(2).upper())
        if info and isinstance(info, dict):
            s = info.get('size') or info.get('Size') or ''
            if s:
                return str(s)
        return ''

    def _extract_codec(self, name):
        for pattern, label in CODEC_PATTERNS:
            if re.search(pattern, name, re.I):
                return label
        return ''

    def _extract_source(self, name):
        for src in SOURCE_PATTERNS:
            m = re.search(src, name, re.I)
            if m:
                return m.group(0)
        return ''

    def _extract_hdr(self, name):
        found = []
        for pattern, label in HDR_PATTERNS:
            if re.search(pattern, name, re.I):
                if label not in found:
                    found.append(label)
        return found

    def _extract_audio(self, name):
        name_normalized = name.replace('.', ' ').replace('_', ' ')
        found_tags = []
        for pattern, label in AUDIO_PATTERNS:
            if re.search(pattern, name_normalized, re.I):
                if not any(label in t or t in label for t in found_tags):
                    found_tags.append(label)
        return found_tags

    def _strip_tags(self, name):
        return re.sub(r'\[[^\]]*\]', '', str(name)).strip()

    def _clean_display_name(self, name):
        if '[AIO' in name:
            return name.strip()
        name = re.sub(r'\[S/L:\s*[\d,./]+\]', '', name)
        name = re.sub(r'\[P:\s*[\d,./]+\]', '', name)
        name = re.sub(
            r'\[\d+(?:[.,]\d+)?\s*(?:GB|MB|TB)\]', '',
            name, flags=re.I)
        name = re.sub(
            r'\(\d+(?:[.,]\d+)?\s*(?:GB|MB|TB)\)', '',
            name, flags=re.I)
        name = re.sub(r'\bS(?:/L)?:\s*[\d,./]+', '', name)
        name = re.sub(
            r'(?i)(?:www\s?\.\s?UIndex\s?\.\s?org|FileList|'
            r'filelist\s?\.\s?io|Meteor|SpeedApp|filelist\s?io|'
            r'MediaFusion|Comet|Heartive|Torrentio|CornCastle|'
            r'PirateBay\+?|YTS)',
            '', name)
        name = re.sub(
            r'(?i)\b(?:FREE(?:LEECH)?|DoubleUP|Double\s*Upload|'
            r'2x\s*(?:Upload|UP)|PROMOVAT|Recomandat|Verificat|'
            r'Aur|VIP|ROSubbed|Internal|INT|DU)\b',
            '', name)
        name = re.sub(r'^[\s\-\.\:]+', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        return name

    def _serialize_item(self, site, link, switch, nume, info):
        if info is None:
            info = {}
        elif not isinstance(info, dict):
            try:
                info = json.loads(str(info))
                if not isinstance(info, dict):
                    info = {}
            except:
                info = {}
        data = {
            'site':   site   or '',
            'link':   link   or '',
            'switch': switch or '',
            'nume':   nume   or '',
            'info':   info
        }
        try:
            return json.dumps(data, ensure_ascii=False, default=str)
        except:
            return json.dumps({
                'site': str(site), 'link': str(link),
                'switch': str(switch), 'nume': str(nume),
                'info': {}
            })

    def _get_fav_menu_item(self, base_url, link, clean_title, data_str):
        is_fav = False
        try:
            from resources.functions import get_fav
            if get_fav(link):
                is_fav = True
        except: pass
        if is_fav:
            return ("Sterge din [B][COLOR orange]Torrente Favorite[/COLOR][/B]", "FAV_DELETE|%s" % link)
        else:
            return ("Adauga la [B][COLOR orange]Torrente Favorite[/COLOR][/B]", "FAV_ADD|%s|%s|%s" % (link, clean_title, data_str))

    # =================================================================
    # INFO TORRENT - fara emoji, cu indexer, text compact
    # =================================================================
    def _build_torrent_info(self, data):
        info = data.get('info', {})
        raw_name = data.get('nume', '')
        site_id = data.get('site', '')
        link = data.get('link', '')
        clean = self._strip_tags(raw_name)
        clean_dots = clean.replace('.', ' ').replace('_', ' ')

        lines = []
        sep = '========================================'

        lines.append('[B]%s[/B]' % sep)
        lines.append('[B][COLOR FF00BFFF]         INFO TORRENT[/COLOR][/B]')
        lines.append('[B]%s[/B]' % sep)
        lines.append('')

        # --- NUME COMPLET ---
        title = info.get('Title', '') or clean
        lines.append('[B][COLOR FFFFCC00]NUME COMPLET:[/COLOR][/B]')
        lines.append('  %s' % title)
        lines.append('')

        # --- CALITATE VIDEO ---
        lines.append('[B][COLOR FF00FA9A]CALITATE VIDEO:[/COLOR][/B]')
        quality = self._detect_quality(clean, info)
        lines.append('  Rezolutie:  [B]%s[/B]' % quality)

        source = self._extract_source(clean)
        if source:
            lines.append('  Sursa:      [B]%s[/B]' % source)

        codec = self._extract_codec(clean)
        if codec:
            lines.append('  Codec:      [B]%s[/B]' % codec)

        hdr_tags = self._extract_hdr(clean)
        if hdr_tags:
            lines.append('  HDR:        [B]%s[/B]' % ' + '.join(hdr_tags))

        # Tag-uri speciale
        for tag in ['Remux', 'PROPER', 'REPACK', 'EXTENDED', 'UNCUT', 'DIRECTOR']:
            if re.search(r'(?i)\b%s\b' % tag, clean):
                lines.append('  Varianta:   [B]%s[/B]' % tag)
                break
        lines.append('')

        # --- AUDIO ---
        audio_tags = self._extract_audio(clean)
        if audio_tags:
            lines.append('[B][COLOR FFFF4500]AUDIO:[/COLOR][/B]')
            for i, atag in enumerate(audio_tags):
                label = 'Principal' if i == 0 else 'Extra'
                lines.append('  %-10s  [B]%s[/B]' % (label + ':', atag))
            ch = re.search(r'(?i)\b(7\.1|5\.1|2\.0|2\.1|1\.0)\b', clean_dots)
            if ch:
                lines.append('  Canale:     [B]%s[/B]' % ch.group(1))
            lines.append('')

        # --- LIMBI ---
        languages = info.get('languages', [])
        if languages:
            if isinstance(languages, list):
                lang_str = ', '.join([str(l) for l in languages if l])
                lang_count = len([l for l in languages if l])
            else:
                lang_str = str(languages)
                lang_count = 1
            if lang_str:
                lines.append('[B][COLOR FF87CEEB]LIMBI:[/COLOR][/B]')
                lines.append('  %s' % lang_str)
                if lang_count > 1:
                    lines.append('  [B]MULTI-LANGUAGE (%d limbi)[/B]' % lang_count)
                lines.append('')

        # Fallback: detectare limbi din titlu
        if not languages:
            lang_in_title = []
            for lp, ln in [
                (r'(?i)\bRO(?:manian)?\b', 'Romana'),
                (r'(?i)\bEN(?:glish)?\b', 'English'),
                (r'(?i)\bMULTI\b', 'Multi'),
                (r'(?i)\bHUN(?:garian)?\b', 'Hungarian'),
                (r'(?i)\bGER(?:man)?\b|DEUTSCH', 'German'),
                (r'(?i)\bFR(?:ench|E)?\b', 'French'),
            ]:
                if re.search(lp, clean):
                    lang_in_title.append(ln)
            if lang_in_title:
                lines.append('[B][COLOR FF87CEEB]LIMBI (din titlu):[/COLOR][/B]')
                lines.append('  %s' % ', '.join(lang_in_title))
                lines.append('')

        # --- FISIER ---
        lines.append('[B][COLOR FF00CED1]FISIER:[/COLOR][/B]')

        size = info.get('Size', info.get('size', ''))
        if not size:
            size = self._extract_size(clean, info)
        if size:
            lines.append('  Marime:     [B]%s[/B]' % self._format_size(size))

        seeders = info.get('seeders', '')
        if not seeders:
            seeders = self._extract_seeds(raw_name)
        if seeders and str(seeders) != '0':
            lines.append('  Seederi:    [B]%s[/B]' % seeders)

        is_cached = info.get('is_cached', False)
        is_cloud = info.get('is_cloud', False)
        if is_cached:
            lines.append('  Status:     [B][COLOR lime]CACHED (Debrid)[/COLOR][/B]')
        elif is_cloud:
            lines.append('  Status:     [B][COLOR cyan]CLOUD[/COLOR][/B]')
        elif link and 'magnet:' in link:
            lines.append('  Status:     [B]P2P (Torrent)[/B]')
        elif link and link.startswith('http'):
            lines.append('  Status:     [B]Direct Link[/B]')
        lines.append('')

        # --- INDEXER / SURSA ---
        lines.append('[B][COLOR cyan]INDEXER / SURSA:[/COLOR][/B]')

        source_addon = info.get('source_addon', '')
        indexer = info.get('indexer', '')
        genre_source = info.get('Genre', '')

        if source_addon:
            lines.append('  Addon:      [B]%s[/B]' % source_addon)

        if indexer:
            lines.append('  Indexer:    [B][COLOR FFFFD700]%s[/COLOR][/B]' % indexer)

        if genre_source and genre_source != source_addon and genre_source not in ('4K', '1080p', '720p', 'SD'):
            genre_clean = re.sub(r'\b(4K|1080p|720p|SD)\b\s*\|?\s*', '', genre_source).strip()
            if genre_clean:
                lines.append('  Tracker:    [B]%s[/B]' % genre_clean)

        prov_name = PROVIDER_NAMES.get(site_id, site_id.upper() if site_id else 'N/A')
        lines.append('  Provider:   [B][COLOR FF00BFFF]%s[/COLOR][/B]' % prov_name)

        if not source_addon and not indexer and not genre_source:
            lines.append('  Indexer:    [B]%s (direct)[/B]' % prov_name)
        lines.append('')

        # --- SERVICE DEBRID ---
        service = info.get('service', '')
        if service:
            lines.append('[B][COLOR FFEE82EE]SERVICIU DEBRID:[/COLOR][/B]')
            lines.append('  %s' % service.replace('realdebrid', 'Real-Debrid').replace('alldebrid', 'AllDebrid').replace('premiumize', 'Premiumize'))
            lines.append('')

        # --- HASH / LINK ---
        if link:
            lines.append('[B][COLOR gray]IDENTIFICARE:[/COLOR][/B]')
            if 'btih:' in link:
                hash_m = re.search(r'btih:([a-fA-F0-9]+)', link)
                if hash_m:
                    lines.append('  Hash:  %s' % hash_m.group(1)[:40])

                trackers = re.findall(r'tr=([^&]+)', link)
                if trackers:
                    lines.append('')
                    lines.append('[B][COLOR gray]TRACKERE (%d):[/COLOR][/B]' % len(trackers))
                    try:
                        try:
                            from urllib import unquote as uq
                        except ImportError:
                            from urllib.parse import unquote as uq
                        for i, tr in enumerate(trackers[:6]):
                            lines.append('  %d. %s' % (i + 1, uq(tr)))
                        if len(trackers) > 6:
                            lines.append('  ... +%d trackere' % (len(trackers) - 6))
                    except:
                        pass
            elif link.startswith('http'):
                try:
                    try:
                        from urlparse import urlparse
                    except ImportError:
                        from urllib.parse import urlparse
                    lines.append('  Server:  %s' % urlparse(link).netloc)
                except:
                    pass
            lines.append('')

        # --- ID-URI MEDIA ---
        imdb_id = info.get('imdb_id', '') or info.get('imdbnumber', '')
        tmdb_id = info.get('tmdb_id', '')
        if imdb_id or tmdb_id:
            lines.append('[B][COLOR gray]ID-URI MEDIA:[/COLOR][/B]')
            if imdb_id:
                lines.append('  IMDb:  %s' % imdb_id)
            if tmdb_id:
                lines.append('  TMDb:  %s' % tmdb_id)
            lines.append('')

        lines.append('[B]%s[/B]' % sep)
        return '\n'.join(lines)

    def onClick(self, controlId):
        if controlId == 2000:
            try:
                item = self.getControl(2000).getSelectedItem()
                if item:
                    self.selected = item.getProperty('mrsp.data')
                    xbmcgui.Window(10000).setProperty('mrsp.torrent.name', item.getProperty('mrsp.name') or '')
            except:
                pass
            self.close()

    def onAction(self, action):
        action_id = action.getId()

        # 1. Back / Close / Escape
        if action_id in (9, 10, 13, 92, 110):
            # Daca tocmai s-a inchis un dialog (textviewer/contextmenu), ignoram
            if hasattr(self, '_dialog_closed_time') and time.time() - self._dialog_closed_time < 0.6:
                self._dialog_closed_time = 0
                return
            self.selected = None
            self.close()

        # 2. Context Menu (Tasta C, Click-Dreapta, Apasare Lunga)
        elif action_id in (117, 101):
            if hasattr(self, '_dialog_closed_time') and time.time() - self._dialog_closed_time < 0.6:
                return

            try:
                item = self.getControl(2000).getSelectedItem()
                if not item: return
                if item.getProperty('mrsp.is_next') == 'true': return

                data_str = item.getProperty('mrsp.data')
                if not data_str: return

                data = json.loads(data_str)
                site = data.get('site', '')

                link = data.get('link') or data.get('legatura') or data.get('url') or ''
                if not link: return

                info = data.get('info', {})
                clean_title = info.get('Title', data.get('nume', ''))
                imdb_id = info.get('imdb_id') or info.get('imdb') or info.get('imdbnumber') or ''

                try:
                    from urllib import quote_plus as quote
                except ImportError:
                    from urllib.parse import quote_plus as quote

                info_str = quote(json.dumps(info, default=str))
                base_url = "plugin://plugin.video.romanianpack/"

                switch_act = data.get('switch', '')
                if switch_act == 'play_rd':
                    menu = [
                        ("[B][COLOR FF00BFFF]INFO Torrent[/COLOR][/B]", "INFO_TORRENT"),
                        ("MetaInfo IMDb", "RunPlugin(%s?action=getMeta&getMeta=IMDb&nume=%s&imdb=%s)" % (base_url, quote(clean_title), quote(imdb_id))),
                        ("MetaInfo TMdb", "RunPlugin(%s?action=getMeta&getMeta=TMdb&nume=%s&imdb=%s)" % (base_url, quote(clean_title), quote(imdb_id))),
                        ("[B][COLOR yellow]Cauta variante[/COLOR][/B]", "SEARCH_VARIANTS"),
                        self._get_fav_menu_item(base_url, link, clean_title, data_str),
                        ("Marcheaza ca vizionat", "RunPlugin(%s?action=watched&watched=save&watchedlink=%s&nume=%s&detalii=%s&norefresh=1)" % (base_url, quote(link), quote(clean_title), quote(data_str))),
                        ("Sterge [B][COLOR red]Resume[/COLOR][/B]", "CLEAR_RESUME"),
                        ("Redare Directa (Real Debrid)", "RunPlugin(%s?action=OpenSite&site=%s&link=%s&switch=play&nume=%s&info=%s)" % (base_url, quote(site), quote(link), quote(clean_title), info_str)),
                        ("Cauta in [B][COLOR red]You[COLOR white]tube[/COLOR][/B]", "RunPlugin(%s?action=YoutubeSearch&url=%s)" % (base_url, quote(clean_title)))
                    ]
                else:
                    menu = [
                        ("[B][COLOR FF00BFFF]INFO Torrent[/COLOR][/B]", "INFO_TORRENT"),
                        ("MetaInfo IMDb", "RunPlugin(%s?action=getMeta&getMeta=IMDb&nume=%s&imdb=%s)" % (base_url, quote(clean_title), quote(imdb_id))),
                        ("MetaInfo TMdb", "RunPlugin(%s?action=getMeta&getMeta=TMdb&nume=%s&imdb=%s)" % (base_url, quote(clean_title), quote(imdb_id))),
                        ("[B][COLOR yellow]Cauta variante[/COLOR][/B]", "SEARCH_VARIANTS"),
                        self._get_fav_menu_item(base_url, link, clean_title, data_str),
                        ("Marcheaza ca vizionat", "RunPlugin(%s?action=watched&watched=save&watchedlink=%s&nume=%s&detalii=%s&norefresh=1)" % (base_url, quote(link), quote(clean_title), quote(data_str))),
                        ("Sterge [B][COLOR red]Resume[/COLOR][/B]", "CLEAR_RESUME"),
                        ("Play cu [B][COLOR FF6AFB92]TorrServer[/COLOR][/B]", "RunPlugin(%s?action=OpenT&Tmode=playtorrserver&Turl=%s&Tsite=%s&info=%s)" % (base_url, quote(link), quote(site), info_str)),
                        ("Play cu [B][COLOR orange]MRSP[/COLOR][/B]", "RunPlugin(%s?action=OpenT&Tmode=playmrsp&Turl=%s&Tsite=%s&info=%s)" % (base_url, quote(link), quote(site), info_str)),
                        ("Play cu [B][COLOR gray]Elementum[/COLOR][/B]", "RunPlugin(%s?action=OpenT&Tmode=playelementum&Turl=%s&Tsite=%s&info=%s)" % (base_url, quote(link), quote(site), info_str)),
                        ("Cauta in [B][COLOR red]You[COLOR white]tube[/COLOR][/B]", "RunPlugin(%s?action=YoutubeSearch&url=%s)" % (base_url, quote(clean_title)))
                    ]

                labels = [m[0] for m in menu]
                dialog = xbmcgui.Dialog()
                ret = dialog.contextmenu(labels)

                # Marcam momentul inchiderii dialogului
                self._dialog_closed_time = time.time()

                if ret >= 0:
                    action_cmd = menu[ret][1]
                    label_chosen = menu[ret][0]

                    # === INFO TORRENT ===
                    if action_cmd == "INFO_TORRENT":
                        info_text = self._build_torrent_info(data)
                        prov_display = PROVIDER_NAMES.get(site, site.upper() if site else 'Torrent')
                        xbmcgui.Dialog().textviewer(
                            'INFO Torrent  -  %s' % prov_display,
                            info_text
                        )
                        # FIX: Marcam si dupa textviewer ca sa nu re-deschida meniul
                        self._dialog_closed_time = time.time()
                        return

                    if action_cmd == "CLEAR_RESUME":
                        try:
                            from resources.functions import addonCache, log as mrsp_log
                            try:
                                from sqlite3 import dbapi2 as database
                            except:
                                from pysqlite2 import dbapi2 as database

                            dbcon = database.connect(addonCache)
                            dbcur = dbcon.cursor()

                            mrsp_log('[MRSP-CLEAR] ========== STERGE RESUME ==========')
                            mrsp_log('[MRSP-CLEAR] info: %s' % str(info)[:200])
                            mrsp_log('[MRSP-CLEAR] link: %s' % str(link)[:200])

                            dbcur.execute("SELECT title, elapsed, total FROM resume")
                            all_resume = dbcur.fetchall()
                            mrsp_log('[MRSP-CLEAR] Total intrari resume in DB: %d' % len(all_resume))
                            for r in all_resume:
                                mrsp_log('[MRSP-CLEAR]   DB: "%s" (%.1f/%.1f)' % (r[0], float(r[1]), float(r[2])))

                            patterns = set()
                            import re as re2

                            i_id = info.get('imdb_id') or info.get('imdb') or info.get('IMDBNumber') or ''
                            t_id = info.get('tmdb_id') or ''
                            if i_id: patterns.add('imdb_%s%%' % i_id)
                            if t_id: patterns.add('tmdb_%s%%' % t_id)

                            if i_id and not t_id:
                                try:
                                    from resources.functions import fetchData, tmdb_key
                                    url_find = 'https://api.themoviedb.org/3/find/%s?api_key=%s&external_source=imdb_id' % (i_id, tmdb_key())
                                    res_f = fetchData(url_find, rtype='json')
                                    if res_f:
                                        if res_f.get('movie_results'): patterns.add('tmdb_%s%%' % res_f['movie_results'][0]['id'])
                                        elif res_f.get('tv_results'): patterns.add('tmdb_%s%%' % res_f['tv_results'][0]['id'])
                                except: pass
                            elif t_id and not i_id:
                                try:
                                    from resources.functions import convert_tmdb_to_imdb
                                    alt_imdb = convert_tmdb_to_imdb(t_id, 'movie') or convert_tmdb_to_imdb(t_id, 'tv')
                                    if alt_imdb: patterns.add('imdb_%s%%' % alt_imdb)
                                except: pass

                            if not i_id and not t_id:
                                try:
                                    from resources.lib import PTN
                                    from resources.functions import get_movie_ids_from_tmdb, get_show_ids_from_tmdb
                                    raw_title = info.get('Title') or clean_title or ''
                                    raw_title = re2.sub(r'\[.*?\]', '', raw_title)
                                    parsed_t = PTN.parse(raw_title.replace('.', ' '))
                                    lookup_t = parsed_t.get('title', '')
                                    lookup_y = parsed_t.get('year')
                                    is_show = bool(parsed_t.get('season') or re2.search(r'(?i)S\d+', raw_title))
                                    mrsp_log('[MRSP-CLEAR] Auto-lookup: "%s" year=%s show=%s' % (lookup_t, lookup_y, is_show))
                                    if lookup_t and len(lookup_t) > 2:
                                        if is_show:
                                            at, ai = get_show_ids_from_tmdb(lookup_t)
                                        else:
                                            at, ai = get_movie_ids_from_tmdb(lookup_t, lookup_y)
                                        if at:
                                            patterns.add('tmdb_%s%%' % at)
                                            mrsp_log('[MRSP-CLEAR] Auto-lookup TMDb: %s' % at)
                                        if ai:
                                            patterns.add('imdb_%s%%' % ai)
                                            mrsp_log('[MRSP-CLEAR] Auto-lookup IMDb: %s' % ai)
                                except Exception as e_lu:
                                    mrsp_log('[MRSP-CLEAR] Auto-lookup eroare: %s' % str(e_lu))

                            if link:
                                md5_m = re2.search(r'([a-f0-9]{32})', link)
                                if md5_m: patterns.add('local_%s%%' % md5_m.group(1))
                                btih_m = re2.search(r'btih:([a-zA-Z0-9]+)', link, re2.I)
                                if btih_m: patterns.add('hash_%s%%' % btih_m.group(1).lower())
                                id_m = re2.search(r'id=(\d+)', link)
                                if id_m: patterns.add('filelist_%s%%' % id_m.group(1))
                                patterns.add(link)

                            try:
                                last_base = xbmcgui.Window(10000).getProperty('mrsp.last_resume_base')
                                if last_base: patterns.add('%s%%' % last_base)
                            except: pass

                            try:
                                sel_data = json.loads(data_str)
                                sel_link = sel_data.get('link', '')
                                if sel_link:
                                    md5_m2 = re2.search(r'([a-f0-9]{32})', sel_link)
                                    if md5_m2: patterns.add('local_%s%%' % md5_m2.group(1))
                                    btih_m2 = re2.search(r'btih:([a-zA-Z0-9]+)', sel_link, re2.I)
                                    if btih_m2: patterns.add('hash_%s%%' % btih_m2.group(1).lower())
                                    id_m2 = re2.search(r'id=(\d+)', sel_link)
                                    if id_m2: patterns.add('filelist_%s%%' % id_m2.group(1))
                            except: pass

                            try:
                                mrsp_data_str = xbmcgui.Window(10000).getProperty('mrsp.data')
                                if mrsp_data_str:
                                    import ast
                                    d = ast.literal_eval(mrsp_data_str)
                                    rid = d.get('mrsp_resume_id', '')
                                    if rid:
                                        base = re2.sub(r'_(S\d+E\d+|S\d+_pack|movie|F[a-f0-9]+)$', '', rid)
                                        if base: patterns.add('%s%%' % base)
                                    mlink = d.get('link') or d.get('landing') or ''
                                    if mlink:
                                        md5_m3 = re2.search(r'([a-f0-9]{32})', mlink)
                                        if md5_m3: patterns.add('local_%s%%' % md5_m3.group(1))
                            except: pass

                            mrsp_log('[MRSP-CLEAR] Patterns de stergere: %s' % str(patterns))

                            total_deleted = 0
                            for pattern in patterns:
                                if not pattern or pattern in ('%', '%%'): continue
                                mrsp_log('[MRSP-CLEAR] Test pattern: "%s"' % pattern)

                                dbcur.execute("SELECT count(*), group_concat(title) FROM resume WHERE title LIKE ?", (str(pattern),))
                                row = dbcur.fetchone()
                                if row[0] and int(row[0]) > 0:
                                    dbcur.execute("DELETE FROM resume WHERE title LIKE ?", (str(pattern),))
                                    total_deleted += int(row[0])

                                dbcur.execute("SELECT count(*) FROM watched WHERE title LIKE ?", (str(pattern),))
                                w_count = dbcur.fetchone()[0]
                                if w_count and int(w_count) > 0:
                                    dbcur.execute("DELETE FROM watched WHERE title LIKE ?", (str(pattern),))
                                    total_deleted += int(w_count)

                            try: dbcur.execute("VACUUM")
                            except: pass
                            dbcon.commit()

                            mrsp_log('[MRSP-CLEAR] Total sters: %d' % total_deleted)

                            _mrsp_icon = os.path.join(xbmcaddon.Addon('plugin.video.romanianpack').getAddonInfo('path'), 'icon.png')
                            if total_deleted > 0:
                                xbmcgui.Dialog().notification('[B][COLOR FFFDBD01]MRSP Lite[/COLOR][/B]', '[B][COLOR red]%d intrari resume sterse[/COLOR][/B]' % total_deleted, _mrsp_icon, 3000, False)
                            else:
                                xbmcgui.Dialog().notification('[B][COLOR FFFDBD01]MRSP Lite[/COLOR][/B]', '[B][COLOR gray]Niciun resume gasit[/COLOR][/B]', _mrsp_icon, 3000, False)
                        except Exception as ex_clear:
                            try:
                                from resources.functions import log as mrsp_log
                                mrsp_log('[MRSP-CLEAR] EROARE: %s' % str(ex_clear))
                            except: pass
                        return

                    if action_cmd.startswith("FAV_ADD|"):
                        parts = action_cmd.split("|", 3)
                        fav_link = parts[1] if len(parts) > 1 else ''
                        fav_title = parts[2] if len(parts) > 2 else ''
                        fav_data = parts[3] if len(parts) > 3 else ''
                        try:
                            from resources.functions import save_fav
                            _mrsp_icon = os.path.join(xbmcaddon.Addon('plugin.video.romanianpack').getAddonInfo('path'), 'icon.png')
                            save_fav(fav_title, fav_link, fav_data, norefresh='1', silent=True)
                            xbmcgui.Dialog().notification('[B][COLOR FFFDBD01]MRSP Lite[/COLOR][/B]', '[B][COLOR lime]Adaugat la [COLOR orange]Torrente Favorite[/COLOR][/B]', _mrsp_icon, 3000, False)
                        except: pass
                        return

                    if action_cmd.startswith("FAV_DELETE|"):
                        fav_link = action_cmd.split("|", 1)[1]
                        try:
                            from resources.functions import del_fav
                            _mrsp_icon = os.path.join(xbmcaddon.Addon('plugin.video.romanianpack').getAddonInfo('path'), 'icon.png')
                            del_fav(fav_link, norefresh='1', silent=True)
                            xbmcgui.Dialog().notification('[B][COLOR FFFDBD01]MRSP Lite[/COLOR][/B]', '[B][COLOR red]Sters din [COLOR orange]Torrente Favorite[/COLOR][/B]', _mrsp_icon, 3000, False)
                        except: pass
                        return

                    if 'YoutubeSearch' in action_cmd:
                        self.close()
                        xbmc.sleep(300)
                        xbmc.executebuiltin(action_cmd)
                        return

                    if action_cmd == "SEARCH_VARIANTS":
                        data['special_action'] = 'search_variants'
                        data['search_query'] = clean_title
                        self.selected = json.dumps(data)
                        self.close()
                    else:
                        if any(x in label_chosen for x in ['Play cu', 'Descarca', 'Rasfoire', 'Redare']):
                            self.close()
                            xbmc.sleep(200)
                        xbmc.executebuiltin(action_cmd)

            except Exception as e:
                pass

    def get_selected(self):
        return self.selected