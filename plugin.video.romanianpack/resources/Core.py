# -*- coding: utf-8 -*-

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs
from .functions import *
from resources.lib import streams, torrents
import json

__settings__ = xbmcaddon.Addon()

__all__ = [x for x in streams.streamsites if __settings__.getSetting(x) != 'false']
__disabled__ = [x for x in streams.streamsites if __settings__.getSetting(x) == 'false']
__alltr__ = [x for x in torrents.torrentsites if __settings__.getSetting(x) != 'false']
__disabledtr__ = [x for x in torrents.torrentsites if __settings__.getSetting(x) == 'false']

try:
    __handle__ = int(sys.argv[1])
    xbmcplugin.setContent(__handle__, 'movies')
except: pass

class player():
        
    def run(self, urls, item, params, link):
        try: __handle__ = int(sys.argv[1])
        except: pass
        landing = ''
        subtitrare = ''
        try:
            seek_time = params.get('info').get('seek_time')
        except: seek_time = None
        if params.get('landing'): 
            landing = params.get('landing')
            params.update({'link': landing, 'switch' : 'get_links'})
        if link == urls or params.get('subtitrare'):
            if params.get('subtitrare'):
                subtitrare = get_sub(unquote(params.get('subtitrare')), unquote(landing), '1')
        else: subtitrare = get_sub(link, unquote(landing))
        item.setInfo('video', {'Cast': [unquot(str(params))]})
        item.setProperty('isPlayable', 'true')
        try:
            item.setPath(urls)
        except:
            item.setPath(str(urls))
        item.setMimeType('mime/x-type')
        try: 
            item.setContentLookup(False)
        except: pass
        try:
            if subtitrare:
                item.setSubtitles([subtitrare])
        except: pass
        xbmcplugin.setResolvedUrl(__handle__, True, listitem=item)
        if seek_time:
            try:
                i=0
                while not xbmc.Monitor().abortRequested() and not xbmc.Player().isPlaying() and i < 450:
                    xbmc.sleep(1000)
                    i += 1
                xbmc.Player().seekTime(float(seek_time) - 30)
            except: pass


