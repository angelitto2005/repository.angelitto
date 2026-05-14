import re
import json
# pyrefly: ignore [missing-import]
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

SOURCE_PATTERNS =[
    'Remux', 'BluRay', 'BDRip', 'BRRip',
    'WEB-DL', 'WEBRip', 'WEB',
    'HDTV', 'HDRip', 'DVDRip', 'DVDScr',
    'HDCAM', 'CAM', 'TeleSync', 'TS',
]

HDR_PATTERNS =[
    (r'HDR10\+',                  'HDR10+'),
    (r'HDR10',                    'HDR10'),
    (r'\bHDR\b',                  'HDR'),
    (r'\bSDR\b',                  'SDR'),
    (r'\bHLG\b',                  'HLG'),
    (r'Dolby[.\s]?Vision',        'DV'),
    (r'\b(DV|DoVi)\b',            'DV'),
]

AUDIO_PATTERNS =[
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

# === AIO STREAMS DICTS ===
AIO_ADDON_COLORS = {
    'comet':          'FFFF4500',
    'mediafusion':    'FFFF4500',
    'torrentio':      'FF7B68EE',
    'jackettio':      'FF32CD32',
    'orionoid':       'FFFFA500',
    'easynews':       'FF00CED1',
    'debridio':       'FFEE82EE',
    'annatar':        'FFFFD700',
    'zilean':         'FF20B2AA',
    'stremio-gdrive': 'FF87CEEB',
    'knightcrawler':  'FFDDA0DD',
    'torbox':         'FF00FA9A',
    'peeratar':       'FFFF69B4',
    'heartive':       'FFFF1493',
    'meteor':         'FFFF4500',
    'tamilmv':        'FF32CD32',
    'yts':            'FF32CD32',
    'torrent9':       'FF32CD32',
    'besttorrents':   'FF32CD32',
    'wolfmax4k':      'FF32CD32',
    'uindex':         'FF32CD32',
    'bludv':          'FF32CD32',
    'cinecalidad':    'FF32CD32',
    'comando':        'FF32CD32',
    'bt4g':           'FF32CD32',
    'knaben':         'FF32CD32',
    'bitmagnet':      'FF32CD32',
    'limetorrents':   'FF32CD32',
    'ilcorsaronero':  'FF32CD32',
    'eztv':           'FF228B22',
    'kickass':        'FF8B4513',
    '1337x':          'FFD2691E',
    'rutracker':      'red',
    'rutor':          'red',
    'tpb':            'red',
    'piratebay+':     'red',
    'thepiratebay':   'red',
    'the pirate bay': 'red',
    'torrentgalaxy':  'red',
    'therarbg':       'red',
    'torrentsdb':     'red',
    'stremthru torz': 'red',
    'nyaa':           'FFDC143C',
    'webstreamr':     'FF7B68EE',
    'nuvio':     'FF7B68EE',
    'sootio':     'lightskyblue',
    'hdhub':      'FF00FA9A',
    'yflix':      'FF00FA9A',
    'primesrcme': 'FF00BFFF',
    'vaplayer': 'FF00FA9A'
}

DEBRID_SHORTNAMES = {
    'realdebrid': 'RD',
    'alldebrid': 'AD',
    'premiumize': 'PM',
    'torbox': 'TB',
    'offcloud': 'OC',
    'easydebrid': 'ED',
    'easynews': 'EN',
    'debrider': 'DB',
    'debridlink': 'DL',
    'putio': 'PU'
}

from resources.lib.config import ADDON, ADDON_PATH

class SourcesInfo(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        self.item = kwargs.get('item')
        self.meta = kwargs.get('meta', {})

    def onInit(self):
        # Proprietăți de bază
        # Folosim numele complet al release-ului (torrent-ului)
        name = self.item.getProperty('tmdbmovies.name')
        self.setProperty('tmdbmovies.release_name', name)
        
        # Logica specială pentru Provider/Indexer (AIO / Stremio)
        provider = self.item.getProperty('tmdbmovies.provider')
        addon = self.item.getProperty('tmdbmovies.addon')
        indexer = self.item.getProperty('tmdbmovies.indexer')
        server = self.item.getProperty('tmdbmovies.server')
        
        if addon and addon.lower() != 'none' and addon != '':
            self.setProperty('tmdbmovies.provider', addon)
            self.setProperty('tmdbmovies.server_label', provider) # aiostreams
        else:
            self.setProperty('tmdbmovies.provider', provider)
            self.setProperty('tmdbmovies.server_label', server)
            
        self.setProperty('tmdbmovies.size', self.item.getProperty('tmdbmovies.size'))
        self.setProperty('tmdbmovies.quality', self.item.getProperty('tmdbmovies.quality'))
        self.setProperty('tmdbmovies.quality_icon', self.item.getProperty('tmdbmovies.quality_icon'))
        self.setProperty('tmdbmovies.tags', self.item.getProperty('tmdbmovies.tags'))
        self.setProperty('tmdbmovies.highlight', self.item.getProperty('tmdbmovies.highlight'))
        
        # Proprietăți noi: Status și Tip Stream
        status = self.item.getProperty('tmdbmovies.status')
        stream_type = self.item.getProperty('tmdbmovies.stream_type')
        
        # Dacă e HTTP, simplificăm statusul
        if stream_type and 'HTTP' in stream_type.upper():
            self.setProperty('tmdbmovies.status_clean', '[COLOR cyan]Direct HTTP Stream[/COLOR]')
        else:
            self.setProperty('tmdbmovies.status_clean', f"{stream_type} | {status}")
        
        # Imagini
        poster = self.item.getProperty('tmdbmovies.poster') or self.meta.get('poster', '')
        fanart = self.item.getProperty('tmdbmovies.fanart') or self.meta.get('fanart', '')
        self.setProperty('tmdbmovies.poster', poster)
        self.setProperty('tmdbmovies.fanart', fanart)
        
        # Info adiționale
        self.setProperty('tmdbmovies.group', self.item.getProperty('tmdbmovies.group'))
        self.setProperty('tmdbmovies.codec', self.item.getProperty('tmdbmovies.codec'))
        self.setProperty('tmdbmovies.audio', self.item.getProperty('tmdbmovies.audio'))
        self.setProperty('tmdbmovies.lang', self.item.getProperty('tmdbmovies.lang'))
        self.setProperty('tmdbmovies.indexer', indexer)
        self.setProperty('tmdbmovies.year', str(self.meta.get('year', '')))
        self.setProperty('tmdbmovies.rating', str(self.meta.get('rating', '')))

    def onAction(self, action):
        if action.getId() in (9, 10, 13, 92, 110, 117, 101):
            self.close()

    def onClick(self, controlId):
        self.close()


class ResultsWindow(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        self.results = kwargs.get('results', [])
        self.all_results = list(self.results)
        self.meta = kwargs.get('meta', {})
        self.selected = None
        self.filter_applied = False
        self.last_cm_time = 0
        self.is_info_open = False

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
        found =[]
        for pattern, label in HDR_PATTERNS:
            if re.search(pattern, name, re.I):
                if label not in found: found.append(label)
        return found

    def _extract_audio(self, name):
        name_normalized = name.replace('.', ' ').replace('_', ' ')
        found_tags =[]
        for pattern, label in AUDIO_PATTERNS:
            if re.search(pattern, name_normalized, re.I):
                if not any(label in t or t in label for t in found_tags):
                    found_tags.append(label)
        return found_tags

    def _set_window_properties(self):
        import xbmcaddon
        import os
        import xbmc # <--- ADĂUGAT
        
        # --- LOGARE PENTRU DEBUG CLEARLOGO ȘI PLOT ---
        log_title = self.meta.get('title', 'Unknown')
        log_logo = self.meta.get('clearlogo', 'LIPSESTE!')
        xbmc.log(f"[TMDb Movies] [RESULTS-WINDOW] Incarcam UI pentru: {log_title} | Logo: {log_logo}", xbmc.LOGINFO)
        # ----------------------------------------------
        
        self.setProperty('tmdbmovies.title', self.meta.get('title', 'Unknown'))
        self.setProperty('tmdbmovies.poster', self.meta.get('poster', ''))
        self.setProperty('tmdbmovies.plot', self.meta.get('plot', ''))
        self.setProperty('tmdbmovies.fanart', self.meta.get('fanart', ''))
        self.setProperty('tmdbmovies.clearlogo', self.meta.get('clearlogo', ''))
        self.setProperty('tmdbmovies.total_results', str(len(self.results)))

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

        try:
            imdb_id = self.meta.get('imdb_id')
            tmdb_id = self.meta.get('tmdb_id')
            season = self.meta.get('season')
            episode = self.meta.get('episode')

            from resources.lib.os_checker import check_ro_subs_bg
            check_ro_subs_bg(imdb_id=imdb_id, tmdb_id=tmdb_id, season=season, episode=episode)
        except: pass

        season = self.meta.get('season')
        episode = self.meta.get('episode')
        if season and episode:
            self.setProperty('tmdbmovies.episode_label', f"S{int(season):02d}E{int(episode):02d}")
        else:
            self.setProperty('tmdbmovies.episode_label', '')

    def _populate_list(self):
        items =[]
        global_poster = self.meta.get('poster', '')
        global_plot = self.meta.get('plot', '')
        
        import xbmcaddon
        try:
            theme_opt = xbmcaddon.Addon('plugin.video.tmdbmovies').getSetting('pov_theme')
        except:
            theme_opt = '0'
            
        is_simple = theme_opt == '1'
        is_mono = theme_opt == '2'
        is_custom = theme_opt == '3'
        
        try: show_indexers = xbmcaddon.Addon('plugin.video.tmdbmovies').getSetting('show_aio_indexers') != 'false'
        except: show_indexers = True
        
        try: show_seeders = xbmcaddon.Addon('plugin.video.tmdbmovies').getSetting('show_seeders') != 'false'
        except: show_seeders = True
        
        CUSTOM_COLORS = [
            "FFF0F8FF", "FFFAEBD7", "FF00FFFF", "FF7FFFD4", "FFF0FFFF", "FFF5F5DC", "FFFFE4C4", "FF000000",
            "FFFFEBCD", "FF0000FF", "FF8A2BE2", "FFA52A2A", "FFDEB887", "FF5F9EA0", "FF7FFF00", "FFD2691E",
            "FFFF7F50", "FF6495ED", "FFFFF8DC", "FFDC143C", "FF00FFFF", "FF00008B", "FF008B8B", "FFB8860B",
            "FFA9A9A9", "FF006400", "FFBDB76B", "FF8B008B", "FF556B2F", "FFFF8C00", "FF9932CC", "FF8B0000",
            "FFE9967A", "FF8FBC8F", "FF483D8B", "FF2F4F4F", "FF00CED1", "FF9400D3", "FFFF1493", "FF00BFFF",
            "FF696969", "FF1E90FF", "FFB22222", "FFFFFAF0", "FF228B22", "FFFF00FF", "FFDCDCDC", "FFF8F8FF",
            "FFFFD700", "FFDAA520", "FF808080", "FF008000", "FFADFF2F", "FFF0FFF0", "FFFF69B4", "FFCD5C5C",
            "FF4B0082", "FFFFFFF0", "FFF0E68C", "FFE6E6FA", "FFFFF0F5", "FF7CFC00", "FFFFFACD", "FFADD8E6",
            "FFF08080", "FFE0FFFF", "FFFAFAD2", "FFD3D3D3", "FF90EE90", "FFFFB6C1", "FFFFA07A", "FF20B2AA",
            "FF87CEFA", "FF778899", "FFB0C4DE", "FFFFFFE0", "FF00FF00", "FF32CD32", "FFFAF0E6", "FFFF00FF",
            "FF800000", "FF66CDAA", "FF0000CD", "FFBA55D3", "FF9370DB", "FF3CB371", "FF7B68EE", "FF00FA9A",
            "FF48D1CC", "FFC71585", "FF191970", "FFF5FFFA", "FFFFE4E1", "FFFFE4B5", "FFFFDEAD", "FF000080",
            "FFFDF5E6", "FF808000", "FF6B8E23", "FFFFA500", "FFFF4500", "FFDA70D6", "FFEEE8AA", "FF98FB98",
            "FFAFEEEE", "FFDB7093", "FFFFEFD5", "FFFFDAB9", "FFCD853F", "FFFFC0CB", "FFDDA0DD", "FFB0E0E6",
            "FF800080", "FFFF0000", "FFBC8F8F", "FF4169E1", "FF8B4513", "FFFA8072", "FFF4A460", "FF2E8B57",
            "FFFFF5EE", "FFA0522D", "FFC0C0C0", "FF87CEEB", "FF6A5ACD", "FF708090", "FFFFFAFA", "FF00FF7F",
            "FF4682B4", "FFD2B48C", "FF008080", "FFD8BFD8", "FFFF6347", "FF40E0D0", "FFEE82EE", "FFF5DEB3",
            "FFFFFFFF", "FFF5F5F5", "FFFFFF00", "FF9ACD32"
        ]
        
        # --- FUNCȚIE NOUĂ PENTRU EXTRAGEREA CULORII ---
        def _get_hex_color(setting_name, default_idx):
            val = xbmcaddon.Addon('plugin.video.tmdbmovies').getSetting(setting_name)
            if not val: return CUSTOM_COLORS[default_idx]
            if val.startswith('[COLOR '): return val[7:15] # Extrage direct "FF7FFF00" din text
            if val.isdigit():
                try: return CUSTOM_COLORS[int(val)]
                except: return CUSTOM_COLORS[default_idx]
            return CUSTOM_COLORS[default_idx]
        # ----------------------------------------------
        
        for idx, res in enumerate(self.results):
            info = res.get('info', {})
            quality = info.get('quality', 'SD')
            size = info.get('size', '')
            provider = info.get('provider', 'Unknown')
            source_provider = info.get('source_provider', '')
            server = info.get('server', '')
            
            release_group = res.get('raw_stream_data', {}).get('releaseGroup', '')
            if not release_group:
                release_group = info.get('releaseGroup', '')
            
            raw_name = res['name']
            provider_id = res.get('raw_stream_data', {}).get('provider_id', '') or res.get('provider_id', '')
            
            is_aio = provider_id in ['aiostreams']
            is_stremio_addon = provider_id in ['torrentio', 'mediafusion', 'comet', 'meteor']
            
            # --- ATRIBUIREA CULORILOR PENTRU FUNDAL ---
            if quality == '4K': 
                if is_custom: base_color = _get_hex_color('color_4k', 80)
                else: base_color = 'FFFF00FF'
            elif quality == '1080p': 
                if is_custom: base_color = _get_hex_color('color_1080p', 60)
                else: base_color = 'FF7CFC00' # FF7CFC00 sau cyan
            elif quality == '720p': 
                if is_custom: base_color = _get_hex_color('color_720p', 84)
                else: base_color = 'FFBA55D3'
            else: 
                if is_custom: base_color = _get_hex_color('color_sd', 41)
                else: base_color = 'FF1E90FF'
                
            hl_focus = '80' + base_color[2:]
            
            if is_simple or is_mono:
                hl_unfocus = 'FFCCCCCC' 
                hl_dim = '25FFFFFF'     
            else:
                # Și "Custom" și "Multicolor" au fundalul colorat
                hl_unfocus = base_color
                hl_dim = '30' + base_color[2:]

# -------------------------------------------------------------
            # LOGICA DEBRID (Coloana stângă sub Calitate)
            # -------------------------------------------------------------
            debrid_label = 'HTTP'
            addon_name_clean = ''
            
            if is_aio or is_stremio_addon:
                addon_name_raw = info.get('addon', '')
                addon_name_lower = addon_name_raw.lower()
                
                # Identificăm excepțiile pentru HTTP streams din AIO
                if 'webstreamr' in addon_name_lower: addon_name_clean = 'WebStreamr'
                elif 'nuvio' in addon_name_lower: addon_name_clean = 'Nuvio'
                elif 'sootio' in addon_name_lower or 'sooti' in addon_name_lower: addon_name_clean = 'Sootio'
                
                # Dacă e o excepție, punem direct numele în stânga și ocolim logica de ++
                if addon_name_clean:
                    debrid_label = addon_name_clean
                else:
                    debrid_service = info.get('debrid_service', '').lower().replace('-', '').replace('.', '')
                    
                    # Curățăm "None" în caz că vine de la AIO
                    if debrid_service == 'none' or not debrid_service:
                        base_name = 'HTTP'
                    else:
                        base_name = DEBRID_SHORTNAMES.get(debrid_service, debrid_service[:2].upper())
                    
                    if info.get('is_cloud'):
                        debrid_label = f"{base_name}++"
                    elif info.get('is_cached'):
                        debrid_label = f"{base_name}+"
                    else:
                        debrid_label = base_name

            # -------------------------------------------------------------
            # CONSTRUIRE INFO LINE (Rândul 2)
            # -------------------------------------------------------------
            parts =[]
            
            if size and size != "N/A": 
                parts.append(f"[COLOR lime][B]{size}[/B][/COLOR]")
            
            # Formătare Addon și Indexer (Pentru AIO și Stremio Addons) vs HTTP Normal
            if is_aio or is_stremio_addon:
                addon_name = info.get('addon', '')
                indexer = info.get('indexer', '')
                
                if addon_name and addon_name.lower() != 'none':
                    if addon_name.lower() not in['webstreamr', 'nuvio', 'sootio', 'sooti']:
                        # --- AICI APLICĂM CULOAREA CERUTĂ DE TINE PENTRU NOII PROVIDERI ---
                        if is_stremio_addon:
                            addon_color = 'FFCCCCFF' 
                        else:
                            addon_color = AIO_ADDON_COLORS.get(addon_name.lower(), 'FF00BFFF')
                            
                        parts.append(f"[COLOR {addon_color}][B]{addon_name}[/B][/COLOR]")
                
                if show_indexers and indexer and indexer.lower() != 'none':
                    idx_display = indexer
                    if addon_name and idx_display.lower().startswith(addon_name.lower()):
                        idx_display = idx_display[len(addon_name):].strip(' |')
                    if idx_display:
                        parts.append(f"[COLOR lightskyblue][B]{idx_display}[/B][/COLOR]")
                        
            if not (is_aio or is_stremio_addon):
                # HTTP Normal
                if source_provider and source_provider.lower() != provider.lower():
                    parts.append(f"[COLOR red][B]{provider} [COLOR FF7B68EE]{source_provider}[/B][/COLOR]")
                else:
                    parts.append(f"[COLOR red][B]{provider}[/B][/COLOR]")
                    
                if server and server.lower() not in [provider.lower(), source_provider.lower()]:
                    parts.append(f"[COLOR FF7B68EE][B]{server}[/B][/COLOR]")

            if release_group:
                parts.append(f"[COLOR FFFF69B4][B]{release_group}[/B][/COLOR]")
                
            # Etichete Video și Audio
            codec = self._extract_codec(raw_name)
            source = self._extract_source(raw_name)
            hdr_tags = self._extract_hdr(raw_name)
            audio_tags = self._extract_audio(raw_name)
            
            # Sistem de dedublare inteligentă
            added_tags_normalized = []
            
            def add_tag(tag, color=None, bold=True):
                if not tag: return
                clean_tag = re.sub(r'\[/?COLOR.*?\]', '', tag).strip().upper()
                clean_tag = clean_tag.replace('[B]', '').replace('[/B]', '')
                if clean_tag in added_tags_normalized: return
                for existing in added_tags_normalized:
                    if clean_tag in existing or existing in clean_tag: return
                added_tags_normalized.append(clean_tag)
                
                final_tag = tag
                if bold and '[B]' not in final_tag: final_tag = f"[B]{final_tag}[/B]"
                if color and '[COLOR' not in final_tag: final_tag = f"[COLOR {color}]{final_tag}[/COLOR]"
                parts.append(final_tag)

            if source:
                src_up = source.upper()
                if 'REMUX' in src_up: add_tag('REMUX', 'FFFF0000')
                elif 'BLURAY' in src_up or 'BLU-RAY' in src_up: add_tag('BluRay', 'FF00BFFF')
                elif 'WEBRIP' in src_up: add_tag('WebRip', 'FF00FA9A')
                elif 'WEB' in src_up: add_tag('WEB-DL', 'FF00FA9A')
                else: add_tag(source)

            if codec:
                cod_up = codec.upper()
                if 'HEVC' in cod_up or '265' in cod_up: add_tag('HEVC', 'red')
                elif '264' in cod_up: add_tag('x264', 'red')
                else: add_tag(codec)

            for htag in hdr_tags:
                add_tag(htag, 'FFFFCC00')

            for atag in audio_tags:
                aud_up = atag.upper()
                color = 'FF7CFC00'
                if 'ATMOS' in aud_up: color = 'FFFF4500'
                elif 'TRUEHD' in aud_up: color = 'FFFF4500'
                elif 'DTS' in aud_up: color = 'FF1E90FF'
                elif 'DDP' in aud_up or 'DD+' in aud_up or 'EAC' in aud_up: color = 'FFADFF2F'
                elif 'AC3' in aud_up: color = 'FF7CFC00'
                elif 'AAC' in aud_up: color = 'FFFFFFFF'
                elif 'FLAC' in aud_up: color = 'FF00CED1'
                add_tag(atag, color)
            
            scraper_tags = info.get('tags',[])
            for t in scraper_tags: add_tag(t, 'gray', bold=False)
                    
            # --- Adaugare Seederi (MEREU LA FINALUL RÂNDULUI 2) ---
            if show_seeders:
                seeders = 0
                raw_stream = res.get('raw_stream_data', {})
                
                if 'seeders' in raw_stream:
                    seeders = raw_stream.get('seeders', 0)
                elif isinstance(raw_stream.get('info'), dict) and 'seeders' in raw_stream['info']:
                    seeders = raw_stream['info'].get('seeders', 0)
                    
                if not seeders:
                    m = re.search(r'(?:👤|👥|S:)\s*(\d+)', raw_name, re.I)
                    if m: seeders = int(m.group(1))
                    
                if seeders and str(seeders) != '0':
                    parts.append(f"[COLOR FF87CEEB][B]S: {seeders}[/B][/COLOR]")
            # ------------------------------------------------------
                
            info_line_colored = " | ".join(parts)
            info_line_white = re.sub(r'\[/?COLOR.*?\]', '', info_line_colored)
            
            # Dacă e Simplu, Mono sau Custom, folosim text curat (alb/gri) când NU are focus
            if is_simple or is_mono or is_custom:
                info_line_unfocus = info_line_white
            else:
                info_line_unfocus = info_line_colored
            
            # STABILIM CULOAREA TITLULUI ȘI TEXTULUI LA FOCUS
            if is_mono or is_custom:
                # EXACT CA LA MONO - Doar alb și gri deschis
                info_line_focus = info_line_white
                title_color_focus = 'FFCCCCFF' # Gri-ul simplu
            else:
                # MULTICOLOR
                info_line_focus = info_line_colored
                title_color_focus = 'FFCCCCFF' # FFFFFF00 Galbenul original strălucitor FFCCCCFF silver

            li = xbmcgui.ListItem(res['name'])
            
            li.setProperty('tmdbmovies.count', f"{idx+1}.")
            li.setProperty('tmdbmovies.quality', quality)
            li.setProperty('tmdbmovies.debrid', debrid_label)  
            li.setProperty('tmdbmovies.highlight', base_color)
            li.setProperty('tmdbmovies.hl_unfocus', hl_unfocus)
            li.setProperty('tmdbmovies.highlight_dim', hl_dim)
            li.setProperty('tmdbmovies.highlight_focus', hl_focus)
            li.setProperty('tmdbmovies.name', res['name'])
            li.setProperty('tmdbmovies.title_color_focus', title_color_focus)
            li.setProperty('tmdbmovies.info_line_unfocus', info_line_unfocus)
            li.setProperty('tmdbmovies.info_line_focus', info_line_focus)
            li.setProperty('tmdbmovies.quality_icon', QUALITY_ICONS.get(quality, 'flagsd.png'))
            
            li.setProperty('tmdbmovies.poster', global_poster)
            li.setProperty('tmdbmovies.plot', global_plot)
            li.setProperty('tmdbmovies.fanart', self.meta.get('fanart', ''))
            li.setProperty('tmdbmovies.provider', provider)
            li.setProperty('tmdbmovies.server', server)
            li.setProperty('tmdbmovies.size', size)
            li.setProperty('tmdbmovies.group', release_group)
            li.setProperty('tmdbmovies.codec', codec)
            li.setProperty('tmdbmovies.audio', ', '.join(audio_tags))
            li.setProperty('tmdbmovies.lang', ', '.join(info.get('languages', [])))
            li.setProperty('tmdbmovies.addon', info.get('addon', ''))
            li.setProperty('tmdbmovies.indexer', info.get('indexer', '')) # Ignorăm setarea de hide pentru Info
            
            # Status și Tip
            is_cached = info.get('is_cached', False)
            li.setProperty('tmdbmovies.status', '[COLOR lime]Cached[/COLOR]' if is_cached else '[COLOR orange]Not Cached[/COLOR]')
            li.setProperty('tmdbmovies.stream_type', '[COLOR cyan]AIO Stream[/COLOR]' if is_aio or is_stremio_addon else 'Direct Stream')
            
            li.setProperty('tmdbmovies.tags', ', '.join(info.get('tags', [])))
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
            if self.filter_applied:
                self.clear_filter()
                return
            self.selected = None
            self.close()
        elif action_id in (117, 101):
            import time
            if time.time() - self.last_cm_time < 0.5:
                return
            self.handle_context_menu()
            self.last_cm_time = time.time()

    def handle_context_menu(self):
        try:
            ctrl = self.getControl(2000)
            item = ctrl.getSelectedItem()
            if not item: return
            
            raw_data = item.getProperty('tmdbmovies.data')
            if not raw_data: return
            stream_data = json.loads(raw_data)
            
            tmdb_id = str(self.meta.get('tmdb_id', ''))
            season = self.meta.get('season')
            episode = self.meta.get('episode')
            c_type = 'tv' if season and episode else 'movie'
            
            from resources.lib.downloader import get_dl_id, start_download_thread
            import xbmcgui
            
            unique_id = get_dl_id(tmdb_id, c_type, season, episode)
            window = xbmcgui.Window(10000)
            is_downloading = window.getProperty(unique_id) == 'active'
            
            options = []
            options.append("[B][COLOR FFFDBD01]Info Sursa[/COLOR][/B]")
            if is_downloading:
                options.append("[B][COLOR red]Stop Download[/COLOR][/B]")
            else:
                options.append("[B][COLOR cyan]Download Source[/COLOR][/B]")

            options.append("[B]SHOW 4K ONLY[/B]")
            options.append("[B]SHOW 1080P ONLY[/B]")
            options.append("[B]SHOW 720P ONLY[/B]")
            options.append("[B]SHOW SD ONLY[/B]")
            options.append("[B]Filter by HDR/DV[/B]")
            options.append("[B]Filter by SDR[/B]")
            options.append("[B]Filter by Provider[/B]")
            options.append("[B]Filter by Title[/B]")
            options.append("[B]Filter by Info[/B]")
                
            ret = xbmcgui.Dialog().contextmenu(options)
            if ret == 0:
                if self.is_info_open: return
                
                import xbmc
                import time
                # Blocăm imediat orice altă încercare (debounce preventiv pentru mouse)
                self.last_cm_time = time.time() + 2.0
                self.is_info_open = True
                
                # Închidem meniul contextual forțat
                xbmc.executebuiltin('Dialog.Close(contextmenu, true)')
                xbmc.sleep(400) 
                
                # Deschidem fereastra de Info
                dialog = SourcesInfo('sources_info.xml', ADDON_PATH, 'Default', '1080i', item=item, meta=self.meta)
                dialog.doModal()
                del dialog
                
                self.is_info_open = False
                self.last_cm_time = time.time() + 1.5
                xbmc.executebuiltin('Dialog.Close(contextmenu, true)')
            elif ret == 1:
                # Logica Download
                if is_downloading:
                    window.setProperty(f"{unique_id}_stop", "true")
                    window.clearProperty(unique_id)
                    xbmcgui.Dialog().notification("Download", "Se opreste...", "", 2000, False)
                else:
                    url = stream_data.get('url', '')
                    raw_release_name = stream_data.get('title', '')
                    if not raw_release_name or len(raw_release_name) < 10:
                        raw_release_name = stream_data.get('name', '')
                    
                    if c_type == 'tv':
                        title = self.meta.get('tvshowtitle', self.meta.get('title', ''))
                    else:
                        title = self.meta.get('title', '')
                        
                    year = str(self.meta.get('year', ''))
                    
                    start_download_thread(url, title, year, tmdb_id, c_type, season, episode, release_name=raw_release_name)
            elif ret == 2: self.apply_filter('quality', '4K')
            elif ret == 3: self.apply_filter('quality', '1080p')
            elif ret == 4: self.apply_filter('quality', '720p')
            elif ret == 5: self.apply_filter('quality', 'SD')
            elif ret == 6: self.apply_filter('hdr', True)
            elif ret == 7: self.apply_filter('sdr', True)
            elif ret == 8:
                providers = sorted(list(set([r.get('info', {}).get('provider') for r in self.all_results if r.get('info', {}).get('provider')])))
                if not providers: return
                p_idx = xbmcgui.Dialog().select("Selectează Provider", providers)
                if p_idx >= 0:
                    self.apply_filter('provider', providers[p_idx])
            elif ret == 9:
                keyword = xbmcgui.Dialog().input("Introduceți cuvânt cheie")
                if keyword:
                    self.apply_filter('title', keyword)
            elif ret == 10:
                all_tags = []
                for r in self.all_results:
                    # Colectăm toate tag-urile din info/tags
                    t_list = r.get('info', {}).get('tags', [])
                    if isinstance(t_list, list):
                        all_tags.extend(t_list)
                
                # Eliminăm '7.1' deoarece este considerat junk/incorect
                tags = sorted(list(set([t for t in all_tags if t != '7.1'])))
                if not tags: 
                    xbmcgui.Dialog().notification("Filtru", "Nu s-au găsit tag-uri info!", "", 2000, False)
                    return
                    
                t_idx = xbmcgui.Dialog().select("Filtrare după Info (Tag-uri)", tags)
                if t_idx >= 0:
                    self.apply_filter('info', tags[t_idx])
        except Exception as e:
            import xbmc
            xbmc.log(f"[CM ERROR] {e}", xbmc.LOGERROR)

    def apply_filter(self, filter_type, value):
        import xbmcgui
        if filter_type == 'quality':
            self.results = [r for r in self.all_results if r.get('info', {}).get('quality') == value]
        elif filter_type == 'hdr':
            self.results = [r for r in self.all_results if any(x in ['HDR', 'HDR10', 'HDR10+', 'DV', 'Dolby Vision'] for x in r.get('info', {}).get('tags', []))]
        elif filter_type == 'sdr':
            self.results = [r for r in self.all_results if not any(x in ['HDR', 'HDR10', 'HDR10+', 'DV', 'Dolby Vision'] for x in r.get('info', {}).get('tags', []))]
        elif filter_type == 'provider':
            self.results = [r for r in self.all_results if r.get('info', {}).get('provider') == value]
        elif filter_type == 'title':
            self.results = [r for r in self.all_results if value.lower() in r['name'].lower()]
        elif filter_type == 'info':
            self.results = [r for r in self.all_results if value.lower() in str(r.get('info', {})).lower()]
        
        if not self.results:
            xbmcgui.Dialog().notification("Filtru", "Nu s-au găsit rezultate pentru acest filtru!", "", 2000, False)
            self.results = list(self.all_results)
            return

        self.filter_applied = True
        self.getControl(2000).reset()
        self._populate_list()
        self.setProperty('tmdbmovies.total_results', str(len(self.results)))
        self.setProperty('tmdbmovies.filter_applied', 'true')

    def clear_filter(self):
        self.filter_applied = False
        self.results = list(self.all_results)
        self.getControl(2000).reset()
        self._populate_list()
        self.setProperty('tmdbmovies.total_results', str(len(self.results)))
        self.setProperty('tmdbmovies.filter_applied', 'false')

    def _build_source_info(self, stream_data):
        import re
        from urllib.parse import urlparse, unquote
        
        info = stream_data.get('info', {})
        
        # Extragem Numele
        raw_name = stream_data.get('title', '')
        if not raw_name or len(raw_name) < 5:
            raw_name = stream_data.get('name', '')
            
        clean_dots = raw_name.replace('.', ' ').replace('_', ' ')
        
        # Extragem Calitatea si Marimea CORECT (Aici era bugul cu SD)
        quality = stream_data.get('quality', 'SD')
        size = stream_data.get('size') or info.get('size', '')
        
        lines = []
        lines.append(f"[COLOR FF00CED1]■ FIȘIER:[/COLOR] [B]{raw_name}[/B]")
        lines.append("")
        
        # --- VIDEO ---
        source = self._extract_source(raw_name)
        codec = self._extract_codec(raw_name)
        hdr_tags = self._extract_hdr(raw_name)
        
        vid_parts = [f"[COLOR FF00FA9A]Calitate:[/COLOR] {quality}"]
        if source: vid_parts.append(f"[COLOR FF00FA9A]Sursă:[/COLOR] {source}")
        if codec: vid_parts.append(f"[COLOR FF00FA9A]Codec:[/COLOR] {codec}")
        if hdr_tags: vid_parts.append(f"[COLOR FF00FA9A]HDR:[/COLOR] {' / '.join(hdr_tags)}")
        
        # Varianta (Extended / Unrated etc)
        editions = []
        for tag in ['PROPER', 'REPACK', 'EXTENDED', 'UNCUT', 'DIRECTOR', 'UNRATED']:
            if re.search(rf'(?i)\b{tag}\b', raw_name): editions.append(tag.upper())
        if editions: vid_parts.append(f"[COLOR FF00FA9A]Varianta:[/COLOR] {' '.join(editions)}")
        
        lines.append(" • ".join(vid_parts))
        
        # --- AUDIO ---
        audio_tags = self._extract_audio(raw_name)
        ch_match = re.search(r'(?i)\b(7\.1|5\.1|2\.0|2\.1|1\.0)\b', clean_dots)
        
        aud_parts = []
        if audio_tags: aud_parts.append(f"[COLOR FFFF4500]Audio:[/COLOR] {' / '.join(audio_tags)}")
        if ch_match: aud_parts.append(f"[COLOR FFFF4500]Canale:[/COLOR] {ch_match.group(1)}")
        if aud_parts:
            lines.append(" • ".join(aud_parts))
            
        # --- LIMBI ---
        lang_in_title = []
        for lp, ln in [
            (r'(?i)\bRO(?:manian)?\b', 'Română'),
            (r'(?i)\bEN(?:glish)?\b', 'Engleză'),
            (r'(?i)\bMULTI\b', 'Multi-Audio'),
            (r'(?i)\bDUAL\b', 'Dual-Audio'),
            (r'(?i)\bHUN(?:garian)?\b', 'Maghiară'),
            (r'(?i)\bGER(?:man)?\b|DEUTSCH', 'Germană'),
            (r'(?i)\bFR(?:ench|E)?\b', 'Franceză'),
            (r'(?i)\bITA(?:lian)?\b', 'Italiană'),
            (r'(?i)\bSPA(?:nish)?\b', 'Spaniolă'),
            (r'(?i)\bHIN(?:di)?\b', 'Hindi')
        ]:
            if re.search(lp, clean_dots):
                lang_in_title.append(ln)
        
        if lang_in_title:
            lines.append(f"[COLOR FF87CEEB]Limbă:[/COLOR] {', '.join(lang_in_title)}")
            
        lines.append("")
        
        # --- HOSTING / STATUS ---
        seeders = info.get('seeders', 0)
        host_parts = []
        if size: host_parts.append(f"[COLOR FFFDBD01]Mărime:[/COLOR] {size}")
        if seeders and str(seeders) != '0': host_parts.append(f"[COLOR FFFDBD01]Seederi:[/COLOR] {seeders}")
        
        is_cached = info.get('is_cached', False)
        is_cloud = info.get('is_cloud', False)
        url = str(stream_data.get('url', ''))
        
        if is_cached:
            host_parts.append("[COLOR FFFDBD01]Status:[/COLOR] [COLOR lime]Cached (Debrid)[/COLOR]")
        elif is_cloud:
            host_parts.append("[COLOR FFFDBD01]Status:[/COLOR] [COLOR cyan]Cloud[/COLOR]")
        elif 'magnet:' in url:
            host_parts.append("[COLOR FFFDBD01]Status:[/COLOR] [COLOR red]P2P (Torrent Necachat)[/COLOR]")
        elif url.startswith('http'):
            host_parts.append("[COLOR FFFDBD01]Status:[/COLOR] HTTP Direct Link")
            
        if host_parts:
            lines.append(" • ".join(host_parts))
            
        # --- PROVIDER INFO ---
        addon = info.get('addon', '') or stream_data.get('provider_id', '')
        indexer = info.get('indexer', '') or info.get('server', '')
        debrid = info.get('debrid_service', '')
        
        prov_parts = []
        if addon: prov_parts.append(f"[COLOR gray]Addon:[/COLOR] {addon.capitalize()}")
        if indexer: prov_parts.append(f"[COLOR gray]Tracker:[/COLOR] {indexer.capitalize()}")
        if debrid: prov_parts.append(f"[COLOR gray]Debrid:[/COLOR] {debrid.capitalize()}")
        
        if prov_parts:
            lines.append(" • ".join(prov_parts))
            
        # --- DATE TEHNICE ---
        if url:
            tech_parts = []
            if 'btih:' in url:
                hash_m = re.search(r'btih:([a-fA-F0-9]+)', url)
                if hash_m: tech_parts.append(f"[COLOR gray]Hash:[/COLOR] {hash_m.group(1)[:25]}...")
            elif url.startswith('http'):
                try:
                    domain = urlparse(url.split('|')[0]).netloc
                    tech_parts.append(f"[COLOR gray]Domeniu:[/COLOR] {domain}")
                except: pass
                
            if tech_parts:
                lines.append(" • ".join(tech_parts))
                
        return '\n'.join(lines)


