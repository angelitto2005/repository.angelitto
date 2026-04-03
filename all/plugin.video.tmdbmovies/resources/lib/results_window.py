import re
import json
import xbmcgui

QUALITY_ICONS = {
    '4K':    'flag4k.png',
    '1080p': 'flag1080p.png',
    '720p':  'flag720p.png',
    'SD':    'flagsd.png',
}

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
        except: pass

    def _extract_codec(self, name):
        for pattern, label in CODEC_PATTERNS:
            if re.search(pattern, name, re.I): return label
        return ''

    def _extract_source(self, name):
        for src in SOURCE_PATTERNS:
            m = re.search(src, name, re.I)
            if m: return m.group(0)
        return ''

    def _extract_hdr(self, name):
        found = []
        for pattern, label in HDR_PATTERNS:
            if re.search(pattern, name, re.I):
                if label not in found: found.append(label)
        return found

    def _extract_audio(self, name):
        name_normalized = name.replace('.', ' ').replace('_', ' ')
        found_tags = []
        for pattern, label in AUDIO_PATTERNS:
            if re.search(pattern, name_normalized, re.I):
                if not any(label in t or t in label for t in found_tags):
                    found_tags.append(label)
        return found_tags

    def _set_window_properties(self):
        import xbmcaddon
        import os
        
        self.setProperty('tmdbmovies.title', self.meta.get('title', 'Unknown'))
        self.setProperty('tmdbmovies.poster', self.meta.get('poster', ''))
        self.setProperty('tmdbmovies.plot', self.meta.get('plot', ''))
        self.setProperty('tmdbmovies.fanart', self.meta.get('fanart', ''))
        self.setProperty('tmdbmovies.clearlogo', self.meta.get('clearlogo', ''))
        self.setProperty('tmdbmovies.total_results', str(len(self.results)))

        # Setează calea către steagul României
        try:
            addon_path = xbmcaddon.Addon('plugin.video.tmdbmovies').getAddonInfo('path')
            self.setProperty('tmdbmovies.flag_ro', os.path.join(addon_path, 'resources', 'media', 'ro.png'))
        except:
            self.setProperty('tmdbmovies.flag_ro', '')

        counts = {'4K': 0, '1080p': 0, '720p': 0, 'SD': 0}
        
        for r in self.results:
            quality = r.get('info', {}).get('quality', 'SD')
            if quality in counts:
                counts[quality] += 1
            else:
                counts['SD'] += 1

        self.setProperty('tmdbmovies.count_4k',    str(counts['4K']))
        self.setProperty('tmdbmovies.count_1080p', str(counts['1080p']))
        self.setProperty('tmdbmovies.count_720p',  str(counts['720p']))
        self.setProperty('tmdbmovies.count_sd',    str(counts['SD']))

        # === DECLANSARE VERIFICARE OPENSUBTITLES IN FUNDAL ===
        try:
            imdb_id = self.meta.get('imdb_id')
            tmdb_id = self.meta.get('tmdb_id')
            season = self.meta.get('season')
            episode = self.meta.get('episode')

            from resources.lib.os_checker import check_ro_subs_bg
            check_ro_subs_bg(imdb_id=imdb_id, tmdb_id=tmdb_id, season=season, episode=episode)
        except:
            pass

    def _populate_list(self):
        items = []
        
        global_poster = self.meta.get('poster', '')
        global_plot = self.meta.get('plot', '')
        
        for idx, res in enumerate(self.results):
            info = res.get('info', {})
            quality = info.get('quality', 'SD')
            size = info.get('size', '')
            provider = info.get('provider', 'Unknown')
            source_provider = info.get('source_provider', '')
            server = info.get('server', '')
            
            raw_name = res['name']
            
            # Culori calități (solid = text, dim = fundal neselectat, focus = fundal selectat)
            if quality == '4K': 
                hl = 'FFFF00FF'
                hl_dim = '30FF00FF'    # 30% opacitate magenta
                hl_focus = '80FF00FF'  # 80% opacitate magenta
            elif quality == '1080p': 
                hl = 'FF7CFC00'
                hl_dim = '307CFC00'
                hl_focus = '807CFC00'
            elif quality == '720p': 
                hl = 'FFBA55D3'
                hl_dim = '30BA55D3'
                hl_focus = '80BA55D3'
            else: 
                hl = 'FF1E90FF'
                hl_dim = '301E90FF'
                hl_focus = '801E90FF'

            # Construire Info Line
            parts = []
            if size and size != "N/A": 
                parts.append(f"[COLOR lime][B]{size}[/B][/COLOR]")
            
            if source_provider and source_provider.lower() != provider.lower():
                parts.append(f"[COLOR FFFFD700][B]{provider} ({source_provider})[/B][/COLOR]")
            else:
                parts.append(f"[COLOR FFFFD700][B]{provider}[/B][/COLOR]")
                
            if server and server.lower() not in [provider.lower(), source_provider.lower()]:
                parts.append(f"[COLOR FF00BFFF][B]{server}[/B][/COLOR]")
                
            # Extragere Regex Etichete (Video / Audio)
            codec = self._extract_codec(raw_name)
            source = self._extract_source(raw_name)
            hdr_tags = self._extract_hdr(raw_name)
            audio_tags = self._extract_audio(raw_name)

            if source:
                src_up = source.upper()
                if 'REMUX' in src_up: source = '[COLOR FFFF0000][B]REMUX[/B][/COLOR]'
                elif 'BLURAY' in src_up or 'BLU-RAY' in src_up: source = '[COLOR FF00BFFF][B]BluRay[/B][/COLOR]'
                elif 'WEBRIP' in src_up: source = '[COLOR FF00FA9A][B]WebRip[/B][/COLOR]'
                elif 'WEB' in src_up: source = '[COLOR FF00FA9A][B]WEB-DL[/B][/COLOR]'
                parts.append(source)

            if codec:
                cod_up = codec.upper()
                if 'HEVC' in cod_up or '265' in cod_up: codec = '[B][COLOR red]HEVC[/COLOR][/B]'
                elif '264' in cod_up: codec = '[B][COLOR red]x264[/COLOR][/B]'
                parts.append(codec)

            for htag in hdr_tags:
                parts.append(f"[COLOR FFFFCC00][B]{htag}[/B][/COLOR]")

            for atag in audio_tags:
                aud_up = atag.upper()
                if 'ATMOS' in aud_up: parts.append('[COLOR FFFF4500][B]Atmos[/B][/COLOR]')
                elif 'TRUEHD' in aud_up: parts.append('[COLOR FFFF4500][B]TrueHD[/B][/COLOR]')
                elif 'DTS' in aud_up: parts.append(f'[COLOR FF1E90FF][B]{atag}[/B][/COLOR]')
                elif 'DDP' in aud_up or 'DD+' in aud_up or 'EAC' in aud_up: parts.append(f'[COLOR FFADFF2F][B]{atag}[/B][/COLOR]')
                elif 'AC3' in aud_up: parts.append(f'[COLOR FF7CFC00][B]{atag}[/B][/COLOR]')
                elif 'AAC' in aud_up: parts.append(f'[COLOR FFFFFFFF][B]{atag}[/B][/COLOR]')
                elif 'FLAC' in aud_up: parts.append('[COLOR FF00CED1][B]FLAC[/B][/COLOR]')
                else: parts.append(f'[COLOR FF7CFC00][B]{atag}[/B][/COLOR]')
            
            scraper_tags = info.get('tags', [])
            for t in scraper_tags: 
                if t.upper() not in [x.upper() for x in (hdr_tags + audio_tags)] and t.upper() not in ['REMUX']:
                    parts.append(f"[COLOR gray]{t}[/COLOR]")
                
            info_line = " | ".join(parts)

            li = xbmcgui.ListItem(res['name'])
            
            li.setProperty('tmdbmovies.count', f"{idx+1}.")
            li.setProperty('tmdbmovies.quality', quality)
            li.setProperty('tmdbmovies.debrid', 'HTTP')  
            li.setProperty('tmdbmovies.highlight', hl)
            li.setProperty('tmdbmovies.highlight_dim', hl_dim)       # Fundal opacitate mica
            li.setProperty('tmdbmovies.highlight_focus', hl_focus)   # Fundal opacitate mare
            li.setProperty('tmdbmovies.name', res['name'])
            li.setProperty('tmdbmovies.info_line', info_line)
            li.setProperty('tmdbmovies.quality_icon', QUALITY_ICONS.get(quality, 'flagsd.png'))
            
            # Postere Dinamice (Aici isi trage posterul/plotul curent si il randează instant)
            li.setProperty('tmdbmovies.poster', global_poster)
            li.setProperty('tmdbmovies.plot', global_plot)
            li.setProperty('tmdbmovies.data', json.dumps(res['raw_stream_data']))
            
            items.append(li)
            
        self.getControl(2000).addItems(items)

    def onClick(self, controlId):
        if controlId == 2000:
            item = self.getControl(2000).getSelectedItem()
            if item:
                self.selected = item.getProperty('tmdbmovies.data')
            self.close()

    def onAction(self, action):
        action_id = action.getId()
        if action_id in (9, 10, 13, 92, 110):
            self.selected = None
            self.close()
        elif action_id in (117, 101):
            pass