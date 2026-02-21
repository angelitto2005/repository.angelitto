# -*- coding: utf-8 -*-
from resources.functions import *
import tempfile
import ssl
import hashlib
import pickle
import abc
__settings__ = xbmcaddon.Addon()
zeroseed = __settings__.getSetting("zeroseed") == 'true'

torrentsites = ['datascene',
             'eztv',
             'filelist',
             'fluxzone',
             'glotorrents',
             'ieet',
             'kickass',
             'kickass2',
             'lime',
             'magnetdl',
             'uindex',
             'meteor',
             'comet',
             'heartive',
             'rarbg',
             'rutor',
             'speedapp',
             'seedfilero',
             'torrentgalaxy',
             'xtremlymtorrents',
             'yts',
             'yourbittorrent']

torrnames = {'datascene': {'nume' : 'DataScene', 'thumb': os.path.join(media, 'datascene.png')},
             'eztv': {'nume': 'EZTV', 'thumb': os.path.join(media, 'eztv.png')},
             'filelist': {'nume': 'FileList', 'thumb': os.path.join(media, 'filelist.png')},
             'fluxzone': {'nume': 'FluxZone', 'thumb': os.path.join(media, 'fluxzone.png')},
             'glotorrents': {'nume': 'GloTorrents', 'thumb': os.path.join(media, 'glotorrents.jpg')},
             'ieet': {'nume': '1377x', 'thumb': os.path.join(media, 'ieetx.png')},
             'kickass': {'nume': 'Kickass', 'thumb': os.path.join(media, 'kickass.png')},
             'kickass2': {'nume': 'Kickass2', 'thumb': os.path.join(media, 'kickass2.png')},
             'lime': {'nume': 'LimeTorrents', 'thumb': os.path.join(media, 'limetorrents.jpg')},
             'magnetdl': {'nume': 'MagnetDL', 'thumb': os.path.join(media, 'magnetdl.png')},
             'uindex': {'nume': 'UIndex', 'thumb': os.path.join(media, 'uindex.png')},
             'meteor': {'nume': 'Meteor', 'thumb': search_icon},
             'comet': {'nume': 'Comet', 'thumb': search_icon},
             'heartive': {'nume': 'Heartive', 'thumb': search_icon},
             'rarbg': {'nume': 'Rarbg', 'thumb': os.path.join(media, 'rarbg.png')},
             'rutor': {'nume': 'RuTor', 'thumb': os.path.join(media, 'rutor.jpg')},
             'seedfilero': {'nume': 'SeedFile', 'thumb': os.path.join(media, 'seedfilero.jpg')},
             'speedapp': {'nume': 'SpeedApp', 'thumb': os.path.join(media, 'speedapp.png')},
             'torrentgalaxy': {'nume': 'TorrentGalaxy', 'thumb': os.path.join(media, 'torrentgalaxy.jpg')},
             'xtremlymtorrents': {'nume': 'ExtremLymTorrents', 'thumb': os.path.join(media, 'extremlymtorrents.jpg')},
             'yts': {'nume': 'YTS', 'thumb': os.path.join(media, 'yts.png')},
             'yourbittorrent': {'nume': 'YourBittorrent', 'thumb': os.path.join(media, 'yourbittorrent.jpg')}}
    

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
    from resources.lib.requests.packages.urllib3.exceptions import InsecureRequestWarning
    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
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
        log(' %s makeRequest(%s) exception: %s' % (name, url, str(e)))
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

class datascene(Torrent):
    def __init__(self):
        self.base_url = 'datascene.xyz'
        self.thumb = os.path.join(media, 'datascene.png')
        self.name = 'DataScene'
        self.username = __settings__.getSetting("DSusername")
        self.password = __settings__.getSetting("DSpassword")
        self.search_url = 'https://%s/torrents?perPage=50&name=%s&page=1' %(self.base_url, '%s&categories[0]=6&categories[1]=1&categories[2]=2' )
        self.login_url = 'https://%s/login' % (self.base_url)

        self.sortare = [('După dată', ''),
                ('După mărime', '&sortField=size'),
                ('După downloads', '&sortField=times_completed'),
                ('După seederi', '&sortField=seeders'),
                ('După leecheri', '&sortField=leechers')]
        
        self.categorii = [('Movies', '1'),
                ('TV', '2'),
                ('XXX', '6')]
        self.menu = [('Recente', "https://%s/torrents?perPage=50&page=1" % self.base_url, 'recente', self.thumb)]
        l = []
        for x in self.categorii:
            l.append((x[0], 'https://%s/torrents?perPage=50&categories[0]=%s&page=1' % (self.base_url, x[1]), 'get_torrent', self.thumb))
        self.menu.extend(l)
        #self.menu.extend([('XXX', 'https://%s/browsex.php?search=&blah=0%s&incldead=1' % (self.base_url, '&cat=12'), 'sortare', self.thumb)])
        self.menu.extend([('Căutare', self.base_url, 'cauta', self.searchimage)])

    def login(self):
        headers = {'Host': self.base_url,
                   'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; rv:70.1) Gecko/20100101 Firefox/70.1',
                   'Accept-Language': 'ro,en-US;q=0.7,en;q=0.3'}
        y, session = makeRequest('https://%s/' % (self.base_url), name=self.__class__.__name__, headers=headers, savecookie=True)
        save_cookie(self.__class__.__name__, session)
        token = re.search('csrf-token.*?content="(.*?)"', y).group(1)
        data = {
            'password': self.password,
            'username': self.username,
            'remember': 'on',
            '_token': token
        }
        log('Log-in  attempt')
        e = []
        try: cookiesitems = session.cookies.iteritems()
        except: cookiesitems = session.cookies.items()
        for i, j in cookiesitems:
            e.append('%s=%s' % (i, j))
        headers['Cookie'] = "; ".join(e)
        headers['Origin'] = 'https://' + self.base_url
        headers['Referer'] = 'https://' + self.base_url + '/login'
        xbmc.sleep(1000)
        x, session1 = makeRequest('https://%s/login' % (self.base_url), name=self.__class__.__name__, data=data, headers=headers, savecookie=True)
        if re.search('logout', x):
            log('LOGGED Datascene')
        if re.search('These credentials do not match our records', x):
            xbmc.executebuiltin((u'Notification(%s,%s)' % ('DataScene Login Error', 'Parola/Username incorecte')))
            clear_cookie(self.__class__.__name__)
        save_cookie(self.__class__.__name__, session1)
        try: cookiesitems = session1.cookies.iteritems()
        except: cookiesitems = session1.cookies.items()
        for cookie, value in cookiesitems:
            return cookie + '=' + value
        return False

    def parse_menu(self, url, meniu, info={}, torraction=None, limit=None):
        lists = []
        imagine = ''
        if meniu == 'get_torrent' or meniu == 'cauta' or meniu == 'recente':
            if meniu == 'cauta':
                from resources.Core import Core
                Core().searchSites({'landsearch': self.__class__.__name__})
            else:
                count = 1
                response = makeRequest(url, name=self.__class__.__name__, headers=self.headers())
                if not self.check_login(response):
                    response = makeRequest(url, name=self.__class__.__name__, headers=self.headers())
                regex = '''<tr.*?>(.+?)</tr>'''
                reg_genre = ''''Genre'></i>(.*?)</span'''
                regex_tr = '''torrent-poster.*?src="(.*?)".*?"view\-torrent.*?href=".*?">(.*?)<.*?torrent-listings-download.*?href="(.*?)"'''
                reg_detaila = '''.*?Bookmark.*?<span.*?>(.*?)</span.*?<span.*?>(.*?)</span.*?<span.*?>(.*?)</span'''
                #reg_detailb = '''torrent-listings-download.*?seeders.*?extra'>(.*?)<.*?seeders.*?extra.*?>(.*?)<.*?leechers.*?extra.*?>(.*?)<'''
                reg_detailb = '''torrent-listings-size".*?<span.*?>(.*?)</span.*?torrent-listings-seeders".*?<span.*?>(.*?)</span.*?torrent-listings-leechers".*?<span.*?>(.*?)</span'''
                if None != response and 0 < len(response):
                    if re.compile('<input.+?type="password"').search(response):
                        xbmc.executebuiltin((u'Notification(%s,%s)' % ('DataScene', 'Eroare la login')))
                    for block in re.compile(regex, re.DOTALL).findall(response):
                        result = re.search(regex_tr, block, re.DOTALL)
                        if result:
                            imagine = result.group(1)
                            legatura = result.group(3)
                            nume = result.group(2)
                            if imagine and legatura and nume:
                                if py3: 
                                    try: nume = html.unescape(nume)
                                    except: nume = htmlparser.HTMLParser().unescape(nume)
                                else: 
                                    nume = htmlparser.HTMLParser().unescape(nume.decode('iso-8859-1'))
                                more = re.findall(reg_detailb, block, re.DOTALL)
                                if not more:
                                    more = re.findall(reg_detaila, block, re.DOTALL)
                                if more:
                                    size, seeds, leechers = more[0]
                                    nume = " ".join(nume.split())
                                    nume = '%s%s' % (('[COLOR lime]Double Upload[/COLOR] ' if re.findall("'Double Upload'", block) else ''), nume)
                                    nume = '%s%s' % (('[COLOR lime]FREE[/COLOR] ' if re.findall('torrent-listings-freeleech|Global Freeleech', block) else ''), nume)
                                    legatura = legatura if legatura.startswith('http') else 'https://%s%s' % (self.base_url, legatura)
                                    size = "".join(size.split())
                                    seeds =  "".join(seeds.split())
                                    leechers = "".join(leechers.split())
                                    nume = '%s  (%s) [S/L: %s/%s] ' % (nume, size, seeds, leechers)
                                    size = formatsize(size)
                                    tip = ",".join(re.findall(reg_genre, block, re.DOTALL))
                                    tip = " ".join(tip.split())
                                    imagine = imagine or self.thumb
                                    plot = '%s %s' % (tip, nume if py3 else nume.encode('utf-8'))
                                    plot = '%s%s' % (('[COLOR lime]Subtitrare Română[/COLOR] ' if re.findall('"Subitrare Romana"', block) else ''), plot)
                                    info = {'Title': nume,
                                            'Plot': plot,
                                            'Genre': tip,
                                            'Size': size,
                                            'Poster': imagine}
                                    if not (seeds == '0' and not zeroseed):
                                        lists.append({'nume': nume,
                                                    'legatura': legatura,
                                                    'imagine': imagine,
                                                    'switch': 'torrent_links',
                                                    'info': info})
                                        if limit:
                                            count += 1
                                            if count == int(limit):
                                                break
                    match = re.compile('"pagination"', re.IGNORECASE | re.DOTALL).findall(response)
                    if len(match) > 0:
                        if 'page=' in url:
                            new = re.compile('page=(\d+)').findall(url)
                            nexturl = re.sub('page=(\d+)', 'page=' + str(int(new[0]) + 1), url)
                        else:
                            nexturl = '%s%s' % (url, '&page=1')
                        lists.append({'nume': 'Next',
                                      'legatura': nexturl,
                                      'imagine': self.nextimage,
                                      'switch': 'get_torrent',
                                      'info': {}})
        elif meniu == 'sortare':
            for nume, sortare in self.sortare:
                legatura = '%s%s' % (url, sortare)
                lists.append({'nume': nume,
                              'legatura': legatura,
                              'imagine': self.thumb,
                              'switch': 'get_torrent',
                              'info': info})
        elif meniu == 'torrent_links':
            # Verificăm dacă este magnet sau link .torrent
            if re.search('magnet\:', url):
                 turl = url
            else:
                 turl = self.getTorrentFile(url) # Această linie poate varia în funcție de scraper
            
            # Folosim metoda helper pentru a pasa corect parametrii
            openTorrent(self._get_torrent_params(turl, info, torraction))
            
        return lists

