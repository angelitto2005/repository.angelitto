# -*- coding: utf-8 -*-
from resources.functions import *

streamsites = ['asiafaninfo',
           'clicksudorg',
           'dozaanimata',
           'filmehdnet',
           'filmeonline2016biz',
           'fsonlineorg',
           'fsonlineto',
           'hindilover',
           'portalultautv',
           'serialenoihd',
           'topfilmeonline',
           'voxfilmeonline']

streamnames = {'asiafaninfo': {'nume' : 'AsiaFanInfo', 'thumb': os.path.join(media,'asiafaninfo.jpg')},
             'clicksudorg': {'nume': 'ClickSud', 'thumb': os.path.join(media, 'clicksud.jpg')},
             'dozaanimata': {'nume': 'DozaAnimata', 'thumb': os.path.join(media,'dozaanimata.jpg')},
             'filmehdnet': {'nume': 'FilmeHD', 'thumb': os.path.join(media, 'filmehdnet.jpg')},
             'filmeonline2016biz': {'nume': 'FilmeOnline2016', 'thumb': os.path.join(media, 'filmeonline2016biz.jpg')},
             'fsonlineorg': {'nume': 'FSOnline', 'thumb': os.path.join(media, 'fsonlineorg.jpg')},
             'fsonlineto': {'nume': 'FSOnline2', 'thumb': os.path.join(media, 'fsonlineorg.jpg')},
             'hindilover': {'nume': 'HindiLover', 'thumb': os.path.join(media, 'hindilover.jpg')},
             'portalultautv': {'nume': 'PortalulTauTv', 'thumb': os.path.join(media, 'portalultautv.jpg')},
             'serialenoihd': {'nume': 'SerialeNoiHD', 'thumb': os.path.join(media, 'serialenoihd.jpg')},
             'topfilmeonline': {'nume': 'TopFilmeOnline', 'thumb': os.path.join(media, 'topfilmeonline.jpg')},
             'voxfilmeonline': {'nume': 'VoxFilmeOnline', 'thumb': os.path.join(media, 'voxfilmeonline.jpg')}}


class asiafaninfo:
    base_url = 'http://www.asiafaninfo.net'
    thumb = os.path.join(media,'asiafaninfo.jpg')
    nextimage = next_icon
    searchimage = search_icon
    name = 'AsiaFanInfo.net'
    menu = [('Recente', base_url, 'recente', thumb), 
            ('Categorii', base_url, 'genuri', thumb),
            ('Căutare', base_url, 'cauta', searchimage)]
                

    def cauta(self, keyword, limit=None):
        return self.__class__.__name__, self.name, self.parse_menu(self.get_search_url(keyword), 'by_genre', limit=limit)
        
    def get_search_url(self, keyword):
        url = self.base_url + '/?s=' + quote(keyword)
        return url

    def parse_menu(self, url, meniu, info={}, limit=None):
        lists = []
        if meniu == 'recente':
            count =1
            link = fetchData(url)
            regex = '''<li>(?:<strong>)?<a href=['"](.+?)['"].+?>(.+?)</li'''
            match = re.findall(regex, link, re.IGNORECASE | re.DOTALL)
            if len(match) > 0:
                for legatura, nume in match:
                    nume = replaceHTMLCodes(striphtml(nume))
                    info = {'Title': nume,'Plot': nume,'Poster': self.thumb}
                    lists.append({'nume': nume,
                                    'legatura': legatura,
                                    'imagine': '',
                                    'switch': 'get_links', 
                                    'info': info})
                    if limit:
                        count += 1
                        if count == int(limit):
                            break
        elif meniu == 'get_links':
            link = fetchData(url)
            nume = ''
            regex_lnk = '''(?:((?:episodul|partea|sursa)[\s]\d+).+?)?<iframe.+?src=['"]((?:[htt]|[//]).+?)["']'''
            regex_seriale = '''(?:<h3>.+?strong>(.+?)<.+?href=['"](.+?)['"].+?)'''
            regex_infos = '''detay-a.+?description">(.+?)</div'''
            match_lnk = []
            #match_srl = re.compile(regex_seriale, re.IGNORECASE | re.DOTALL).findall(link)
            match_nfo = re.compile(regex_infos, re.IGNORECASE | re.DOTALL).findall(link)
            try:
                info = eval(str(info))
                info['Plot'] = (striphtml(match_nfo[0]).strip())
            except: pass
            content = ''
            for episod, content in re.findall('"collapseomatic ".+?(?:.+?>(episodul.+?)</)?(.+?)</li>', link, re.DOTALL | re.IGNORECASE):
                if episod:
                    lists.append({'nume': '[COLOR lime]%s[/COLOR]' % episod,
                                    'legatura': 'nolink',
                                    'imagine': '',
                                    'switch': 'nimic', 
                                    'info': {}})
                match_lnk = []
                if content:
                    for numes, host1 in re.findall('''(?:>(sursa.+?)</.+?)?(?:src|href)?=['"]((?:[htt]|[//]).+?)["']''', content, re.DOTALL | re.IGNORECASE):
                        match_lnk.append((numes, host1))
                    for host, link1 in get_links(match_lnk):
                        lists.append({'nume': host,
                                    'legatura': link1,
                                    'imagine': '',
                                    'switch': 'play', 
                                    'info': info,
                                    'landing': url})
            if not content:
                match2_lnk = re.findall(regex_lnk, link, re.IGNORECASE | re.DOTALL)
                for host, link1 in get_links(match2_lnk):
                    lists.append({'nume': host,
                                    'legatura': link1,
                                    'imagine': '',
                                    'switch': 'play', 
                                    'info': info,
                                    'landing': url})
        elif meniu == 'by_genre' or meniu == 'cauta':
            if meniu == 'cauta':
                from resources.Core import Core
                Core().searchSites({'landsearch': self.__class__.__name__})
            else: 
                count = 1
                link = fetchData(url)
                regex_all = '''id="post-(.+?)</div>\s+</div>\s+</div>'''
                r_link = '''href=['"](.+?)['"].+?title.+?categ'''
                r_name = '''title.+?per.+?>(.+?)<.+?categ'''
                r_genre = '''category tag">(.+?)<'''
                r_autor = '''author">(.+?)<'''
                r_image = '''author".+?src="(.+?)"'''
                if link:
                    match = re.findall(regex_all, link, re.IGNORECASE | re.DOTALL)
                    for movie in match:
                        legatura = re.findall(r_link, movie, re.IGNORECASE | re.DOTALL)
                        if legatura:
                            legatura = legatura[0]
                            nume = re.findall(r_name, movie, re.IGNORECASE | re.DOTALL)[0]
                            try: gen = [', '.join(re.findall(r_genre, movie, re.IGNORECASE | re.DOTALL))]
                            except: gen = ''
                            try: autor = re.findall(r_autor, movie, re.IGNORECASE | re.DOTALL)[0]
                            except: autor = ''
                            try: imagine = re.findall(r_image, movie, re.IGNORECASE | re.DOTALL)[0]
                            except: imagine = self.thumb
                            nume = replaceHTMLCodes(striphtml(nume))
                            info = {'Title': nume,'Plot': '%s \nTraducator: %s' % (nume, autor),'Poster': imagine, 'Genre': gen}
                            lists.append({'nume': nume,
                                    'legatura': legatura,
                                    'imagine': imagine,
                                    'switch': 'get_links', 
                                    'info': info})
                            if limit:
                                count += 1
                                if count == int(limit):
                                    break
                    match = re.compile('"post-nav', re.IGNORECASE).findall(link)
                    if len(match) > 0:
                        if '/page/' in url:
                            new = re.compile('/page/(\d+)').findall(url)
                            nexturl = re.sub('/page/(\d+)', '/page/' + str(int(new[0]) + 1), url)
                        else:
                            if '/?s=' in url:
                                nextpage = re.compile('\?s=(.+?)$').findall(url)
                                nexturl = '%s/page/2/?s=%s' % (self.base_url, nextpage[0])
                            else: 
                                nexturl = '%s%s' % (url, 'page/2/' if str(url).endswith('/') else '/page/2/')
                        lists.append({'nume': 'Next',
                                    'legatura': nexturl,
                                    'imagine': self.nextimage,
                                    'switch': meniu, 
                                    'info': {}})
        elif meniu == 'genuri':
            link = fetchData(url)
            regex_cat = '''class="cat-item.+?href=['"](.+?)['"][\s]?>(.+?)<'''
            if link:
                match = re.findall(regex_cat, link, re.IGNORECASE | re.DOTALL)
                if len(match) > 0:
                    for legatura, nume in match:
                        nume = replaceHTMLCodes(nume).capitalize()
                        lists.append({'nume': nume,
                                    'legatura': legatura.replace('"', ''),
                                    'imagine': '',
                                    'switch': 'by_genre', 
                                    'info': info})
        return lists

