# -*- coding: utf-8 -*-
from resources.functions import *
import tempfile
import ssl
import hashlib
import pickle
import abc
import threading
from resources.functions import __settings__
zeroseed = __settings__.getSetting("zeroseed") == 'true'

torrentsites = ['filelist',
             'speedapp',
             'uindex',
             'dhtindex',
             'meteor',
             'comet',
             'heartive',
             'mediafusion',
             'torrentio',
             'corncastle',
             'yts',
             'aiostreams'
]

torrnames = {'filelist': {'nume': 'FileList', 'thumb': os.path.join(media, 'filelist.png')},
             'speedapp': {'nume': 'SpeedApp', 'thumb': os.path.join(media, 'speedapp.png')},
             'uindex': {'nume': 'UIndex', 'thumb': os.path.join(media, 'uindex.png')},
             'dhtindex': {'nume': 'DHTindex', 'thumb': os.path.join(media, 'torrents.png')},
             'meteor': {'nume': 'Meteor', 'thumb': os.path.join(media, 'meteor.png')},
             'comet': {'nume': 'Comet', 'thumb': os.path.join(media, 'comet.png')},
             'heartive': {'nume': 'Heartive', 'thumb': os.path.join(media, 'heartive.png')},
             'mediafusion': {'nume': 'MediaFusion', 'thumb': os.path.join(media, 'mediafusion.png')},
             'torrentio': {'nume': 'Torrentio', 'thumb': os.path.join(media, 'torrentio.png')},
             'corncastle': {'nume': 'CornCastle', 'thumb': os.path.join(media, 'torrentio.png')},
             'yts': {'nume': 'YTS', 'thumb': os.path.join(media, 'yts.png')},
             'aiostreams': {'nume': 'AIO Streams', 'thumb': os.path.join(media, 'aiostreams.png')}
}

    

def getKey(item):
        return item[1]

def save_cookie(name, session):
    cookie=os.path.join(dataPath, name + '.txt')
    with open(cookie, 'wb') as f:
        pickle.dump(session.cookies, f)
    

def load_cookie(name, session):
    cookie=os.path.join(dataPath, name + '.txt')
    if os.path.exists(cookie):
        try:
            with open(cookie, 'rb') as f:
                session.cookies.update(pickle.load(f))
        except: pass
    return session
    
def clear_cookie(name):
    cookie=os.path.join(dataPath, name + '.txt')
    if os.path.exists(cookie):
        os.remove(cookie)
        log('%s [clear_cookie]: cookie cleared' % (torrnames.get(name)))
            
def makeRequest(url, data={}, headers={}, name='', timeout=None, referer=None, rtype=None, savecookie=None, raw=None):
    import urllib3
    from urllib3.exceptions import InsecureRequestWarning
    urllib3.disable_warnings(InsecureRequestWarning)
    s = requests.Session()
    if name:
        s = load_cookie(name, s)
    timeout = timeout if timeout else int(__settings__.getSetting('timeout'))
    if not headers:
        headers['User-Agent'] = USERAGENT
    if referer != None:
        headers['Referer'] = referer
    try:
        if data: get = s.post(url, headers=headers, data=data, verify=False, timeout=timeout)
        else: get = s.get(url, headers=headers, verify=False, timeout=timeout)
        if rtype: 
            if rtype == 'json': result = get.json()
            else: 
                try: result = get.text.decode('utf-8')
                except: result = get.text.decode('latin-1')
        else:
            if raw:
                result = get.content
            else:
                try: result = get.content.decode('utf-8')
                except: result = get.content.decode('latin-1')
        if savecookie:
            return (result if raw else str(result), s)
        else:
            return (result if raw else str(result))
    except BaseException as e:
        # INCEPUT MODIFICARE: Protejare link-uri personale in LOG
        safe_url = url
        if name.lower() in ['comet', 'meteor', 'heartive', 'mediafusion']:
            try:
                from urllparse import urlparse
            except:
                from urllib.parse import urlparse
            parsed = urlparse(url)
            safe_url = "%s://%s/PROTEJAT" % (parsed.scheme, parsed.netloc)
        
        log(' %s makeRequest(%s) exception: %s' % (name, safe_url, str(e)))
        # SFARSIT MODIFICARE
        return
    
def tempdir():
        if py3: dirname = xbmcvfs.translatePath('special://temp')
        else: dirname = xbmc.translatePath('special://temp')
        for subdir in ('xbmcup', 'plugin.video.torrenter'):
            dirname = os.path.join(dirname, subdir)
            if not os.path.exists(dirname):
                os.mkdir(dirname)
        return dirname

def md5(string):
        hasher = hashlib.md5()
        hasher.update(string.encode('utf-8'))
        return hasher.hexdigest()

def saveTorrentFile(url, content):
    try:
        temp_dir = tempfile.gettempdir()
    except:
        temp_dir = tempdir()
    localFileName = os.path.join(temp_dir,md5(url)+".torrent")
    localFile = open(localFileName, 'wb+')
    localFile.write(content)
    localFile.close()
    return localFileName

def clear_title(s):
        return striphtml(unescape(s)).replace('   ', ' ').replace('  ', ' ').strip()
    
