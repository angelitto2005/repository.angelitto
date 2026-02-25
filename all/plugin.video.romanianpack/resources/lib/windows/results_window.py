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
    (r'Dolby[.\s]?Vision|\.DV\.', 'DV'),
    (r'D/VISION',                 'DV'),
]

AUDIO_PATTERNS = [
    (r'Atmos',              'Atmos'),
    (r'TrueHD',             'TrueHD'),
    (r'DTS-HD(?:\.?MA)?',   'DTS-HD'),
    (r'\bDTS\b',            'DTS'),
    (r'DD[P\+]\s?5\.1',    'DD+5.1'),
    (r'\bDDP\b',            'DD+'),
    (r'EAC3',               'EAC3'),
    (r'\bAAC\b',            'AAC'),
    (r'\bAC3\b',            'AC3'),
    (r'\bFLAC\b',           'FLAC'),
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
]


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

# === MODIFICARE: Numărare statistici fără a include butonul de paginare ===
        counts = {'4K': 0, '1080p': 0, '720p': 0, 'SD': 0}
        for r in self.results:
            # Dacă r[5] este 'system', înseamnă că e butonul de paginare, deci îl sărim
            if len(r) > 5 and r[5] == 'system':
                continue
                
            n = r[0] if r and r[0] else ''
            q = self._detect_quality(self._strip_tags(n))
            counts[q] = counts.get(q, 0) + 1
            
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

                quality   = self._detect_quality(clean) if not is_next else ''
                highlight = QUALITY_COLORS.get(quality, QUALITY_COLORS['SD']) if not is_next else 'FFFFFFFF'
                icon      = QUALITY_ICONS.get(quality, '') if not is_next else ''

                tracker_tags = self._extract_tracker_tags(raw_name)
                seeds  = self._extract_seeds(raw_name)
                size   = self._extract_size(clean, info)
                codec  = self._extract_codec(clean)
                source = self._extract_source(clean)
                hdr    = self._extract_hdr(clean)
                audio  = self._extract_audio(clean)

                # --- CULORI CODECURI ---
                if codec:
                    cod_up = codec.upper()
                    if 'HEVC' in cod_up or '265' in cod_up:
                        codec = '[B][COLOR FF008080]HEVC[/COLOR][/B]' # Teal
                    elif '264' in cod_up:
                        codec = '[B][COLOR FFA52A2A]x264[/COLOR][/B]' # Maro/Cărămiziu

                # --- CULORI SURSE (Case Insensitive) ---
                if source:
                    src_up = source.upper()
                    if 'REMUX' in src_up: 
                        source = '[COLOR FFFF0000][B]REMUX[/B][/COLOR]' # Roșu
                    elif 'BLURAY' in src_up or 'BLU-RAY' in src_up or 'BDMV' in src_up: 
                        source = '[COLOR FF00BFFF][B]BluRay[/B][/COLOR]' # Cyan
                    elif 'WEBRIP' in src_up: 
                        source = '[COLOR FF20B2AA][B]WebRip[/B][/COLOR]' # Light Sea Green
                    elif 'WEB' in src_up: 
                        source = '[COLOR FF00FA9A][B]WEB-DL[/B][/COLOR]' # Spring Green

                # --- CULORI AUDIO (Case Insensitive) ---
                if audio:
                    aud_up = audio.upper()
                    if 'ATMOS' in aud_up: 
                        audio = '[COLOR FFFF4500][B]Atmos[/B][/COLOR]' # Portocaliu
                    elif 'DTS' in aud_up: 
                        audio = '[COLOR FF1E90FF][B]%s[/B][/COLOR]' % audio # Albastru (DTS, DTS-HD, DTS-X)
                    elif 'EAC3' in aud_up or 'DD+' in aud_up or 'DDP' in aud_up: 
                        audio = '[COLOR FFADFF2F][B]DD+[/B][/COLOR]' # Lime Green
                    elif 'AC3' in aud_up: 
                        audio = '[COLOR FF7CFC00][B]AC3[/B][/COLOR]' # Lawn Green
                    elif 'AAC' in aud_up: 
                        if '5.1' in aud_up: audio = '[COLOR FFFFFFFF][B]AAC 5.1[/B][/COLOR]'
                        else: audio = '[COLOR FFFFFFFF][B]AAC[/B][/COLOR]' # Alb
                    elif '5.1' in aud_up: 
                        audio = '[COLOR FF7CFC00][B]5.1[/B][/COLOR]'

                info_parts = []
                if tracker_tags: info_parts.append(tracker_tags)
                if size:         info_parts.append('[COLOR FF00CED1][B]%s[/B][/COLOR]' % size)
                if source:       info_parts.append(source)
                if codec:        info_parts.append(codec)
                if hdr:          info_parts.append('[COLOR FFFFCC00][B]%s[/B][/COLOR]' % hdr)
                if audio:        info_parts.append(audio)
                if seeds:        info_parts.append('[B][COLOR FF87CEEB]S: %s[/COLOR][/B]' % seeds)
                info_line = ' | '.join(info_parts)

                display_name = self._clean_display_name(clean)
                li = xbmcgui.ListItem(display_name)
                
                if is_next:
                    display_name = '[B][COLOR orange]► %s[/COLOR][/B]' % display_name.replace('► ', '')
                    info_line = 'Afișează restul de rezultate disponibile...'
                    site_nm = '' 
                    li.setProperty('mrsp.provider_icon', 'special://home/addons/plugin.video.romanianpack/resources/media/next.png')

                li.setProperty('mrsp.name',         display_name)
                li.setProperty('mrsp.quality',      quality)
                li.setProperty('mrsp.highlight',    highlight)
                li.setProperty('mrsp.quality_icon', icon)
                li.setProperty('mrsp.provider',     site_nm)
                li.setProperty('mrsp.info_line',    info_line)
                li.setProperty('mrsp.is_next',      'true' if is_next else '')
                li.setProperty('mrsp.data',         self._serialize_item(site_id, link, switch, raw_name, info))
                items.append(li)
            except: pass
        self.getControl(2000).addItems(items)


    def _detect_quality(self, name):
        for pattern, quality in QUALITY_PATTERNS:
            if re.search(pattern, name, re.I):
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
        m = re.search(r'\[S/L:\s*(\d[\d,.]*)', name)
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
        for pattern, label in HDR_PATTERNS:
            if re.search(pattern, name, re.I):
                return label
        return ''

    def _extract_audio(self, name):
        for pattern, label in AUDIO_PATTERNS:
            if re.search(pattern, name, re.I):
                return label
        return ''

    def _strip_tags(self, name):
        return re.sub(r'\[[^\]]*\]', '', str(name)).strip()

    def _clean_display_name(self, name):
        name = re.sub(r'\[S/L:\s*[\d,./]+\]', '', name)
        name = re.sub(r'\[P:\s*[\d,./]+\]', '', name)
        name = re.sub(
            r'\[\d+(?:[.,]\d+)?\s*(?:GB|MB|TB)\]', '',
            name, flags=re.I)
        name = re.sub(
            r'(?i)(?:www\s?\.\s?UIndex\s?\.\s?org|FileList|'
            r'filelist\s?\.\s?io|Meteor|SpeedApp|filelist\s?io)',
            '', name)
        name = re.sub(
            r'(?i)\b(?:FREE(?:LEECH)?|DoubleUP|Double\s*Upload|'
            r'2x\s*(?:Upload|UP)|PROMOVAT|Recomandat|Verificat|'
            r'Aur|VIP|ROSubbed|Dublat|Internal|INT|DU)\b',
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

    def onClick(self, controlId):
        if controlId == 2000:
            try:
                item = self.getControl(2000).getSelectedItem()
                if item:
                    self.selected = item.getProperty('mrsp.data')
            except:
                pass
            self.close()

    def onAction(self, action):
        if action.getId() in (9, 10, 13, 92, 110):
            self.selected = None
            self.close()

    def get_selected(self):
        return self.selected