class eztv(Torrent):
    def __init__(self):
        self.base_url = 'eztv.re'
        self.thumb = os.path.join(media, 'eztv.png')
        self.name = 'EZTV'
        self.search_url = 'https://%s/search/%s' % (self.base_url, '%s')
        self.menu = [('Recente', "https://%s/page_0" % (self.base_url), 'recente', self.thumb),
                ('Lista Seriale', "https://%s/showlist/" % (self.base_url), 'showlist', self.thumb),
                ('Căutare', self.base_url, 'cauta', self.searchimage)]

    def parse_menu(self, url, meniu, info={}, torraction=None, limit=None):
        lists = []
        if meniu == 'get_torrent' or meniu == 'cauta' or meniu == 'recente':
            if meniu == 'cauta':
                from resources.Core import Core
                Core().searchSites({'landsearch': self.__class__.__name__})
            else:
                count = 1
                regex_table = '''\<tr\sname="hover"\s+class="forum_header_border"(.+?)\</tr\>'''
                regex_details = '''epinfo"\>(.+?)\<.+?href="(magnet.*?)".+?post"\>(.*?)\<.*?post"\>(.*?)\<.*?end"\>(.+?)\<'''
                link = fetchData(url, headers=self.headers())
                if link:
                    tables = re.findall(regex_table, link, re.DOTALL)
                    if tables:
                        imagine = self.thumb
                        if info:
                            try:
                                info = eval(info)
                                imagine = info.get('Poster') or self.thumb
                            except: pass
                        for table in tables:
                            show = re.findall(regex_details, table, re.DOTALL)
                            if show:
                                nume, legatura, marime, adaugat, seeds = show[0]
                                nume = ensure_str(re.sub('<img.*?>', '', nume))
                                seeds = ''.join(str(seeds).split()) if seeds else '-1'
                                seeds = striphtml(seeds) if not seeds == '-' else '0'
                                leechs = '0'
                                size = striphtml(marime).strip()
                                nume = '%s [COLOR green]%s[/COLOR] (%s) [S/L: %s/%s] ' % (nume, adaugat, size, seeds, leechs)
                                size = formatsize(marime)
                                info = {'Title': nume,
                                        'Plot': nume,
                                        'Size': size,
                                        'Poster': imagine}
                                if not (seeds == '0' and not zeroseed):
                                    lists.append({'nume': nume,
                                                  'legatura': legatura,
                                                  'imagine': imagine,
                                                  'switch': 'torrent_links',
                                                  'info': info})
                                    if limit:
                                        count += 1
                                        if count == int(limit):
                                            break
                        new = re.findall('/page_(\d+)', unquote(url))
                        try: new = new[0]
                        except: new = ''
                        if new:
                            nexturl = re.sub('/page_(\d+)', '/page_%s' % (int(new) + 1), unquote(url))
                        else:
                            nexturl = ''
                        if nexturl:
                            lists.append({'nume': 'Next',
                                          'legatura': nexturl,
                                          'imagine': self.nextimage,
                                          'switch': 'recente', 
                                          'info': {}})
        elif meniu == "showlist":
            regex = '''\<tr\s+name="hover"\>(.*?)\</tr'''
            regex_details = '''img\s+src="(.*?)".+?href="(.*?)".*?\>(.*?)\<.*?post"\>(.*?)\<.*?post".*?\>(.*?)\</td'''
            data = {'showlist_thumbs': "on",
                    'status': ""}
            link = fetchData(url, headers=self.headers(), data=data)
            if link:
                tables = re.findall(regex, link, re.DOTALL)
                if tables:
                    for table in tables:
                        show = re.findall(regex_details, table, re.DOTALL)
                        if show:
                            imagine, legatura, nume, status, votes = show[0]
                            imagine = 'https://%s%s' % (self.base_url, imagine)
                            legatura = 'https://%s%s' % (self.base_url, legatura)
                            nume = ensure_str(nume)
                            status = striphtml(status).strip()
                            votes = " ".join(striphtml(votes).split())
                            nume += ' [COLOR lime]Status: [/COLOR][COLOR blue]%s[/COLOR] Rating: %s' % (status, votes.strip())
                            info = {'Title': nume,
                                    'Plot': nume,
                                    'Poster': imagine}
                            lists.append({'nume': nume,
                                          'legatura': legatura,
                                          'imagine': imagine,
                                          'switch': 'get_torrent',
                                          'info': info})
                            
        elif meniu == 'torrent_links':
            action = torraction if torraction else ''
            openTorrent({'Tmode':action, 'Turl': url, 'Tsite': self.__class__.__name__, 'info': info, 'orig_url': url})
            
        return lists

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
        
        self.categorii = [('Anime', 'cat=24'),
                ('Desene', 'cat=15'),
                ('Filme 3D', 'cat=25'),
                ('Filme 4k', 'cat=6'),
                ('Filme 4k Blu-Ray', 'cat=26'),
                ('Filme Blu-Ray', 'cat=20'),
                ('Filme DVD', 'cat=2'),
                ('Filme DVD-RO', 'cat=3'),
                ('Filme HD', 'cat=4'),
                ('Filme HD-RO', 'cat=19'),
                ('Filme SD', 'cat=1'),
                ('Seriale 4k', 'cat=27'),
                ('Seriale HD', 'cat=21'),
                ('Seriale SD', 'cat=23'),
                ('Sport', 'cat=13'),
                ('Videoclip', 'cat=12'),
                ('XXX', 'cat=7')]
        
        self.menu = [('Recente', "https://%s/browse.php?cats[]=24&cats[]=15&cats[]=25&cats[]=6&cats[]=26&cats[]=20&cats[]=2&cats[]=3&cats[]=4&cats[]=19&cats[]=1&cats[]=27&cats[]=21&cats[]=23&cats[]=13&cats[]=12&incldead=0" % self.base_url, 'recente', self.thumb)]
        l = []
        for x in self.categorii:
            l.append((x[0], 'https://%s/browse.php?%s' % (self.base_url, x[1]), 'get_torrent', self.thumb))
        self.menu.extend(l)
        self.menu.extend([('Căutare', self.base_url, 'cauta', self.searchimage)])
        
        self.search_url_base = "https://%s/browse.php" % self.base_url

    def login(self):
        username = __settings__.getSetting("FLusername")
        password = __settings__.getSetting("FLpassword")
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; rv:70.1) Gecko/20100101 Firefox/70.1',
                   'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                   'Accept-Language': 'ro,en-US;q=0.7,en;q=0.3',
                   'Host': self.base_url}
        w, session = makeRequest('https://%s/login.php' % (self.base_url), name=self.__class__.__name__, headers=headers, savecookie=True)
        save_cookie(self.__class__.__name__, session)
        try: validator = re.findall("validator.*value='(.+?)'", w)[0]
        except: validator = ''
        
        if not (password or username):
            xbmc.executebuiltin((u'Notification(%s,%s)' % ('FileList.ro', 'lipsa username si parola din setari')))
            return False
            
        data = {
            'validator': validator,
            'password': password,
            'username': username,
            'unlock': '1',
            'returnto': '/'
        }
        headers = {'Origin': 'https://' + self.base_url,
                   'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; rv:70.1) Gecko/20100101 Firefox/70.1',
                   'Referer': 'https://' + self.base_url + '/',
                   'X-Requested-With': 'XMLHttpRequest',
                   'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                   'Accept-Language': 'ro,en-US;q=0.7,en;q=0.3',
                   'Host': self.base_url}
        xbmc.sleep(1000)
        x, session = makeRequest('https://%s/takelogin.php' % (self.base_url), name=self.__class__.__name__, data=data, headers=headers, savecookie=True)
        if re.search('logout.php', x):
            log('LOGGED FileListRO')
        elif re.search('Numarul maxim permis de actiuni a fost depasit', x):
            xbmc.executebuiltin((u'Notification(%s,%s)' % ('FileList.ro', u'Site in protectie, reincearca peste o ora')))
            clear_cookie(self.__class__.__name__)
        elif re.search('User sau parola gresite\.', x):
            xbmc.executebuiltin((u'Notification(%s,%s)' % ('FileList.ro', u'Parola/User gresite, verifica-le')))
            clear_cookie(self.__class__.__name__)
        else:
            pass
            
        xbmc.sleep(1000)
        save_cookie(self.__class__.__name__, session)
        try: cookiesitems = session.cookies.iteritems()
        except: cookiesitems = session.cookies.items()
        for cookie, value in cookiesitems:
            if cookie == 'pass':
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
            return True
        return False

    def cauta(self, keyword, limit=None):
        import xbmcgui, json
        
        clean_keyword = unquote(keyword)
        
        # --- 1. PRELUARE CONTEXT (pentru a gasi ID-ul IMDb) ---
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
        except:
            pass

        # --- 2. SANITIZARE TITLU PENTRU FILELIST ---
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

        # --- 3. PARSARE SEZON/EPISOD ---
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

        # --- 4. FALLBACK TMDB PENTRU IMDB ID ---
        if not imdb_id or not str(imdb_id).startswith('tt'):
            if media_type in ['episode', 'tv', 'tvshow']:
                _, api_imdb = get_show_ids_from_tmdb(title_for_search)
                if api_imdb: imdb_id = api_imdb
            else:
                _, api_imdb = get_movie_ids_from_tmdb(title_for_search, year)
                if api_imdb: imdb_id = api_imdb

        filter_data = {'mode': 'normal'}
        urls_to_scan = []
        
        if season is not None:
            if episode is not None:
                filter_data = {'mode': 'D1', 'season': int(season), 'target_ep': int(episode)}
            else:
                filter_data = {'mode': 'D2', 'season': int(season)}

        # --- 5. LOGICA CAUTARE DUPA IMDB ID ---
        if imdb_id and str(imdb_id).startswith('tt'):
            numeric_id = str(imdb_id).replace('tt', '')
            # URL de forma: browse.php?search=31193180&cat=0&searchin=3&sort=2
            url = "%s?search=%s&cat=0&searchin=3&sort=2" % (self.search_url_base, numeric_id)
            urls_to_scan = [url]
            log('[FileList] Cautare optimizata dupa IMDb ID: %s -> %s' % (imdb_id, url))
            
        # --- 6. FALLBACK LA CAUTARE VECHE TEXT ---
        else:
            log('[FileList] Nu s-a gasit IMDb ID, fallback la cautare text: %s' % clean_keyword)
            base_params = "&cat=0&searchin=1&sort=2"
            
            if season is not None:
                term_season = "%s S%02d" % (title_for_search, int(season))
                if episode is not None:
                    term_episode = "%s S%02dE%02d" % (title_for_search, int(season), int(episode))
                    url1 = "%s?search=%s%s" % (self.search_url_base, urllib.quote_plus(term_episode), base_params)
                    url2 = "%s?search=%s%s" % (self.search_url_base, urllib.quote_plus(term_season), base_params)
                    urls_to_scan = [url1, url2]
                else:
                    url = "%s?search=%s%s" % (self.search_url_base, urllib.quote_plus(term_season), base_params)
                    urls_to_scan = [url]
            else:
                url = "%s?search=%s%s" % (self.search_url_base, urllib.quote_plus(clean_keyword), base_params)
                urls_to_scan = [url]

        info_with_data = {'_filter_data': filter_data, '_scan_urls': urls_to_scan}
        if imdb_id:
            info_with_data['imdb_id'] = imdb_id
        
        return self.__class__.__name__, self.name, self.parse_menu(urls_to_scan[0], 'get_torrent', info=info_with_data, limit=None)
        
    def parse_menu(self, url, meniu, info={}, torraction=None, limit=None):
        yescat = ['24', '15', '25', '6', '26', '20', '2', '3', '4', '19', '1', '27', '21', '23', '13', '12']
        lists = []
        
        filter_data = info.get('_filter_data', {'mode': 'normal'}) if info else {'mode': 'normal'}
        scan_urls = info.get('_scan_urls', [url]) if info else [url]
        
        # === MODIFICARE ANGELITTO: Pastrare ID-uri pentru a le propaga in rezultate ===
        preserved_ids = {}
        if info:
            if info.get('tmdb_id'): preserved_ids['tmdb_id'] = info['tmdb_id']
            if info.get('imdb_id'): preserved_ids['imdb_id'] = info['imdb_id']
        # =============================================================================
        
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
                log('[FileList] Fetching: %s' % current_url)
                response = makeRequest(current_url, name=self.__class__.__name__, headers=self.headers())
                
                if not self.check_login(response):
                    response = makeRequest(current_url, name=self.__class__.__name__, headers=self.headers())
                
                if not response: continue
                
                # ===== FIX PARSARE HTML FILELIST =====
                # Spargem pagina in randuri de tabel, folosind clasa specifica
                rows = response.split("<div class='torrentrow'>")
                if len(rows) > 1:
                    rows = rows[1:] # Primul element e header-ul/continutul de dinainte
                else:
                    continue

                for block in rows:
                    try:
                        # Curatam finalul div-ului daca e prins
                        if "</div></div>" in block:
                            block = block.split("</div></div>")[0]

                        # 1. Extragem Categorie (pentru filtrare vizuala)
                        cat_match = re.search(r'browse\.php\?cat=(\d+)', block)
                        cat_id = cat_match.group(1) if cat_match else ''
                        
                        # Numele categoriei din imagine
                        cat_name_match = re.search(r"alt='([^']+)'", block)
                        if not cat_name_match:
                            # Fallback: cautam in img src
                            cat_name_match = re.search(r"src='styles/images/cat/([^.]+)\.png'", block)
                            cat_name = cat_name_match.group(1).upper() if cat_name_match else 'UNK'
                        else:
                            cat_name = cat_name_match.group(1)

                        # 2. Extragem ID si Nume (Link-ul principal)
                        # Cautam exact structura: href='details.php?id=...' title='...'
                        link_match = re.search(r"href='details\.php\?id=(\d+)'[^>]*title='([^']+)'", block)
                        if not link_match: continue
                        
                        torrent_id = link_match.group(1)
                        nume_raw = link_match.group(2)
                        legatura = "https://%s/download.php?id=%s" % (self.base_url, torrent_id)

                        # 3. Extragem Size, Seeds, Leechers prin impartirea pe celule (torrenttable)
                        # Aceasta metoda e mult mai sigura decat un regex gigant
                        cells = re.findall(r"class='torrenttable'>(.*?)</div>", block, re.DOTALL)
                        
                        # Filelist are de obicei cam 11 celule per rand. 
                        # Index 6 = Size, Index 8 = Seeds, Index 9 = Leechers (aproximativ, depinde de layout)
                        # Dar sa fim siguri, cautam pattern-uri in celule.
                        
                        size = "N/A"
                        seeds = "0"
                        leechers = "0"
                        
                        for cell in cells:
                            # Cautam Size (Cifre urmate de <br /> si unitate)
                            # Regex care accepta si intregi si zecimale: \d+(?:\.\d+)?
                            s_match = re.search(r'>(\d+(?:\.\d+)?)<br />(TB|GB|MB|KB)<', cell)
                            if s_match:
                                size = "%s %s" % (s_match.group(1), s_match.group(2))
                                continue
                            
                            # Cautam Seeds (de obicei bold si colorat, sau doar bold)
                            # Filelist seeds sunt in bold: <b><font color=#...>13</font></b> sau <b>13</b>
                            if 'styles/images/arrowup.gif' in response or 'color=#' in cell or '<b>' in cell:
                                # Incercam sa extragem un numar "curat" din celula daca pare a fi seed
                                # Dar trebuie sa distingem de leechers.
                                pass

                        # Metoda pozitională (mai sigura pe structura fixa FL)
                        # Celula 6 (index 6): Size
                        # Celula 8 (index 8): Seeds
                        # Celula 9 (index 9): Leechers
                        if len(cells) >= 10:
                            # Size
                            sz_m = re.search(r'(\d+(?:\.\d+)?)<br />(TB|GB|MB|KB)', cells[6])
                            if sz_m: size = "%s %s" % (sz_m.group(1), sz_m.group(2))
                            
                            # Seeds - curatam toate tagurile
                            seeds_text = re.sub(r'<[^>]+>', '', cells[8]).strip()
                            seeds = seeds_text.replace(',', '') if seeds_text.isdigit() else '0'
                            
                            # Leechers
                            leech_text = re.sub(r'<[^>]+>', '', cells[9]).strip()
                            leechers = leech_text.replace(',', '') if leech_text.isdigit() else '0'

                        # --- FILTRARE D1/D2 ---
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
                                
                        elif mode == 'D2': # Cautam pack-uri de sezon
                            target_s = filter_data.get('season')
                            if item_season != -1 and item_season != target_s:
                                keep_item = False
                            elif is_episode: # Daca e episod individual, il ignoram in modul D2
                                keep_item = False

                        if keep_item and not (seeds == '0' and not zeroseed):
                            if torrent_id in seen_magnets: continue
                            seen_magnets.add(torrent_id)
                            
                            # --- FORMATARE VIZUALA ---
                            badges_str = ""
                            if 'doubleup.png' in block: badges_str += '[B][COLOR blue]2X[/COLOR][/B] '
                            if 'internal.png' in block: badges_str += '[B][COLOR FFFF69B4]INT[/COLOR][/B] '
                            if 'freeleech.png' in block: badges_str += '[B][COLOR lime]FREE[/COLOR][/B] '
                            if 'romanian.png' in block: badges_str += '[B][COLOR lime]RO[/COLOR][/B] '

                            # Numele complet colorat
                            nume_afisat = '%s%s  [B][COLOR FFFDBD01]%s[/COLOR][/B] [B][COLOR FF00FA9A](%s)[/COLOR][/B] [B][COLOR FFFF69B4][S/L: %s/%s][/COLOR][/B]' % \
                                          (badges_str, nume_curat, cat_name, size, seeds, leechers)
                            
                            info_dict = {
                                'Title': nume_curat,
                                'Plot': nume_afisat, 
                                'Genre': cat_name,
                                'Size': formatsize(size),
                                'Label2': self.name,
                                'Poster': self.thumb
                            }
                            
                            # === MODIFICARE ANGELITTO: Re-atasare ID-uri la torrentul gasit ===
                            if preserved_ids:
                                info_dict.update(preserved_ids)
                            # ==================================================================
                            
                            # Incercam sa luam posterul din tooltip (daca exista)
                            img_match = re.search(r"title=\"<img src='(.*?)'", block)
                            if img_match:
                                info_dict['Poster'] = img_match.group(1)

                            appender = {'nume': nume_afisat,
                                        'legatura': legatura,
                                        'imagine': info_dict['Poster'],
                                        'switch': 'torrent_links',
                                        'info': info_dict}
                            
                            if '?search=' in current_url:
                                if str(cat_id) in yescat or meniu == 'cauta':
                                    lists.append(appender)
                            else: 
                                lists.append(appender)
                            
                            count += 1

                    except Exception as e:
                        continue
            
            # Paginare (Next Page) - Doar daca nu e cautare compusa
            if len(scan_urls) == 1 and 'search=' not in scan_urls[0]:
                match = re.compile("'pager'.+?\&page=", re.IGNORECASE | re.DOTALL).findall(response)
                if len(match) > 0:
                    if '&page=' in url:
                        new = re.compile('\&page\=(\d+)').findall(url)
                        nexturl = re.sub('\&page\=(\d+)', '&page=' + str(int(new[0]) + 1), url)
                    else:
                        nexturl = '%s%s' % (url, '&page=1')
                    lists.append({'nume': 'Next',
                                  'legatura': nexturl,
                                  'imagine': self.nextimage,
                                  'switch': 'get_torrent',
                                  'info': {}})

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
    
class fluxzone(Torrent):
    def __init__(self):
        self.base_url = 'fluxzone.org'
        self.thumb = os.path.join(media, 'fluxzone.png')
        self.name = 'FluxZone'
        self.username = __settings__.getSetting("FZusername")
        self.password = __settings__.getSetting("FZpassword")
        self.login_data = {
            'password': self.password,
            'username': self.username,
            'takelogin': '1',
            'returnto': '/'}
        self.login_url = 'http://%s/takelogin.php' % (self.base_url)
        self.login_referer = 'http://%s/login.php' % self.base_url
        self.search_url = 'http://%s/browse.php?search=%s' % (self.base_url,
                                                              '%s&blah=0&cat=0&incldead=1&sort=7&type=desc')

        self.sortare = [('După dată', '&sort=4&type=desc'),
                ('După mărime', '&sort=5&type=desc'),
                ('După downloads', '&sort=6&type=desc'),
                ('După seederi', '&sort=7&type=desc'),
                ('După leecheri', '&sort=8&type=desc')]
        
        self.categorii = [('Anime', 'cat=1'),
                ('Anime-RO', 'cat=42'),
                ('Filme Pack', 'cat=18'),
                ('Filme 3D', 'cat=39'),
                ('Filme DVD', 'cat=9'),
                ('Filme DVD-RO', 'cat=10'),
                ('Filme HD', 'cat=11'),
                ('Filme HD-RO', 'cat=12'),
                ('Filme Blu-ray', 'cat=5'),
                ('Filme Blu-Ray-RO', 'cat=6'),
                ('Filme 4k', 'cat=8'),
                ('Filme SD', 'cat=24'),
                ('Filme SD-RO', 'cat=25'),
                ('Muzica/Videoclip', 'cat=28'),
                ('Sport', 'cat=32'),
                ('Seriale SD', 'cat=21'),
                ('Seriale HD', 'cat=81'),
                ('Seriale 4k', 'cat=79'),
                ('XXX', 'cat=27')]
        self.menu = [('Recente', "http://%s/browse.php?all=1" % self.base_url, 'recente', self.thumb)]
        l = []
        for x in self.categorii:
            l.append((x[0], 'http://%s/browse.php?search=&blah=0&%s&incldead=1' % (self.base_url, x[1]), 'sortare', self.thumb))
        self.menu.extend(l)
        self.menu.extend([('Căutare', self.base_url, 'cauta', self.searchimage)])

    def parse_menu(self, url, meniu, info={}, torraction=None, limit=None):
        lists = []
        #log('link: ' + link)
        imagine = ''
        if meniu == 'get_torrent' or meniu == 'cauta' or meniu == 'recente':
            if meniu == 'cauta':
                from resources.Core import Core
                Core().searchSites({'landsearch': self.__class__.__name__})
            else:
                count = 1
                response = makeRequest(url, name=self.__class__.__name__, headers=self.headers())
                if not self.check_login(response):
                    response = makeRequest(url, name=self.__class__.__name__, headers=self.headers())
                regex = '''<tr class="browse"(.+?)</td>\n</tr>'''
                regex_tr = '''\?(cat=\d+).+?<b>(.+?)</b>.+?(?:(\[.+?\]).+?)?href="(download\.php.+?)".+?align=center>.+?>([0-9.]+<br>.+?)</f.+?>([0-9]+)</font>.+?([0-9]+)</font>'''
                if None != response and 0 < len(response):
                    if re.compile('Not logged in').search(response):
                        xbmc.executebuiltin((u'Notification(%s,%s)' % ('FluxZone', 'lipsa username si parola din setari')))
                    for block in re.compile(regex, re.DOTALL).findall(response):
                        result = re.compile(regex_tr, re.DOTALL).findall(block)
                        if result:
                            for cat, nume, genre, legatura, size, seeds, leechers in result:
                                for r,t in self.categorii:
                                    if re.search(cat, t):
                                        size = striphtml(size)
                                        nume = ('[COLOR lime]FREE[/COLOR] ' if re.findall('freetorrent.png', block) else '') + replaceHTMLCodes(nume)
                                        seeds = ''.join(str(seeds).split()) if seeds else '-1'
                                        nume = '%s  [COLOR green]%s[/COLOR] (%s) [S/L: %s/%s] ' % (nume, r, size, seeds, leechers)
                                        legatura = 'http://%s/%s' % (self.base_url, legatura)
                                        imagine = self.thumb
                                        tip = genre or ''
                                        size = formatsize(size)
                                        info = {'Title': nume,
                                                'Plot': '%s %s' % (tip, nume),
                                                'Genre': tip,
                                                'Size': size,
                                                'Poster': imagine}
                                        if not (seeds == '0' and not zeroseed):
                                            lists.append({'nume': nume,
                                                          'legatura': legatura,
                                                          'imagine': imagine,
                                                          'switch': 'torrent_links',
                                                          'info': info})
                                            if limit:
                                                count += 1
                                                if count == int(limit):
                                                    break
                                        break
                                if limit:
                                    if count == int(limit):
                                        break
                        if limit:
                            if count == int(limit):
                                break    
                    match = re.compile('pager".+?page=', re.IGNORECASE | re.DOTALL).findall(response)
                    if len(match) > 0:
                        if 'page=' in url:
                            new = re.compile('page=(\d+)').findall(url)
                            nexturl = re.sub('page=(\d+)', 'page=' + str(int(new[0]) + 1), url)
                        else:
                            nexturl = '%s%s' % (url, '&page=1')
                        lists.append({'nume': 'Next',
                                      'legatura': nexturl,
                                      'imagine': self.nextimage,
                                      'switch': 'get_torrent',
                                      'info': {}})
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
            openTorrent(self._get_torrent_params(turl, info, torraction))
            
        return lists