class Torrent(object):
    __metaclass__ = abc.ABCMeta
    
    nextimage = next_icon
    searchimage = search_icon

    base_url = ''
    thumb = ''
    name = ''
    username = ''
    password = ''
    search_url = ''
    login_url = ''
    login_data = {}
    login_referer = login_url
    url_referer = ''
    url_host = ''
    
    def headers(self):
        self.url_referer = self.url_referer or 'https://%s/' % self.base_url
        self.url_host = self.url_host or self.base_url
        headers = {'Host': self.url_host,
                'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; rv:70.1) Gecko/20100101 Firefox/70.1',
                'Referer': self.url_referer,
                'X-Requested-With': 'XMLHttpRequest',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'}
        return headers
    
    def cauta(self, keyword, replace=False, limit=None):
        url = self.search_url % (keyword.replace(" ", "-") if replace else quote(keyword) )
        return self.__class__.__name__, self.name, self.parse_menu(url, 'get_torrent', limit=limit)
    
        # Metodă helper pentru parametrii
    def _get_torrent_params(self, url, info, torraction=None):
        """Helper pentru a construi parametrii openTorrent cu info Kodi"""
        action = torraction if torraction else ''
        
        # Extrage parametrii Kodi din info
        kodi_dbtype = info.get('kodi_dbtype') if isinstance(info, dict) else None
        kodi_dbid = info.get('kodi_dbid') if isinstance(info, dict) else None
        kodi_path = info.get('kodi_path') if isinstance(info, dict) else None
        
        params = {
            'Tmode': action,
            'Turl': url,
            'Tsite': self.__class__.__name__,
            'info': info,
            'orig_url': url
        }
        
        if kodi_dbtype:
            params['kodi_dbtype'] = kodi_dbtype
            params['kodi_dbid'] = kodi_dbid
            params['kodi_path'] = kodi_path
            log('[%s-TORRENT] Parametri Kodi adăugați: dbtype=%s, dbid=%s' % (self.name, kodi_dbtype, kodi_dbid))
        
        return params
    
    def login(self):
        log('Log-in  attempt')
        self.login_headers = {'Host': self.base_url,
                   'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; rv:70.1) Gecko/20100101 Firefox/70.1',
                   'Referer': self.login_url,
                   'X-Requested-With': 'XMLHttpRequest',
                   'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                   'Content-Type': 'application/x-www-form-urlencoded',
                   'Accept-Language': 'ro,en-US;q=0.7,en;q=0.3'}
        x, session = makeRequest(self.login_url,
                                 name=self.__class__.__name__,
                                 data=self.login_data,
                                 headers=self.login_headers,
                                 savecookie=True)
        if re.search('logout.php|account-details.php', x):
            log('LOGGED %s' % self.name)
        if re.search('incorrect.+?try again|Username or password incorrect', x, re.IGNORECASE):
            xbmc.executebuiltin((u'Notification(%s,%s)' % ('%s Login Error' % self.name, 'Parola/Username incorecte')))
            clear_cookie(self.__class__.__name__)
        save_cookie(self.__class__.__name__, session)
        try: cookiesitems = session.cookies.iteritems()
        except: cookiesitems = session.cookies.items()
        for cookie, value in cookiesitems:
            if cookie == 'pass' or cookie == 'uid' or cookie == 'username':
                return cookie + '=' + value
        return False
    
    def check_login(self, response=None):
        if None != response and 0 < len(response):
            response = str(response)
            if re.compile('<input.+?type="password"|<title> FileList :: Login </title>|Not logged in|/register">Sign up now|account-login.php').search(response):
                log('%s Not logged!' % self.name)
                clear_cookie(self.__class__.__name__)
                self.login()
                return False
            if re.search('incorrect.+?try again|Username or password incorrect|Access Denied', response, re.IGNORECASE):
                xbmc.executebuiltin((u'Notification(%s,%s)' % ('%s Login Error' % self.name, 'Parola/Username incorecte')))
                clear_cookie(self.__class__.__name__)
            return True
        return False
    
    def getTorrentFile(self, url):
        content = makeRequest(url, name=self.__class__.__name__, headers=self.headers(), raw='1')
        if not self.check_login(content):
            content = makeRequest(url, name=self.__class__.__name__, headers=self.headers(), raw='1')
        if re.search("<html", str(content)):
            msg = re.search('Username or password incorrect|User sau parola gresite|Numele de utilizator nu a fost|Date de autentificare invalide', str(content))
            if msg:
                xbmc.executebuiltin((u'Notification(%s,%s)' % ('%s Login Error' % self.name, 'Parola/Username incorecte')))
            xbmc.sleep(4000)
            sys.exit(1)
        return saveTorrentFile(url, content)

class filelist(Torrent):
    def __init__(self):
        self.base_url = 'filelist.io'
        self.thumb = os.path.join(media, 'filelist.png')
        self.name = '[B]FileList[/B]'

        self.sortare = [('Hibrid', '&sort=0'),
                ('Relevanță', '&sort=1'),
                ('După dată', '&sort=2'),
                ('După mărime', '&sort=3'),
                ('După downloads', '&sort=4'),
                ('După peers', '&sort=5')]
        
        self.token = '&usetoken=1'
        
        self.categorii = [('Anime', 'cat=24'), ('Desene', 'cat=15'), ('Filme 3D', 'cat=25'), ('Filme 4k', 'cat=6'), ('Filme 4k Blu-Ray', 'cat=26'), ('Filme Blu-Ray', 'cat=20'), ('Filme DVD', 'cat=2'), ('Filme DVD-RO', 'cat=3'), ('Filme HD', 'cat=4'), ('Filme HD-RO', 'cat=19'), ('Filme SD', 'cat=1'), ('Seriale 4k', 'cat=27'), ('Seriale HD', 'cat=21'), ('Seriale SD', 'cat=23'), ('Sport', 'cat=13'), ('Videoclip', 'cat=12'), ('XXX', 'cat=7'), ('RO Dubbed', 'cat=28')]
        
        self.menu = [('Recente', "https://%s/browse.php?cats[]=24&cats[]=15&cats[]=25&cats[]=6&cats[]=26&cats[]=20&cats[]=2&cats[]=3&cats[]=4&cats[]=19&cats[]=1&cats[]=27&cats[]=21&cats[]=23&cats[]=13&cats[]=12&cats[]=28&incldead=0" % self.base_url, 'recente', self.thumb)]
        l = []
        for x in self.categorii:
            l.append((x[0], 'https://%s/browse.php?%s' % (self.base_url, x[1]), 'get_torrent', self.thumb))
        self.menu.extend(l)
        self.menu.extend([('Căutare', self.base_url, 'cauta', self.searchimage)])
        
        self.search_url_base = "https://%s/browse.php" % self.base_url

    def login(self):
        username = __settings__.getSetting("FLusername")
        password = __settings__.getSetting("FLpassword")
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; rv:70.1) Gecko/20100101 Firefox/70.1', 'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8', 'Accept-Language': 'ro,en-US;q=0.7,en;q=0.3', 'Host': self.base_url}
        w, session = makeRequest('https://%s/login.php' % (self.base_url), name=self.__class__.__name__, headers=headers, savecookie=True)
        save_cookie(self.__class__.__name__, session)
        try: validator = re.findall("validator.*value='(.+?)'", w)[0]
        except: validator = ''
        
        if not (password or username):
            xbmc.executebuiltin((u'Notification(%s,%s)' % ('FileList.ro', 'lipsa username si parola din setari')))
            return False
            
        data = {'validator': validator, 'password': password, 'username': username, 'unlock': '1', 'returnto': '/'}
        headers = {'Origin': 'https://' + self.base_url, 'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; rv:70.1) Gecko/20100101 Firefox/70.1', 'Referer': 'https://' + self.base_url + '/', 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8', 'Accept-Language': 'ro,en-US;q=0.7,en;q=0.3', 'Host': self.base_url}
        xbmc.sleep(1000)
        x, session = makeRequest('https://%s/takelogin.php' % (self.base_url), name=self.__class__.__name__, data=data, headers=headers, savecookie=True)
        if re.search('logout.php', x): log('LOGGED FileListRO')
        elif re.search('Numarul maxim permis de actiuni a fost depasit', x):
            xbmc.executebuiltin((u'Notification(%s,%s)' % ('FileList.ro', u'Site in protectie, reincearca peste o ora')))
            clear_cookie(self.__class__.__name__)
        elif re.search(r'User sau parola gresite\.', x):
            xbmc.executebuiltin((u'Notification(%s,%s)' % ('FileList.ro', u'Parola/User gresite, verifica-le')))
            clear_cookie(self.__class__.__name__)
        
        xbmc.sleep(1000)
        save_cookie(self.__class__.__name__, session)
        try: cookiesitems = session.cookies.iteritems()
        except: cookiesitems = session.cookies.items()
        for cookie, value in cookiesitems:
            if cookie == 'pass': return cookie + '=' + value
        return False
        
    def check_login(self, response=None):
        if None != response and 0 < len(response):
            response = str(response)
            if re.compile('<input.+?type="password"|<title> FileList :: Login </title>|Not logged in|/register">Sign up now|account-login.php').search(response):
                log('%s Not logged!' % self.name)
                clear_cookie(self.__class__.__name__)
                self.login()
                return False
            return True
        return False

    def cauta(self, keyword, limit=None):
        import xbmcgui, json
        clean_keyword = unquote(keyword)
        
        try:
            if not isinstance(clean_keyword, str) and hasattr(clean_keyword, 'decode'): clean_keyword = clean_keyword.decode('utf-8')
        except: pass
        
        diacritice = {'ă':'a', 'â':'a', 'î':'i', 'ș':'s', 'ț':'t', 'Ă':'A', 'Â':'A', 'Î':'I', 'Ș':'S', 'Ț':'T', 'ş':'s', 'ţ':'t', 'Ş':'S', 'Ţ':'T'}
        for d, r in diacritice.items(): clean_keyword = clean_keyword.replace(d, r)
        
        imdb_id, media_type, season, episode = None, 'movie', None, None
        try:
            window = xbmcgui.Window(10000)
            playback_info_str = window.getProperty('mrsp.playback.info')
            if playback_info_str:
                playback_data = json.loads(playback_info_str)
                imdb_id = playback_data.get('imdb_id') or playback_data.get('imdbnumber')
                media_type = playback_data.get('mediatype', 'movie')
                season = playback_data.get('season')
                episode = playback_data.get('episode')
        except: pass

        sanitize_chars = {':': ' ', '–': ' ', '—': ' ', '"': '', "'": '', '&': 'and', '!': '', '?': '', '/': ' ', '\\': ' ', '(': '', ')': '', '[': '', ']': '', ',': '', '`': ''}
        for char, replacement in sanitize_chars.items(): clean_keyword = clean_keyword.replace(char, replacement)
        while '  ' in clean_keyword: clean_keyword = clean_keyword.replace('  ', ' ')
        clean_keyword = clean_keyword.strip()

        match_s_e = re.search(r'(.*?)\s+S(\d+)(?:E(\d+))?', clean_keyword, re.IGNORECASE)
        title_for_search, year = clean_keyword, None
        
        if match_s_e:
            title_for_search = match_s_e.group(1).strip()
            if season is None: season = int(match_s_e.group(2))
            if episode is None and match_s_e.group(3): episode = int(match_s_e.group(3))
            media_type = 'episode' if episode else 'tv'
        else:
            match_year = re.search(r'\b(19|20\d{2})\s*$', clean_keyword)
            if match_year:
                title_for_search = clean_keyword[:match_year.start()].strip()
                year = match_year.group(1)

        if not imdb_id or not str(imdb_id).startswith('tt'):
            if media_type in ['episode', 'tv', 'tvshow']:
                _, api_imdb = get_show_ids_from_tmdb(title_for_search)
                if api_imdb: imdb_id = api_imdb
            else:
                _, api_imdb = get_movie_ids_from_tmdb(title_for_search, year)
                if api_imdb: imdb_id = api_imdb

        filter_data = {'mode': 'normal'}
        if season is not None:
            if episode is not None: filter_data = {'mode': 'D1', 'season': int(season), 'target_ep': int(episode)}
            else: filter_data = {'mode': 'D2', 'season': int(season)}

        urls_to_scan, fallback_urls = [], []
        base_params = "&cat=0&searchin=1&sort=2"
        
        if imdb_id and str(imdb_id).startswith('tt'):
            urls_to_scan.append("%s?search=%s&cat=0&searchin=0&sort=2" % (self.search_url_base, str(imdb_id)))

        if season is not None:
            term_season = "%s S%02d" % (title_for_search, int(season))
            urls_to_scan.append("%s?search=%s%s" % (self.search_url_base, urllib.quote_plus(term_season), base_params))
            if episode is not None:
                term_episode = "%s S%02dE%02d" % (title_for_search, int(season), int(episode))
                urls_to_scan.append("%s?search=%s%s" % (self.search_url_base, urllib.quote_plus(term_episode), base_params))
        else:
            text_fallback_enabled = __settings__.getSetting("FLtextfallback") == 'true'
            if text_fallback_enabled:
                fallback_urls.append("%s?search=%s%s" % (self.search_url_base, urllib.quote_plus(clean_keyword), base_params))
            if not urls_to_scan:
                urls_to_scan.append("%s?search=%s%s" % (self.search_url_base, urllib.quote_plus(clean_keyword), base_params))
                fallback_urls = []

        info_with_data = {'_filter_data': filter_data, '_scan_urls': urls_to_scan, '_fallback_urls': fallback_urls}
        if imdb_id: info_with_data['imdb_id'] = imdb_id
        
        return self.__class__.__name__, self.name, self.parse_menu(urls_to_scan[0], 'get_torrent', info=info_with_data, limit=None)

    def parse_menu(self, url, meniu, info={}, torraction=None, limit=None):
        # FIX: Adaugat categoria 28 (Desene/Filme Dublate) care lipsea
        yescat = ['24', '15', '25', '6', '26', '20', '2', '3', '4', '19', '1', '27', '21', '23', '13', '12', '7', '28']
        lists = []
        
        filter_data = info.get('_filter_data', {'mode': 'normal'}) if info else {'mode': 'normal'}
        scan_urls = info.get('_scan_urls', [url]) if info else [url]
        fallback_urls = info.get('_fallback_urls', []) if info else []
        
        preserved_ids = {}
        if info:
            if info.get('tmdb_id'): preserved_ids['tmdb_id'] = info['tmdb_id']
            if info.get('imdb_id'): preserved_ids['imdb_id'] = info['imdb_id']
        
        if info:
            info = info.copy()
            if '_filter_data' in info: del info['_filter_data']
            if '_scan_urls' in info: del info['_scan_urls']
            if '_fallback_urls' in info: del info['_fallback_urls']

        if meniu == 'cauta':
            from resources.Core import Core
            Core().searchSites({'landsearch': self.__class__.__name__})
            
        elif meniu == 'get_torrent' or meniu == 'recente':
            seen_magnets = set()
            
            # Construim lista totala de URL-uri de scanat
            # 1. URL-urile principale (ID IMDb sau Text Serial)
            # 2. Daca nu gasim nimic, vom incerca si fallback (Text Film)
            urls_groups = [scan_urls]
            if fallback_urls:
                urls_groups.append(fallback_urls)
            
            for group_index, urls_in_group in enumerate(urls_groups):
                # Daca am gasit deja rezultate din primul grup, nu mai intram in fallback
                if group_index > 0 and len(lists) > 0:
                    break
                    
                for current_url in urls_in_group:
                    if group_index > 0: log('[FileList] Fallback fetching: %s' % current_url)
                    else: log('[FileList] Fetching: %s' % current_url)
                    
                    response = makeRequest(current_url, name=self.__class__.__name__, headers=self.headers())
                    
                    if not self.check_login(response):
                        response = makeRequest(current_url, name=self.__class__.__name__, headers=self.headers())
                    
                    if not response: continue
                    
                    rows = response.split("<div class='torrentrow'>")
                    if len(rows) > 1:
                        rows = rows[1:]
                    else:
                        continue

                    for block in rows:
                        try:
                            if "</div></div>" in block:
                                block = block.split("</div></div>")[0]

                            # Extragere Categorie
                            cat_match = re.search(r'browse\.php\?cat=(\d+)', block)
                            cat_id = cat_match.group(1) if cat_match else ''
                            
                            # Extragere Nume Categorie
                            cat_name_match = re.search(r"alt='([^']+)'", block)
                            if not cat_name_match:
                                cat_name_match = re.search(r"src='styles/images/cat/([^.]+)\.png'", block)
                                cat_name = cat_name_match.group(1).upper() if cat_name_match else 'UNK'
                            else:
                                cat_name = cat_name_match.group(1)

                            # Extragere ID si Nume Torrent
                            link_match = re.search(r"href='details\.php\?id=(\d+)'[^>]*title='([^']+)'", block)
                            if not link_match: continue
                            
                            torrent_id = link_match.group(1)
                            nume_raw = link_match.group(2)
                            legatura = "https://%s/download.php?id=%s" % (self.base_url, torrent_id)

                            # Extragere Date Tabel (Size, Seeds, Leechers)
                            cells = re.findall(r"class='torrenttable'>(.*?)</div>", block, re.DOTALL)
                            
                            size = "N/A"
                            seeds = "0"
                            leechers = "0"
                            
                            if len(cells) >= 10:
                                sz_m = re.search(r'(\d+(?:\.\d+)?)<br />(TB|GB|MB|KB)', cells[6])
                                if sz_m: size = "%s %s" % (sz_m.group(1), sz_m.group(2))
                                seeds_text = re.sub(r'<[^>]+>', '', cells[8]).strip()
                                seeds = seeds_text.replace(',', '') if seeds_text.isdigit() else '0'
                                leech_text = re.sub(r'<[^>]+>', '', cells[9]).strip()
                                leechers = leech_text.replace(',', '') if leech_text.isdigit() else '0'

                            # Filtrare D1/D2
                            nume_curat = replaceHTMLCodes(nume_raw)
                            mode = filter_data.get('mode')
                            
                            s_match = re.search(r'(?i)S(\d+)', nume_curat)
                            e_match = re.search(r'(?i)E(\d+)', nume_curat)
                            item_season = int(s_match.group(1)) if s_match else -1
                            item_episode = int(e_match.group(1)) if e_match else -1
                            is_episode = (item_season != -1 and item_episode != -1)
                            
                            keep_item = True
                            if mode == 'D1':
                                target_s = filter_data.get('season')
                                target_e = filter_data.get('target_ep')
                                if item_season != -1 and item_season != target_s:
                                    keep_item = False
                                elif is_episode and item_episode != target_e:
                                    keep_item = False
                            elif mode == 'D2':
                                target_s = filter_data.get('season')
                                if item_season != -1 and item_season != target_s:
                                    keep_item = False
                                elif is_episode:
                                    keep_item = False

                            if keep_item and not (seeds == '0' and not zeroseed):
                                if torrent_id in seen_magnets: continue
                                seen_magnets.add(torrent_id)
                                
                                # Badges
                                badges_str = ""
                                if 'doubleup.png' in block: badges_str += '[B][COLOR lightskyblue]2X[/COLOR][/B] '
                                if 'internal.png' in block: badges_str += '[B][COLOR FFFF69B4]INT[/COLOR][/B] '
                                if 'freeleech.png' in block: badges_str += '[B][COLOR lime]FREE[/COLOR][/B] '
                                if 'romanian.png' in block: badges_str += '[B][COLOR lime]RO[/COLOR][/B] '

                                nume_afisat = '%s%s  [B][COLOR FFFDBD01]%s[/COLOR][/B] [B][COLOR FF00FA9A](%s)[/COLOR][/B] [B][COLOR FFFF69B4][S/L: %s/%s][/COLOR][/B]' % \
                                              (badges_str, nume_curat, cat_name, size, seeds, leechers)
                                
                                # Poster
                                img_match = re.search(r"title=['\"].*?src=['\"]([^'\"]+)['\"]", block)
                                if img_match and 'styles/images' not in img_match.group(1):
                                    poster_final = img_match.group(1)
                                else:
                                    poster_final = ''
                                
                                info_dict = {
                                    'Title': nume_curat,
                                    'Plot': nume_afisat, 
                                    'Genre': cat_name,
                                    'Size': formatsize(size),
                                    'Label2': self.name,
                                    'Poster': poster_final
                                }
                                if preserved_ids:
                                    info_dict.update(preserved_ids)

                                appender = {'nume': nume_afisat,
                                            'legatura': legatura,
                                            'imagine': info_dict['Poster'],
                                            'switch': 'torrent_links',
                                            'info': info_dict}
                                
                                # FIX: Daca cautam dupa ID (tt...), ignoram categoriile si luam tot ce gasim
                                is_imdb_search = 'search=tt' in current_url
                                if is_imdb_search:
                                    lists.append(appender)
                                elif '?search=' in current_url:
                                    if str(cat_id) in yescat or meniu == 'cauta':
                                        lists.append(appender)
                                else: 
                                    lists.append(appender)
                                
                                count += 1

                        except Exception as e:
                            continue
            
            # Paginare (Next Page)
            # Verificam doar pe URL-urile din primul grup pentru paginare
            if len(scan_urls) == 1 and 'search=' not in scan_urls[0]:
                try:
                    match = re.compile(r"'pager'.+?\&page=", re.IGNORECASE | re.DOTALL).findall(response)
                    if len(match) > 0:
                        if '&page=' in url:
                            new = re.compile(r'\&page\=(\d+)').findall(url)
                            nexturl = re.sub(r'\&page\=(\d+)', '&page=' + str(int(new[0]) + 1), url)
                        else:
                            nexturl = '%s%s' % (url, '&page=1')
                        lists.append({'nume': 'Next',
                                      'legatura': nexturl,
                                      'imagine': self.nextimage,
                                      'switch': 'get_torrent',
                                      'info': {}})
                except:
                    pass

        elif meniu == 'sortare':
            for nume, sortare in self.sortare:
                legatura = '%s%s' % (url, sortare)
                lists.append({'nume': nume,
                              'legatura': legatura,
                              'imagine': self.thumb,
                              'switch': 'get_torrent',
                              'info': info})
                              
        elif meniu == 'torrent_links':
            turl = self.getTorrentFile(url)
            action = torraction if torraction else ''
            torrent_params = self._get_torrent_params(turl, info, torraction)
            openTorrent(torrent_params)
            
        return lists

_SP_API = 'https://speedapp.io/api'
_SP_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
_SP_JUNK = r'(?i)\b(trailer|sample|cam|camrip|hdts|hdtc|ts|telesync|scr|screener|preair|clip|preview|tc|hc)\b'
_SP_LOCK = threading.Lock()
_SP_MEM = {'token': None, 'ts': 0, 'fails': 0}
_SP_QUOTA = {'logged': False, 'warned': False}


def _sp_fmt_params(params):
    try:
        parts = []
        for k in sorted(params):
            v = params[k]
            if isinstance(v, list):
                v = ','.join(str(x) for x in v)
            parts.append('%s=%s' % (k, v))
        return '&'.join(parts)
    except:
        return str(params)


def _sp_quota(resp, label):
    try:
        rem = resp.headers.get('x-ratelimit-remaining')
        lim = resp.headers.get('x-ratelimit-limit')
        if rem is None:
            return
        rem = int(rem)
        lim = int(lim) if lim else None
    except:
        return
    if rem > 0 and not _SP_QUOTA['logged']:
        log('[SpeedApp] rate-limit %s: %d ramase%s' % (label, rem,
            (' din %d' % lim) if lim else ''))
        _SP_QUOTA['logged'] = True
    if rem == 0:
        if not _SP_QUOTA['warned']:
            log('[SpeedApp] ATINS rate-limit %s 0 - asteptam resetul ferestrei' % label)
            _SP_QUOTA['warned'] = True
    else:
        _SP_QUOTA['warned'] = False


def _sp_cache_read():
    try:
        f = open(os.path.join(dataPath, 'speedapp_api.json'), 'r')
        d = json.load(f)
        f.close()
        return d if isinstance(d, dict) else {}
    except:
        return {}


def _sp_cache_write(d):
    try:
        f = open(os.path.join(dataPath, 'speedapp_api.json'), 'w')
        json.dump(d, f)
        f.close()
    except:
        pass


class speedapp(Torrent):
    # Categorii video acceptate in rezultate (canonicalName de pe noul API)
    yescats = set(['movies_sd', 'movies_sd_ro', 'movies_dvd', 'movies_dvd_ro',
        'movies_hd', 'movies_hd_ro', 'movies_bluray', 'movies_blurayro',
        'uhd', 'uhd_ro', 'movies_packs', 'ro_movie',
        'tv_sd', 'tv_sd_ro', 'tv_hd', 'tv_hd_ro', 'tv_packs', 'tv_pack_ro', 'ro_tv',
        'sport', 'sports_ro', 'cartoons', 'documentary', 'documentary_ro',
        'anime_hentai', 'music_videos',
        'xxx', 'xxx_sd', 'xxx_dvd', 'xxx_hd', 'xxx_packs'])

    # Categoriile XXX cer scope=adult, altfel API-ul intoarce 400 "Invalid category IDs"
    _adult_cats = set(['xxx', 'xxx_sd', 'xxx_dvd', 'xxx_hd', 'xxx_packs', 'xxx_imgset'])

    def __init__(self):
        self.base_url = 'speedapp.io'
        self.thumb = os.path.join(media, 'speedapp.png')
        self.name = '[B]SpeedApp[/B]'
        self.username = __settings__.getSetting("SPAusername")
        if not self.username:
            self.username = __settings__.getSetting("SFZusername")
        if not self.username:
            self.username = __settings__.getSetting("XZusername")
        self.password = __settings__.getSetting("SPApassword")
        if not self.password:
            self.password = __settings__.getSetting("SFZpassword")
        if not self.password:
            self.password = __settings__.getSetting("XZpassword")
        self.login_url = 'https://%s/login' % (self.base_url)
        self.search_url_base = 'https://%s/browse' % self.base_url

        self.sortare = [('Dupa data', ''),
                ('Dupa marime', 'sort=size&direction=desc'),
                ('Dupa downloads', 'sort=timesCompleted&direction=desc'),
                ('Dupa seederi', 'sort=seeders&direction=desc'),
                ('Dupa leecheri', 'sort=leechers&direction=desc')]

        self.categorii = [('Anime/Hentai', 'anime_hentai'),
                ('Seriale HDTV', 'tv_hd'),
                ('Seriale HDTV-Ro', 'tv_hd_ro'),
                ('Seriale TV (SD)', 'tv_sd'),
                ('Seriale TV-Ro (SD)', 'tv_sd_ro'),
                ('Seriale Romanesti', 'ro_tv'),
                ('Filme BluRay', 'movies_bluray'),
                ('Filme BluRay-Ro', 'movies_blurayro'),
                ('Filme DVD', 'movies_dvd'),
                ('Filme DVD-Ro', 'movies_dvd_ro'),
                ('Filme HD', 'movies_hd'),
                ('Filme HD-Ro', 'movies_hd_ro'),
                ('Filme romanesti', 'ro_movie'),
                ('Filme 4K(2160p)', 'uhd'),
                ('Filme 4K-RO(2160p)', 'uhd_ro'),
                ('Movies Packs', 'movies_packs'),
                ('Videoclipuri', 'music_videos'),
                ('Filme SD', 'movies_sd'),
                ('Filme SD-Ro', 'movies_sd_ro'),
                ('Sport', 'sport'),
                ('Sport-Ro', 'sports_ro'),
                ('TV Packs', 'tv_packs'),
                ('TV Packs-Ro', 'tv_pack_ro'),
                ('Desene Animate', 'cartoons'),
                ('Documentare', 'documentary'),
                ('Documentare-Ro', 'documentary_ro')]
        self.adult = [('XXX-Packs', 'xxx_packs'),
                ('XXX', 'xxx'),
                ('XXX DVD', 'xxx_dvd'),
                ('XXX HD', 'xxx_hd'),
                ('XXX-SD', 'xxx_sd')]

        self.menu = [('Recente', self._build_url(page=1), 'recente', self.thumb)]
        self.menu.append(('Internal', self._build_url(scope='internal', page=1), 'sortare', self.thumb))
        l = []
        for x in self.categorii:
            l.append((x[0], self._build_url(cat=[x[1]]), 'sortare', self.thumb))
        self.menu.extend(l)
        m = []
        for x in self.adult:
            m.append((x[0], self._build_url(cat=[x[1]]), 'sortare', self.thumb))
        self.menu.extend(m)
        self.menu.extend([('Toate(fara XXX)', self._build_url(cat=[x[1] for x in self.categorii]), 'sortare', self.thumb)])
        self.menu.extend([('Cautare', self.base_url, 'cauta', self.searchimage)])

    # ---------- URL / query helpers ----------
    def _build_url(self, search=None, cat=None, sort=None, direction=None, page=1, items=50, scope=None):
        parts = []
        if scope:
            parts.append('scope=' + scope)
        if search:
            parts.append('search=' + urllib.quote_plus(search))
        if cat:
            parts.append('cat=' + ','.join(cat))
        if sort:
            parts.append('sort=%s&direction=%s' % (sort, direction or 'desc'))
        parts.append('page=%d' % int(page or 1))
        parts.append('itemsPerPage=%d' % int(items or 50))
        return '%s/torrents?%s' % (_SP_API, '&'.join(parts))

    def _url_params(self, url):
        raw = {}
        qs = url.split('?', 1)[1] if '?' in url else ''
        for part in qs.split('&'):
            if not part:
                continue
            k, sep, v = part.partition('=')
            k = urllib.unquote_plus(k)
            v = urllib.unquote_plus(v) if sep else ''
            if k in raw:
                if not isinstance(raw[k], list):
                    raw[k] = [raw[k]]
                raw[k].append(v)
            else:
                raw[k] = v
        cats = self._categories()
        params = {}
        for k, v in raw.items():
            if k == 'cat':
                names = v if isinstance(v, list) else [x for x in v.split(',')]
                ids = []
                known = []
                missing = []
                for n in names:
                    n = n.strip()
                    if not n:
                        continue
                    if n in cats:
                        ids.append(cats[n])
                        known.append(n)
                    else:
                        missing.append(n)
                if missing:
                    log('[SpeedApp] categorii necunoscute pe API, ignorate: %s' % ','.join(missing))
                if ids:
                    params['categories[]'] = ids
                # API-ul respinge categoriile XXX (400 "Invalid category IDs") daca nu trimitem scope=adult
                if known and all(n in self._adult_cats for n in known):
                    params['scope'] = 'adult'
            elif k in ('page', 'itemsPerPage'):
                if isinstance(v, list):
                    v = v[0]
                try:
                    params[k] = int(v)
                except:
                    pass
            elif k in ('sort', 'direction', 'search', 'scope'):
                params[k] = v if not isinstance(v, list) else v[0]
        params.setdefault('itemsPerPage', 50)
        return params

    def _next_url(self, params):
        cats = self._categories()
        rev = {}
        for name, cid in cats.items():
            rev[cid] = name
        names = [rev.get(int(c), None) for c in (params.get('categories[]') or [])]
        names = [n for n in names if n]
        return self._build_url(search=params.get('search'), cat=names or None,
                               sort=params.get('sort'), direction=params.get('direction'),
                               page=int(params.get('page', 1)) + 1,
                               items=int(params.get('itemsPerPage', 50)),
                               scope=params.get('scope'))

    # ---------- API ----------
    def _token(self, force=False):
        # /api/login are rate-limit agresiv (429 cu zeci de minute) -> un singur login per proces
        # si niciun retry in serie (parola gresita ar lovi limita la fiecare listing)
        with _SP_LOCK:
            if _SP_MEM.get('fails') and (time.time() - _SP_MEM['fails']) < 600:
                return _SP_MEM.get('token')
            if not force and _SP_MEM['token'] and (time.time() - _SP_MEM['ts']) < 12 * 86400:
                return _SP_MEM['token']
            cache = _sp_cache_read()
            tok = cache.get('token')
            ts = cache.get('ts', 0)
            if not force and tok and (time.time() - ts) < 12 * 86400:
                _SP_MEM['token'] = tok
                _SP_MEM['ts'] = ts
                return tok
            if not self.username or not self.password:
                log('[SpeedApp] lipsesc credentialele (SPAusername/SPApassword)')
                return tok if tok else None
            try:
                r = requests.post(_SP_API + '/login', json={'username': self.username, 'password': self.password},
                                  headers={'User-Agent': _SP_UA}, timeout=15, verify=False)
            except Exception as e:
                _SP_MEM['fails'] = time.time()
                log('[SpeedApp] API login error: %s' % str(e))
                return tok if tok else None
            if r.status_code == 429:
                _SP_MEM['fails'] = time.time()
                if tok:
                    return tok
                log('[SpeedApp] API login rate-limit (429) - nu mai incercam 10 min')
                return None
            if r.status_code not in (200, 201):
                _SP_MEM['fails'] = time.time()
                log('[SpeedApp] API login failed: %s %s (nu mai incercam 10 min)' % (r.status_code, str(r.text)[:120]))
                return tok if tok else None
            try:
                new_tok = (r.json() or {}).get('token')
            except:
                new_tok = None
            if not new_tok:
                return tok if tok else None
            now = time.time()
            cache['token'] = new_tok
            cache['ts'] = now
            _sp_cache_write(cache)
            _SP_MEM['token'] = new_tok
            _SP_MEM['ts'] = now
            return new_tok

    def _api_get(self, path, params):
        for attempt in (0, 1):
            tok = self._token(force=(attempt == 1))
            if not tok:
                return None
            try:
                r = requests.get(_SP_API + path, params=params,
                                 headers={'User-Agent': _SP_UA, 'Authorization': 'Bearer ' + tok,
                                          'Accept': 'application/ld+json'},
                                 timeout=20, verify=False)
            except Exception as e:
                log('[SpeedApp] API %s error: %s' % (path, str(e)))
                return None
            _sp_quota(r, path)
            if r.status_code == 200:
                try:
                    return r.json()
                except:
                    return None
            if r.status_code in (401, 403):
                if attempt == 0:
                    continue
                # login reusit, dar requestul tot 401 -> nu mai reimprospteaza in fiecare listing
                _SP_MEM['fails'] = time.time()
                log('[SpeedApp] token respingat (401 la %s) - pauza 10 min' % path)
                return None
            if r.status_code == 429:
                log('[SpeedApp] API rate-limit (429)')
                return None
            log('[SpeedApp] API %s -> %s %s' % (path, r.status_code, str(r.text)[:150]))
            return None
        return None

    def _categories(self):
        cache = _sp_cache_read()
        cats = cache.get('categories')
        if cats and (time.time() - cache.get('cats_ts', 0)) < 86400:
            return cats
        data = self._api_get('/categories', {'itemsPerPage': 100})
        m = {}
        if data:
            for c in (data.get('member') or []):
                if c.get('canonicalName'):
                    m[c['canonicalName']] = c.get('id')
        if m:
            cache['categories'] = m
            cache['cats_ts'] = time.time()
            _sp_cache_write(cache)
            return m
        return cats if cats else {}

    def login(self):
        return self._token(force=True)

    # ---------- rezultate ----------
    def _item(self, t, filter_data, preserved_ids, hide_int=False):
        nume = (t.get('name') or '').strip()
        if not nume:
            return None
        cat = t.get('category') or {}
        cat_name = cat.get('canonicalName') or ''
        if cat_name and cat_name not in self.yescats:
            return None
        if re.search(_SP_JUNK, nume):
            return None
        s_match = re.search(r'(?i)S(\d+)', nume)
        e_match = re.search(r'(?i)E(\d+)', nume)
        item_season = int(s_match.group(1)) if s_match else -1
        item_episode = int(e_match.group(1)) if e_match else -1
        is_episode_flag = (item_season != -1 and item_episode != -1)
        fmode = filter_data.get('mode') if filter_data else 'normal'
        if fmode == 'D1':
            target_s = filter_data.get('season')
            target_e = filter_data.get('target_ep')
            if item_season != -1 and item_season != target_s:
                return None
            if is_episode_flag and item_episode != target_e:
                return None
        elif fmode == 'D2':
            target_s = filter_data.get('season')
            if item_season != -1 and item_season != target_s:
                return None
            if is_episode_flag:
                return None
        try:
            seeds = int(t.get('seeders') or 0)
            leechers = int(t.get('leechers') or 0)
        except:
            seeds = 0
            leechers = 0
        if seeds == 0 and not zeroseed:
            return None
        try:
            size_b = int(t.get('size') or 0)
        except:
            size_b = 0
        size = format_bytes(size_b)
        free = '[B][COLOR lime]FREE[/COLOR][/B] ' if t.get('isFreeleech') else ''
        double = '[B][COLOR yellow]DoubleUP[/COLOR][/B] ' if t.get('isDoubleUpload') else ''
        promovat = '[B][COLOR lime]PROMOVAT[/COLOR][/B] ' if t.get('isSticky') else ''
        intern = '' if (hide_int or not t.get('isInternal')) else '[B][COLOR FF00CED1]INT[/COLOR][/B] '
        nume_afisat = '%s%s%s%s%s (%s) [S/L: %s/%s]' % (promovat, free, double, intern, nume, size, seeds, leechers)
        plot = '%s\n\n[COLOR yellow]Download: %s[/COLOR]\n[B][COLOR FF00FA9A](%s)[/COLOR][/B] [B][COLOR FFFF69B4][S/L: %s/%s][/COLOR][/B]' % (nume_afisat, size, size, seeds, leechers)
        info_dict = {'Title': nume, 'Plot': plot, 'Size': size, 'Poster': self.thumb}
        if preserved_ids:
            info_dict.update(preserved_ids)
        tid = t.get('id')
        if tid is None:
            return None
        return {'nume': nume_afisat,
                'legatura': '%s/torrents/%s/download' % (_SP_API, tid),
                'imagine': self.thumb,
                'switch': 'torrent_links',
                'info': info_dict}

    def _collect(self, data, lists, seen, filter_data, preserved_ids, rows=None, hide_int=False):
        if not data:
            return 0
        added = 0
        for t in (data.get('member') or []):
            tid = t.get('id')
            if tid is None or tid in seen:
                continue
            it = self._item(t, filter_data, preserved_ids, hide_int)
            if not it:
                continue
            seen.add(tid)
            lists.append(it)
            if rows is not None:
                rows.append((it, t))
            added += 1
        return added

    # ---------- postere TMDb (API-ul SpeedApp nu livreaza imagini) ----------
    _poster_ttl = 7 * 86400
    _poster_workers = 10
    _poster_deadline = 5.0
    _poster_max = 40

    def _poster_key(self, title, year, kind):
        return '%s|%s|%s' % (kind, re.sub(r'[^a-z0-9]+', '', (title or '').lower()), year or '')

    def _poster_meta(self, t):
        title = (t.get('title') or '').strip()
        year = t.get('year')
        name = t.get('name') or ''
        cat = ((t.get('category') or {}).get('canonicalName') or '')
        kind = 'movie'
        if cat.startswith('tv_') or cat in ('ro_tv', 'anime_hentai') or re.search(r'(?i)\bS\d+E\d+', name):
            kind = 'tv'
        if not title:
            try:
                from resources.lib import PTN
                parsed = PTN.parse(re.sub(r'[._\-]+', ' ', name))
                title = str(parsed.get('title') or '').strip()
                if not year and parsed.get('year'):
                    year = parsed.get('year')
                if parsed.get('season') is not None:
                    kind = 'tv'
            except:
                pass
        if not title or len(title) < 2:
            return None
        return (title, year, kind)

    def _poster_cache_read(self, keys):
        out = {}
        if not keys:
            return out
        try:
            con = database.connect(addonCache)
            cur = con.cursor()
            cur.execute("CREATE TABLE IF NOT EXISTS sp_posters (k TEXT PRIMARY KEY, poster TEXT, ts INTEGER)")
            cur.execute("SELECT k, poster, ts FROM sp_posters WHERE k IN (%s)" % ','.join(['?'] * len(keys)), keys)
            now = time.time()
            for k, poster, ts in cur.fetchall():
                if ts and (now - ts) < self._poster_ttl:
                    out[k] = poster or ''
            con.close()
        except Exception as e:
            log('[SpeedApp] poster cache read: %s' % str(e))
        return out

    def _poster_cache_write(self, pairs):
        if not pairs:
            return
        try:
            con = database.connect(addonCache)
            cur = con.cursor()
            cur.execute("CREATE TABLE IF NOT EXISTS sp_posters (k TEXT PRIMARY KEY, poster TEXT, ts INTEGER)")
            now = int(time.time())
            cur.executemany("INSERT OR REPLACE INTO sp_posters (k, poster, ts) VALUES (?,?,?)",
                            [(k, v or '', now) for k, v in pairs])
            con.commit()
            con.close()
        except Exception as e:
            log('[SpeedApp] poster cache write: %s' % str(e))

    def _tmdb_poster(self, title, year, kind):
        try:
            params = {'api_key': tmdb_key(), 'query': title, 'language': 'en-US'}
            if kind != 'tv' and year:
                params['primary_release_year'] = year
            r = requests.get('https://api.themoviedb.org/3/search/%s' % kind, params=params,
                             timeout=6, verify=False)
            if r.status_code != 200:
                return ''
            results = (r.json() or {}).get('results') or []
        except:
            return ''
        tnorm = re.sub(r'[^a-z0-9]+', ' ', (title or '').lower()).strip()
        best = None
        best_score = 0
        for it in results:
            if not it.get('poster_path'):
                continue
            nm = it.get('name') if kind == 'tv' else it.get('title')
            if not nm:
                continue
            inorm = re.sub(r'[^a-z0-9]+', ' ', nm.lower()).strip()
            score = 0
            if inorm == tnorm:
                score += 10
            elif inorm.startswith(tnorm) or tnorm.startswith(inorm):
                score += 6
            elif tnorm in inorm or inorm in tnorm:
                score += 3
            ry = (it.get('first_air_date') if kind == 'tv' else it.get('release_date')) or ''
            ry = ry[:4]
            if year and ry:
                try:
                    if ry == str(year):
                        score += 5
                    elif abs(int(ry) - int(year)) <= 1:
                        score += 2
                except:
                    pass
            if score > best_score:
                best_score = score
                best = it
        if not best or best_score < 6:
            return ''
        return 'https://image.tmdb.org/t/p/w500%s' % best['poster_path']

    def _apply_posters(self, rows):
        if not rows:
            return
        jobs = {}
        for item, t in rows:
            info = item.get('info') or {}
            if info.get('Poster') and info.get('Poster') != self.thumb:
                continue
            meta = self._poster_meta(t)
            if not meta:
                continue
            jobs[self._poster_key(*meta)] = meta
        if not jobs:
            return
        keys = list(jobs.keys())[:self._poster_max]
        cached = self._poster_cache_read(keys)
        lut = {}
        for k in keys:
            if k in cached:
                lut[k] = cached[k]
        todo = [k for k in keys if k not in lut]
        if todo:
            lock = threading.Lock()
            found = {}

            def work(key):
                title, year, kind = jobs[key]
                p = self._tmdb_poster(title, year, kind)
                if not p:
                    p = self._tmdb_poster(title, year, 'tv' if kind == 'movie' else 'movie')
                with lock:
                    found[key] = p

            deadline = time.time() + self._poster_deadline
            running = []
            while todo or running:
                while todo and len(running) < self._poster_workers:
                    key = todo.pop(0)
                    th = threading.Thread(target=work, args=(key,))
                    th.daemon = True
                    try:
                        th.start()
                    except:
                        continue
                    running.append(th)
                if time.time() >= deadline:
                    break
                time.sleep(0.05)
                running = [t for t in running if t.is_alive()]
            with lock:
                done = dict(found)
            self._poster_cache_write(list(done.items()))
            lut.update(done)
        hit = 0
        for item, t in rows:
            meta = self._poster_meta(t)
            if not meta:
                continue
            p = lut.get(self._poster_key(*meta))
            if p:
                info = item.get('info')
                if isinstance(info, dict):
                    info['Poster'] = p
                item['imagine'] = p
                hit += 1
        log('[SpeedApp] postere TMDb: %d/%d randuri, %d cautari in cache' % (hit, len(rows), len(keys)))

    # ---------- cautare ----------
    def cauta(self, keyword, limit=None):
        import xbmcgui

        clean_keyword = unquote(keyword)

        try:
            if not isinstance(clean_keyword, str) and hasattr(clean_keyword, 'decode'):
                clean_keyword = clean_keyword.decode('utf-8')
        except: pass

        diacritice = {
            'ă':'a', 'â':'a', 'î':'i', 'ș':'s', 'ț':'t', 'Ă':'A', 'Â':'A', 'Î':'I', 'Ș':'S', 'Ț':'T',
            'ş':'s', 'ţ':'t', 'Ş':'S', 'Ţ':'T'
        }
        for d, r in diacritice.items():
            clean_keyword = clean_keyword.replace(d, r)

        imdb_id = None
        media_type = 'movie'
        season = None
        episode = None

        try:
            window = xbmcgui.Window(10000)
            playback_info_str = window.getProperty('mrsp.playback.info')
            if playback_info_str:
                playback_data = json.loads(playback_info_str)
                imdb_id = playback_data.get('imdb_id') or playback_data.get('imdbnumber')
                media_type = playback_data.get('mediatype', 'movie')
                season = playback_data.get('season')
                episode = playback_data.get('episode')
        except: pass

        sanitize_chars = {':': ' ', '–': ' ', '—': ' ', '"': '', "'": '', '&': 'and'}
        for char, replacement in sanitize_chars.items():
            clean_keyword = clean_keyword.replace(char, replacement)
        while '  ' in clean_keyword:
            clean_keyword = clean_keyword.replace('  ', ' ')
        clean_keyword = clean_keyword.strip()

        match_s_e = re.search(r'(.*?)\s+S(\d+)(?:E(\d+))?', clean_keyword, re.IGNORECASE)
        title_for_search = clean_keyword
        year = None

        if match_s_e:
            title_for_search = match_s_e.group(1).strip()
            if season is None: season = int(match_s_e.group(2))
            if episode is None and match_s_e.group(3): episode = int(match_s_e.group(3))
            media_type = 'episode' if episode else 'tv'
        else:
            match_year = re.search(r'\b(19|20\d{2})\s*$', clean_keyword)
            if match_year:
                title_for_search = clean_keyword[:match_year.start()].strip()
                year = match_year.group(1)

        if not imdb_id or not str(imdb_id).startswith('tt'):
            if media_type in ['episode', 'tv', 'tvshow']:
                _, api_imdb = get_show_ids_from_tmdb(title_for_search)
                if api_imdb: imdb_id = api_imdb
            else:
                _, api_imdb = get_movie_ids_from_tmdb(title_for_search, year)
                if api_imdb: imdb_id = api_imdb

        filter_data = {'mode': 'normal'}
        if season is not None:
            if episode is not None:
                filter_data = {'mode': 'D1', 'season': int(season), 'target_ep': int(episode)}
            else:
                filter_data = {'mode': 'D2', 'season': int(season)}

        base = {'sort': 'seeders', 'direction': 'desc', 'itemsPerPage': 100}
        scan_queries = []
        fallback_queries = []

        def q(term):
            d = dict(base)
            d['search'] = term
            return d

        if imdb_id and str(imdb_id).startswith('tt'):
            scan_queries.append(q(str(imdb_id)))

        if season is not None:
            scan_queries.append(q("%s S%02d" % (title_for_search, int(season))))
            if episode is not None:
                scan_queries.append(q("%s S%02dE%02d" % (title_for_search, int(season), int(episode))))
        else:
            text_fallback_enabled = __settings__.getSetting("SPAtextfallback") == 'true'
            if text_fallback_enabled:
                fallback_queries.append(q(clean_keyword))
            if not scan_queries:
                scan_queries.append(q(clean_keyword))
                fallback_queries = []

        preserved_ids = {}
        if imdb_id:
            preserved_ids['imdb_id'] = imdb_id

        lists = []
        seen = set()
        rows = []

        for params in scan_queries:
            log('[SpeedApp] API search: %s' % params.get('search'))
            data = self._api_get('/torrents', params)
            self._collect(data, lists, seen, filter_data, preserved_ids, rows)

        if not lists and fallback_queries:
            log('[SpeedApp] IMDb n-a gasit nimic, fallback pe cautare text...')
            for params in fallback_queries:
                log('[SpeedApp] API fallback: %s' % params.get('search'))
                data = self._api_get('/torrents', params)
                self._collect(data, lists, seen, filter_data, preserved_ids, rows)

        self._apply_posters(rows)
        return self.__class__.__name__, self.name, lists

    # ---------- browse ----------
    def _fetch_and_parse_browse(self, orig_url, scan_urls, fallback_urls, yescat, filter_data, imagine, preserved_ids):
        lists = []
        seen = set()
        rows = []
        params = None
        data = None

        for u in scan_urls:
            params = self._url_params(u)
            log('[SpeedApp] Browse API: %s -> %s' % (u, _sp_fmt_params(params)))
            data = self._api_get('/torrents', params)
            hide_int = params.get('scope') == 'internal'
            self._collect(data, lists, seen, filter_data, preserved_ids, rows, hide_int)

        if not lists and fallback_urls:
            log('[SpeedApp] Browse: IMDb n-a gasit nimic, fallback pe cautare text...')
            for u in fallback_urls:
                fparams = self._url_params(u)
                log('[SpeedApp] Browse fallback: %s' % u)
                self._collect(self._api_get('/torrents', fparams), lists, seen, filter_data, preserved_ids, rows)

        self._apply_posters(rows)

        # Paginare doar pt browsare normala (nu cautare compusa)
        if len(scan_urls) == 1 and params and data and not params.get('search'):
            try:
                per = int(params.get('itemsPerPage', 50))
                page = int(params.get('page', 1))
                total = int(data.get('totalItems') or 0)
                if per > 0 and page * per < total:
                    lists.append({'nume': 'Next',
                                  'legatura': self._next_url(params),
                                  'imagine': self.nextimage,
                                  'switch': 'get_torrent',
                                  'info': {}})
            except:
                pass

        return lists

    def getTorrentFile(self, url):
        tok = self._token()
        headers = {'User-Agent': _SP_UA}
        if tok:
            headers['Authorization'] = 'Bearer ' + tok
        try:
            r = requests.get(url, headers=headers, timeout=30, verify=False)
        except Exception as e:
            log('[SpeedApp] download error: %s' % str(e))
            return None
        _sp_quota(r, 'download')
        if r.status_code == 429:
            log('[SpeedApp] download rate-limit (429)')
            return None
        if r.status_code in (401, 403):
            tok = self._token(force=True)
            if not tok:
                return None
            try:
                r = requests.get(url, headers={'User-Agent': _SP_UA, 'Authorization': 'Bearer ' + tok},
                                 timeout=30, verify=False)
            except Exception as e:
                log('[SpeedApp] download retry error: %s' % str(e))
                return None
        if r.status_code != 200 or not r.content:
            log('[SpeedApp] download failed: %s' % r.status_code)
            return None
        if b'8:announce' not in r.content[:64] and b'd8:announce' not in r.content[:64]:
            log('[SpeedApp] download invalid (nu bencode)')
            return None
        return saveTorrentFile(url, r.content)

    def parse_menu(self, url, meniu, info={}, torraction=None, limit=None):
        lists = []
        imagine = self.thumb

        filter_data = info.get('_filter_data', {'mode': 'normal'}) if info else {'mode': 'normal'}
        scan_urls = info.get('_scan_urls', [url]) if info else [url]
        fallback_urls = info.get('_fallback_urls', []) if info else []

        preserved_ids = {}
        if info:
            if info.get('tmdb_id'): preserved_ids['tmdb_id'] = info['tmdb_id']
            if info.get('imdb_id'): preserved_ids['imdb_id'] = info['imdb_id']

        if info:
            info = info.copy()
            if '_filter_data' in info: del info['_filter_data']
            if '_scan_urls' in info: del info['_scan_urls']
            if '_fallback_urls' in info: del info['_fallback_urls']

        if meniu == 'get_torrent' or meniu == 'cauta' or meniu == 'recente':
            if meniu == 'cauta':
                from resources.Core import Core
                Core().searchSites({'landsearch': self.__class__.__name__})
            else:
                lists = self._fetch_and_parse_browse(url, scan_urls, fallback_urls, None, filter_data, imagine, preserved_ids)

        elif meniu == 'sortare':
            for nume, sortare in self.sortare:
                legatura = '%s%s&page=1' % (url, (('&%s' % sortare) if sortare else ''))
                lists.append({'nume': nume,
                                'legatura': legatura,
                                'imagine': self.thumb,
                                'switch': 'get_torrent',
                                'info': info})
        elif meniu == 'torrent_links':
            turl = self.getTorrentFile(url)
            if not turl:
                xbmc.executebuiltin((u'Notification(%s,%s)' % ('SpeedApp', 'Download esuitat')))
                return lists
            action = torraction if torraction else ''
            openTorrent(self._get_torrent_params(turl, info, torraction))

        return lists


class uindex(Torrent):
    def __init__(self):
        self.base_url = 'uindex.org'
        self.thumb = os.path.join(media, 'uindex.png')
        self.name = '[B]UIndex[/B]'
        self.search_url = "https://%s/search.php" % self.base_url
        
        # URL-urile pentru Top 100
        url_movies = 'https://%s/top.php?c=1' % self.base_url
        url_tv = 'https://%s/top.php?c=2' % self.base_url
        
        # Combinam URL-urile cu separatorul | pentru a fi procesate impreuna la Recente
        url_combined_recents = "%s|%s" % (url_movies, url_tv)

        self.menu = [
            ('Top 100 Filme (7 zile)', url_movies, 'get_torrent', self.thumb),
            ('Top 100 Seriale (7 zile)', url_tv, 'get_torrent', self.thumb),
            # Elementul magic pentru Recente Globale
            ('Recente', url_combined_recents, 'recente', self.thumb),
            ('Căutare', self.base_url, 'cauta', self.searchimage)
        ]

    def _normalize_name(self, name):
        """Normalizeaza un nume pentru comparare: lowercase, fara caractere speciale, spatii simple."""
        # Strip tracker prefix (diverse formate) INAINTE de normalizare
        n = re.sub(r'(?i)^(?:www\.)?uindex\.org\s*[-–—:]\s*', '', name).strip()
        # Strip tag-uri in paranteze patrate de la inceput: [RO], [UIndex], etc.
        n = re.sub(r'^\[.*?\]\s*', '', n).strip()
        # Normalizare standard
        n = n.replace('.', ' ').replace('-', ' ').replace('_', ' ').replace(':', ' ')
        n = re.sub(r'[^\w\s]', '', n)
        n = re.sub(r'\s+', ' ', n).strip().lower()
        return n

    def _get_tmdb_year(self, tmdb_id):
        """Obtine anul de lansare de pe site-ul TMDB (fara API key)"""
        try:
            url = 'https://www.themoviedb.org/movie/%s' % str(tmdb_id)
            try:
                from urllib2 import urlopen, Request
            except ImportError:
                from urllib.request import urlopen, Request
            req = Request(url)
            req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
            req.add_header('Accept-Language', 'en-US,en;q=0.5')
            resp = urlopen(req, timeout=5)
            html = resp.read().decode('utf-8', errors='ignore')
            # <title>War Machine (2026) — The Movie Database (TMDB)</title>
            match = re.search(r'<title>[^<]*\((\d{4})\)', html)
            if match:
                year = match.group(1)
                log('[UIndex] Got year from TMDB website (id=%s): %s' % (str(tmdb_id), year))
                return year
        except Exception as e:
            log('[UIndex] TMDB year lookup failed: %s' % str(e))
        return None

    def cauta(self, keyword, limit=None):
        import xbmcgui, json
        clean_keyword = unquote(keyword).strip()
        
        # DEBUG: vezi ce limit vine din exterior
        # log('[UIndex] cauta called with limit=%s' % str(limit))
        
        # --- 0. ELIMINARE DIACRITICE ---
        try:
            if not isinstance(clean_keyword, str) and hasattr(clean_keyword, 'decode'):
                clean_keyword = clean_keyword.decode('utf-8')
        except: pass
        diacritice = {
            'ă':'a', 'â':'a', 'î':'i', 'ș':'s', 'ț':'t', 'Ă':'A', 'Â':'A', 'Î':'I', 'Ș':'S', 'Ț':'T',
            'ş':'s', 'ţ':'t', 'Ş':'S', 'Ţ':'T'
        }
        for d, r in diacritice.items():
            clean_keyword = clean_keyword.replace(d, r)

        # --- 1. PRELUARE CONTEXT ---
        media_type = 'movie'
        season = None
        episode = None
        context_year = None
        tmdb_id = None
        
        try:
            window = xbmcgui.Window(10000)
            playback_info_str = window.getProperty('mrsp.playback.info')
            if playback_info_str:
                playback_data = json.loads(playback_info_str)
                media_type = playback_data.get('mediatype', 'movie')
                season = playback_data.get('season')
                episode = playback_data.get('episode')
                context_year = playback_data.get('year')
                tmdb_id = playback_data.get('tmdb_id')
                if not context_year:
                    premiered = playback_data.get('premiered', '')
                    if premiered:
                        y_match = re.search(r'((?:19|20)\d{2})', str(premiered))
                        if y_match:
                            context_year = y_match.group(1)
                if context_year:
                    context_year = str(context_year)
        except: pass

        # --- 2. SANITIZARE ---
        sanitize_chars = {
            ':': ' ', '–': ' ', '—': ' ', '"': '', "'": '', '&': 'and',
            '!': '', '?': '', '/': ' ', '\\': ' ', '(': '', ')': '',
            '[': '', ']': '', ',': '', '`': ''
        }
        for char, replacement in sanitize_chars.items():
            clean_keyword = clean_keyword.replace(char, replacement)
        while '  ' in clean_keyword:
            clean_keyword = clean_keyword.replace('  ', ' ')
        clean_keyword = clean_keyword.strip()

        # --- 3. PARSARE SEZON/EPISOD SI AN ---
        match_s_e = re.search(r'(.*?)\s+S(\d+)(?:E(\d+))?', clean_keyword, re.IGNORECASE)
        title_for_search = clean_keyword
        year = None
        
        if match_s_e:
            title_for_search = match_s_e.group(1).strip()
            if season is None: season = int(match_s_e.group(2))
            if episode is None and match_s_e.group(3): episode = int(match_s_e.group(3))
            media_type = 'episode' if episode else 'tv'
        else:
            match_year = re.search(r'\b((?:19|20)\d{2})\s*$', clean_keyword)
            if match_year:
                title_for_search = clean_keyword[:match_year.start()].strip()
                year = match_year.group(1)
        
        # An din context
        if not year and context_year and media_type == 'movie':
            year = context_year

        # --- 3b. AN DIN TMDB WEBSITE (daca tot nu avem) ---
        if not year and media_type == 'movie' and tmdb_id:
            year = self._get_tmdb_year(tmdb_id)

        # --- 4. CONSTRUCTIE URL-URI ---
        filter_data = {'mode': 'normal'}
        urls_to_scan = []
        
        if match_s_e:
            # === SERIAL ===
            s = season if season else int(match_s_e.group(2))
            e = episode
            
            if e:
                term_episode = "%s S%02dE%02d" % (title_for_search, s, e)
                term_season = "%s S%02d" % (title_for_search, s)
                url1 = "%s?search=%s&c=2&sort=seeders&order=DESC" % (self.search_url, urllib.quote_plus(term_episode))
                url2 = "%s?search=%s&c=2&sort=seeders&order=DESC" % (self.search_url, urllib.quote_plus(term_season))
                urls_to_scan = [url1, url2]
                filter_data = {'mode': 'D1', 'season': s, 'target_ep': e}
            else:
                term_season = "%s S%02d" % (title_for_search, s)
                url = "%s?search=%s&c=2&sort=seeders&order=DESC" % (self.search_url, urllib.quote_plus(term_season))
                urls_to_scan = [url]
                filter_data = {'mode': 'D2', 'season': s}
        else:
            # === FILM: titlu + an (daca exista) ===
            if year:
                search_term = "%s %s" % (title_for_search, year)
            else:
                search_term = title_for_search
            
            url = "%s?search=%s&c=1&sort=seeders&order=DESC" % (self.search_url, urllib.quote_plus(search_term))
            urls_to_scan = [url]
            # FARA FILTRARE - serverul face treaba cu anul in search term
            # Filtram dupa an (daca il avem)
            if year:
                filter_data = {'mode': 'movie_year', 'year': year}
            else:
                filter_data = {'mode': 'normal'}
            
            log('[UIndex] Movie search: title="%s", year="%s", url="%s"' % (title_for_search, str(year), url))

        info_with_data = {'_filter_data': filter_data, '_scan_urls': urls_to_scan}
        
        # DUPĂ (ignora limit-ul extern, arata TOATE rezultatele):
        return self.__class__.__name__, self.name, self.parse_menu(urls_to_scan[0], 'get_torrent', info=info_with_data, limit=None)
        
    def parse_menu(self, url, meniu, info={}, torraction=None, limit=None):
        lists = []
        imagine = self.thumb
        
    # Extragem datele injectate
        filter_data = info.get('_filter_data', {'mode': 'normal'}) if info else {'mode': 'normal'}
        
        # Suport pentru URL-uri multiple (ex: Recente UIndex)
        if info and '_scan_urls' in info:
            scan_urls = info['_scan_urls']
        else:
            if '|' in url:
                scan_urls = url.split('|')
            else:
                scan_urls = [url]
        
        # Pastrare ID-uri pentru propagare
        preserved_ids = {}
        if info:
            if info.get('tmdb_id'): preserved_ids['tmdb_id'] = info['tmdb_id']
            if info.get('imdb_id'): preserved_ids['imdb_id'] = info['imdb_id']
        
        # Curatam info de datele interne
        if info:
            info = info.copy()
            if '_filter_data' in info: del info['_filter_data']
            if '_scan_urls' in info: del info['_scan_urls']
        
        if meniu == 'cauta':
            from resources.Core import Core
            Core().searchSites({'landsearch': self.__class__.__name__})
            
        elif meniu == 'get_torrent' or meniu == 'recente':
            seen_magnets = set()
            count = 0
            
            for current_url in scan_urls:
                log('[UIndex] Fetching: %s' % current_url)
                link = fetchData(current_url, headers=self.headers())
                
                if not link: continue
                
                # Parsam rand cu rand (tr) pentru precizie maxima
                rows = re.findall(r'<tr>(.*?)</tr>', link, re.DOTALL | re.IGNORECASE)
                # log('[UIndex] Total rows found: %d' % len(rows))
                
                parsed = 0
                for row in rows:
                    try:
                        # Magnet link
                        m_magnet = re.search(r"href=['\"]?(magnet:\?xt=urn:btih:[^'\">\s]+)", row, re.IGNORECASE)
                        if not m_magnet:
                            continue
                        
                        magnet = m_magnet.group(1)
                        if magnet in seen_magnets:
                            continue
                        
                        # Titlu - din link-ul details.php
                        m_title = re.search(r"href=['\"]?/details\.php\?id=\d+['\"]?>(.+?)</a>", row, re.DOTALL | re.IGNORECASE)
                        if not m_title:
                            continue
                        
                        # Curatam titlul de tag-uri HTML (<span class="new-label">New</span> etc)
                        raw_title = m_title.group(1)
                        raw_title = re.sub(r'<[^>]+>', '', raw_title).strip()
                        
                        # Size
                        m_size = re.search(r'<td[^>]*>([\d\.,]+\s*[KMGT]i?B)</td>', row, re.IGNORECASE)
                        if not m_size:
                            continue
                        
                        # Seeds
                        m_seeds = re.search(r"class=['\"]g['\"]>([\d,]+)</span>", row, re.IGNORECASE)
                        # Leechers
                        m_leechers = re.search(r"class=['\"]b['\"]>([\d,]+)</span>", row, re.IGNORECASE)
                        
                        if not m_seeds or not m_leechers:
                            continue
                        
                        seeds = m_seeds.group(1)
                        leechers = m_leechers.group(1)
                        size = m_size.group(1).strip()
                        
                        nume_curat = raw_title
                        nume_curat = re.sub(r'(?i)(?:www\.)?uindex\.org\s*[-\u2013\u2014]\s*', '', nume_curat).strip()
                        legatura = magnet.strip()
                        seeds_clean = seeds.replace(',', '')
                        leechers_clean = leechers.replace(',', '')
                        
                        # --- FILTRARE ---
                        mode = filter_data.get('mode')
                        keep_item = True

                        if mode == 'movie_year':
                            year_check = filter_data.get('year')
                            if year_check and year_check not in nume_curat:
                                keep_item = False

                        elif mode == 'D1':
                            s_match = re.search(r'(?i)S(\d+)', nume_curat)
                            e_match = re.search(r'(?i)E(\d+)', nume_curat)
                            item_season = int(s_match.group(1)) if s_match else -1
                            item_episode = int(e_match.group(1)) if e_match else -1
                            is_episode = (item_season != -1 and item_episode != -1)
                            
                            target_s = filter_data.get('season')
                            target_e = filter_data.get('target_ep')
                            if item_season != -1 and item_season != target_s:
                                keep_item = False
                            elif is_episode and item_episode != target_e:
                                keep_item = False

                        elif mode == 'D2':
                            s_match = re.search(r'(?i)S(\d+)', nume_curat)
                            e_match = re.search(r'(?i)E(\d+)', nume_curat)
                            item_season = int(s_match.group(1)) if s_match else -1
                            item_episode = int(e_match.group(1)) if e_match else -1
                            is_episode = (item_season != -1 and item_episode != -1)
                            
                            target_s = filter_data.get('season')
                            if item_season != -1 and item_season != target_s:
                                keep_item = False
                            elif is_episode:
                                keep_item = False

                            if keep_item and not (seeds_clean == '0' and not zeroseed):
                                seen_magnets.add(magnet)
                            
                            if seeds_clean == '0':
                                seed_color = 'FFFF0000'
                            else:
                                seed_color = 'FF00FA9A'
                            
                            nume_pentru_lista = '%s [B][COLOR FF00FA9A](%s)[/COLOR][/B] [B][COLOR %s][S/L: %s/%s][/COLOR][/B]' % (nume_curat, size, seed_color, seeds, leechers)
                            info_secundara = '[B][COLOR FF00FA9A]Size: %s[/COLOR][/B]  [B][COLOR %s]S/L: %s/%s[/COLOR][/B]' % (size, seed_color, seeds, leechers)
                            
                            info_dict = {
                                'Title': nume_curat,
                                'Plot': nume_curat + '\n' + info_secundara,
                                'Size': formatsize(size),
                                'Label2': info_secundara,
                                'Poster': imagine
                            }
                            if preserved_ids:
                                info_dict.update(preserved_ids)
                            
                            lists.append({
                                'nume': nume_pentru_lista,
                                'legatura': legatura,
                                'imagine': imagine,
                                'switch': 'torrent_links',
                                'info': info_dict
                            })
                            
                            count += 1
                            parsed += 1
                            
                            if limit and int(limit) > 0 and count >= int(limit):
                                break
                                
                    except Exception as e:
                        continue
                
                # log('[UIndex] Parsed from rows: %d, Total items added: %d' % (parsed, len(lists)))
                
                if limit and int(limit) > 0 and count >= int(limit):
                    break

            log('[UIndex] Total items added: %d' % len(lists))
    
        elif meniu == 'torrent_links':
            action = torraction if torraction else ''
            openTorrent({'Tmode': action, 'Turl': url, 'Tsite': self.__class__.__name__, 'info': info, 'orig_url': url})
            
        return lists

class dhtindex(Torrent):
    def __init__(self):
        self.base_url = 'dhtindex.org'
        self.thumb = os.path.join(media, 'torrents.png')
        self.name = '[B]DHTindex[/B]'
        self.search_url = "https://%s/search" % self.base_url
        self.menu = [
            ('Căutare', self.base_url, 'cauta', self.searchimage)
        ]

    def cauta(self, keyword, replace=False, limit=None):
        clean_kw = unquote(keyword).strip()
        import xbmcgui, json
        media_type = 'movie'
        context_year = None
        season = None
        episode = None
        try:
            window = xbmcgui.Window(10000)
            p_str = window.getProperty('mrsp.playback.info')
            if p_str:
                p_data = json.loads(p_str)
                media_type = p_data.get('mediatype', 'movie')
                s_val = p_data.get('season')
                if s_val is not None: season = int(s_val)
                e_val = p_data.get('episode')
                if e_val is not None: episode = int(e_val)
                premiered = p_data.get('premiered') or ''
                context_year = p_data.get('year') or premiered[-4:] or None
                if context_year and len(str(context_year)) == 4:
                    context_year = str(context_year)
        except: pass
        match_s_e = re.search(r'(.*?)\s+S(\d+)(?:E(\d+))?', clean_kw, re.IGNORECASE)
        title_for_search = clean_kw
        year = None
        if match_s_e:
            title_for_search = match_s_e.group(1).strip()
            if season is None: season = int(match_s_e.group(2))
            if episode is None and match_s_e.group(3): episode = int(match_s_e.group(3))
            media_type = 'episode' if episode else 'tv'
        else:
            match_year = re.search(r'\b((?:19|20)\d{2})\s*$', clean_kw)
            if match_year:
                title_for_search = clean_kw[:match_year.start()].strip()
                year = match_year.group(1)
        if not year and context_year and media_type == 'movie':
            year = context_year
        if media_type == 'movie' and year:
            title_for_search += ' ' + year
        elif media_type in ('episode', 'tv', 'tvshow') and season:
            title_for_search += ' S%02d' % season
        search_type = 'video'
        url = "%s?q=%s&type=%s&sort=best" % (self.search_url, urllib.quote_plus(title_for_search), search_type)
        all_items = []
        current_url = url
        max_pages = 20
        pages_fetched = 0
        while current_url and pages_fetched < max_pages:
            pages_fetched += 1
            items, next_url = self._parse_page(current_url)
            if not items:
                break
            all_items.extend(items)
            if limit and len(all_items) >= int(limit):
                all_items = all_items[:int(limit)]
                break
            current_url = next_url
        if media_type in ('episode', 'tv', 'tvshow') and season:
            all_items = self._filter_tv_items(all_items, season, episode)
        log('[DHTINDEX] Total iteme: %s din %s pagini' % (len(all_items), pages_fetched))
        return self.__class__.__name__, self.name, all_items

    def _filter_tv_items(self, items, season, episode=None):
        s_str = 'S%02d' % season
        ep_str = 'S%02dE%02d' % (season, episode) if episode else None
        filtered = []
        for item in items:
            nume = item.get('nume', '')
            title_upper = nume.upper()
            if s_str not in title_upper:
                continue
            is_pack = False
            if ep_str:
                if ep_str in title_upper:
                    pass
                elif not re.search(r'S%02dE\d{2}' % season, title_upper):
                    is_pack = True
                else:
                    continue
            else:
                if not re.search(r'S%02dE\d{2}' % season, title_upper):
                    is_pack = True
                else:
                    continue
            if is_pack and item.get('info'):
                item['info']['aio_bypass_filter'] = True
            filtered.append(item)
        return filtered

    def _parse_page(self, url):
        items = []
        response = fetchData(url, headers=self.headers())
        if not response:
            return items, None
        blocks = re.findall(r'<div class="py-3 flex[^>]*>(?:.*?</div>){3}\s*</div>', response, re.DOTALL)
        if not blocks:
            return items, None
        for block in blocks:
            try:
                title_m = re.search(r'<a href="/torrent/[^"]+"[^>]*>(.*?)</a>', block, re.DOTALL)
                if not title_m: continue
                title = title_m.group(1).strip()
                if not title: continue
                magnet_m = re.search(r'href="(magnet:\?xt=urn:btih:[^"]+)"', block)
                if not magnet_m: continue
                magnet = magnet_m.group(1)
                size_m = re.search(r'<span>([\d.]+\s*(?:GB|MB|KB|TB|B))</span>', block)
                size = size_m.group(1) if size_m else 'N/A'
                seeds_m = re.search(r'S:\s*(\d+)', block)
                leech_m = re.search(r'L:\s*(\d+)', block)
                seeds = seeds_m.group(1) if seeds_m else '0'
                leechers = leech_m.group(1) if leech_m else '0'
                if not zeroseed and int(seeds) == 0: continue
                seed_color = 'FFFF0000' if seeds == '0' else 'FF00FA9A'
                nume = '%s [B][COLOR FF00FA9A](%s)[/COLOR][/B] [B][COLOR %s][S/L: %s/%s][/COLOR][/B]' % (title, size, seed_color, seeds, leechers)
                info_sec = '[B][COLOR FF00FA9A]Size: %s[/COLOR][/B]  [B][COLOR %s]S/L: %s/%s[/COLOR][/B]' % (size, seed_color, seeds, leechers)
                info_dict = {
                    'Title': title,
                    'Plot': title + '\n' + info_sec,
                    'Size': formatsize(size),
                    'Poster': self.thumb
                }
                items.append({
                    'nume': nume,
                    'legatura': magnet,
                    'imagine': self.thumb,
                    'switch': 'torrent_links',
                    'info': info_dict
                })
            except:
                continue
        next_m = re.search(r'href="(/search\?q=[^"]*?page=\d+)"[^>]*>Next', response)
        next_url = "https://%s%s" % (self.base_url, next_m.group(1)) if next_m else None
        return items, next_url

    def parse_menu(self, url, meniu, info={}, torraction=None, limit=None):
        lists = []
        if meniu == 'cauta':
            from resources.Core import Core
            Core().searchSites({'landsearch': self.__class__.__name__})
        elif meniu == 'get_torrent':
            items, next_url = self._parse_page(url)
            lists.extend(items)
            if next_url:
                lists.append({
                    'nume': 'PAGINA URMATOARE (%d ramase)' % len(items),
                    'legatura': next_url,
                    'imagine': self.nextimage,
                    'switch': 'get_torrent',
                    'info': info
                })
        elif meniu == 'torrent_links':
            action = torraction if torraction else ''
            openTorrent({'Tmode': action, 'Turl': url, 'Tsite': self.__class__.__name__, 'info': info, 'orig_url': url})
        return lists

class yts(Torrent):
    def __init__(self):
        self.base_url = 'yts.bz'
        self.thumb = os.path.join(media, 'yts.png')
        self.name = '[B]YTS[/B]'
        self.api_url = "https://%s/api/v2/list_movies.json" % self.base_url
        self.search_url = "https://%s/browse-movies/%s/all/all/0/downloads/0/all" % (self.base_url, '%s')

        self.menu = [
            ('Recente', "%s?sort_by=date_added&limit=50" % self.api_url, 'cauta_api', self.thumb),
            ('Filme', "%s?limit=50" % self.api_url, 'sortare', self.thumb),
            ('Limba', "%s?sort_by=date_added&limit=50" % self.api_url, 'limba', self.thumb),
            ('Genuri', "%s?limit=50" % self.api_url, 'genre', self.thumb),
            ('Calitate', "%s?limit=50" % self.api_url, 'calitate', self.thumb),
            ('Căutare', self.base_url, 'cauta', self.searchimage)
        ]

        self.sortare = [
            ('Ultimele', 'date_added'),
            ('Cele mai vechi', 'date_added&order_by=asc'),
            ('După seederi', 'seeds'),
            ('După peers', 'peers'),
            ('După ani', 'year'),
            ('După aprecieri', 'like_count'),
            ('După rating', 'rating'),
            ('Alfabetic', 'title'),
            ('După descărcări', 'download_count')
        ]

        self.calitate = [
            ('Toate', 'all'),
            ('720p', '720p'),
            ('1080p', '1080p'),
            ('4K', '2160p'),
            ('3D', '3D')
        ]

        self.limba = [('English', 'en'), ('Foreign', 'foreign'), ('All', 'all'), ('Japanese', 'ja'), ('French', 'fr'), ('Italian', 'it'), ('German', 'de'), ('Spanish', 'es'), ('Chinese', 'zh'), ('Hindi', 'hi'), ('Cantonese', 'cn'), ('Korean', 'ko'), ('Russian', 'ru'), ('Swedish', 'sv'), ('Portuguese', 'pt'), ('Polish', 'pl'), ('Danish', 'da'), ('Norwegian', 'no'), ('Telugu', 'te'), ('Thai', 'th'), ('Dutch', 'nl'), ('Czech', 'cs'), ('Finnish', 'fi'), ('Tamil', 'ta'), ('Vietnamese', 'vi'), ('Turkish', 'tr'), ('Indonesian', 'id'), ('Persian', 'fa'), ('Greek', 'el'), ('Arabic', 'ar'), ('Hebrew', 'he'), ('Hungarian', 'hu'), ('Urdu', 'ur'), ('Tagalog', 'tl'), ('Malay', 'ms'), ('Bangla', 'bn'), ('Romanian', 'ro'), ('Icelandic', 'is'), ('Estonian', 'et'), ('Catalan', 'ca'), ('Malayalam', 'ml'), ('Ukrainian', 'uk'), ('Punjabi', 'pa'), ('xx', 'xx'), ('Serbian', 'sr'), ('Afrikaans', 'af'), ('Kannada', 'kn'), ('Basque', 'eu'), ('Slovak', 'sk'), ('Tibetan', 'bo'), ('Amharic', 'am'), ('Galician', 'gl'), ('Bosnian', 'bs'), ('Latin', 'la'), ('Mongolian', 'mn'), ('Marathi', 'mr'), ('Norwegian', 'nb'), ('Latvian', 'lv'), ('Pashto', 'ps'), ('Southern', 'st'), ('Inuktitut', 'iu'), ('Somali', 'so'), ('Wolof', 'wo'), ('Azerbaijani', 'az'), ('Swahili', 'sw'), ('Abkhazian', 'ab'), ('Haitian', 'ht'), ('Serbo-Croatian', 'sh'), ('Kyrgyz', 'ky'), ('Akan', 'ak'), ('Ossetic', 'os'), ('Luxembourgish', 'lb'), ('Georgian', 'ka'), ('Maori', 'mi'), ('Afar', 'aa'), ('Irish', 'ga'), ('Yiddish', 'yi'), ('Khmer', 'km'), ('Macedonian', 'mk')]

        self.genre = ['Action', 'Adventure', 'Animation', 'Biography', 'Comedy', 'Crime', 'Documentary', 'Drama', 'Family', 'Fantasy', 'Film-Noir', 'Game-Show', 'History', 'Horror', 'Music', 'Musical', 'Mystery', 'News', 'Reality-TV', 'Romance', 'Sci-Fi', 'Sport', 'Talk-Show', 'Thriller', 'War', 'Western']

    def cauta(self, keyword, replace=False, limit=None):
        import xbmcgui, json
        clean_keyword = unquote(keyword).strip()
        imdb_id = None
        m_type = 'movie'

        try:
            window = xbmcgui.Window(10000)
            p_info = window.getProperty('mrsp.playback.info')
            if p_info:
                p_data = json.loads(p_info)
                imdb_id = p_data.get('imdb_id') or p_data.get('imdbnumber')
                m_type = p_data.get('mediatype', 'movie')
        except: pass

        is_serial = m_type in ['episode', 'tv', 'tvshow']
        if not is_serial:
            is_serial = bool(re.search(r'(?i)\bS\d+(?:E\d+)?\b', clean_keyword))

        if is_serial:
            log('[YTS] Serial detectat, skip cautare (YTS are doar filme)')
            return self.__class__.__name__, self.name, []

        if not imdb_id or not str(imdb_id).startswith('tt'):
            m_year = re.search(r'\b(19|20\d{2})\s*$', clean_keyword)
            s_title, year = (clean_keyword[:m_year.start()].strip(), m_year.group(1)) if m_year else (clean_keyword, None)
            _, api_id = get_movie_ids_from_tmdb(s_title, year)
            imdb_id = api_id

        if imdb_id and str(imdb_id).startswith('tt'):
            url = "%s?query_term=%s&limit=50" % (self.api_url, str(imdb_id))
            log('[YTS] Cautare API IMDb: %s' % imdb_id)
        else:
            url = "%s?query_term=%s&limit=50" % (self.api_url, quote(clean_keyword))
            log('[YTS] Cautare API Text: %s' % clean_keyword)

        return self.__class__.__name__, self.name, self.parse_menu(url, 'cauta_api', limit=limit, info={'imdb_id': imdb_id})

    def parse_menu(self, url, meniu, info={}, torraction=None, limit=None):
        lists = []

        # =====================================================
        # API HANDLER - RAPID, fara call-uri externe
        # =====================================================
        if meniu == 'cauta_api':
            log('[YTS] API fetch: %s' % url)
            link = fetchData(url)
            if not link:
                log('[YTS] API: Nu s-a primit raspuns')
                return lists
            try:
                import json
                data = json.loads(link)
                status = data.get('status', '')
                movie_count = data.get('data', {}).get('movie_count', 0)
                log('[YTS] API status=%s movie_count=%s' % (status, movie_count))

                if status == 'ok' and movie_count > 0:
                    count = 0
                    for movie in data['data'].get('movies', []):
                        nume_film = movie.get('title_english') or movie.get('title', '')
                        an = movie.get('year', '')
                        imdb_code = movie.get('imdb_code', '')

                        # Poster din YTS (pentru lista)
                        poster = movie.get('large_cover_image') or movie.get('medium_cover_image') or self.thumb
                        # Background din YTS (pentru buffering UI - GRATIS, fara call extra)
                        fanart = movie.get('background_image_original') or movie.get('background_image', '')

                        nume_complet = '%s (%s)' % (nume_film, an)

                        torrents = movie.get('torrents', [])
                        if not torrents:
                            continue

                        for torrent in torrents:
                            calitate = torrent.get('quality', '')
                            tip = torrent.get('type', '')
                            size_string = torrent.get('size', '0 B')
                            seeds = str(torrent.get('seeds', 0))
                            leechers = str(torrent.get('peers', 0))

                            try:
                                seeds_int = int(seeds)
                            except:
                                seeds_int = 0
                            if not zeroseed and seeds_int == 0:
                                continue

                            hash_t = torrent.get('hash', '')
                            if not hash_t:
                                continue

                            magnet = "magnet:?xt=urn:btih:%s&dn=%s" % (hash_t, quote(nume_complet))
                            trackers = [
                                'udp://open.demonii.com:1337/announce',
                                'udp://tracker.openbittorrent.com:80',
                                'udp://tracker.coppersurfer.tk:6969',
                                'udp://glotorrents.pw:6969/announce',
                                'udp://tracker.opentrackr.org:1337/announce',
                                'udp://exodus.desync.com:6969/announce',
                                'udp://p4p.arenabg.com:1337/announce'
                            ]
                            for tr in trackers:
                                magnet += "&tr=" + quote(tr)

                            # Nume curat primul, detalii dupa
                            nume_torrent = '[B]%s[/B] - %s %s (%s) [S/L: %s/%s]' % (
                                nume_complet, calitate, tip, size_string, seeds, leechers
                            )

                            info_torrent = {
                                'Title': nume_complet,
                                'Plot': '%s\n\n[B]Quality:[/B] [COLOR FF00FA9A]%s %s[/COLOR]\n[B]Size:[/B] [COLOR FFFDBD01]%s[/COLOR]\n[B]S/L:[/B] [COLOR FFFF69B4]%s/%s[/COLOR]' % (
                                    nume_complet, calitate, tip, size_string, seeds, leechers
                                ),
                                'Size': size_string,
                                'Poster': poster,
                                'Fanart': fanart,
                                'imdb_id': imdb_code if imdb_code else info.get('imdb_id', ''),
                            }

                            lists.append({
                                'nume': nume_torrent,
                                'legatura': magnet,
                                'imagine': poster,
                                'fanart': fanart,
                                'switch': 'torrent_links',
                                'info': info_torrent
                            })

                            if limit:
                                count += 1
                                if count >= int(limit):
                                    break

                        if limit and count >= int(limit):
                            break

                    # === PAGINARE ===
                    if not limit:
                        total = data['data'].get('movie_count', 0)
                        limit_api = data['data'].get('limit', 50)
                        page_num = data['data'].get('page_number', 1)

                        if page_num * limit_api < total:
                            if '&page=' in url:
                                next_url = re.sub(r'&page=\d+', '&page=%d' % (page_num + 1), url)
                            else:
                                next_url = '%s&page=%d' % (url, page_num + 1)
                            lists.append({
                                'nume': '[B]>>> Pagina următoare >>>[/B]',
                                'legatura': next_url,
                                'imagine': self.nextimage,
                                'switch': 'cauta_api',
                                'info': info
                            })

                    log('[YTS] API: %d rezultate in %.0fms' % (len(lists), 0))
                else:
                    log('[YTS] API: 0 rezultate')
            except Exception as e:
                log('[YTS] Eroare API: %s' % str(e))
                import traceback
                log('[YTS] Traceback: %s' % traceback.format_exc())
            return lists

        # =====================================================
        # DIALOG CAUTARE
        # =====================================================
        elif meniu == 'cauta':
            from resources.Core import Core
            Core().searchSites({'landsearch': self.__class__.__name__})

        # =====================================================
        # DETALII FILM - fallback pt link-uri vechi
        # =====================================================
        elif meniu == 'get_torrent_links':
            lists = []
            try:
                info_baza = eval(str(info))
                nume_film = info_baza.get('Title', '')
                poster = info_baza.get('Poster', self.thumb)
            except:
                info_baza = {}
                nume_film = ''
                poster = self.thumb

            search_term = ''
            if info_baza.get('imdb_id'):
                search_term = info_baza['imdb_id']
            elif nume_film:
                clean_name = re.sub(r'\[/?B\]', '', nume_film)
                clean_name = re.sub(r'\s*\(\d{4}\)\s*$', '', clean_name).strip()
                search_term = clean_name
            else:
                slug_match = re.search(r'/movies/(.+?)(?:\?|$)', url)
                if slug_match:
                    slug = slug_match.group(1)
                    slug_clean = re.sub(r'-\d{4}$', '', slug)
                    search_term = slug_clean.replace('-', ' ')

            if search_term:
                api_url = "%s?query_term=%s&limit=5" % (self.api_url, quote(str(search_term)))
                log('[YTS] get_torrent_links via API: %s' % api_url)
                api_results = self.parse_menu(api_url, 'cauta_api', info=info_baza)
                if api_results:
                    return api_results

            # Fallback HTML
            log('[YTS] get_torrent_links HTML fallback: %s' % url)
            link = fetchData(url)
            if link:
                regex_baza = r'modal-torrent".+?quality.+?<span>(.+?)</span>.+?-size">(.+?)<.+?-size">(.+?)<.+?"(magnet.+?)"'
                all_seeds = re.findall(r'<span title="Seeds"[^>]*>Seeds</span>\s*([\d,]+)', link)
                all_leechers = re.findall(r'<span title="Leechers"[^>]*>Leechers</span>\s*([\d,]+)', link)
                matches = re.compile(regex_baza, re.DOTALL).findall(link)

                for i, (calitate, calitate2, size, legatura) in enumerate(matches):
                    try:
                        seeds = all_seeds[i].strip().replace(',', '') if i < len(all_seeds) else '0'
                        leechers = all_leechers[i].strip().replace(',', '') if i < len(all_leechers) else '0'
                        size_curat = size.strip()
                        nume_torrent = '[B]%s[/B] - %s %s (%s) [S/L: %s/%s]' % (
                            nume_film, calitate.strip(), calitate2.strip(), size_curat, seeds, leechers
                        )
                        info_torrent = {
                            'Title': nume_torrent,
                            'Plot': '%s\n\n[B]Quality:[/B] [COLOR FF00FA9A]%s %s[/COLOR]\n[B]Size:[/B] [COLOR FFFDBD01]%s[/COLOR]\n[B]S/L:[/B] [COLOR FFFF69B4]%s/%s[/COLOR]' % (
                                nume_film, calitate.strip(), calitate2.strip(), size_curat, seeds, leechers
                            ),
                            'Size': size_curat,
                            'Poster': poster,
                            'Fanart': info_baza.get('Fanart', ''),
                        }
                        if info_baza.get('imdb_id'):
                            info_torrent['imdb_id'] = info_baza['imdb_id']
                        lists.append({
                            'nume': nume_torrent,
                            'legatura': legatura,
                            'imagine': poster,
                            'switch': 'torrent_links',
                            'info': info_torrent
                        })
                    except: continue

        # =====================================================
        # CALITATE
        # =====================================================
        elif meniu == 'calitate':
            for nume, calitate in self.calitate:
                legatura = '%s&quality=%s' % (url, calitate)
                lists.append({
                    'nume': nume,
                    'legatura': legatura,
                    'imagine': self.thumb,
                    'switch': 'sortare',
                    'info': info
                })

        # =====================================================
        # GENURI
        # =====================================================
        elif meniu == 'genre':
            for gen in self.genre:
                legatura = '%s&genre=%s' % (url, gen.lower())
                lists.append({
                    'nume': gen,
                    'legatura': legatura,
                    'imagine': self.thumb,
                    'switch': 'sortare',
                    'info': info
                })

        # =====================================================
        # SORTARE
        # =====================================================
        elif meniu == 'sortare':
            for nume, sortare in self.sortare:
                legatura = '%s&sort_by=%s' % (url, sortare)
                lists.append({
                    'nume': nume,
                    'legatura': legatura,
                    'imagine': self.thumb,
                    'switch': 'cauta_api',
                    'info': info
                })

        # =====================================================
        # LIMBA
        # =====================================================
        elif meniu == 'limba':
            for nume, limba in self.limba:
                legatura = '%s&language=%s' % (url, limba)
                lists.append({
                    'nume': nume,
                    'legatura': legatura,
                    'imagine': self.thumb,
                    'switch': 'cauta_api',
                    'info': info
                })

        # =====================================================
        # DESCHIDE TORRENT
        # =====================================================
        elif meniu == 'torrent_links':
            action = torraction if torraction else ''
            openTorrent(self._get_torrent_params(url, info, torraction))

        return lists
# =====================================================================
# INCEPUT ADĂUGARE METEOR: Clasa pentru providerul Meteor (Stremio JSON)
# =====================================================================
class meteor(Torrent):
    def __init__(self):
        self.base_url = 'meteorfortheweebs.midnightignite.me'
        self.thumb = os.path.join(media, 'meteor.png')
        self.name = '[B]Meteor[/B]'
        self.config = 'eyJkZWJyaWRTZXJ2aWNlIjoidG9ycmVudCIsImRlYnJpZEFwaUtleSI6IiIsImNhY2hlZE9ubHkiOmZhbHNlLCJyZW1vdmVUcmFzaCI6dHJ1ZSwicmVtb3ZlU2FtcGxlcyI6dHJ1ZSwicmVtb3ZlQWR1bHQiOnRydWUsImV4Y2x1ZGUzRCI6dHJ1ZSwiZW5hYmxlU2VhRGV4IjpmYWxzZSwibWluU2VlZGVycyI6NSwibWF4UmVzdWx0cyI6NTAsIm1heFJlc3VsdHNQZXJSZXMiOjAsIm1heFNpemUiOjAsInJlc29sdXRpb25zIjpbIjRrIiwiMTA4MHAiLCI3MjBwIl0sImxhbmd1YWdlcyI6eyJwcmVmZXJyZWQiOlsiZW4iXSwicmVxdWlyZWQiOltdLCJleGNsdWRlIjpbXX0sInJlc3VsdEZvcm1hdCI6WyJ0aXRsZSIsInF1YWxpdHkiLCJzaXplIiwiYXVkaW8iLCJzZWVkZXJzIiwic291cmNlIl0sInNvcnRPcmRlciI6WyJyZXNvbHV0aW9uIiwic2VlZGVycyIsInBhY2siLCJzaXplIiwicXVhbGl0eSIsImNhY2hlZCIsImxhbmd1YWdlIiwic2VhZGV4Il19'
        self.menu = [('Căutare', self.base_url, 'cauta', self.searchimage)]

    def headers(self):
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json'
        }

    def get_size(self, bytess):
        try:
            bytess = float(bytess)
            alternative = [(1024**5, ' PB'), (1024**4, ' TB'), (1024**3, ' GB'), (1024**2, ' MB'), (1024**1, ' KB'), (1024**0, ' B')]
            for factor, suffix in alternative:
                if bytess >= factor: break
            amount = round(bytess / factor, 2)
            return str(amount) + suffix
        except: return "0 B"

    def _extract_from_desc(self, desc, emoji_py3, emoji_py2):
        try:
            if py3: match = re.search(re.escape(emoji_py3) + r'\s*(.+?)(?:\n|$)', desc)
            else: match = re.search(re.escape(emoji_py2) + r'\s*(.+?)(?:\n|$)', desc)
            if match: return match.group(1).strip()
        except: pass
        return ''

    def _clean_emojis(self, text):
        if not text: return text
        text = re.sub(r'(?i)Meteor\s+-\s+', '', text)
        if py3: emojis = ['📄', '⭐', '🔊', '💾', '👤', '👥', '☁️', '🎥', '🎬', '🔗', '🔨', '📺', '🎞', '🏷', '📦', '✅', '❌', '⚡', '🌐', '📡']
        else: emojis = ['\xf0\x9f\x93\x84','\xe2\xad\x90','\xf0\x9f\x94\x8a','\xf0\x9f\x92\xbe','\xf0\x9f\x91\xa4','\xf0\x9f\x91\xa5','\xe2\x98\x81\xef\xb8\x8f','\xe2\x98\x81','\xf0\x9f\x8e\xa5','\xf0\x9f\x8e\xac','\xf0\x9f\x94\x97','\xf0\x9f\x94\xa8']
        for e in emojis: text = text.replace(e, '')
        return text.strip()

    def cauta(self, keyword, replace=False, limit=None):
        import xbmcgui, json
        imdb_id, m_type, season, episode = None, 'movie', None, None
        clean_kw = unquote(keyword).strip()
        
        if clean_kw.startswith('tt') and len(clean_kw) > 6:
            imdb_id = clean_kw
        
        if not imdb_id:
            try:
                win = xbmcgui.Window(10000)
                p_info = win.getProperty('mrsp.playback.info')
                if p_info:
                    p_data = json.loads(p_info)
                    imdb_id = p_data.get('imdb_id') or p_data.get('imdbnumber')
                    m_type = p_data.get('mediatype', 'movie')
                    season = p_data.get('season')
                    episode = p_data.get('episode')
            except: pass

        m_s_e = re.search(r'(.*?)\s+S(\d+)(?:E(\d+))?', clean_kw, re.IGNORECASE)
        if m_s_e:
            title = m_s_e.group(1).strip()
            if not season: season = int(m_s_e.group(2))
            ep_str = m_s_e.group(3)
            if not episode: episode = int(ep_str) if ep_str else 1
            m_type = 'episode' if ep_str else 'tv'
            if not imdb_id or not str(imdb_id).startswith('tt'):
                _, imdb_id = get_show_ids_from_tmdb(title)
        elif not imdb_id or not str(imdb_id).startswith('tt'):
            y_m = re.search(r'\b(19|20\d{2})\s*$', clean_kw)
            title, year = (clean_kw[:y_m.start()].strip(), y_m.group(1)) if y_m else (clean_kw, None)
            _, imdb_id = get_movie_ids_from_tmdb(title, year)
            if not imdb_id:
                _, api_id_tv = get_show_ids_from_tmdb(title)
                if api_id_tv:
                    imdb_id = api_id_tv
                    m_type, season, episode = 'tv', 1, 1

        if not imdb_id or not str(imdb_id).startswith('tt'):
            log('[Meteor] Failed to resolve IMDB ID for keyword: %s' % clean_kw)
            return self.__class__.__name__, self.name, []

        st_id = "%s:%s:%s" % (imdb_id, season or 1, episode or 1) if m_type in ['episode','tv','tvshow'] else imdb_id
        st_type = "series" if m_type in ['episode','tv','tvshow'] else "movie"
        url = "https://%s/%s/stream/%s/%s.json" % (self.base_url, self.config, st_type, st_id)
        
        return self.__class__.__name__, self.name, self.parse_menu(url, 'get_torrent', info={'imdb_id': imdb_id}, limit=limit)

    def parse_menu(self, url, meniu, info={}, torraction=None, limit=None):
        lists = []
        if meniu == 'cauta':
            from resources.Core import Core
            Core().searchSites({'landsearch': self.__class__.__name__})
        elif meniu == 'get_torrent' or meniu == 'recente':
            import re
            page = 1
            page_match = re.search(r'[\?&]page=(\d+)', url)
            if page_match: page = int(page_match.group(1))
            clean_url = re.sub(r'[\?&]page=\d+', '', url)
            
            response = makeRequest(clean_url, name=self.__class__.__name__, headers=self.headers(), timeout=5)
            
            if response:
                import json
                try:
                    if not response.strip().startswith('{'): return []
                    data = json.loads(response.strip())
                    streams = data.get('streams', [])
                    b4k, b1080, b720 = [], [], []

                    for stream in streams:
                        try:
                            bh = stream.get('behaviorHints', {})
                            title_orig = bh.get('filename') or stream.get('title') or stream.get('name', '')
                            if not title_orig: continue
                            desc = stream.get('description', '')
                            meta_name = stream.get('name', '').upper()
                            full_check = (title_orig + " " + desc + " " + meta_name).upper()

                            res_p, res_l = 0, ""
                            if any(x in full_check for x in ['2160P', '4K', 'UHD']): res_p, res_l = 4, "4K"
                            elif '1080P' in full_check: res_p, res_l = 3, "1080p"
                            elif '720P' in full_check: res_p, res_l = 2, "720p"
                            if res_p < 2: continue

                            junk = r'(?i)\b(trailer|sample|cam|camrip|hdts|hdtc|ts|telesync|scr|screener|preair|clip|preview)\b'
                            if re.search(junk, title_orig) or re.search(junk, desc): continue

                            # EXTRAGERE SEEDERI (Dupa emoji 👥)
                            peers_int = 0
                            seed_match = re.search(r'(?:👥|peers)\s*(\d+)', desc, re.IGNORECASE)
                            if seed_match: 
                                peers_int = int(seed_match.group(1))
                            else:
                                # Fallback: cautam cifre izolate
                                nums = re.findall(r'\b(\d+)\b', desc)
                                if nums: peers_int = int(nums[-1]) # Ultimul numar e de obicei peers
                            if peers_int == 0: peers_int = 1

                            if not zeroseed and peers_int == 0: continue

                            # EXTRAGERE SURSA (Dupa emoji 🔗)
                            provider_source = ""
                            source_match = re.search(r'(?:🔗|Source)\s*([^\n]+)', desc, re.IGNORECASE)
                            if source_match:
                                provider_source = source_match.group(1).strip()

                            title = title_orig
                            if ' / ' in title: title = title.split(' / ')[-1]
                            title = self._clean_emojis(title)
                            title = re.sub(r'^[ \t\-\.\:📄]+', '', title).strip()

                            size = "N/A"
                            if bh.get('videoSize'): size = self.get_size(bh.get('videoSize'))
                            else:
                                sz_m = re.search(r'([\d\.]+\s*[KMGT]B)', desc, re.IGNORECASE)
                                if sz_m: size = sz_m.group(1)

                            magnet = "magnet:?xt=urn:btih:%s" % stream.get('infoHash')
                            for s_url in stream.get('sources', []):
                                if s_url.startswith('tracker:'): magnet += "&tr=" + quote(s_url.replace('tracker:', ''))

                            quality = self._extract_from_desc(desc, '⭐', '\xe2\xad\x90')
                            audio = self._extract_from_desc(desc, '🔊', '\xf0\x9f\x94\x8a')
                            
                            plot_lines = ['[B][COLOR white]%s[/COLOR][/B]' % title, '', '[B]Rezoluție: [COLOR yellow]%s[/COLOR][/B]' % res_l]
                            v_tech = []
                            if re.search(r'\bDV\b|DOVI|DOLBY.?VISION', title, re.IGNORECASE): v_tech.append('Dolby Vision')
                            if re.search(r'\bHDR(?:10\+?)?\b', title, re.IGNORECASE): v_tech.append('HDR')
                            if v_tech: plot_lines.append('[B]Video: [COLOR magenta]%s[/COLOR][/B]' % ' / '.join(v_tech))
                            if quality: plot_lines.append('[B]Calitate: [COLOR lightskyblue]%s[/COLOR][/B]' % quality)
                            if audio: plot_lines.append('[B]Audio: [COLOR orange]%s[/COLOR][/B]' % audio)
                            plot_lines.append('[B]Mărime: [COLOR FF00FA9A]%s[/COLOR][/B]' % size)
                            plot_lines.append('[B]Peers: [COLOR FFFF69B4]%s[/COLOR][/B]' % peers_int)
                            if provider_source: plot_lines.append('[B]Surse: [COLOR gray]%s[/COLOR][/B]' % provider_source)
                            plot_lines.append(''), plot_lines.append('[B]Provider: [COLOR FFFDBD01]Meteor[/COLOR][/B]')

                            nume_afisat = '%s  [B][COLOR FFFDBD01]Meteor[/COLOR][/B] [B][COLOR FF00FA9A](%s)[/COLOR][/B] [B][COLOR FFFF69B4][S: %s][/COLOR][/B]' % (title, size, peers_int)

                            info_dict = {
                                'Title': title, 
                                'Plot': '\n'.join(plot_lines), 
                                'Size': size, 
                                'Poster': self.thumb,
                                'Genre': provider_source # Trimitem Providerul Original in Genre pt results_window
                            }
                            if info.get('imdb_id'): info_dict['imdb_id'] = info['imdb_id']
                            if info.get('tmdb_id'): info_dict['tmdb_id'] = info['tmdb_id']

                            item_data = {'peers': peers_int, 'item': {'nume': nume_afisat, 'legatura': magnet, 'imagine': self.thumb, 'switch': 'torrent_links', 'info': info_dict}}
                            
                            if res_p == 4: b4k.append(item_data)
                            elif res_p == 3: b1080.append(item_data)
                            elif res_p == 2: b720.append(item_data)
                        except: continue

                    b4k.sort(key=lambda x: x['peers'], reverse=True)
                    b1080.sort(key=lambda x: x['peers'], reverse=True)
                    b720.sort(key=lambda x: x['peers'], reverse=True)

                    final_sorted = []
                    max_slices = max(len(b4k), len(b1080))
                    for i in range(0, max_slices, 25):
                        final_sorted.extend(b4k[i:i+25])
                        final_sorted.extend(b1080[i:i+25])
                    final_sorted.extend(b720)

                    start_idx = (page - 1) * 50
                    end_idx = start_idx + 50
                    
                    for res in final_sorted[start_idx:end_idx]: lists.append(res['item'])

                    if len(final_sorted) > end_idx:
                        next_url = clean_url + ('&' if '?' in clean_url else '?') + 'page=' + str(page + 1)
                        lists.append({
                            'nume': 'PAGINA URMATOARE (%d ramase)' % (len(final_sorted) - end_idx),
                            'legatura': next_url, 'imagine': self.nextimage, 'switch': 'get_torrent', 'info': info
                        })
                except Exception as e: log('[Meteor] Error: %s' % str(e))

        elif meniu == 'torrent_links':
            openTorrent(self._get_torrent_params(url, info, torraction))
        return lists