class clicksudorg:
    base_url = 'https://clicksud.biz'
    thumb = os.path.join(media, 'clicksud.jpg')
    nextimage = next_icon
    searchimage = search_icon
    name = 'ClickSud'
    menu = [('Recente', base_url, 'recente', thumb),
            ('Filme românești', '%s/filme-romanesti-online-hd' % base_url, 'recente', thumb),
            ('Filme turcești', '%s/filme-online-subtitrate-hd-in-romana/filme-turcesti-online/' % base_url, 'recente', thumb),
            ('Filme online', '%s/filme-online-subtitrate-hd-in-romana/' % base_url, 'recente', thumb),
            ('Seriale românești', '%s/2012/06/seriale-romanesti-online/' % base_url, 'liste', thumb),
            ('Emisiuni online', '%s/2012/11/emisiuni-tv-online/' % base_url, 'liste', thumb),
            ('Seriale online', '%s/2020/08/seriale-online/' % base_url, 'liste', thumb),
            ('Seriale turcesti', '%s/2021/03/seriale-turcesti-online/' % base_url, 'liste', thumb),
            ('Las Fierbinti', base_url + '/las-fierbinti-2012-2023-online/', 'liste', thumb),
            ('Căutare', base_url, 'cauta', searchimage)]
    headers = {'Host': 'clicksud.biz',
                'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; rv:70.1) Gecko/20100101 Firefox/70.1',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Referer': base_url}
        
    def get_search_url(self, keyword):
        url = self.base_url + '/page/1/?s=' + quote(keyword)
        return url

    def getKey(self, item):
        return item[1]

    def cauta(self, keyword, limit=None):
        return self.__class__.__name__, self.name, self.parse_menu(self.get_search_url(keyword), 'recente', limit=limit)

    def parse_menu(self, url, meniu, info={}, limit=None):
        lists = []
        imagine = ''
        if meniu == 'recente' or meniu == 'cauta':
            if meniu == 'cauta':
                from resources.Core import Core
                Core().searchSites({'landsearch': self.__class__.__name__})
            else: 
                count = 1
                link = fetchData(url.replace('+', '%2B'))
                regex_menu = '''"td-module-thumb(.*?)</div>\s+</div>\s+</div>'''
                regex_submenu = '''href=['"](.*?)['"].*?title=['"](.*?)['"].*?(?:image\:|data-bg\=).*?[\("]([htp].*?)[\)"]'''
                regex_search = '''class="page-nav'''
                if link:
                    for meniul in re.compile(regex_menu, re.DOTALL).findall(link):
                        match = re.findall(regex_submenu, meniul, re.DOTALL)
                        for legatura, nume, imagine in match:
                            nume = replaceHTMLCodes(ensure_str(nume))
                            info = {'Title': nume,'Plot': nume,'Poster': imagine}
                            szep = re.findall('(?:sezo[a-zA-Z\s]+(\d+).+?)?epi[a-zA-Z\s]+(\d+)', nume, re.IGNORECASE | re.DOTALL)
                            if szep:
                                try:
                                    if re.search('–|-|~', nume):
                                        all_name = re.split(r'–|-|:|~', nume,1)
                                        title = all_name[0]
                                        title2 = all_name[1]
                                    else: 
                                        title = nume
                                        title2 = ''
                                    title, year = xbmc.getCleanMovieTitle(title)
                                    title2, year2 = xbmc.getCleanMovieTitle(title2)
                                    title = title if title else title2
                                    year = year if year else year2
                                    if year: info['Year'] = year
                                    if szep[0][1] and not szep[0][0]: info['Season'] = '01'
                                    else: info['Season'] = str(szep[0][0])
                                    info['Episode'] = str(szep[0][1])
                                    info['TvShowTitle'] = (re.sub('(?:sezo[a-zA-Z\s]+\d+.+?)?epi[a-zA-Z\s]+\d+.+?$', '', title, flags=re.IGNORECASE | re.DOTALL)).strip()
                                except: pass
                            switch = 'get_links'
                            lists.append({'nume': nume,
                                    'legatura': legatura,
                                    'imagine': imagine,
                                    'switch': switch, 
                                    'info': info})
                            if limit:
                                count += 1
                                if count == int(limit):
                                    break
                        if limit:
                            if count == int(limit):
                                break
                    match = re.compile(regex_search, re.DOTALL).findall(link)
                    if match:
                        if '/page/' in url:
                            new = re.search('/page/(\d+)', url)
                            nexturl = re.sub('/page/(\d+)', '/page/' + str(int(new.group(1)) + 1)+'/', url)
                        else: nexturl = '%s%s%s' % (url , '' if url.endswith('/') else '/', "page/2/")
                        lists.append({'nume': 'Next',
                                    'legatura': nexturl,
                                    'imagine': self.nextimage,
                                    'switch': meniu, 
                                    'info': {}})
        elif meniu == 'get_links':
            sources = []
            link = fetchData(url)
            regex_lnk = '''(?:(?:>(?:\s+)?((?:Server|Partea).*?)(?:\s+)?|item title="(.*?)".*?))?(?:text/javascript">\s+str=["'](.*?)["']|<iframe.*?src="((?:[htt]|[//]).*?)")'''
            match_lnk = re.findall(regex_lnk, link, re.IGNORECASE | re.DOTALL)
            for nume1, nume2, match1, match in match_lnk:
                if nume1:
                    nume1 = " ".join(nume1.split())
                if match:
                    if match.find('+f.id+') == -1 and not match.endswith('.js'): 
                        sources.append((nume1, match))
                        #log(match)
                else:
                    if match1 and not match:
                        match1 = unquote(match1.replace('@','%'))
                        match1 = re.findall('<iframe.*?src="((?:[htt]|[//]).*?)"', match1, re.IGNORECASE | re.DOTALL)[0]
                        nume = nume1 + nume2
                        sources.append((nume, match1))
            if info: 
                if not 'Poster' in info: info['Poster'] = self.thumb
            for host, link1 in get_links(sources):
                lists.append({'nume': host,
                                    'legatura': link1,
                                    'imagine': '',
                                    'switch': 'play', 
                                    'info': info,
                                    'landing': url})
        elif meniu == 'seriale_rom' or meniu == 'emisiuni_online' or meniu == 'seriale_online':
            link = fetchData(url)
            if meniu == 'seriale_rom': 
                regex_seriale_rom = '''Seriale rom.*?<ul(.*?)</ul'''
            elif meniu == 'emisiuni_online':
                regex_seriale_rom = '''Emisiuni on.*?<ul(.*?)>Seriale'''
            elif meniu == 'seriale_online':
                regex_seriale_rom = '''Seriale online.*?<ul(.*?)</ul'''
            regex_serial_rom = '''href="(.*?)">(.*?)<'''
            seriale = re.search(regex_seriale_rom, link, re.DOTALL)
            if seriale:
                for legatura,nume in re.findall(regex_serial_rom, seriale.group(1), re.DOTALL):
                    if not legatura == '#' :
                        info = {'Title': nume, 'Plot': nume, 'TvShowTitle': nume, 'Poster': self.thumb}
                        switch = 'recente' if '/tag/' in legatura else 'liste'
                        lists.append({'nume': nume,
                                    'legatura': legatura,
                                    'imagine': self.thumb,
                                    'switch': switch, 
                                    'info': info})
            
        elif meniu == 'liste':
            try:
                info = eval(str(info))
                default_image = info.get('Poster') or ''
            except:
                default_image = ''
            info = {}
            link = fetchData(url.replace('+', '%2B'))
            #log(link)
            regex_menu = '''(?s)(?:<table (.+?)</table|"td_block_inner tdb-block-inner td-fix-index"(.*?)(?:"td_ajax_infinite"|</div>\s+</div>\s+</div>\s+</div>\s+</div>))'''
            regex_submenu = '''(?s)(?:td-module-thumb".*?href="(.*?)".*?title="(.*?)"(?:.*?(?:url|data-bg=)[\("]+(.*?)[\)"]+)?|<td.*?>(?:<strong>)?(.*?)<.*?href="(.*?)">(?:<b>)?(.*?)<(?:.*?src="(h.*?)")?)'''
            regex2_submenu = '''(?s)data-label="(.*?)"><a.*?href="(.*?)"(?:.*?src="(.*?)")?'''
            regex3_submenu = '''<li>.*?href="(.*?)">(.*?)<'''
            regex_menu1 = '''<article(.*?)</article'''
            regex_submenu1 = '''href=['"](.*?)['"](?:.*?title=['"](.*?)['"])?(?:.*?content=['"]([htp].*?)['"])?'''
            regex_search1 = '''<span class='pager-older-link.*?href=['"](.*?)['"].*?</span'''
            regex_search = '''class="page-nav'''
            match1 = False
            match2 = False
            match3 = False
            for meniul in re.findall(regex_menu, link, re.DOTALL):
                if meniul:
                    meniul = meniul[0] or meniul[1]
                    match = re.compile(regex3_submenu).findall(meniul)
                    if match:
                        match3 = True
                    else:
                        match =  re.compile(regex2_submenu).findall(meniul)
                        if match:
                            match2 = True
                        else:
                            match = re.compile(regex_submenu).findall(meniul)
                            match1 = True
                    if match:
                        for details in match:
                            if match1: 
                                legatura, nume, imagine, nume3, legatura2, nume2, imagine2 = details
                                if not imagine:
                                    imagine = imagine2 if imagine2 else self.thumb
                                if not legatura:
                                    legatura = legatura2
                                if not nume:
                                    nume = nume2
                                if not nume:
                                    nume = nume3
                            if match2:
                                nume, legatura, imagine = details
                                imagine = imagine if imagine else self.thumb
                            if match3:
                                legatura, nume = details
                                imagine  = default_image or self.thumb
                            try:
                                leg2 = re.findall('(ht.+?)"', legatura, re.IGNORECASE | re.DOTALL)
                                if leg2: legatura = leg2[0]
                            except:pass
                            nume = replaceHTMLCodes(nume)
                            szep = re.findall('([\s\w].+?)(?:sezo[a-zA-Z\s]+(\d+).+?)?epi[a-zA-Z\s]+(\d+)', nume, re.IGNORECASE | re.DOTALL)
                            if szep:
                                name, sezon, episod = szep[0]
                                sz = str(sezon) if sezon else '1'
                                eps = str(episod) if episod else '1'
                                info = {'Title': '%s S%s E%s' % (name, sz, eps), 'Plot': '%s S%s E%s' % (name, sz, eps), 'Season': sz, 'Episode': eps, 'TvShowTitle': name, 'Poster': default_image or imagine}
                            else:
                                info = {'Title': nume, 'Poster': imagine}
                            if legatura.endswith(".html"):
                                if  '/p/' in legatura: switch = 'liste'
                                else: switch = 'get_links'
                                if re.search('sezonul|episod|episoade', legatura): switch = 'get_links'
                            elif re.search('/search/', legatura): switch = 'recente'
                            else: switch = 'liste'
                            if re.search('sezonul|episod|episoade', legatura): switch = 'get_links'
                            
                            if nume and not nume.isspace():
                                lists.append({'nume': nume,
                                        'legatura': legatura.replace('"', ''),
                                        'imagine': imagine,
                                        'switch': switch, 
                                        'info': info})
            for meniul in re.compile(regex_menu1, re.DOTALL).findall(link):
                match = re.findall(regex_submenu1, meniul, re.DOTALL)
                for legatura, nume, imagine in match:
                    if nume and imagine:
                        if len(imagine) > 8:
                            nume = replaceHTMLCodes(ensure_str(nume))
                            info = {'Title': nume,'Plot': nume,'Poster': imagine}
                            szep = re.findall('(?:sezo[a-zA-Z\s]+(\d+).+?)?epi[a-zA-Z\s]+(\d+)', nume, re.IGNORECASE | re.DOTALL)
                            if szep:
                                try:
                                    if re.search('–|-|~', nume):
                                        all_name = re.split(r'–|-|:|~', nume,1)
                                        title = all_name[0]
                                        title2 = all_name[1]
                                    else: 
                                        title = nume
                                        title2 = ''
                                    title, year = xbmc.getCleanMovieTitle(title)
                                    title2, year2 = xbmc.getCleanMovieTitle(title2)
                                    title = title if title else title2
                                    year = year if year else year2
                                    if year: info['Year'] = year
                                    if szep[0][1] and not szep[0][0]: info['Season'] = '01'
                                    else: info['Season'] = str(szep[0][0])
                                    info['Episode'] = str(szep[0][1])
                                    info['TvShowTitle'] = (re.sub('(?:sezo[a-zA-Z\s]+\d+.+?)?epi[a-zA-Z\s]+\d+.+?$', '', title, flags=re.IGNORECASE | re.DOTALL)).strip()
                                except: pass
                            if re.search('sezonul|episod|film', legatura) or re.search('sezonul|episod|film', nume):
                                switch = 'get_links'
                            else: switch = 'liste'
                            lists.append({'nume': nume,
                                    'legatura': legatura,
                                    'imagine': imagine,
                                    'switch': switch, 
                                    'info': info})
            match = re.compile(regex_search, re.DOTALL).findall(link)
            if match:
                if '/page/' in url:
                    new = re.search('/page/(\d+)', url)
                    nexturl = re.sub('/page/(\d+)', '/page/' + str(int(new.group(1)) + 1)+'/', url)
                else: nexturl = url + "page/2/"
                lists.append({'nume': 'Next',
                            'legatura': nexturl,
                            'imagine': self.nextimage,
                            'switch': meniu, 
                            'info': {}})
            else:
                match = re.compile(regex_search1, re.DOTALL).findall(link)
                if match:
                    nexturl = unquot(match[0])
                    lists.append({'nume': 'Next',
                                        'legatura': nexturl,
                                        'imagine': self.nextimage,
                                        'switch': meniu, 
                                        'info': {}})
        return lists
   
class filmeonline2016biz:
    base_url = 'https://filmeonline.st'
    thumb = os.path.join(media, 'filmeonline2016biz.jpg')
    nextimage = next_icon
    searchimage = search_icon
    name = 'FilmeOnline2016.biz'
    menu = [('Recente', base_url, 'recente', thumb), 
            ('Genuri', base_url, 'genuri', thumb),
            ('Căutare', base_url, 'cauta', searchimage)]
    headers = {'User-Agent':'Mozilla/5.0 (Windows NT 6.1; rv:57.0) Gecko/20100101 Firefox/57.0', 'Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8', 'Accept-Language': 'ro,en-US;q=0.7,en;q=0.3', 'TE': 'Trailers'}
        
    def get_search_url(self, keyword):
        url = self.base_url + '/?s=' + quote(keyword)
        return url

    def getKey(self, item):
        return item[1]

    def cauta(self, keyword, limit=None):
        return self.__class__.__name__, self.name, self.parse_menu(self.get_search_url(keyword), 'recente', limit=limit)

    def parse_menu(self, url, meniu, info={}, limit=None):
        lists = []
        imagine = ''
        if meniu == 'recente' or meniu == 'cauta':
            if meniu == 'cauta':
                from resources.Core import Core
                Core().searchSites({'landsearch': self.__class__.__name__})
            else:
                count = 1
                link = fetchData(url, url, headers=self.headers)
                if not re.search(">Nothing Found", link):
                    regex_menu = '''<article.+?href="(.+?)".+?\s+src="(http.+?)".+?title">(.+?)<.+?"description">(.+?)</articl'''
                    if link:
                        match = re.findall(regex_menu, link, re.DOTALL | re.IGNORECASE)
                        for legatura, imagine, nume, descriere in match:
                            if not "&paged=" in legatura:
                                nume = replaceHTMLCodes(striphtml(nume))
                                descriere = " ".join(replaceHTMLCodes(striphtml(descriere)).split())
                                info = {'Title': nume,'Plot': descriere,'Poster': imagine}
                                lists.append({'nume': nume,
                                            'legatura': legatura,
                                            'imagine': imagine,
                                            'switch': 'get_links', 
                                            'info': info})
                                if limit:
                                    count += 1
                                    if count == int(limit):
                                        break
                        match = re.compile('pagenavi', re.IGNORECASE).findall(link)
                        if len(match) > 0:
                            if '/page/' in url:
                                new = re.compile('/page/(\d+)').findall(url)
                                nexturl = re.sub('/page/(\d+)', '/page/' + str(int(new[0]) + 1), url)
                            else:
                                if '/?s=' in url:
                                    nextpage = re.compile('\?s=(.+?)$').findall(url)
                                    nexturl = '%s%s?s=%s' % (self.base_url, ('page/2/' if str(url).endswith('/') else '/page/2/'), nextpage[0])
                                else: nexturl = url + "/page/2"
                            lists.append({'nume': 'Next',
                                    'legatura': nexturl,
                                    'imagine': self.nextimage,
                                    'switch': meniu, 
                                    'info': {}})
        elif meniu == 'get_links':
            import base64
            second = []
            link = fetchData('%s?show_player=true' % url)
            regex_lnk = '''(?:">(Episodul.+?)<.+?)?<iframe.+?src="((?:[htt]|[//]).+?)"'''
            regex_lnk2 = '''(?:">(Episodul.+?)<.+?)?atob\("(.+?)"'''
            regex_infos = '''kalin".+?<p>(.+?)</p'''
            regex_tag = '''category tag">(.+?)<'''
            match_lnk = re.findall(regex_lnk, link, re.IGNORECASE | re.DOTALL)
            match_lnk2 = re.findall(regex_lnk2, link, re.IGNORECASE | re.DOTALL)
            match_nfo = re.findall(regex_infos, link, re.IGNORECASE | re.DOTALL)
            match_tag = re.findall(regex_tag, link, re.IGNORECASE | re.DOTALL)
            try:
                info = eval(str(info))
                info['Plot'] = (striphtml(match_nfo[0]).strip())
                info['Genre'] = ', '.join(match_tag)
            except: pass
            infos = eval(str(info))
            try:
                for nume2, coded in match_lnk2:
                    second.append((nume2, base64.b64decode(coded)))
                second = second + match_lnk
            except: second = match_lnk
            for nume, link1 in second:
                try:
                    if py3: host = str(link1).split('/')[2].replace('www.', '').capitalize()
                    else: host = link1.split('/')[2].replace('www.', '').capitalize()
                    try:
                        year = re.findall("\((\d+)\)", infos.get('Title'))
                        infos['Year'] = year[0]
                    except: pass
                    try:
                        infos['TvShowTitle'] = re.sub(" (?:–|\().+?\)", "", info.get('Title'))
                        try:
                            infos['Season'] = str(re.findall("sezonul (\d+) ", info.get('Title'), re.IGNORECASE)[0])
                        except: infos['Season'] = '01'
                        infos['Episode'] = str(re.findall("episodul (\d+)$", nume, re.IGNORECASE)[0])
                        infos['Title'] = '%s S%sE%s' % (infos['TvShowTitle'], infos['Season'].zfill(2), infos['Episode'].zfill(2))
                        infos['Plot'] = infos['Title'] + ' ' + info['Plot']
                    except: pass
                    if nume:
                        lists.append({'nume': '[COLOR lime]%s[/COLOR]' % nume,
                                    'legatura': 'nimic',
                                    'imagine': '',
                                    'switch': '', 
                                    'info': {}})
                    lists.append({'nume': host,
                                'legatura': link1,
                                'imagine': '',
                                'switch': 'play', 
                                'info': str(infos),
                                'landing': url})
                except: pass
        elif meniu == 'genuri':
            link = fetchData(url, headers=self.headers)
            regex_cats = '''categories-2"(.+?)</ul'''
            regex_cat = '''href="(.+?)"(?:\s+.+?)?>(.+?)<'''
            if link:
                for cat in re.findall(regex_cats, link, re.IGNORECASE | re.DOTALL):
                    match = re.findall(regex_cat, cat, re.IGNORECASE | re.DOTALL)
                    if len(match) >= 0:
                        for legatura, nume in sorted(match, key=self.getKey):
                            nume = replaceHTMLCodes(nume).capitalize()
                            lists.append({'nume': nume,
                                    'legatura': legatura.replace('"', ''),
                                    'imagine': '',
                                    'switch': 'recente', 
                                    'info': info})
        return lists
    
class fsonlineorg:
    base_url = 'http://www.filmeserialeonline.org'
    thumb = os.path.join(media, 'fsonlineorg.jpg')
    nextimage = next_icon
    searchimage = search_icon
    name = 'FSOnline'
    menu = [('Recente', base_url, 'recente', thumb),
            ('Genuri Filme', '%s/filme-online/' % base_url, 'genuri', thumb),
            ('Genuri Seriale', '%s/seriale/' % base_url, 'genuri', thumb),
            ('Filme', base_url + '/filme-online/', 'recente', thumb),
            ('Seriale', base_url + '/seriale/', 'recente', thumb),
            ('Filme După ani', '%s/filme-online/' % base_url, 'ani', thumb),
            ('Seriale După ani', '%s/seriale/' % base_url, 'ani', thumb),
            ('Căutare', base_url, 'cauta', searchimage)]
        
    def get_search_url(self, keyword):
        url = self.base_url + '/?s=' + quote(keyword)
        return url

    def getKey(self, item):
        return item[1]

    def cauta(self, keyword, limit=None):
        return self.__class__.__name__, self.name, self.parse_menu(self.get_search_url(keyword), 'recente', limit=limit)

    def parse_menu(self, url, meniu, info={}, limit=None):
        lists = []
        #log('link: ' + link)
        imagine = ''
        if meniu == 'recente' or meniu == 'cauta':
            if meniu == 'cauta':
                from resources.Core import Core
                Core().searchSites({'landsearch': self.__class__.__name__})
            else:
                count = 1
                link = fetchData(url, self.base_url+ '/')
                regexprim = '''<div id="m(.*?)</div>.*?</div>'''
                regex = '''href="(.*?)".*?src="(.*?)".+?alt="(.*?)".*?class="tipoitem">(.*?)</.*?"icon-star">(.*?)</span.*?"calidad2">(.*?)</span.*?(?:.*"year">(.*?)</)?'''
                if link:
                    matches = re.findall(regexprim, link, re.DOTALL)
                    if matches:
                        for matchs in matches:
                            matchagain = re.findall(regex, matchs, re.DOTALL)
                            if matchagain:
                                for legatura, imagine, nume, descriere, tip, rating, an in matchagain:
                                    rating = striphtml(rating)
                                    descriere = replaceHTMLCodes(descriere)
                                    nume = replaceHTMLCodes(nume)
                                    imagine = imagine.strip()
                                    info = {'Title': nume,
                                        'Plot': descriere,
                                        'Rating': rating,
                                        'Poster': imagine,
                                        'Year': an}
                                    numelista = '%s (%s)' % (nume, an) if an else nume
                                    if re.search('/seriale/', legatura):
                                        lists.append({'nume': numelista + ' - Serial',
                                                    'legatura': legatura,
                                                    'imagine': imagine,
                                                    'switch': 'seriale', 
                                                    'info': str(info)})
                                        if limit:
                                            count += 1
                                            if count == int(limit):
                                                break
                                    else: 
                                        lists.append({'nume': numelista,
                                                    'legatura': legatura,
                                                    'imagine': imagine,
                                                    'switch': 'get_links', 
                                                    'info': str(info)})
                                        if limit:
                                            count += 1
                                            if count == int(limit):
                                                break
                            if limit:
                                if count == int(limit):
                                    break
                    match = re.compile('"paginador"', re.IGNORECASE).findall(link)
                    if len(match) > 0:
                        if '/page/' in url:
                            new = re.compile('/page/(\d+)').findall(url)
                            nexturl = re.sub('/page/(\d+)', '/page/' + str(int(new[0]) + 1), url)
                        else:
                            if '/?s=' in url:
                                nextpage = re.compile('\?s=(.+?)$').findall(url)
                                nexturl = '%s%s?s=%s' % (self.base_url, ('page/2/' if str(url).endswith('/') else '/page/2/'), nextpage[0])
                            else: nexturl = url + "/page/2"
                        lists.append({'nume': 'Next',
                                        'legatura': nexturl,
                                        'imagine': self.nextimage,
                                        'switch': meniu, 
                                        'info': {}})
        elif meniu == 'get_links':
            from resources.lib import requests
            from resources.lib.requests.packages.urllib3.exceptions import InsecureRequestWarning
            requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
            s = requests.Session()
            second = "%s/wp-content/themes/grifus/loop/second.php" % self.base_url
            third = '%s/wp-content/themes/grifus/includes/single/second.php' % self.base_url
            reg_id = '''id[\:\s]+(\d+)[,\}]'''
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; rv:70.1) Gecko/20100101 Firefox/70.1', 'Referer': url}
            first = s.get(url, headers=headers)
            try:
                mid = re.findall(reg_id, first.text)[0].strip()
            except: mid = "1"
            dataid = {'id': mid, 'logat': '0'}
            data1 = {'call': '03AHhf_52tCb5gUikGtjLeSMufA-2Hd3hcejVejJrPldhT-fjSepWRZdKTuQ0YjvPiph7-zcazBsIoVtGAwi_C3JsOFH74_TvXq2rRRQ4Aev59zTCFHFIAOOyxuOHRyIKIy4AZoxalLMegYUL5-J6LBvFZvFuTeKa6h3oNLISO4J0qw0fZSGrEhN02Hlbtnmdilj-nRUrMUCpPLWnZaV8eB8iatMaOg6FEqayxdJ1oF8AaFlOoVOnRrw_WWPu0cH97VkreacJNaQqh0qz-5yB1tbFD0GVOHLtU7Bd6DvUf_24hTxFsCszvjPD_hltYNxTrSOj49_lpTs279NghbyVvz-yVFfC-3mU-bQ'}
            if re.search('/episodul/', url):
                s.post(second, data=data1, headers=headers)
                j = 0
                html = ''
                while (j <= 4):
                    reslink = '%s/wp-content/themes/grifus/loop/second_id.php?id=%s&embed=%s' % (self.base_url, mid, j)
                    res = s.get(reslink, headers=headers).text
                    html += res
                    j = j + 1
                    xbmc.sleep(300)
                g = html
            else:
                f = s.post(third, data=data1, headers=headers)
                g = s.post(third, data=dataid, headers=headers).text
            reg_link = '''<iframe(?:.+?)?src="(?:[\s+])?((?:[htt]|[//]).+?)"'''
            linkss = []
            if not re.search('/episodul/', url):
                reg = '''url:\s+"(.+?)"'''
                match_lnk = re.findall(reg, g, re.IGNORECASE | re.DOTALL)
                try:
                    for links in match_lnk:
                        link = s.get('%s/%s' % (self.base_url,links), headers=headers).text
                        linkss.append(re.findall(reg_link, link)[0])
                except: pass
            else:
                match_lnk = re.findall(reg_link, g, re.IGNORECASE | re.DOTALL)
                for links in match_lnk:
                    linkss.append(links)
            for host, link1 in get_links(linkss, getlocation=True):
                if re.search('youtube.com', host, flags=re.IGNORECASE):
                    lists.append({'nume': 'Trailer Youtube',
                                    'legatura': link1,
                                    'imagine': '',
                                    'switch': 'play', 
                                    'info': info,
                                    'landing': url})
                else:
                    lists.append({'nume': host,
                                        'legatura': link1,
                                        'imagine': '',
                                        'switch': 'play', 
                                        'info': info,
                                        'landing': url})
        elif meniu == 'genuri':
            link = fetchData(url)
            regex_cats = '''"categorias">(.+?)</div'''
            regex_cat = '''href="(.+?)"(?:\s)?>(.+?)<.+?n>(.+?)<'''
            gen = re.findall(regex_cats, link, re.IGNORECASE | re.DOTALL)
            match = re.findall(regex_cat, gen[0], re.DOTALL)
            for legatura, nume, cantitate in match:
                nume = '%s [COLOR lime]%s[/COLOR]' % (replaceHTMLCodes(nume).capitalize(), cantitate)
                lists.append({'nume': nume,
                                        'legatura': legatura,
                                        'imagine': '',
                                        'switch': 'recente', 
                                        'info': info})
        elif meniu == 'seriale':
            link = fetchData(url)
            #log('link: ' + str(link))
            regex = '''(?:"se-q".+?title">(.*?)</span.+?)?"numerando">(.+?)<.+?class="episodiotitle.+?href="(.+?)"(?:[\s]+)?>(.+?)<.+?"date">(.+?)<'''
            match = re.findall(regex, link, re.DOTALL | re.IGNORECASE)
            info = eval(info)
            title = info.get('Title')
            #log(link)
            plot = info.get('Plot')
            for sezon, numerotare, link, nume, data in match:
                epis = numerotare.split('x')
                try:
                    infos = info
                    infos['Season'] = epis[0].strip()
                    infos['Episode'] = epis[1].strip()
                    infos['TVshowtitle'] = title
                    infos['Title'] = '%s S%02dE%02d' % (title, int(epis[0].strip()), int(epis[1].strip()))
                    infos['Plot'] = '%s S%02dE%02d - %s' % (title, int(epis[0].strip()), int(epis[1].strip()), plot)
                except: pass
                if sezon:
                    lists.append({'nume': '[COLOR lime]%s[/COLOR]' % sezon,
                                    'legatura': 'nolink',
                                    'imagine': '',
                                    'switch': 'nimic', 
                                    'info': {}})
                lists.append({'nume': nume,
                                    'legatura': link,
                                    'imagine': '',
                                    'switch': 'get_links', 
                                    'info': str(info)})
        elif meniu == 'ani':
            link = fetchData(url)
            regex_cats = '''"filtro_y">.*?(?:An Seriale|An Film)(.*?)</div'''
            regex_cat = '''href="(.+?)"(?:\s)?>(.+?)<'''
            an = re.compile(regex_cats, re.DOTALL).findall(link)
            match = re.compile(regex_cat, re.DOTALL).findall(an[0])
            for legatura, nume in match:
                lists.append({'nume': nume,
                                'legatura': legatura,
                                'imagine': '',
                                'switch': 'recente', 
                                'info': info})
        return lists