class ieet(Torrent):
    def __init__(self):
        self.base_url = 'www.1377x.to'
        self.thumb = os.path.join(media, 'ieetx.png')
        self.name = '1377x'
        self.search_url = "https://%s/sort-search/%s" % (self.base_url, '%s/seeders/desc/1/')
        self.menu = [('Recente', "https://%s/cat/Movies/1/" % self.base_url, 'recente', self.thumb),
                ('Seriale Recente', "https://%s/cat/TV/1/" % self.base_url, 'get_torrent', self.thumb),
                #('Categorii Filme', "https://%s/movie-lib-sort/%s/%s/desc/%s/1/", 'categorii', thumb),
                ('Filme', "https://%s/%s/Movies/%s/", 'sortare', self.thumb),
                ('Seriale', "https://%s/%s/TV/%s/", 'sortare', self.thumb),
                ('Documentare', "https://%s/%s/Documentaries/%s/", 'sortare', self.thumb),
                ('Anime', "https://%s/%s/Anime/%s/", 'sortare', self.thumb),
                ('Adulți', "https://%s/%s/XXX/%s/", 'sortare', self.thumb),
                ('Librarie Filme', "https://%s/movie-library/1/" % self.base_url, 'librarie', self.thumb),
                ('Filme populare in ultimele 24 ore', "https://%s/popular-movies" % self.base_url, 'get_torrent', self.thumb),
                ('Filme populare saptamana asta', "https://%s/popular-movies-week" % self.base_url, 'get_torrent', self.thumb),
                ('Top 100 Documentare', "https://%s/top-100-documentaries" % self.base_url, 'get_torrent', self.thumb),
                ('Top 100 Filme ', "https://%s/top-100-movies" % self.base_url, 'get_torrent', self.thumb),
                ('Top 100 TV ', "https://%s/top-100-television" % self.base_url, 'get_torrent', self.thumb),
                ('Top 100 Filme în engleză ', "https://%s/top-100-eng-movies" % self.base_url, 'get_torrent', self.thumb),
                ('Top 100 Filme în alte limbi ', "https://%s/top-100-non-eng-movies" % self.base_url, 'get_torrent', self.thumb),
                ('Top 100 Anime', "https://%s/top-100-anime" % self.base_url, 'get_torrent', self.thumb),
                ('Top 100 Adulți', "https://%s/top-100-xxx" % self.base_url, 'get_torrent', self.thumb),
                ('Căutare', self.base_url, 'cauta', self.searchimage)]

    def get_cat(self):
        cats = []
        link = fetchData('https://%s/movie-library/1/' % self.base_url)
        regex = '''select name="genre"(.+?)</select'''
        sub_regex = '''value="(.+?)">(.+?)<'''
        match = re.findall(regex, link, re.IGNORECASE | re.DOTALL)
        if match:
            for result in match:
                match2 = re.findall(sub_regex, result, re.IGNORECASE | re.DOTALL)
                if match2:
                    for legatura, nume in match2:
                        cats.append((legatura.replace(" ", "+").replace("-", "+"), nume))
        return cats
    
    def get_ani(self):
        ani = []
        link = fetchData('https://%s/movie-library/1/' % self.base_url)
        regex = '''select name="year"(.+?)</select'''
        sub_regex = '''value="(.+?)">(.+?)<'''
        match = re.findall(regex, link, re.IGNORECASE | re.DOTALL)
        if match:
            for result in match:
                match2 = re.findall(sub_regex, result, re.IGNORECASE | re.DOTALL)
                if match2:
                    for legatura, nume in match2:
                        ani.append((legatura.replace(" ", "+").replace("-", "+"), nume))
        return ani
    
    def get_lang(self):
        lang = []
        link = fetchData('https://%s/movie-library/1/' % self.base_url)
        regex = '''select name="lang"(.+?)</select'''
        sub_regex = '''value="(.+?)">(.+?)<'''
        match = re.findall(regex, link, re.IGNORECASE | re.DOTALL)
        if match:
            for result in match:
                match2 = re.findall(sub_regex, result, re.IGNORECASE | re.DOTALL)
                if match2:
                    for legatura, nume in match2:
                        lang.append((legatura.replace(" ", "+").replace("-", "+"), nume))
        return lang
    
    def get_score(self):
        score = [('score', 'Movie Score'),
                 ('popularity', 'Popularity'),
                 ('release', 'Release Date'),
                 ('latest', 'Latest Submited')]
        return score
    
    def get_sort(self): #sort-cat/Movies/time/desc/1/
        score = [('1', 'Default'),
                 ('time/desc/1', 'Time'),
                 ('size/desc/1', 'Size'),
                 ('seeders/desc/1', 'Seeders'),
                 ('leechers/desc/1', 'Leechers')]
        return score
    
    def get_ascend(self):
        ascend = [('desc', 'Descending'),
                  ('asc', 'Ascending')]
        return ascend
    
    def parse_menu(self, url, meniu, info={}, torraction=None, limit=None):
        #log(self.get_cat())
        lists = []
        #log('link: ' + link)
        imagine = ''
        if meniu == 'librarie':
            link = fetchData(url)
            regex = '''data-target.+?original="(.+?)".+?header">(.+?)<div.+?category">(.+?)</div.+?"content.+?">(.+?)</div.+?download".+?href="(.+?)"'''
            if re.search("/1/", url):
                lists.append({'nume':'[COLOR lime]Categorii[/COLOR]',
                              'legatura': "https://%s/movie-lib-sort/%s/all/score/desc/all/1/",
                              'imagine': self.thumb,
                              'switch': 'categorii',
                              'info': {}})
                lists.append({'nume': '[COLOR lime]Ani[/COLOR]',
                              'legatura': "https://%s/movie-lib-sort/all/all/score/desc/%s/1/",
                              'imagine': self.thumb,
                              'switch': 'ani',
                              'info': {}})
                lists.append({'nume': '[COLOR lime]Limba[/COLOR]',
                              'legatura': "https://%s/movie-lib-sort/all/%s/score/desc/all/1/",
                              'imagine': self.thumb,
                              'switch': 'lang',
                              'info': {}})
            if link:
                match = re.findall(regex, link, re.DOTALL)
                for imagine, nume, categorie, descriere, legatura in match:
                    imagine = 'http:%s' % (imagine) if imagine.startswith('//') else imagine
                    #log(imagine)
                    legatura = 'https://%s%s' % (self.base_url, legatura)
                    descriere = ensure_str(replaceHTMLCodes(striphtml(descriere))).strip()
                    nume = ensure_str(replaceHTMLCodes(striphtml(nume))).strip()
                    info = {'Title': nume,
                        'Plot': descriere,
                        'Poster': imagine}
                    lists.append({'nume': nume,
                                  'legatura':legatura,
                                  'imagine': imagine,
                                  'switch': 'get_torrent',
                                  'info': info})
                match = re.findall('("pagination")', link, re.IGNORECASE)
                if len(match) > 0:
                    if re.search("/(\d+)/", url):
                        new = re.compile('/(\d+)/').findall(url)
                        nexturl = re.sub('/(\d+)/', '/' + str(int(new[0]) + 1) + '/', url)
                        lists.append({'nume': 'Next',
                                      'legatura': nexturl,
                                      'imagine': self.nextimage,
                                      'switch': meniu,
                                      'info': {}})
        elif meniu == 'get_torrent' or meniu == 'cauta' or meniu == 'recente':
            if meniu == 'cauta':
                from resources.Core import Core
                Core().searchSites({'landsearch': self.__class__.__name__})
            else:
                count = 1
                link = fetchData(url)
                if link:
                    infos = {}
                    regex = '''<tr>(.+?)</tr>'''
                    regex_tr = '''a><a href="(.+?)">(.+?)<.+?seeds">(.+?)<.+?leeches">(.+?)<.+?size.+?>(.+?)<'''
                    tables = re.findall(regex, link, re.IGNORECASE | re.DOTALL)
                    if tables:
                        for table in tables:
                            match = re.findall(regex_tr, table, re.IGNORECASE | re.DOTALL)
                            if match:
                                for legatura, nume, seeds, leechers, size in match:
                                    size = size.replace('&nbsp;', ' ')
                                    seeds = ''.join(str(seeds).split()) if seeds else '-1'
                                    legatura = 'https://%s%s' % (self.base_url, legatura) if legatura.startswith('/') else legatura
                                    nume = '%s  (%s) [S/L: %s/%s] ' % (striphtml(nume), size, seeds, leechers)
                                    size = formatsize(size)
                                    if not info:
                                        infos = {'Title': nume,
                                                'Plot': nume,
                                                'Size': size,
                                                'Poster': self.thumb}
                                    else:
                                        infos = info
                                        try:

                                            infos = eval(str(infos))
                                            infos['Size'] = size
                                            infos['Plot'] = '%s - %s' % (nume, infos['Plot'])
                                        except: pass
                                        #infos.update({'Plot': '%s - %s' % (nume, infos['Plot'])})
                                    if not (seeds == '0' and not zeroseed):
                                        lists.append({'nume':nume,
                                                      'legatura': legatura,
                                                      'imagine':self.thumb,
                                                      'switch': 'torrent_links',
                                                      'info': infos})
                                        if limit:
                                            count += 1
                                            if count == int(limit):
                                                break
                            if limit:
                                if count == int(limit):
                                    break
                    match = re.compile('"pagination"', re.IGNORECASE).findall(link)
                    if len(match) > 0:
                        if re.search("/(\d+)/", url):
                            new = re.compile('/(\d+)/').findall(url)
                            nexturl = re.sub('/(\d+)/', '/' + str(int(new[0]) + 1) + '/', url)
                            lists.append({'nume': 'Next',
                                          'legatura': nexturl,
                                          'imagine': self.nextimage,
                                          'switch': meniu, 
                                          'info': {}})
        elif meniu == 'categorii' or meniu == 'ani' or meniu == 'lang':
            if meniu == 'categorii': categorii = self.get_cat()
            elif meniu == 'ani': categorii = self.get_ani()
            elif meniu == 'lang': categorii = self.get_lang()
            if categorii:
                for legatura, nume in categorii:
                    legatura = url % (self.base_url, legatura)
                    lists.append({'nume': nume,
                                    'legatura': legatura,
                                    'imagine': imagine,
                                    'switch': 'librarie',
                                    'info': info})
        elif meniu == 'sortare':
            sort = self.get_sort()
            if sort:
                for legatura, nume in sort:
                    if nume == 'Default':
                        legatura = url % (self.base_url, 'cat', legatura)
                    else:
                        legatura = url % (self.base_url, 'sort-cat' ,legatura)
                    lists.append({'nume': nume,
                                    'legatura': legatura,
                                    'imagine': imagine,
                                    'switch': 'get_torrent',
                                    'info': info})
        elif meniu == 'torrent_links':
            link = fetchData(url)
            try: surl = re.compile('href="(magnet:.+?)"', re.DOTALL).findall(link)[0]
            except: surl = None
            action = torraction if torraction else ''
            if surl: openTorrent({'Tmode':action, 'Turl': surl, 'Tsite': self.__class__.__name__, 'info': info, 'orig_url': url})
            
        return lists
    
class kickass(Torrent):
    def __init__(self):
        self.base_url = 'katcr.to'
        self.thumb = os.path.join(media, 'kickass.png')
        self.name = 'Kickass'
        self.search_url = "https://%s/usearch/%s" % (self.base_url, '%s/?sortby=seeders&sort=desc')
        self.menu = [('Recente', "https://%s/new/" % self.base_url, 'recente', self.thumb),
                ('Filme', "https://%s/movies/" % self.base_url, 'sortare', self.thumb),
                ('Seriale', "https://%s/tv/" % self.base_url, 'sortare', self.thumb),
                ('Documentare', "https://%s/documentaries/" % self.base_url, 'sortare', self.thumb),
                ('Anime', "https://%s/anime/" % self.base_url, 'sortare', self.thumb),
                ('XXX', "https://%s/xxx/" % self.base_url, 'sortare', self.thumb),
                ('Filme populare', "https://%s/popular-movies" % self.base_url, 'sortare', self.thumb),
                ('Seriale populare', "https://%s/popular-tv" % self.base_url, 'sortare', self.thumb),
                ('Anime populare', "https://%s/popular-anime/" % self.base_url, 'sortare', self.thumb),
                ('XXX populare', "https://%s/popular-xxx/" % self.base_url, 'sortare', self.thumb),
                ('Filme Top 100', "https://%s/top-100-movies" % self.base_url, 'get_torrent', self.thumb),
                ('Seriale Top 100', "https://%s/top-100-television" % self.base_url, 'get_torrent', self.thumb),
                ('Anime Top 100', "https://%s/top-100-anime" % self.base_url, 'get_torrent', self.thumb),
                ('XXX Top 100', "https://%s/top-100-xxx" % self.base_url, 'get_torrent', self.thumb),
                ('Căutare', self.base_url, 'cauta', self.searchimage)]

        self.sortare = [('Recent adăugate', '?sortby=time&sort=desc'),
                ('După seederi', '?sortby=seeders&sort=desc'),
                ('După Mărime', '?sortby=size&sort=desc'),
                ('După leecheri', '?sortby=leechers&sort=desc')]

    def parse_menu(self, url, meniu, info={}, torraction=None, limit=None):
        lists = []
        #log('link: ' + link)
        imagine = ''
        if meniu == 'get_torrent' or meniu == 'cauta' or meniu == 'recente':
            accepted = ['Movies', 'TV', 'XXX',  'Documentaries', 'Anime']
            acceptcats = ['VideoType']
            if meniu == 'cauta':
                from resources.Core import Core
                Core().searchSites({'landsearch': self.__class__.__name__})
            else:
                count = 1
                link = fetchData(url, headers=self.headers())
                #log(link)
                if link:
                    infos = {}
                    regex = '''\<tr class=".+?"(.+?)\</tr\>'''
                    regex_tr = r'''href=".+?href="(.+?)"(?:.+?class="torType(.+?)".+?)?.+?\<a href=".+?html"\s+class=.+?k"\>(.+?)\</a\>.+?(?:.+?in\s+\<span.+?"\>(.+?)\</a\>.+?)?.+?\<td class="nobr center"\>(.+?)\</.+?\<td class="green center"\>([\dN\/A\s]+)\</td\>.+?\<td class="red lasttd center"\>([\dN\/A\s]+)\</td\>'''
                    for trr in re.findall(regex, link, re.IGNORECASE | re.DOTALL):
                        match = re.findall(regex_tr, trr, re.IGNORECASE | re.DOTALL)
                        if match:
                            for legatura, forum1, nume, forum, size, seeds, leechers in match:
                                forum = ''.join(forum.split()) if forum else ''
                                forum1 = ''.join(forum1.split()) if forum1 else ''
                                if forum in accepted or forum1 in acceptcats:
                                    legatura = unquote(re.sub(r'[htps://].+?/.+?\?url=', '', legatura))
                                    legatura = 'https://%s%s' % (self.base_url, legatura)
                                    nume = unescape(striphtml(nume)).decode('utf-8').strip()
                                    seeds = ''.join(str(seeds).split()) if seeds else '-1'
                                    leechers = leechers.strip()
                                    size = striphtml(size).strip()
                                    if seeds == 'N/A' : seeds = '0'
                                    if leechers == 'N/A': leechers = '0'
                                    nume = '%s  [COLOR green]%s[/COLOR] (%s) [S/L: %s/%s] ' % (striphtml(nume), forum, size, seeds, leechers)
                                    size = formatsize(size)
                                    if not info:
                                        infos = {'Title': nume,
                                                'Plot': nume,
                                                'Size': size,
                                                'Poster': self.thumb}
                                    else:
                                        infos = info
                                        try:
                                            infos = eval(str(infos))
                                            infos['Size'] = size
                                            infos['Plot'] = '%s - %s' % (nume, infos['Plot'])
                                        except: pass
                                        #infos.update({'Plot': '%s - %s' % (nume, infos['Plot'])})
                                    if not (seeds == '0' and not zeroseed):
                                        lists.append({'nume': nume,
                                                      'legatura': legatura,
                                                      'imagine': self.thumb,
                                                      'switch': 'torrent_links',
                                                      'info': infos})
                                        if limit:
                                            count += 1
                                            if count == int(limit):
                                                break
                        if limit:
                            if count == int(limit):
                                break
                    match = re.findall('(class="pages)', link, re.IGNORECASE)
                    if len(match) > 0:
                        if re.search("/(\d+)/", url): 
                            new = re.findall("/(\d+)/", url)
                            nexturl = re.sub('/(\d+)/', '/%s/' % (str(int(new[0]) + 1)), url)
                        else:
                            try:
                                newn = re.search(r'(.*)/\?(.*)',url)
                                nexturl = '%s/2/?%s' % (newn.group(1), newn.group(2))
                            except: 
                                nexturl = ('%s2/' % url) if url.endswith('/') else ''
                        lists.append({'nume': 'Next',
                                      'legatura': nexturl,
                                      'imagine': self.nextimage,
                                      'switch': meniu,
                                      'info': {}})
        elif meniu == 'sortare':
            for nume, sortare in self.sortare:
                legatura = '%s%s' % (url, sortare)
                lists.append({'nume': nume,
                                'legatura': legatura,
                                'imagine': self.thumb,
                                'switch': 'get_torrent',
                                'info': info})
        elif meniu == 'torrent_links':
            link = fetchData(url, headers=self.headers())
            turl = ''
            if link:
                torrent = re.findall('href="(magnet.+?)"', link)
                if torrent:
                    turl = torrent[0]
            action = torraction if torraction else ''
            if turl:
                openTorrent(self._get_torrent_params(turl, info, torraction))
            
        return lists
    
class kickass2(Torrent):
    def __init__(self):
        self.base_url = 'kick4ss.com'
        self.thumb = os.path.join(media, 'kickass2.png')
        self.name = 'Kickass2'
        self.search_url = "https://%s/usearch/%s" % (self.base_url, '%s/?field=seeders&sorder=desc')
        self.menu = [('Recente', "https://%s/new/" % self.base_url, 'recente', self.thumb),
                ('Filme', "https://%s/movies/" % self.base_url, 'recente', self.thumb),
                ('Seriale', "https://%s/tv/" % self.base_url, 'recente', self.thumb),
                ('XXX', "https://%s/xxx/" % self.base_url, 'recente', self.thumb),
                ('Toate', "https://%s/full/" % self.base_url, 'recente', self.thumb),
                ('Căutare', self.base_url, 'cauta', self.searchimage)]

    def parse_menu(self, url, meniu, info={}, torraction=None, limit=None):
        lists = []
        #log('link: ' + link)
        imagine = ''
        if meniu == 'get_torrent' or meniu == 'cauta' or meniu == 'recente':
            accepted = ['Movies', 'TV', 'XXX']
            acceptcats = ['VideoType']
            if meniu == 'cauta':
                from resources.Core import Core
                Core().searchSites({'landsearch': self.__class__.__name__})
            else:
                count = 1
                link = fetchData(url, headers=self.headers())
                #log(link)
                if link:
                    infos = {}
                    regex = '''<tr class=".+?" id=(.+?)</tr>'''
                    regex_tr = r'''title="Download torrent file" href="(.+?)".+?(?:.+?class="torType(.+?)".+?)?<a href=".+?html" class=.+?k">(.+?)</a>.+?(?:.+?in <span.+?"><strong>.+?">(.+?)</a>.+?)?.+?<td class="nobr center">(.+?)</.+?<td class="green center">(\d+?|N/A)</td>.+?<td class="red lasttd center">(?:\s+)?(\d+?|N/A)</td>'''
                    for trr in re.findall(regex, link, re.IGNORECASE | re.DOTALL):
                        match = re.findall(regex_tr, trr, re.IGNORECASE | re.DOTALL)
                        if match:
                            for legatura, forum1, nume, forum, size, seeds, leechers in match:
                                forum = ''.join(forum.split()) if forum else ''
                                forum1 = ''.join(forum1.split()) if forum1 else ''
                                if forum in accepted or forum1 in acceptcats:
                                    legatura = unquote(re.sub(r'[htps://].+?/.+?\?url=', '', legatura))
                                    nume = unescape(striphtml(nume)).decode('utf-8').strip()
                                    size = striphtml(size)
                                    seeds = ''.join(str(seeds).split()) if seeds else '-1'
                                    if seeds == 'N/A' : seeds = '0'
                                    if leechers == 'N/A': leechers = '0'
                                    nume = '%s  [COLOR green]%s[/COLOR] (%s) [S/L: %s/%s] ' % (striphtml(nume), forum, size, seeds, leechers)
                                    size = formatsize(size)
                                    if not info:
                                        infos = {'Title': nume,
                                                'Plot': nume,
                                                'Size': size,
                                                'Poster': self.thumb}
                                    else:
                                        infos = info
                                        try:
                                            infos = eval(str(infos))
                                            infos['Size'] = size
                                            infos['Plot'] = '%s - %s' % (nume, infos['Plot'])
                                        except: pass
                                        #infos.update({'Plot': '%s - %s' % (nume, infos['Plot'])})
                                    if not (seeds == '0' and not zeroseed):
                                        lists.append({'nume': nume,
                                                        'legatura': legatura,
                                                        'imagine': self.thumb,
                                                        'switch': 'torrent_links',
                                                        'info': infos})
                                        if limit:
                                            count += 1
                                            if count == int(limit):
                                                break
                        if limit:
                            if count == int(limit):
                                break
                    match = re.findall('(class="pages)', link, re.IGNORECASE)
                    if len(match) > 0:
                        if re.search("/(\d+)(?:$|\?)?", url): 
                            new = re.findall("/(\d+)(?:$|\?)?", url)
                            nexturl = re.sub('/(\d+)', '/' + str(int(new[0]) + 1), url)
                        else:
                            try:
                                newn = re.search(r'(.*)/(.*)',url)
                                nexturl = '%s/2%s' % (newn.group(1), newn.group(2))
                            except: 
                                nexturl = '%s2' % url
                        lists.append({'nume': 'Next',
                                      'legatura': nexturl,
                                      'imagine': self.nextimage,
                                      'switch': meniu,
                                      'info': {}})
        elif meniu == 'torrent_links':
            action = torraction if torraction else ''
            openTorrent({'Tmode':action, 'Turl': url, 'Tsite': self.__class__.__name__, 'info': info, 'orig_url': url})
            
        return lists
    
class lime(Torrent):
    def __init__(self):
        self.base_url = 'www.limetorrents.info'
        self.thumb = os.path.join(media, 'limetorrents.jpg')
        self.name = 'LimeTorrents'
        self.search_url = "https://%s/search/all/%s" % (self.base_url, '%s/seeds/1/')
        self.menu = [('Recente', "https://%s/latest100" % self.base_url, 'recente', self.thumb),
                ('Filme', "https://%s/browse-torrents/Movies/" % self.base_url, 'sortare', self.thumb),
                ('Seriale', "https://%s/browse-torrents/TV-shows/" % self.base_url, 'sortare', self.thumb),
                ('Seriale Clasice', "https://%s/browse-torrents/TV-shows-Classics/" % self.base_url, 'sortare', self.thumb),
                ('Anime', "https://%s/browse-torrents/Anime/" % self.base_url, 'sortare', self.thumb),
                ('Altele', "https://%s/browse-torrents/Other-Other/" % self.base_url, 'sortare', self.thumb),
                ('Top 100', "https://%s/cat_top/16/Movies/" % self.base_url, 'get_torrent', self.thumb),
                ('Top 100 Filme', "https://%s/top100" % self.base_url, 'get_torrent', self.thumb),
                ('Top 100 TV', "https://%s/cat_top/20/TV-shows/" % self.base_url, 'get_torrent', self.thumb),
                ('Top 100 Anime', "https://%s/cat_top/1/Anime/" % self.base_url, 'get_torrent', self.thumb),
                ('Top 100 Altele', "https://%s/cat_top/27/Other-Other/" % self.base_url, 'get_torrent', self.thumb),
                ('Căutare', self.base_url, 'cauta', self.searchimage)]
    
    def get_sort(self):
        score = [('Dupa data adaugarii', 'date/1/'),
                 ('Dupa seeders', 'seeds/1/'),
                 ('Dupa leechers', 'leechs/1/'),
                 ('Dupa marime', 'size/1/')]
        return score

    def parse_menu(self, url, meniu, info={}, torraction=None, limit=None):
        #log(self.get_cat())
        nocat = ['Games', 'Applications']
        lists = []
        #log('link: ' + link)
        imagine = ''
        if meniu == 'get_torrent' or meniu == 'cauta' or meniu == 'recente':
            if meniu == 'cauta':
                from resources.Core import Core
                Core().searchSites({'landsearch': self.__class__.__name__})
            else:
                count = 1
                link = fetchData(url)
                if link:
                    infos = {}
                    regex = '''<tr(.+?)</tr'''
                    regex_tr = '''(?:href="(.+?)".+?)?href="(.+?)">(.+?)<.+?normal">(.+?)<.+?(?:normal">(.+?)<.+?.+?)?tdseed">(.+?)<.+?tdleech">(.+?)<'''
                    tables = re.findall(regex, link)
                    if tables:
                        for table in tables:
                            match = re.findall(regex_tr, table)
                            if match:
                                for legatura, legaturadetalii, nume, time, size, seeds, leechers in match:
                                    canshow = True
                                    seeds = ''.join(str(seeds).split()) if seeds else '-1'
                                    size = size.replace('&nbsp;', ' ').strip()
                                    time = time.replace('&nbsp;', ' ').strip()
                                    cat = re.search('in\s(.*?)$', time)
                                    if cat:
                                        if cat.group(1) in nocat:
                                            canshow = False
                                    else:
                                        canshow = True
                                    if canshow:
                                        legaturadetalii = 'https://%s%s' % (self.base_url, legaturadetalii)
                                        legatura  = legaturadetalii # if not legatura else legatura
                                        nume = '%s [COLOR green]%s[/COLOR] (%s) [S/L: %s/%s] ' % (striphtml(nume), time, size, seeds, leechers)
                                        size = formatsize(size)
                                        if not info:
                                            infos = {'Title': nume,
                                                    'Plot': nume,
                                                    'Size': size,
                                                    'Poster': self.thumb}
                                        else:
                                            infos = info
                                            try:
                                                infos = eval(str(infos))
                                                infos['Size'] = size
                                                infos['Plot'] = '%s - %s' % (nume, infos['Plot'])
                                            except: pass
                                            #infos.update({'Plot': '%s - %s' % (nume, infos['Plot'])})
                                        if not (seeds == '0' and not zeroseed):
                                            lists.append({'nume': nume,
                                                            'legatura': legatura,
                                                            'imagine': self.thumb,
                                                            'switch': 'torrent_links',
                                                            'info': infos})
                                            if limit:
                                                count += 1
                                                if count == int(limit):
                                                    break
                            if limit:
                                if count == int(limit):
                                    break
                    match = re.compile('next page', re.IGNORECASE).findall(link)
                    if len(match) > 0:
                        if re.search("/(\d+)/", url):
                            new = re.compile('/(\d+)/').findall(url)
                            nexturl = re.sub('/(\d+)/', '/' + str(int(new[0]) + 1) + '/', url)
                        else:
                            nexturl = '%s%s2/' % (url, '/' if url.endswith('/') else '//')
                        lists.append({'nume': 'Next',
                                      'legatura': nexturl,
                                      'imagine': self.nextimage,
                                      'switch': meniu,
                                      'info': {}})
        elif meniu == 'sortare':
            sort = self.get_sort()
            if sort:
                for nume, legatura in sort:
                    legatura = '%s%s' % (url, legatura)
                    lists.append({'nume': nume,
                                      'legatura': legatura,
                                      'imagine': imagine,
                                      'switch': 'get_torrent',
                                      'info': info})
        elif meniu == 'torrent_links':
            if url.endswith('.html'):
                link = fetchData(url)
                try: surl = re.search('href="(magnet:.+?)"', link).group(1)
                except: surl = None
            else:
                surl = url
            action = torraction if torraction else ''
            if surl: openTorrent({'Tmode':action, 'Turl': surl, 'Tsite': self.__class__.__name__, 'info': info, 'orig_url': url})
            
        return lists

