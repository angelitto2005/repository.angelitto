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
    # Atmos si TrueHD (Prioritate maxima)
    (r'(?i)Atmos',              'Atmos'),
    (r'(?i)TrueHD',             'TrueHD'),
    
    # DTS Variants
    (r'(?i)DTS[\-\.]?HD(?:[\-\.]?MA)?',   'DTS-HD'),
    (r'(?i)\bDTS\b',            'DTS'),
    
    # DDP / DD+ / EAC3 (inclusiv DDP5.1 lipit sau cu spatii)
    (r'(?i)DDP\s?5[\. ]?1|DD\+\s?5[\. ]?1|EAC3\s?5[\. ]?1', 'DDP 5.1'),
    (r'(?i)\bDDP\b|DD\+|EAC3',      'DDP'),
    
    # DD / AC3 (inclusiv DD5.1 lipit)
    (r'(?i)DD\s?5[\. ]?1|AC3\s?5[\. ]?1', 'DD 5.1'),
    (r'(?i)\bAC3\b|\bDD\b',            'AC3'),
    
    # AAC (inclusiv AAC5.1 lipit)
    (r'(?i)AAC\s?5[\. ]?1', 'AAC 5.1'), # Va prinde si AAC5.1
    (r'(?i)\bAAC\b',            'AAC'),
    
    # FLAC
    (r'(?i)\bFLAC\b',           'FLAC'),
    
    # Alte formate de 5.1 (6CH, sau "5 1" simplu in titlu)
    # Atentie: \b5[\. ]?1\b prinde "5.1", "5 1"
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

    def _format_size(self, size_raw):
        try:
            # Daca e deja formatat (ex: 2.5 GB), il lasam asa
            if 'GB' in str(size_raw) or 'MB' in str(size_raw): return str(size_raw)
            
            # Daca e numar (bytes), il convertim
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

# === MODIFICARE: Numărare statistici fără a include butonul de paginare ===
        counts = {'4K': 0, '1080p': 0, '720p': 0, 'SD': 0}
        for r in self.results:
            # Dacă r[5] este 'system', înseamnă că e butonul de paginare, deci îl sărim
            if len(r) > 5 and r[5] == 'system':
                continue
                
            n = r[0] if r and r[0] else ''
            q = self._detect_quality(self._strip_tags(n), r[4] if len(r) > 4 else None)
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
        # 1. Determinam daca suntem in Cautare (avem poster real) sau Recente (poster generic)
        global_poster = self.meta.get('Poster', '')
        global_plot = self.meta.get('Plot', '')
        
        # Daca posterul global contine 'recente.png' sau 'search.png', inseamna ca suntem in meniu generic
        # Daca e un link HTTP real (TMDb), inseamna ca suntem intr-o cautare de film
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

                quality   = self._detect_quality(clean, info) if not is_next else ''
                highlight = QUALITY_COLORS.get(quality, QUALITY_COLORS['SD']) if not is_next else 'FFFFFFFF'
                icon      = QUALITY_ICONS.get(quality, '') if not is_next else ''

                tracker_tags = self._extract_tracker_tags(raw_name)
                seeds  = self._extract_seeds(raw_name)