class hindilover:
    site_url = 'https://namasteserials.com'
    base_url = 'database.namasteserials.com'
    protocol = 'https://'
    api_url = '%s%s/api/' % (protocol,base_url)
    latestmovies_url = '%smovies/search/findAllByTypeIdWithAparitionDateTimeBefore?type_id=' % (api_url)
    finishedshows_url = '%stvShows/search/findByTypeIdAndTerminatTrueSeasons?id=' % (api_url)
    runningshows_url = '%stvShows/search/findByTypeIdAndTerminatFalseSeasons?id=' % (api_url)
    per_page = '20'
    thumb = os.path.join(media, 'hindilover.jpg')
    nextimage = next_icon
    searchimage = search_icon
    headers = {'Host': base_url,
                    'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; rv:70.1) Gecko/20100101 Firefox/70.1',
                    'Origin': site_url,
                    'Referer': '%s/' % site_url}
    name = 'HindiLover.biz'
    menu = [('Recente', '%sepisodes/search/findLastEpisodesByTypeId?type_id=1&page=0&size=20' % (api_url), 'recente', thumb),
            ('Seriale Indiene în desfășurare', '%s1&page=0&size=%s' % (runningshows_url,per_page), 'recente', thumb),
            ('Seriale Indiene terminate', '%s1&page=0&size=%s' % (finishedshows_url,per_page), 'recente', thumb),
            ('Seriale Turcești în desfășurare', '%s3&page=0&size=%s' % (runningshows_url,per_page), 'recente', thumb),
            ('Seriale Turcești terminate', '%s3&page=0&size=%s' % (finishedshows_url,per_page), 'recente', thumb),
            ('Seriale Coreene în desfășurare', '%s2&page=0&size=%s' % (runningshows_url,per_page), 'recente', thumb),
            ('Seriale Coreene terminate', '%s2&page=0&size=%s' % (finishedshows_url,per_page), 'recente', thumb),
            ('Seriale Spaniole în desfășurare', '%s4&page=0&size=%s' % (runningshows_url,per_page), 'recente', thumb),
            ('Seriale Spaniole terminate', '%s4&page=0&size=%s' % (finishedshows_url,per_page), 'recente', thumb),
            ('Seriale Românești în desfășurare', '%s5&page=0&size=%s' % (runningshows_url,per_page), 'recente', thumb),
            ('Seriale Românești terminate', '%s5&page=0&size=%s' % (finishedshows_url,per_page), 'recente', thumb),
            ('Filme Indiene', '%s1&page=0&size=%s' % (latestmovies_url,per_page), 'recente', thumb),
            ('Filme Turcești', '%s3&page=0&size=%s' % (latestmovies_url,per_page), 'recente', thumb),
            ('Filme Coreene', '%s2&page=0&size=%s' % (latestmovies_url,per_page), 'recente', thumb),
            ('Filme Românești', '%s5&page=0&size=%s' % (latestmovies_url,per_page), 'recente', thumb),
            ('Filme Spaniole', '%s4&page=0&size=%s' % (latestmovies_url,per_page), 'recente', thumb),
            ('Căutare', base_url, 'cauta', searchimage)]
        
    def get_search_url(self, keyword):
        url = '%stvShows/search/findByNameContainingOrderByNameAsc?name=%s&page=0&size=%s' % (self.api_url, quote(keyword), self.per_page)
        log(url)
        return url

    def getKey(self, item):
        return item[1]

    def cauta(self, keyword, limit=None):
        return self.__class__.__name__, self.name, self.parse_menu(self.get_search_url(keyword), 'recente', limit=limit)

    def parse_menu(self, url, meniu, info={}, limit=None):
        lists = []
        #log('link: ' + link)
        imagine = ''
        nexturl = None
        if meniu == 'recente' or meniu == 'cauta':
            if meniu == 'cauta':
                from resources.Core import Core
                Core().searchSites({'landsearch': self.__class__.__name__})
            else: 
                count = 1
                link = fetchData(url, headers=self.headers, rtype='json')
                if link:
                    results = link.get('_embedded')
                    episodes = results.get('episodes')
                    movies = results.get('movies')
                    tvshows = results.get('tvShows')
                    if episodes:
                        for episod in episodes:
                            legatura = ''
                            a = 1
                            infog = {}
                            nume = episod.get('name')
                            imagine = episod.get('img_url_big') or episod.get('img_url') or self.thumb
                            descriere = episod.get('description')
                            episodnumber = episod.get('numberCombinat') or episod.get('number')
                            sezonnumber = episod.get('sezon')
                            nume = '%s S%s E%s' % (nume, sezonnumber, episodnumber)
                            descriere = '%s %s' % (nume, descriere)
                            infog = {'Title': nume,'Plot': descriere,'Poster': imagine, 'TvShowTitle': nume, 'Episode': episodnumber, 'Season': sezonnumber}
                            while a <= 8:
                                getlink = episod.get('server%s' % str(a))
                                if getlink:
                                    legatura += '%s,,' % getlink
                                a += 1
                            lists.append({'nume': '%s' % nume,
                                    'legatura': legatura,
                                    'imagine': imagine,
                                    'switch': 'get_links', 
                                    'info': infog})
                            if limit:
                                count += 1
                                if count == int(limit):
                                    break
                    if tvshows:
                        for show in tvshows:
                            ids = show.get('id')
                            nume = show.get('name')
                            descriere = show.get('description')
                            imagine = show.get('imageUrlBig') or show.get('imageUrl') or self.thumb
                            infog = {'Title': nume,'Plot': descriere,'Poster': imagine}
                            legatura = '%sepisodes/search/findTvShowEpisodes?show_id=%s&page=0&size=%s' % (self.api_url, ids, self.per_page)
                            lists.append({'nume': '%s' % nume,
                                    'legatura': legatura,
                                    'imagine': imagine,
                                    'switch': 'recente', 
                                    'info': infog})
                            if limit:
                                count += 1
                                if count == int(limit):
                                    break
                    if movies:
                        for movie in movies:
                            nume = movie.get('name')
                            descriere = movie.get('description')
                            an = movie.get('year')
                            imagine = movie.get('imageUrlBig') or movie.get('imageUrl') or self.thumb
                            infog = {'Title': nume,'Plot': descriere,'Poster': imagine,'Year': an}
                            legatura = ''
                            a = 1
                            while a <= 8:
                                getlink = movie.get('server%s' % str(a))
                                if getlink:
                                    legatura += '%s,,' % getlink
                                a += 1
                            lists.append({'nume': '%s' % nume,
                                    'legatura': legatura,
                                    'imagine': imagine,
                                    'switch': 'get_links', 
                                    'info': infog})
                            if limit:
                                count += 1
                                if count == int(limit):
                                    break
                    if '&page=' in url:
                        new = re.compile('page\=(\d+)').findall(url)
                        nexturl = re.sub('page\=(\d+)', 'page=' + str(int(new[0]) + 1), url)
                        lists.append({'nume': 'Next',
                                    'legatura': nexturl,
                                    'imagine': self.nextimage,
                                    'switch': meniu, 
                                    'info': {}})
        
        elif meniu == "get_links":
            match = url.split(',,')
            log(match)
            if match:
                for host, link1 in get_links(match):
                    lists.append({'nume': host,
                                    'legatura': link1,
                                    'imagine': '',
                                    'switch': 'play', 
                                    'info': info,
                                    'landing': url})
        return lists
    