class uindex(Torrent):
    def __init__(self):
        self.base_url = 'uindex.org'
        self.thumb = os.path.join(media, 'uindex.png')
        self.name = '[B]UIndex[/B]'
        self.search_url = "https://%s/search.php" % self.base_url
        self.menu = [('Căutare', self.base_url, 'cauta', self.searchimage)]

    def cauta(self, keyword, limit=None):
        clean_keyword = unquote(keyword)
        match_s_e = re.search(r'(.*?)\s+S(\d+)(?:E(\d+))?', clean_keyword, re.IGNORECASE)
        
        filter_data = {'mode': 'normal'}
        urls_to_scan = []
        
        if match_s_e:
            title = match_s_e.group(1).strip()
            season = match_s_e.group(2)
            episode = match_s_e.group(3)
            
            # Construim termeni de cautare specifici
            term_season = "%s S%s" % (title, season)
            
            if episode:
                # MODE D1: Sezon si Episod
                # STRATEGIA DUALA: Cautam si SxxExx, si Sxx (pentru pack-uri)
                term_episode = "%s S%sE%s" % (title, season, episode)
                
                url1 = "%s?search=%s&c=0&sort=seeders&order=DESC" % (self.search_url, urllib.quote_plus(term_episode))
                url2 = "%s?search=%s&c=0&sort=seeders&order=DESC" % (self.search_url, urllib.quote_plus(term_season))
                
                urls_to_scan = [url1, url2] # Ordinea conteaza, prioritate episodul
                
                filter_data = {
                    'mode': 'D1',
                    'season': int(season),
                    'target_ep': int(episode)
                }
            else:
                # MODE D2: Doar Sezon
                url = "%s?search=%s&c=0&sort=seeders&order=DESC" % (self.search_url, urllib.quote_plus(term_season))
                urls_to_scan = [url]
                
                filter_data = {
                    'mode': 'D2',
                    'season': int(season)
                }
        else:
            # Caz Normal (Film sau Cautare text simpla)
            url = "%s?search=%s&c=0&sort=seeders&order=DESC" % (self.search_url, urllib.quote_plus(clean_keyword))
            urls_to_scan = [url]
            filter_data = {'mode': 'normal'}

        # Injectam lista de URL-uri in info pentru a fi procesata de parse_menu
        info_with_data = {'_filter_data': filter_data, '_scan_urls': urls_to_scan}
        
        # URL-ul principal e doar de forma, munca se face pe lista _scan_urls
        return self.__class__.__name__, self.name, self.parse_menu(urls_to_scan[0], 'get_torrent', info=info_with_data, limit=None)

    def parse_menu(self, url, meniu, info={}, torraction=None, limit=None):
        lists = []
        imagine = self.thumb
        
        # Extragem datele injectate
        filter_data = info.get('_filter_data', {'mode': 'normal'}) if info else {'mode': 'normal'}
        scan_urls = info.get('_scan_urls', [url]) if info else [url]
        
        # Curatam info pentru a nu pasa date interne mai departe
        if info:
            info = info.copy()
            if '_filter_data' in info: del info['_filter_data']
            if '_scan_urls' in info: del info['_scan_urls']
        
        if meniu == 'cauta':
            from resources.Core import Core
            Core().searchSites({'landsearch': self.__class__.__name__})
            
        elif meniu == 'get_torrent' or meniu == 'recente':
            
            seen_magnets = set() # Pentru deduplicare
            count = 0
            
            # Iteram prin toate URL-urile de cautare (ex: S03E08 si apoi S03)
            for current_url in scan_urls:
                log('[UIndex] Fetching: %s' % current_url)
                link = fetchData(current_url, headers=self.headers())
                
                if not link: continue
                
                # Regex validat anterior
                regex = r"href='(magnet:\?xt=urn:btih:[^']+)'[^>]*>.*?href='/details\.php\?id=\d+'>([^<]+)</a>.*?<td[^>]*>([\d\.,]+\s*[KMGT]B)</td>.*?class='g'>(\d+)</span>.*?class='b'>(\d+)</span>"
                matches = re.findall(regex, link, re.DOTALL | re.IGNORECASE)
                
                if not matches:
                     regex_backup = r"href='/details\.php\?id=\d+'>([^<]+)</a>.*?href='(magnet:\?xt=urn:btih:[^']+)'[^>]*>.*?<td[^>]*>([\d\.,]+\s*[KMGT]B)</td>.*?class='g'>(\d+)</span>.*?class='b'>(\d+)</span>"
                     matches_inv = re.findall(regex_backup, link, re.DOTALL | re.IGNORECASE)
                     matches = [(m[1], m[0], m[2], m[3], m[4]) for m in matches_inv]

                log('[UIndex] Matches for current URL: %d' % len(matches))

                for magnet, nume_raw, size_raw, seeds, leechers in matches:
                    try:
                        # Deduplicare rapida pe baza magnet link
                        if magnet in seen_magnets:
                            continue
                            
                        nume_curat = striphtml(nume_raw).strip()
                        nume_curat = re.sub(r'(?i)www\.UIndex\.org\s+-\s+', '', nume_curat).strip()
                        legatura = magnet.strip()
                        size = size_raw.strip()
                        
                        # --- FILTRARE ---
                        mode = filter_data.get('mode')
                        
                        # Detectie
                        s_match = re.search(r'(?i)S(\d+)', nume_curat)
                        e_match = re.search(r'(?i)E(\d+)', nume_curat)
                        
                        item_season = int(s_match.group(1)) if s_match else -1
                        item_episode = int(e_match.group(1)) if e_match else -1
                        
                        is_pack = (item_season != -1 and item_episode == -1)
                        is_episode = (item_season != -1 and item_episode != -1)

                        keep_item = True

                        if mode == 'D1':
                            target_s = filter_data.get('season')
                            target_e = filter_data.get('target_ep')
                            
                            # Sezon gresit?
                            if item_season != -1 and item_season != target_s:
                                keep_item = False
                            
                            # Daca e episod individual, trebuie sa fie cel cautat
                            elif is_episode and item_episode != target_e:
                                keep_item = False
                                
                            # Pack-urile (is_pack) trec, Episodul corect trece

                        elif mode == 'D2':
                            target_s = filter_data.get('season')
                            # Sezon gresit?
                            if item_season != -1 and item_season != target_s:
                                keep_item = False
                            # Daca e episod individual, il aruncam
                            elif is_episode:
                                keep_item = False

                        if keep_item and not (seeds == '0' and not zeroseed):
                            nume_pentru_lista = '%s [B][COLOR FF00FA9A](%s)[/COLOR][/B] [B][COLOR FFFF69B4][S/L: %s/%s][/COLOR][/B]' % (nume_curat, size, seeds, leechers)
                            info_secundara = '[B][COLOR FF00FA9A]Size: %s[/COLOR][/B]  [B][COLOR FFFF69B4]S/L: %s/%s[/COLOR][/B]' % (size, seeds, leechers)
                            
                            info_dict = {
                                'Title': nume_curat,
                                'Plot': nume_curat + '\n' + info_secundara,
                                'Size': formatsize(size),
                                'Label2': info_secundara,
                                'Poster': imagine
                            }
                            
                            # === MODIFICARE ANGELITTO: Propagare ID-uri catre Player ===
                            if info.get('tmdb_id'): info_dict['tmdb_id'] = info['tmdb_id']
                            if info.get('imdb_id'): info_dict['imdb_id'] = info['imdb_id']
                            # ===========================================================
                            
                            lists.append({
                                'nume': nume_pentru_lista,
                                'legatura': legatura,
                                'imagine': imagine,
                                'switch': 'torrent_links',
                                'info': info_dict
                            })
                            
                            seen_magnets.add(magnet) # Marcam ca vazut
                            count += 1
                            
                            # Verificare limita globala (pe toate cautarile)
                            if limit and int(limit) > 0 and count >= int(limit):
                                break
                                
                    except Exception as e:
                        continue
                
                # Daca am atins limita, nu mai facem urmatoarele cautari
                if limit and int(limit) > 0 and count >= int(limit):
                    break

            log('[UIndex] Total items added: %d' % len(lists))
        
        elif meniu == 'torrent_links':
            action = torraction if torraction else ''
            openTorrent({'Tmode':action, 'Turl': url, 'Tsite': self.__class__.__name__, 'info': info, 'orig_url': url})
            
        return lists
    
class rarbg(Torrent):
    def __init__(self):
        self.base_url = 'http://torrentapi.org/pubapi_v2.php'
        self.appid = 'plugin.video.romanianpack'
        self.thumb = os.path.join(media, 'rarbg.png')
        self.name = 'Rarbg'
        self.search_url = '%s?mode=search&search_string=%s%s&limit=50' % (self.base_url, '%s&app_id=plugin.video.romanianpack&format=json_extended&ranked=0', '&sort=seeders')
        self.catfilme = [('Recente', '%s%s14;48;17;44;45;47;50;51;52;42;46%s%s%s'),
                    ('Toate', '%s%s14;48;17;44;45;47;50;51;52;42;46%s%s%s'),
                    ('4k/x265/HDR', '%s%s52%s%s%s'),
                    ('4k/x265', '%s%s51%s%s%s'),
                    ('1080p/x264', '%s%s44%s%s%s'),
                    ('720p/x264', '%s%s45%s%s%s'),
                    ('x264', '%s%s17%s%s%s'),
                    ('720p/xvid', '%s%s48%s%s%s'),
                    ('xvid', '%s%s14%s%s%s'),
                    ('BD Remux', '%s%s46%s%s%s')]
        self.catseriale = [('Recente', '%s%s2;18;41;49%s%s%s'),
                    ('Toate', '%s%s2;18;41;49%s%s%s'),
                    ('Episoade', '%s%s18%s%s%s'),
                    ('Episoade HD', '%s%s41%s%s%s'),
                    ('Episoade UHD', '%s%s49%s%s%s')]
        self.sortare = [('Recent adăugate', 'last'),
                ('După seederi', 'seeders'),
                ('După leecheri', 'leechers')]
        self.menu = [('Recente', 
                "%s?mode=list&category=2;14;15;16;17;21;22;42;18;19;41;29;30;31;24;26;34;43;44;45;46;47;48;49;50;51;52&app_id=%s&format=json_extended&ranked=0&sort=last&limit=100" % 
                (self.base_url, self.appid), 'recente', self.thumb),
                ('Filme', "", 'filme', self.thumb),
                ('Seriale ', "", 'seriale', self.thumb),
                ('Adulti', "%s?mode=list&category=4&app_id=%s&ranked=0&format=json_extended&limit=100" % (self.base_url, self.appid), 'sortare', self.thumb),
                ('Căutare', self.base_url, 'cauta', self.searchimage)]

    def get_token(self):
        try: 
            token = fetchData('%s?get_token=get_token&app_id=plugin.video.romanianpack' % self.base_url, rtype='json', api=1)["token"]
            return token
        except: pass

    def get_size(self, bytess):
        alternative = [
            (1024 ** 5, ' PB'),
            (1024 ** 4, ' TB'), 
            (1024 ** 3, ' GB'), 
            (1024 ** 2, ' MB'), 
            (1024 ** 1, ' KB'),
            (1024 ** 0, (' byte', ' bytes')),
            ]
        for factor, suffix in alternative:
            if bytess >= factor:
                break
        amount = int(bytess / factor)
        if isinstance(suffix, tuple):
            singular, multiple = suffix
            if amount == 1:
                suffix = singular
            else:
                suffix = multiple
        return str(amount) + suffix
    
    def parse_menu(self, url, meniu, info={}, torraction=None, limit=None):
        lists = []
        if meniu == 'get_torrent' or meniu == 'cauta' or meniu == 'recente':
            if meniu == 'cauta':
                from resources.Core import Core
                Core().searchSites({'landsearch': self.__class__.__name__})
            else:
                count = 1
                token = self.get_token()
                xbmc.sleep(2000)
                try: url = '%s&token=%s' % (url, token)# url % (self.base_url, appid, 'format=json_extended', '&limit=100', token)
                except: pass
                link = fetchData(url, rtype='json', api=1)
                if link:
                    if not "error" in link:
                        for detail in link["torrent_results"]:
                            magnet = detail["download"]
                            title = detail["title"]
                            seeds = detail["seeders"]
                            leechers = detail["leechers"]
                            size = self.get_size(detail["size"])
                            category = detail["category"]
                            if detail["episode_info"]: imdb = detail["episode_info"]["imdb"]
                            else: imdb = ''
                            seeds = ''.join(str(seeds).split()) if seeds else '-1'
                            nume = '%s (%s) [S/L: %s/%s]' % (title, size, seeds, leechers)
                            size = formatsize(size)
                            info = {'Title': nume,
                                'Plot': nume,
                                'Poster': self.thumb,
                                'Size': size,
                                'Genre': category}
                            if imdb:
                                trailerlink = 'https://www.imdb.com/title/%s/' % imdb
                                info['Trailer'] = '%s?action=GetTrailerimdb&link=%s&nume=%s&poster=%s&plot=%s' % (sys.argv[0], quote(trailerlink), quote(nume), quote(self.thumb), quote(nume))
                                info['imdb'] = imdb
                            if not (seeds == '0' and not zeroseed):
                                lists.append({'nume': nume,
                                                'legatura': magnet,
                                                'imagine': self.thumb,
                                                'switch': 'torrent_links',
                                                'info': info})
                                if limit:
                                    count += 1
                                    if count == int(limit):
                                        break
                    else: log(link)
        elif meniu == "filme" or meniu == 'seriale':
            if meniu == 'filme': itter = self.catfilme
            else: itter = self.catseriale
            for name, cat in itter:
                nume = '%s %s' % ('Filme ', name) if meniu == 'filme' else name
                legatura = cat % (self.base_url, '?mode=list&category=', '&app_id=', self.appid, '&ranked=0&format=json_extended&limit=100')
                if name == 'Recente':
                    legatura = '%s%s' % (legatura, '&sort=last')
                    next_menu = 'get_torrent'
                else: next_menu = 'sortare'
                lists.append({'nume': nume,
                                'legatura': legatura,
                                'imagine': self.thumb,
                                'switch': next_menu,
                                'info': info})
        elif meniu == 'sortare':
            for nume, sortare in self.sortare:
                legatura = '%s&sort=%s' % (url, sortare)
                lists.append({'nume': nume,
                                'legatura': legatura,
                                'imagine': self.thumb,
                                'switch': 'get_torrent',
                                'info': info})
        elif meniu == 'torrent_links':
            action = torraction if torraction else ''
            openTorrent({'Tmode':action, 'Turl': url, 'Tsite': self.__class__.__name__, 'info': info, 'orig_url': url})
        
        return lists
    