# Extragem marimea si o formatam daca e nevoie
                raw_size = self._extract_size(clean, info)
                size = self._format_size(raw_size)
                codec  = self._extract_codec(clean)
                source = self._extract_source(clean)
                hdr    = self._extract_hdr(clean)
                audio  = self._extract_audio(clean)

                # --- CULORI CODECURI ---
                if codec:
                    cod_up = codec.upper()
                    if 'HEVC' in cod_up or '265' in cod_up: codec = '[B][COLOR FF008080]HEVC[/COLOR][/B]'
                    elif '264' in cod_up: codec = '[B][COLOR FFA52A2A]x264[/COLOR][/B]'

                # --- CULORI SURSE ---
                if source:
                    src_up = source.upper()
                    if 'REMUX' in src_up: source = '[COLOR FFFF0000][B]REMUX[/B][/COLOR]'
                    elif 'BLURAY' in src_up or 'BLU-RAY' in src_up: source = '[COLOR FF00BFFF][B]BluRay[/B][/COLOR]'
                    elif 'WEBRIP' in src_up: source = '[COLOR FF20B2AA][B]WebRip[/B][/COLOR]'
                    elif 'WEB' in src_up: source = '[COLOR FF00FA9A][B]WEB-DL[/B][/COLOR]'

                # --- CULORI AUDIO ---
                if audio:
                    aud_up = audio.upper()
                    if 'ATMOS' in aud_up: audio = '[COLOR FFFF4500][B]Atmos[/B][/COLOR]'
                    elif 'DTS' in aud_up: audio = '[COLOR FF1E90FF][B]%s[/B][/COLOR]' % audio
                    elif 'EAC3' in aud_up or 'DD+' in aud_up: audio = '[COLOR FFADFF2F][B]DD+[/B][/COLOR]'
                    elif 'AC3' in aud_up: audio = '[COLOR FF7CFC00][B]AC3[/B][/COLOR]'
                    elif 'AAC' in aud_up: 
                        if '5.1' in aud_up: audio = '[COLOR FFFFFFFF][B]AAC 5.1[/B][/COLOR]'
                        else: audio = '[COLOR FFFFFFFF][B]AAC[/B][/COLOR]'
                    elif '5.1' in aud_up: audio = '[COLOR FF7CFC00][B]5.1[/B][/COLOR]'

                info_parts = []
                # Adaugam sursa originala pentru toti providerii JSON
                if site_id in ['torrentio', 'meteor', 'comet', 'mediafusion', 'heartive']:
                    orig_prov = info.get('Genre')
                    if orig_prov: info_parts.append('[COLOR cyan][B]%s[/B][/COLOR]' % orig_prov)
                
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
                
                # Preluam iconita site-ului din addon (pentru stanga)
                prov_icon = os.path.join(xbmcaddon.Addon('plugin.video.romanianpack').getAddonInfo('path'), 'resources', 'media', site_id + '.png')

                if is_next:
                    # BUTON NEXT
                    display_name = '[COLOR orange]► %s[/COLOR]' % display_name.replace('► ', '')
                    highlight = 'FFFFA500' 
                    info_line = 'Afișează restul de rezultate disponibile...'
                    site_nm = '' 
                    # Sageata in stanga
                    li.setProperty('mrsp.provider_icon', os.path.join(xbmcaddon.Addon('plugin.video.romanianpack').getAddonInfo('path'), 'resources', 'media', 'next.png'))
                    li.setProperty('mrsp.is_next', 'true')
                    li.setProperty('mrsp.poster', '')
                    li.setProperty('mrsp.plot', '')
                else:
                    # ITEM NORMAL
                    li.setProperty('mrsp.provider_icon', prov_icon)
                    
                    if is_search_mode:
                        # CAUTARE: Folosim Posterul si Plotul Global (TMDb) pentru aspect unitar
                        li.setProperty('mrsp.poster', global_poster)
                        li.setProperty('mrsp.plot', global_plot)
                    else:
                        # RECENTE: Folosim Posterul itemului. Daca nu are, punem iconita site-ului.
                        poster_item = info.get('Poster')
                        if poster_item:
                            li.setProperty('mrsp.poster', poster_item)
                        else:
                            li.setProperty('mrsp.poster', prov_icon)
                        
                        li.setProperty('mrsp.plot', info.get('Plot', ''))

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
        # 1. Căutăm întâi în nume (cea mai sigură metodă)
        for pattern, quality in QUALITY_PATTERNS:
            if re.search(pattern, name, re.I):
                return quality
        
        # 2. Dacă nu găsim în nume, căutăm în metadatele de categorie (Genre)
        if info and isinstance(info, dict):
            # Combinăm Genre și Plot pentru o scanare completă
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
        # Caută formatul [S/L: 123] sau [S: 123]
        m = re.search(r'\[S(?:/L)?:\s*(\d[\d,.]*)', name)
        if m:
            return m.group(1).replace(',', '')
            
        # Fallback pentru alte formate (Seeds: 123)
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
        # Folosim puncte si spatii ca delimitatori pentru a prinde formatele lipite
        name_normalized = name.replace('.', ' ').replace('_', ' ')
        found_tags = []
        
        for pattern, label in AUDIO_PATTERNS:
            if re.search(pattern, name_normalized, re.I):
                # Daca am gasit deja un tag mai specific (ex: DDP 5.1), nu mai adaugam "5.1" simplu
                if not any(label in t for t in found_tags):
                    found_tags.append(label)
        
        # Returnam toate tagurile gasite (ex: "DDP 5.1") sau primul gasit
        return found_tags[0] if found_tags else ''

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

    def _get_fav_menu_item(self, base_url, link, clean_title, data_str):
        """Returnează dinamic Adaugă sau Șterge din Favorite, în funcție de stare."""
        is_fav = False
        try:
            from resources.functions import get_fav
            if get_fav(link):
                is_fav = True
        except: pass
        
        if is_fav:
            return ("Șterge din [B][COLOR orange]Torrente Favorite[/COLOR][/B]", "FAV_DELETE|%s" % link)
        else:
            return ("Adaugă la [B][COLOR orange]Torrente Favorite[/COLOR][/B]", "FAV_ADD|%s|%s|%s" % (link, clean_title, data_str))

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
        import time
        action_id = action.getId()
        
        # 1. Butoane de Back / Close / Escape
        if action_id in (9, 10, 13, 92, 110):
            self.selected = None
            self.close()
            
        # 2. Butoane de Context Menu (Tasta C, Click-Dreapta, Apăsare Lungă)
        elif action_id in (117, 101):
            # === FIX MENIU DUBLU ===
            # Verificam daca a trecut mai putin de jumatate de secunda de la INCHIDEREA ultimului meniu
            if hasattr(self, 'menu_closed_time') and time.time() - self.menu_closed_time < 0.5:
                return
            
            try:
                item = self.getControl(2000).getSelectedItem()
                if not item: return
                
                # Nu deschidem meniu pe butonul de Paginare
                if item.getProperty('mrsp.is_next') == 'true': return
                
                data_str = item.getProperty('mrsp.data')
                if not data_str: return
                
                data = json.loads(data_str)
                site = data.get('site', '')
                
                # === FIX PENTRU EXTRAGERE LINK ===
                link = data.get('link') or data.get('legatura') or data.get('url') or ''
                if not link: return
                
                info = data.get('info', {})
                clean_title = info.get('Title', data.get('nume', ''))
                
                # Extragem ID-urile pentru butoanele de MetaInfo
                imdb_id = info.get('imdb_id') or info.get('imdb') or ''
                
                try:
                    from urllib import quote_plus as quote
                except ImportError:
                    from urllib.parse import quote_plus as quote
                    
                info_str = quote(json.dumps(info))
                base_url = "plugin://plugin.video.romanianpack/"
                
                # AM INLOCUIT action=openTorrent cu action=OpenT
                menu = [
                    ("MetaInfo IMDb", "RunPlugin(%s?action=getMeta&getMeta=IMDb&nume=%s&imdb=%s)" % (base_url, quote(clean_title), quote(imdb_id))),
                    ("MetaInfo TMdb", "RunPlugin(%s?action=getMeta&getMeta=TMdb&nume=%s&imdb=%s)" % (base_url, quote(clean_title), quote(imdb_id))),
                    ("[B][COLOR yellow]Caută variante[/COLOR][/B]", "SEARCH_VARIANTS"),
                    self._get_fav_menu_item(base_url, link, clean_title, data_str),
                    ("Marchează ca vizionat", "RunPlugin(%s?action=watched&watched=save&watchedlink=%s&nume=%s&detalii=%s&norefresh=1)" % (base_url, quote(link), quote(clean_title), quote(data_str))),
                    ("Play cu [B][COLOR FF6AFB92]TorrServer[/COLOR][/B]", "RunPlugin(%s?action=OpenT&Tmode=playtorrserver&Turl=%s&Tsite=%s&info=%s)" % (base_url, quote(link), quote(site), info_str)),
                    ("Play cu [B][COLOR orange]MRSP[/COLOR][/B]", "RunPlugin(%s?action=OpenT&Tmode=playmrsp&Turl=%s&Tsite=%s&info=%s)" % (base_url, quote(link), quote(site), info_str)),
                    ("Play cu [B][COLOR gray]Elementum[/COLOR][/B]", "RunPlugin(%s?action=OpenT&Tmode=playelementum&Turl=%s&Tsite=%s&info=%s)" % (base_url, quote(link), quote(site), info_str)),
                    # ("Răsfoire torrent", "RunPlugin(%s?action=OpenT&Tmode=browsetorrent&Turl=%s&Tsite=%s&info=%s)" % (base_url, quote(link), quote(site), info_str)),
                    # ("Descarcă în fundal", "RunPlugin(%s?action=OpenT&Tmode=addtorrenter&Turl=%s&Tsite=%s&info=%s)" % (base_url, quote(link), quote(site), info_str)),
                    # ("Descarcă cu Transmission", "RunPlugin(%s?action=OpenT&Tmode=addtransmission&Turl=%s&Tsite=%s&info=%s)" % (base_url, quote(link), quote(site), info_str)),
                    ("Caută în [B][COLOR red]You[COLOR white]tube[/COLOR][/B]", "RunPlugin(%s?action=YoutubeSearch&url=%s)" % (base_url, quote(clean_title)))
                ]
                
                labels = [m[0] for m in menu]
                dialog = xbmcgui.Dialog()
                
                # Aici Kodi se blocheaza si asteapta ca tu sa alegi ceva din meniu
                ret = dialog.contextmenu(labels)
                
                # Salvam exact secunda in care s-a INCHIS meniul
                self.menu_closed_time = time.time()
                
                # Executarea actiunii alese
                if ret >= 0:
                    action_cmd = menu[ret][1]
                    label_chosen = menu[ret][0]
                    
                    if action_cmd.startswith("FAV_ADD|"):
                        parts = action_cmd.split("|", 3)
                        fav_link = parts[1] if len(parts) > 1 else ''
                        fav_title = parts[2] if len(parts) > 2 else ''
                        fav_data = parts[3] if len(parts) > 3 else ''
                        try:
                            from resources.functions import save_fav
                            _mrsp_icon = os.path.join(xbmcaddon.Addon('plugin.video.romanianpack').getAddonInfo('path'), 'icon.png')
                            save_fav(fav_title, fav_link, fav_data, norefresh='1', silent=True)
                            xbmcgui.Dialog().notification('[B][COLOR FFFDBD01]MRSP Lite[/COLOR][/B]', '[B][COLOR lime]Adăugat la [COLOR orange]Torrente Favorite[/COLOR][/B]', _mrsp_icon, 3000, False)
                        except: pass
                        return
                                        
                    if action_cmd.startswith("FAV_DELETE|"):
                        fav_link = action_cmd.split("|", 1)[1]
                        try:
                            from resources.functions import del_fav
                            _mrsp_icon = os.path.join(xbmcaddon.Addon('plugin.video.romanianpack').getAddonInfo('path'), 'icon.png')
                            del_fav(fav_link, norefresh='1', silent=True)
                            xbmcgui.Dialog().notification('[B][COLOR FFFDBD01]MRSP Lite[/COLOR][/B]', '[B][COLOR red]Șters din [COLOR orange]Torrente Favorite[/COLOR][/B]', _mrsp_icon, 3000, False)
                        except: pass
                        return
                        
                        # Semnalăm refresh-ul
                        data['special_action'] = 'refresh_favorites'
                        self.selected = json.dumps(data)
                        self.close()
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
                        # Daca alegem o actiune de Play, Download sau Youtube, inchidem fereastra
                        if any(x in label_chosen for x in ['Play cu', 'Descarcă', 'Răsfoire']):
                            self.close()
                            # Asteptam putin sa se inchida fereastra grafic
                            xbmc.sleep(200)
                        
                        xbmc.executebuiltin(action_cmd)
                        
            except Exception as e:
                pass

    def get_selected(self):
        return self.selected