class portalultautv:
    base_url = 'https://portalultautv.net'
    thumb = os.path.join(media, 'portalultautv.jpg')
    nextimage = next_icon
    searchimage = search_icon
    name = 'PortalulTauTv.com'
    menu = [('Recente', base_url, 'recente', thumb), 
            ('Seriale', '%s/seriale-online-subtitrate-hd/' % base_url, 'recente', thumb),
            ('Genuri', base_url, 'genuri', thumb),
            ('Căutare', base_url, 'cauta', searchimage)]
                

    def cauta(self, keyword, limit=None):
        return self.__class__.__name__, self.name, self.parse_menu(self.get_search_url(keyword), 'recente', limit=limit)
        
    def get_search_url(self, keyword):
        url = self.base_url + '/?s=' + quote(keyword)
        return url

    def parse_menu(self, url, meniu, info={}, limit=None):
        lists = []
        link = fetchData(url)
        if meniu == 'recente' or meniu == 'cauta':
            if meniu == 'cauta':
                from resources.Core import Core
                Core().searchSites({'landsearch': self.__class__.__name__})
            else: 
                count = 1
                link = fetchData(url, self.base_url + '/')
                regex_menu = '''<article(.+?)</art'''
                regex_submenu = '''href=['"](.*?)['"](?:.*?title=['"](.*?)['"])?.*?src=['"](.*?)['"](?:.*?title=['"](.*?)['"])?'''
                if link:
                    for movie in re.compile(regex_menu,  re.DOTALL).findall(link):
                        match = re.compile(regex_submenu, re.DOTALL).findall(movie)
                        for legatura, nume, imagine, nume2 in match:
                            nume = nume or nume2
                            nume = replaceHTMLCodes(striphtml(nume))
                            info = {'Title': nume,'Plot': nume,'Poster': imagine}
                            lists.append({'nume': nume,
                                    'legatura': legatura,
                                    'imagine': imagine,
                                    'switch': 'get_links', 
                                    'info': info})
                            if limit:
                                count += 1
                                if count == int(limit):
                                    break
                        if limit:
                            if count == int(limit):
                                break
                    match = re.compile('navigation"', re.IGNORECASE).findall(link)
                    match2 = re.compile('"next page-numbers"', re.IGNORECASE).findall(link)
                    if len(match) > 0 or len(match2) > 0:
                        if '/page/' in url:
                            new = re.compile('/page/(\d+)').findall(url)
                            nexturl = re.sub('/page/(\d+)', '/page/' + str(int(new[0]) + 1), url)
                        else:
                            if '/?s=' in url:
                                nextpage = re.compile('\?s=(.+?)$').findall(url)
                                nexturl = '%s%s?s=%s' % (self.base_url, ('page/2/' if str(url).endswith('/') else '/page/2/'), nextpage[0])
                            else: nexturl = '%s/page/2' % url if not url.endswith('/') else '%spage/2' % url
                        #log(nexturl)
                        lists.append({'nume': 'Next',
                                    'legatura': nexturl,
                                    'imagine': self.nextimage,
                                    'switch': meniu, 
                                    'info': {}})
        elif meniu == 'get_links':
            link = fetchData(url)
            nume = ''
            regex_lnk = '''(?:type=[\'"]text/javascript["\']>(?:\s+)?str=['"](.+?)["']|(?:(S\d+E\d+).+?)?<iframe.+?src=['"]((?:[htt]|[//]).+?)["'])'''
            regex_seriale = '''(?:<h3>.+?strong>(.+?)<(.+?)hr />)'''
            regex_infos = '''sinopsis(.+?)<div'''
            regex_content = '''<article(.+?)</articl'''
            match_content = re.findall(regex_content, link, re.IGNORECASE | re.DOTALL)
            match_lnk = []
            #match_nfo = []
            #match_srl = []
            if len(match_content) > 0:
                match_lnk = re.compile(regex_lnk, re.IGNORECASE | re.DOTALL).findall(link)
                #match_nfo = re.compile(regex_infos, re.IGNORECASE | re.DOTALL).findall(link)
                #match_srl = re.compile(regex_seriale, re.IGNORECASE | re.DOTALL).findall(link)
            infos = eval(str(info))
            #try:
                #infos['Title'] = infos.get('Title').decode('unicode-escape')
                #infos['Plot'] = infos.get('Plot').decode('unicode-escape')
                #infos['Poster'] = infos.get('Poster').decode('unicode-escape')
            #except: pass
            #try:
                #if len(match_nfo) > 0:
                    #infos['Plot'] = htmlparser.HTMLParser().unescape(striphtml(match_nfo[0]).strip().decode('utf-8'))
            #except: pass
            titleorig = infos['Title']
            for numerotare, linknumerotare, linknumerotareunu in match_lnk:
                if not numerotare:
                    szep = re.findall('S(\d+)E(\d+)', linknumerotare, re.IGNORECASE | re.DOTALL)
                    if szep:
                        episod = linknumerotare
                        linknumerotare = linknumerotareunu
                        try:
                            if re.search('–|-|~', titleorig):
                                all_name = re.split(r'–|-|:|~', titleorig,1)
                                title = all_name[1]
                                title2 = all_name[0]
                            else: 
                                title = titleorig
                                title2 = ''
                            title, year = xbmc.getCleanMovieTitle(title)
                            title2, year2 = xbmc.getCleanMovieTitle(title2)
                            title = title if title else title2
                            year = year if year else year2
                            if year: infos['Year'] = year
                            if szep[0][1] and not szep[0][0]: infos['Season'] = '01'
                            else: infos['Season'] = str(szep[0][0])
                            infos['Episode'] = str(szep[0][1])
                            infos['TvShowTitle'] = title
                        except: pass
                else:
                    #log(unquote(numerotare.replace('@','%')))
                    numerotare = re.findall('<(?:iframe|script).+?src=[\'"]((?:[htt]|[//]).+?)["\']', unquote(numerotare.replace('@','%')), re.IGNORECASE | re.DOTALL)[0]
                    try:
                        if re.search('–|-|~', titleorig):
                            all_name = re.split(r'–|-|:|~', titleorig,1)
                            title = all_name[1]
                            title2 = all_name[0]
                        else: 
                            title = titleorig
                            title2 = ''
                        title, year = xbmc.getCleanMovieTitle(title)
                        title2, year2 = xbmc.getCleanMovieTitle(title2)
                        title = title if title else title2
                        year = year if year else year2
                        if year: infos['Year'] = year
                        infos['Title'] = title
                    except: pass
                    linknumerotare = numerotare
                #log(numerotare)
                try:
                    if not numerotare: host = episod
                    else: host = ''
                    #log(host)
                    for hosts, link1 in get_links([linknumerotare]):
                        lists.append({'nume': '%s %s' % (host, hosts),
                                    'legatura': link1,
                                    'imagine': '',
                                    'switch': 'play', 
                                    'info': str(infos),
                                    'landing': url})
                except:
                    for host, link1 in get_links([linknumerotareunu]):
                        lists.append({'nume': host,
                                    'legatura': link1,
                                    'imagine': '',
                                    'switch': 'play', 
                                    'info': str(infos),
                                    'landing': url})
        elif meniu == 'genuri':
            link = fetchData(url)
            regex_cats = '''Categorie-Gen(.+?)</div'''
            regex_cat = '''\s+href=["'](.*?)['"\s]>(.+?)<'''
            if link:
                for cat in re.compile(regex_cats, re.IGNORECASE | re.MULTILINE | re.DOTALL).findall(link):
                    match = re.compile(regex_cat, re.DOTALL).findall(cat)
                    for legatura, nume in match:
                        lists.append({'nume': nume,
                                    'legatura': legatura.replace('"', ''),
                                    'imagine': '',
                                    'switch': 'recente', 
                                    'info': info})
        return lists