class speedapp(Torrent):
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

        self.sortare = [('După dată', ''),
                ('După mărime', 'sort=torrent.size&direction=desc'),
                ('După downloads', 'sort=torrent.timesCompleted&direction=desc'),
                ('După seederi', 'sort=torrent.seeders&direction=desc'),
                ('După leecheri', 'sort=torrent.leechers&direction=desc')]
        
        self.categorii = [('Anime/Hentai', '3'),
                ('Seriale HDTV', '43'),
                ('Seriale HDTV-Ro', '44'),
                ('Filme 3D', '61'),
                ('Filme 3d Ro', '62'),
                ('Filme BluRay', '17'),
                ('Filme BluRay-Ro', '24'),
                ('Filme DVD', '7'),
                ('Filme DVD-Ro', '2'),
                ('Filme HD', '8'),
                ('Filme HD-Ro', '29'),
                ('Filme Românești', '59'),
                ('Filme 4K(2160p)', '61'),
                ('Filme 4K-RO(2160p)', '57'),
                ('Movies Packs', '38'),
                ('Videoclipuri', '64'),
                ('Filme SD', '10'),
                ('Filme SD-Ro', '35'),
                ('Sport', '22'),
                ('Sport-Ro', '58'),
                ('Seriale TV', '45'),
                ('Seriale TV-Ro', '46'),
                ('TV Packs', '41'),
                ('TV Packs-Ro', '66'),
                ('Seriale Românești', '60'),
                ('Desene Animate', '62'),
                ('Documentare', '9'),
                ('Documentare-Ro', '63')]
        self.adult = [('XXX-Packs', '50'),
                ('XXX', '15'),
                ('XXX DVD', '47'),
                ('XXX HD', '48'),
                ('XXX-SD', '51')]
        self.menu = [('Recente', "https://%s/browse?page=1" % self.base_url, 'recente', self.thumb)]
        l = []
        for x in self.categorii:
            l.append((x[0], 'https://%s/browse?categories[0]=%s' % (self.base_url, x[1]), 'sortare', self.thumb))
        self.menu.extend(l)
        m = []
        for x in self.adult:
            m.append((x[0], 'https://%s/adult?categories[0]=%s' % (self.base_url, x[1]), 'sortare', self.thumb))
        self.menu.extend(m)
        self.menu.extend([('Toate(fără XXX)', 'https://%s/browse?categories[0]=38&categories[1]=10&categories[2]=35&categories[3]=8&categories[4]=29&categories[5]=7&categories[6]=2&categories[7]=17&categories[8]=24&categories[9]=59&categories[10]=57&categories[11]=61&categories[12]=41&categories[13]=66&categories[14]=45&categories[15]=46&categories[16]=43&categories[17]=44&categories[18]=60&categories[19]=62&categories[20]=3&categories[21]=64&categories[22]=22&categories[23]=58&categories[24]=9&categories[25]=63' % self.base_url, 'sortare', self.thumb)])
        self.menu.extend([('Căutare', self.base_url, 'cauta', self.searchimage)])

    def login(self):
        headers = {'Host': self.base_url,
                   'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; rv:70.1) Gecko/20100101 Firefox/70.1',
                   'Accept-Language': 'ro,en-US;q=0.7,en;q=0.3'}
        y, session = makeRequest('https://%s/login' % (self.base_url), name=self.__class__.__name__, headers=headers, savecookie=True)
        save_cookie(self.__class__.__name__, session)
        token_match = re.search('_csrf_token.+?value="(.+?)"', y)
        if not token_match:
            return False
        token = token_match.group(1)
        
        data = {
            'password': self.password,
            'username': self.username,
            '_remember_me': 'on',
            '_csrf_token': token
        }
        log('Log-in  attempt')
        e = []
        try: cookiesitems = session.cookies.iteritems()
        except: cookiesitems = session.cookies.items()
        for i, j in cookiesitems:
            e.append('%s=%s' % (i, j))
        headers['Cookie'] = "; ".join(e)
        headers['Origin'] = 'https://' + self.base_url
        headers['Referer'] = 'https://' + self.base_url + '/login'
        xbmc.sleep(1000)
        x, session1 = makeRequest('https://%s/login' % (self.base_url), name=self.__class__.__name__, data=data, headers=headers, savecookie=True)
        if re.search('logout', x):
            log('LOGGED SpeedApp')
        if re.search('Invalid credentials', x):
            xbmc.executebuiltin((u'Notification(%s,%s)' % ('SpeedApp Login Error', 'Parola/Username incorecte')))
            clear_cookie(self.__class__.__name__)
        save_cookie(self.__class__.__name__, session1)
        try: cookiesitems = session1.cookies.iteritems()
        except: cookiesitems = session1.cookies.items()
        for cookie, value in cookiesitems:
            return cookie + '=' + value
        return False

    def cauta(self, keyword, limit=None):
        import xbmcgui, json
        
        clean_keyword = unquote(keyword)
        
        # --- 1. PRELUARE CONTEXT (pentru a gasi ID-ul IMDb) ---
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
        except:
            pass

        # --- 2. SANITIZARE TITLU PENTRU FALLBACK ---
        sanitize_chars = {':': ' ', '–': ' ', '—': ' ', '"': '', "'": '', '&': 'and'}
        for char, replacement in sanitize_chars.items():
            clean_keyword = clean_keyword.replace(char, replacement)
        while '  ' in clean_keyword:
            clean_keyword = clean_keyword.replace('  ', ' ')
        clean_keyword = clean_keyword.strip()

        # --- 3. PARSARE SEZON/EPISOD DIN TEXT ---
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

        # --- 4. FALLBACK TMDB PENTRU IMDB ID (Daca contextul e gol) ---
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

        urls_to_scan = []
        # --- 5. LOGICA CAUTARE DUPA IMDB ID (ttXXXXXXXX) ---
        if imdb_id and str(imdb_id).startswith('tt'):
            # SpeedApp cauta direct dupa ttID in parametrul search
            url = "https://%s/browse?search=%s&submit=&sort=torrent.seeders&direction=desc&page=1" % (self.base_url, str(imdb_id))
            urls_to_scan = [url]
            log('[SpeedApp] Cautare optimizata dupa IMDb ID: %s' % imdb_id)
        else:
            # --- 6. FALLBACK LA CAUTARE TEXT ---
            log('[SpeedApp] Nu s-a gasit IMDb ID, fallback la cautare text: %s' % clean_keyword)
            url = "https://%s/browse?search=%s&submit=&sort=torrent.seeders&direction=desc&page=1" % (self.base_url, urllib.quote_plus(clean_keyword))
            urls_to_scan = [url]

        info_with_data = {'_filter_data': filter_data, '_scan_urls': urls_to_scan}
        if imdb_id: info_with_data['imdb_id'] = imdb_id
        
        return self.__class__.__name__, self.name, self.parse_menu(urls_to_scan[0], 'get_torrent', info=info_with_data, limit=None)

    def parse_menu(self, url, meniu, info={}, torraction=None, limit=None):
        lists = []
        yescat = ['38', '10', '35', '8', '29', '7', '2', '17', '24', '59', '57', '61', '41', '66', '45', '46', '43', '44', '60', '62', '3', '64', '22', '58', '9', '63', '50', '51', '15', '47', '48']
        imagine = self.thumb
        
        filter_data = info.get('_filter_data', {'mode': 'normal'}) if info else {'mode': 'normal'}
        scan_urls = info.get('_scan_urls', [url]) if info else [url]
        
        if info:
            info = info.copy()
            if '_filter_data' in info: del info['_filter_data']
            if '_scan_urls' in info: del info['_scan_urls']
        
        if meniu == 'get_torrent' or meniu == 'cauta' or meniu == 'recente':
            if meniu == 'cauta':
                from resources.Core import Core
                Core().searchSites({'landsearch': self.__class__.__name__})
            else:
                seen_magnets = set()
                count = 0
                
                for current_url in scan_urls:
                    log('[SpeedApp] Fetching: %s' % current_url)
                    response = makeRequest(current_url, name=self.__class__.__name__, headers=self.headers())
                    
                    if not self.check_login(response):
                        response = makeRequest(current_url, name=self.__class__.__name__, headers=self.headers())

                    if response:
                        blocks = response.split('<div class="row mr-0 ml-0 py-3">')
                        if len(blocks) > 1:
                            blocks = blocks[1:]
                        
                        for block_content in blocks:
                            try:
                                if 'href="/torrents/' not in block_content: continue

                                cat_match = re.search(r'href="/browse\?categories%5B0%5D=(\d+)"', block_content)
                                cat = cat_match.group(1) if cat_match else ''
                                
                                if cat not in yescat and meniu != 'cauta': continue

                                detalii_match = re.search(r'<a class="font-weight-bold" href="([^"]+)">(.+?)</a>', block_content, re.DOTALL)
                                if not detalii_match: continue
                                nume_brut = detalii_match.group(2)
                                nume = ensure_str(re.sub(r'</?mark>', '', nume_brut)).strip()
                                
                                # INCEPUT MODIFICARE SPEEDAPP: Filtrare CAM, TS, HDTS si alte gunoaie
                                junk_pattern = r'(?i)\b(trailer|sample|cam|camrip|hdts|hdtc|ts|telesync|scr|screener|preair|clip|preview|tc|hc)\b'
                                if re.search(junk_pattern, nume):
                                    continue
                                # SFARSIT MODIFICARE
                                
                                download_match = re.search(r'href="(/torrents/[^"]+\.torrent)"', block_content)
                                if not download_match: continue
                                legatura = 'https://%s%s' % (self.base_url, download_match.group(1))
                                
                                if legatura in seen_magnets: continue
                                
                                # --- FILTRARE D1/D2 ---
                                mode = filter_data.get('mode')
                                s_match = re.search(r'(?i)S(\d+)', nume)
                                e_match = re.search(r'(?i)E(\d+)', nume)
                                item_season = int(s_match.group(1)) if s_match else -1
                                item_episode = int(e_match.group(1)) if e_match else -1
                                is_pack = (item_season != -1 and item_episode == -1)
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

                                if not keep_item: continue

                                added_match = re.search(r'data-toggle="tooltip" title="([^"]+)"', block_content)
                                added = added_match.group(1).strip() if added_match else ''

                                size_match = re.search(r'(\d+[\.,]?\d*\s*[KMGT]B)', block_content)
                                size = size_match.group(1).strip() if size_match else 'N/A'

                                seeds_match = re.search(r'text-success.*?>(\d+)<', block_content)
                                seeds = seeds_match.group(1) if seeds_match else '0'
                                leech_match = re.search(r'text-danger.*?>(\d+)<', block_content)
                                leechers = leech_match.group(1) if leech_match else '0'
                                
                                if not (seeds == '0' and not zeroseed):
                                    seen_magnets.add(legatura)
                                    
                                    # INCEPUT MODIFICARE SPEEDAPP: Title trebuie sa fie curat
                                    free = '[B][COLOR lime]FREE[/COLOR][/B] ' if 'title="Descarcarea acestui torrent este gratuita' in block_content else ''
                                    double = '[B][COLOR yellow]DoubleUP[/COLOR][/B] ' if 'title="Uploadul pe acest torrent se va contoriza dublu."' in block_content else ''
                                    promovat = '[B][COLOR lime]PROMOVAT[/COLOR][/B] ' if 'Acest torrent este promovat' in block_content else ''

                                    nume_afisat = '%s%s%s%s (%s) [S/L: %s/%s]' % (promovat, free, double, nume, size, seeds, leechers)
                                    plot = '%s\n\n[COLOR yellow]Adaugat: %s[/COLOR]\n[B][COLOR FF00FA9A](%s)[/COLOR][/B] [B][COLOR FFFF69B4][S/L: %s/%s][/COLOR][/B]' % (nume_afisat, added, size, seeds, leechers)
                                    
                                    info_dict = {
                                        'Title': nume, # <--- AICI am schimbat din nume_afisat in nume
                                        'Plot': plot,
                                        'Size': formatsize(size),
                                        'Poster': imagine
                                    }
                                    # SFARSIT MODIFICARE SPEEDAPP

                                    lists.append({
                                        'nume': nume_afisat,
                                        'legatura': legatura,
                                        'imagine': imagine,
                                        'switch': 'torrent_links',
                                        'info': info_dict
                                    })
                                    count += 1
                                    # AM ELIMINAT VERIFICAREA LIMIT DE AICI PENTRU A AFISA TOT
                            except Exception:
                                continue
                                
                    # Logica paginare doar pt browsare normala
                    if len(scan_urls) == 1 and 'search=' not in scan_urls[0]:
                        if 'page=' in url:
                            new_page_match = re.search('page=(\d+)', url)
                            if new_page_match:
                                current_page = int(new_page_match.group(1))
                                next_url = url.replace('page=%d' % current_page, 'page=%d' % (current_page + 1))
                                lists.append({
                                    'nume': 'Next',
                                    'legatura': next_url,
                                    'imagine': self.nextimage,
                                    'switch': 'get_torrent',
                                    'info': {}
                                })

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
            action = torraction if torraction else ''
            openTorrent(self._get_torrent_params(turl, info, torraction))
            
        return lists

class seedfilero(Torrent):
    def __init__(self):
        self.base_url = 'seedfile.io'
        self.thumb = os.path.join(media, 'seedfilero.jpg')
        self.name = 'SeedFile'
        self.username = __settings__.getSetting("seedfilerousername")
        self.password = __settings__.getSetting("seedfileropassword")
        self.search_url = 'https://%s/torrents.php?search=%s' % (self.base_url, '%s&page=0')
        self.login_data =  {'password': self.password,
                            'username': self.username}
        self.login_url = 'https://%s/takelogin.php' % self.base_url
        self.login_referer = 'https://%s/' % self.base_url
        
        self.categorii = [('Desene SD', 'cat=2'),
                ('Filme Blu-Ray', 'cat=5'),
                ('Filme DVD', 'cat=6'),
                ('Filme DVD-RO', 'cat=7'),
                ('Filme HD', 'cat=8'),
                ('Filme HD-RO', 'cat=9'),
                ('Filme SD', 'cat=10'),
                ('Filme SD-RO', 'cat=11'),
                ('Seriale HD', 'cat=18'),
                ('Seriale HD-RO', 'cat=19'),
                ('Seriale TV', 'cat=20'),
                ('Seriale TV-RO', 'cat=21'),
                ('Sport', 'cat=22'),
                ('Videoclip', 'cat=23'),
                ('XXX 18+', 'cat=24'),
                ('Video 3D', 'cat=36'),
                ('Desene HD-RO', 'cat=39'),
                ('Desene SD-RO', 'cat=40')]
        self.menu = [('Recente', "https://%s/download-torrents?page=0" % self.base_url, 'recente', self.thumb)]
        self.menu.extend([('Dublate în Română', "https://%s/rodubbeds.php?page=0" % self.base_url, 'get_torrent', self.searchimage)])
        l = []
        for x in self.categorii:
            l.append((x[0], 'https://%s/torrents.php?search=&%s&page=0' % (self.base_url, x[1]), 'get_torrent', self.thumb))
        self.menu.extend(l)
        self.menu.extend([('Căutare', self.base_url, 'cauta', self.searchimage)])

    def parse_menu(self, url, meniu, info={}, torraction=None, limit=None):
        lists = []
        #log('link: ' + link)
        imagine = ''
        if meniu == 'get_torrent' or meniu == 'cauta' or meniu == 'recente':
            if meniu == 'cauta':
                from resources.Core import Core
                Core().searchSites({'landsearch': self.__class__.__name__})
            else:
                count = 1
                response = makeRequest(url, name=self.__class__.__name__, headers=self.headers())
                if not self.check_login(response):
                    response = makeRequest(url, name=self.__class__.__name__, headers=self.headers())
                regex = '''<tr class="browse">(.+?)</tr>\s+(?:<tr>|</table)'''
                if None != response and 0 < len(response):
                    if re.compile('Not logged in').search(response):
                        xbmc.executebuiltin((u'Notification(%s,%s)' % ('SeedFile', 'lipsa username si parola din setari')))
                    for block in re.compile(regex, re.DOTALL | re.IGNORECASE).findall(response):
                        result = re.compile('(<td.+?</td>)', re.DOTALL).findall(block)
                        if result:
                            cat = re.findall('torrents.+?(cat=\d+)"', result[0])
                            try: cat = cat[0]
                            except: cat = ''
                            verificat = ' Verificat' if re.search('title="(verified)"', result[1], re.IGNORECASE) else ''
                            imagine = re.findall("src='(.+?)'", result[1])
                            try: imagine = imagine[0]
                            except: imagine = self.thumb
                            gold = ' Aur' if re.search('title="(torent de aur)"', result[1], re.IGNORECASE) else ''
                            free = '[COLOR lime]FreeLeech[/COLOR] ' if re.search('(freeleech\.png)', result[1]) else ''
                            sticky = ' Sticky' if re.search('(sticky\.png)', result[1]) else ''
                            rosubbed = ' ROSubbed' if re.search('(rosubbed\.png)', result[1]) else ''
                            rodubbed = ' Dublat' if re.search('(rodubbed\.png)', result[1]) else ''
                            
                            try: nume = re.findall(";'>(.+?)<", result[1])[0]
                            except: nume = ''
                            genre = re.findall("genre.+?\:.+?>(.+?)<", result[1], re.IGNORECASE)
                            try: genre = genre[0]
                            except: genre = ''
                            tip = '%s' % (' '.join(striphtml(genre).replace('&nbsp;', '').replace('|', '').split()) if genre else '')
                            legatura = re.findall('href="(.+?)"', result[1])[0]
                            legatura = 'https://%s/%s' % (self.base_url, replaceHTMLCodes(legatura))
                            recomandat = ' Recomandat' if re.search('(recomand.+?recomand)', result[1], re.IGNORECASE) else ''
                            size = striphtml(result[4])
                            seeds = striphtml(result[5])
                            seeds = ''.join(str(seeds).split()) if seeds else '-1'
                            leechers = striphtml(result[6])
                            added = ' %s' % striphtml(result[3])
                            nume = free + replaceHTMLCodes(nume).replace('|', '-')
                            nume = '%s  [COLOR green]%s%s%s%s%s%s%s[/COLOR] (%s) [S/L: %s/%s] ' % (ensure_str(nume), gold, recomandat, verificat, added, sticky, rosubbed, rodubbed ,size, seeds.strip(), leechers.strip())
                            size = formatsize(size)
                            info = {'Title': nume,
                                    'Plot': '%s %s' % (tip, nume),
                                    'Genre': tip,
                                    'Size': size,
                                    'Poster': imagine}
                            if not (seeds == '0' and not zeroseed):
                                for r,t in self.categorii:
                                    if cat == t or not cat:
                                        lists.append({'nume': nume,
                                                    'legatura': legatura,
                                                    'imagine': imagine,
                                                    'switch': 'torrent_links', 
                                                    'info': info})
                                        break
                                if limit:
                                    count += 1
                                    if count == int(limit):
                                        break
                    match = re.compile('page=', re.IGNORECASE | re.DOTALL).findall(response)
                    if len(match) > 0:
                        if 'page=' in url:
                            new = re.compile('page=(\d+)').findall(url)
                            nexturl = re.sub('page=(\d+)', 'page=' + str(int(new[0]) + 1), url)
                        else:
                            nexturl = '%s%s' % (url, '&page=0')
                        lists.append({'nume': 'Next',
                                          'legatura': nexturl,
                                          'imagine': self.nextimage,
                                          'switch': 'get_torrent', 
                                          'info': {}})
        elif meniu == 'torrent_links':
            response = makeRequest(url, name=self.__class__.__name__, headers=self.headers())
            surl = 'https://%s/%s' % (self.base_url, re.compile('href="(download\.php.+?\.torrent)"', re.DOTALL).findall(response)[0])
            turl = self.getTorrentFile(surl)
            action = torraction if torraction else ''
            openTorrent(self._get_torrent_params(turl, info, torraction))
            
        return lists

class xtremlymtorrents(Torrent):
    def __init__(self):
        self.base_url = 'extremlymtorrents.ws'
        self.thumb = os.path.join(media, 'extremlymtorrents.jpg')
        self.name = 'ExtremlyMTorrents'
        self.username = __settings__.getSetting("ELTusername")
        self.password = __settings__.getSetting("ELTpassword")
        self.search_url = 'https://%s/torrents-search.php?search=%s' % (self.base_url, '%s')
        self.login_url = 'https://%s/account-login.php' % self.base_url
        self.login_data = {
                        'password': self.password,
                        'username': self.username
                        }
        
        self.categorii = [('1080p HD', '15'),
                    ('4K UHD', '40'),
                    ('720p HD', '22'),
                    ('Music Video 4k', '48'),
                    ('Anime-Japanese', '28'),
                    ('BluRay 3D', '16'),
                    ('Bluray HDR', '12'),
                    ('Bollywood', '44'),
                    ('BRRip', '35'),
                    ('CAMRip', '36'),
                    ('Documentaries', '31'),
                    ('DVD', '27'),
                    ('DVDRip', '5'),
                    ('HDTV', '13'),
                    ('Hentai-Manga', '43'),
                    ('Kids-Cartoons', '9'),
                    ('Pack', '21'),
                    ('PDTV-SDTV', '30'),
                    ('Porn-XXX', '11'),
                    ('Porn 4K-XXX', '47'),
                    ('Sport TV', '39'),
                    ('TS-Telesync-HDTS', '38'),
                    ('TV Episode-Season Complete', '10'),
                    ('TV 4K Episodes', '49'),
                    ('TVRip', '41'),
                    ('VideoClip', '24'),
                    ('WebRip-WebDL', '25'),
                    ('X Extern Only Magnet', '42')]
        self.menu = [('Recente', "https://%s/torrents.php?page=0" % self.base_url, 'recente', self.thumb)]
        l = []
        for x in self.categorii:
            l.append((x[0], 'https://%s/torrents.php?cat=%s&page=0' % (self.base_url, x[1]), 'get_torrent', self.thumb))
        self.menu.extend(l)
        self.menu.extend([('Căutare', self.base_url, 'cauta', self.searchimage)])

    def parse_menu(self, url, meniu, info={}, torraction=None, limit=None):
        lists = []
        #log('link: ' + link)
        imagine = ''
        yescat = ['15', '40', '22', '48', '28', '16', '12', '44', '35', '36', '31', '27', '5', '13', '43', '9', '21', '30', '11', '47', '39', '38', '10', '49', '41', '24', '25', '42']
        if meniu == 'get_torrent' or meniu == 'cauta' or meniu == 'recente':
            if meniu == 'cauta':
                from resources.Core import Core
                Core().searchSites({'landsearch': self.__class__.__name__})
            else:
                count = 1
                response = makeRequest(url, name=self.__class__.__name__, headers=self.headers())
                if not self.check_login(response):
                    response = makeRequest(url, name=self.__class__.__name__, headers=self.headers())
                regex = '''<tr\s+class(.+?)</tr>'''
                if None != response and 0 < len(response):
                    for block in re.findall(regex, response, re.DOTALL):
                        try:
                            catname = ''
                            tables = re.findall('(?:<td.+?>(.+?)</td>)', block)
                            if tables and len(tables) == 8:
                                cat = re.findall('/?cat=(.+?)"', tables[0])[0].strip()
                                for n, c in self.categorii:
                                    if c == cat:
                                        catname = n
                                        break
                                imagine, nume = re.findall('img\s+src=/(.+?)\s+.+?b>(.+?)</b', tables[1])[0]
                                genre =  re.findall('<br />(.+?)??<', tables[1])[0]
                                tip = ", ".join(re.split(',|\|', genre))
                                legatura = re.findall('href=(download.+?)\s+.+?\((.+?)\)', block)[0]
                                adaugat = striphtml(tables[7])
                                size = striphtml(tables[4]).strip()
                                seeds = striphtml(tables[5]).strip()
                                seeds = (''.join(str(seeds).split())).replace(',', '') if seeds else '-1'
                                leechers = striphtml(tables[6]).strip()
                                nume = replaceHTMLCodes(nume)
                                if str(cat) in yescat:
                                    #log(r[1] if str(cat)==r[1] else t[1])
                                    if re.findall('vip-icon.png', tables[1]):
                                        nume = '[COLOR yellow]VIP[/COLOR] ' + nume
                                    if re.findall('3d.png', tables[1]):
                                        nume += ' [COLOR green]3D[/COLOR]'
                                    if re.findall('engsub.png', tables[1]):
                                        nume += ' [COLOR green]ENGSub[/COLOR]'
                                    if re.findall('rosubbed.png', tables[1]):
                                        nume += ' [COLOR green]ROSub[/COLOR]'
                                    if re.findall('sticky.png', tables[1]):
                                        nume += ' [COLOR green]Sticky[/COLOR]'
                                    if re.findall('4you.png', tables[1]):
                                        nume += ' [COLOR green]Recommended[/COLOR]'
                                    nume += ' [COLOR green]%s[/COLOR]' % catname
                                    nume += ' [COLOR green]%s[/COLOR] ' % adaugat
                                    nume = '%s (%s) [S/L: %s/%s] ' % (nume, size, seeds, leechers)
                                    legatura = 'https://%s/%s' % (self.base_url, legatura[0])
                                    imagine = 'https://%s/%s' % (self.base_url, imagine)
                                    #tip = genre or ''
                                    #tip = ''
                                    size = formatsize(size)
                                    info = {'Title': nume,
                                            'Plot': '%s \n%s \n%s' % (tip, catname, nume),
                                            'Genre': tip,
                                            'Size': size,
                                            'Poster': imagine}
                                    if not (seeds == '0' and not zeroseed):
                                        lists.append({'nume': nume,
                                                        'legatura': legatura,
                                                        'imagine': imagine,
                                                        'switch': 'torrent_links', 
                                                        'info': info})
                                        if limit:
                                            count += 1
                                            if count == int(limit):
                                                break
                        except: pass
                    match = re.compile('/?page=\d+', re.DOTALL).findall(response)
                    if len(match) > 0:
                        if 'page=' in url:
                            new = re.compile('page=(\d+)').findall(url)
                            nexturl = re.sub('page=(\d+)', 'page=' + str(int(new[0]) + 1), url)
                        else:
                            nexturl = '%s%s' % (url, '&page=1')
                        lists.append({'nume': 'Next',
                                        'legatura': nexturl,
                                        'imagine': self.nextimage,
                                        'switch': 'get_torrent', 
                                        'info': {}})
        elif meniu == 'torrent_links':
            turl = self.getTorrentFile(url)
            action = torraction if torraction else ''
            openTorrent(self._get_torrent_params(turl, info, torraction))
            
        return lists