class Core:
    __scriptname__ = __settings__.getAddonInfo('name')
    ROOT = __settings__.getAddonInfo('path')
    scrapers = os.path.join(ROOT, 'resources', 'lib', 'scrapers')
    if scrapers not in sys.path: sys.path.append(scrapers)
    torrents = os.path.join(ROOT, 'resources', 'lib', 'torrent')
    if torrents not in sys.path: sys.path.append(torrents)
    create_tables()
    #check_one_db()
    if xbmc.getCondVisibility('System.HasAddon(plugin.video.youtube)'): youtube = '1'
    else: youtube = '0'
    if getSettingAsBool('torrs'):
        if __settings__.getSetting('searchtype') == 'Torrent': sstype = 'torrs'
        elif __settings__.getSetting('searchtype') == 'Ambele': sstype = 'both'
        else: sstype = 'sites'
    else: sstype = 'sites'
    context_trakt_search_mode = __settings__.getSetting('context_trakt_search_mode')

    def sectionMenu(self):
        listings = []
        listings.append(self.drawItem(title = '[COLOR lime]Recente sortate după nume [/COLOR]',
                 action = 'recents',
                 link = {'Sortby': 'name'},
                 image = recents_icon))
        listings.append(self.drawItem(title = '[COLOR lime]Recente grupate pe site-uri [/COLOR]',
                 action = 'recents',
                 link = {'Sortby': 'site'},
                 image = recents_icon))
        listings.append(self.drawItem(title = '[COLOR lime]Categorii[/COLOR]',
                 action = 'getCats',
                 link = {},
                 image = cat_icon))
        if self.sstype == 'both':
            if getSettingAsBool('torrs'):
                listings.append(self.drawItem(title = '[COLOR lime]Torrent[/COLOR]',
                                              action = 'TorrentsMenu',
                                              link = {},
                                              image = torr_icon))
        listings.append(self.drawItem(title = '[COLOR lime]Favorite[/COLOR]',
                                      action = 'favorite',
                                      link = {'site': 'site',
                                              'favorite': 'print'},
                                      image = torr_icon))
        listings.append(self.drawItem(title = '[COLOR lime]Căutare[/COLOR]',
                                      action = 'searchSites',
                                      link = {'Stype': 'sites'},
                                      image = search_icon))
        listings.append(self.drawItem(title = '[COLOR lime]Văzute[/COLOR]',
                 action = 'watched',
                 link = {'watched': 'list'},
                 image = seen_icon))
        listings.append(self.drawItem(title = '[COLOR lime]Cinemagia[/COLOR]',
                 action = 'openCinemagia',
                 link = {},
                 image = os.path.join(media, 'cinemagia.jpg')))
        listings.append(self.drawItem(title = '[COLOR lime]IMDb[/COLOR]',
                 action = 'openIMDb',
                 link = {},
                 image = os.path.join(media, 'imdb.png')))
        listings.append(self.drawItem(title = '[COLOR lime]Trakt[/COLOR]',
                 action = 'openTrakt',
                 link = {},
                 image = os.path.join(media, 'trakt.png')))
        #self.drawItem('[COLOR lime]Setări[/COLOR]', 'openSettings', {}, image=os.path.join(media, 'settings.png'))
        set1 = xbmcgui.ListItem('[COLOR lime]Setări[/COLOR]')
        set1.setArt({'icon': os.path.join(media, 'settings.png')})
        set3 = xbmcgui.ListItem('[COLOR lime]Setări Resolver[/COLOR]')
        set3.setArt({'icon': os.path.join(media, 'settings.png')})
        listings.append(('%s?action=openSettings' % (sys.argv[0]), set1, False))
        listings.append(('%s?action=openResolverSettings' % (sys.argv[0]), set3, False))
        for site in __all__:
            cm = []
            imp =  streams.streamnames.get(site)
            name = imp.get('nume')
            params = {'site': site}
            cm.append(self.CM('disableSite', 'disable', nume=site))
            listings.append(self.drawItem(title = name,
                 action = 'openMenu',
                 link = params,
                 image = imp.get('thumb'),
                 contextMenu = cm))
        for site in __disabled__:
            cm = []
            imp =  streams.streamnames.get(site)
            name = imp.get('nume')
            params = {'site': site, 'nume': name, 'disableSite': 'check'}
            cm.append(self.CM('disableSite', 'enable', nume=site))
            listitem=xbmcgui.ListItem('[COLOR red]%s[/COLOR]' % name)
            listitem.setArt({'thumb': imp.get('thumb'), 'icon': imp.get('thumb')})
            listitem.addContextMenuItems(cm, replaceItems=True)
            url = '%s?action=disableSite&site=%s&nume=%s&disableSite=check' % (sys.argv[0], site, name)
            listings.append((url, listitem, False))
            #self.drawItem('[COLOR red]%s[/COLOR]'% name, 'disableSite', params, image=imp().thumb, contextMenu=cm, isFolder=False, replaceMenu=False)
        xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
        xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)
    
    def TorrentsMenu(self, params={}):
        listings = []
        listings.append(self.drawItem(title = '[COLOR lime]Recente sortate după seederi [/COLOR]',
                                      action = 'recents',
                                      link = {'Rtype': 'torrs', 'Sortby': 'seed'},
                                      image = recents_icon))
        listings.append(self.drawItem(title = '[COLOR lime]Recente sortate după mărime [/COLOR]',
                                      action = 'recents',
                                      link = {'Rtype': 'torrs', 'Sortby': 'size'},
                                      image = recents_icon))
        listings.append(self.drawItem(title = '[COLOR lime]Recente sortate după nume [/COLOR]',
                                      action = 'recents',
                                      link = {'Rtype': 'torrs', 'Sortby': 'name'},
                                      image = recents_icon))
        listings.append(self.drawItem(title = '[COLOR lime]Recente grupate pe site-uri [/COLOR]',
                                      action = 'recents',
                                      link = {'Rtype': 'torrs', 'Sortby': 'site'},
                                      image = recents_icon))
        #self.drawItem('[COLOR lime]Categorii[/COLOR]', 'getCats', {}, image=search_icon)
        listings.append(self.drawItem(title = '[COLOR lime]Căutare[/COLOR]',
                                      action = 'searchSites',
                                      link = {'Stype': 'torrs'},
                                      image = search_icon))
        if self.sstype == 'torrs':
            listings.append(self.drawItem(title = '[COLOR lime]Favorite[/COLOR]',
                                          action = 'favorite',
                                          link = {'site': 'site', 'favorite': 'print'},
                                          image = torr_icon))
            listings.append(self.drawItem(title = '[COLOR lime]Văzute[/COLOR]',
                                          action = 'watched',
                                          link = {'watched': 'list'},
                                          image = seen_icon))
            listings.append(self.drawItem(title = '[COLOR lime]Cinemagia[/COLOR]',
                                          action = 'openCinemagia',
                                          link = {},
                                          image = os.path.join(media, 'cinemagia.jpg')))
            listings.append(self.drawItem(title = '[COLOR lime]IMDb[/COLOR]',
                                          action = 'openIMDb',
                                          link = {},
                                          image = os.path.join(media, 'imdb.png')))
            listings.append(self.drawItem(title = '[COLOR lime]Trakt[/COLOR]',
                                          action = 'openTrakt',
                                          link = {},
                                          image = os.path.join(media, 'trakt.png')))
        tcb = xbmcgui.ListItem('[COLOR lime]Torrent client browser[/COLOR]')
        tcb.setArt({'thumb': torrclient_icon})
        listings.append(('%s?action=OpenT&Tmode=opentclient&Turl=abcd' % (sys.argv[0]), tcb, False))
        lb = xbmcgui.ListItem('[COLOR lime]Libtorrent browser[/COLOR]')
        lb.setArt({'thumb': torrclient_icon})
        if torrenter: listings.append(('%s?action=OpenT&Tmode=opentbrowser&Turl=abcd' % (sys.argv[0]), lb, False))
        tcb = xbmcgui.ListItem('[COLOR lime]Intern Torrent[/COLOR]')
        tcb.setArt({'thumb': torrclient_icon})
        listings.append(('%s?action=OpenT&Tmode=opentintern&Turl=abcd' % (sys.argv[0]), tcb, False))
        if self.sstype == 'torrs':
            set1 = xbmcgui.ListItem('[COLOR lime]Setări[/COLOR]')
            set1.setArt({'icon': os.path.join(media, 'settings.png')})
            listings.append(('%s?action=openSettings' % (sys.argv[0]), set1, False))
        set2 = xbmcgui.ListItem('[COLOR lime]Setări Torrent2http[/COLOR]')
        set2.setArt({'icon': os.path.join(media, 'settings.png')})
        listings.append(('%s?action=openSettings&script=torrent2http' % (sys.argv[0]), set2, False))
        for torr in __alltr__:
            cm = []
            imp = torrents.torrnames.get(torr)
            name = imp.get('nume')
            params = {'site': torr}
            seedmrsp = getSettingAsBool('%sseedmrsp' % torr)
            seedtransmission = getSettingAsBool('%sseedtransmission' % torr)
            cm.append(self.CM('disableSite', 'disable', nume=torr))
            if seedmrsp or seedtransmission:
                params['info'] = {'Plot': 'Seeding cu %s activat' % ('MRSP' if seedmrsp else 'Transmission')}
                name = '[COLOR lightblue]%s[/COLOR]' % name
            else:
                params['info'] = {'Plot': 'Seeding dezactivat'}
            if not seedtransmission:
                cm.append(('%s seed MRSP' % ('Dezactivează' if seedmrsp else 'Activează'), 'RunPlugin(%s?action=setTorrent&setTorrent=%s&site=%s&value=%s)' % (sys.argv[0], 'seedmrsp', torr, 'false' if seedmrsp else 'true')))
            if not seedmrsp:
                cm.append(('%s seed Transmission' % ('Dezactivează' if seedtransmission else 'Activează'), 'RunPlugin(%s?action=setTorrent&setTorrent=%s&site=%s&value=%s)' % (sys.argv[0], 'seedtransmission', torr, 'false' if seedtransmission else 'true')))
            listings.append(self.drawItem(title = name,
                                          action = 'openMenu',
                                          link = params,
                                          image = imp.get('thumb'),
                                          contextMenu = cm))
        for torr in __disabledtr__:
            cm = []
            imp = torrents.torrnames.get(torr)
            name = imp.get('nume')
            cm.append(self.CM('disableSite', 'enable', nume=torr))
            listitem=xbmcgui.ListItem('[COLOR red]%s[/COLOR]' % name)
            listitem.setArt({'thumb': imp.get('thumb')})
            listitem.addContextMenuItems(cm, replaceItems=True)
            url = '%s?action=disableSite&site=%s&nume=%s&disableSite=check' % (sys.argv[0], torr, name)
            listings.append((url, listitem, False))
            #self.drawItem('[COLOR red]%s[/COLOR]'% name, 'disableSite', params, image=imp().thumb, contextMenu=cm, isFolder=False, replaceMenu=False)
        xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
        xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)

    def authTrakt(self, params={}):
        from . import trakt
        trakt.authTrakt()
        
    def testTrakt(self, params={}):
        from . import trakt
        get = params.get
        imdb = get('testTrakt')
        if imdb:
            trakt.addShowToWtachlist(imdb)
    
    def markTrakt(self, params={}):
        from . import trakt
        get = params.get
        action = get('markTrakt')
        det = unquote(get('detalii'))
        det = eval(det)
        idt = det.get('id')
        sezon = det.get('sezon')
        episod = det.get('episod')
        if action == 'watched':
            try:
                if sezon and episod:
                    result = trakt.markEpisodeAsWatched(idt, sezon, episod)
                    result = json.loads(result)
                    number = result.get('added').get('episodes') 
                    if number > 0:
                        showMessage("MRSP", "%s episod marcat vizionat in Trakt" % str(number), 3000)
            except: pass
        if action == 'delete':
            try:
                result = trakt.markTVShowAsNotWatched(idt)
                result = json.loads(result)
                showMessage("MRSP", "show sters din Trakt", 3000)
            except: pass
        #xbmc.sleep(1000)
        #xbmc.executebuiltin("Container.Refresh")
        
    def openTrakt(self, params={}):
        from . import trakt
        import zipfile
        if py3: from io import BytesIO as StringIO
        else: from cStringIO import StringIO
        import base64
        showunreleased = getSettingAsBool('showtraktunreleased')
        new_params = {}
        listings = []
        seelist = []
        action = params.get('openTrakt')
        page = params.get('page')
        page = int(page) if page else 1
        traktCredentials = trakt.getTraktCredentialsInfo()
        items = []
        image = os.path.join(media, 'trakt.png')
        if not traktCredentials:
            trakt.authTrakt()
        else:
            if not action:
                listings.append(self.drawItem(title = '[COLOR lime]Calendar[/COLOR]',
                                          action = 'openTrakt',
                                          link = {'openTrakt': 'calendar'},
                                          image = image))
                listings.append(self.drawItem(title = '[COLOR lime]Trending[/COLOR]',
                                          action = 'openTrakt',
                                          link = {'openTrakt': 'trending', 'page': page},
                                          image = image))
                listings.append(self.drawItem(title = '[COLOR lime]Popular[/COLOR]',
                                          action = 'openTrakt',
                                          link = {'openTrakt': 'popular', 'page': page},
                                          image = image))
                listings.append(self.drawItem(title = '[COLOR lime]Played[/COLOR]',
                                          action = 'openTrakt',
                                          link = {'openTrakt': 'played', 'page': page},
                                          image = image))
                listings.append(self.drawItem(title = '[COLOR lime]Watched[/COLOR]',
                                          action = 'openTrakt',
                                          link = {'openTrakt': 'watched', 'page': page},
                                          image = image))
            elif action in ['popular','watched','trending','played']:
                if action == 'popular':
                    tkturl = 'popular?limit=30&page=%s' % page
                elif action == 'watched':
                    tkturl = 'watched/weekly?limit=30&page=%s' % page
                elif action == 'trending':
                    tkturl = 'trending?limit=30&page=%s' % page
                elif action == 'played':
                    tkturl = 'played/weekly?limit=30&page=%s' % page
                movielist = trakt.getMovie(tkturl, full=True)
                if movielist:
                    for item in movielist:
                        try: imdb = item.get('ids').get('imdb')
                        except:
                            item = item.get('movie')
                            imdb = item.get('ids').get('imdb')
                        tmdb = item.get('ids').get('tmdb')
                        tmdb_url = 'https://api.themoviedb.org/3/movie/%s?api_key=%s&language=en-US' % (tmdb, tmdb_key())
                        tmdb_data = fetchData(tmdb_url,rtype='json')
                        try: poster = tmdb_data.get('poster_path')
                        except: poster = None
                        try: fanart = tmdb_data.get('backdrop_path')
                        except: fanart = None
                        infos = {}
                        infos['Title'] = item.get('title')
                        infos['Year'] = item.get('year')
                        infos['Premiered'] = item.get('released')
                        infos['Genre'] = ', '.join(item.get('genres'))
                        infos['Rating'] = item.get('rating')
                        infos['Votes'] = item.get('votes')
                        infos['Plot'] = item.get('overview')
                        infos['Trailer'] = item.get('trailer')
                        infos['Duration'] = item.get('runtime') * 60
                        infos['imdb'] = imdb
                        infos['Poster'] = '%s' % ('https://image.tmdb.org/t/p/w500%s' % poster) if poster else image
                        infos['Fanart'] = '%s' % ('https://image.tmdb.org/t/p/w780%s' % fanart) if fanart else ''
                        #infos['tmdb'] = item.get('ids').get('tmdb')
                        infos['Country'] = item.get('country')
                        #infos['Language'] = item.get('language')
                        infos['PlotOutline'] = item.get('tagline')
                        infos['mpaa'] = item.get('certification')
                        nume = item.get('title')
                        new_params['info'] = str(infos)
                        new_params['Stype'] = self.sstype
                        if self.context_trakt_search_mode == '0':
                            new_params['modalitate'] = 'edit'
                            new_params['query'] = quote(nume)
                            
                        else:
                            new_params['searchSites'] = 'cuvant'
                            new_params['cuvant'] = quote(nume)
                        listings.append(self.drawItem(title = nume,
                                          action = 'searchSites',
                                          link = new_params,
                                          image = infos['Poster']))
                    listings.append(self.drawItem(title = 'Next',
                                          action = 'openTrakt',
                                          link = {'openTrakt': action, 'page': page + 1},
                                          image = next_icon))
                    #lists.append(('Next', nexturl, self.nextimage, 'get_torrent', {}))
            elif action == 'calendar':
                syncs = trakt.syncTVShows()
                if syncs:
                    for item in syncs:
                        try:
                            num_1 = 0
                            for i in range(0, len(item['seasons'])):
                                if item['seasons'][i]['number'] > 0: num_1 += len(item['seasons'][i]['episodes'])
                            num_2 = int(item['show']['aired_episodes'])
                            if num_1 > num_2: raise Exception()
                            season = str(item['seasons'][-1]['number'])

                            episode = [x for x in item['seasons'][-1]['episodes'] if 'number' in x]
                            episode = sorted(episode, key=lambda x: x['number'])
                            episode = str(episode[-1]['number'])

                            tvshowtitle = item['show']['title']
                            if tvshowtitle == None or tvshowtitle == '': raise Exception()
                            tvshowtitle = replaceHTMLCodes(tvshowtitle)

                            year = item['show']['year']
                            year = re.sub('[^0-9]', '', str(year))
                            if int(year) > int((datetime.datetime.utcnow() - datetime.timedelta(hours = 5)).strftime('%Y')): raise Exception()

                            imdb = item['show']['ids']['imdb']
                            if imdb == None or imdb == '': imdb = '0'

                            tvdb = item['show']['ids']['tvdb']
                            if tvdb == None or tvdb == '': raise Exception()
                            tvdb = re.sub('[^0-9]', '', str(tvdb))

                            last_watched = item['last_watched_at']
                            if last_watched == None or last_watched == '': last_watched = '0'
                            items.append({'imdb': imdb, 'tvdb': tvdb, 'tvshowtitle': tvshowtitle, 'year': year, 'snum': season, 'enum': episode, '_last_watched': last_watched})
                        except: pass
                    def items_list(i, seelist):
                        try:
                            tvdb_image = 'https://thetvdb.com/banners/'
                            tvdb_poster = 'https://thetvdb.com/banners/_cache/'
                            if py3: url = 'http://thetvdb.com/api/%s/series/%s/all/en.zip' % (base64.b64decode('MUQ2MkYyRjkwMDMwQzQ0NA==').decode('utf-8'), i['tvdb'])
                            else: url = 'http://thetvdb.com/api/%s/series/%s/all/en.zip' % ('MUQ2MkYyRjkwMDMwQzQ0NA=='.decode('base64'), i['tvdb'])
                            data = urllib2.urlopen(url, timeout=10).read()

                            zip = zipfile.ZipFile(StringIO(data))
                            result = zip.read('en.xml')
                            if py3: result = result.decode('utf-8')
                            zip.close()

                            result = result.split('<Episode>')
                            item = [x for x in result if '<EpisodeNumber>' in x and re.compile('<SeasonNumber>(.+?)</SeasonNumber>').findall(x)[0] != '0']
                            item2 = result[0]
                                    
                            num = [x for x,y in enumerate(item) if re.compile('<SeasonNumber>(.+?)</SeasonNumber>').findall(y)[0] == str(i['snum']) and re.compile('<EpisodeNumber>(.+?)</EpisodeNumber>').findall(y)[0] == str(i['enum'])][-1]
                            item = [y for x,y in enumerate(item) if x > num]
                            if item:
                                item = item[0]
                                try: premiered = re.findall(r'(FirstAired)>(.+?)</\1', item)[0][1]
                                except: 
                                    try:
                                        premiered = re.findall(r'(FirstAired)>(.+?)</\1', item)[1][1]
                                    except:
                                        premiered = ' no info about release date'
                                if premiered == '' or '-00' in premiered: premiered = '0'
                                premiered = replaceHTMLCodes(premiered)
                                
                                try: status = re.findall(r'(Status)>(.+?)</\1', item)[0][1]
                                except: status = ''
                                if status == '': status = 'Ended'
                                status = replaceHTMLCodes(status)
                                unaired = ''
                                #if status == 'Ended': pass
                                #if premiered == '0': raise Exception()
                                try:
                                    if int(re.sub('[^0-9]', '', str(premiered))) > int(re.sub('[^0-9]', '', str((datetime.datetime.utcnow() - datetime.timedelta(hours = 5)).strftime('%Y-%m-%d')))): unaired = 'true'
                                except: unaired = 'true'

                                try: poster = re.findall(r'(filename)>(.+?)</\1', item)[0][1]
                                except: poster = ''
                                if not poster == '': poster = tvdb_image + poster

                                try: studio = re.findall(r'(Network)>(.+?)</\1', item)[0][1]
                                except: studio = ''

                                try: genre = re.findall(r'(Genre)>(.+?)</\1', item)[0][1]
                                except: genre = ''
                                genre = [x for x in genre.split('|') if not x == '']
                                genre = ' / '.join(genre)

                                try: rating = re.findall(r'(Rating)>(.+?)</\1', item)[0][1]
                                except: rating = ''

                                try: votes = re.findall(r'(RatingCount)>(.+?)</\1', item)[0][1]
                                except: votes = ''

                                try: director = re.findall(r'(Director)>(.+?)</\1', item)[0][1]
                                except: director = ''
                                director = [x for x in director.split('|') if not x == '']
                                director = ' / '.join(director)
                                director = replaceHTMLCodes(director)

                                try: writer = re.findall(r'(Writer)>(.+?)</\1', item)[0][1]
                                except: writer = ''
                                writer = [x for x in writer.split('|') if not x == '']
                                writer = ' / '.join(writer)
                                writer = replaceHTMLCodes(writer)
                                
                                try: cast = re.findall(r'(GuestStars)>(.*?)</:?\s?\1', item)[0][1]
                                except: cast = ''
                                cast = [x for x in cast.split('|') if not x == '']
                                try: cast = [(x, '') for x in cast]
                                except: cast = []

                                try: plot = re.findall(r'(Overview)>(.+?)</\1', item)[0][1]
                                except: plot = ''
                                plot = replaceHTMLCodes(plot)
                                
                                try: title = re.findall(r'(EpisodeName)>(.+?)</\1', item)[0][1]
                                except: title = '0'
                                title = replaceHTMLCodes(title)

                                season = re.findall(r'(SeasonNumber)>(.+?)</\1', item)[0][1]
                                season = '%02d' % int(season)

                                episode = re.findall(r'(EpisodeNumber)>(.+?)</\1', item)[0][1]
                                episode = re.sub('[^0-9]', '', '%02d' % int(episode))
                                
                                tvshowtitle = i['tvshowtitle']
                                imdb, tvdb = i['imdb'], i['tvdb']
                                
                                year = i['year']
                                
                                
                                seelist.append({'imdb': imdb, 'tvdb': tvdb, 'tvshowtitle': tvshowtitle, 'year': year, 'snum': season, 'enum': episode, 'premiered': premiered, 'unaired': unaired, '_sort_key': max(i['_last_watched'], premiered), 'info': {'title': title, 'season': season, 'episode': episode, 'tvshowtitle': tvshowtitle, 'year': year, 'premiered': premiered, 'status': status, 'studio': studio, 'genre': genre, 'rating': rating, 'votes': votes, 'director': director, 'writer': writer, 'cast': cast, 'plot': plot, 'imdb': imdb, 'tvdb': tvdb, 'Poster': poster}})
                        except: pass
                #items = items[:100]
                import threading
                threads = []
                for i in items: threads.append(threading.Thread(name=i, target=items_list, args=(i, seelist,)))
                get_threads(threads, 'Deschidere', 0)
                seelist = sorted(seelist, key=lambda k: k['premiered'], reverse=True)
                #seelist = sorted(seelist, key=lambda k: k['_sort_key'], reverse=True)
                for show in seelist:
                    cm = []
                    nume = '%s - S%s E%s Data:%s' % (show.get('tvshowtitle'), show.get('snum'), show.get('enum'), show.get('premiered'))
                    nume = ('[COLOR red]%s[/COLOR]' if show.get('unaired') == 'true' else '%s') % nume
                    try:
                        titluc = show.get('tvshowtitle')
                        if show.get('snum'): titluc = '%s S%02d' % (titluc, int(show.get('snum')))
                        if show.get('enum'):
                            if self.context_trakt_search_mode != '2':
                                titluc = '%sE%02d' % (titluc, int(show.get('enum')))
                        cm.append(('Caută Variante', 'Container.Update(%s?action=searchSites&modalitate=edit&query=%s&Stype=%s)' % (sys.argv[0], quote(titluc), self.sstype)))
                        new_params['info'] = str(show.get('info'))
                        new_params['Stype'] = self.sstype
                        if self.context_trakt_search_mode == '0':
                            new_params['modalitate'] = 'edit'
                            new_params['query'] = quote(titluc)
                        else:
                            new_params['searchSites'] = 'cuvant'
                            new_params['cuvant'] = quote(titluc)
                    except: pass
                    if show.get('unaired') and not showunreleased:
                        continue
                    cm.append(self.CM('markTrakt', 'watched', params={'id': show.get('tvdb'), 'sezon' : show.get('snum'), 'episod': show.get('enum')}))
                    cm.append(self.CM('markTrakt', 'delete', params={'id': show.get('tvdb'), 'sezon' : show.get('snum'), 'episod': show.get('enum')}))
                    listings.append(self.drawItem(title = nume,
                                          action = 'searchSites',
                                          link = new_params,
                                          image = search_icon,
                                          contextMenu = cm))
        xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
        xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)
    
    def openIMDb(self, params={}):
        listings = []
        from . import imdb as i
        get = params.get
        action = get('actions') or ''
        count = get('count') or '50'
        start = get('start') or '1'
        title_type = unquote(get('title_type')) or ''
        sorting = get('sorting') or ''
        ascending = get('ascending') or ''
        groups = get('groups') or ''
        base_start = get('base_start') or ''
        genres = unquote(get('genres')) or ''
        years = unquote(get('years')) or ''
        methods = {'actions': action,
                   'title_type': title_type,
                   'count': count,
                   'start': start,
                   'sorting': sorting,
                   'ascending': ascending,
                   'genres': genres,
                   'years': years,
                   'groups': groups,
                   'base_start': base_start}
        sort = [('Popularity', 'moviemeter'),
                ('Alphabetical', 'alpha'),
                ('User Rating', 'user_rating'),
                ('Number of Votes', 'num_votes'),
                ('US Box Office', 'boxoffice_gross_us'),
                ('Runtime', 'runtime'),
                ('Year', 'year'),
                ('Release Date', 'release_date')]
        asc = [('Ascendent', 'asc'),
               ('Descendent', 'desc')]
        
        genre_list = ['Action', 'Adventure', 'Animation', 'Comedy',
                      'Crime', 'Drama', 'Sci-Fi', 'Fantasy', 'Thriller',
                      'Family', 'Romance', 'Short', 'Mystery', 'Sport',
                      'Horror', 'War', 'History', 'Reality-TV', 'Western',
                      'Game-Show', 'Documentary', 'Music', 'Musical', 'Biography',
                      'News', 'Talk-Show', 'Film-Noir']
        if not action:
            methods['actions'] = 'list_genres'
            methods['base_start'] = 'genuri'
            listings.append(self.drawItem(title = 'Genuri',
                                          action = 'openIMDb',
                                          link = methods,
                                          image = i.thumb))
            methods['actions'] = 'search'
            methods['base_start'] = 'tipuri'
            methods['title_type'] = 'mini_series'
            listings.append(self.drawItem(title = 'Mini Serii',
                                          action = 'openIMDb',
                                          link = methods,
                                          image = i.thumb))
            methods['title_type'] = 'tv_series'
            listings.append(self.drawItem(title = 'Seriale',
                                          action = 'openIMDb',
                                          link = methods,
                                          image = i.thumb))
            methods['title_type'] = 'movie'
            listings.append(self.drawItem(title = 'Filme',
                                          action = 'openIMDb',
                                          link = methods,
                                          image = i.thumb))
            methods['title_type'] = 'video'
            listings.append(self.drawItem(title = 'Video',
                                          action = 'openIMDb',
                                          link = methods,
                                          image = i.thumb))
            methods['groups'] = 'top_100'
            methods['title_type'] = ''
            methods['base_start'] = ''
            listings.append(self.drawItem(title = 'Top 100',
                                          action = 'openIMDb',
                                          link = methods,
                                          image = i.thumb))
            methods['groups'] = 'top_250'
            listings.append(self.drawItem(title = 'Top 250',
                                          action = 'openIMDb',
                                          link = methods,
                                          image = i.thumb))
            methods['groups'] = 'top_1000'
            listings.append(self.drawItem(title = 'Top 1000',
                                          action = 'openIMDb',
                                          link = methods,
                                          image = i.thumb))
        url = '%s/search/title/' % (i.base_url)
        url += '?count=%s' % (count)
        url += '&view=advanced'
        url += ('&groups=%s' % (groups)) if groups else ''
        url += ('&genres=%s' % (genres)) if genres else ''
        url += ('&release_date=%s' % (years)) if years else ''
        url += '&explore=title_type,genres'
        url += '&title_type=%s' % (title_type) if title_type else ''
        url += ('&sort=%s' % (sorting)) if sorting else ''
        url += (',%s' % (ascending)) if ascending else ''
        url += '&start=%s' % (start)

        if action == 'list_genres':
            methods['actions'] = 'search'
            for k in genre_list:
                methods['genres'] = k.lower()
                listings.append(self.drawItem(title = k,
                                          action = 'openIMDb',
                                          link = methods,
                                          image = i.thumb))
        if action == 'tipuri':
            items = i.get_types(url)
            methods['actions'] = 'search'
            for item in items:
                methods['title_type'] = item[0]
                listings.append(self.drawItem(title = '%s [COLOR lime]%s[/COLOR]' % (item[1], item[2]),
                                          action = 'openIMDb',
                                          link = methods,
                                          image = i.thumb))
        if action == 'genres':
            items = i.get_genres(url)
            methods['actions'] = 'search'
            for item in items:
                if genres and not item[0].lower() in genres:
                    methods['genres'] = '%s,%s' % (genres, item[0].lower())
                else:
                    methods['genres'] = item[0].lower()
                listings.append(self.drawItem(title = '%s [COLOR lime]%s[/COLOR]' % (item[0], item[1]),
                                          action = 'openIMDb',
                                          link = methods,
                                          image = i.thumb))
        if action == 'years':
            an = datetime.datetime.now().year
            methods['actions'] = 'search'
            while (an > 1929):
                methods['years'] = '%s-01-01,%s-12-31' % (str(an), str(an))
                listings.append(self.drawItem(title = str(an),
                                          action = 'openIMDb',
                                          link = methods,
                                          image = i.thumb))
                an -= 1
        if action == 'search':
            if not sorting:
                for sort_name, sort_method in sort:
                    methods['sorting'] = sort_method
                    listings.append(self.drawItem(title = sort_name,
                                          action = 'openIMDb',
                                          link = methods,
                                          image = i.thumb))
            if (not ascending) and sorting:
                for asc_name, asc_method in asc:
                    methods['ascending'] = asc_method
                    listings.append(self.drawItem(title = asc_name,
                                          action = 'openIMDb',
                                          link = methods,
                                          image = i.thumb))
            if sorting and ascending:
                if base_start == 'tipuri':
                    methods['actions'] = 'genres'
                    listings.append(self.drawItem(title = '[COLOR lime]Pe Genuri[/COLOR]',
                                          action = 'openIMDb',
                                          link = methods,
                                          image = i.thumb))
                if base_start == 'genuri':
                    methods['actions'] = 'tipuri'
                    listings.append(self.drawItem(title = '[COLOR lime]Pe tipuri[/COLOR]',
                                          action = 'openIMDb',
                                          link = methods,
                                          image = i.thumb))
                methods['actions'] = 'years'
                listings.append(self.drawItem(title = '[COLOR lime]Pe ani[/COLOR]',
                                        action = 'openIMDb',
                                        link = methods,
                                        image = i.thumb))
                items = i.get_list(url)
                for item in items:
                    cm = []
                    info = item
                    title = info.get('Title')
                    poster = info.get('Poster')
                    imdb = info.get('IMDBNumber')
                    cm.append(('Caută Variante', 'Container.Update(%s?action=searchSites&modalitate=edit&query=%s&Stype=%s)' % (sys.argv[0], quote(title), self.sstype)))
                    listings.append(self.drawItem(title = title,
                                          action = 'getMeta',
                                          link = {'getMeta': 'IMDb', 'imdb': imdb, 'nume': quote(title), 'info':info},
                                          image = poster,
                                          isFolder = 'False',
                                          contextMenu = cm))
                methods['actions'] = action
                methods['start'] = str(int(start) + 50)
                listings.append(self.drawItem(title = 'Next',
                                          action = 'openIMDb',
                                          link = methods,
                                          image = i.nextimage))
        xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
        xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)
    
    def openCinemagia(self, params={}):
        listings = []
        from . import cinemagia as c
        get = params.get
        meniu = unquote(get('meniu'))
        url = unquote(get('url'))
        if not get('meniu'):
            listings.append(self.drawItem(title = 'Liste utilizatori',
                                      action = 'openCinemagia',
                                      link = {'meniu': 'liste', 'url': '%s/liste/filme/?pn=1' % c.base_url},
                                      image = c.thumb))
            listings.append(self.drawItem(title = 'Filme',
                                      action = 'openCinemagia',
                                      link = {'meniu': 'all', 'url': '%s/filme/?pn=1' % c.base_url},
                                      image = c.thumb))
            listings.append(self.drawItem(title = 'Seriale',
                                      action = 'openCinemagia',
                                      link = {'meniu': 'all', 'url': '%s/seriale-tv/?pn=1' % c.base_url},
                                      image = c.thumb))
            listings.append(self.drawItem(title = 'Filme după țări',
                                      action = 'openCinemagia',
                                      link = {'meniu': 'tari', 'url': '%s/filme/?pn=1' % c.base_url},
                                      image = c.thumb))
            listings.append(self.drawItem(title = 'Filme după gen',
                                      action = 'openCinemagia',
                                      link = {'meniu': 'gen', 'url': '%s/filme/?pn=1' % c.base_url},
                                      image = c.thumb))
            listings.append(self.drawItem(title = 'Filme după ani',
                                      action = 'openCinemagia',
                                      link = {'meniu': 'ani', 'url': '%s/filme/?pn=1' % c.base_url},
                                      image = c.thumb))
            listings.append(self.drawItem(title = 'Seriale după țări',
                                      action = 'openCinemagia',
                                      link = {'meniu': 'tari', 'url': '%s/seriale-tv/?pn=1' % c.base_url},
                                      image = c.thumb))
            listings.append(self.drawItem(title = 'Seriale după gen',
                                      action = 'openCinemagia',
                                      link = {'meniu': 'gen', 'url': '%s/seriale-tv/?pn=1' % c.base_url},
                                      image = c.thumb))
            listings.append(self.drawItem(title = 'Seriale după ani',
                                      action = 'openCinemagia',
                                      link = {'meniu': 'ani', 'url': '%s/seriale-tv/?pn=1' % c.base_url},
                                      image = c.thumb))
            #self.drawItem('Căutare', 'openCinemagia', {'meniu': 'cautare', 'url': '%s/filme/?pn=1' % c.base_url}, image=c.thumb)
        if meniu == 'liste':
            listdirs = c.getliste(url)
            for order, imagine, link, nume, info in listdirs:
                listings.append(self.drawItem(title = nume,
                                      action = 'openCinemagia',
                                      link = {'meniu': 'listliste', 'info': info, 'url': link},
                                      image = imagine))
            if '/?pn=' in url:
                new = re.compile('\?pn=(\d+)').findall(url)
                nexturl = re.sub('\?pn=(\d+)', '?pn=' + str(int(new[0]) + 1), url)
                listings.append(self.drawItem(title = 'Next',
                                      action = 'openCinemagia',
                                      link = {'meniu': meniu, 'url': nexturl},
                                      image = c.nextimage))
        elif meniu == 'listliste':
            listmedia = c.listmovies(url, 'liste')
            for media in listmedia:
                cm = []
                getm = media.get
                cm.append(('Caută Variante', 'Container.Update(%s?action=searchSites&modalitate=edit&query=%s&Stype=%s)' % (sys.argv[0], quote(getm('info').get('Title')), self.sstype)))
                if getm('info').get('IMDBNumber'): self.getMetacm(url, getm('info').get('Title'), cm, getm('info').get('IMDBNumber'))
                else: self.getMetacm(url, getm('info').get('Title'), cm)
                #if self.torrenter == '1':
                    #cm.append(('Caută în Torrenter', torrmode(getm('info').get('Title'))))
                if self.youtube == '1':
                    cm.append(('Caută în Youtube', 'RunPlugin(%s?action=YoutubeSearch&url=%s)' % (sys.argv[0], quote(getm('info').get('Title')))))
                listings.append(self.drawItem(title = getm('label'),
                                      action = 'searchSites',
                                      link = {'searchSites': 'cuvant',
                                              'cuvant': getm('info').get('Title'),
                                              'info': getm('info')},
                                      image = getm('poster'),
                                      contextMenu = cm))
        elif meniu == 'tari' or meniu == 'gen' or meniu == 'ani':
            listtari = c.gettari(url, meniu)
            for number, legatura, nume in listtari:
                dats = {'meniu': 'sortare', 'url': legatura}
                if meniu == 'tari': dats.update({'tari': nume})
                else: dats.update({'genuri': nume})
                listings.append(self.drawItem(title = nume,
                                      action = 'openCinemagia',
                                      link = dats,
                                      image = c.thumb))
                #lists.append((nume,legatura,thumb,'listtari', {'tari': nume} if meniu == 'tari' else {'genuri': nume}))
        elif meniu == 'tarigen' or meniu == 'gentari':
            listtari = c.gettari(url, 'tari' if meniu == 'tarigen' else 'gen')
            for number, legatura, nume in listtari:
                listings.append(self.drawItem(title = nume,
                                      action = 'openCinemagia',
                                      link = {'meniu': 'listtari', 'url': legatura, 'info': {}},
                                      image = c.thumb))
                #log(nume)
                #lists.append((nume,legatura,thumb,'listtari', {}))
        elif meniu == 'sortare':
            sort = [('', 'Relevanță'),
                    ('asc', 'Popularitate'),
                    ('an', 'An'),
                    ('nota', 'Nota Cinemagia'),
                    ('nota_im', 'Nota IMDb'),
                    ('voturi', 'Voturi'),
                    ('pareri', 'Păreri')]
            for sortlink, sortnume in sort:
                dats = {'meniu': 'listtari', 'url': '%s%s/' % (url,sortlink) if sortlink else url, 'info': {}}
                if get('tari'): dats.update({'tari': unquote(get('tari'))})
                if get('genuri'): dats.update({'genuri': unquote(get('genuri'))})
                listings.append(self.drawItem(title = sortnume,
                                      action = 'openCinemagia',
                                      link = dats,
                                      image = c.thumb))
        elif meniu == 'listtari':
            listmedia = c.listmovies(url, 'filme')
            if get('tari'):
                nume = unquote(get('tari'))
                listings.append(self.drawItem(title = '[COLOR lime]Genuri din %s[/COLOR]' % nume,
                                      action = 'openCinemagia',
                                      link = {'meniu': 'gentari', 'url': url},
                                      image = c.thumb))
            if get('genuri'):
                nume = unquote(get('genuri'))
                listings.append(self.drawItem(title = '[COLOR lime]%s pe țări[/COLOR]' % nume,
                                      action = 'openCinemagia',
                                      link = {'meniu': 'tarigen', 'url': url},
                                      image = c.thumb))
            for media in listmedia:
                cm = []
                getm = media.get
                cm.append(('Caută Variante', 'Container.Update(%s?action=searchSites&modalitate=edit&query=%s&Stype=%s)' % (sys.argv[0], quote(getm('info').get('Title')), self.sstype)))
                if getm('info').get('IMDBNumber'): self.getMetacm(url, getm('info').get('Title'), cm, getm('info').get('IMDBNumber'))
                else: self.getMetacm(url, getm('info').get('Title'), cm)
                if self.youtube == '1':
                    cm.append(('Caută în Youtube', 'RunPlugin(%s?action=YoutubeSearch&url=%s)' % (sys.argv[0], quote(getm('info').get('Title')))))
                if getm('label') == 'Next' and not getm('info'):
                    if '/?&pn=' in url:
                        new = re.compile('\&pn=(\d+)').findall(url)
                        nexturl = re.sub('\&pn=(\d+)', '&pn=' + str(int(new[0]) + 1), url)
                    else: 
                        nexturl = url + '?&pn=2'
                    listings.append(self.drawItem(title = 'Next',
                                    action = 'openCinemagia',
                                    link = {'meniu': meniu, 'url': nexturl},
                                    image = c.nextimage))
                else:
                    listings.append(self.drawItem(title = getm('label'),
                                    action = 'searchSites',
                                    link = {'searchSites': 'cuvant',
                                            'cuvant': getm('info').get('Title'),
                                            'info': getm('info')},
                                    image = getm('poster'),
                                    contextMenu = cm))
        elif meniu == 'all':
            listmedia = c.listmovies(url, 'filme')
            for media in listmedia:
                cm = []
                getm = media.get
                cm.append(('Caută Variante', 'Container.Update(%s?action=searchSites&modalitate=edit&query=%s&Stype=%s)' % (sys.argv[0], quote(getm('info').get('Title')), self.sstype)))
                if getm('info').get('IMDBNumber'): self.getMetacm(url, getm('info').get('Title'), cm, getm('info').get('IMDBNumber'))
                else: self.getMetacm(url, getm('info').get('Title'), cm)
                if self.youtube == '1':
                    cm.append(('Caută în Youtube', 'RunPlugin(%s?action=YoutubeSearch&url=%s)' % (sys.argv[0], quote(getm('info').get('Title')))))
                if getm('label') == 'Next' and not getm('info'):
                    if '/?&pn=' in url:
                        new = re.compile('\&pn=(\d+)').findall(url)
                        nexturl = re.sub('\&pn=(\d+)', '&pn=' + str(int(new[0]) + 1), url)
                    else: 
                        nexturl = url + '?&pn=2'
                    listings.append(self.drawItem(title = 'Next',
                                    action = 'openCinemagia',
                                    link = {'meniu': meniu, 'url': nexturl},
                                    image = c.nextimage))
                else:
                    listings.append(self.drawItem(title = getm('label'),
                                    action = 'searchSites',
                                    link = {'searchSites': 'cuvant',
                                            'cuvant': getm('info').get('Title'),
                                            'info': getm('info')},
                                    image = getm('poster'),
                                    contextMenu = cm))
        xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
        xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)
    
    def setTorrent(self, params={}):
        get = params.get
        action = get('setTorrent')
        site = get('site')
        valoare = get('value')
        if action:
            secondaction = '%sseedtransmission' % site if action == 'seedmrsp' else '%sseedmrsp' % site
            actiune = '%s%s' % (site, action)
            if not getSettingAsBool(secondaction):
                __settings__.setSetting(actiune, value=valoare)
                showMessage('Succes', 'Operatiune realizată cu succes', forced=True)
            else: 
                showMessage('Interzis!', 'E deja activat seed cu %s' % ('MRSP' if action == 'seedtransmission' else 'Transmission'), forced=True)
            xbmc.executebuiltin("Container.Refresh")
    
    def disableSite(self, params={}):
        get = params.get
        action = get('disableSite')
        nume = get('nume')
        site = get('site')
        if not nume: nume = site
        if not site: site = nume
        if action == 'disable':
            __settings__.setSetting(id=nume, value='false')
            xbmc.executebuiltin("Container.Refresh")
        elif action == 'enable' or action == 'check':
            enable = True
            if action == 'check':
                dialog = xbmcgui.Dialog()
                ret = dialog.yesno(self.__scriptname__, '%s este dezactivat,\nVrei sa îl activezi?' % nume, yeslabel='Da', nolabel='Nu' )
                if ret == 1:
                    #self.disableSite({'disableSite': 'enable', 'site': site})
                    enable = True
                else: enable = False
            elif action == 'enable': 
                enable == True
            if enable:
                acces = '1'
                parola = __settings__.getSetting('parolasite')
                if parola and not parola == '0':
                    dialog = xbmcgui.Dialog()
                    d = dialog.input('Parola', type=xbmcgui.INPUT_NUMERIC)
                    if d == __settings__.getSetting('parolasite'): acces = '1'
                    else: acces = None
                if acces:
                    __settings__.setSetting(id=site, value='true')
                    #os.rename(os.path.join(self.disabled,'%s.py' % nume), os.path.join(self.scrapers,'%s.py' % nume))
                    xbmc.executebuiltin("Container.Refresh")
                else: ret = dialog.ok(self.__scriptname__, 'Ai introdus parola greșită')
        #elif action == 'check':
            
            #xbmc.executebuiltin('Notification(%s, "%s dezactivat")' % (self.__scriptname__, nume))
            
    
    def openMenu(self, params={}):
        listings = []
        get = params.get
        site = get('site')
        if site in streams.streamsites: imp = getattr(streams, site)
        else: imp = getattr(torrents, site)
        menu = imp().menu
        if menu:
            for name, url, switch, image in menu:
                params = {'site': site, 'link': url, 'switch': switch }
                listings.append(self.drawItem(title = name,
                                          action = 'OpenSite',
                                          link = params,
                                          image = image))
        xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
        xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)
        
    def getCats(self, params={}):
        listings = []
        categorii = {'Actiune': ['actiune', 'action', 'acţiune', 'acțiune'],
                 'Adulti': ['adult +18', 'erotic', 'erotice'],
                 'Aventura': ['aventura', 'aventuri', 'adventure', 'aventură'],
                 'Animatie': ['animatie', 'animation', 'animaţie', 'animație'],
                 'Biografic': ['biografie', 'biografic', 'biography'],
                 'Comedie': ['comedie', 'comedy'],
                 'Craciun': ['craciun', 'christmas'],
                 'Crima': ['crima', 'crime', 'crimă'],
                 'Dublat': ['dublate', 'dublat'],
                 'Drama': ['drama', 'dramă'],
                 'Familie': ['familie', 'family'],
                 'fara subtitrare': ['fara sub', 'fara subtitrare'],
                 'Film noir': ['film-noir', 'film noir'],
                 'Horror': ['horror', 'groaza', 'groază'],
                 'Istoric' : ['istoric', 'istorice', 'istorie', 'history'],
                 'Muzical': ['musical', 'muzical', 'muzicale', 'muzica (musical)', 'music'],
                 'Mister': ['mister', 'mystery'],
                 'Mitologic': ['mitologic', 'mythological'],
                 'Psihologic': ['psihologice', 'psihologic', 'psychological'],
                 'Reality': ['reality', 'reality-tv'],
                 'Sci-Fi': ['sci-fi', 'science – fiction (sf)', 'sf', 's-f', 'sci-fi &amp; fantasy', 'science fiction (sf)'],
                 'Romantic': ['romantic', 'romantice', 'romance'],
                 'Documentar': ['documentar', 'documentare', 'documentary'],
                 'Fantezie': ['fantastic', 'fantezie', 'fantasy'],
                 'Seriale': ['seriale', 'seriale online', 'tv show'],
                 'Romanesc': ['romanesti', 'romanesc', 'filme româneşti'],
                 'Thriller': ['thriller', 'suspans'],
                 'Razboi' : ['war', 'razboi', 'război']}
        cat_list = {}
        all_links = []
        result = thread_me(__all__, params, 'categorii')
        try: resultitems = result.iteritems()
        except: resultitems = result.items()
        for key, value in resultitems:
            all_links.extend(value)
        for cat in all_links:
            for j in categorii:
                for k in categorii.get(j):
                    if cat[0].lower() == k:
                        cat[0] = j
            if cat[0].lower() in cat_list:
                cat_list[cat[0].lower()].append(cat)
            else:
                cat_list[cat[0].lower()] = []
                cat_list[cat[0].lower()].append(cat)
        for nume in sorted(cat_list):
            cat_plots = []
            for cat_plot in cat_list[nume]:
                if cat_plot[2].get('site') in streams.streamsites:
                    cat_plots.append(streams.streamnames.get(cat_plot[2].get('site')).get('nume'))
                elif cat_plot[2].get('site') in torrents.torrentsites:
                    cat_plots.append(torrents.torrnames.get(cat_plot[2].get('site')).get('nume'))
            params = {'categorie': quote(json.dumps(cat_list[nume])), 'info': {'Plot': 'Categorie găsită pe: \n%s' % (", ".join(cat_plots))}}
            listings.append(self.drawItem(title = nume.capitalize(),
                                    action = 'openCat',
                                    link = params,
                                    image = cat_icon))
        xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
        xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)
    
    def openCat(self, params={}):
        listings = []
        threads = []
        all_links = []
        nextlink = []
        parms = {}
        get = params.get
        if get('categorie'):
            categorie = json.loads(unquote(get('categorie')))
            for nume, action, pars, imagine, cm in categorie:
                threads.append(pars.get('site'))
                parms[pars.get('site')] = pars
            result = thread_me(threads, parms, 'categorie')
            try: resultitems = result.iteritems()
            except: resultitems = result.items()
            for key, value in resultitems:
                all_links.extend(value)
            for nume, action, params, imagine, cm in sorted(all_links, key=lambda x: re.sub('\[.*?\].*?\[.*?\]', '', x[0]).lstrip(' ')):
                if nume == 'Next':
                    nextlink.append([nume, 'OpenSite', params, imagine, cm])
                else:
                    if params.get('site') in streams.streamsites:
                        site = streams.streamnames.get(params.get('site')).get('nume')
                    elif params.get('site') in torrents.torrentsites:
                        site = torrents.torrnames.get(params.get('site')).get('nume')
                    listings.append(self.drawItem(title = '[COLOR red]%s:[/COLOR] %s' % (site, nume),
                                    action = action,
                                    link = params,
                                    image = imagine,
                                    contextMenu = cm))
            if len(nextlink) > 0:
                listings.append(self.drawItem(title = 'Next',
                                    action = 'openCat',
                                    link = {'categorie': quote(json.dumps(nextlink))},
                                    image = next_icon))
        xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
        xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)
        
    def getMeta(self, params={}):
        metadata = params.get('getMeta')
        import unicodedata
        import codecs
        from resources.lib import PTN
        nameorig = re.sub('\[COLOR.+?\].+?\[/COLOR\]|\[.*?\]', '', unquote(params.get('nume')))
        parsed = PTN.parse(nameorig.strip())
        nume = parsed.get('title') or nameorig.strip()
        an = parsed.get('year') or ''
        imdb = params.get('imdb') or ''
        sezon = parsed.get('season') or ''
        
        if params.get('modalitate') == 'edit':
            getquery = nume
            if getquery:
                try:
                    if sezon:
                        getquery = '%s S%02d' % (getquery, int(sezon))
                except: pass
            keyboard = xbmc.Keyboard(getquery)
            keyboard.doModal()
            if (keyboard.isConfirmed() == False): return
            keyword = keyboard.getText()
            if len(keyword) == 0: return
            else: nume = keyword

        content = ''
        if metadata == "IMDb":
            #nume = '%s %s' % (nume, an) if an else nume
            base_url = 'https://www.imdb.com'
            lists = []
            headers={'Accept-Language': 'ro-RO'}
            if imdb: 
                urls = '%s/title/%s/' % (base_url, imdb if imdb.startswith('tt') else 'tt%s' % imdb)
                content = fetchData(urls, headers=headers)
            else:
                url = '%s/find?q=%s&s=tt' % (base_url, nume)
                regex_search = '''findResult.+?src=.+?href="(.+?)"(?:.+?)?>(.+?)</td'''
                content = fetchData(url, headers=headers)
                if content:
                    match = re.findall(regex_search, content, re.DOTALL)
                    if match:
                        for legatura, name in match:
                            legatura = '%s%s' % (base_url, legatura)
                            name = striphtml(replaceHTMLCodes(ensure_str(name)))
                            lists.append((name, legatura))
                if len(lists) > 0:
                    if len(lists) > 1:
                        dialog = xbmcgui.Dialog()
                        sel = dialog.select("Mai multe disponibile", [item[0] for item in lists])
                    else: sel = 0
                    if sel >= 0:
                        content = fetchData(lists[sel][1], headers=headers)
                    else: 
                        content = ''
            if content:
                try:
                    imdb_json = '''<script id="__NEXT_DATA__" type="application/json">(.*?)</script>'''
                    try: s = re.findall(imdb_json, content, re.DOTALL | re.IGNORECASE)
                    except: s = re.findall(imdb_json, content.decode('utf-8'), re.DOTALL | re.IGNORECASE)
                    info_json = json.loads(''.join(s))
                    if info_json.get('props').get('pageProps').get('findPageMeta'):
                        titlesinfo = info_json.get('props').get('pageProps').get('titleResults')
                        if titlesinfo:
                            titles = titlesinfo.get('results')
                            if len(titles) > 0:
                                if len(titles) > 1:
                                    dialog = xbmcgui.Dialog()
                                    sel = dialog.select("Mai multe disponibile", ['%s %s %s' % (item.get('titleNameText'), item.get('titleReleaseText'), item.get('imageType')) for item in titles])
                                else: sel = 0
                                if sel >= 0:
                                    content = fetchData('%s/title/%s/' % (base_url, titles[sel].get('id')), headers=headers)
                                else: 
                                    content = ''
                except: pass
            if content:
                #from . import metaimdb as meta
                #disp = meta.window()
                #disp.get_n(content,nameorig,imdb)
                #disp.doModal()
                #del disp
                transPath = xbmcvfs.translatePath if py3 else xbmc.translatePath
                try: addonpath = transPath(ROOT.decode('utf-8'))
                except: addonpath = transPath(ROOT)
                
                from resources.lib.windows.video_info import VideoInfoXML
                window = VideoInfoXML('video_info.xml', addonpath, 'Default', content=content, nameorig=nameorig, imdb=imdb)
                action, code = window.run()
                del window
                if action == 'search_name':
                    #self.searchSites(params={'modalitate': 'edit', 'query': code})
                    #xbmc.executebuiltin("ActivateWindow(busydialog)")
                    xbmc.executebuiltin('Container.Update(%s?action=searchSites&modalitate=edit&query=%s)' % (sys.argv[0], code))
                    #xbmc.executebuiltin("Dialog.Close(busydialog)")
                
        elif metadata == "TMdb":
            jdef = {}
            results_number = 1
            if not imdb:
                regex = 'S\d+E\d+|ep[. ]+\d+|sezon|\d+\s+x\s+\d+'
                t = nume
                if ('serial' in nume.lower()) or re.search(regex, nume, flags=re.IGNORECASE) or sezon:
                    jsonpage = fetchData('https://api.themoviedb.org/3/search/tv?api_key=%s&query=%s&page=1&%s' % (tmdb_key(), quote(nume), (('first_air_date_year=' + str(an)) if an else '')))
                    jdef = json.loads(jsonpage)
                    if jdef.get('total_results') == 0:
                        jsonpage = fetchData('https://api.themoviedb.org/3/search/tv?api_key=%s&query=%s&page=1&' % (tmdb_key(), quote(nume)))
                        jdef = json.loads(jsonpage)
                    jdef['gen'] = 'serial'
                else:
                    #log('1: %s\n2: %s\n3: %s\n4: %s\n5: %s' % (t, y, nume, link, nume2))
                    try:
                        g = re.split('\d{4}|film|HD|online[\s]+gratis',nume,1)[0]
                        if not g: g = re.split('film|HD',nume,1)[0]
                        t = g
                    except: pass
                    if an:
                        jdef = fetchData('http://api.themoviedb.org/3/search/movie?api_key=%s&query=%s&year=%s' % (tmdb_key(), quote(t), an), rtype='json')
                    else:
                        jdef = fetchData('http://api.themoviedb.org/3/search/movie?api_key=%s&query=%s' % (tmdb_key(), quote(t)), rtype='json')
                    if jdef.get('total_results') == 0:
                        jdef = fetchData('http://api.themoviedb.org/3/search/movie?api_key=%s&query=%s' % (tmdb_key(), quote(nameorig)), rtype='json')
                        if jdef.get('total_results') == 0:
                            jdef = fetchData('https://api.themoviedb.org/3/search/tv?api_key=%s&query=%s&page=1&%s' % (tmdb_key(), quote(t), (('first_air_date_year=' + str(an)) if an else '')), rtype='json')
                            jdef['gen'] = 'serial'
                results_number = jdef.get('total_results') or 0
            else:
                jdef = json.loads(fetchData('https://api.themoviedb.org/3/movie/%s?append_to_response=trailers,credits&api_key=%s' % (imdb, tmdb_key())))
                if str(jdef.get('status_code')) == '34':
                    try:
                        jdef = json.loads(fetchData('https://api.themoviedb.org/3/find/%s?api_key=%s&language=en-US&external_source=imdb_id' % (imdb, tmdb_key()))).get('tv_results')[0]
                    except: pass
            if int(results_number) > 0:
                if jdef.get('results') and len(jdef.get('results')) > 1:
                    dialog = xbmcgui.Dialog()
                    sel = dialog.select("Mai multe disponibile", ['%s - %s' % ((item.get('name') or item.get('title')), (item.get('release_date') or item.get('first_air_date'))) for item in jdef.get('results')])
                else: sel = 0
                if sel >= 0:
                    if jdef.get('gen') == 'serial':
                        jdef = json.loads(fetchData('https://api.themoviedb.org/3/tv/%s?append_to_response=trailers,credits&api_key=%s' % (jdef.get('results')[sel].get('id'), tmdb_key())))
                        jdef['gen'] = 'serial'
                    else:
                        try:
                            jdef = json.loads(fetchData('https://api.themoviedb.org/3/movie/%s?append_to_response=trailers,credits&api_key=%s' % (jdef.get('results')[sel].get('id'), tmdb_key())))
                        except: pass
            if jdef:
                from . import metatmdb as meta
                disp = meta.window()
                disp.get_n(nameorig,jdef)
                disp.doModal()
                del disp
                
        
    def getMetacm(self, url, nume, cm, imdb=None):
        metadata = __settings__.getSetting('metadata')
        try:
            if metadata == 'Ambele':
                cm.append(self.CM('getMeta', 'IMDb', url=url, nume=nume, imdb=imdb))
                cm.append(self.CM('getMeta', 'TMdb', url=url, nume=nume, imdb=imdb))
            else: cm.append(self.CM('getMeta', metadata, url=url, nume=nume, imdb=imdb))
        except BaseException as e: log(u"getMetacm ##Error: %s" % str(e))
    
    def OpenSite(self, params={}, handle=None, limit=None, all_links=[], new=None):
        listings = []
        all_links_new=[]
        #xbmcplugin.setContent(int(sys.argv[1]), 'movies')
        get = params.get
        switch = get('switch')
        link = unquote(get('link'))
        nume = get('nume')
        site = get('site')
        torraction = get('torraction')
        info = unquote(get('info')) if get('info') else None
        if switch == 'play' or switch == 'playoutside':
            dp = xbmcgui.DialogProgressBG()
            dp.create(self.__scriptname__, 'Starting...')
            liz = xbmcgui.ListItem(nume)
            if info: 
                info = eval(info)
                liz.setInfo(type="Video", infoLabels=info); liz.setArt({'thumb': info.get('Poster') or os.path.join(__settings__.getAddonInfo('path'), 'resources', 'media', 'video.png')})
            else: liz.setInfo(type="Video", infoLabels={'Title':unquote(nume)})
            dp.update(50, message='Starting...')
            try:
                params.update({'info' : info})
                import resolveurl as urlresolver
                play_link = urlresolver.resolve(link)
                if not play_link: 
                    try:
                        from resources.lib import requests
                        headers = {'User-Agent': randomagent()}
                        red = requests.head(link, headers=headers, allow_redirects=False)
                        try: link = red.headers['Location'] + '|Cookie='+ quote(red.headers['Set-Cookie'])
                        except: link = red.headers['Location']
                    except:pass
                    play_link = link
                dp.update(100, message='Starting...')
                xbmc.sleep(100)
                dp.close()
                player().run(play_link, liz, params, link)
                #xbmc.Player().play(hmf.resolve(), liz, False)
            except Exception as e:
                dp.update(0)
                dp.close()
                showMessage("Eroare", "%s" % e)
                #xbmcplugin.endOfDirectory(handle=int(sys.argv[1]), succeeded=True)
            #xbmc.executebuiltin('Action(Back)')
        #elif switch == 'playoutside':
            #log('from outside MRSP')
        else:
            if switch == 'torrent_links':
                torraction = torraction if torraction else ''
                menu = getattr(torrents, site)().parse_menu(link, switch, info, torraction=torraction)
            else:
                if site in streams.streamsites:
                    menu = getattr(streams, site)().parse_menu(unquot(link), switch, info, limit=limit)
                elif site in torrents.torrentsites:
                    menu = getattr(torrents, site)().parse_menu(link, switch, info, limit=limit)
                else: menu = ''
            isfolder = True
            if menu:
                for datas in menu:
                    isfolder = True
                    landing = None
                    subtitrare = None
                    cm = []
                    addcm = None
                    nume = datas.get('nume')
                    url = datas.get('legatura')
                    imagine = datas.get('imagine')
                    switch = datas.get('switch')
                    infoa = datas.get('info')
                    #if switch == 'torrent_links':
                        #isfolder = False
                    addcm = datas.get('cm')
                    if switch == 'get_links':
                        isfolder = False
                    else: landing = datas.get('landing')
                    subtitrare = datas.get('subtitrare')
                    if addcm:
                        cm.extend(addcm)
                    
                    params = {'site': get('site'), 'link': url, 'switch': switch, 'nume': nume, 'info': infoa, 'favorite': 'check', 'watched': 'check'}
                    if not nume == 'Next':
                        if infoa:
                            if not isinstance(infoa, dict):
                                infoa = eval(str(infoa))
                            if infoa.get('imdb'): self.getMetacm(url, nume, cm, infoa.get('imdb'))
                            else: self.getMetacm(url, nume, cm)
                            cm.append(('Caută Variante', 'Container.Update(%s?action=searchSites&modalitate=edit&query=%s&Stype=%s)' % (sys.argv[0], quote(nume), self.sstype)))
                        if self.favorite(params):
                            nume = '[COLOR yellow]Fav[/COLOR] - %s' % nume
                            cm.append(self.CM('favorite', 'delete', url, nume))
                        else: cm.append(self.CM('favorite', 'save', url, nume, str(params)))
                        if self.watched(params):
                            if not isinstance(params['info'], dict):
                                params['info'] = eval(str(params['info']))
                            if params['info']:
                                #log(params)
                                params['info'].update({'playcount': 1, 'overlay': 7})
                            cm.append(self.CM('watched', 'delete', url))
                        else:
                            try:
                                if not isinstance(params['info'], dict):
                                    params['info'] = eval(str(params['info']))
                                #params['info'].update({'playcount': 0, 'overlay': 6})
                            except: pass
                            cm.append(self.CM('watched', 'save', landing if landing else url, params=str(params)))
                        #if self.torrenter == '1':
                            ##cm.append(('Caută în Torrenter', 'RunPlugin(plugin://plugin.video.torrenter/?action=searchWindow&mode=search&query=%s)' % (unquote(nume))))
                            #cm.append(('Caută în Torrenter', torrmode(nume)))
                        if self.youtube == '1':
                            cm.append(('Caută în Youtube', 'RunPlugin(%s?action=YoutubeSearch&url=%s)' % (sys.argv[0], quote(nume))))
                        if landing: params.update({'landing': landing})
                        if subtitrare: params.update({'subtitrare': subtitrare})
                        
                    #if switch == 'get_links': self.drawItem(nume, 'OpenSite', params, isFolder=isfolder, image=imagine, contextMenu=cm)
                    if handle: 
                        if handle == '1': 
                            if get('site') in streams.streamsites:
                                name = streams.streamnames.get(get('site')).get('nume')
                            elif get('site') in torrents.torrentsites:
                                name = torrents.torrnames.get(get('site')).get('nume')
                            if not new:
                                all_links.append(['[COLOR red]%s:[/COLOR] %s' % (name, nume), 'OpenSite', params, imagine, cm])
                            else:
                                all_links_new.append(['[COLOR red]%s:[/COLOR] %s' % (name, nume), 'OpenSite', params, imagine, cm])
                        elif handle == '2': 
                            if not new: all_links.append([nume, 'OpenSite', params, imagine, cm])
                            else : all_links_new.append([nume, 'OpenSite', params, imagine, cm])
                    else: 
                        listings.append(self.drawItem(title = nume,
                                          action = 'OpenSite',
                                          link = params,
                                          image = imagine,
                                          contextMenu = cm,
                                          isFolder = isfolder,
                                          isPlayable = True if switch == 'get_links' else True))
                if not handle:
                    xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
                    xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)
            else:
                if not handle:
                    xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
                    xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)
        if new:
            return all_links_new
    
    def recents(self, params):
        rtype = __all__
        listings = []
        all_links = []
        #if __settings__.getSetting('searchtype') == 'Ambele':
            #allnew = __all__
            #allnew.extend(__alltr__)
        #elif __settings__.getSetting('searchtype') == 'Torrent':
            #allnew = __alltr__
        #else: allnew = __all__
        #if stype == 'torrs': allnew = __alltr__
        if params.get('Rtype') == 'torrs': rtype = __alltr__
        result = thread_me(rtype, params, 'recente')
        try: resultitems = result.iteritems()
        except: resultitems = result.items()
        for key, value in resultitems:
            all_links.extend(value)
        patt = re.compile(r'\[S/L: (\d+)')
        if params.get('Rtype') == 'torrs':
            if params.get('Sortby') == 'seed':
                all_links.sort(key=lambda x: int(patt.search(x[0].replace(',','').replace('.','')).group(1)) if patt.search(x[0]) else 0, reverse=True)
            if params.get('Sortby') == 'size':
                all_links.sort(key=lambda x: float(x[2].get('info').get('Size')) if x[2].get('info').get('Size') else float(99999), reverse=True)
        if params.get('Sortby') == 'name':
            all_links.sort(key=lambda x: re.sub('\[.*?\].*?\[.*?\](?:\s+)?', '', ensure_str(x[0])).strip())
        for nume, action, params, imagine, cm in all_links:
            if not re.sub('\[.*?\].*?\[.*?\]', '', nume).lstrip(' ') == 'Next': 
                listings.append(self.drawItem(title = nume,
                                    action = action,
                                    link = params,
                                    image = imagine,
                                    contextMenu = cm))
        xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
        xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)
    
    def favorite(self, params):
        listings = []
        get = params.get
        action = get('favorite')
        page = get('page') or '1'
        if action == "save":
            save_fav(unquote(get('nume')), unquote(get('favoritelink')), unquote(get('detalii')), get('norefresh'))
        elif action == "check":
            check_link = '%s' % (get('link') or get('landing'))
            check = get_fav(unquote(check_link))
            if check: return True
            else: return False
        elif action == "delete":
            del_fav(unquote(get('favoritelink')), get('norefresh'))
        elif action == "print":
            favs = get_fav(page=int(page))
            if favs:
                for fav in favs:
                    cm = []
                    if fav[1]:
                        fav_info = eval(fav[3])
                        self.getMetacm(fav_info.get('link'), fav_info.get('nume'), cm)
                        if self.watched({'watched': 'check', 'link': fav[1]}):
                            try: fav_info['info'].update({'playcount': 1, 'overlay': 7})
                            except: 
                                fav_info['info'] = eval(str(fav_info['info']))
                                fav_info['info'].update({'playcount': 1, 'overlay': 7})
                            #log(fav_info['info'])
                            cm.append(self.CM('watched', 'delete', fav_info.get('link')))
                        else:
                            fav_info['watched'] = 'check'
                            cm.append(self.CM('watched', 'save', fav_info.get('link'), params=str(fav_info)))
                        cm.append(self.CM('favorite', 'delete', fav[1], fav[2]))
                        cm.append(('Caută Variante', 'Container.Update(%s?action=searchSites&modalitate=edit&query=%s&Stype=%s)' % (sys.argv[0], quote(fav[2]), self.sstype)))
                        #if self.torrenter == '1':
                            #cm.append(('Caută în Torrenter', torrmode(fav[1])))
                        if self.youtube == '1':
                            cm.append(('Caută în Youtube', 'RunPlugin(%s?action=YoutubeSearch&url=%s)' % (sys.argv[0], quote(fav[2]))))
                        names = fav_info.get('site')
                        if names in torrents.torrentsites: name = torrents.torrnames.get(names).get('nume')
                        elif names in streams.streamsites: name = streams.streamnames.get(names).get('nume')
                        else: name = 'indisponibil'
                        listings.append(self.drawItem(title = '[COLOR red]%s:[/COLOR] %s' % (name, fav[2]),
                                    action = 'OpenSite',
                                    link = fav_info,
                                    contextMenu = cm))
                page = int(page) + 1
                listings.append(self.drawItem(title = '[COLOR lime]Next[/COLOR]',
                                    action = 'favorite',
                                    link = {'site': 'site', 'favorite': 'print', 'page': '%s' % page},
                                    image = fav_icon))
            #listMask = '[[COLOR red]AsiaFanInfo.net:[/COLOR]]'
            #xbmcplugin.addSortMethod(int(sys.argv[1]), xbmcplugin.SORT_METHOD_UNSORTED)
            #xbmcplugin.addSortMethod(int(sys.argv[1]), xbmcplugin.SORT_METHOD_LABEL, label2Mask="%X")
            #xbmcplugin.addSortMethod(int(sys.argv[1]), xbmcplugin.SORT_METHOD_FULLPATH, label2Mask="%X")
            #xbmcplugin.addSortMethod(int(sys.argv[1]), xbmcplugin.SORT_METHOD_TITLE, label2Mask="D")
            #try:
                #p_handle = int(sys.argv[1])
                #xbmcplugin.addSortMethod(p_handle, xbmcplugin.SORT_METHOD_UNSORTED)
                #xbmcplugin.addSortMethod(p_handle, xbmcplugin.SORT_METHOD_SIZE)
                ##xbmcplugin.addSortMethod(p_handle, xbmcplugin.SORT_METHOD_LABEL)
                ##xbmcplugin.addSortMethod(p_handle, xbmcplugin.SORT_METHOD_TITLE)
                ##xbmc.executebuiltin("Container.SetSortMethod(%s)" % str(1))
                ##xbmc.executebuiltin("Container.SetSortDirection()")
            #except: pass
            xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
            xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)
    
    def watched(self, params):
        listings = []
        get = params.get
        action = get('watched')
        page = get('page') or '1'
        elapsed = get('elapsed')
        total = get('total')
        if action == 'save':
            save_watched(unquote(get('watchedlink')), unquote(get('detalii')), '1' if get('norefresh') else None , elapsed, total)
        elif action == 'delete':
            delete_watched(unquote(get('watchedlink')))
        elif action == 'check':
            return get_watched(unquote(get('link')))
        elif action == 'list':
            watch = list_watched(int(page))
            resume = list_partial_watched(int(page))
            if resume:
                try: watch.extend(resume)
                except: pass
            if watch:
                if resume: watch = sorted(watch, key=lambda x: x[4], reverse=True)
                for watcha in watch:
                    try:
                        if watcha[1]:
                            cm = []
                            try:
                                if watcha[4]:
                                    watchtime = time.strftime('%d-%m-%Y %H:%M:%S', time.localtime(int(watcha[4])))
                                else: watchtime = ''
                            except: watchtime = ''
                            try: watcha_info = eval(watcha[2])
                            except: watcha_info = eval(unquote(watcha[2]))
                            if not isinstance(watcha_info.get('info'), dict):
                                watcha_info['info'] = eval(str(watcha_info.get('info')))
                            wtitle = watcha_info.get('info').get('Title')
                            wnume = watcha_info.get('nume') or wtitle
                            wtvshow = watcha_info.get('info').get('TVShowTitle')
                            watcha_ii = ('%s - %s' % (wtvshow, wtitle)) if wtvshow else (wtitle if wtitle == wnume else '%s - %s' % (wtitle, wnume))
                            self.getMetacm('%s' % (watcha_info.get('link') or watcha_info.get('landing')), watcha_ii, cm)
                            cm.append(self.CM('watched', 'delete', watcha[1]))
                            cm.append(('Caută Variante', 'Container.Update(%s?action=searchSites&modalitate=edit&query=%s&Stype=%s)' % (sys.argv[0], quote(watcha_ii), self.sstype)))
                            if self.favorite(watcha_info):
                                watcha_ii = '[COLOR yellow]Fav[/COLOR] - %s' % watcha_ii
                                cm.append(self.CM('favorite', 'delete', '%s' % (watcha_info.get('link') or watcha_info.get('landing')), watcha_ii))
                            else: cm.append(self.CM('favorite', 'save', '%s' % (watcha_info.get('link') or watcha_info.get('landing')), watcha_ii, str(watcha_info)))
                            names = watcha_info.get('site')
                            if names in torrents.torrentsites: name = torrents.torrnames.get(names).get('nume')
                            elif names in streams.streamsites: name = streams.streamnames.get(names).get('nume')
                            else: name = ''
                            if len(watcha) == 6:
                                partialdesc = '[COLOR yellow]%s din %s[/COLOR] ' % (datetime.timedelta(seconds=int(float(watcha[3]))), datetime.timedelta(seconds=int(float(watcha[5]))))
                                try: watcha_info['info']['seek_time'] = watcha[3]
                                except: pass
                            else: partialdesc = ''
                            try: 
                                watcha_info['info']['played_file'] = re.findall('Played file\:\s+(.+?)\s\\n', watcha_info.get('info').get('Plot'))[0]
                            except: pass
                            listings.append(self.drawItem(title = '%s%s[COLOR red]%s:[/COLOR] %s' % (partialdesc,
                                                                                             (('%s ' % watchtime) if watchtime else ''),
                                                                                             name,
                                                                                             watcha_ii),
                                                         action = 'OpenSite',
                                                         link = watcha_info,
                                                         contextMenu = cm))
                    except: pass
                page = int(page) + 1
                listings.append(self.drawItem(title = '[COLOR lime]Next[/COLOR]',
                                    action = 'watched',
                                    link = {'watched': 'list', 'page': '%s' % page},
                                    image = seen_icon))
            xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
            xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)
    
    def openSettings(self, params={}):
        if params.get('script') == 'torrent2http':
            xbmcaddon.Addon(id='script.module.torrent2http').openSettings()
        else:
            __settings__.openSettings()
    
    def openTorrent(self, params={}):
        listings = []
        get = params.get
        info = unquote(get("info"),'')
        try:
            info = eval(info) if info else {}
        except: pass
        site = unquote(get("site"),'')
        infog = info
        info = str(info)
        url = unquote(get("url"),None)
        if not url: url = unquote(get("link"),None)
        files = unquote(get("files"),'')
        clickactiontype = __settings__.getSetting('clickactiontype')
        if not files:
            from resources.lib.mrspplayer import MRPlayer
            filename, files = MRPlayer().start(url,browse=True)
        if files:
            if py3:
                if isinstance(files, str):
                    files = eval(files)
            else:
                if isinstance(files, basestring):
                    files = eval(files)
            #log(files)
            transPath = xbmcvfs.translatePath if py3 else xbmc.translatePath
            try: addonpath = transPath(ROOT.decode('utf-8'))
            except: addonpath = transPath(ROOT)
            
            from resources.lib.windows.browse_torrents import BrowseTorrentsXML
            window = BrowseTorrentsXML('browse_torrents.xml', addonpath, 'Default', files=files, info=info, link=url, site=site)
            action, identifier = window.run()
            del window
            if action == 'Play':
                pars = {'Turl': quote(url),
                        'Tid': identifier,
                        'info': quote(info),
                        'download': 'true' if clickactiontype == '3' else 'false',
                        'Tsite': site}
                openTorrent(pars)
    
    def openTorrenterSettings(self, params={}):
        xbmcaddon.Addon(id='plugin.video.torrenter').openSettings()
        
    def openResolverSettings(self, params={}):
        xbmcaddon.Addon(id='script.module.resolveurl').openSettings()
    
    def searchSites(self, params={}):
        listings = []
        get = params.get
        if get('Stype'): stype = get('Stype')
        else: 
            stype = self.sstype
            #stype = 'site'
        if get('landsearch'): landing = get('landsearch')
        else: landing = None
        if get('searchSites') == 'delete':
            del_search(unquote(get('cuvant')))
        elif get('searchSites') == 'edit':
            keyboard = xbmc.Keyboard(unquote(get('cuvant')))
            keyboard.doModal()
            #if (keyboard.isConfirmed() == False): return
            keyword = keyboard.getText()
            if len(keyword) > 0:
                save_search(keyword)
                xbmc.executebuiltin("Container.Refresh")
        elif get('searchSites') == 'noua':
            keyboard = xbmc.Keyboard('')
            keyboard.doModal()
            #if (keyboard.isConfirmed() == False): return
            keyword = keyboard.getText()
            if len(keyword) > 0: self.get_searchsite(keyword, landing, stype=stype)
        elif get('searchSites') == 'cuvant':
            self.get_searchsite(unquote(get('cuvant')), landing, stype=stype)
        elif get('searchSites') == 'favorite':
            favs = get_fav()
            nofav = '1'
            if favs:
                listings = []
                for fav in favs[::-1]:
                    cm = []
                    if fav[0]:
                        fav_info = eval(fav[2])
                        if unquote(get('cuvant')).strip() in fav_info.get('nume').strip():
                            nofav = '0'
                            cm.append(self.CM('searchSites', 'cuvant', cuvant=unquote(get('cuvant')), container='1'))
                            self.getMetacm(fav_info.get('link'), fav_info.get('nume'), cm)
                            if self.watched({'watched': 'check', 'link': fav[0]}):
                                try: fav_info['info'].update({'playcount': 1, 'overlay': 7})
                                except: 
                                    fav_info['info'] = eval(str(fav_info['info']))
                                    fav_info['info'].update({'playcount': 1, 'overlay': 7})
                                cm.append(self.CM('watched', 'delete', fav_info.get('link')))
                            else:
                                fav_info['watched'] = 'check'
                                cm.append(self.CM('watched', 'save', fav_info.get('link'), params=str(fav_info)))
                            cm.append(self.CM('favorite', 'delete', fav[0], fav[1]))
                            names = fav_info.get('site')
                            if names in torrents.torrentsites: name = torrents.torrnames.get(names).get('nume')
                            elif names in streams.streamsites: name = streams.streamnames.get(names).get('nume')
                            else: name = 'indisponibil'
                            listings.append(self.drawItem(title = '[COLOR red]%s:[/COLOR] %s' % (name, fav[1]),
                                    action = 'OpenSite',
                                    link = fav_info,
                                    contextMenu = cm))
                            xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
                            
            if nofav == '1': self.get_searchsite(unquote(get('cuvant')), None, stype=stype)
        elif not get('searchSites'):
            if get('modalitate'):
                if get('modalitate') == 'edit':
                    getquery = get('query')
                    if getquery:
                        getquery = unquote(getquery)
                        try:
                            from resources.lib import PTN
                            getquery = re.sub('\[COLOR.+?\].+?\[/COLOR\]|\[.*?\]', '', getquery)
                            getquery = re.sub('\.', ' ', getquery)
                            parsed = PTN.parse(getquery)
                            if parsed.get('title'): 
                                getquery = parsed.get('title')
                            if parsed.get('season'):
                                getquery = '%s S%02d' % (getquery, int(parsed.get('season')))
                            if parsed.get('episode'):
                                getquery = '%sE%02d' % (getquery, int(parsed.get('episode')))
                        except: pass
                    keyboard = xbmc.Keyboard(unquote(getquery))
                    keyboard.doModal()
                    if (keyboard.isConfirmed() == False): return
                    keyword = keyboard.getText()
                    if len(keyword) == 0: return
                    else: self.get_searchsite(keyword, landing, stype=stype)
            else:
                cautari = get_search()
                if cautari:
                    listings = []
                    param_new = params
                    param_new['searchSites'] = 'noua'
                    if get('landsearch'):
                        param_new['landsearch'] = get('landsearch')
                    listings.append(self.drawItem(title = 'Căutare nouă',
                                          action = 'searchSites',
                                          link = param_new,
                                          image = search_icon))
                    for cautare in cautari[::-1]:
                        cm = []
                        new_params = params
                        new_params['cuvant'] = cautare[0]
                        new_params['searchSites'] = 'cuvant'
                        if get('landsearch'):
                            param_new['landsearch'] = get('landsearch')
                        cm.append(self.CM('searchSites', 'edit', cuvant=cautare[0]))
                        cm.append(self.CM('searchSites', 'delete', cuvant=cautare[0]))
                        #if self.torrenter == '1':
                            #cm.append(('Caută în Torrenter', torrmode(cautare[0])))
                        if self.youtube == '1':
                            cm.append(('Caută în Youtube', 'RunPlugin(%s?action=YoutubeSearch&url=%s)' % (sys.argv[0], quote(cautare[0]))))
                        listings.append(self.drawItem(title = unquote(cautare[0]),
                                          action = 'searchSites',
                                          link = new_params,
                                          image = search_icon,
                                          contextMenu = cm))
                    xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
                else:
                    keyboard = xbmc.Keyboard('')
                    keyboard.doModal()
                    if (keyboard.isConfirmed() == False): return
                    keyword = keyboard.getText()
                    if len(keyword) == 0: return
                    else: self.get_searchsite(keyword, landing, stype=stype)
        #try:
            #p_handle = int(sys.argv[1])
            #xbmcplugin.addSortMethod(p_handle, xbmcplugin.SORT_METHOD_UNSORTED)
            #xbmcplugin.addSortMethod(p_handle, xbmcplugin.SORT_METHOD_SIZE)
            ##xbmcplugin.addSortMethod(p_handle, xbmcplugin.SORT_METHOD_LABEL)
            ##xbmcplugin.addSortMethod(p_handle, xbmcplugin.SORT_METHOD_TITLE)
            ##xbmc.executebuiltin("Container.SetSortMethod(%s)" % str(1))
            ##xbmc.executebuiltin("Container.SetSortDirection()")
        #except: pass
        xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)

    def get_searchsite(self, word, landing=None, stype='sites'):
        import difflib
        from resources.lib import PTN
        gathereda = []
        result = {}
        nextlink = []
        allnew = []
        save_search(unquote(word))
        if landing:
            if landing in streams.streamsites:
                imp = getattr(streams, landing)
            else:
                imp = getattr(torrents, landing)
            site_name = imp().name
            total = 1
            result = {landing : imp().cauta(word)}
        else:
            if stype == 'both':
                allnew = __all__
                allnew.extend(__alltr__)
            elif stype == 'torrs':
                allnew = __alltr__
            else: allnew = __all__
            #else: result = thread_me(__all__, word, 'cautare', word=word)
            result = thread_me(allnew, word, 'cautare', word=word)
        try: resultitems = result.iteritems()
        except: resultitems = result.items()
        for sait, results in resultitems:
            if results and len(results) > 1:
                if results[2]:
                        for build in results[2]:
                            gathereda.append((build.get('nume'), build.get('legatura'), build.get('imagine'), build.get('switch'), build.get('info'), results[0], results[1]))
        patt = re.compile(r'\[S/L: (\d+)')
        #if not sait in __alltr__:
        #sorted(sorted(a, key = lambda x : x[0]), key = lambda x : x[1], reverse = True)
        if getSettingAsBool('slow_system_search'):
            gatheredb = sorted(gathereda, key=lambda x:difflib.SequenceMatcher(None, x[0].strip(), unquote(word)).ratio(), reverse=True)
            if stype == 'torrs' or stype == 'both':
                gathered = sorted(gatheredb, key=lambda x: int(patt.search(x[0]).group(1)) if patt.search(x[0]) else 0, reverse=True)
            else:
                gathered = gatheredb
        else:
            gatheredb = sorted(gathereda, key=lambda x: (difflib.SequenceMatcher(None, PTN.parse(re.sub('\[COLOR.+?\].+?\[/COLOR\](?:\s+)?|\[.*?\]', '', x[0].strip())).get('title'), unquote(word)).ratio(), int(patt.search(x[0].replace(',','').replace('.','')).group(1)) if patt.search(x[0]) else 0), reverse=True)
        
        gathered = gatheredb
        listings = []
        for deploy in gathered:
            nume = deploy[0]
            url = deploy[1]
            imagine = deploy[2]
            switch = deploy[3]
            infoa = deploy[4]
            site = deploy[5]
            site_name = deploy[6]
            params = {'site': site, 'link': url, 'switch': switch, 'nume': nume, 'info': infoa, 'favorite': 'check', 'watched': 'check'}
            if not nume == 'Next' or landing:
                if not nume == 'Next':
                    cm = []
                    self.getMetacm(url, nume, cm)
                    cm.append(('Caută Variante', 'Container.Update(%s?action=searchSites&modalitate=edit&query=%s&Stype=%s)' % (sys.argv[0], quote(nume), stype)))
                    if self.watched(params):
                        try: eval(params['info'])
                        except: pass
                        try:
                            params['info'].update({'playcount': 1, 'overlay': 7})
                            cm.append(self.CM('watched', 'delete', url, norefresh='1'))
                        except: pass
                    else:
                        #try: params['info'].update({'playcount': 0, 'overlay': 6})
                        #except: pass
                        cm.append(self.CM('watched', 'save', url, params=str(params), norefresh='1'))
                    if self.favorite(params):
                        nume = '[COLOR yellow]Fav[/COLOR] - %s' % nume
                        cm.append(self.CM('favorite', 'delete', url, nume, norefresh='1'))
                    else:
                        cm.append(self.CM('favorite', 'save', url, nume, params, norefresh='1'))
                    if self.youtube == '1':
                        cm.append(('Caută în Youtube', 'RunPlugin(%s?action=YoutubeSearch&url=%s)' % (sys.argv[0], quote(nume))))
                    listings.append(self.drawItem(title = '[COLOR red]%s[/COLOR] - %s' %
                                                  (site_name, nume) if not landing else nume,
                                          action = 'OpenSite',
                                          link = params,
                                          image = imagine,
                                          contextMenu = cm))
                else: nextlink.append(('[COLOR red]%s[/COLOR] - %s' % (site_name, nume) if not landing else nume, 'OpenSite', params, next_icon))
        if nextlink:
            for nextd in nextlink:
                for nume, action, params, icon in nextlink:
                    listings.append(self.drawItem(title = nume,
                                          action = action,
                                          link = params,
                                          image = icon))
        xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
                
        
    def CM(self, action, subaction=None, url=None, nume=None, params=None, norefresh=None, cuvant=None, container=None, imdb=None):
        text = action
        if action == 'favorite' and subaction == 'delete': text = 'Șterge din favorite'
        elif action == 'favorite' and subaction == 'save': text = 'Adaugă la favorite'
        elif action == 'watched' and subaction == 'delete': text = 'Șterge din istoric'
        elif action == 'watched' and subaction == 'save': text = 'Marchează ca vizionat'
        elif action == 'searchSites' and subaction == 'delete': text = 'Șterge din căutări'
        elif action == 'searchSites' and subaction == 'edit': text = 'Modifică'
        elif action == 'searchSites' and subaction == 'cuvant': text = 'Caută pe site-uri'
        elif action == 'disableSite' and subaction == 'enable': text = 'Activează'
        elif action == 'disableSite' and subaction == 'disable': text = 'Dezactivează'
        elif action == 'markTrakt' and subaction == 'watched': text = 'Marchează ca văzut în Trakt'
        elif action == 'markTrakt' and subaction == 'delete': text = 'Sterge show din Trakt'
        elif action == 'getMeta': text = 'MetaInfo %s' % subaction
        cm = (text, '%s(%s?action=%s%s%s%s%s%s%s%s,)' % ('Container.Update' if container else 'RunPlugin',
                                                                   sys.argv[0],
                                                                   action,
                                                                   '&' + action + '=' + subaction if subaction else '',
                                                                   '&' + action + 'link=' + quote(url) if url else '',
                                                                   '&nume=' + quote(nume) if nume else '',
                                                                   '&detalii=' + quote(str(params)) if params else '',
                                                                   '&norefresh=1' if norefresh else '',
                                                                   '&cuvant=' + quote(cuvant) if cuvant else '',
                                                                   '&imdb=' + quote(imdb) if imdb else ''))
        return cm
        
    def drawItem(self, **kwargs):
        #drawItem(self, title, action, link='', image='', isFolder=True, contextMenu=None, replaceMenu=True, action2='', fileSize=0, isPlayable=True):
        get = kwargs.get
        title = get('title')
        action = get('action')
        link = get('link')
        image = get('image')
        isFolder = get('isFolder') or True
        if isFolder == 'False':
            isFolder = False
        contextMenu = get('contextMenu')
        replaceMenu = get('replaceMenu') or True
        action2 = get('action2')
        fileSize = get('fileSize')
        isPlayable = get('isPlayable') or False
        if not image or image == '': image = os.path.join(__settings__.getAddonInfo('path'), 'resources', 'media', 'video.png')
        fanart = image
        torrent = False
        outside = False
        if isinstance(link, dict):
            link_url = ''
            if link.get('categorie'):
                link_url = '%s&%s=%s' % (link_url, 'categorie', link.get('categorie'))
            else:
                for key in link.keys():
                    if link.get(key):
                        if isinstance(link.get(key), dict):
                            try:
                                link.get(key)['imdbnumber'] = link.get(key).pop('imdb')
                            except: pass
                            link_url = '%s&%s=%s' % (link_url, key, quote(str(link.get(key))))
                        else:
                            link_url = '%s&%s=%s' % (link_url, key, quote(link.get(key)))
                            if key == 'switch' and link.get(key) == 'play': isFolder = False
                            if key == 'switch' and link.get(key) == 'torrent_links': 
                                isFolder = False
                                torrent = True
                            if key == 'switch' and link.get(key) == 'playoutside': 
                                isFolder = False
                                outside = True
            info = link.get('info')
            if info:
                info  = eval(str(info))
                if isinstance(info, dict):
                    image = info.get('Poster') or image
                    fanart = info.get('Fanart')
            url = '%s?action=%s' % (sys.argv[0], action) + link_url
            if torrent:
                if contextMenu:
                    contextMenu = play_variants(contextMenu, url)
        else:
            info = {"Title": title, "Plot": title}
            if not isFolder and fileSize:
                info['size'] = fileSize
            url = '%s?action=%s&url=%s' % (sys.argv[0], action, quote(link))
        if action2:
            url = url + '&url2=%s' % quote(ensure_str(action2))
        listitem = xbmcgui.ListItem(title)
        images = {'icon': image, 'thumb': image,
                  'Poster': image, 'banner': image,
                  'fanart': (fanart or image), 'landscape': image
                  }
        listitem.setArt(images)
        infog = info
        if infog:
            infog.pop('Poster', None)
            infog.pop('Fanart', None)
            infog.pop('Label2', None)
            infog.pop('imdb', None)
            infog.pop('tvdb', None)
            infog.pop('seek_time', None)
            infog.pop('played_file', None)
        if isFolder:
            listitem.setProperty("Folder", "true")
            listitem.setInfo(type='Video', infoLabels=infog)
        else:
            listitem.setInfo(type='Video', infoLabels=infog)
            if ((not torrent) and isPlayable) or outside:
                listitem.setProperty('isPlayable', 'true')
            try: 
                listitem.setContentLookup(False)
            except: pass
            listitem.setArt({'thumb': image})
        if contextMenu:
            try:
                listitem.addContextMenuItems(contextMenu, replaceItems=1 if replaceMenu else 0)
            except:
                listitem.addContextMenuItems(contextMenu, replaceItems=replaceMenu)
        if py3:
            isFolder = 1 if isFolder else 0
                
        return (url, listitem, isFolder)

    def getParameters(self, parameterString):
        commands = {}
        splitCommands = parameterString[parameterString.find('?') + 1:].split('&')
        for command in splitCommands:
            if (len(command) > 0):
                splitCommand = command.split('=')
                if (len(splitCommand) > 1):
                    name = splitCommand[0]
                    value = splitCommand[1]
                    commands[name] = value
        return commands

    def executeAction(self, params={}):
        #log(params)
        get = params.get
        if hasattr(self, get("action")):
            getattr(self, get("action"))(params)
        else:
            if self.sstype == 'torrs':
                self.TorrentsMenu()
            elif self.sstype == 'sites' or self.sstype == 'both':
                self.sectionMenu()

    def localize(self, string):
        return string
    
    def Trailercnmg(self, params={}):
        playTrailerCnmg(params)
        
    def GetTrailerimdb(self, params={}):
        getTrailerImdb(params)
    
    def OpenT(self, params={}):
        openTorrent(params)
    
    def YoutubeSearch(self, params={}):
        nume = params.get('url')
        from resources.lib import PTN
        getquery = re.sub('\[COLOR.+?\].+?\[/COLOR\]|\[.*?\]', '', unquote(nume))
        getquery = re.sub('\.', ' ', getquery)
        parsed = PTN.parse(getquery)
        if parsed.get('title'):
            xbmc.executebuiltin('Container.Update(plugin://plugin.video.youtube/kodion/search/query/?q=%s)' % (quote(parsed.get('title'))))
        else: return ''
    
    def CleanDB(self, params={}):
        clean_database()
    
    def internTorrentBrowser(self, params={}):
        from torrent2http import s
        if s.role == 'client' and (not s.mrsprole):
            try: values = params.iteritems()
            except: values = params.items()
            for key, value in values:
                if '0.0.0.0' in value:
                    params[key] = value.replace('0.0.0.0', s.remote_host)
        listings = []
        menu, dirs = [], []
        contextMenustring = 'RunPlugin(%s)' % ('%s?action=%s&modify=%s') % (sys.argv[0], 'internTorrentBrowser', '%s')
        get = params.get
        if not get('url'):
            if get('modify'):
                try:
                    requests.head(unquote(get('modify')))
                except: pass
                if 'stopanddelete' in unquote(get('modify')):
                    resume = get('resume_file')
                    if resume and resume != 'false':
                        resume = unquote(resume)
                        try: xbmcvfs.delete(resume)
                        except: pass
                return
            else:
                procs_started = check_torrent2http()
                if procs_started:
                    for resume_file, proc_started in procs_started:
                        try:
                            data = requests.get('http://%s/status' % proc_started).json()
                        except:
                            showMessage('Atentie', 'Ai un process la care nu ma pot conecta, restarteaza kodi sau aparatul', forced=True)
                            data = {}
                        folder = True
                        name = data.get('name')
                        popup = []
                        status = ' '
                        d_stat = data.get('state_str')
                        ses_stat = data.get('session_status')
                        progres = data.get('progress')
                        img = ''
                        info = {}
                        link = 'http://%s/' % proc_started
                        resume_file = resume_file if not resume_file in ['false', ''] else 'false'
                        if d_stat == 'finished':
                            status = TextBB('[%.1f%%]' % (float(progres) * 100))
                            status += TextBB(' [||] ', 'b')
                        elif d_stat == 'seeding':
                            status = TextBB('[%.1f%%]' % (float(progres) * 100))
                            status += TextBB(' [U] ', 'b')
                            img = os.path.join(ROOT, 'resources', 'media', 'upload-icon.png')
                        elif d_stat == 'downloading':
                            status = TextBB('[%.1f%%]' % (float(progres) * 100))
                            status += TextBB(' [D] ', 'b')
                            img = os.path.join(ROOT, 'resources', 'media', 'download-icon.png')
                        elif d_stat in ('queued_for_checking', 'checking_files', 'downloading_metadata', 'allocating', 'checking_resume_data'):
                            status = TextBB(' [><] ', 'b')
                        if ses_stat == 'paused':
                            status = TextBB('[%.1f%%]' % (float(progres) * 100))
                            status += TextBB(' [Stopped] ', 'b')
                        info = {'Title': name, 'Plot': '%s %s %s' % (name, d_stat, ses_stat), 'Poster': img}
                        if ses_stat == 'running':
                            popup.append(('Pause', contextMenustring % '%sstop' % quote(link)))
                        else:
                            popup.append(('Resume', contextMenustring % '%sresume' % quote(link)))
                        if d_stat == 'finished':
                            popup.append(('Start torrent', contextMenustring % quote('%spriority?index=%s&priority=%s' % (link, '0', '9999'))))
                        popup.append(('Stop', contextMenustring % '%sshutdown' % quote(link)))
                        popup.append(('Stop and force remove files', contextMenustring % ('%s&resume_file=%s' % (quote('%sstopanddelete' % link), quote(resume_file)))))
                        listings.append(self.drawItem(title = '%s %s' % (status, name),
                                        action = 'internTorrentBrowser',
                                        link = {'url': link, 'info': info},
                                        image = img,
                                        isFolder = folder,
                                        replaceMenu = 'True',
                                        contextMenu = popup,
                                        isPlayable = 'False'))
                xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
                xbmcplugin.endOfDirectory(handle=int(sys.argv[1]), succeeded=True)
        else:
            if get('play'):
                #if link == urls or params.get('subtitrare'):
                    #if params.get('subtitrare'):
                        #subtitrare = get_sub(unquote(params.get('subtitrare')), unquote(landing), '1')
                #else: subtitrare = get_sub(link, unquote(landing))
                subtitrare = None
                item = xbmcgui.ListItem(get('title'))
                info = get('info')
                if info: 
                    info = eval(unquote(info))
                    item.setInfo(type="Video", infoLabels=info); item.setArt({'thumb': info.get('Poster') or os.path.join(__settings__.getAddonInfo('path'), 'resources', 'media', 'video.png')})
                else: item.setInfo(type="Video", infoLabels={'Title':unquote(get('title'))})
                item.setInfo('video', {'Cast': [str(params)]})
                try:
                    item.setContentLookup(False)
                except: pass
                try:
                    if subtitrare:
                        item.setSubtitles([subtitrare])
                except: pass
                requests.get('%s/resume' % unquote(get('url')))
                #requests.get('%s/priority?index=%s&priority=1' % (unquote(get('url')), get('ind')))
                xbmc.Player().play(unquote(get('play')), item)
            else:
                url = unquote(get('url'))
                data = requests.get('%sls' % url).json()
                for index, f in enumerate(data.get('files')):
                    popup = []
                    name = f.get('name')
                    save_path = f.get('save_path')
                    priority = f.get('priority')
                    downloaded = f.get('download')
                    progress = f.get('progress')
                    size = f.get('size')
                    play = f.get('url')
                    d_stat = ''
                    if priority == 0:
                        status = TextBB('%.1f%%' % (float(progress) * 100))
                        status += TextBB(' [||] ', 'b')
                        d_stat = ' not downloading'
                        img = os.path.join(ROOT, 'resources', 'media', 'stop-icon.png')
                    else:
                        status = TextBB('%.1f%%' % (float(progress) * 100))
                        status += TextBB(' [>] ', 'b')
                        if progress == 1:
                            d_stat = ' downloaded'
                        else:
                            d_stat = ' downloading'
                        img = os.path.join(ROOT, 'resources', 'media', 'upload-icon.png')
                    if priority > 0:
                        popup.append(('Stop Downloading This file', contextMenustring % quote('%spriority?index=%s&priority=%s' % (url, index, '0'))))
                    else:
                        popup.append(('Start Downloading This file', contextMenustring % quote('%spriority?index=%s&priority=%s' % (url, index, '4'))))
                    info = {'Title': name, 'Plot': '%s %s MB%s' % (name, str(size/1024/1024), d_stat), 'Poster': img}
                    listings.append(self.drawItem(title = '%s %s %s MB' % (status, name, str(size/1024/1024)),
                                    action = 'internTorrentBrowser',
                                    link = {'url': url,
                                            'info': info,
                                            'play': play,
                                            'title': name,
                                            'ind': index},
                                    image = img,
                                    isFolder = 'False',
                                    replaceMenu = 'True',
                                    contextMenu = popup,
                                    isPlayable = 'False',
                                    fileSize = size))
                xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
                xbmcplugin.endOfDirectory(handle=int(sys.argv[1]), succeeded=True)
                
    
    def uTorrentBrowser(self, params={}):
        listings = []
        from resources.lib.utorrent.net import Download
        menu, dirs = [], []
        contextMenustring = 'RunPlugin(%s)' % ('%s?action=%s&url=%s') % (sys.argv[0], 'uTorrentBrowser', '%s')
        get = params.get
        try:
            apps = json.loads(urllib.unquote_plus(get("url")))
        except:
            apps = {}
        action = apps.get('action')
        hash = apps.get('hash')
        ind = apps.get('ind')
        tdir = apps.get('tdir')

        #print str(action)+str(hash)+str(ind)+str(tdir)

        DownloadList = Download().list()
        if DownloadList == False:
            showMessage('Error', 'No connection! Check settings!', forced=True)
            return

        if action:
            if action == 'context':
                xbmc.executebuiltin("Action(ContextMenu)")
                return
            if (ind or ind == 0) and action in ('0', '3'):
                Download().setprio_simple(hash, action, ind)
            elif action in ['play','copy']:
                p, dllist, i, folder, filename = DownloadList, Download().listfiles(hash), 0, None, None
                for data in p:
                    if data['id'] == hash:
                        folder = data['dir']
                        break
                if isRemoteTorr():
                    t_dir = __settings__.getSetting("torrent_dir")
                    torrent_replacement = __settings__.getSetting("torrent_replacement")
                    empty = [None, '']
                    if t_dir in empty or torrent_replacement in empty:
                        if xbmcgui.Dialog().yesno(
                                'Remote Torrent-client',
                                'You didn\'t set up replacement path in setting.',
                                'For example /media/dl_torr/ to smb://SERVER/dl_torr/. Setup now?'):
                            if t_dir in empty:
                                torrent_dir()
                            __settings__.openSettings()
                        return
                    folder = folder.replace(t_dir, torrent_replacement)
                if (ind or ind == 0) and action == 'play':
                    for data in dllist:
                        if data[2] == int(ind):
                            filename = data[0]
                            break
                    filename = os.path.join(folder, filename)
                    xbmc.executebuiltin('PlayMedia("' + filename.encode('utf-8') + '")')
                elif tdir and action == 'copy':
                    path = os.path.join(localize_path(folder), localize_path(tdir))
                    dirs, files=xbmcvfs.listdir(path)
                    if len(dirs) > 0:
                        dirs.insert(0, './ (Root folder)')
                        for dd in dirs:
                            dd = file_decode(dd)
                            dds=xbmcvfs.listdir(os.path.join(path,dd))[0]
                            if len(dds)>0:
                                for d in dds:
                                    dirs.append(dd+os.sep+d)
                        ret = xbmcgui.Dialog().select('Choose directory:', dirs)
                        if ret > 0:
                            path=os.path.join(path, dirs[ret])
                            dirs, files=xbmcvfs.listdir(path)
                    for file in files:
                        file = localize_path(file)
                        if not xbmcvfs.exists(os.path.join(path, file)):
                            xbmcvfs.delete(os.path.join(path, file))
                        xbmcvfs.copy(os.path.join(path, file),os.path.join(folder, file))
                        i=i+1
                    showMessage('Torrent-client Browser', 'Copied %d files!' % i, forced=True)
                return
            elif not tdir and action not in ('0', '3'):
                Download().action_simple(action, hash)
            elif action in ('0', '3'):
                dllist = sorted(Download().listfiles(hash), key=lambda x: x[0])
                for name, percent, ind, size in dllist:
                    if tdir:
                        if '/' in name and tdir in name:
                            menu.append((hash, action, str(ind)))
                    else:
                        menu.append((hash, action, str(ind)))
                Download().setprio_simple_multi(menu)
                return
            xbmc.executebuiltin('Container.Refresh')
            return
        
        if not hash:
            for data in DownloadList:
                status = " "
                img=''
                if data['status'] in ('seed_pending', 'stopped'):
                    status = TextBB(' [||] ', 'b')
                elif data['status'] in ('seeding', 'downloading'):
                    status = TextBB(' [>] ', 'b')
                if data['status']   == 'seed_pending':
                    img = os.path.join(ROOT, 'resources', 'media', 'pause-icon.png')
                elif data['status'] == 'stopped':
                    img = os.path.join(ROOT, 'resources', 'media', 'stop-icon.png')
                elif data['status'] == 'seeding':
                    img = os.path.join(ROOT, 'resources', 'media', 'upload-icon.png')
                elif data['status'] == 'downloading':
                    img = os.path.join(ROOT, 'resources', 'media', 'download-icon.png')
                menu.append(
                    {"title": '[' + str(data['progress']) + '%]' + status + data['name'] + ' [' + str(
                        data['ratio']) + ']', "image":img,
                     "argv": {'hash': str(data['id'])}})
        elif not tdir:
            dllist = sorted(Download().listfiles(hash), key=lambda x: x[0])
            for name, percent, ind, size in dllist:
                if '/' not in name:
                    menu.append({"title": '[' + str(percent) + '%]' + '[' + str(size) + '] ' + name, "image": os.path.join(ROOT, 'resources', 'media', 'magnet.png'),
                                 "argv": {'hash': hash, 'ind': str(ind), 'action': 'context'}})
                else:
                    tdir = name.split('/')[0]
                    # tfile=name[len(tdir)+1:]
                    if tdir not in dirs: dirs.append(tdir)
        elif tdir:
            dllist = sorted(Download().listfiles(hash), key=lambda x: x[0])
            for name, percent, ind, size in dllist:
                if '/' in name and tdir in name:
                    menu.append(
                        {"title": '[' + str(percent) + '%]' + '[' + str(size) + '] ' + name[len(tdir) + 1:], "image": os.path.join(ROOT, 'resources', 'media', 'magnet.png'),
                         "argv": {'hash': hash, 'ind': str(ind), 'action': 'context'}})

        for i in dirs:
            app = {'hash': hash, 'tdir': i}
            link = json.dumps(app)
            popup = []
            folder = True
            actions = [('3', 'High Priority Files'), ('copy', 'Copy Files in Root'), ('0', 'Skip All Files')]
            for a, title in actions:
                app['action'] = a
                popup.append((title, contextMenustring % urllib.quote_plus(json.dumps(app))))
            listings.append(self.drawItem(title = unicode(i),
                                    action = 'uTorrentBrowser',
                                    link = link,
                                    image = img,
                                    isFolder = folder,
                                    replaceMenu = 'True',
                                    contextMenu = popup,
                                    isPlayable = 'False'))

        for i in menu:
            app = i['argv']
            link = json.dumps(app)
            img = i['image']
            popup = []
            if not hash:
                actions = [('start', 'Start'), ('stop', 'Stop'),
                           ('remove', 'Remove'),
                           ('3', 'High Priority Files'), ('0', 'Skip All Files'),
                           ('removedata', 'Remove with files')]

                folder = True
            else:
                actions = [('3', 'High Priority'), ('0', 'Skip File'),
                           ('play', 'Play File')]
                folder = False
            for a, title in actions:
                app['action'] = a
                popup.append((title, contextMenustring % urllib.quote_plus(json.dumps(app))))
            try: titlea = unicode(i['title'])
            except: titlea = i['title']
            listings.append(self.drawItem(title = titlea,
                                    action = 'uTorrentBrowser',
                                    link = link,
                                    image = img,
                                    isFolder = folder,
                                    replaceMenu = 'True',
                                    contextMenu = popup,
                                    isPlayable = 'False'))
        xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
        xbmcplugin.endOfDirectory(handle=int(sys.argv[1]), succeeded=True)
        return