class serialenoihd:
    base_url = 'https://serialenoihd.com'
    thumb = os.path.join(media, 'serialenoihd.jpg')
    nextimage = next_icon
    searchimage = search_icon
    name = 'SerialeNoiHD.com'
    menu = [('Recente', base_url, 'recente', thumb),
            ('Categorii', base_url, 'categorii', thumb),
            ('Căutare', base_url, 'cauta', searchimage)]
        
    def get_search_url(self, keyword):
        url = self.base_url + '/?s=' + quote(keyword)
        return url

    def getKey(self, item):
        return item[1]

    def cauta(self, keyword, limit=None):
        return self.__class__.__name__, self.name, self.parse_menu(self.get_search_url(keyword), 'recente', limit=limit)

    def parse_menu(self, url, meniu, info={}, limit=None):
        lists = []
        imagine = ''
        if meniu == 'recente' or meniu == 'cauta':
            if meniu == 'cauta':
                from resources.Core import Core
                Core().searchSites({'landsearch': self.__class__.__name__})
            else:
                count = 1
                link = fetchData(url)
                regex_menu = '''<article(.+?)</article'''
                regex_submenu = '''href="(.+?)".+?src="(.+?)".+?mark">(.+?)<.+?excerpt">(.+?)</div'''
                if link:
                    for movie in re.compile(regex_menu, re.IGNORECASE | re.MULTILINE | re.DOTALL).findall(link):
                        match = re.compile(regex_submenu, re.DOTALL).findall(movie)
                        for legatura, imagine, nume, descriere in match:
                            nume = replaceHTMLCodes(striphtml(nume))
                            descriere = replaceHTMLCodes(striphtml(descriere))
                            info = {'Title': nume,'Plot': descriere,'Poster': imagine}
                            szep = re.findall('(?:sezo[a-zA-Z\s]+(\d+).+?)?epi[a-zA-Z\s]+(\d+)', nume, re.IGNORECASE | re.DOTALL)
                            if szep:
                                try:
                                    if re.search('–|-|~', nume):
                                        all_name = re.split(r'–|-|:|~', nume,1)
                                        title = all_name[0]
                                        title2 = all_name[1]
                                    else: 
                                        title = nume
                                        title2 = ''
                                    title, year = xbmc.getCleanMovieTitle(title)
                                    title2, year2 = xbmc.getCleanMovieTitle(title2)
                                    title = title if title else title2
                                    year = year if year else year2
                                    if year: info['Year'] = year
                                    if szep[0][1] and not szep[0][0]: info['Season'] = '01'
                                    else: info['Season'] = str(szep[0][0])
                                    info['Episode'] = str(szep[0][1])
                                    info['TvShowTitle'] = (re.sub('(?:sezo[a-zA-Z\s]+\d+.+?)?epi[a-zA-Z\s]+\d+', '', title, flags=re.IGNORECASE | re.DOTALL)).strip()
                                except: pass
                            lists.append({'nume': nume,
                                    'legatura': legatura,
                                    'imagine': imagine,
                                    'switch': 'get_links', 
                                    'info': str(info)})
                            if limit:
                                count += 1
                                if count == int(limit):
                                    break
                        if limit:
                            if count == int(limit):
                                break
                    match = re.compile('"nav-links"', re.IGNORECASE).findall(link)
                    if len(match) > 0:
                        if '/page/' in url:
                            new = re.compile('/page/(\d+)').findall(url)
                            nexturl = re.sub('/page/(\d+)', '/page/' + str(int(new[0]) + 1), url)
                        else:
                            if '/?s=' in url:
                                nextpage = re.compile('\?s=(.+?)$').findall(url)
                                nexturl = '%s%s?s=%s' % (self.base_url, ('page/2/' if str(url).endswith('/') else '/page/2/'), nextpage[0])
                            else: nexturl = url + "/page/2"
                        lists.append({'nume': 'Next',
                                    'legatura': nexturl,
                                    'imagine': self.nextimage,
                                    'switch': meniu, 
                                    'info': {}})
        elif meniu == 'get_links':
            link = fetchData(url)
            if re.search('content-protector-captcha', link):
                cpc = re.findall('content-protector-captcha.+?value="(.+?)"', link, re.DOTALL)
                cpt = re.findall('content-protector-token.+?value="(.+?)"', link, re.DOTALL)
                cpi = re.findall('content-protector-ident.+?value="(.+?)"', link, re.DOTALL)
                cpp = re.findall('content-protector-password.+?value="(.+?)"', link, re.DOTALL)
                cpsx = '348'
                cpsy = '220'
                data = {'content-protector-captcha': cpc[0],
                        'content-protector-token': cpt[0],
                        'content-protector-ident': cpi[0],
                        'content-protector-submit.x': cpsx,
                        'content-protector-submit.y': cpsy,
                        'content-protector-password': cpp[0]}
                link = fetchData(url, data=data)
            coded_lnk = '''type=[\'"].+?text/javascript[\'"]>(?:\s+)?str=['"](.+?)["']'''
            regex_lnk = '''<iframe.+?src="((?:[htt]|[//]).+?)"'''
            regex_infos = '''"description">(.+?)</'''
            match_coded = re.compile(coded_lnk, re.IGNORECASE | re.DOTALL).findall(link)
            match_lnk = re.compile(regex_lnk, re.IGNORECASE | re.DOTALL).findall(link)
            match_nfo = re.compile(regex_infos, re.IGNORECASE | re.DOTALL).findall(link)
            try:
                info = eval(str(info))
                info['Plot'] = (striphtml(match_nfo[0]).strip())
            except: pass
            regex_sub_oload = '''"captions" src="(.+?)"'''
            regex_sub_vidoza = '''tracks[:\s]+(.+?])'''
            for host, link1 in get_links(match_lnk):
                lists.append({'nume': host,
                                'legatura': link1,
                                'imagine': '',
                                'switch': 'play', 
                                'info': info,
                                'landing': url})
            try:
                list_link = []
                for one_code in match_coded:
                    decoded = re.findall('<(?:iframe|script).+?src=[\'"]((?:[htt]|[//]).+?)["\']', unquote(one_code.replace('@','%')), re.IGNORECASE | re.DOTALL)[0]
                    list_link.append(decoded)
                for host, link1 in get_links(list_link):
                    lists.append({'nume': host,
                                    'legatura': link1,
                                    'imagine': '',
                                    'switch': 'play', 
                                    'info': info,
                                    'landing': url})
            except: pass
                
        elif meniu == 'categorii':
            cats = ['Seriale Indiene', 'Seriale Turcesti', 'Seriale Straine', 'Emisiuni TV', 'Seriale Romanesti']
            for cat in cats:
                lists.append({'nume': cat,
                                'legatura': self.base_url,
                                'imagine': self.thumb,
                                'switch': 'titluri', 
                                'info': {'categorie': cat}})
        elif meniu == 'titluri':
            info = eval(str(info))
            link = fetchData(url)
            regex_cats = '''%s</a>(.+?)</ul''' % info.get('categorie')
            regex_cat = '''href="(.+?)"(?:\s+)?>(.+?)<'''
            if link:
                for cat in re.findall(regex_cats, link, re.IGNORECASE | re.DOTALL):
                    match = re.findall(regex_cat, cat, re.IGNORECASE | re.DOTALL)
                    if len(match) >= 0:
                        for legatura, nume in sorted(match, key=self.getKey):
                            nume = replaceHTMLCodes(striphtml(nume)).capitalize()
                            lists.append({'nume': nume,
                                    'legatura': legatura.replace('"', ''),
                                    'imagine': '',
                                    'switch': 'recente', 
                                    'info': info})
        return lists