# =====================================================================
# INCEPUT ADĂUGARE COMET: Clasa pentru providerul Comet (Stremio JSON)
# =====================================================================
class comet(Torrent):
    def __init__(self):
        self.base_url = 'cometfortheweebs.midnightignite.me'
        self.thumb = os.path.join(media, 'comet.png')
        self.name = '[B]Comet[/B]'
        self.config = 'eyJtYXhSZXN1bHRzUGVyUmVzb2x1dGlvbiI6MCwibWF4U2l6ZSI6MCwiY2FjaGVkT25seSI6ZmFsc2UsInNvcnRDYWNoZWRVbmNhY2hlZFRvZ2V0aGVyIjpmYWxzZSwicmVtb3ZlVHJhc2giOnRydWUsInJlc3VsdEZvcm1hdCI6WyJhbGwiXSwiZGVicmlkU2VydmljZXMiOltdLCJlbmFibGVUb3JyZW50Ijp0cnVlLCJkZWR1cGxpY2F0ZVN0cmVhbXMiOmZhbHNlLCJzY3JhcGVEZWJyaWRBY2NvdW50VG9ycmVudHMiOmZhbHNlLCJkZWJyaWRTdHJlYW1Qcm94eVBhc3N3b3JkIjoiIiwibGFuZ3VhZ2VzIjp7InJlcXVpcmVkIjpbXSwiYWxsb3dlZCI6W10sImV4Y2x1ZGUiOltdLCJwcmVmZXJyZWQiOltdfSwicmVzb2x1dGlvbnMiOnsicjU3NnAiOmZhbHNlLCJyNDgwcCI6ZmFsc2UsInIzNjBwIjpmYWxzZSwicjI0MHAiOmZhbHNlfSwib3B0aW9ucyI6eyJyZW1vdmVfcmFua3NfdW5kZXIiOi0xMDAwMDAwMDAwMCwiYWxsb3dfZW5nbGlzaF9pbl9sYW5ndWFnZXMiOmZhbHNlLCJyZW1vdmVfdW5rbm93bl9sYW5ndWFnZXMiOmZhbHNlfX0='
        self.menu = [('Căutare', self.base_url, 'cauta', self.searchimage)]

    def headers(self):
        return {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)','Accept': 'application/json'}

    def get_size(self, bytess):
        try:
            bytess = float(bytess)
            for unit in ['B','KB','MB','GB','TB']:
                if bytess < 1024.0: return "%3.2f %s" % (bytess, unit)
                bytess /= 1024.0
        except: return "0 B"

    def _clean_text(self, text):
        if not text: return text
        if py3:
            emojis = ['📄','📹','🔊','⭐','👤','💾','🔎','🏷️','🌎','🇬🇧','🇵🇹','🎥','🎬','👥','🎞️','🎞', '🇪🇸', '🇮🇹']
            for e in emojis: text = text.replace(e, '')
        else:
            emojis = ['\xf0\x9f\x93\x84','\xf0\x9f\x93\xb9','\xf0\x9f\x94\x8a','\xe2\xad\x90','\xf0\x9f\x91\xa4','\xf0\x9f\x92\xbe','\xf0\x9f\x94\x8e']
            for e in emojis: text = text.replace(e, '')
        return text.strip()

    def cauta(self, keyword, replace=False, limit=None):
        import xbmcgui, json
        imdb_id, m_type, season, episode = None, 'movie', None, None
        try:
            win = xbmcgui.Window(10000)
            data = json.loads(win.getProperty('mrsp.playback.info'))
            imdb_id = data.get('imdb_id') or data.get('imdbnumber')
            m_type, season, episode = data.get('mediatype', 'movie'), data.get('season'), data.get('episode')
        except: pass

        clean_kw = unquote(keyword).strip()
        m_s_e = re.search(r'(.*?)\s+S(\d+)(?:E(\d+))?', clean_kw, re.IGNORECASE)
        if m_s_e:
            title = m_s_e.group(1).strip()
            if not season: season = int(m_s_e.group(2))
            ep_s = m_s_e.group(3)
            if not episode: episode = int(ep_s) if ep_s else 1
            m_type = 'episode' if ep_s else 'tv'
            if not imdb_id or not str(imdb_id).startswith('tt'):
                _, imdb_id = get_show_ids_from_tmdb(title)
        elif not imdb_id or not str(imdb_id).startswith('tt'):
            y_m = re.search(r'\b(19|20\d{2})\s*$', clean_kw)
            title, year = (clean_kw[:y_m.start()].strip(), y_m.group(1)) if y_m else (clean_kw, None)
            _, imdb_id = get_movie_ids_from_tmdb(title, year)
            if not imdb_id:
                _, api_id_tv = get_show_ids_from_tmdb(title)
                if api_id_tv:
                    imdb_id = api_id_tv
                    m_type, season, episode = 'tv', 1, 1

        if not imdb_id: return self.__class__.__name__, self.name, []

        st_id = "%s:%s:%s" % (imdb_id, season or 1, episode or 1) if m_type in ['episode','tv','tvshow'] else imdb_id
        st_type = "series" if m_type in ['episode','tv','tvshow'] else "movie"
        url = "https://%s/%s/stream/%s/%s.json" % (self.base_url, self.config, st_type, st_id)
        
        return self.__class__.__name__, self.name, self.parse_menu(url, 'get_torrent', info={'imdb_id': imdb_id}, limit=None)

    def parse_menu(self, url, meniu, info={}, torraction=None, limit=None):
        lists = []
        if meniu == 'cauta':
            from resources.Core import Core
            Core().searchSites({'landsearch': self.__class__.__name__})
        elif meniu == 'get_torrent' or meniu == 'recente':
            import re
            page = 1
            p_m = re.search(r'[\?&]page=(\d+)', url)
            if p_m: page = int(p_m.group(1))
            clean_url = re.sub(r'[\?&]page=\d+', '', url)
            response = makeRequest(clean_url, name=self.__class__.__name__, headers=self.headers(), timeout=15)
            
            if response:
                import json
                try:
                    if not response.strip().startswith('{'): return []
                    data = json.loads(response.strip())
                    streams = data.get('streams', [])
                    b4k, b1080, b720 = [], [], []

                    for stream in streams:
                        try:
                            bh = stream.get('behaviorHints', {})
                            desc = stream.get('description', '')
                            name_orig = stream.get('name', '')
                            info_hash = stream.get('infoHash')
                            if not info_hash: continue

                            # 1. Extragere Titlu
                            # Comet pune fisierul real pe prima linie, dupa emoji-ul 📄
                            title_orig = bh.get('filename')
                            if not title_orig:
                                first_line = desc.split('\n')[0]
                                if '📄' in first_line:
                                    title_orig = first_line.split('📄')[1].strip()
                                else:
                                    title_orig = first_line.strip()
                            
                            # Curatare text
                            clean_title_line = self._clean_text(title_orig)

                            # 2. Extragere Provider Sursa (dupa emoji 🔎)
                            provider_source = ""
                            source_match = re.search(r'(?:🔎|Source)\s*([^\n]+)', desc, re.IGNORECASE)
                            if source_match:
                                provider_source = source_match.group(1).strip()

                            # 3. Detectie Rezolutie
                            full_check = (name_orig + " " + title_orig + " " + desc).upper()
                            res_p, res_l = 0, ""
                            if any(x in full_check for x in ['2160P', '4K', 'UHD']): res_p, res_l = 4, "4K"
                            elif '1080P' in full_check: res_p, res_l = 3, "1080p"
                            elif '720P' in full_check: res_p, res_l = 2, "720p"
                            if res_p < 2: continue

                            # Junk
                            if re.search(r'(?i)\b(trailer|sample|cam|camrip|hdts|hdtc|ts|telesync|scr|screener|preair|clip)\b', title_orig): continue

                            # 4. Extragere SEEDERI (dupa emoji 👤)
                            seeds = "0"
                            seed_match = re.search(r'(?:👤|Seeders?)\s*(\d+)', desc, re.IGNORECASE)
                            if seed_match: seeds = seed_match.group(1)
                            peers_int = int(seeds)
                            if peers_int == 0: peers_int = 1
                            if not zeroseed and peers_int == 0: continue

                            # 5. Extragere SIZE
                            size = "N/A"
                            if bh.get('videoSize'):
                                size = self.get_size(bh.get('videoSize'))
                            else:
                                m_size = re.search(r'([\d\.]+\s*[KMGT]B)', desc, re.IGNORECASE)
                                if m_size: size = m_size.group(1)

                            # 6. Magnet
                            magnet = "magnet:?xt=urn:btih:%s" % info_hash
                            for s_url in stream.get('sources', []):
                                if s_url.startswith('tracker:'): magnet += "&tr=" + quote(s_url.replace('tracker:', ''))

                            # 7. Constructie Nume Afisat (Lista)
                            n_afisat = '%s  [B][COLOR FFFDBD01]Comet[/COLOR][/B] [B][COLOR FF00FA9A](%s)[/COLOR][/B] [B][COLOR FFFF69B4][S: %s][/COLOR][/B]' % (clean_title_line, size, seeds)

                            # 8. Plot Detaliat (in Stanga)
                            plot = ['[B][COLOR white]%s[/COLOR][/B]' % clean_title_line, '', '[B]Rezoluție: [COLOR yellow]%s[/COLOR][/B]' % res_l]
                            if "HDR" in full_check: plot.append('[B]Video: [COLOR magenta]HDR[/COLOR][/B]')
                            if "DV" in full_check: plot.append('[B]Video: [COLOR magenta]Dolby Vision[/COLOR][/B]')
                            if "SDR" in full_check: plot.append('[B]Video: [COLOR magenta]SDR[/COLOR][/B]')
                            
                            plot.append('[B]Mărime: [COLOR FF00FA9A]%s[/COLOR][/B]' % size)
                            plot.append('[B]Seederi: [COLOR FFFF69B4]%s[/COLOR][/B]' % seeds)
                            if provider_source: plot.append('[B]Sursă Originală: [COLOR cyan]%s[/COLOR][/B]' % provider_source)
                            plot.extend(['', '[B]Provider: [COLOR FFFDBD01]Comet[/COLOR][/B]'])

                            info_d = {
                                'Title': clean_title_line, 
                                'Plot': '\n'.join(plot), 
                                'Size': size, 
                                'Poster': self.thumb,
                                'Genre': provider_source # Trimitem provider-ul prin Genre
                            }
                            if info.get('imdb_id'): info_d['imdb_id'] = info['imdb_id']
                            if info.get('tmdb_id'): info_d['tmdb_id'] = info['tmdb_id']

                            item_f = {'peers': peers_int, 'item': {'nume': n_afisat, 'legatura': magnet, 'imagine': self.thumb, 'switch': 'torrent_links', 'info': info_d}}
                            
                            if res_p == 4: b4k.append(item_f)
                            elif res_p == 3: b1080.append(item_f)
                            elif res_p == 2: b720.append(item_f)
                        except: continue

                    b4k.sort(key=lambda x: x['peers'], reverse=True)
                    b1080.sort(key=lambda x: x['peers'], reverse=True)
                    b720.sort(key=lambda x: x['peers'], reverse=True)

                    f_sorted = []
                    for i in range(0, max(len(b4k), len(b1080)), 25):
                        f_sorted.extend(b4k[i:i+25]); f_sorted.extend(b1080[i:i+25])
                    f_sorted.extend(b720)

                    start, end = (page-1)*50, page*50
                    for res in f_sorted[start:end]: lists.append(res['item'])

                    if len(f_sorted) > end:
                        lists.append({'nume': 'PAGINA URMATOARE (%d ramase)' % (len(f_sorted)-end), 'legatura': clean_url+('&' if '?' in clean_url else '?')+'page='+str(page+1), 'imagine': self.nextimage, 'switch': 'get_torrent', 'info': info})
                except Exception as e: log('[Comet] Error: %s' % str(e))

        elif meniu == 'torrent_links':
            openTorrent(self._get_torrent_params(url, info, torraction))
        return lists
        