class yts(Torrent):
    def __init__(self):
        self.base_url = 'yts.bz'
        self.thumb = os.path.join(media, 'yts.png')
        self.name = '[B]YTS[/B]'
        self.search_url = "https://%s/browse-movies/%s/all/all/0/downloads/0/all" % (self.base_url, '%s')
        self.menu = [('Recente', "https://%s/browse-movies" % self.base_url, 'recente', self.thumb),
                ('Filme', "https://%s/browse-movies/0/all/all/0/" % self.base_url, 'sortare', self.thumb),
                ('Limba', "https://%s/browse-movies/0/all/all/0/latest/0/" % self.base_url, 'limba', self.thumb),
                ('Genuri', "https://%s/browse-movies/0/all/%s/0/", 'genre', self.thumb),
                ('Calitate', "https://%s/browse-movies/0/%s/all/0/", 'calitate', self.thumb),
                ('Căutare', self.base_url, 'cauta', self.searchimage)]

        self.sortare = [('Ultimele', 'latest'),
                ('Cele mai vechi', 'oldest'),
                ('Populare', 'featured'),
                ('După seederi', 'seeds'),
                ('După peers', 'peers'),
                ('După ani', 'year'),
                ('După aprecieri', 'likes'),
                ('După rating', 'rating'),
                ('Alfabetic', 'alphabetical'),
                ('După descărcări', 'downloads')]
        
        self.calitate = [('Toate', 'all'),
                ('720p', '720p'),
                ('1080p', '1080p'),
                ('4K', '2160p'),
                ('3D', '3D')]
        
        self.limba = [('English', 'en'),
                        ('Foreign', 'foreign'),
                        ('All', 'all'),
                        ('Japanese', 'ja'),
                        ('French', 'fr'),
                        ('Italian', 'it'),
                        ('German', 'de'),
                        ('Spanish', 'es'),
                        ('Chinese', 'zh'),
                        ('Hindi', 'hi'),
                        ('Cantonese', 'cn'),
                        ('Korean', 'ko'),
                        ('Russian', 'ru'),
                        ('Swedish', 'sv'),
                        ('Portuguese', 'pt'),
                        ('Polish', 'pl'),
                        ('Danish', 'da'),
                        ('Norwegian', 'no'),
                        ('Telugu', 'te'),
                        ('Thai', 'th'),
                        ('Dutch', 'nl'),
                        ('Czech', 'cs'),
                        ('Finnish', 'fi'),
                        ('Tamil', 'ta'),
                        ('Vietnamese', 'vi'),
                        ('Turkish', 'tr'),
                        ('Indonesian', 'id'),
                        ('Persian', 'fa'),
                        ('Greek', 'el'),
                        ('Arabic', 'ar'),
                        ('Hebrew', 'he'),
                        ('Hungarian', 'hu'),
                        ('Urdu', 'ur'),
                        ('Tagalog', 'tl'),
                        ('Malay', 'ms'),
                        ('Bangla', 'bn'),
                        ('Romanian', 'ro'),
                        ('Icelandic', 'is'),
                        ('Estonian', 'et'),
                        ('Catalan', 'ca'),
                        ('Malayalam', 'ml'),
                        ('Ukrainian', 'uk'),
                        ('Punjabi', 'pa'),
                        ('xx', 'xx'),
                        ('Serbian', 'sr'),
                        ('Afrikaans', 'af'),
                        ('Kannada', 'kn'),
                        ('Basque', 'eu'),
                        ('Slovak', 'sk'),
                        ('Tibetan', 'bo'),
                        ('Amharic', 'am'),
                        ('Galician', 'gl'),
                        ('Bosnian', 'bs'),
                        ('Latin', 'la'),
                        ('Mongolian', 'mn'),
                        ('Marathi', 'mr'),
                        ('Norwegian', 'nb'),
                        ('Latvian', 'lv'),
                        ('Pashto', 'ps'),
                        ('Southern', 'st'),
                        ('Inuktitut', 'iu'),
                        ('Somali', 'so'),
                        ('Wolof', 'wo'),
                        ('Azerbaijani', 'az'),
                        ('Swahili', 'sw'),
                        ('Abkhazian', 'ab'),
                        ('Haitian', 'ht'),
                        ('Serbo-Croatian', 'sh'),
                        ('Kyrgyz', 'ky'),
                        ('Akan', 'ak'),
                        ('Ossetic', 'os'),
                        ('Luxembourgish', 'lb'),
                        ('Georgian', 'ka'),
                        ('Maori', 'mi'),
                        ('Afar', 'aa'),
                        ('Irish', 'ga'),
                        ('Yiddish', 'yi'),
                        ('Khmer', 'km'),
                        ('Macedonian', 'mk')]
        
        self.genre = ['Action',
                'Adventure',
                'Animation',
                'Biography',
                'Comedy',
                'Crime',
                'Documentary',
                'Drama',
                'Family',
                'Fantasy',
                'Film-Noir',
                'Game-Show',
                'History',
                'Horror',
                'Music',
                'Musical',
                'Mystery',
                'News',
                'Reality-TV',
                'Romance',
                'Sci-Fi',
                'Sport',
                'Talk-Show',
                'Thriller',
                'War',
                'Western']

    def parse_menu(self, url, meniu, info={}, torraction=None, limit=None):
        lists = []
        #log('link: ' + link)
        imagine = ''
        if meniu == 'get_torrent' or meniu == 'cauta' or meniu == 'recente' or meniu == 'cautare':
            if meniu == 'cauta':
                from resources.Core import Core
                Core().searchSites({'landsearch': self.__class__.__name__})
            # BLOCUL "elif meniu == 'cautare':" A FOST ELIMINAT
            else:
                count = 1
                link = fetchData(url)
                if link:
                    infos = {}
                    regex = '''class="browse-movie-wrap(.+?)</div'''
                    regex_tr = '''href="(.+?)".+?src="(.+?)".+?rating">(.+?)</.+?h4>(.+?)<.+?title">(.+?)</a.+?year">(.+?)$'''
                    blocks = re.compile(regex, re.DOTALL).findall(link)
                    if blocks:
                        for block in blocks:
                            match=re.compile(regex_tr, re.DOTALL).findall(block)
                            if match:
                                for legatura, imagine, rating, genre, nume, an in match:
                                    nume = unescape(striphtml(nume)).decode('utf-8').strip()
                                    nume = '[B]%s (%s)[/B]' % (nume, an)
                                    info = {'Title': nume,
                                            'Plot': '%s (%s) - [B][COLOR FFFDBD01]%s[/COLOR][/B]  [B][COLOR FFFF69B4]Rating: %s[/COLOR][/B]' % (nume, an, genre, rating),
                                            'Poster': imagine,
                                            'Genre': genre,
                                            'Rating': rating,
                                            'Label2': genre,
                                            'Year': an}
                                    lists.append({'nume': nume,
                                                'legatura': legatura,
                                                'imagine': imagine,
                                                'switch': 'get_torrent_links', 
                                                'info': info})
                                    if limit:
                                        count += 1
                                        if count == int(limit):
                                            break
                            if limit:
                                if count == int(limit):
                                    break
                    match = re.compile('"tsc_pagination.+?\?page=', re.IGNORECASE | re.DOTALL).findall(link)
                    if len(match) > 0:
                        if '?page=' in url:
                            new = re.compile('\?page\=(\d+)').findall(url)
                            nexturl = re.sub('\?page\=(\d+)', '?page=' + str(int(new[0]) + 1), url)
                        else:
                            if '/?s=' in url:
                                nextpage = re.compile('\?s=(.+?)$').findall(url)
                                nexturl = '%s/page/2/?s=%s' % (self.base_url, nextpage[0])
                            else: 
                                nexturl = '%s%s' % (url, '?page=2')
                        lists.append({'nume': 'Next',
                                        'legatura': nexturl,
                                        'imagine': self.nextimage,
                                        'switch': 'get_torrent', 
                                        'info': {}})
        elif meniu == 'get_torrent_links':
            link = fetchData(url)
            lists = []
            # Regex-ul tÄƒu original, pe care È™tim cÄƒ funcÈ›ioneazÄƒ
            regex_baza = r'modal-torrent".+?quality.+?<span>(.+?)</span>.+?-size">(.+?)<.+?-size">(.+?)<.+?"(magnet.+?)"'
            
            try:
                info_baza = eval(str(info))
                nume_film = info_baza.get('Title')
                poster = info_baza.get('Poster', '')
            except: 
                info_baza = {}
                nume_film = ''
                poster = self.thumb
                
            # --- REGEX CORECTAT PENTRU SEEDERI/LEECHERI ---
            # CautÄƒ textul "Seeds" È™i apoi captureazÄƒ numÄƒrul de DUPÄ‚ tag
            all_seeds = re.findall(r'<span title="Seeds"[^>]*>Seeds</span>\s*([\d,]+)', link)
            all_leechers = re.findall(r'<span title="Leechers"[^>]*>Leechers</span>\s*([\d,]+)', link)
            
            matches = re.compile(regex_baza, re.DOTALL).findall(link)
            
            for i, (calitate, calitate2, size, legatura) in enumerate(matches):
                try:
                    # LuÄƒm seederii È™i leecherii din listele corecte
                    seeds = all_seeds[i].strip().replace(',', '') if i < len(all_seeds) else '0'
                    leechers = all_leechers[i].strip().replace(',', '') if i < len(all_leechers) else '0'
                    
                    size_curat = size.strip()
                    size_formatat = formatsize(size_curat)

                    # 1. Construim numele final È™i complet pentru listÄƒ
                    nume_torrent = '[B]%s %s[/B] (%s) [S/L: %s/%s] - %s' % (calitate.strip(), calitate2.strip(), size_curat, seeds, leechers, nume_film)
                    
                    # 2. CreÄƒm un dicÈ›ionar NOU cu informaÈ›iile TORRENTULUI (nu filmului)
                    info_torrent = {
                        'Title': nume_torrent,
                        'Plot': '%s\n\n[B]Quality:[/B] [B][COLOR FF00FA9A]%s %s[/COLOR][/B]\n[B]Size:[/B] [B][COLOR FFFDBD01]%s[/COLOR][/B]\n[B]Seeds/Leechers:[/B] [B][COLOR FFFF69B4]%s/%s[/COLOR][/B]' % (nume_film, calitate.strip(), calitate2.strip(), size_curat, seeds, leechers),
                        'Size': size_formatat,
                        'Poster': poster
                    }
                    
                    lists.append({'nume': nume_torrent,
                                  'legatura': legatura,
                                  'imagine': poster,
                                  'switch': 'torrent_links', 
                                  'info': info_torrent})
                except:
                    continue
        elif meniu == 'calitate':
            for nume, calitate in self.calitate:
                legatura = url % (self.base_url, calitate)
                lists.append({'nume': nume,
                                'legatura': legatura,
                                'imagine': self.thumb,
                                'switch': 'sortare', 
                                'info': info})
        elif meniu == 'genre':
            for gen in self.genre:
                legatura = url % (self.base_url, gen.lower())
                lists.append({'nume': gen,
                                'legatura': legatura,
                                'imagine': self.thumb,
                                'switch': 'sortare', 
                                'info': info})
        elif meniu == 'sortare':
            for nume, sortare in self.sortare:
                legatura = '%s%s/0/all' % (url, sortare)
                lists.append({'nume': nume,
                                'legatura': legatura,
                                'imagine': self.thumb,
                                'switch': 'get_torrent', 
                                'info': info})
        elif meniu == 'limba':
            for nume, limba in self.limba:
                legatura = '%s%s' % (url, limba)
                lists.append({'nume': nume,
                                'legatura': legatura,
                                'imagine': self.thumb,
                                'switch': 'get_torrent', 
                                'info': info})
        elif meniu == 'torrent_links':
            action = torraction if torraction else ''
            openTorrent({'Tmode':action, 'Turl': url, 'Tsite': self.__class__.__name__, 'info': info, 'orig_url': url})
            
        return lists


class magnetdl(Torrent):
    def __init__(self):
        self.base_url = 'magnetdl.com'
        self.thumb = os.path.join(media, 'magnetdl.png')
        self.name = 'MagnetDL'
        self.cats = ['Movie', 'Music', 'Other', 'TV']
        self.url_referer = 'https://www.%s' % self.base_url
        self.url_host = 'www.%s' % self.base_url
        self.menu = [('Recente', "https://www.%s/download/others/1/" % self.base_url, 'recente', self.thumb),
                ('Filme', "https://www.%s/download/movies/" % self.base_url, 'sortare', self.thumb),
                ('Seriale', "https://www.%s/download/tv/" % self.base_url, 'sortare', self.thumb),
                ('Music', "https://www.%s/download/music/" % self.base_url, 'sortare', self.thumb),
                ('Altele', "https://www.%s/download/other/" % self.base_url, 'sortare', self.thumb),
                ('Căutare', self.base_url, 'cauta', self.searchimage)]

        self.sortare = [('Implicit', '1/'),
                ('Ultimele', 'age/desc/1/'),
                ('După mărime', 'size/desc/1/'),
                ('După seederi', 'se/desc/1/'),
                ('După leecheri', 'le/desc/1/')]

    def cauta(self, keyword, limit=None):
        import random
        url = "https://www.%s/search/?q=%s&m=1&x=%s&y=%s" % (self.base_url, quote(keyword), str(random.randint(1, 79)), str(random.randint(1, 30)))
        return self.__class__.__name__, self.name, self.parse_menu(url, 'get_torrent', limit=limit)

    def parse_menu(self, url, meniu, info={}, torraction=None, limit=None):
        lists = []
        #log('link: ' + link)
        imagine = self.thumb
        if meniu == 'get_torrent' or meniu == 'cauta' or meniu == 'recente':
            if meniu == 'cauta':
                from resources.Core import Core
                Core().searchSites({'landsearch': self.__class__.__name__})
            else:
                count = 1
                link = fetchData(url, headers=self.headers())
                if link:
                    regex = '''<tr><td class="m">(.+?)</tr>'''
                    regex_tr = '''href="(magnet.+?)".+?title=".+?" rel="nofollow">.+?<a href=".+?" title="(.+?)">.+?</td><td>(.+?)</td><td class=".+?">(.+?)</td><td>.+?</td><td>(.+?)</td><td class="s">(\d+)</td><td class="l">(\d+)</td>'''
                    blocks = re.compile(regex).findall(link)
                    if blocks:
                        for block in blocks:
                            match=re.compile(regex_tr).findall(block)
                            if match:
                                for legatura, nume, added, tip, size, seeds, leeches in match:
                                    if not (seeds == '0' and not zeroseed) and tip in self.cats:
                                        nume = '%s (%s) [S/L: %s/%s] ' % (nume, size, seeds, leeches)
                                        nume = '%s [COLOR green]%s %s[/COLOR]' % (nume, tip, added)
                                        size = formatsize(size)
                                        info = {'Title': nume,
                                                'Plot': nume,
                                                'Size': size,
                                                'Poster': imagine}
                                        lists.append({'nume': nume,
                                                        'legatura': legatura,
                                                        'imagine': imagine,
                                                        'switch': 'torrent_links', 
                                                        'info': info})
                                        if limit:
                                            count += 1
                                            if count == int(limit):
                                                break
                            if limit:
                                if count == int(limit):
                                    break
                    match = re.compile('Next Page &gt;').findall(link)
                    if len(match) > 0:
                        new = re.compile('/(\d+)/').findall(url)
                        if new:
                            nexturl = re.sub('/(\d+)/', '/%s/' % str(int(new[0]) + 1), url)
                        else:
                            nexturl = '%s/2/' % (url)
                        lists.append({'nume': 'Next',
                                    'legatura': nexturl,
                                    'imagine': self.nextimage,
                                    'switch': 'get_torrent', 
                                    'info': {}})
        elif meniu == 'sortare':
            for nume, sortare in self.sortare:
                legatura = '%s%s' % (url, sortare)
                lists.append({'nume': nume,
                                'legatura': legatura,
                                'imagine': self.thumb,
                                'switch': 'get_torrent', 
                                'info': info})
        elif meniu == 'torrent_links':
            action = torraction if torraction else ''
            openTorrent({'Tmode':action, 'Turl': url, 'Tsite': self.__class__.__name__, 'info': info, 'orig_url': url})
            
        return lists
    
class torrentgalaxy(Torrent):
    def __init__(self):
        self.base_url = 'torrentgalaxy.to'
        self.thumb = os.path.join(media, 'torrentgalaxy.jpg')
        self.name = 'TorrentGalaxy'
        self.search_url = "https://%s/torrents.php?search=%s&lang=0&nox=1&sort=seeders&order=desc&page=0" % (self.base_url, '%s')
        self.cats = {'28': 'Anime',
                '9': 'Documentaries',
                '3': 'Movies 4K UHD',
                '46': 'Movies Bollywood',
                '45': 'Movies CAM/TS',
                '42': 'Movies HD',
                '4': 'Movies Packs',
                '1': 'Movies SD',
                '25': 'Music Video',
                '41': 'TV HD',
                '5': 'TV SD',
                '6': 'TV Packs',
                '7': 'TV Sports',
                '35': 'XXX HD',
                '34': 'XXX SD'}
        
        self.sortare = [('Ultimele', '&sort=id&order=desc'),
                ('După seederi', '&sort=seeders&order=desc'),
                ('După nume', '&sort=name&order=desc'),
                ('După mărime', '&sort=size&order=desc')]
        
        self.menu = [('Recente', "https://%s/torrents.php?parent_cat=&nox=1&sort=id&order=desc&page=0" % self.base_url, 'recente', self.thumb),
                ('Movies', "https://%s/torrents.php?parent_cat=Movies" % self.base_url, 'sortare', self.thumb),
                ('TV', "https://%s/torrents.php?parent_cat=TV" % self.base_url, 'sortare', self.thumb),
                ('Documentaries', "https://%s/torrents.php?parent_cat=Documentaries" % self.base_url, 'sortare', self.thumb),
                ('Anime', "https://%s/torrents.php?parent_cat=Anime" % self.base_url, 'sortare', self.thumb),
                ('XXX', "https://%s/torrents.php?parent_cat=XXX" % self.base_url, 'sortare', self.thumb)]
        l = []
        for x in self.cats:
            l.append((self.cats.get(x), 'https://%s/torrents.php?cat=%s' % (self.base_url, x), 'sortare', self.thumb))
        self.menu.extend(l)
        self.menu.extend([('Căutare', self.base_url, 'cauta', self.searchimage)])

    def parse_menu(self, url, meniu, info={}, torraction=None, limit=None):
        lists = []
        #log('link: ' + link)
        imagine = self.thumb
        if meniu == 'get_torrent' or meniu == 'cauta' or meniu == 'recente':
            if meniu == 'cauta':
                from resources.Core import Core
                Core().searchSites({'landsearch': self.__class__.__name__})
            else:
                count = 1
                link = fetchData(url, headers=self.headers())
                if link:
                    regex = r'''(?:\\'hovercoverimg\\'\s+src=\\'(.*?)\\'|'tgxtablecell shrink rounded txlight').*?\?cat=(\d+)".*?title="(.*?)".*?href="(magnet.*?)"(?:.*?<span.*?>(.*?)</span){2}(?:.*?<span.+?>(\[.*?.])</span)'''
                    blocks = re.findall(regex, link, re.DOTALL)
                    if blocks:
                        for image, cat, nume, legatura, size, peers in blocks:
                            legatura = unquote(legatura)
                            if image: imagine = image
                            else: imagine = self.thumb
                            seeds, leeches = striphtml(peers).replace('[', '').replace(']', '').split('/')
                            if not (seeds == '0' and not zeroseed):
                                if self.cats.get(str(cat)):
                                    nume = '%s (%s) [S/L: %s/%s] ' % (nume, size, seeds, leeches)
                                    nume = '%s [COLOR green]%s[/COLOR]' % (nume, self.cats.get(str(cat)))
                                    size = formatsize(size)
                                    info = {'Title': nume,
                                            'Plot': nume,
                                            'Size': size,
                                            'Poster': imagine}
                                    lists.append({'nume': nume,
                                                'legatura': legatura,
                                                'imagine': imagine,
                                                'switch': 'torrent_links', 
                                                'info': info})
                                    if limit:
                                        count += 1
                                        if count == int(limit):
                                            break
                    match = re.compile("'pagination").findall(link)
                    if len(match) > 0:
                        if 'page=' in url:
                            new = re.compile('page=(\d+)').findall(url)
                            nexturl = re.sub('page=(\d+)', 'page=' + str(int(new[0]) + 1), url)
                        else:
                            nexturl = '%s%s' % (url, '&page=1')
                        lists.append({'nume': 'Next',
                                    'legatura': nexturl,
                                    'imagine': self.nextimage,
                                    'switch': 'get_torrent', 
                                    'info': {}})
        elif meniu == 'sortare':
            for nume, sortare in self.sortare:
                legatura = '%s%s&page=0' % (url, sortare)
                lists.append({'nume': nume,
                                'legatura': legatura,
                                'imagine': self.thumb,
                                'switch': 'get_torrent', 
                                'info': info})
                
        elif meniu == 'torrent_links':
            action = torraction if torraction else ''
            openTorrent({'Tmode':action, 'Turl': url, 'Tsite': self.__class__.__name__, 'info': info, 'orig_url': url})
            
        return lists

