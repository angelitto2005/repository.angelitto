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
    'sootio':     'blue'
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


class ResultsWindow(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        self.results = kwargs.get('results',[])
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
            provider_id = res.get('raw_stream_data', {}).get('provider_id', '')
            is_aio = (provider_id == 'aiostreams')
            
            if quality == '4K': 
                base_color = 'FFFF00FF'
            elif quality == '1080p': 
                base_color = 'FF7CFC00'
            elif quality == '720p': 
                base_color = 'FFBA55D3'
            else: 
                base_color = 'FF1E90FF'
                
            hl_focus = '80' + base_color[2:]
            
            if is_simple or is_mono:
                hl_unfocus = 'FFCCCCCC' # Gri deschis
                # AICI MODIFICI OPACITATEA FUNDALULUI: 15 e opacitatea (din FF maxim). Poți pune '20FFFFFF' pentru mai deschis
                hl_dim = '25FFFFFF'     
            else:
                hl_unfocus = base_color
                hl_dim = '30' + base_color[2:]

# -------------------------------------------------------------
            # LOGICA DEBRID (Coloana stângă sub Calitate)
            # -------------------------------------------------------------
            debrid_label = 'HTTP'
            addon_name_clean = ''
            
            if is_aio:
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
            
            # Formătare Addon și Indexer (Pentru AIO) vs HTTP Normal
            if is_aio:
                addon_name = info.get('addon', '')
                indexer = info.get('indexer', '')
                
                if addon_name and addon_name.lower() != 'none':
                    # Dacă addon-ul este o excepție, NU îl mai dublăm aici pentru că l-am pus deja în stânga!
                    if addon_name.lower() not in['webstreamr', 'nuvio', 'sootio', 'sooti']:
                        addon_color = AIO_ADDON_COLORS.get(addon_name.lower(), 'FF00BFFF')
                        parts.append(f"[COLOR {addon_color}][B]{addon_name}[/B][/COLOR]")
                
                if indexer and indexer.lower() != 'none':
                    idx_display = indexer
                    if addon_name and idx_display.lower().startswith(addon_name.lower()):
                        idx_display = idx_display[len(addon_name):].strip(' |')
                    if idx_display:
                        parts.append(f"[COLOR blue][B]{idx_display}[/B][/COLOR]")
                        
            if release_group:
                parts.append(f"[COLOR FFFF69B4][B]{release_group}[/B][/COLOR]")

            if not is_aio:
                # HTTP Normal
                if source_provider and source_provider.lower() != provider.lower():
                    parts.append(f"[COLOR red][B]{provider} [COLOR FF7B68EE]{source_provider}[/B][/COLOR]")
                else:
                    parts.append(f"[COLOR red][B]{provider}[/B][/COLOR]")
                    
                if server and server.lower() not in [provider.lower(), source_provider.lower()]:
                    parts.append(f"[COLOR FF7B68EE][B]{server}[/B][/COLOR]")
                
            # Etichete Video și Audio
            codec = self._extract_codec(raw_name)
            source = self._extract_source(raw_name)
            hdr_tags = self._extract_hdr(raw_name)
            audio_tags = self._extract_audio(raw_name)

            if source:
                src_up = source.upper()
                if 'REMUX' in src_up: parts.append('[COLOR FFFF0000][B]REMUX[/B][/COLOR]')
                elif 'BLURAY' in src_up or 'BLU-RAY' in src_up: parts.append('[COLOR FF00BFFF][B]BluRay[/B][/COLOR]')
                elif 'WEBRIP' in src_up: parts.append('[COLOR FF00FA9A][B]WebRip[/B][/COLOR]')
                elif 'WEB' in src_up: parts.append('[COLOR FF00FA9A][B]WEB-DL[/B][/COLOR]')
                else: parts.append(source)

            if codec:
                cod_up = codec.upper()
                if 'HEVC' in cod_up or '265' in cod_up: parts.append('[B][COLOR red]HEVC[/COLOR][/B]')
                elif '264' in cod_up: parts.append('[B][COLOR red]x264[/COLOR][/B]')
                else: parts.append(codec)

            # --- Adaugare Seederi pe randul 2 ---
            seeders = 0
            raw_stream = res.get('raw_stream_data', {})
            
            # Căutăm seeders prima oară direct în rădăcina dicționarului raw_stream (format API AIO Streams)
            if 'seeders' in raw_stream:
                seeders = raw_stream.get('seeders', 0)
            # Apoi căutăm în dicționarul info, dacă s-a mutat acolo
            elif isinstance(raw_stream.get('info'), dict) and 'seeders' in raw_stream['info']:
                seeders = raw_stream['info'].get('seeders', 0)
                
            # Fallback cu regex din titlu
            if not seeders:
                m = re.search(r'(?:👤|👥|S:)\s*(\d+)', raw_name, re.I)
                if m: seeders = int(m.group(1))
                
            if seeders and str(seeders) != '0':
                parts.append(f"[COLOR FF87CEEB][B]S: {seeders}[/B][/COLOR]")
            # ------------------------------------

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
            
            scraper_tags = info.get('tags',[])
            for t in scraper_tags: 
                if t.upper() not in[x.upper() for x in (hdr_tags + audio_tags)] and t.upper() not in ['REMUX']:
                    parts.append(f"[COLOR gray]{t}[/COLOR]")
                
            info_line_colored = " | ".join(parts)
            info_line_white = re.sub(r'\[/?COLOR.*?\]', '', info_line_colored)
            
            info_line_unfocus = info_line_white if (is_simple or is_mono) else info_line_colored
            
            # STABILIM CULOAREA TITLULUI SELECTAT
            if is_mono:
                info_line_focus = info_line_white
                title_color_focus = 'FFCCCCFF' # Gri-ul simplu
            else:
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
            import time
            if not hasattr(self, 'last_cm_time'):
                self.last_cm_time = 0
            # Dacă a trecut mai puțin de 0.5s de când s-a închis meniul, ignorăm comanda
            if time.time() - self.last_cm_time < 0.5:
                return
            
            self.handle_context_menu()
            
            # Înregistrăm timpul exact când s-a ÎNCHIS meniul contextual
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
                
            ret = xbmcgui.Dialog().contextmenu(options)
            if ret == 0:
                info_text = self._build_source_info(stream_data)
                xbmcgui.Dialog().textviewer("Info Sursa", info_text)
            elif ret == 1:
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
                    # Nu inchidem fereastra ca userul sa poata downloada in fundal in timp ce cauta si alte surse
            elif ret == 1:
                info_text = self._build_source_info(stream_data)
                xbmcgui.Dialog().textviewer("Info Sursa", info_text)
        except Exception as e:
            import xbmc
            xbmc.log(f"[POV CM ERROR] {e}", xbmc.LOGERROR)

    def _build_source_info(self, stream_data):
        import re
        from urllib.parse import urlparse, unquote
        
        info = stream_data.get('info', {})
        raw_name = stream_data.get('title', '')
        if not raw_name or len(raw_name) < 5:
            raw_name = stream_data.get('name', '')
            
        clean_dots = raw_name.replace('.', ' ').replace('_', ' ')
            
        lines = []
        sep = '=================================================='
        lines.append('[B]%s[/B]' % sep)
        lines.append('[B][COLOR FF00BFFF]                   INFO SURSA[/COLOR][/B]')
        lines.append('[B]%s[/B]' % sep)
        lines.append('')
        
        lines.append('[B][COLOR FFFFCC00]NUME COMPLET:[/COLOR][/B]')
        lines.append('  %s' % raw_name)
        lines.append('')
        
        # --- CALITATE VIDEO ---
        lines.append('[B][COLOR FF00FA9A]CALITATE VIDEO:[/COLOR][/B]')
        quality = info.get('quality', 'SD')
        lines.append('  Rezolutie:  [B]%s[/B]' % quality)
        
        source = self._extract_source(raw_name)
        if source:
            lines.append('  Sursa:      [B]%s[/B]' % source)
            
        codec = self._extract_codec(raw_name)
        if codec:
            lines.append('  Codec:      [B]%s[/B]' % codec)
            
        hdr_tags = self._extract_hdr(raw_name)
        if hdr_tags:
            lines.append('  HDR:        [B]%s[/B]' % ' + '.join(hdr_tags))
            
        # Extragere Editie/Varianta
        editions = []
        for tag in ['PROPER', 'REPACK', 'EXTENDED', 'UNCUT', 'DIRECTOR', 'UNRATED', 'REMUX']:
            if re.search(r'(?i)\b%s\b' % tag, raw_name):
                editions.append(tag.upper())
        if editions:
            lines.append('  Varianta:   [B][COLOR FFFF4500]%s[/COLOR][/B]' % ', '.join(editions))
            
        lines.append('')
        
        # --- AUDIO ---
        audio_tags = self._extract_audio(raw_name)
        ch_match = re.search(r'(?i)\b(7\.1|5\.1|2\.0|2\.1|1\.0)\b', clean_dots)
        
        if audio_tags or ch_match:
            lines.append('[B][COLOR FFFF4500]AUDIO:[/COLOR][/B]')
            if audio_tags:
                for i, atag in enumerate(audio_tags):
                    label = 'Principal' if i == 0 else 'Extra'
                    lines.append('  %-10s  [B]%s[/B]' % (label + ':', atag))
            if ch_match:
                lines.append('  Canale:     [B]%s[/B]' % ch_match.group(1))
            lines.append('')
            
        # --- LIMBI ---
        lang_in_title = []
        for lp, ln in [
            (r'(?i)\bRO(?:manian)?\b', 'Romana'),
            (r'(?i)\bEN(?:glish)?\b', 'English'),
            (r'(?i)\bMULTI\b', 'Multi-Language'),
            (r'(?i)\bDUAL\b', 'Dual-Audio'),
            (r'(?i)\bHUN(?:garian)?\b', 'Hungarian'),
            (r'(?i)\bGER(?:man)?\b|DEUTSCH', 'German'),
            (r'(?i)\bFR(?:ench|E)?\b', 'French'),
            (r'(?i)\bITA(?:lian)?\b', 'Italian'),
            (r'(?i)\bSPA(?:nish)?\b', 'Spanish'),
            (r'(?i)\bHIN(?:di)?\b', 'Hindi')
        ]:
            if re.search(lp, clean_dots):
                lang_in_title.append(ln)
        
        if lang_in_title:
            lines.append('[B][COLOR FF87CEEB]LIMBI DETECTATE:[/COLOR][/B]')
            lines.append('  %s' % ', '.join(lang_in_title))
            lines.append('')
            
        # --- FISIER / STATUS ---
        lines.append('[B][COLOR FF00CED1]FISIER / STATUS:[/COLOR][/B]')
        size = info.get('size', '')
        if size:
            lines.append('  Marime:     [B]%s[/B]' % size)
            
        seeders = info.get('seeders', 0)
        if seeders and str(seeders) != '0':
            lines.append('  Seederi:    [B]%s[/B]' % seeders)
            
        is_cached = info.get('is_cached', False)
        is_cloud = info.get('is_cloud', False)
        url = str(stream_data.get('url', ''))
        
        if is_cached:
            lines.append('  Status:     [B][COLOR lime]CACHED (Debrid)[/COLOR][/B]')
        elif is_cloud:
            lines.append('  Status:     [B][COLOR cyan]CLOUD[/COLOR][/B]')
        elif 'magnet:' in url:
            lines.append('  Status:     [B]P2P (Torrent Ne-Cachat)[/B]')
        elif url.startswith('http'):
            lines.append('  Status:     [B]Direct Link (HTTP)[/B]')
        lines.append('')
        
        # --- INDEXER / PROVIDER ---
        lines.append('[B][COLOR cyan]INDEXER / PROVIDER:[/COLOR][/B]')
        addon = info.get('addon', '')
        indexer = info.get('indexer', '')
        provider = info.get('provider', '')
        source_provider = info.get('source_provider', '')
        server = info.get('server', '')
        debrid = info.get('debrid_service', '')
        
        if addon:
            lines.append('  Addon AIO:  [B]%s[/B]' % addon.capitalize())
        if indexer:
            lines.append('  Indexer:    [B][COLOR FFFFD700]%s[/COLOR][/B]' % indexer.capitalize())
        if provider and provider != 'Unknown':
            lines.append('  Provider:   [B]%s[/B]' % provider)
        if source_provider and source_provider.lower() != provider.lower():
            lines.append('  Sursa Web:  [B]%s[/B]' % source_provider)
        if server:
            lines.append('  Server:     [B]%s[/B]' % server)
        if debrid:
            lines.append('  Debrid:     [B][COLOR FFEE82EE]%s[/COLOR][/B]' % debrid.capitalize())
        lines.append('')
        
        # --- DATE TEHNICE (LINK / HASH) ---
        if url:
            lines.append('[B][COLOR gray]DATE TEHNICE (LINK):[/COLOR][/B]')
            if 'btih:' in url:
                hash_m = re.search(r'btih:([a-fA-F0-9]+)', url)
                if hash_m:
                    lines.append('  Hash:       %s' % hash_m.group(1)[:40])
                
                trackers = re.findall(r'tr=([^&]+)', url)
                if trackers:
                    lines.append('  Trackere:   %d identificate' % len(trackers))
                    for i, tr in enumerate(trackers[:3]):
                        try:
                            clean_tr = unquote(tr).split('://')[-1].split('/')[0]
                            lines.append('    - %s' % clean_tr)
                        except: pass
                    if len(trackers) > 3:
                        lines.append('    - ... si altele')
            elif url.startswith('http'):
                try:
                    domain = urlparse(url.split('|')[0]).netloc
                    lines.append('  Domeniu:    %s' % domain)
                except: pass
            lines.append('')
        
        lines.append('[B]%s[/B]' % sep)
        return '\n'.join(lines)