class topfilmeonline:
    base_url = 'https://topfilmeonline.biz'
    thumb = os.path.join(media, 'topfilmeonline.jpg')
    nextimage = next_icon
    searchimage = search_icon
    name = 'TopFilmeOnline'
    menu = [('Recente', base_url, 'recente', thumb), 
            ('Genuri', base_url, 'genuri', thumb),
            ('Căutare', 'post', 'cauta', searchimage)]
        
    def get_search_url(self, keyword):
        url = self.base_url + '/?s=' + quote(keyword)
        return url

    def getKey(self, item):
        return item[1]

    def cauta(self, keyword, limit=None):
        return self.__class__.__name__, self.name, self.parse_menu('post', 'cauta', keyw=keyword, limit=limit)

    def parse_menu(self, url, meniu, info={}, keyw=None, limit=None):
        lists = []
        #log('link: ' + link)
        imagine = ''
        if meniu == 'recente':
            count = 1
            link = fetchData(url, self.base_url + '/')
            regex_submenu = '''article id="post.*?href="(.*?)".*?title">(.*?)<.*?(?:.*?imdb.*?([\d.]+))?.*?views.*?(\d+).*?data-src="(.*?)"'''
            if link:
                match = re.compile(regex_submenu, re.IGNORECASE | re.DOTALL).findall(link)
                if len(match) > 0:
                    for legatura, nume, imdb, views, imagine in match:
                        nume = replaceHTMLCodes(striphtml(nume))
                        info = {'Title': nume,'Plot': nume,'Poster': imagine, 'Rating' : imdb}
                        lists.append({'nume': nume,
                                    'legatura': legatura,
                                    'imagine': imagine,
                                    'switch': 'get_links', 
                                    'info': info})
                        if limit:
                            count += 1
                            if count == int(limit):
                                break
                match = re.compile('"navigation', re.IGNORECASE).findall(link)
                if len(match) > 0:
                    if '/page/' in url:
                        new = re.compile('/page/(\d+)').findall(url)
                        nexturl = re.sub('/page/(\d+)', '/page/' + str(int(new[0]) + 1), url)
                    else:
                        if '/?s=' in url:
                            nextpage = re.compile('\?s=(.+?)$').findall(url)
                            nexturl = '%s%s?s=%s' % (self.base_url, ('page/2/' if str(url).endswith('/') else '/page/2/'), nextpage[0])
                        else: nexturl = url + "/page/2"
                    lists.append({'nume': 'Next',
                                    'legatura': nexturl,
                                    'imagine': self.nextimage,
                                    'switch': meniu, 
                                    'info': {}})
        elif meniu == 'cauta':
            count = 1
            if url == 'post':

                if keyw:
                    url = self.get_search_url(keyw)
                    link = fetchData(url)
                else:
                    link = None
                    from resources.Core import Core
                    Core().searchSites({'landsearch': self.__class__.__name__})
            else:
                link = fetchData(url)
            regex = '''post-.+?href="(.+?)".+?>(.+?)<.+?summary">(.+?)</div'''
            if link:
                match = re.compile(regex, re.IGNORECASE | re.DOTALL).findall(link)
                if len(match) > 0:
                    for legatura, nume, descriere in match:
                        imagine = self.thumb
                        nume = replaceHTMLCodes(striphtml(ensure_str(nume)))
                        descriere = replaceHTMLCodes(striphtml(ensure_str(descriere)))
                        info = {'Title': nume,'Plot': descriere,'Poster': imagine}
                        lists.append({'nume': nume,
                                    'legatura': legatura,
                                    'imagine': imagine,
                                    'switch': 'get_links', 
                                    'info': info})
                        if limit:
                            count += 1
                            if count == int(limit):
                                break
                match = re.compile('"navigation', re.IGNORECASE).findall(link)
                if len(match) > 0:
                    if '/page/' in url:
                        new = re.compile('/page/(\d+)').findall(url)
                        nexturl = re.sub('/page/(\d+)', '/page/' + str(int(new[0]) + 1), url)
                    else:
                        if '/?s=' in url:
                            nextpage = re.compile('\?s=(.+?)$').findall(url)
                            nexturl = '%s%s?s=%s' % (self.base_url, ('page/2/' if str(url).endswith('/') else '/page/2/'), nextpage[0])
                        else: nexturl = url + "/page/2"
                    lists.append({'nume': 'Next',
                                    'legatura': nexturl,
                                    'imagine': self.nextimage,
                                    'switch': meniu, 
                                    'info': {}})
            
        elif meniu == 'get_links':
            link = fetchData(url)
            links = []
            regex_lnk = '''<iframe.+?src="((?:[htt]|[//]).+?)"'''
            regex_infos = '''movie-description">(.+?)</p'''
            reg_id = '''data-singleid="(.+?)"'''
            reg_server = '''data-server="(.+?)"'''
            match_nfo = re.compile(regex_infos, re.IGNORECASE | re.DOTALL).findall(link)
            match_id = re.findall(reg_id, link, re.IGNORECASE | re.DOTALL)
            match_server = re.findall(reg_server, link, re.IGNORECASE | re.DOTALL)
            #try:
                #mid = list(set(match_id))[0]
                #mserver = list(set(match_server))
                #for code in mserver:
                    #try:
                        #get_stupid_links = fetchData('%s/wp-admin/admin-ajax.php' % self.base_url, data = {'action': 'samara_video_lazyload', 
                                                                                #'server': code,
                                                                                #'singleid': mid})
                        #match_lnk = re.findall(regex_lnk, get_stupid_links, re.IGNORECASE | re.DOTALL)
                        #links.append(match_lnk[0])
                    #except: pass
            #except: pass
            try:
                links = re.findall(regex_lnk, link, re.IGNORECASE | re.DOTALL)
            except: pass
            try:
                info = eval(str(info))
                info['Plot'] = (striphtml(match_nfo[0]).strip())
            except: pass
            for host, link1 in get_links(links):
                lists.append({'nume': host,
                                'legatura': link1,
                                'imagine': '',
                                'switch': 'play', 
                                'info': info,
                                'landing': url})
        elif meniu == 'genuri':
            link = fetchData(url)
            regex_cats = '''"cat-item.+?href=['"](.+?)['"](?:>|.+?title.+?">)(.+?)<'''
            if link:
                match = re.compile(regex_cats, re.IGNORECASE | re.MULTILINE | re.DOTALL).findall(link)
                if len(match) >= 0:
                    for legatura, nume in sorted(match, key=self.getKey):
                        lists.append({'nume': nume,
                                    'legatura': legatura.replace('"', ''),
                                    'imagine': '',
                                    'switch': 'recente', 
                                    'info': info})
        return lists
    