# =====================================================================
# INCEPUT ADĂUGARE HEARTIVE: Agregator Torrentio, MediaFusion, PB+
# =====================================================================
class heartive(Torrent):
    def __init__(self):
        self.base_url = 'heartive'
        self.thumb = os.path.join(media, 'heartive.png')
        self.name = '[B]Heartive[/B]'
        # API-urile pe care le foloseste Heartive
        self.apis = [
            {"name": "Torrentio", "url": "https://torrentio.strem.fun/providers=yts,eztv,rarbg,1337x,thepiratebay,kickasstorrents,torrentgalaxy,magnetdl,horriblesubs,nyaasi,tokyotosho,anidex"},
            {"name": "MediaFusion", "url": "https://mediafusionfortheweebs.midnightignite.me/D-MgIOYBm8hyaUIwwpw-vb7g1DkYuDWlVkR8yC2LTS3b7ejVz5s0yzfMZ1Gf5CxiqtreQCeRCfLfLhOWTFkTDsQL8ozlOF6Sig9mbbuqGnKCFO46BLz3EoWk2OGlL5oM7dpIsTJXVyJC7zWVlgRHXhPy8C-kzUcMHgCJwcFQ-p877sugPoevStrllmYQou9DPpyzbR87R58nJNFrrOj7AoAWK3EkJjAZrvA-t1JCXrrjKWJ-F5FBg4kP9NZ3-6kF8ukse-wG2rU1-xRrHa9r-oya4KwNbR7wYqc2RJVk8WZ5NlKl9SyhS-_FaCGLHinIvG_Spgi-_f9f1aEAVE6_f6rEF-23ajBhmoRu7E3-_F6Fzaahv5sXXG4PkOC62GE37K3OeWZf9X2x-zoIlvmDd6mQ6PAsbKrmhxZbe71uccjWeSjvAOd4iamk1dUiGZp_KPlgjFIEsp98dg7DDG_bXn2klWQuJspM_Pqnaa2T1v8VMuYkqEGcYfAlxYEDKwmB_FIGla9SB5eK2kxZ6NfY3eruKJZ-RDGll9oiTRql9boUeooCAIg839XoenYcHred5wx7r_j5Yx0yUAuC9gytKArPajtIc46TDa4bNsO3ugvJ8U2kKLkLcrCaDSyi3daFSS3Yw_zyv7OeNH2ZH-5UoGgiR49kxLUiGhhR0eM724890haspz40N1JyUeexC620OyAdYIm47hfshxAToEKnPL3fr3L9_HwjwAtxUTWTIO3mLc-RLUz_BDOxeSqKyW-ogq_iTYOVmKBrLVPuQhYIBTSHoZ9fwS4K6UalaQVSADTbun-Nw8xpW6uy9_pLXn-fzw0S-t7is3U63gAkET_f6y30LkWbkuCBF-haoyx7f8i6fMoDZ-i3JedLGw1ReXIK-SKUqo7a0OOWuZF97A-GPyYOu34TZTcGLL3YH-XbZm0kPMXUh9gIM5-vMbafSaZKobLIAg4LSHb0IQVmpQKUqiifXfjhQx7xdwgdTg0aZ-MUa1kZ__vAvWonmAlIXKoj3myCZ3CO4NhzMS90D4rcD7cMx5NGP5fG6EQVbnlyrfpqcT1bsuz1rk5QeIyhGGhRyivaJbJfCC9a5kGtiO9gFBkiDiRnq8Lmy_ADqcTnZYYc5vgbgCDHjZRW3uh2PT61UzN6oWnisSHMQUQWu_KwpAHQ"},
            {"name": "PirateBay+", "url": "https://thepiratebay-plus.strem.fun"}
        ]
        self.menu = [('Căutare', self.base_url, 'cauta', self.searchimage)]

    def headers(self):
        return {'User-Agent': 'Mozilla/5.0','Accept': 'application/json'}

    def get_size(self, bytess):
        try:
            bytess = float(bytess)
            for unit in ['B','KB','MB','GB','TB']:
                if bytess < 1024.0: return "%3.2f %s" % (bytess, unit)
                bytess /= 1024.0
        except: return "0 B"

    def _clean_text(self, text):
        if not text: return text
        if py3:
            emojis = ['📄','📹','🔊','⭐','👤','💾','🔎','🏷️','🌎','🇬🇧','🇵🇹','🎥','🎬','👥','🎞️','🎞']
            for e in emojis: text = text.replace(e, '')
        else:
            emojis = ['\xf0\x9f\x93\x84','\xf0\x9f\x93\xb9','\xf0\x9f\x94\x8a','\xe2\xad\x90','\xf0\x9f\x91\xa4','\xf0\x9f\x92\xbe','\xf0\x9f\x94\x8e']
            for e in emojis: text = text.replace(e, '')
        return text.strip()

    def cauta(self, keyword, replace=False, limit=None):
        import xbmcgui, json
        imdb_id, m_type, season, episode = None, 'movie', None, None
        try:
            win = xbmcgui.Window(10000)
            playback_info_str = win.getProperty('mrsp.playback.info')
            if playback_info_str:
                p_data = json.loads(playback_info_str)
                imdb_id = p_data.get('imdb_id') or p_data.get('imdbnumber')
                m_type, season, episode = p_data.get('mediatype', 'movie'), p_data.get('season'), p_data.get('episode')
        except: pass

        clean_kw = unquote(keyword).strip()
        m_s_e = re.search(r'(.*?)\s+S(\d+)(?:E(\d+))?', clean_kw, re.IGNORECASE)
        if m_s_e:
            title = m_s_e.group(1).strip()
            if not season: season = int(m_s_e.group(2))
            ep_s = m_s_e.group(3)
            if not episode: episode = int(ep_s) if ep_s else 1
            m_type = 'episode' if ep_s else 'tv'
            if not imdb_id or not str(imdb_id).startswith('tt'):
                _, imdb_id = get_show_ids_from_tmdb(title)
        elif not imdb_id or not str(imdb_id).startswith('tt'):
            y_m = re.search(r'\b(19|20\d{2})\s*$', clean_kw)
            title, year = (clean_kw[:y_m.start()].strip(), y_m.group(1)) if y_m else (clean_kw, None)
            _, imdb_id = get_movie_ids_from_tmdb(title, year)
            if not imdb_id:
                _, api_id_tv = get_show_ids_from_tmdb(title)
                if api_id_tv:
                    imdb_id = api_id_tv
                    m_type, season, episode = 'tv', 1, 1

        if not imdb_id: return self.__class__.__name__, self.name, []

        p_info = {'imdb_id': imdb_id, 'media_type': m_type, 'season': season, 'episode': episode, 'page': 1}
        return self.__class__.__name__, self.name, self.parse_menu(str(p_info), 'get_torrent', limit=limit)

    def parse_menu(self, p_info_raw, meniu, info={}, torraction=None, limit=None):
        lists = []
        if meniu == 'cauta':
            from resources.Core import Core
            Core().searchSites({'landsearch': self.__class__.__name__})
        
        elif meniu == 'get_torrent' or meniu == 'recente':
            import json, re
            try:
                if isinstance(p_info_raw, dict): p_info = p_info_raw
                else: p_info = eval(p_info_raw)
            except: return []

            imdb_id = p_info.get('imdb_id')
            m_type = p_info.get('media_type')
            page = int(p_info.get('page', 1))
            
            if m_type in ['episode', 'tv', 'tvshow']:
                path = "series/%s:%s:%s.json" % (imdb_id, p_info.get('season') or 1, p_info.get('episode') or 1)
            else:
                path = "movie/%s.json" % imdb_id

            b4k, b1080, b720 = [], [], []
            seen_hashes = set()

            for target in self.apis:
                try:
                    full_url = "%s/stream/%s" % (target['url'], path)
                    resp = makeRequest(full_url, name=self.__class__.__name__, headers=self.headers(), timeout=5) # Timeout mai mare pt agregator
                    if not resp: continue
                    
                    data = json.loads(resp)
                    for stream in data.get('streams', []):
                        try:
                            info_hash = stream.get('infoHash')
                            if not info_hash or info_hash in seen_hashes: continue
                            
                            bh = stream.get('behaviorHints', {})
                            title_orig = bh.get('filename') or stream.get('title') or stream.get('description', '')
                            desc = stream.get('description', '') or stream.get('title', '')
                            
                            # 1. FILTRARE JUNK
                            junk_pattern = r'(?i)\b(trailer|sample|cam|camrip|hdts|hdtc|ts|telesync|scr|screener|preair|clip|preview|tc|hc)\b'
                            if re.search(junk_pattern, title_orig) or re.search(junk_pattern, desc):
                                continue

                            # 2. DETECTIE REZOLUTIE
                            full_check = (title_orig + " " + desc).upper()
                            res_p, res_l = 0, ""
                            if any(x in full_check for x in ['2160P', '4K', 'UHD']): res_p, res_l = 4, "4K"
                            elif '1080P' in full_check: res_p, res_l = 3, "1080p"
                            elif '720P' in full_check: res_p, res_l = 2, "720p"
                            if res_p < 2: continue

                            # 3. PEERS & SIZE
                            seeds_m = re.search(r'👤\s*(\d+)', desc) or re.search(r'(\d+)\s*seeders', desc, re.IGNORECASE)
                            seeds = int(seeds_m.group(1)) if seeds_m else 0
                            
                            if not zeroseed and seeds == 0: continue

                            size = "N/A"
                            if bh.get('videoSize'): size = self.get_size(bh.get('videoSize'))
                            else:
                                sz_m = re.search(r'([\d\.]+\s*[KMGT]B)', desc, re.IGNORECASE)
                                if sz_m: size = sz_m.group(1)

                            # 4. CURATARE TITLU
                            title = title_orig
                            if ' / ' in title: title = title.split(' / ')[-1]
                            title = title.split('\n')[0].replace('\r', '').strip()
                            title = self._clean_text(title)
                            title = re.sub(r'^[ \t\-\.\:📄]+', '', title).strip()

                            # 5. CONSTRUIRE NUME AFISAT
                            n_afisat = '%s  [B][COLOR FFFDBD01]Heartive[/COLOR][/B] [B][COLOR FF00FA9A](%s)[/COLOR][/B] [B][COLOR FFFF69B4][S: %s][/COLOR][/B]' % (title, size, seeds)

                            # 6. PLOT STÂNGA
                            plot = ['[B][COLOR white]%s[/COLOR][/B]' % title, '', '[B]Rezoluție: [COLOR yellow]%s[/COLOR][/B]' % res_l]
                            plot.append('[B]Mărime: [COLOR FF00FA9A]%s[/COLOR][/B]' % size)
                            plot.append('[B]Seederi: [COLOR FFFF69B4]%s[/COLOR][/B]' % seeds)