class yourbittorrent(Torrent):
    def __init__(self):
        self.base_url = 'yourbittorrent.com'
        self.thumb = os.path.join(media, 'yourbittorrent.jpg')
        self.name = 'YourBittorrent'
        self.search_url = "https://%s/?q=%s&page=1" % (self.base_url, '%s')
        self.cats = {'/adult.html': 'Adult',
                '/movies.html': 'Movies',
                '/television.html': 'TV',
                '/anime.html': 'Anime'}
        
        self.sortare = [('Ultimele', '&sort=id&order=desc'),
                ('După seederi', '&sort=seeders&order=desc'),
                ('După nume', '&sort=name&order=desc'),
                ('După mărime', '&sort=size&order=desc')]
        
        self.menu = [('Recente', "https://%s/new/1.html" % self.base_url, 'recente', self.thumb)]
        l = []
        for x in self.cats:
            l.append((self.cats.get(x), 'https://%s%s/1.html' % (self.base_url, x.replace('.html', '')), 'get_torrent', self.thumb))
        self.menu.extend(l)
        self.menu.extend([('Căutare', self.base_url, 'cauta', self.searchimage)])

    def parse_menu(self, url, meniu, info={}, torraction=None, limit=None):
        lists = []
        imagine = self.thumb
        if meniu == 'get_torrent' or meniu == 'cauta' or meniu == 'recente':
            if meniu == 'cauta':
                from resources.Core import Core
                Core().searchSites({'landsearch': self.__class__.__name__})
            else:
                count = 1
                link = fetchData(url, headers=self.headers())
                if link:
                    regex = '''<tr\s+class(.+?)</tr>'''
                    regex_tr = '''<td.+?(?:.+?href=[\'"](.+?)[\'"].+?(?:title="(.+?)".+?)?|.+?)?>(.+?)</td>'''
                    blocks = re.findall(regex, link, re.DOTALL)
                    for block in blocks:
                            match=re.findall(regex_tr, block, re.DOTALL)
                            if match:
                                try:
                                    cat, nume, size, added, seeds, leeches, nimic = match
                                    cat = cat[0]
                                    if cat in self.cats:
                                        legatura = 'https://%s%s' % (self.base_url, nume[0])
                                        nume = striphtml(nume[1]).replace('&nbsp;', '').strip()
                                        size = size[2]
                                        added = added[2]
                                        seeds = seeds[2]
                                        leeches = leeches[2]
                                        nume = '%s (%s) [S/L: %s/%s] ' % (nume, size, seeds, leeches)
                                        nume = '%s [COLOR green]%s Added %s[/COLOR]' % (nume, self.cats.get(cat), added)
                                        size = formatsize(size)
                                        info = {'Title': nume,
                                                'Plot': nume,
                                                'Size': size,
                                                'Poster': imagine}
                                        lists.append({'nume': nume,
                                                        'legatura': legatura,
                                                        'imagine': imagine,
                                                        'switch': 'torrent_links', 
                                                        'info': info})
                                        if limit:
                                            count += 1
                                            if count == int(limit):
                                                break
                                except: pass
                    match = re.compile('"page-link"').findall(link)
                    if len(match) > 0:
                        if 'page=' in url:
                            new = re.compile('page=(\d+)').findall(url)
                            nexturl = re.sub('page=(\d+)', 'page=' + str(int(new[0]) + 1), url)
                        if url.endswith('.html'):
                            new = re.compile('/(\d+)\.html').findall(url)
                            nexturl = re.sub('/(\d+)\.html', '/' + str(int(new[0]) + 1) + '.html', url)
                        lists.append({'nume': 'Next',
                                    'legatura': nexturl,
                                    'imagine': self.nextimage,
                                    'switch': 'get_torrent', 
                                    'info': {}})
        elif meniu == 'sortare':
            for nume, sortare in self.sortare:
                legatura = '%s%s&page=0' % (url, sortare)
                lists.append({'nume': nume,
                            'legatura': legatura,
                            'imagine': self.thumb,
                            'switch': 'get_torrent', 
                            'info': info})
                
        elif meniu == 'torrent_links':
            link = fetchData(url)
            try:
                surl = 'https://%s%s' % (self.base_url, re.search('''(/down/.*?.torrent)''', link).group(1))
                turl = self.getTorrentFile(surl)
                action = torraction if torraction else ''
                openTorrent(self._get_torrent_params(turl, info, torraction))
            except: pass
            
        return lists
    
class rutor(Torrent):
    def __init__(self):
        self.base_url = 'rutor.info'
        self.thumb = os.path.join(media, 'rutor.jpg')
        self.name = 'RuTor'
        self.search_url = "http://%s/search/0/0/000/0/%s" % (self.base_url, '%s')
        self.cats = {'/browse/0/1': 'Foreign Films',
                '/browse/0/12': 'Popular Science Films',
                '/browse/0/5': 'Russian Films',
                '/browse/0/4': 'Foriegn Serials',
                '/browse/0/16': 'Russian Serials',
                '/browse/0/17': 'Foriegn Releases',
                '/browse/0/15': 'Humor',
                '/browse/0/13': 'Sport and Health',
                '/browse/0/6': 'Tv',
                '/browse/0/7': 'Animation',
                '/browse/0/10': 'Anime'}
        
        self.sortare = [('După dată descendent', '/0/0'),
                ('După dată ascendent', '/0/1'),
                ('După seederi', '/0/2'),
                ('După leecheri', '/0/2'),
                ('După nume descendent', '/0/6'),
                ('După nume ascendent', '/0/7'),
                ('După mărime descendent', '/0/8'),
                ('După mărime ascendent', '/0/9')]
        self.menu = [('Recente', "http://%s/" % self.base_url, 'recente', self.thumb)]
        l = []
        for x in self.cats:
            l.append((self.cats.get(x), 'http://%s%s' % (self.base_url, x), 'sortare', self.thumb))
        self.menu.extend(l)
        self.menu.extend([('Căutare', self.base_url, 'cauta', self.searchimage)])
        self.wanted = ["webrip", "web-dl", 'bdrip', 'hdtv', 'bdremux', 'dvdrip', 'dvd', 'hdrip', 'satrip', 'tvrip', 'iptv', 'dvb']

    def parse_menu(self, url, meniu, info={}, torraction=None, limit=None):
        lists = []
        imagine = self.thumb
        if meniu == 'get_torrent' or meniu == 'cauta' or meniu == 'recente':
            if meniu == 'cauta':
                from resources.Core import Core
                Core().searchSites({'landsearch': self.__class__.__name__})
            else:
                count = 1
                link = fetchData(url, headers=self.headers())
                if link:
                    regex = '''<tr\s+class="(?:gai|tum)?">(.+?)</tr>'''
                    regex_tr = '''<td.*?>(.+?)</td>'''
                    blocks = re.findall(regex, link, re.DOTALL)
                    for block in blocks:
                            match=re.findall(regex_tr, block, re.DOTALL)
                            if match:
                                try:
                                    nume = re.findall('<a.*?>(.+?)</a>', match[1])[-1]
                                    if any(x in nume.lower() for x in self.wanted):
                                        added = match[0].replace('&nbsp;', '')
                                        size = match[-2].replace('&nbsp;', '')
                                        sedleech = re.findall('<span.*?>(.+?)</span>', match[-1])
                                        seeds = striphtml(sedleech[0]).replace('&nbsp;', '')
                                        leeches = striphtml(sedleech[1]).replace('&nbsp;', '')
                                        legatura = re.findall('href="(magnet.+?)"', match[1])[0]
                                        if not(seeds == '0' and not zeroseed):
                                            nume = '%s (%s) [S/L: %s/%s] ' % (nume, size, seeds, leeches)
                                            nume = '%s [COLOR green]Added %s[/COLOR]' % (nume, added)
                                            size = formatsize(size)
                                            info = {'Title': nume,
                                                    'Plot': nume,
                                                    'Size': size,
                                                    'Poster': imagine}
                                            lists.append({'nume': nume,
                                                        'legatura': legatura,
                                                        'imagine': imagine,
                                                        'switch': 'torrent_links', 
                                                        'info': info})
                                            if limit:
                                                count += 1
                                                if count == int(limit):
                                                    break
                                except: pass
                    new = re.compile('/(?:search|browse)?/(\d+)/').findall(url)
                    try:
                        nexturl = re.sub(r'(/(?:search|browse)?/)\d+/', r'\g<1>%s/' % str(int(new[0]) + 1), url)
                        lists.append({'nume': 'Next',
                                    'legatura': nexturl,
                                    'imagine': self.nextimage,
                                    'switch': 'get_torrent', 
                                    'info': {}})
                    except: pass
        elif meniu == 'sortare':
            for nume, sortare in self.sortare:
                legatura = '%s%s' % (url, sortare)
                lists.append({'nume': nume,
                                'legatura': legatura,
                                'imagine': self.thumb,
                                'switch': 'get_torrent', 
                                'info': info})
                
        elif meniu == 'torrent_links':
            action = torraction if torraction else ''
            openTorrent({'Tmode':action, 'Turl': url, 'Tsite': self.__class__.__name__, 'info': info, 'orig_url': url})
            
        return lists

class glotorrents(Torrent):
    def __init__(self):
        self.base_url = 'glodls.to'
        self.thumb = os.path.join(media, 'glotorrents.jpg')
        self.name = 'GloTorrents'
        self.search_url = self.search_url = "https://%s/search_results.php?search=%s&page=0" % (self.base_url, '%s')
        self.cats = {'1': 'Movies',
                     '41': 'TV',
                     '72': 'TV/Movie Packs',
                     '71': 'Video',
                     '28': 'Anime',
                     '76': 'Sports',
                     '50': 'Adult XXX',
                     '73': 'Desi Porn'}
        self.sortare = [('Ultimele', '&sort=id&order=desc'),
                ('După nume', '&sort=name&order=desc'),
                ('După mărime', '&sort=size&order=desc'),
                ('După seederi', '&sort=seeders&order=desc'),
                ('După leecheri', '&sort=leechers&order=desc')]
        self.menu = [('Recente', "https://%s/today.php" % self.base_url, 'recente', self.thumb)]
        for x in self.cats:
            self.menu.append((self.cats.get(x), 'https://%s/search.php?cat=%s' % (self.base_url, x), 'sortare', self.thumb))
        self.menu.extend([('Căutare', self.base_url, 'cauta', self.searchimage)])

    def parse_menu(self, url, meniu, info={}, torraction=None, limit=None):
        lists = []
        imagine = self.thumb
        if meniu == 'get_torrent' or meniu == 'cauta' or meniu == 'recente':
            if meniu == 'cauta':
                from resources.Core import Core
                Core().searchSites({'landsearch': self.__class__.__name__})
            else:
                count = 1
                link = fetchData(url, headers=self.headers())
                if link:
                    regex = '''(<td\s+class=['"]ttable_col1['"].*?)<tr\s+class=\'t-row\''''
                    regex_tr = '''<td.*?>(.+?)</td>'''
                    blocks = re.findall(regex, link, re.DOTALL)
                    if blocks:
                        for block in blocks:
                            match=re.findall(regex_tr, block, re.DOTALL)
                            if match:
                                if len(match) == 9:
                                    tip, nume, torrent, legatura, size, seeds, leeches, user, health = match
                                    seeds = re.search('<b>(.+?)</b>', seeds).group(1) if seeds else '0'
                                    leeches = re.search('<b>(.+?)</b>', leeches).group(1) if leeches else '0'
                                    tip = str(re.search('cat=(\d+)">', tip).group(1)) if tip else ''
                                    try: nume = re.search('<a.*?><b>(.+?)</b>', nume).group(1)
                                    except: nume = re.search('<a\stitle="(.*?)"', nume).group(1)
                                    legatura = re.search('href="(magnet.+?)"', legatura).group(1)
                                    if not re.search('btih\:([a-zA-Z0-9]+)\&', legatura):
                                        legatura = re.search('href="(.+?)"', torrent).group(1)
                                        if legatura.startswith('/'):
                                            legatura = 'https://%s%s' % (self.base_url, legatura)
                                    if not(seeds == '0' and not zeroseed) and self.cats.get(tip):
                                        nume = '%s (%s) [S/L: %s/%s] ' % (nume, size, seeds, leeches)
                                        nume = '%s [COLOR green]%s[/COLOR]' % (nume, self.cats.get(tip))
                                        size = formatsize(size)
                                        info = {'Title': nume,
                                                'Plot': nume,
                                                'Size': size,
                                                'Poster': imagine}
                                        lists.append({'nume': nume,
                                                        'legatura': legatura,
                                                        'imagine': imagine,
                                                        'switch': 'torrent_links', 
                                                        'info': info})
                                        if limit:
                                            count += 1
                                            if count == int(limit):
                                                break
                    match = re.compile('"pagination"').findall(link)
                    if len(match) > 0:
                        if 'page=' in url:
                            new = re.compile('page=(\d+)').findall(url)
                            nexturl = re.sub('page=(\d+)', 'page=' + str(int(new[0]) + 1), url)
                        else:
                            nexturl = '%s%s' % (url, '&page=1')
                        lists.append({'nume': 'Next',
                                    'legatura': nexturl,
                                    'imagine': self.nextimage,
                                    'switch': 'get_torrent', 
                                    'info': {}})
        elif meniu == 'sortare':
            for nume, sortare in self.sortare:
                legatura = '%s%s&page=0' % (url, sortare)
                lists.append({'nume': nume,
                                    'legatura': legatura,
                                    'imagine': self.thumb,
                                    'switch': 'get_torrent', 
                                    'info': info})
        elif meniu == 'torrent_links':
            action = torraction if torraction else ''
            if re.search('magnet\:', url):
                turl = url
            else:
                turl = self.getTorrentFile(url)
            openTorrent(self._get_torrent_params(turl, info, torraction))
        return lists