class voxfilmeonline:
    base_url = 'https://voxfilmeonline.biz'
    thumb = os.path.join(media, 'voxfilmeonline.jpg')
    nextimage = next_icon
    searchimage = search_icon
    name = 'VoxFilmeOnline'
    menu = [('Recente', base_url, 'recente', thumb), 
            ('Genuri', base_url, 'genuri', thumb),
            ('Căutare', base_url, 'cauta', searchimage)]
        
    def get_search_url(self, keyword):
        url = self.base_url + '/?s=' + quote(keyword)
        return url

    def getKey(self, item):
        return item[1]

    def cauta(self, keyword, limit=None):
        return self.__class__.__name__, self.name, self.parse_menu(self.get_search_url(keyword), 'recente', limit=limit)

    def parse_menu(self, url, meniu, info={}, limit=None):
        lists = []
        #log('link: ' + link)
        imagine = ''
        if meniu == 'recente' or meniu == 'cauta':
            if meniu == 'cauta':
                from resources.Core import Core
                Core().searchSites({'landsearch': self.__class__.__name__})
            else: 
                count = 1
                link = fetchData(url)
                regex_menu = '''<article(.+?)</art'''
                regex_submenu = '''href="(.+?)".+?title">(.+?)<(?:.+?rating">(.+?)</div)?.+?src="(ht.+?)"'''
                if link:
                    for movie in re.compile(regex_menu, re.IGNORECASE | re.MULTILINE | re.DOTALL).findall(link):
                        match = re.compile(regex_submenu, re.DOTALL).findall(movie)
                        for legatura, nume, descriere, imagine in match:
                            try:
                                nume = replaceHTMLCodes(striphtml(ensure_str(nume)))
                                descriere = replaceHTMLCodes(striphtml(ensure_str(descriere)))
                            except:
                                nume = striphtml(ensure_str(nume)).strip()
                                descriere = striphtml(ensure_str(descriere)).strip()
                            descriere = "-".join(descriere.split("\n"))
                            info = {'Title': nume,'Plot': descriere,'Poster': imagine}
                            lists.append({'nume': nume,
                                    'legatura': legatura,
                                    'imagine': imagine,
                                    'switch': 'get_links', 
                                    'info': info})
                            if limit:
                                count += 1
                                if count == int(limit):
                                    break
                        if limit:
                            if count == int(limit):
                                break
                    match = re.compile('pagination"', re.IGNORECASE).findall(link)
                    if len(match) > 0:
                        if '/page/' in url:
                            new = re.compile('/page/(\d+)').findall(url)
                            nexturl = re.sub('/page/(\d+)', '/page/' + str(int(new[0]) + 1), url)
                        else:
                            if '/?s=' in url:
                                nextpage = re.compile('\?s=(.+?)$').findall(url)
                                nexturl = '%s%s?s=%s' % (self.base_url, ('page/2/' if str(url).endswith('/') else '/page/2/'), nextpage[0])
                            else: nexturl = url + "/page/2"
                        lists.append({'nume': 'Next',
                                    'legatura': nexturl,
                                    'imagine': self.nextimage,
                                    'switch': meniu, 
                                    'info': {}})
        elif meniu == 'get_links':
            link = fetchData(url)
            links = []
            regex_lnk = '''<iframe.+?src="((?:[htt]|[//]).+?)"'''
            match_lnk = re.compile(regex_lnk, re.IGNORECASE | re.DOTALL).findall(link)
            try:
                match_lnk = list(set(match_lnk))
            except: pass
            for host, link1 in get_links(match_lnk):
                lists.append({'nume': host,
                                    'legatura': link1,
                                    'imagine': '',
                                    'switch': 'play', 
                                    'info': info,
                                    'landing': url})
        elif meniu == 'genuri':
            link = fetchData(url)
            regex_cats = '''cat\-item\-.+?href=['"](.+?)['"](?:\s+.+?">|>)?(.+?)</a'''
            if link:
                match = re.compile(regex_cats).findall(link)
                if len(match) >= 0:
                    for legatura, nume in sorted(match, key=self.getKey):
                        lists.append({'nume': nume,
                                    'legatura': legatura.replace('"',''),
                                    'imagine': '',
                                    'switch': 'recente', 
                                    'info': info})
        return lists

class dozaanimata:
    base_url = 'https://www.dozaanimata.ro'
    thumb = os.path.join(media,'dozaanimata.jpg')
    nextimage = next_icon
    searchimage = search_icon
    name = 'DozaAnimata'
    menu = [('Desene', '%s/tag/desene/' % base_url, 'recente', thumb), 
            ('Anime', '%s/tag/anime/' % base_url, 'recente', thumb),
            ('Filme', '%s/genre/filme/'% base_url, 'recente', thumb),
            ('Seriale', '%s/series/'% base_url, 'recente', thumb),
            ('Canale', base_url, 'genuri', thumb),
            ('Căutare', base_url, 'cauta', searchimage)]
                

    def cauta(self, keyword, limit=None):
        return self.__class__.__name__, self.name, self.parse_menu(self.get_search_url(keyword), 'recente', limit=limit)
        
    def get_search_url(self, keyword):
        url = '%s/page/1/?s=%s' % (self.base_url, quote(keyword))
        return url

    def parse_menu(self, url, meniu, info={}, limit=None):
        lists = []
        if meniu == 'recente':
            count = 1
            url = '%s%s' % (self.base_url, url) if url.startswith('/') else url
            link = fetchData(url)
            regex = '''data-movie-id=(.+?)clearfix"></div>'''
            mregex = '''href="(.+?)".+?(?:.+?quality(?:\s+tv)?"\>(.+?)\<)?.+?(?:.+?eps"\>(.+?)\</sp)?.+?data-original="(.+?)".+?info"\>(.+?)\</sp'''
            match = re.findall(regex, link, re.DOTALL)
            if len(match) > 0:
                for movies in match:
                    movie = re.findall(mregex, movies, re.DOTALL)
                    if movie:
                        for legatura, calitate, episod, imagine, nume in movie:
                            legatura = '%s%s' % (self.base_url, legatura) if legatura.startswith('/') else legatura
                            nume = replaceHTMLCodes(striphtml(nume))
                            if calitate:
                                nume = '%s [COLOR lime]%s[/COLOR]' % (nume, striphtml(calitate).strip())
                            if episod:
                                nume = '%s [COLOR lime]%s[/COLOR]' % (nume, striphtml(episod).strip())
                            info = {'Title': nume,'Plot': nume,'Poster': imagine}
                            lists.append({'nume': nume,
                                    'legatura': legatura,
                                    'imagine': imagine,
                                    'switch': 'get_links', 
                                    'info': info})
                            if limit:
                                count += 1
                                if count == int(limit):
                                    break
                    if limit:
                        if count == int(limit):
                            break
                match = re.compile("pagination'.+?page/", re.IGNORECASE).findall(link)
                if len(match) > 0 :
                    nexturl = ''
                    if '/page/' in url:
                        new = re.compile('/page/(\d+)').findall(url)
                        nexturl = re.sub('/page/(\d+)', '/page/' + str(int(new[0]) + 1), url)
                    elif 'page=' in url:
                            new = re.compile('page\=(\d+)').findall(url)
                            nexturl = re.sub('page\=(\d+)', 'page\=' + str(int(new[0]) + 1), url)
                    else:
                        nexturl = '%spage/2/' % url
                    lists.append({'nume': 'Next',
                                    'legatura': nexturl,
                                    'imagine': self.nextimage,
                                    'switch': meniu, 
                                    'info': {}})
        elif meniu == 'get_links':
            url = '%s%s' % (self.base_url, url) if url.startswith('/') else url
            link = fetchData(url)
            seasons_regex = '''tvseason"(?:.*?\>(Sez.*?)\<)?.*?(.*?)\</div\>\s*\</div\>'''
            episode_regex = '''href="(.+?)">(.+?)<'''
            coded_lnk = '''text/javascript[\'"]>(?:\s+)?str=['"](.+?)["']'''
            regex_lnk = '''<iframe.+?src="((?:[htt]|[//]).+?)"'''
            if link:
                s = re.findall(seasons_regex, link, re.DOTALL)
                if s:
                    for sezonname, episodelist in s:
                        lists.append({'nume': '[COLOR lime]%s[/COLOR]' % sezonname.strip(),
                                    'legatura': 'nolink',
                                    'imagine': '',
                                    'switch': 'nimic', 
                                    'info': {}})
                        episodes = re.findall(episode_regex, episodelist, re.DOTALL)
                        if episodes:
                            for episodeurl, episodename in episodes:
                                lists.append({'nume': episodename.strip(),
                                            'legatura': episodeurl.strip(),
                                            'imagine': '',
                                            'switch': 'get_links', 
                                            'info': info})
                else:
                    match_coded = re.compile(coded_lnk, re.IGNORECASE | re.DOTALL).findall(link)
                    match_lnk = re.findall(regex_lnk, link, re.DOTALL)
                    for host, link1 in get_links(match_lnk, getlocation=True):
                        lists.append({'nume': host,
                                    'legatura': link1,
                                    'imagine': '',
                                    'switch': 'play', 
                                    'info': info,
                                    'landing': url})
                    list_link = []
                    for one_code in match_coded:
                        decoded = ''
                        try:
                            decoded = re.findall('<(?:iframe|script).+?src=[\'"]((?:[htt]|[//]).+?)["\']', unquote(one_code.replace('@','%')), re.IGNORECASE | re.DOTALL)[0]
                        except:
                            decoded = unquote(one_code.replace('@','%'))
                        list_link.append(decoded)
                    for host, link1 in get_links(list_link, getlocation=True):
                        lists.append({'nume': host,
                                    'legatura': link1,
                                    'imagine': '',
                                    'switch': 'play', 
                                    'info': info,
                                    'landing': url})
        elif meniu == 'cauta':
            from resources.Core import Core
            Core().searchSites({'landsearch': self.__class__.__name__})
        elif meniu == 'genuri':
            link = fetchData(url)
            regex = '''Canale.+?<ul(.+?)</ul'''
            regex_cat = '''<li.+?href="(.+?)">(.+?)<'''
            if link:
                match = re.findall(regex, link, re.DOTALL)
                if len(match) > 0:
                    match2 = re.findall(regex_cat, match[0])
                    if match2:
                        for legatura, nume in match2:
                            nume = replaceHTMLCodes(nume).capitalize()
                            lists.append({'nume': nume,
                                    'legatura': legatura.replace('"',''),
                                    'imagine': '',
                                    'switch': 'recente', 
                                    'info': info})
        return lists