################################ MODIFICARE START: IDENTIFICARE API SURSA HEARTIVE ################################
                            # Sursa este numele API-ului (Torrentio / MediaFusion / PirateBay+)
                            plot.append('[B]Sursă: [COLOR cyan]%s[/COLOR][/B]' % target['name'])
                            plot.extend(['', '[B]Provider: [COLOR FFFDBD01]Heartive[/COLOR][/B]'])

                            magnet = "magnet:?xt=urn:btih:%s" % info_hash
                            
                            info_d = {
                                'Title': title, 
                                'Plot': '\n'.join(plot), 
                                'Size': size, 
                                'Poster': self.thumb, 
                                'imdb_id': imdb_id,
                                'Genre': target['name'] # Trimitem numele API-ului in Genre pentru afisarea pe randul 2
                            }
################################# MODIFICARE END ##################################################################

                            item_f = {'peers': seeds, 'item': {'nume': n_afisat, 'legatura': magnet, 'imagine': self.thumb, 'switch': 'torrent_links', 'info': info_d}}
                            seen_hashes.add(info_hash)
                            
                            if res_p == 4: b4k.append(item_f)
                            elif res_p == 3: b1080.append(item_f)
                            elif res_p == 2: b720.append(item_f)
                        except: continue
                except: continue

            b4k.sort(key=lambda x: x['peers'], reverse=True)
            b1080.sort(key=lambda x: x['peers'], reverse=True)
            b720.sort(key=lambda x: x['peers'], reverse=True)

            f_sorted = []
            for i in range(0, max(len(b4k), len(b1080)), 25):
                f_sorted.extend(b4k[i:i+25]); f_sorted.extend(b1080[i:i+25])
            f_sorted.extend(b720)

            start, end = (page-1)*50, page*50
            for res in f_sorted[start:end]: lists.append(res['item'])

            if len(f_sorted) > end:
                p_info['page'] = page + 1
                lists.append({'nume': 'PAGINA URMATOARE (%d ramase)' % (len(f_sorted)-end), 'legatura': str(p_info), 'switch': 'get_torrent', 'info': {}})

        elif meniu == 'torrent_links':
            action = torraction if torraction else ''
            openTorrent(self._get_torrent_params(p_info_raw, info, action))
            
        return lists
        