# =====================================================================
# INCEPUT ADĂUGARE METEOR: Clasa pentru providerul Meteor (Stremio JSON)
# =====================================================================
class meteor(Torrent):
    def __init__(self):
        self.base_url = 'meteorfortheweebs.midnightignite.me'
        self.thumb = search_icon
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
            alternative = [
                (1024 ** 5, ' PB'),
                (1024 ** 4, ' TB'),
                (1024 ** 3, ' GB'),
                (1024 ** 2, ' MB'),
                (1024 ** 1, ' KB'),
                (1024 ** 0, ' B'),
            ]
            for factor, suffix in alternative:
                if bytess >= factor:
                    break
            amount = round(bytess / factor, 2)
            return str(amount) + suffix
        except:
            return "0 B"

    def _extract_from_desc(self, desc, emoji_py3, emoji_py2):
        """Extrage textul de pe linia care începe cu un emoji specific."""
        try:
            if py3:
                match = re.search(re.escape(emoji_py3) + r'\s*(.+?)(?:\n|$)', desc)
            else:
                match = re.search(re.escape(emoji_py2) + r'\s*(.+?)(?:\n|$)', desc)
            if match:
                return match.group(1).strip()
        except:
            pass
        return ''

    def _clean_emojis(self, text):
        """Elimină toate emoji-urile și branding-ul Meteor."""
        if not text:
            return text
        # INCEPUT MODIFICARE METEOR
        text = re.sub(r'(?i)Meteor\s+-\s+', '', text) # Sterge prefixul Meteor
        # SFARSIT MODIFICARE
        if py3:
            emojis = ['📄', '⭐', '🔊', '💾', '👤', '👥', '☁️', '🎥', '🎬', '🔗',
                      '🔨', '📺', '🎞', '🏷', '📦', '✅', '❌', '⚡', '🌐', '📡']
            for e in emojis:
                text = text.replace(e, '')
        else:
            emojis = [
                '\xf0\x9f\x93\x84',  # 📄
                '\xe2\xad\x90',      # ⭐
                '\xf0\x9f\x94\x8a',  # 🔊
                '\xf0\x9f\x92\xbe',  # 💾
                '\xf0\x9f\x91\xa4',  # 👤
                '\xf0\x9f\x91\xa5',  # 👥
                '\xe2\x98\x81\xef\xb8\x8f',  # ☁️
                '\xe2\x98\x81',      # ☁
                '\xf0\x9f\x8e\xa5',  # 🎥
                '\xf0\x9f\x8e\xac',  # 🎬
                '\xf0\x9f\x94\x97',  # 🔗
                '\xf0\x9f\x94\xa8',  # 🔨
            ]
            for e in emojis:
                text = text.replace(e, '')
        return text.strip()

    def cauta(self, keyword, replace=False, limit=None):
        import xbmcgui, json

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
        except:
            pass

        clean_keyword = unquote(keyword).strip()

        if not imdb_id or not str(imdb_id).startswith('tt'):
            match_s_e = re.search(r'(.*?)\s+S(\d+)(?:E(\d+))?', clean_keyword, re.IGNORECASE)
            if match_s_e:
                title = match_s_e.group(1).strip()
                season = int(match_s_e.group(2))
                episode_str = match_s_e.group(3)
                if episode_str:
                    episode = int(episode_str)
                    media_type = 'episode'
                else:
                    episode = None
                    media_type = 'tv'

                _, api_imdb = get_show_ids_from_tmdb(title)
                if api_imdb:
                    imdb_id = api_imdb
            else:
                year = None
                match_year = re.search(r'\b(19|20\d{2})\s*$', clean_keyword)
                if match_year:
                    clean_keyword_no_year = clean_keyword[:match_year.start()].strip()
                    year = match_year.group(1)
                else:
                    clean_keyword_no_year = clean_keyword

                _, api_imdb = get_movie_ids_from_tmdb(clean_keyword_no_year, year)
                if api_imdb:
                    imdb_id = api_imdb

        if not imdb_id or not str(imdb_id).startswith('tt'):
            log('[Meteor] Failed to resolve IMDB ID for keyword: %s' % clean_keyword)
            return self.__class__.__name__, self.name, []

        if media_type in ['episode', 'tv', 'tvshow']:
            s_val = season if season is not None else 1
            e_val = episode if episode is not None else 1
            stremio_id = "%s:%s:%s" % (imdb_id, s_val, e_val)
            stremio_type = "series"
        else:
            stremio_id = imdb_id
            stremio_type = "movie"

        url = "https://%s/%s/stream/%s/%s.json" % (self.base_url, self.config, stremio_type, stremio_id)
        
        info_with_data = {'imdb_id': imdb_id}

        return self.__class__.__name__, self.name, self.parse_menu(url, 'get_torrent', info=info_with_data, limit=limit)

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
            response = makeRequest(clean_url, name=self.__class__.__name__, headers=self.headers())
            
            if response:
                import json
                try:
                    data = json.loads(response)
                    streams = data.get('streams', [])
                    
                    # Buckets pentru sortare pe categorii
                    b4k = []
                    b1080 = []
                    b720 = []

                    for stream in streams:
                        try:
                            behaviorHints = stream.get('behaviorHints', {})
                            title_orig = behaviorHints.get('filename') or stream.get('title') or stream.get('name', '')
                            if not title_orig: continue

                            # 1. DETECTIE REZOLUTIE
                            binge = str(behaviorHints.get('bingeGroup', '')).upper()
                            desc = stream.get('description', '')
                            meta_name = stream.get('name', '').upper()
                            full_check = (title_orig + " " + binge + " " + desc + " " + meta_name).upper()

                            res_priority = 0
                            res_label = ""
                            if any(x in full_check for x in ['2160P', '4K', 'UHD']):
                                res_priority = 4
                                res_label = "4K"
                            elif '1080P' in full_check:
                                res_priority = 3
                                res_label = "1080p"
                            elif '720P' in full_check:
                                res_priority = 2
                                res_label = "720p"

                            if res_priority < 2: continue

                            # 2. ELIMINARE JUNK
                            junk = r'(?i)\b(trailer|sample|cam|camrip|hdts|hdtc|ts|telesync|scr|screener|preair|clip|preview)\b'
                            if re.search(junk, title_orig) or re.search(junk, desc): continue

                            # 3. EXTRAGERE PEERS
                            peers_int = 0
                            if py3: p_m = re.search(r'👥\s*(\d+)', desc)
                            else: p_m = re.search(r'\xf0\x9f\x91\xa5\s*(\d+)', desc)
                            if p_m: peers_int = int(p_m.group(1))
                            else:
                                p_fb = re.search(r'(\d+)\s*(?:peers?|seeders?)', desc, re.IGNORECASE)
                                if p_fb: peers_int = int(p_fb.group(1))
                            
                            # 4. CURATARE TITLU
                            title = title_orig
                            if ' / ' in title: title = title.split(' / ')[-1]
                            title = self._clean_emojis(title)
                            title = re.sub(r'^[ \t\-\.\:📄]+', '', title).strip()

                            # 5. MARIME
                            size = "N/A"
                            size_bytes = behaviorHints.get('videoSize')
                            if size_bytes: size = self.get_size(size_bytes)
                            else:
                                sz_m = re.search(r'([\d\.]+\s*[KMGT]B)', desc, re.IGNORECASE)
                                if sz_m: size = sz_m.group(1)

                            magnet = "magnet:?xt=urn:btih:%s" % stream.get('infoHash')
                            for s_url in stream.get('sources', []):
                                if s_url.startswith('tracker:'): magnet += "&tr=" + quote(s_url.replace('tracker:', ''))

                            # 6. PANOU INFO & INSIGNE
                            quality = self._extract_from_desc(desc, '⭐', '\xe2\xad\x90')
                            audio = self._extract_from_desc(desc, '🔊', '\xf0\x9f\x94\x8a')
                            sources_info = self._extract_from_desc(desc, '🔗', '\xf0\x9f\x94\x97')
                            
                            plot_lines = ['[B][COLOR white]%s[/COLOR][/B]' % title, '', '[B]Rezoluție: [COLOR yellow]%s[/COLOR][/B]' % res_label]
                            v_tech = []
                            if re.search(r'\bDV\b|DOVI|DOLBY.?VISION', title, re.IGNORECASE): v_tech.append('Dolby Vision')
                            if re.search(r'\bHDR(?:10\+?)?\b', title, re.IGNORECASE): v_tech.append('HDR')
                            if v_tech: plot_lines.append('[B]Video: [COLOR magenta]%s[/COLOR][/B]' % ' / '.join(v_tech))
                            if quality: plot_lines.append('[B]Calitate: [COLOR blue]%s[/COLOR][/B]' % quality)
                            if audio: plot_lines.append('[B]Audio: [COLOR orange]%s[/COLOR][/B]' % audio)
                            plot_lines.append('[B]Mărime: [COLOR FF00FA9A]%s[/COLOR][/B]' % size)
                            plot_lines.append('[B]Peers: [COLOR FFFF69B4]%s[/COLOR][/B]' % peers_int)
                            if sources_info: plot_lines.append('[B]Surse: [COLOR gray]%s[/COLOR][/B]' % sources_info)
                            plot_lines.append(''), plot_lines.append('[B]Provider: [COLOR FFFDBD01]Meteor[/COLOR][/B]')

                            badges = []
                            if res_priority == 4: badges.append('[B][COLOR yellow]4K[/COLOR][/B]')
                            elif res_priority == 3: badges.append('[B][COLOR yellow]1080p[/COLOR][/B]')
                            elif res_priority == 2: badges.append('[B][COLOR yellow]720p[/COLOR][/B]')
                            if re.search(r'REMUX', title, re.IGNORECASE): badges.append('[B][COLOR red]REMUX[/COLOR][/B]')
                            elif re.search(r'WEB-?DL|WEB-?RIP', title, re.IGNORECASE): badges.append('[B][COLOR blue]WEB-DL[/COLOR][/B]')
                            elif re.search(r'BLU-?RAY|BDRIP', title, re.IGNORECASE): badges.append('[B][COLOR cyan]BLURAY[/COLOR][/B]')
                            
                            badges_str = " ".join(badges) + " " if badges else ""
                            nume_afisat = '%s%s  [B][COLOR FFFDBD01]Meteor[/COLOR][/B] [B][COLOR FF00FA9A](%s)[/COLOR][/B] [B][COLOR FFFF69B4][P: %s][/COLOR][/B]' % (badges_str, title, size, peers_int)

                            info_dict = {'Title': title, 'Plot': '\n'.join(plot_lines), 'Size': size, 'Poster': self.thumb}
                            if info.get('imdb_id'): info_dict['imdb_id'] = info['imdb_id']
                            if info.get('tmdb_id'): info_dict['tmdb_id'] = info['tmdb_id']

                            item_data = {'peers': peers_int, 'item': {'nume': nume_afisat, 'legatura': magnet, 'imagine': self.thumb, 'switch': 'torrent_links', 'info': info_dict}}
                            
                            # Repartizare pe rezolutii
                            if res_priority == 4: b4k.append(item_data)
                            elif res_priority == 3: b1080.append(item_data)
                            elif res_priority == 2: b720.append(item_data)
                        except: continue

                    # Sortam fiecare bucket dupa peers
                    b4k.sort(key=lambda x: x['peers'], reverse=True)
                    b1080.sort(key=lambda x: x['peers'], reverse=True)
                    b720.sort(key=lambda x: x['peers'], reverse=True)

                    # --- LOGICA DE ÎNTREȚESERE (25 4K + 25 1080p) ---
                    final_sorted = []
                    max_slices = max(len(b4k), len(b1080))
                    
                    # Combinam calupuri de cate 25 din fiecare
                    for i in range(0, max_slices, 25):
                        final_sorted.extend(b4k[i:i+25])
                        final_sorted.extend(b1080[i:i+25])
                    
                    # Adaugam restul (720p) la final
                    final_sorted.extend(b720)

                    # PAGINARE LA 50 ITEME
                    items_per_page = 50
                    start_idx = (page - 1) * items_per_page
                    end_idx = start_idx + items_per_page
                    
                    paged_results = final_sorted[start_idx:end_idx]
                    for res in paged_results: lists.append(res['item'])

                    if len(final_sorted) > end_idx:
                        next_url = clean_url + ('&' if '?' in clean_url else '?') + 'page=' + str(page + 1)
                        lists.append({
                            'nume': '[B][COLOR lime]Pagina Următoare (Meteor - %d rezultate rămase) >>[/COLOR][/B]' % (len(final_sorted) - end_idx),
                            'legatura': next_url, 'imagine': self.nextimage, 'switch': 'get_torrent', 'info': info
                        })
                except Exception as e: log('[Meteor] Error: %s' % str(e))

        elif meniu == 'torrent_links':
            action = torraction if torraction else ''
            openTorrent(self._get_torrent_params(url, info, torraction))
        return lists


# =====================================================================
# INCEPUT ADĂUGARE COMET: Clasa pentru providerul Comet (Stremio JSON)
# =====================================================================
class comet(Torrent):
    def __init__(self):
        self.base_url = 'comet.feels.legal'
        self.thumb = search_icon
        self.name = '[B]Comet[/B]'
        self.config = 'eyJtYXhSZXN1bHRzUGVyUmVzb2x1dGlvbiI6MCwibWF4U2l6ZSI6MCwiY2FjaGVkT25seSI6ZmFsc2UsInNvcnRDYWNoZWRVbmNhY2hlZFRvZ2V0aGVyIjpmYWxzZSwicmVtb3ZlVHJhc2giOnRydWUsInJlc3VsdEZvcm1hdCI6WyJhbGwiXSwiZGVicmlkU2VydmljZXMiOltdLCJlbmFibGVUb3JyZW50Ijp0cnVlLCJkZWR1cGxpY2F0ZVN0cmVhbXMiOmZhbHNlLCJzY3JhcGVEZWJyaWRBY2NvdW50VG9ycmVudHMiOmZhbHNlLCJkZWJyaWRTdHJlYW1Qcm94eVBhc3N3b3JkIjoiIiwibGFuZ3VhZ2VzIjp7InJlcXVpcmVkIjpbXSwiYWxsb3dlZCI6W10sImV4Y2x1ZGUiOltdLCJwcmVmZXJyZWQiOltdfSwicmVzb2x1dGlvbnMiOnsicjU3NnAiOmZhbHNlLCJyNDgwcCI6ZmFsc2UsInIzNjBwIjpmYWxzZSwicjI0MHAiOmZhbHNlLCJ1bmtub3duIjpmYWxzZX0sIm9wdGlvbnMiOnsicmVtb3ZlX3JhbmtzX3VuZGVyIjotMTAwMDAwMDAwMDAsImFsbG93X2VuZ2xpc2hfaW5fbGFuZ3VhZ2VzIjpmYWxzZSwicmVtb3ZlX3Vua25vd25fbGFuZ3VhZ2VzIjpmYWxzZX19'
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
            data = json.loads(win.getProperty('mrsp.playback.info'))
            imdb_id = data.get('imdb_id') or data.get('imdbnumber')
            m_type, season, episode = data.get('mediatype', 'movie'), data.get('season'), data.get('episode')
        except: pass

        clean_kw = unquote(keyword).strip()
        if not imdb_id or not str(imdb_id).startswith('tt'):
            m_s_e = re.search(r'(.*?)\s+S(\d+)(?:E(\d+))?', clean_kw, re.IGNORECASE)
            if m_s_e:
                title = m_s_e.group(1).strip()
                season, ep_s = int(m_s_e.group(2)), m_s_e.group(3)
                episode, m_type = (int(ep_s), 'episode') if ep_s else (None, 'tv')
                _, api_id = get_show_ids_from_tmdb(title)
                imdb_id = api_id
            else:
                y_m = re.search(r'\b(19|20\d{2})\s*$', clean_kw)
                title, year = (clean_kw[:y_m.start()].strip(), y_m.group(1)) if y_m else (clean_kw, None)
                _, api_id = get_movie_ids_from_tmdb(title, year)
                imdb_id = api_id

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
            response = makeRequest(clean_url, name=self.__class__.__name__, headers=self.headers())
            
            if response:
                import json
                try:
                    data = json.loads(response)
                    streams = data.get('streams', [])
                    b4k, b1080, b720 = [], [], []

                    for stream in streams:
                        try:
                            bh = stream.get('behaviorHints', {})
                            title_orig = bh.get('filename') or stream.get('title') or stream.get('name', '')
                            if not title_orig: continue
                            desc = stream.get('description', '')
                            full_check = (title_orig + " " + desc + " " + stream.get('name', '')).upper()

                            # 1. Rezolutie
                            res_p, res_l = 0, ""
                            if any(x in full_check for x in ['2160P', '4K', 'UHD']): res_p, res_l = 4, "4K"
                            elif '1080P' in full_check: res_p, res_l = 3, "1080p"
                            elif '720P' in full_check: res_p, res_l = 2, "720p"
                            if res_p < 2: continue

                            # 2. Junk
                            if re.search(r'(?i)\b(trailer|sample|cam|camrip|hdts|hdtc|ts|telesync|scr|screener|preair|clip)\b', title_orig): continue

                            # 3. EXTRAGERE DATE (Robustă)
                            seeds_match = re.search(r'👤\s*(\d+)', desc) or re.search(r'(\d+)\s*Seeders?', desc, re.IGNORECASE)
                            seeds = seeds_match.group(1) if seeds_match else '0'
                            peers_int = int(seeds)

                            quality_match = re.search(r'⭐\s*([^|\n]+)', desc)
                            quality = quality_match.group(1).strip() if quality_match else ''
                            
                            audio_match = re.search(r'🔊\s*([^|\n]+)', desc)
                            audio_ext = audio_match.group(1).strip() if audio_match else ''
                            
                            source_match = re.search(r'🔎\s*([^|\n]+)', desc)
                            sources_info = source_match.group(1).strip() if source_match else ''

                            # 4. Curatare Titlu
                            title = title_orig
                            if ' / ' in title: title = title.split(' / ')[-1]
                            title = self._clean_text(title)
                            title = re.sub(r'^[ \t\-\.\:📄]+', '', title).strip()

                            # 5. Marime
                            size = "N/A"
                            if bh.get('videoSize'):
                                size = self.get_size(bh.get('videoSize'))
                            else:
                                size_match = re.search(r'💾\s*([\d\.]+\s*[KMGT]B)', desc) or re.search(r'([\d\.]+\s*[KMGT]B)', desc)
                                if size_match: size = size_match.group(1)

                            magnet = "magnet:?xt=urn:btih:%s" % stream.get('infoHash')
                            for s_url in stream.get('sources', []):
                                if s_url.startswith('tracker:'): magnet += "&tr=" + quote(s_url.replace('tracker:', ''))

                            # 6. Plot Stanga
                            plot = ['[B][COLOR white]%s[/COLOR][/B]' % title, '', '[B]Rezoluție: [COLOR yellow]%s[/COLOR][/B]' % res_l]
                            v_tech = []
                            if re.search(r'\bDV\b|DOVI|DOLBY.?VISION', title, re.IGNORECASE): v_tech.append('Dolby Vision')
                            if re.search(r'\bHDR(?:10\+?)?\b', title, re.IGNORECASE): v_tech.append('HDR')
                            if v_tech: plot.append('[B]Video: [COLOR magenta]%s[/COLOR][/B]' % ' / '.join(v_tech))
                            if quality: plot.append('[B]Calitate: [COLOR blue]%s[/COLOR][/B]' % quality)
                            if audio_ext: plot.append('[B]Audio: [COLOR orange]%s[/COLOR][/B]' % audio_ext)
                            plot.append('[B]Mărime: [COLOR FF00FA9A]%s[/COLOR][/B]' % size)
                            plot.append('[B]Peers: [COLOR FFFF69B4]%s[/COLOR][/B]' % seeds)
                            if sources_info: plot.append('[B]Surse: [COLOR gray]%s[/COLOR][/B]' % sources_info)
                            plot.extend(['', '[B]Provider: [COLOR FFFDBD01]Comet[/COLOR][/B]'])

                            # 7. Badges Lista
                            badges = []
                            if res_p == 4: badges.append('[B][COLOR yellow]4K[/COLOR][/B]')
                            elif res_p == 3: badges.append('[B][COLOR yellow]1080p[/COLOR][/B]')
                            elif res_p == 2: badges.append('[B][COLOR yellow]720p[/COLOR][/B]')
                            if re.search(r'REMUX', title, re.IGNORECASE): badges.append('[B][COLOR red]REMUX[/COLOR][/B]')
                            elif re.search(r'WEB-?DL|WEB-?RIP', title, re.IGNORECASE): badges.append('[B][COLOR blue]WEB-DL[/COLOR][/B]')
                            if re.search(r'ATMOS|DDP?\s?[57][\. ]1', title + desc, re.IGNORECASE): badges.append('[B][COLOR orange]ATMOS[/COLOR][/B]')
                            
                            n_afisat = '%s%s  [B][COLOR FFFDBD01]Comet[/COLOR][/B] [B][COLOR FF00FA9A](%s)[/COLOR][/B] [B][COLOR FFFF69B4][P: %s][/COLOR][/B]' % (" ".join(badges)+" ", title, size, seeds)
                            info_d = {'Title': title, 'Plot': '\n'.join(plot), 'Size': size, 'Poster': self.thumb}
                            if info.get('imdb_id'): info_d['imdb_id'] = info['imdb_id']
                            if info.get('tmdb_id'): info_d['tmdb_id'] = info['tmdb_id']

                            item_f = {'peers': peers_int, 'item': {'nume': n_afisat, 'legatura': magnet, 'imagine': self.thumb, 'switch': 'torrent_links', 'info': info_d}}
                            if res_p == 4: b4k.append(item_f)
                            elif res_p == 3: b1080.append(item_f)
                            elif res_p == 2: b720.append(item_f)
                        except Exception as e:
                            log('[Comet] Skip item error: %s' % str(e))
                            continue

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
                        lists.append({'nume': '[B][COLOR lime]Pagina Următoare (Comet - %d rămase) >>[/COLOR][/B]' % (len(f_sorted)-end), 'legatura': clean_url+('&' if '?' in clean_url else '?')+'page='+str(page+1), 'imagine': self.nextimage, 'switch': 'get_torrent', 'info': info})
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
        self.thumb = search_icon
        self.name = '[B]Heartive[/B]'
        # API-urile pe care le foloseste Heartive
        self.apis = [
            {"name": "Torrentio", "url": "https://torrentio.strem.fun/providers=yts,eztv,rarbg,1337x,thepiratebay,kickasstorrents,torrentgalaxy,magnetdl,horriblesubs,nyaasi,tokyotosho,anidex"},
            {"name": "MediaFusion", "url": "https://mediafusion.elfhosted.com/D-614MVFDUZtgFV56UcW5tuxxRq35euHVq3KtL7X4zbcA"},
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
        if not imdb_id:
            m_s_e = re.search(r'(.*?)\s+S(\d+)(?:E(\d+))?', clean_kw, re.IGNORECASE)
            if m_s_e:
                title = m_s_e.group(1).strip()
                season, ep_s = int(m_s_e.group(2)), m_s_e.group(3)
                episode, m_type = (int(ep_s), 'episode') if ep_s else (None, 'tv')
                _, api_id = get_show_ids_from_tmdb(title)
                imdb_id = api_id
            else:
                y_m = re.search(r'\b(19|20\d{2})\s*$', clean_kw)
                title, year = (clean_kw[:y_m.start()].strip(), y_m.group(1)) if y_m else (clean_kw, None)
                _, api_id = get_movie_ids_from_tmdb(title, year)
                imdb_id = api_id

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
                    resp = makeRequest(full_url, name=self.__class__.__name__, headers=self.headers())
                    if not resp: continue
                    
                    data = json.loads(resp)
                    for stream in data.get('streams', []):
                        try:
                            info_hash = stream.get('infoHash')
                            if not info_hash or info_hash in seen_hashes: continue
                            
                            bh = stream.get('behaviorHints', {})
                            title_orig = bh.get('filename') or stream.get('title') or stream.get('description', '')
                            desc = stream.get('description', '') or stream.get('title', '')
                            
                            # 1. FILTRARE JUNK (CAM, TS, HDTS, etc.)
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
                            
                            size = "N/A"
                            if bh.get('videoSize'): size = self.get_size(bh.get('videoSize'))
                            else:
                                sz_m = re.search(r'([\d\.]+\s*[KMGT]B)', desc, re.IGNORECASE)
                                if sz_m: size = sz_m.group(1)

                            # 4. CURATARE TITLU
                            title = title_orig
                            if ' / ' in title: title = title.split(' / ')[-1]
                            title = self._clean_text(title)
                            title = re.sub(r'^[ \t\-\.\:📄]+', '', title).strip()

                            # 5. BADGES
                            badges = []
                            if res_p == 4: badges.append('[B][COLOR yellow]4K[/COLOR][/B]')
                            elif res_p == 3: badges.append('[B][COLOR yellow]1080p[/COLOR][/B]')
                            elif res_p == 2: badges.append('[B][COLOR yellow]720p[/COLOR][/B]')
                            if re.search(r'REMUX', title, re.IGNORECASE): badges.append('[B][COLOR red]REMUX[/COLOR][/B]')
                            elif re.search(r'WEB-?DL|WEB-?RIP', title, re.IGNORECASE): badges.append('[B][COLOR blue]WEB-DL[/COLOR][/B]')
                            if re.search(r'ATMOS|DDP?\s?[57][\. ]1', title + desc, re.IGNORECASE): badges.append('[B][COLOR orange]ATMOS[/COLOR][/B]')
                            
                            n_afisat = '%s%s  [B][COLOR FFFDBD01]%s[/COLOR][/B] [B][COLOR FF00FA9A](%s)[/COLOR][/B] [B][COLOR FFFF69B4][S: %s][/COLOR][/B]' % (" ".join(badges)+" ", title, target['name'], size, seeds)

                            # PLOT COLORAT
                            plot = ['[B][COLOR white]%s[/COLOR][/B]' % title, '', '[B]Rezoluție: [COLOR yellow]%s[/COLOR][/B]' % res_l]
                            plot.append('[B]Mărime: [COLOR FF00FA9A]%s[/COLOR][/B]' % size)
                            plot.append('[B]Seederi: [COLOR FFFF69B4]%s[/COLOR][/B]' % seeds)
                            plot.append('[B]Sursă: [COLOR cyan]%s[/COLOR][/B]' % target['name'])
                            plot.extend(['', '[B]Provider: [COLOR FFFDBD01]Heartive[/COLOR][/B]'])

                            magnet = "magnet:?xt=urn:btih:%s" % info_hash
                            magnet += "&tr=udp://tracker.opentrackr.org:1337/announce&tr=udp://9.rarbg.to:2710/announce"

                            info_d = {'Title': title, 'Plot': '\n'.join(plot), 'Size': size, 'Poster': self.thumb, 'imdb_id': imdb_id}

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
                lists.append({'nume': '[B][COLOR lime]Pagina Următoare (Heartive) >>[/COLOR][/B]', 'legatura': str(p_info), 'switch': 'get_torrent', 'info': {}})

        elif meniu == 'torrent_links':
            action = torraction if torraction else ''
            openTorrent(self._get_torrent_params(p_info_raw, info, action))
            
        return lists