class filmehdnet:
    base_url = 'https://filmehd.se'
    thumb = os.path.join(media, 'filmehdnet.jpg')
    nextimage = next_icon
    searchimage = search_icon
    name = 'FilmeHD.net'
    menu = [('Recente', base_url + '/page/1', 'recente', thumb), 
            ('Categorii', base_url, 'genuri', thumb),
            ('După ani', base_url, 'ani', thumb),
            ('Seriale', base_url + '/seriale', 'recente', thumb),
            ('De colecție', base_url + '/filme-vechi', 'recente', thumb),
            ('Căutare', base_url, 'cauta', searchimage)]
        
    def get_search_url(self, keyword):
        url = self.base_url + '/?s=' + quote(keyword)
        return url

    def getKey(self, item):
        return item[1]

    def cauta(self, keyword, limit=None):
        return self.__class__.__name__, self.name, self.parse_menu(self.get_search_url(keyword), 'recente', limit=limit)

    def parse_menu(self, url, meniu, info={}, limit=None):
        lists = []
        imagine = ''
        if meniu == 'recente' or meniu == 'cauta':
            if meniu == 'cauta':
                from resources.Core import Core
                Core().searchSites({'landsearch': self.__class__.__name__})
            else: 
                count = 1
                link = fetchData(url)
                regex_submenu = '''class="imgleft".+?href="(.+?)".+?src="(.+?)".+?href.+?>(.+?)<'''
                if link:
                    match = re.compile(regex_submenu, re.DOTALL).findall(link)
                    for legatura, imagine, nume in match:
                        if py3: nume = replaceHTMLCodes(nume)
                        else: nume = replaceHTMLCodes(nume.decode('utf-8')).encode('utf-8')
                        info = {'Title': nume,'Plot': nume,'Poster': imagine}
                        if 'serial-tv' in legatura or 'miniserie-tv' in legatura:
                            try:
                                if re.search('–|-|~', nume):
                                    all_name = re.split(r'–|-|:|~', nume,1)
                                    title = all_name[0]
                                    title2 = all_name[1]
                                else: title2 = ''
                                title, year = xbmc.getCleanMovieTitle(title)
                                title2, year2 = xbmc.getCleanMovieTitle(title2)
                                title = title if title else title2
                                year = year if year else year2
                                info['Year'] = year
                                info['TVShowTitle'] = title
                            except:pass
                        lists.append({'nume': nume,
                                    'legatura': legatura,
                                    'imagine': imagine,
                                    'switch': 'get_all', 
                                    'info': info})
                        if limit:
                            count += 1
                            if count == int(limit):
                                break
                    match = re.compile('class=\'wp-pagenavi', re.IGNORECASE).findall(link)
                    if len(match) > 0:
                        if '/page/' in url:
                            new = re.compile('/page/(\d+)').findall(url)
                            nexturl = re.sub('/page/(\d+)', '/page/' + str(int(new[0]) + 1), url)
                        else:
                            if '/?s=' in url:
                                nextpage = re.compile('\?s=(.+?)$').findall(url)
                                nexturl = '%s%s?s=%s' % (self.base_url, ('page/2/' if str(url).endswith('/') else '/page/2/'), nextpage[0])
                            else: nexturl = url + "/page/2"
                        lists.append({'nume': 'Next',
                                    'legatura': nexturl,
                                    'imagine': self.nextimage,
                                    'switch': meniu, 
                                    'info': {}})
        elif meniu == 'get_all':
            link = fetchData(url)
            regex_lnk = '''(?:id="tabs_desc_\d+_(.*?)".*?)?(?:<center>(.*?)</center>.*?)?data-src=['"]((?:[htt]|[//]).*?)['"]'''
            regex_infos = '''Descriere film.+?p>(.+?)</p'''
            match_lnk = re.findall(regex_lnk, link, re.IGNORECASE | re.DOTALL)
            match_nfo = re.findall(regex_infos, link, re.IGNORECASE | re.DOTALL)
            info = eval(str(info))
            try:
                info['Plot'] = (striphtml(match_nfo[0]).strip())
            except: pass
            for server, name, legatura in match_lnk:
                if server:
                    lists.append({'nume': 'Server  %s' % server,
                                    'legatura': legatura,
                                    'imagine': '',
                                    'switch': 'nimic', 
                                    'info': info,
                                    'landing': url})
                if not legatura.startswith('http'):
                    legatura = '%s%s' % (self.base_url, legatura.replace('&amp;', '&'))
                name = striphtml(name)
                if info.get('TVShowTitle'):
                    try:
                        szep = re.findall('sezo[a-zA-Z\s]+(\d+)\s+epi[a-zA-Z\s]+(\d+)', name, re.IGNORECASE)
                        if szep:
                            info['Season'] = str(szep[0][0])
                            info['Episode'] = str(szep[0][1])
                    except: pass
                if name: 
                    lists.append({'nume': name,
                                    'legatura': legatura,
                                    'imagine': '',
                                    'switch': 'get_links', 
                                    'info': str(info)})
        elif meniu == 'get_links':
            link = fetchData(url)
            regex_lnk = '''<iframe(?:.+?)?src=['"]((?:[htt]|[//]).+?)['"]'''
            match_lnk = re.compile(regex_lnk, re.IGNORECASE | re.DOTALL).findall(link)
            for host, link1 in get_links(match_lnk):
                lists.append({'nume': host,
                                    'legatura': link1,
                                    'imagine': '',
                                    'switch': 'play', 
                                    'info': info,
                                    'landing': url})
        elif meniu == 'genuri':
            link = fetchData(url)
            cats = []
            regex_menu = '''GEN FILM.*<ul\s+class="sub-menu(.+?)</ul>'''
            regex_submenu = '''<li.+?a href="(.+?)">(.+?)<'''
            for meniu in re.compile(regex_menu, re.IGNORECASE | re.MULTILINE | re.DOTALL).findall(link):
                match = re.compile(regex_submenu, re.DOTALL).findall(meniu)
                for legatura, nume in match:
                    if py3: nume = replaceHTMLCodes(nume).capitalize()
                    else: nume = replaceHTMLCodes(nume.decode('utf-8')).encode('utf-8').capitalize()
                    cats.append((legatura, nume))
                cats.append(('https://filmehd.se/despre/filme-romanesti', 'Romanesti'))
            for legatura, nume in sorted(cats, key=self.getKey):
                lists.append({'nume': nume,
                                    'legatura': legatura.replace("'",''),
                                    'imagine': self.thumb,
                                    'switch': 'recente', 
                                    'info': info})
        elif meniu == 'ani':
            import datetime
            an = datetime.datetime.now().year
            while (an > 1929):
                legatura = self.base_url + '/despre/filme-' + str(an)
                lists.append({'nume': str(an),
                                    'legatura': legatura,
                                    'imagine': self.thumb,
                                    'switch': 'recente', 
                                    'info': info})
                an -= 1
        return lists
    
class fsonlineto:
    base_url = 'https://fsonline.app'
    thumb = os.path.join(media, 'fsonlineorg.jpg')
    nextimage = next_icon
    searchimage = search_icon
    name = 'FSOnline2'
    menu = [('Recente', base_url, 'recente', thumb),
            ('Filme', '%s/film/' % base_url, 'recente', thumb),
            ('Seriale', '%s/seriale/' % base_url, 'recente', thumb),
            ('Genuri', base_url, 'genuri', thumb),
            ('Căutare', base_url, 'cauta', searchimage)]
        
    def get_search_url(self, keyword):
        url = self.base_url + '/?s=' + quote(keyword)
        return url

    def getKey(self, item):
        return item[1]

    def cauta(self, keyword, limit=None):
        return self.__class__.__name__, self.name, self.parse_menu(self.get_search_url(keyword), 'recente', limit=limit)

    def parse_menu(self, url, meniu, info={}, limit=None):
        lists = []
        #log('link: ' + link)
        imagine = ''
        if meniu == 'recente' or meniu == 'cauta':
            if meniu == 'cauta':
                from resources.Core import Core
                Core().searchSites({'landsearch': self.__class__.__name__})
            else: 
                count = 1
                link = fetchData(url)
                regex_menu = '''<article(.+?)</art'''
                regex_submenu = '''(?:src="(ht.+?)".*?alt="(.*?)".*?(?:"quali.*?"|"tobeornot")>(.*?)<.*?href="(.*?)"|href="(.*?)".*?src="(.*?)".*?alt="(.*?)".*?"tobeornot">(.*?)<)'''
                if link:
                    for movie in re.compile(regex_menu, re.IGNORECASE | re.MULTILINE | re.DOTALL).findall(link):
                        match = re.compile(regex_submenu, re.DOTALL).findall(movie)
                        for movie in match:
                            imagine, nume, descriere, legatura, legatura1, imagine1, nume1, descriere1 = movie
                            imagine = imagine or imagine1
                            nume = nume or nume1
                            legatura = legatura or legatura1
                            descriere = descriere or descriere1
                            try:
                                nume = replaceHTMLCodes(striphtml(ensure_str(nume)))
                                descriere = replaceHTMLCodes(striphtml(ensure_str(descriere)))
                            except:
                                nume = striphtml(ensure_str(nume)).strip()
                                descriere = striphtml(ensure_str(descriere)).strip()
                            descriere = "-".join(descriere.split("\n"))
                            info = {'Title': nume,'Plot': descriere,'Poster': imagine}
                            if '/seriale/' in legatura:
                                switch = 'get_seasons'
                            else:
                                switch = 'get_links'
                            lists.append({'nume': nume,
                                    'legatura': legatura,
                                    'imagine': imagine,
                                    'switch': switch,
                                    'info': info})
                            if limit:
                                count += 1
                                if count == int(limit):
                                    break
                        if limit:
                            if count == int(limit):
                                break
                    match = re.compile('pagination"', re.IGNORECASE).findall(link)
                    if len(match) > 0:
                        if '/page/' in url:
                            new = re.compile('/page/(\d+)').findall(url)
                            nexturl = re.sub('/page/(\d+)', '/page/' + str(int(new[0]) + 1), url)
                        else:
                            if '/?s=' in url:
                                nextpage = re.compile('\?s=(.+?)$').findall(url)
                                nexturl = '%s%s?s=%s' % (self.base_url, ('page/2/' if str(url).endswith('/') else '/page/2/'), nextpage[0])
                            else: nexturl = url + "/page/2"
                        lists.append({'nume': 'Next',
                                    'legatura': nexturl,
                                    'imagine': self.nextimage,
                                    'switch': meniu, 
                                    'info': {}})
        elif meniu == 'get_links':
            link = fetchData(url)
            #log(link)
            links = []
            servers_lnk = []
            ids = '''movie\-id="(.*?)"'''
            regex_lnk = '''data-vs="((?:[htt]|[//]).+?)"'''
            match_ids = re.search(ids, link)
            if match_ids:
                ids_nr = match_ids.group(1)
            else:
                ids_nr = '0'
            data = {'action': 'lazy_player',
                        'movieID': ids_nr}
            post_link = '%s/wp-admin/admin-ajax.php' % self.base_url
            link = fetchData(post_link, data=data)
            headers = {'Referer': self.base_url}
            match_lnk = re.compile(regex_lnk, re.DOTALL).findall(link)
            if match_lnk:
                match_lnk = list(set(match_lnk))
                for server_link in match_lnk:
                    servers = requests.head(server_link, headers=headers)
                    server = servers.headers.get('Location')
                    servers_lnk.append(server)
            for host, link1 in get_links(servers_lnk):
                lists.append({'nume': host,
                                    'legatura': link1,
                                    'imagine': '',
                                    'switch': 'play', 
                                    'info': info,
                                    'landing': url})
        elif meniu == 'get_seasons':
            link = fetchData(url)
            regex_menu = '''<article class="item (?:season|episodes)"(.*?)</art'''
            regex_submenu = '''href="(.*?)".*?src="(.*?)".*?"data">(.*?)</div'''
            for sezon in re.compile(regex_menu, re.DOTALL).findall(link):
                match = re.findall(regex_submenu, sezon, re.DOTALL)
                if match:
                    for legatura, imagine, nume in match:
                        nume = striphtml(nume)
                        info = {'Title': nume,'Plot': nume,'Poster': imagine}
                        if '/sezonul/' in legatura:
                            switch = 'get_seasons'
                        else:
                            switch = 'get_links'
                        lists.append({'nume': nume,
                                        'legatura': legatura,
                                        'imagine': imagine,
                                        'switch': switch, 
                                        'info': info})
        elif meniu == 'genuri':
            link = fetchData(url)
            regex_container = '''Genuri.*?<ul(.*?)</ul'''
            regex_cats = '''href="(.*?)">(.*?)<'''
            if link:
                match_container = re.search(regex_container, link)
                if match_container:
                    match = re.findall(regex_cats, match_container.group(1))
                    for legatura, nume in sorted(match, key=self.getKey):
                        if '/seriale/' in legatura:
                            switch = 'get_seasons'
                        else:
                            switch = 'recente'
                        lists.append({'nume': nume,
                                    'legatura': legatura.replace('"',''),
                                    'imagine': '',
                                    'switch': switch, 
                                    'info': info})
        return lists