# =====================================================================
# INCEPUT ADĂUGARE MEDIAFUSION: Agregator P2P & Community Streams
# =====================================================================
class mediafusion(Torrent):
    def __init__(self):
        self.base_url = 'mediafusionfortheweebs.midnightignite.me'
        self.thumb = os.path.join(media, 'mediafusion.png')
        self.name = '[B]MediaFusion[/B]'
        self.config = 'D-MgIOYBm8hyaUIwwpw-vb7g1DkYuDWlVkR8yC2LTS3b7ejVz5s0yzfMZ1Gf5CxiqtreQCeRCfLfLhOWTFkTDsQL8ozlOF6Sig9mbbuqGnKCFO46BLz3EoWk2OGlL5oM7dpIsTJXVyJC7zWVlgRHXhPy8C-kzUcMHgCJwcFQ-p877sugPoevStrllmYQou9DPpyzbR87R58nJNFrrOj7AoAWK3EkJjAZrvA-t1JCXrrjKWJ-F5FBg4kP9NZ3-6kF8ukse-wG2rU1-xRrHa9r-oya4KwNbR7wYqc2RJVk8WZ5NlKl9SyhS-_FaCGLHinIvG_Spgi-_f9f1aEAVE6_f6rEF-23ajBhmoRu7E3-_F6Fzaahv5sXXG4PkOC62GE37K3OeWZf9X2x-zoIlvmDd6mQ6PAsbKrmhxZbe71uccjWeSjvAOd4iamk1dUiGZp_KPlgjFIEsp98dg7DDG_bXn2klWQuJspM_Pqnaa2T1v8VMuYkqEGcYfAlxYEDKwmB_FIGla9SB5eK2kxZ6NfY3eruKJZ-RDGll9oiTRql9boUeooCAIg839XoenYcHred5wx7r_j5Yx0yUAuC9gytKArPajtIc46TDa4bNsO3ugvJ8U2kKLkLcrCaDSyi3daFSS3Yw_zyv7OeNH2ZH-5UoGgiR49kxLUiGhhR0eM724890haspz40N1JyUeexC620OyAdYIm47hfshxAToEKnPL3fr3L9_HwjwAtxUTWTIO3mLc-RLUz_BDOxeSqKyW-ogq_iTYOVmKBrLVPuQhYIBTSHoZ9fwS4K6UalaQVSADTbun-Nw8xpW6uy9_pLXn-fzw0S-t7is3U63gAkET_f6y30LkWbkuCBF-haoyx7f8i6fMoDZ-i3JedLGw1ReXIK-SKUqo7a0OOWuZF97A-GPyYOu34TZTcGLL3YH-XbZm0kPMXUh9gIM5-vMbafSaZKobLIAg4LSHb0IQVmpQKUqiifXfjhQx7xdwgdTg0aZ-MUa1kZ__vAvWonmAlIXKoj3myCZ3CO4NhzMS90D4rcD7cMx5NGP5fG6EQVbnlyrfpqcT1bsuz1rk5QeIyhGGhRyivaJbJfCC9a5kGtiO9gFBkiDiRnq8Lmy_ADqcTnZYYc5vgbgCDHjZRW3uh2PT61UzN6oWnisSHMQUQWu_KwpAHQ'
        self.menu = [('Căutare', self.base_url, 'cauta', self.searchimage)]

    def headers(self):
        return {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)','Accept': 'application/json'}

    def get_size(self, bytess):
        try:
            bytess = float(bytess)
            for unit in ['B','KB','MB','GB','TB']:
                if bytess < 1024.0: return "%3.2f %s" % (bytess, unit)
                bytess /= 1024.0
        except: return "0 B"

    def _clean_text(self, text):
        if not text: return text
        if py3: emojis = ['📄','📂','📹','🔊','⭐','👤','💾','🔎','🏷️','🌐','🔗','🧑‍💻','🌎','🇬🇧','🇮🇹','🎥','🎬','👥','🎞️','🎞','┈➤', '📦', '🎨', '📺', '🎵']
        else: emojis = ['\xf0\x9f\x93\x84','\xf0\x9f\x93\xb9','\xf0\x9f\x94\x8a','\xe2\xad\x90','\xf0\x9f\x91\xa4','\xf0\x9f\x92\xbe','\xf0\x9f\x94\x8e']
        for e in emojis: text = text.replace(e, '')
        return text.strip()

    def cauta(self, keyword, replace=False, limit=None):
        import xbmcgui, json
        imdb_id, m_type, season, episode = None, 'movie', None, None
        clean_kw = unquote(keyword).strip()

        if clean_kw.startswith('tt') and len(clean_kw) > 6:
            imdb_id = clean_kw
        
        if not imdb_id:
            try:
                win = xbmcgui.Window(10000)
                p_info = win.getProperty('mrsp.playback.info')
                if p_info:
                    p_data = json.loads(p_info)
                    imdb_id = p_data.get('imdb_id') or p_data.get('imdbnumber')
                    m_type = p_data.get('mediatype', 'movie')
                    season = p_data.get('season')
                    episode = p_data.get('episode')
            except: pass

        m_s_e = re.search(r'(.*?)\s+S(\d+)(?:E(\d+))?', clean_kw, re.IGNORECASE)
        if m_s_e:
            title = m_s_e.group(1).strip()
            if not season: season = int(m_s_e.group(2))
            ep_s = m_s_e.group(3)
            if not episode: episode = int(ep_s) if ep_s else 1
            m_type = 'episode' if ep_s else 'tv'
            if not imdb_id or not str(imdb_id).startswith('tt'):
                _, imdb_id = get_show_ids_from_tmdb(title)
        elif not imdb_id or not str(imdb_id).startswith('tt'):
            y_m = re.search(r'\b(19|20\d{2})\s*$', clean_kw)
            title, year = (clean_kw[:y_m.start()].strip(), y_m.group(1)) if y_m else (clean_kw, None)
            _, imdb_id = get_movie_ids_from_tmdb(title, year)
            if not imdb_id:
                _, api_id_tv = get_show_ids_from_tmdb(title)
                if api_id_tv:
                    imdb_id = api_id_tv
                    m_type, season, episode = 'tv', 1, 1

        if not imdb_id or not str(imdb_id).startswith('tt'): return self.__class__.__name__, self.name, []

        st_id = "%s:%s:%s" % (imdb_id, season or 1, episode or 1) if m_type in ['episode','tv','tvshow'] else imdb_id
        st_type = "series" if m_type in ['episode','tv','tvshow'] else "movie"
        url = "https://%s/%s/stream/%s/%s.json" % (self.base_url, self.config, st_type, st_id)
        
        return self.__class__.__name__, self.name, self.parse_menu(url, 'get_torrent', info={'imdb_id': imdb_id}, limit=None)

    def parse_menu(self, url, meniu, info={}, torraction=None, limit=None):
        lists = []
        if meniu == 'cauta':
            from resources.Core import Core
            Core().searchSites({'landsearch': self.__class__.__name__})
        elif meniu == 'get_torrent' or meniu == 'recente':
            import re
            page = 1
            p_m = re.search(r'[\?&]page=(\d+)', url)
            if p_m: page = int(p_m.group(1))
            clean_url = re.sub(r'[\?&]page=\d+', '', url)
            
            response = makeRequest(clean_url, name=self.__class__.__name__, headers=self.headers(), timeout=15)
            
            if response:
                import json
                try:
                    if not response.strip().startswith('{'): return []
                    data = json.loads(response.strip())
                    streams = data.get('streams', [])
                    b4k, b1080, b720 = [], [], []

                    for stream in streams:
                        try:
                            bh = stream.get('behaviorHints', {})
                            title_orig = bh.get('filename') or stream.get('title') or stream.get('name', '')
                            if not title_orig: continue
                            desc = stream.get('description', '')
                            full_check = (title_orig + " " + desc + " " + stream.get('name', '')).upper()

                            # 1. DETECTIE REZOLUTIE
                            res_p, res_l = 0, ""
                            if any(x in full_check for x in ['2160P', '4K', 'UHD']): res_p, res_l = 4, "4K"
                            elif '1080P' in full_check: res_p, res_l = 3, "1080p"
                            elif '720P' in full_check: res_p, res_l = 2, "720p"
                            if res_p < 2: continue

                            # 2. FILTRARE JUNK
                            if re.search(r'(?i)\b(trailer|sample|cam|camrip|hdts|hdtc|ts|telesync|scr|screener|preair|clip|preview)\b', title_orig): continue

                            # 3. EXTRAGERE PROVIDER (dupa emoji 🔗)
                            provider_source = ""
                            source_match = re.search(r'(?:🔗|Source)\s*([^\n]+)', desc, re.IGNORECASE)
                            if source_match:
                                provider_source = self._clean_text(source_match.group(1))

                            # 4. EXTRAGERE PEERS & SIZE
                            seeds_m = re.search(r'👤\s*(\d+)', desc) or re.search(r'(\d+)\s*seeders?', desc, re.IGNORECASE)
                            seeds = seeds_m.group(1) if seeds_m else '0'
                            peers_int = int(seeds)
                            if peers_int == 0: peers_int = 1
                            if not zeroseed and peers_int == 0: continue

                            size = "N/A"
                            if bh.get('videoSize'): size = self.get_size(bh.get('videoSize'))
                            else:
                                sz_m = re.search(r'(?:📦|💾)\s*([\d\.]+\s*[KMGT]B)', desc, re.IGNORECASE) or re.search(r'([\d\.]+\s*[KMGT]B)', desc, re.IGNORECASE)
                                if sz_m: size = sz_m.group(1)

                            # 5. CURATARE TITLU
                            title = title_orig
                            if ' ┈➤ ' in title: title = title.split(' ┈➤ ')[-1]
                            if ' / ' in title: title = title.split(' / ')[-1]
                            title = title.split('\n')[0].replace('\r', '').strip()
                            title = self._clean_text(title)
                            title = re.sub(r'^[ \t\-\.\:📄📂]+', '', title).strip()

                            magnet = "magnet:?xt=urn:btih:%s" % stream.get('infoHash')
                            for s_url in stream.get('sources', []):
                                if s_url.startswith('tracker:'): magnet += "&tr=" + quote(s_url.replace('tracker:', ''))

                            # 6. PLOT STÂNGA
                            plot = ['[B][COLOR white]%s[/COLOR][/B]' % title, '', '[B]Rezoluție: [COLOR yellow]%s[/COLOR][/B]' % res_l]
                            v_tech = []
                            if re.search(r'\bDV\b|DOVI|DOLBY.?VISION', title + desc, re.IGNORECASE): v_tech.append('Dolby Vision')
                            if re.search(r'\bHDR(?:10\+?)?\b', title + desc, re.IGNORECASE): v_tech.append('HDR')
                            if re.search(r'\bSDR\b', title + desc, re.IGNORECASE): v_tech.append('SDR')
                            if v_tech: plot.append('[B]Video: [COLOR magenta]%s[/COLOR][/B]' % ' / '.join(v_tech))
                            
                            audio_m = re.search(r'(?:🔊|🎵)\s*([^|\n]+)', desc)
                            if audio_m: plot.append('[B]Audio: [COLOR orange]%s[/COLOR][/B]' % audio_m.group(1).strip())
                            
                            plot.append('[B]Mărime: [COLOR FF00FA9A]%s[/COLOR][/B]' % size)
                            plot.append('[B]Seederi: [COLOR FFFF69B4]%s[/COLOR][/B]' % seeds)
                            
                            if provider_source: plot.append('[B]Sursă Originală: [COLOR cyan]%s[/COLOR][/B]' % provider_source)
                            plot.extend(['', '[B]Provider: [COLOR FFFDBD01]MediaFusion[/COLOR][/B]'])

                            n_afisat = '%s  [B][COLOR FFFDBD01]MediaFusion[/COLOR][/B] [B][COLOR FF00FA9A](%s)[/COLOR][/B] [B][COLOR FFFF69B4][S: %s][/COLOR][/B]' % (title, size, seeds)
                            info_d = {
                                'Title': title, 
                                'Plot': '\n'.join(plot), 
                                'Size': size, 
                                'Poster': self.thumb,
                                'Genre': provider_source # Trimitem in Genre pentru afisare pe randul 2
                            }
                            if info.get('imdb_id'): info_d['imdb_id'] = info['imdb_id']

                            item_f = {'peers': peers_int, 'item': {'nume': n_afisat, 'legatura': magnet, 'imagine': self.thumb, 'switch': 'torrent_links', 'info': info_d}}
                            
                            if res_p == 4: b4k.append(item_f)
                            elif res_p == 3: b1080.append(item_f)
                            elif res_p == 2: b720.append(item_f)
                        except: continue

                    b4k.sort(key=lambda x: x['peers'], reverse=True)
                    b1080.sort(key=lambda x: x['peers'], reverse=True)
                    b720.sort(key=lambda x: x['peers'], reverse=True)

                    f_sorted = []
                    for i in range(0, max(len(b4k), len(b1080)), 25):
                        f_sorted.extend(b4k[i:i+25]); f_sorted.extend(b1080[i:i+25])
                    f_sorted.extend(b720)

                    start, end = (page-1)*50, page*50
                    for res in f_sorted[start:end]: lists.append(res['item'])

                    if len(f_sorted) > end:
                        next_url = clean_url + ('&' if '?' in clean_url else '?') + 'page=' + str(page + 1)
                        lists.append({'nume': 'PAGINA URMATOARE (%d ramase)' % (len(f_sorted)-end), 'legatura': next_url, 'imagine': self.nextimage, 'switch': 'get_torrent', 'info': info})
                except Exception as e: log('[MediaFusion] JSON error: %s' % str(e))

        elif meniu == 'torrent_links':
            openTorrent(self._get_torrent_params(url, info, torraction))
        return lists
        
        
class torrentio(Torrent):
    def __init__(self):
        self.base_url = 'torrentio.strem.fun'
        self.thumb = os.path.join(media, 'torrentio.png')
        self.name = '[B]Torrentio[/B]'
        # Configurare standard Torrentio (fara CAM/SCR/3D/480p)
        self.config = 'qualityfilter=cam,scr,threed,480p'
        self.menu = [('Căutare', self.base_url, 'cauta', self.searchimage)]

    def headers(self):
        return {'User-Agent': 'Mozilla/5.0','Accept': 'application/json'}

    def get_size(self, bytess):
        try:
            bytess = float(bytess)
            for unit in ['B','KB','MB','GB','TB']:
                if bytess < 1024.0: return "%3.2f %s" % (bytess, unit)
                bytess /= 1024.0
        except: return "0 B"

    def _clean_text(self, text):
        if not text: return text
        if py3:
            emojis = ['📄','📹','🔊','⭐','👤','💾','🔎','🏷️','🌎','🇬🇧','🇮🇹','🎥','🎬','👥','🎞️','🎞','⚙️']
            for e in emojis: text = text.replace(e, '')
        else:
            emojis = ['\xf0\x9f\x93\x84','\xf0\x9f\x93\xb9','\xf0\x9f\x94\x8a','\xe2\xad\x90','\xf0\x9f\x91\xa4','\xf0\x9f\x92\xbe','\xf0\x9f\x94\x8e']
            for e in emojis: text = text.replace(e, '')
        return text.strip()

    def cauta(self, keyword, replace=False, limit=None):
        import xbmcgui, json
        imdb_id, m_type, season, episode = None, 'movie', None, None
        try:
            win = xbmcgui.Window(10000)
            p_info = win.getProperty('mrsp.playback.info')
            if p_info:
                p_data = json.loads(p_info)
                imdb_id = p_data.get('imdb_id') or p_data.get('imdbnumber')
                m_type = p_data.get('mediatype', 'movie')
                season = p_data.get('season')
                episode = p_data.get('episode')
        except: pass

        clean_kw = unquote(keyword).strip()
        m_s_e = re.search(r'(.*?)\s+S(\d+)(?:E(\d+))?', clean_kw, re.IGNORECASE)
        if m_s_e:
            title = m_s_e.group(1).strip()
            if not season: season = int(m_s_e.group(2))
            ep_s = m_s_e.group(3)
            if not episode: episode = int(ep_s) if ep_s else 1
            m_type = 'episode' if ep_s else 'tv'
            if not imdb_id or not str(imdb_id).startswith('tt'):
                _, imdb_id = get_show_ids_from_tmdb(title)
        elif not imdb_id or not str(imdb_id).startswith('tt'):
            y_m = re.search(r'\b(19|20\d{2})\s*$', clean_kw)
            title, year = (clean_kw[:y_m.start()].strip(), y_m.group(1)) if y_m else (clean_kw, None)
            _, imdb_id = get_movie_ids_from_tmdb(title, year)
            if not imdb_id:
                _, api_id_tv = get_show_ids_from_tmdb(title)
                if api_id_tv:
                    imdb_id = api_id_tv
                    m_type, season, episode = 'tv', 1, 1

        if not imdb_id: return self.__class__.__name__, self.name, []

        st_id = "%s:%s:%s" % (imdb_id, season or 1, episode or 1) if m_type in ['episode','tv','tvshow'] else imdb_id
        st_type = "series" if m_type in ['episode','tv','tvshow'] else "movie"
        url = "https://%s/%s/stream/%s/%s.json" % (self.base_url, self.config, st_type, st_id)
        
        return self.__class__.__name__, self.name, self.parse_menu(url, 'get_torrent', info={'imdb_id': imdb_id}, limit=None)

    def parse_menu(self, url, meniu, info={}, torraction=None, limit=None):
        lists = []
        if meniu == 'cauta':
            from resources.Core import Core
            Core().searchSites({'landsearch': self.__class__.__name__})
        elif meniu == 'get_torrent' or meniu == 'recente':
            response = makeRequest(url, name=self.__class__.__name__, headers=self.headers(), timeout=5)
            
            if response:
                import json
                try:
                    if not response.strip().startswith('{'): return []
                    data = json.loads(response.strip())
                    streams = data.get('streams', [])
                    b4k, b1080, b720 = [], [], []

                    for stream in streams:
                        try:
                            # 1. Extragere date principale
                            name_orig = stream.get('name', '')
                            title_orig = stream.get('title', '') # Contine Titlu \n Info
                            info_hash = stream.get('infoHash')
                            if not info_hash: continue

                            # 2. Separare Titlu de Info (Torrentio pune info pe linia 2)
                            parts = title_orig.split('\n')
                            clean_title_line = parts[0].strip()
                            info_line = parts[1] if len(parts) > 1 else ""

                            # 3. Extragere Provider Sursa (dupa ⚙️ sau din newline)
                            provider_source = "Torrentio"
                            if "⚙️" in title_orig:
                                p_parts = title_orig.split("⚙️")
                                provider_source = p_parts[1].split('\n')[0].strip()
                            
                            # Curatare titlu
                            clean_title_line = self._clean_text(clean_title_line)

                            # 4. Detectie Rezolutie
                            full_check = (name_orig + " " + title_orig).upper()
                            res_p, res_l = 0, ""
                            if any(x in full_check for x in ['2160P', '4K', 'UHD']): res_p, res_l = 4, "4K"
                            elif '1080P' in full_check: res_p, res_l = 3, "1080p"
                            elif '720P' in full_check: res_p, res_l = 2, "720p"
                            if res_p < 2: continue

                            # 5. EXTRAGERE PEERS & SIZE (FIX METODA SIGURA)
                            seeds = "0"
                            size = "N/A"
                            
                            # a) Cautam MARIMEA intai (format cifre + unitate)
                            # Regex cauta: 2.29 GB sau 700 MB
                            size_match = re.search(r'(\d+(?:\.\d+)?\s*[KMGT]B)', info_line, re.IGNORECASE)
                            if size_match:
                                size = size_match.group(1)
                            elif stream.get('behaviorHints', {}).get('videoSize'):
                                size = self.get_size(stream.get('behaviorHints').get('videoSize'))

                            # b) Cautam SEEDERII
                            # Stergem marimea din text pentru a nu confunda cifrele din marime cu seederii
                            temp_line = info_line
                            if size_match:
                                temp_line = temp_line.replace(size_match.group(0), "")
                            
                            # Acum cautam primul numar intreg ramas in text
                            # De obicei formatul ramas e "👤 46 💾  ⚙️ Provider" -> Gaseste 46
                            seeds_match = re.search(r'(\d+)', temp_line)
                            if seeds_match:
                                seeds = seeds_match.group(1)
                            
                            peers_int = int(seeds)
                            if not zeroseed and peers_int == 0: continue

                            # 6. Construire Nume Afisat
                            n_afisat = '%s  [B][COLOR FFFDBD01]Torrentio[/COLOR][/B] [B][COLOR FF00FA9A](%s)[/COLOR][/B] [B][COLOR FFFF69B4][S: %s][/COLOR][/B]' % (clean_title_line, size, seeds)
                            
                            # 7. Construire Magnet
                            magnet = "magnet:?xt=urn:btih:%s" % info_hash
                            
                            # 8. Plot Detaliat
                            plot = ['[B][COLOR white]%s[/COLOR][/B]' % clean_title_line, '', '[B]Rezoluție: [COLOR yellow]%s[/COLOR][/B]' % res_l]
                            
                            if "HDR" in full_check: plot.append('[B]Video: [COLOR magenta]HDR[/COLOR][/B]')
                            if "DV" in full_check: plot.append('[B]Video: [COLOR magenta]Dolby Vision[/COLOR][/B]')
                            if "SDR" in full_check: plot.append('[B]Video: [COLOR magenta]SDR[/COLOR][/B]')
                            
                            plot.append('[B]Mărime: [COLOR FF00FA9A]%s[/COLOR][/B]' % size)
                            plot.append('[B]Seederi: [COLOR FFFF69B4]%s[/COLOR][/B]' % seeds)
                            plot.append('[B]Sursă Originală: [COLOR cyan]%s[/COLOR][/B]' % provider_source)
                            plot.extend(['', '[B]Provider: [COLOR FFFDBD01]Torrentio[/COLOR][/B]'])

                            info_d = {
                                'Title': clean_title_line, 
                                'Plot': '\n'.join(plot), 
                                'Size': size, 
                                'Poster': self.thumb,
                                'Genre': provider_source
                            }
                            if info.get('imdb_id'): info_d['imdb_id'] = info['imdb_id']

                            item_f = {'peers': peers_int, 'item': {'nume': n_afisat, 'legatura': magnet, 'imagine': self.thumb, 'switch': 'torrent_links', 'info': info_d}}
                            
                            if res_p == 4: b4k.append(item_f)
                            elif res_p == 3: b1080.append(item_f)
                            elif res_p == 2: b720.append(item_f)
                        except: continue

                    b4k.sort(key=lambda x: x['peers'], reverse=True)
                    b1080.sort(key=lambda x: x['peers'], reverse=True)
                    b720.sort(key=lambda x: x['peers'], reverse=True)

                    f_sorted = []
                    for i in range(0, max(len(b4k), len(b1080)), 25):
                        f_sorted.extend(b4k[i:i+25]); f_sorted.extend(b1080[i:i+25])
                    f_sorted.extend(b720)

                    for res in f_sorted: lists.append(res['item'])

                except Exception as e: log('[Torrentio] Error: %s' % str(e))

        elif meniu == 'torrent_links':
            openTorrent(self._get_torrent_params(url, info, torraction))
        return lists


# =====================================================================
# INCEPUT ADĂUGARE CORNCASTLE: Wrapper peste Torrentio (fără filtre)
# =====================================================================
class corncastle(Torrent):
    def __init__(self):
        self.base_url = 'torrentio.strem.fun'
        self.thumb = os.path.join(media, 'corncastle.png')
        self.name = '[B]CornCastle[/B]'
        # CornCastle foloseste Torrentio FARA filtre de calitate (default complet)
        # Diferenta fata de clasa torrentio: nu are qualityfilter, deci poate returna
        # rezultate suplimentare pe care Torrentio le filtreaza la nivel de API
        self.config = ''
        self.menu = [('Căutare', self.base_url, 'cauta', self.searchimage)]

    def headers(self):
        return {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36', 'Accept': 'application/json'}

    def get_size(self, bytess):
        try:
            bytess = float(bytess)
            for unit in ['B','KB','MB','GB','TB']:
                if bytess < 1024.0: return "%3.2f %s" % (bytess, unit)
                bytess /= 1024.0
        except: return "0 B"

    def _clean_text(self, text):
        if not text: return text
        if py3:
            emojis = ['📄','📹','🔊','⭐','👤','💾','🔎','🏷️','🌎','🇬🇧','🇮🇹','🎥','🎬','👥','🎞️','🎞','⚙️','🔗','🔨','📺','🎞','🏷','📦','✅','❌','⚡','🌐','📡']
            for e in emojis: text = text.replace(e, '')
        else:
            emojis = ['\xf0\x9f\x93\x84','\xf0\x9f\x93\xb9','\xf0\x9f\x94\x8a','\xe2\xad\x90','\xf0\x9f\x91\xa4','\xf0\x9f\x92\xbe','\xf0\x9f\x94\x8e','\xf0\x9f\x94\x97','\xf0\x9f\x94\xa8']
            for e in emojis: text = text.replace(e, '')
        return text.strip()

    def cauta(self, keyword, replace=False, limit=None):
        import xbmcgui, json
        imdb_id, m_type, season, episode = None, 'movie', None, None
        
        # 1. Preluare context din playback info
        try:
            win = xbmcgui.Window(10000)
            p_info = win.getProperty('mrsp.playback.info')
            if p_info:
                p_data = json.loads(p_info)
                imdb_id = p_data.get('imdb_id') or p_data.get('imdbnumber')
                m_type = p_data.get('mediatype', 'movie')
                season = p_data.get('season')
                episode = p_data.get('episode')
        except: pass

        # 2. Fallback: parsare keyword pentru IMDb ID
        clean_kw = unquote(keyword).strip()
        m_s_e = re.search(r'(.*?)\s+S(\d+)(?:E(\d+))?', clean_kw, re.IGNORECASE)
        if m_s_e:
            title = m_s_e.group(1).strip()
            if not season: season = int(m_s_e.group(2))
            ep_s = m_s_e.group(3)
            if not episode: episode = int(ep_s) if ep_s else 1
            m_type = 'episode' if ep_s else 'tv'
            if not imdb_id or not str(imdb_id).startswith('tt'):
                _, imdb_id = get_show_ids_from_tmdb(title)
        elif not imdb_id or not str(imdb_id).startswith('tt'):
            y_m = re.search(r'\b(19|20\d{2})\s*$', clean_kw)
            title, year = (clean_kw[:y_m.start()].strip(), y_m.group(1)) if y_m else (clean_kw, None)
            _, imdb_id = get_movie_ids_from_tmdb(title, year)
            if not imdb_id:
                _, api_id_tv = get_show_ids_from_tmdb(title)
                if api_id_tv:
                    imdb_id = api_id_tv
                    m_type, season, episode = 'tv', 1, 1

        if not imdb_id:
            log('[CornCastle] Nu s-a putut rezolva IMDb ID pentru: %s' % clean_kw)
            return self.__class__.__name__, self.name, []

        # 3. Constructie URL API
        st_id = "%s:%s:%s" % (imdb_id, season or 1, episode or 1) if m_type in ['episode','tv','tvshow'] else imdb_id
        st_type = "series" if m_type in ['episode','tv','tvshow'] else "movie"
        
        # CornCastle: URL FARA config (Torrentio default)
        url = "https://%s/stream/%s/%s.json" % (self.base_url, st_type, st_id)
        log('[CornCastle] Cautare: %s -> %s' % (clean_kw, url))
        
        return self.__class__.__name__, self.name, self.parse_menu(url, 'get_torrent', info={'imdb_id': imdb_id}, limit=None)

    def parse_menu(self, url, meniu, info={}, torraction=None, limit=None):
        lists = []
        if meniu == 'cauta':
            from resources.Core import Core
            Core().searchSites({'landsearch': self.__class__.__name__})
            
        elif meniu == 'get_torrent' or meniu == 'recente':
            response = makeRequest(url, name=self.__class__.__name__, headers=self.headers(), timeout=5)
            
            if response:
                import json
                try:
                    if not response.strip().startswith('{'): return []
                    data = json.loads(response.strip())
                    streams = data.get('streams', [])
                    b4k, b1080, b720 = [], [], []

                    for stream in streams:
                        try:
                            # 1. Extragere date principale
                            name_orig = stream.get('name', '')
                            title_orig = stream.get('title', '')
                            info_hash = stream.get('infoHash')
                            if not info_hash: continue

                            # 2. Separare Titlu de Info (Torrentio pune info pe linia 2)
                            parts = title_orig.split('\n')
                            clean_title_line = parts[0].strip()
                            info_line = parts[1] if len(parts) > 1 else ""

                            # 3. Extragere Provider Sursa (tracker-ul original: YTS, RARBG, 1337x etc.)
                            provider_source = ""
                            if "⚙️" in title_orig:
                                p_parts = title_orig.split("⚙️")
                                provider_source = p_parts[1].split('\n')[0].strip()
                            
                            # Curatare titlu de emojis
                            clean_title_line = self._clean_text(clean_title_line)

                            # 4. Detectie Rezolutie
                            full_check = (name_orig + " " + title_orig).upper()
                            res_p, res_l = 0, ""
                            if any(x in full_check for x in ['2160P', '4K', 'UHD']): res_p, res_l = 4, "4K"
                            elif '1080P' in full_check: res_p, res_l = 3, "1080p"
                            elif '720P' in full_check: res_p, res_l = 2, "720p"
                            if res_p < 2: continue

                            # 5. Filtrare junk (CAM, TS, screener etc.)
                            junk = r'(?i)\b(trailer|sample|cam|camrip|hdts|hdtc|ts|telesync|scr|screener|preair|clip|preview|tc|hc)\b'
                            if re.search(junk, clean_title_line) or re.search(junk, info_line): continue

                            # 6. EXTRAGERE SIZE
                            seeds = "0"
                            size = "N/A"
                            
                            size_match = re.search(r'(\d+(?:\.\d+)?\s*[KMGT]B)', info_line, re.IGNORECASE)
                            if size_match:
                                size = size_match.group(1)
                            elif stream.get('behaviorHints', {}).get('videoSize'):
                                size = self.get_size(stream.get('behaviorHints').get('videoSize'))

                            # 7. EXTRAGERE SEEDERI (eliminam size din text pentru a nu confunda cifrele)
                            temp_line = info_line
                            if size_match:
                                temp_line = temp_line.replace(size_match.group(0), "")
                            
                            seeds_match = re.search(r'(\d+)', temp_line)
                            if seeds_match:
                                seeds = seeds_match.group(1)
                            
                            peers_int = int(seeds)
                            if not zeroseed and peers_int == 0: continue

                            # 8. Construire Nume Afisat (randul 1 = DOAR titlul curat)
                            # Badges-urile se afiseaza automat pe randul 2 de catre results_window.py
                            n_afisat = '%s  [B][COLOR FFFDBD01]CornCastle[/COLOR][/B] [B][COLOR FF00FA9A](%s)[/COLOR][/B] [B][COLOR FFFF69B4][S: %s][/COLOR][/B]' % (clean_title_line, size, seeds)
                            
                            # 9. Construire Magnet Link
                            magnet = "magnet:?xt=urn:btih:%s" % info_hash
                            
                            # 10. PLOT Detaliat (panoul stanga)
                            check_text = clean_title_line + " " + info_line
                            plot = ['[B][COLOR white]%s[/COLOR][/B]' % clean_title_line, '']
                            plot.append('[B]Rezoluție: [COLOR yellow]%s[/COLOR][/B]' % res_l)
                            
                            # Video tech pentru Plot
                            v_tech = []
                            if re.search(r'\bDV\b|DoVi|DOLBY[\.\s-]?VISION', check_text, re.IGNORECASE): v_tech.append('Dolby Vision')
                            if re.search(r'\bHDR10\+', check_text, re.IGNORECASE): v_tech.append('HDR10+')
                            elif re.search(r'\bHDR10\b', check_text, re.IGNORECASE): v_tech.append('HDR10')
                            elif re.search(r'\bHDR\b', check_text, re.IGNORECASE): v_tech.append('HDR')
                            if re.search(r'\bSDR\b', check_text, re.IGNORECASE): v_tech.append('SDR')
                            if v_tech: plot.append('[B]Video: [COLOR magenta]%s[/COLOR][/B]' % ' / '.join(v_tech))
                            
                            # Audio tech pentru Plot
                            a_tech = []
                            if re.search(r'ATMOS', check_text, re.IGNORECASE): a_tech.append('Atmos')
                            if re.search(r'TRUE[\s.-]?HD', check_text, re.IGNORECASE): a_tech.append('TrueHD')
                            if re.search(r'DTS[\s.-]?HD[\s.-]?MA', check_text, re.IGNORECASE): a_tech.append('DTS-HD MA')
                            elif re.search(r'DTS[\s.-]?HD', check_text, re.IGNORECASE): a_tech.append('DTS-HD')
                            elif re.search(r'\bDTS\b', check_text, re.IGNORECASE): a_tech.append('DTS')
                            if re.search(r'DDP[\s.-]?[57][\.\s]1|DD\+[\s.-]?[57][\.\s]1|EAC3[\s.-]?[57][\.\s]1', check_text, re.IGNORECASE): a_tech.append('DD+ 5.1/7.1')
                            elif re.search(r'\bDDP\b|\bDD\+|EAC-?3', check_text, re.IGNORECASE): a_tech.append('DD+')
                            elif re.search(r'\bDD[\s.-]?[57][\.\s]1\b|AC-?3[\s.-]?[57][\.\s]1', check_text, re.IGNORECASE): a_tech.append('DD 5.1')
                            elif re.search(r'\bAAC\b', check_text, re.IGNORECASE): a_tech.append('AAC')
                            if a_tech: plot.append('[B]Audio: [COLOR orange]%s[/COLOR][/B]' % ' / '.join(a_tech))
                            
                            plot.append('[B]Mărime: [COLOR FF00FA9A]%s[/COLOR][/B]' % size)
                            plot.append('[B]Seederi: [COLOR FFFF69B4]%s[/COLOR][/B]' % seeds)
                            if provider_source: plot.append('[B]Sursă Originală: [COLOR cyan]%s[/COLOR][/B]' % provider_source)
                            plot.extend(['', '[B]Provider: [COLOR FFFDBD01]CornCastle[/COLOR][/B]'])

                            # 11. Info dict
                            info_d = {
                                'Title': clean_title_line, 
                                'Plot': '\n'.join(plot), 
                                'Size': size, 
                                'Poster': self.thumb,
                                'Genre': provider_source
                            }
                            if info.get('imdb_id'): info_d['imdb_id'] = info['imdb_id']
                            if info.get('tmdb_id'): info_d['tmdb_id'] = info['tmdb_id']

                            item_f = {'peers': peers_int, 'item': {'nume': n_afisat, 'legatura': magnet, 'imagine': self.thumb, 'switch': 'torrent_links', 'info': info_d}}
                            
                            if res_p == 4: b4k.append(item_f)
                            elif res_p == 3: b1080.append(item_f)
                            elif res_p == 2: b720.append(item_f)
                        except: continue

                    # Sortare pe rezolutie si peers
                    b4k.sort(key=lambda x: x['peers'], reverse=True)
                    b1080.sort(key=lambda x: x['peers'], reverse=True)
                    b720.sort(key=lambda x: x['peers'], reverse=True)

                    # Intercalare 4K si 1080p, apoi 720p
                    f_sorted = []
                    for i in range(0, max(len(b4k), len(b1080)), 25):
                        f_sorted.extend(b4k[i:i+25]); f_sorted.extend(b1080[i:i+25])
                    f_sorted.extend(b720)

                    for res in f_sorted: lists.append(res['item'])

                except Exception as e: log('[CornCastle] Error: %s' % str(e))

        elif meniu == 'torrent_links':
            openTorrent(self._get_torrent_params(url, info, torraction))
        return lists



# =====================================================================
# CLASA AIO STREAMS - VERSIUNEA FINALĂ (RD ONLY, PRIORITIZED CACHED)
# =====================================================================
class aiostreams(Torrent):
    def __init__(self):
        self.base_url = 'aiostreams'
        self.thumb = os.path.join(media, 'aiostreams.png')
        self.name = '[B]AIO Streams[/B]'

        # URL-uri default per instanță (index = valoarea din enum)
        default_urls = [
            'https://aiostreams.stremio.ru',           # 0: Kuu-lection stable
            'https://aiostreams-nightly.stremio.ru',           # 1: Kuu-lection nightly
            'https://aiostreams.viren070.me',           # 2: Viren070
            'https://aiostreams.fortheweak.cloud',      # 3: Fortheweak stable
            'https://aiostreams-nightly.fortheweak.cloud',  # 4: Fortheweak nightly
            'https://aiostreamsfortheweebsstable.midnightignite.me',  # 5: Midnight stable
            'https://aiostreamsfortheweebs.midnightignite.me',        # 6: Midnight nightly
            'https://aiostreams.elfhosted.com',         # 7: Elfhosted
            '',                                         # 8: Custom
        ]

        try:
            instance_id = int(__settings__.getSetting('aiostreams_instance') or '0')
        except:
            instance_id = 0

        # URL: pentru Custom (1) luăm ce a scris userul, altfel default
        if instance_id == 1:
            base_url = (__settings__.getSetting('aio_url.1') or '').strip().rstrip('/')
        else:
            base_url = (__settings__.getSetting('aio_url.%d' % instance_id) or '').strip().rstrip('/')
            if not base_url and instance_id < len(default_urls):
                base_url = default_urls[instance_id]

        # UUID și Password (înlocuiesc username/password)
        aio_uuid = __settings__.getSetting('aio_uuid.%d' % instance_id) or ''
        aio_pass = __settings__.getSetting('aio_password.%d' % instance_id) or ''

        # Auth: UUID ca "username", password ca parolă (HTTP Basic Auth)
        # Dacă nu există UUID, auth=None (instanță publică fără autentificare)
        if aio_uuid and aio_pass:
            self.aio_auth = (aio_uuid, aio_pass)
        elif aio_uuid:
            # Unele instanțe cer doar UUID fără parolă
            self.aio_auth = (aio_uuid, '')
        else:
            self.aio_auth = None

        self.base_url_api = base_url
        self.search_link = '%s/api/v1/search' % base_url
        self.menu = [('Căutare', base_url, 'cauta', self.searchimage)]

    def headers(self):
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Accept': 'application/json'
        }

    def get_size(self, bytess):
        try:
            bytess = float(bytess)
            if bytess <= 0: return "N/A"
            for factor, suffix in [(1024**4, ' TB'), (1024**3, ' GB'), (1024**2, ' MB'), (1024**1, ' KB'), (1024**0, ' B')]:
                if bytess >= factor: return str(round(bytess / factor, 2)) + suffix
            return "N/A"
        except: return "N/A"

    def _clean_emojis(self, text):
        if not text: return text
        if py3: emojis = ['📄','📂','📹','🔊','⭐','👤','👥','💾','🔎','🏷️','🌐','🔗','🧑‍💻','🌎','🇬🇧','🇮🇹','🎥','🎬','🎞️','🎞','⚙️','📦','🎨','📺','🎵','✅','❌','⚡','📡']
        else: emojis = ['\xf0\x9f\x93\x84','\xf0\x9f\x93\xb9','\xf0\x9f\x94\x8a','\xe2\xad\x90','\xf0\x9f\x91\xa4','\xf0\x9f\x92\xbe','\xf0\x9f\x94\x8e']
        for e in emojis: text = text.replace(e, '')
        return text.strip()

    def _do_api_search(self, imdb_id, media_type, season=None, episode=None):
        from urllib3.exceptions import InsecureRequestWarning
        urllib3.disable_warnings(InsecureRequestWarning)

        m_type = 'series' if media_type in ('episode', 'tv', 'tvshow', 'series') else 'movie'
        timeout_val = int(__settings__.getSetting('timeout') or '30')

        def _fetch(st_id):
            params = {'type': m_type, 'id': st_id}
            try:
                response = requests.get(
                    self.search_link,
                    params=params,
                    auth=self.aio_auth,   # None pentru instanțe publice, (uuid, pass) pentru private
                    headers=self.headers(),
                    verify=False,
                    timeout=timeout_val
                )
                if not response.ok:
                    return []
                return response.json().get('data', {}).get('results', [])
            except:
                return []

        if m_type != 'series' or not season:
            return _fetch(str(imdb_id))

        ep_num = int(episode or 1)

        # Apel 1: episodul curent
        results_ep = _fetch('%s:%s:%s' % (imdb_id, season, ep_num))

        # Apel 2: episodul următor — pentru a identifica pack-urile
        results_next = _fetch('%s:%s:%s' % (imdb_id, season, ep_num + 1))

        next_urls = set(r.get('url', '') for r in results_next if r.get('url'))

        all_results = []
        seen_urls = set()

        for r in results_ep:
            url = r.get('url', '')
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            if url in next_urls:
                r['_is_pack'] = True
            all_results.append(r)

        return all_results


    def cauta(self, keyword, replace=False, limit=None):
        import xbmcgui, json
        imdb_id, m_type, season, episode, kodi_title = None, 'movie', None, None, ''
        clean_kw = unquote(keyword).strip()

        # 1. Verificare ID direct
        if clean_kw.startswith('tt') and len(clean_kw) > 6: imdb_id = clean_kw

        # 2. Preluare context din Kodi
        if not imdb_id:
            try:
                win = xbmcgui.Window(10000)
                p_info = win.getProperty('mrsp.playback.info')
                if p_info:
                    p_data = json.loads(p_info)
                    imdb_id = p_data.get('imdb_id') or p_data.get('imdbnumber')
                    tmdb_id = p_data.get('tmdb_id') # <-- ADAUGAT AICI
                    m_type = p_data.get('mediatype', 'movie')
                    season = p_data.get('season')
                    episode = p_data.get('episode')
                    kodi_title = p_data.get('title', '')
            except: pass

        # 3. Rezolvare Fallback TMDB
        m_s_e = re.search(r'(.*?)\s+S(\d+)(?:E(\d+))?', clean_kw, re.IGNORECASE)
        if m_s_e:
            title = m_s_e.group(1).strip()
            if not season: season = int(m_s_e.group(2))
            ep_str = m_s_e.group(3)
            if not episode: episode = int(ep_str) if ep_str else 1
            m_type = 'episode' if ep_str else 'tv'
            if not imdb_id or not str(imdb_id).startswith('tt'):
                _, imdb_id = get_show_ids_from_tmdb(title)
        elif not imdb_id or not str(imdb_id).startswith('tt'):
            y_m = re.search(r'\b((?:19|20)\d{2})\s*$', clean_kw)
            title, year = (clean_kw[:y_m.start()].strip(), y_m.group(1)) if y_m else (clean_kw, None)
            _, imdb_id = get_movie_ids_from_tmdb(title, year)
            if not imdb_id:
                _, api_id_tv = get_show_ids_from_tmdb(title)
                if api_id_tv:
                    imdb_id = api_id_tv
                    m_type, season, episode = 'tv', 1, 1

        if not imdb_id: return self.__class__.__name__, self.name, []

        return self.__class__.__name__, self.name, self.parse_menu('aio://', 'get_torrent', info={'imdb_id': imdb_id, 'tmdb_id': tmdb_id, 'media_type': m_type, 'season': season, 'episode': episode, 'Title': kodi_title})

    def parse_menu(self, url, meniu, info={}, torraction=None, limit=None):
        import json
        lists = []
        
        if meniu == 'cauta':
            from resources.Core import Core
            Core().searchSites({'landsearch': self.__class__.__name__})
            return []

        imdb_id  = info.get('imdb_id')
        media_type = info.get('media_type', 'movie')
        season   = info.get('season')
        episode  = info.get('episode')
        movie_title = info.get('Title', 'AIO Stream')
        
        streams = self._do_api_search(imdb_id, media_type, season, episode)
        if not streams:
            return []

        for item in streams:
            try:
                # --- 1. EXCLUDEM P2P (Magnets) ---
                item_type = str(item.get('type', '')).lower()
                if 'p2p' in item_type:
                    continue

                # --- 2. URL REDARE — definit primul, înainte de orice ---
                play_url = item.get('url', '')
                if not play_url or not play_url.startswith('http'):
                    continue

                # --- 3. PARSARE DATE ---
                parsed = item.get('parsedFile', {})
                bh     = item.get('behaviorHints', {})

                # Titlul COMPLET (toate liniile) pentru detecție calitate
                full_title_raw = str(item.get('title', ''))

                # Titlul de display: filename sau prima linie
                title = str(item.get('filename') or bh.get('filename') or parsed.get('filename') or '').strip()
                if not title or len(title) < 5:
                    title = full_title_raw.split('\n')[0].strip()
                if not title or len(title) < 5:
                    title = movie_title

                title_clean = self._clean_emojis(title).strip()

                # --- 4. REZOLUTIE — folosim full_title_raw + parsedFile ---
                res_l      = str(parsed.get('resolution') or '').upper()
                check_text = (res_l + ' ' + full_title_raw + ' ' + title_clean).upper()

                res_tag = 'SD'
                if any(x in check_text for x in ['2160P', '2160', '4K', 'UHD']):
                    res_tag = '4K'
                elif any(x in check_text for x in ['1080P', '1080I', 'FHD']):
                    res_tag = '1080p'
                elif any(x in check_text for x in ['720P', '720I', 'HD']):
                    res_tag = '720p'

                # --- 5. FILTRU JUNK ---
                if re.search(r'(?i)\b(trailer|sample|cam|camrip|hdts|hdtc|ts|telesync)\b', title_clean):
                    continue

                # --- 6. SEEDERI ---
                seeders = 0
                try:
                    s_val = item.get('seeders')
                    if s_val:
                        seeders = int(s_val)
                    else:
                        m_seeds = re.search(
                            r'(?:👤|👥|S:)\s*(\d+)',
                            full_title_raw + str(item.get('description', '')),
                            re.IGNORECASE)
                        if m_seeds:
                            seeders = int(m_seeds.group(1))
                except:
                    pass

                # --- 7. CACHED, CLOUD & SERVICE ---
                # Aici extragem clar serviciul (ex: realdebrid, alldebrid)
                debrid_service = str(item.get('service', '')).strip()
                is_cached = bool(item.get('cached', False))
                is_cloud  = 'cloud' in str(item.get('indexer', '')).lower() or 'cloud' in item_type

                # --- 8. MARIME ---
                size_bytes = item.get('size') or bh.get('videoSize') or 0
                size_str   = self.get_size(float(size_bytes))

                # --- 9. SURSA & LIMBI & INDEXER ---
                source_addon = str(item.get('addon') or item.get('provider') or parsed.get('source') or '').strip()
                languages    = parsed.get('languages', [])
                indexer      = str(item.get('indexer', '')).strip()

                # --- 10. INFO DICT ---
                # Acum transmitem toate cheile necesare catre results_window.py
                info_dict = {
                    'Title':        title_clean,
                    'Plot':         title_clean,
                    'Size':         size_str,
                    'Poster':       self.thumb,
                    'Genre':        res_tag,          
                    'imdb_id':      imdb_id,
                    'tmdb_id':      info.get('tmdb_id'),
                    'is_cached':    is_cached,
                    'is_cloud':     is_cloud,
                    'service':      debrid_service,   # <--- CHEIA MAGICĂ PENTRU RD+
                    'seeders':      seeders,
                    'languages':    languages,
                    'addon':        source_addon,     # Setat clar ca 'addon' cum îl caută fereastra
                    'indexer':      indexer,
                    'aio_bypass_filter': True,        
                }

                lists.append({
                    'nume':    title_clean,
                    'legatura': play_url,
                    'imagine': self.thumb,
                    'switch':  'play',
                    'info':    info_dict,
                    'site_id': 'aiostreams'
                })

            except Exception as e:
                log('[AIO Streams] Eroare item: %s' % str(e))
                continue

        return lists

