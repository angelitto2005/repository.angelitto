# -*- coding: utf-8 -*-

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs
from .functions import *
# MODIFICARE: Am eliminat importul 'streams'
from resources.lib import torrents
import json

__settings__ = xbmcaddon.Addon()

# MODIFICARE: Am eliminat listele __all__ si __disabled__ pentru streams.
# Pastram doar listele pentru torenti.
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
        
        # item.setInfo('video', {'Cast': [unquot(str(params))]})
        # item.setProperty('mrsp.data', unquot(str(params)))
        # ===== START MODIFICARE: Folosire Window Property (pentru stream-uri) =====
        # Stocăm datele într-o proprietate a ferestrei principale (ID 10000).
        # Aceasta este o metodă sigură de a pasa informații către serviciu.
        xbmcgui.Window(10000).setProperty('mrsp.data', str(params))
        # ===== SFÂRȘIT MODIFICARE =====
        
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
    
    # ===== INCEPUT MODIFICARE =====
    # Variabilă de clasă pentru a păstra informațiile Kodi în sesiunea curentă
    _kodi_context = {'dbtype': None, 'dbid': None, 'path': None}
    # ===== SFARSIT MODIFICARE =====
    
    #check_one_db()
    if xbmc.getCondVisibility('System.HasAddon(plugin.video.youtube)'): youtube = '1'
    else: youtube = '0'
    
    # MODIFICARE: Fortam tipul de cautare si sursa strict pe torenti ('torrs')
    # Am eliminat verificarile pentru 'searchtype' si 'torrs' din setari
    sstype = 'torrs'
    
    context_trakt_search_mode = __settings__.getSetting('context_trakt_search_mode')

    def _set_video_info_from_dict(self, list_item, info_dict):
        """
        Setează metadatele video pe un ListItem folosind metoda modernă InfoTagVideo.
        Acest lucru evită avertismentul de depreciere și gestionează corect cheile.
        """
        if not isinstance(info_dict, dict):
            return

        try:
            video_tag = list_item.getVideoInfoTag()

            # Informații esențiale pentru seriale
            if 'TVShowTitle' in info_dict and info_dict['TVShowTitle']:
                video_tag.setTvShowTitle(str(info_dict['TVShowTitle']))
            if 'Season' in info_dict and info_dict['Season'] is not None:
                video_tag.setSeason(int(info_dict['Season']))
            if 'Episode' in info_dict and info_dict['Episode'] is not None:
                video_tag.setEpisode(int(info_dict['Episode']))

            # Informații generale
            if 'Title' in info_dict and info_dict['Title']:
                video_tag.setTitle(str(info_dict['Title']))
            if 'Plot' in info_dict and info_dict['Plot']:
                video_tag.setPlot(str(info_dict['Plot']))
            if 'Year' in info_dict and info_dict['Year']:
                video_tag.setYear(int(info_dict['Year']))
            
            if 'Genre' in info_dict and info_dict['Genre']:
                genre_data = info_dict['Genre']
                genre_list = []
                if isinstance(genre_data, str):
                    cleaned_str = genre_data.strip("[]'\" ")
                    genre_list = [g.strip() for g in cleaned_str.split(',')]
                elif isinstance(genre_data, list):
                    genre_list = genre_data
                
                if genre_list:
                    video_tag.setGenres(genre_list)

            if 'Duration' in info_dict and info_dict['Duration']:
                video_tag.setDuration(int(info_dict['Duration']))
            if 'Rating' in info_dict and info_dict['Rating']:
                video_tag.setRating(float(info_dict['Rating']))
            if 'Votes' in info_dict and info_dict['Votes']:
                video_tag.setVotes(str(info_dict['Votes']))
            if 'mpaa' in info_dict and info_dict['mpaa']:
                video_tag.setMpaa(str(info_dict['mpaa']))
            if 'imdbnumber' in info_dict and info_dict['imdbnumber']:
                video_tag.setIMDBNumber(str(info_dict['imdbnumber']))
            
            # --- AICI ESTE CORECȚIA PRINCIPALĂ ---
            # Setarea 'playcount' este metoda corectă pentru a indica statusul "vizionat".
            # Skin-ul va afișa automat iconița corespunzătoare.
            if 'playcount' in info_dict and info_dict['playcount'] is not None:
                video_tag.setPlaycount(int(info_dict['playcount']))
            
            # Am eliminat complet secțiunea pentru 'setOverlay', deoarece nu există și
            # este redundantă atunci când 'playcount' este setat.

        except (ValueError, TypeError) as e:
            log(f"Eroare la setarea InfoTagVideo: {e}. Verificati tipul de date.")
        except Exception as e:
            log(f"Eroare necunoscuta in _set_video_info_from_dict: {e}")

    def _set_video_info_modern(self, listitem, info_dict):
        """
        Setează informațiile video folosind InfoTagVideo (Kodi 20+)
        Cu fallback pentru versiuni mai vechi.
        """
        if not info_dict:
            return
            
        try:
            info_tag = listitem.getVideoInfoTag()
            
            # Mapare chei comune
            if info_dict.get('Title'):
                info_tag.setTitle(str(info_dict['Title']))
            if info_dict.get('OriginalTitle'):
                info_tag.setOriginalTitle(str(info_dict['OriginalTitle']))
            if info_dict.get('Plot'):
                info_tag.setPlot(str(info_dict['Plot']))
            if info_dict.get('Tagline'):
                info_tag.setTagLine(str(info_dict['Tagline']))
            if info_dict.get('Year'):
                try: info_tag.setYear(int(info_dict['Year']))
                except: pass
            if info_dict.get('Rating'):
                try: info_tag.setRating(float(info_dict['Rating']))
                except: pass
            if info_dict.get('Duration') or info_dict.get('duration'):
                try: info_tag.setDuration(int(info_dict.get('Duration') or info_dict.get('duration')))
                except: pass
            if info_dict.get('Genre'):
                genre = info_dict['Genre']
                if isinstance(genre, str):
                    info_tag.setGenres([g.strip() for g in genre.split(',')])
                elif isinstance(genre, list):
                    info_tag.setGenres(genre)
            if info_dict.get('Director'):
                director = info_dict['Director']
                if isinstance(director, str):
                    info_tag.setDirectors([d.strip() for d in director.split(',')])
                elif isinstance(director, list):
                    info_tag.setDirectors(director)
            if info_dict.get('Writer'):
                writer = info_dict['Writer']
                if isinstance(writer, str):
                    info_tag.setWriters([w.strip() for w in writer.split(',')])
                elif isinstance(writer, list):
                    info_tag.setWriters(writer)
            if info_dict.get('Studio'):
                studio = info_dict['Studio']
                if isinstance(studio, str):
                    info_tag.setStudios([studio])
                elif isinstance(studio, list):
                    info_tag.setStudios(studio)
            if info_dict.get('TVShowTitle'):
                info_tag.setTvShowTitle(str(info_dict['TVShowTitle']))
            if info_dict.get('Season'):
                try: info_tag.setSeason(int(info_dict['Season']))
                except: pass
            if info_dict.get('Episode'):
                try: info_tag.setEpisode(int(info_dict['Episode']))
                except: pass
            if info_dict.get('Premiered'):
                info_tag.setPremiered(str(info_dict['Premiered']))
            if info_dict.get('MPAA'):
                info_tag.setMpaa(str(info_dict['MPAA']))
            if info_dict.get('Country'):
                country = info_dict['Country']
                if isinstance(country, str):
                    info_tag.setCountries([country])
                elif isinstance(country, list):
                    info_tag.setCountries(country)
                    
            # IMDb Number
            if info_dict.get('imdbnumber'):
                info_tag.setIMDBNumber(str(info_dict['imdbnumber']))
            elif info_dict.get('IMDBNumber'):
                info_tag.setIMDBNumber(str(info_dict['IMDBNumber']))
            elif info_dict.get('imdb_id'):
                info_tag.setIMDBNumber(str(info_dict['imdb_id']))
                
            # UniqueIDs
            uids = {}
            if info_dict.get('tmdb_id'):
                uids['tmdb'] = str(info_dict['tmdb_id'])
            if info_dict.get('imdb_id'):
                uids['imdb'] = str(info_dict['imdb_id'])
            if info_dict.get('imdbnumber'):
                uids['imdb'] = str(info_dict['imdbnumber']).replace('tt', '')
            if info_dict.get('tvdb_id'):
                uids['tvdb'] = str(info_dict['tvdb_id'])
            if uids:
                info_tag.setUniqueIDs(uids)
                
        except AttributeError:
            # Fallback pentru Kodi < 20 (nu are getVideoInfoTag)
            safe_keys = ['Title', 'OriginalTitle', 'Plot', 'Year', 'Rating', 'Duration', 
                         'Genre', 'Director', 'Writer', 'TVShowTitle', 'Season', 'Episode', 
                         'imdbnumber', 'Premiered', 'MPAA', 'Tagline', 'Studio', 'Country',
                         'size', 'Votes', 'Top250', 'Trailer', 'PlayCount', 'LastPlayed']
            safe_info = {}
            for k, v in info_dict.items():
                if k in safe_keys and v is not None:
                    safe_info[k] = v
            if safe_info:
                listitem.setInfo('video', safe_info)
        except Exception as e:
            # Fallback generic
            log('[MRSP-CORE] Eroare _set_video_info_modern: %s' % str(e))


    def RecentsSubMenu(self, params={}):
        listings = []
        listings.append(self.drawItem(title = '[B][COLOR white]Recente sortate după seederi [/COLOR][/B]',
                                      action = 'recents',
                                      link = {'Rtype': 'torrs', 'Sortby': 'seed'},
                                      image = recents_icon))
        listings.append(self.drawItem(title = '[B][COLOR white]Recente sortate după mărime [/COLOR][/B]',
                                      action = 'recents',
                                      link = {'Rtype': 'torrs', 'Sortby': 'size'},
                                      image = recents_icon))
        listings.append(self.drawItem(title = '[B][COLOR white]Recente sortate după nume [/COLOR][/B]',
                                      action = 'recents',
                                      link = {'Rtype': 'torrs', 'Sortby': 'name'},
                                      image = recents_icon))
        listings.append(self.drawItem(title = '[B][COLOR white]Recente grupate pe site-uri [/COLOR][/B]',
                                      action = 'recents',
                                      link = {'Rtype': 'torrs', 'Sortby': 'site'},
                                      image = recents_icon))
        
        # Content type gol pentru a preveni fortarea iconitei de folder
        xbmcplugin.setContent(int(sys.argv[1]), '')
        xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
        xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)

    def TorrentsMenu(self, params={}):
        listings = []
        
        # Recente
        listings.append(self.drawItem(title = '[B][COLOR white]Recente[/COLOR][/B]',
                                      action = 'RecentsSubMenu',
                                      link = {},
                                      image = recents_icon))
        
        # Cautare
        listings.append(self.drawItem(title = '[B][COLOR white]Căutare[/COLOR][/B]',
                                      action = 'searchSites',
                                      link = {'Stype': 'torrs'},
                                      image = search_icon))
                                      
        if self.sstype == 'torrs':
            # Favorite
            listings.append(self.drawItem(title = '[B][COLOR white]Favorite[/COLOR][/B]',
                                          action = 'favorite',
                                          link = {'site': 'site', 'favorite': 'print'},
                                          image = fav_icon))
            
            # Vazute
            listings.append(self.drawItem(title = '[B][COLOR white]Văzute[/COLOR][/B]',
                                          action = 'watched',
                                          link = {'watched': 'list'},
                                          image = seen_icon))
            
            # Meniuri extra
            img_tmdb = os.path.join(media, 'tmdb.png') 
            if not os.path.exists(img_tmdb): img_tmdb = search_icon # Fallback
            
            listings.append(self.drawItem(title = '[B][COLOR FFFDBD01]TMDb (Filme & Seriale)[/COLOR][/B]',
                                          action = 'openTMDB',
                                          link = {},
                                          image = img_tmdb))
                                          
            img_trakt = os.path.join(media, 'trakt.png')
            listings.append(self.drawItem(title = '[B][COLOR white]Trakt[/COLOR][/B]',
                                          action = 'openTrakt',
                                          link = {},
                                          image = img_trakt))
        
            img_cinemagia = os.path.join(media, 'cinemagia.png')
            listings.append(self.drawItem(title = '[B][COLOR white]Cinemagia[/COLOR][/B]',
                                          action = 'openCinemagia',
                                          link = {},
                                          image = img_cinemagia))
        
        # Tools - Torrent Client Browser
        tcb = xbmcgui.ListItem('[B][COLOR white]Torrent client browser[/COLOR][/B]')
        tcb.setArt({'thumb': torrclient_icon, 'icon': torrclient_icon, 'poster': torrclient_icon})
        listings.append(('%s?action=OpenT&Tmode=opentclient&Turl=abcd' % (sys.argv[0]), tcb, False))
        
        # Tools - Libtorrent Browser
        if torrenter: 
            lb = xbmcgui.ListItem('[B][COLOR white]Libtorrent browser[/COLOR][/B]')
            lb.setArt({'thumb': torrclient_icon, 'icon': torrclient_icon, 'poster': torrclient_icon})
            listings.append(('%s?action=OpenT&Tmode=opentbrowser&Turl=abcd' % (sys.argv[0]), lb, False))
            
        # Tools - Intern Torrent
        tcb2 = xbmcgui.ListItem('[B][COLOR white]Intern Torrent[/COLOR][/B]')
        tcb2.setArt({'thumb': torrclient_icon, 'icon': torrclient_icon, 'poster': torrclient_icon})
        listings.append(('%s?action=OpenT&Tmode=opentintern&Turl=abcd' % (sys.argv[0]), tcb2, False))
        
        # Setari
        settings_icon = os.path.join(media, 'settings.png')
        if self.sstype == 'torrs':
            set1 = xbmcgui.ListItem('[B][COLOR white]Setări[/COLOR][/B]')
            set1.setArt({'icon': settings_icon, 'thumb': settings_icon, 'poster': settings_icon})
            listings.append(('%s?action=openSettings' % (sys.argv[0]), set1, False))
            
        set2 = xbmcgui.ListItem('[B][COLOR white]Setări Torrent2http[/COLOR][/B]')
        set2.setArt({'icon': settings_icon, 'thumb': settings_icon, 'poster': settings_icon})
        listings.append(('%s?action=openSettings&script=torrent2http' % (sys.argv[0]), set2, False))
        
        # Site-uri active
        for torr in __alltr__:
            cm = []
            imp = torrents.torrnames.get(torr)
            name = imp.get('nume')
            thumb_site = imp.get('thumb')
            params = {'site': torr}
            seedmrsp = getSettingAsBool('%sseedmrsp' % torr)
            seedtransmission = getSettingAsBool('%sseedtransmission' % torr)
            
            cm.append(self.CM('disableSite', 'disable', nume=torr))
            
            # Logica de afisare a numelui si culorii
            if seedmrsp or seedtransmission:
                params['info'] = {'Plot': 'Seeding cu %s activat' % ('MRSP' if seedmrsp else 'Transmission')}
                # Daca e la seed, il lasam lightblue pentru a se distinge, dar Bold
                name = '[B][COLOR lightblue]%s[/COLOR][/B]' % name
            else:
                params['info'] = {'Plot': 'Seeding dezactivat'}
                # Culoarea ceruta: FFFDBD01 (Gold) si Bold
                name = '[B][COLOR FFFDBD01]%s[/COLOR][/B]' % name

            if not seedtransmission:
                cm.append(('%s seed MRSP' % ('Dezactivează' if seedmrsp else 'Activează'), 'RunPlugin(%s?action=setTorrent&setTorrent=%s&site=%s&value=%s)' % (sys.argv[0], 'seedmrsp', torr, 'false' if seedmrsp else 'true')))
            if not seedmrsp:
                cm.append(('%s seed Transmission' % ('Dezactivează' if seedtransmission else 'Activează'), 'RunPlugin(%s?action=setTorrent&setTorrent=%s&site=%s&value=%s)' % (sys.argv[0], 'seedtransmission', torr, 'false' if seedtransmission else 'true')))
            
            listings.append(self.drawItem(title = name,
                                          action = 'openMenu',
                                          link = params,
                                          image = thumb_site,
                                          contextMenu = cm))
        
        # Site-uri dezactivate (eliminate din lista conform cererii anterioare)
        
        xbmcplugin.setContent(int(sys.argv[1]), '')
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
        try: 
            from io import BytesIO as StringIO
        except ImportError: 
            from cStringIO import StringIO
        import base64
        import datetime
        import threading
        
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
                # --- MENIU PRINCIPAL TRAKT ---
                listings.append(self.drawItem(title = '[B][COLOR white]Calendar[/COLOR][/B]',
                                          action = 'openTrakt',
                                          link = {'openTrakt': 'calendar'},
                                          image = image))
                listings.append(self.drawItem(title = '[B][COLOR white]Trending[/COLOR][/B]',
                                          action = 'openTrakt',
                                          link = {'openTrakt': 'trending', 'page': page},
                                          image = image))
                listings.append(self.drawItem(title = '[B][COLOR white]Popular[/COLOR][/B]',
                                          action = 'openTrakt',
                                          link = {'openTrakt': 'popular', 'page': page},
                                          image = image))
                listings.append(self.drawItem(title = '[B][COLOR white]Played[/COLOR][/B]',
                                          action = 'openTrakt',
                                          link = {'openTrakt': 'played', 'page': page},
                                          image = image))
                listings.append(self.drawItem(title = '[B][COLOR white]Watched[/COLOR][/B]',
                                          action = 'openTrakt',
                                          link = {'openTrakt': 'watched', 'page': page},
                                          image = image))
                listings.append(self.drawItem(title = '[B][COLOR white]Anticipate[/COLOR][/B]',
                                          action = 'openTrakt',
                                          link = {'openTrakt': 'anticipated', 'page': page},
                                          image = image))
                listings.append(self.drawItem(title = '[B][COLOR white]Favorite Saptamanale[/COLOR][/B]',
                                          action = 'openTrakt',
                                          link = {'openTrakt': 'favorited', 'page': page},
                                          image = image))
                listings.append(self.drawItem(title = '[B][COLOR FFFDBD01]Listele Mele[/COLOR][/B]',
                                          action = 'openTrakt',
                                          link = {'openTrakt': 'mylists'},
                                          image = image))
                
                xbmcplugin.setContent(int(sys.argv[1]), '')
                xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
                xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)

            elif action == 'mylists':
                my_username = __settings__.getSetting('trakt.username')
                if not my_username:
                    xbmcgui.Dialog().ok("Utilizator Trakt Lipsa", "Te rugam sa introduci numele de utilizator Trakt in setarile addon-ului.")
                else:
                    my_lists = trakt.getUserLists(my_username)
                    if my_lists:
                        for a_list in my_lists:
                            list_name = a_list.get('name')
                            list_id = a_list.get('ids', {}).get('slug')
                            item_count = a_list.get('item_count', 0)
                            
                            if list_name and list_id:
                                listings.append(self.drawItem(
                                    title = '[B]%s[/B] [COLOR gray](%d iteme)[/COLOR]' % (list_name, item_count),
                                    action = 'openTrakt',
                                    link = {'openTrakt': 'listitems', 'list_id': list_id, 'username': my_username, 'page': '1'},
                                    image = image
                                ))
                xbmcplugin.setContent(int(sys.argv[1]), '')
                xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
                xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)

            elif action == 'listitems':
                list_id = params.get('list_id')
                username = params.get('username')
                page = int(params.get('page', '1'))
                items = trakt.getListItems(username, list_id, page=page, limit=30)
                
                if items:
                    for item in items:
                        item_type = item.get('type')
                        media_item = item.get(item_type)

                        if not media_item: continue
                        
                        ids = media_item.get('ids', {})
                        imdb = ids.get('imdb')
                        tmdb = ids.get('tmdb')
                        
                        # =====================================================
                        # FIX: Pentru seriale/episoade, luăm ID-urile SHOW-ului
                        # =====================================================
                        show_imdb = imdb
                        show_tmdb = tmdb
                        
                        if item_type == 'episode':
                            show_data = item.get('show', {})
                            show_ids = show_data.get('ids', {})
                            show_imdb = show_ids.get('imdb') or imdb
                            show_tmdb = show_ids.get('tmdb') or tmdb
                        elif item_type == 'show':
                            # Pentru show, ID-urile sunt deja corecte
                            pass
                        # =====================================================
                        
                        poster = fanart = image
                        if tmdb:
                            if item_type == 'movie':
                                tmdb_url = 'https://api.themoviedb.org/3/movie/%s?api_key=%s&language=en-US' % (tmdb, tmdb_key())
                            else:
                                tmdb_url = 'https://api.themoviedb.org/3/tv/%s?api_key=%s&language=en-US' % (show_tmdb, tmdb_key())

                            tmdb_data = fetchData(tmdb_url, rtype='json')
                            if tmdb_data:
                                poster_path = tmdb_data.get('poster_path')
                                fanart_path = tmdb_data.get('backdrop_path')
                                if poster_path: poster = 'https://image.tmdb.org/t/p/w500%s' % poster_path
                                if fanart_path: fanart = 'https://image.tmdb.org/t/p/w780%s' % fanart_path

                        infos = {}
                        infos['Title'] = media_item.get('title')
                        infos['Year'] = media_item.get('year')
                        infos['Plot'] = media_item.get('overview')
                        infos['imdb'] = imdb
                        infos['imdb_id'] = imdb
                        infos['tmdb_id'] = tmdb
                        infos['Poster'] = poster
                        infos['Fanart'] = fanart
                        
                        # =====================================================
                        # FIX: Adăugăm ID-urile în format corect pentru subtitles
                        # Pentru seriale/episoade folosim ID-urile SHOW-ului
                        # =====================================================
                        if item_type == 'movie':
                            infos['tmdb_id'] = str(tmdb) if tmdb else ''
                            infos['imdb_id'] = str(imdb) if imdb else ''
                        else:
                            # Serial sau episod - folosim ID-urile show-ului
                            infos['tmdb_id'] = str(show_tmdb) if show_tmdb else ''
                            infos['imdb_id'] = str(show_imdb) if show_imdb else ''
                        # =====================================================
                        
                        # --- CONSTRUCTIE NUME SI QUERY ---
                        display_name = media_item.get('title')
                        search_query = display_name
                        
                        if item_type == 'episode':
                            show_title = item.get('show', {}).get('title')
                            season = media_item.get('season')
                            episode = media_item.get('number')
                            
                            if show_title:
                                display_name = '%s - S%02dE%02d - %s' % (show_title, season, episode, media_item.get('title'))
                                
                                if self.context_trakt_search_mode == '2':
                                    search_query = '%s S%02d' % (show_title, season)
                                else:
                                    search_query = '%s S%02dE%02d' % (show_title, season, episode)
                        
                        elif item_type == 'show':
                             pass

                        new_params = {'info': str(infos), 'Stype': self.sstype}
                        
                        # =====================================================
                        # FIX: Adăugăm ID-urile direct în parametri
                        # =====================================================
                        if infos.get('tmdb_id'):
                            new_params['tmdb_id'] = infos['tmdb_id']
                        if infos.get('imdb_id'):
                            new_params['imdb_id'] = infos['imdb_id']
                        # =====================================================
                        
                        if self.context_trakt_search_mode == '0':
                            new_params['modalitate'] = 'edit'
                            new_params['query'] = quote(search_query)
                        else:
                            new_params['searchSites'] = 'cuvant'
                            new_params['cuvant'] = quote(search_query)
                            
                        listings.append(self.drawItem(title = display_name,
                                          action = 'searchSites',
                                          link = new_params,
                                          image = poster))

                    if len(items) >= 30:
                        listings.append(self.drawItem(
                            title = 'Next >>',
                            action = 'openTrakt',
                            link = {
                                'openTrakt': 'listitems',
                                'list_id': list_id,
                                'username': username,
                                'page': str(page + 1)
                            },
                            image = next_icon
                        ))
                
                xbmcplugin.setContent(int(sys.argv[1]), 'movies')
                xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
                xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)

            elif action in ['popular','watched','trending','played', 'anticipated', 'favorited']:
                if action == 'popular':
                    tkturl = 'popular?limit=30&page=%s' % page
                elif action == 'watched':
                    tkturl = 'watched/weekly?limit=30&page=%s' % page
                elif action == 'trending':
                    tkturl = 'trending?limit=30&page=%s' % page
                elif action == 'played':
                    tkturl = 'played/weekly?limit=30&page=%s' % page
                elif action == 'anticipated':
                    tkturl = 'anticipated?limit=30&page=%s' % page
                elif action == 'favorited':
                    tkturl = 'favorited/weekly?limit=30&page=%s' % page
                
                movielist = trakt.getMovie(tkturl, full=True)
                if movielist:
                    for item in movielist:
                        try: 
                            if 'movie' in item: media_data = item.get('movie')
                            else: media_data = item
                        except: media_data = item

                        try: imdb = media_data.get('ids').get('imdb')
                        except: imdb = ''
                        
                        try: tmdb = media_data.get('ids').get('tmdb')
                        except: tmdb = ''
                        
                        tmdb_url = 'https://api.themoviedb.org/3/movie/%s?api_key=%s&language=en-US' % (tmdb, tmdb_key())
                        tmdb_data = fetchData(tmdb_url,rtype='json')
                        
                        poster = image
                        fanart = ''
                        try: poster_path = tmdb_data.get('poster_path')
                        except: poster_path = None
                        try: fanart_path = tmdb_data.get('backdrop_path')
                        except: fanart_path = None
                        
                        if poster_path: poster = 'https://image.tmdb.org/t/p/w500%s' % poster_path
                        if fanart_path: fanart = 'https://image.tmdb.org/t/p/w780%s' % fanart_path

                        infos = {}
                        infos['Title'] = media_data.get('title')
                        infos['Year'] = media_data.get('year')
                        infos['Premiered'] = media_data.get('released')
                        try: infos['Genre'] = ', '.join(media_data.get('genres', []))
                        except: infos['Genre'] = ''
                        infos['Rating'] = media_data.get('rating')
                        infos['Votes'] = media_data.get('votes')
                        infos['Plot'] = media_data.get('overview')
                        infos['Trailer'] = media_data.get('trailer')
                        try: infos['Duration'] = media_data.get('runtime', 0) * 60
                        except: pass
                        infos['imdb'] = imdb
                        infos['imdb_id'] = imdb
                        infos['tmdb_id'] = tmdb
                        infos['Poster'] = poster
                        infos['Fanart'] = fanart
                        infos['PlotOutline'] = media_data.get('tagline')
                        infos['mpaa'] = media_data.get('certification')
                        
                        # =====================================================
                        # FIX: Adăugăm ID-urile în format corect pentru subtitles
                        # =====================================================
                        infos['tmdb_id'] = str(tmdb) if tmdb else ''
                        infos['imdb_id'] = str(imdb) if imdb else ''
                        # =====================================================
                        
                        nume = media_data.get('title')
                        new_params = {'info': str(infos), 'Stype': self.sstype}
                        
                        # =====================================================
                        # FIX: Adăugăm ID-urile direct în parametri
                        # =====================================================
                        if tmdb:
                            new_params['tmdb_id'] = str(tmdb)
                        if imdb:
                            new_params['imdb_id'] = str(imdb)
                        # =====================================================
                        
                        if self.context_trakt_search_mode == '0':
                            new_params['modalitate'] = 'edit'
                            new_params['query'] = quote(nume)
                        else:
                            new_params['searchSites'] = 'cuvant'
                            new_params['cuvant'] = quote(nume)
                            
                        listings.append(self.drawItem(title = nume,
                                          action = 'searchSites',
                                          link = new_params,
                                          image = poster))
                    
                    listings.append(self.drawItem(title = 'Next >>',
                                          action = 'openTrakt',
                                          link = {'openTrakt': action, 'page': page + 1},
                                          image = next_icon))
                
                xbmcplugin.setContent(int(sys.argv[1]), 'movies')
                xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
                xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)

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
                            
                            # =====================================================
                            # FIX: Extragem și TMDb ID pentru calendar
                            # =====================================================
                            try:
                                tmdb = item['show']['ids'].get('tmdb')
                                if tmdb == None: tmdb = ''
                            except:
                                tmdb = ''
                            # =====================================================

                            last_watched = item['last_watched_at']
                            if last_watched == None or last_watched == '': last_watched = '0'
                            items.append({'imdb': imdb, 'tvdb': tvdb, 'tmdb': tmdb, 'tvshowtitle': tvshowtitle, 'year': year, 'snum': season, 'enum': episode, '_last_watched': last_watched})
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
                                
                                # =====================================================
                                # FIX: Păstrăm și TMDb ID
                                # =====================================================
                                tmdb = i.get('tmdb', '')
                                # =====================================================
                                
                                year = i['year']
                                
                                seelist.append({'imdb': imdb, 'tvdb': tvdb, 'tmdb': tmdb, 'tvshowtitle': tvshowtitle, 'year': year, 'snum': season, 'enum': episode, 'premiered': premiered, 'unaired': unaired, '_sort_key': max(i['_last_watched'], premiered), 'info': {'title': title, 'season': season, 'episode': episode, 'tvshowtitle': tvshowtitle, 'year': year, 'premiered': premiered, 'status': status, 'studio': studio, 'genre': genre, 'rating': rating, 'votes': votes, 'director': director, 'writer': writer, 'cast': cast, 'plot': plot, 'imdb': imdb, 'tvdb': tvdb, 'tmdb_id': str(tmdb) if tmdb else '', 'imdb_id': str(imdb) if imdb else '', 'Poster': poster}})
                        except: pass
                
                threads = []
                for i in items: threads.append(threading.Thread(name=i.get('tvshowtitle'), target=items_list, args=(i, seelist,)))
                get_threads(threads, 'Deschidere', 0)
                seelist = sorted(seelist, key=lambda k: k['premiered'], reverse=True)
                
                for show in seelist:
                    cm = []
                    nume_afisare = '%s - S%s E%s Data:%s' % (show.get('tvshowtitle'), show.get('snum'), show.get('enum'), show.get('premiered'))
                    if show.get('unaired') == 'true':
                        nume_afisare = '[COLOR red]%s[/COLOR]' % nume_afisare
                    
                    titluc = show.get('tvshowtitle')
                    sezon = int(show.get('snum'))
                    episod = int(show.get('enum'))
                    
                    search_query = ""
                    if self.context_trakt_search_mode == '2':
                         search_query = '%s S%02d' % (titluc, sezon)
                    else:
                         search_query = '%s S%02dE%02d' % (titluc, sezon, episod)
                    
                    cm.append(('Caută Variante', 'Container.Update(%s?action=searchSites&modalitate=edit&query=%s&Stype=%s)' % (sys.argv[0], quote(search_query), self.sstype)))
                    
                    new_params = {}
                    new_params['info'] = str(show.get('info'))
                    new_params['Stype'] = self.sstype
                    
                    # =====================================================
                    # FIX: Adăugăm ID-urile direct în parametri pentru calendar
                    # =====================================================
                    if show.get('tmdb'):
                        new_params['tmdb_id'] = str(show.get('tmdb'))
                    if show.get('imdb') and show.get('imdb') != '0':
                        new_params['imdb_id'] = str(show.get('imdb'))
                    # =====================================================
                    
                    if self.context_trakt_search_mode == '0':
                        new_params['modalitate'] = 'edit'
                        new_params['query'] = quote(search_query)
                    else:
                        new_params['searchSites'] = 'cuvant'
                        new_params['cuvant'] = quote(search_query)

                    if show.get('unaired') and not showunreleased:
                        continue
                        
                    cm.append(self.CM('markTrakt', 'watched', params={'id': show.get('tvdb'), 'sezon' : show.get('snum'), 'episod': show.get('enum')}))
                    cm.append(self.CM('markTrakt', 'delete', params={'id': show.get('tvdb'), 'sezon' : show.get('snum'), 'episod': show.get('enum')}))
                    
                    listings.append(self.drawItem(title = nume_afisare,
                                          action = 'searchSites',
                                          link = new_params,
                                          image = search_icon,
                                          contextMenu = cm))
                
                xbmcplugin.setContent(int(sys.argv[1]), 'episodes')
                xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
                xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)
    

# === FUNCTIA OPEN TMDB (FIX IMAGINI EPISOADE + RESTUL NESCHIMBAT) ===
    def openTMDB(self, params={}):
        listings = []
        get = params.get
        action = get('action_tmdb')
        endpoint = unquote(get('endpoint', ''))
        page = int(get('page') or 1)
        
        tmdb_api_key = tmdb_key()
        lang = 'en-US'
        
        tmdb_icon = os.path.join(xbmcaddon.Addon().getAddonInfo('path'), 'resources', 'media', 'tmdb.png')
        
        base_poster = 'https://image.tmdb.org/t/p/w500'
        base_fanart = 'https://image.tmdb.org/t/p/w1280'
        
        today = datetime.date.today().strftime('%Y-%m-%d')
        
        if not action:
            listings.append(self.drawItem(title='[B][COLOR white]Filme[/COLOR][/B]', action='openTMDB', link={'action_tmdb': 'movies_menu'}, image=tmdb_icon))
            listings.append(self.drawItem(title='[B][COLOR white]Seriale[/COLOR][/B]', action='openTMDB', link={'action_tmdb': 'tv_menu'}, image=tmdb_icon))
            xbmcplugin.setContent(int(sys.argv[1]), '')
            xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
            xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)
            return

        elif action == 'movies_menu':
            # === BUTON CĂUTARE FILME ===
            listings.append(self.drawItem(title='[B][COLOR FF00CED1]Caută Filme[/COLOR][/B]', action='openTMDB', link={'action_tmdb': 'search_tmdb', 'search_type': 'movie'}, image=tmdb_icon))
            cats = [
                ('[B][COLOR FFFDBD01]Trending (Azi)[/COLOR][/B]', 'trending/movie/day'),
                ('[B]Trending (Saptamana asta)[/B]', 'trending/movie/week'),
                ('[B]Popular (All Time)[/B]', 'movie/popular'),
                ('[B]In Cinematografe (Acum)[/B]', 'movie/now_playing'),
                ('[B]Upcoming (Vin Curand)[/B]', 'movie/upcoming'),
                ('[B]Blockbusters (Lansate)[/B]', 'discover/movie?sort_by=revenue.desc&primary_release_date.lte=%s' % today),
                ('[B]Top Rated (Cele mai apreciate)[/B]', 'movie/top_rated'),
                ('[B]Comedy (Comedie)[/B]', 'discover/movie?with_genres=35&sort_by=popularity.desc'),
                ('[B]Romance (Dragoste)[/B]', 'discover/movie?with_genres=10749&sort_by=popularity.desc'),
                ('[B]Actiune & Aventura[/B]', 'discover/movie?with_genres=28,12&sort_by=popularity.desc'),
                ('[B]Animatie[/B]', 'discover/movie?with_genres=16&sort_by=popularity.desc'),
                ('[B]Horror & Thriller[/B]', 'discover/movie?with_genres=27,53&sort_by=popularity.desc')
            ]
            for name, ep in cats:
                listings.append(self.drawItem(title=name, action='openTMDB', link={'action_tmdb': 'list_content', 'endpoint': ep, 'mediatype': 'movie'}, image=tmdb_icon))
            xbmcplugin.setContent(int(sys.argv[1]), '')
            xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
            xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)
            return

        elif action == 'tv_menu':
            # === BUTON CĂUTARE SERIALE ===
            listings.append(self.drawItem(title='[B][COLOR FF00CED1]Caută Seriale[/COLOR][/B]', action='openTMDB', link={'action_tmdb': 'search_tmdb', 'search_type': 'tv'}, image=tmdb_icon))
            
            cats = [
                ('[B][COLOR FFFDBD01]Trending (Azi)[/COLOR][/B]', 'trending/tv/day'),
                ('[B]Trending (Saptamana asta)[/B]', 'trending/tv/week'),
                ('[B]Popular (All Time)[/B]', 'tv/popular'),
                ('[B]Airing Today (Noi Azi)[/B]', 'tv/airing_today'),
                ('[B]On The Air (Saptamana asta)[/B]', 'tv/on_the_air'),
                ('[B]Top Rated[/B]', 'tv/top_rated'),
                ('[B]Seriale Noi (Premiere)[/B]', 'discover/tv?sort_by=first_air_date.desc&first_air_date.lte=%s' % today),
                ('[B]Upcoming (Vor aparea)[/B]', 'discover/tv?sort_by=first_air_date.asc&first_air_date.gte=%s' % today),
                ('[B]Comedy (Comedie)[/B]', 'discover/tv?with_genres=35&sort_by=popularity.desc'),
                ('[B]Romance (Dragoste)[/B]', 'discover/tv?with_genres=10749&sort_by=popularity.desc'),
                ('[B]Sci-Fi & Fantasy[/B]', 'discover/tv?with_genres=10765&sort_by=popularity.desc'),
                ('[B]Action & Adventure[/B]', 'discover/tv?with_genres=10759&sort_by=popularity.desc')
            ]
            for name, ep in cats:
                listings.append(self.drawItem(title=name, action='openTMDB', link={'action_tmdb': 'list_content', 'endpoint': ep, 'mediatype': 'tv'}, image=tmdb_icon))
            xbmcplugin.setContent(int(sys.argv[1]), '')
            xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
            xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)
            return

        # === CĂUTARE TMDB ===
        elif action == 'search_tmdb':
            search_type = get('search_type', 'movie')  # movie sau tv
            query = get('query', '')
            
            # Dacă nu avem query, afișăm keyboard
            if not query:
                keyboard = xbmc.Keyboard('', 'Caută %s:' % ('Filme' if search_type == 'movie' else 'Seriale'))
                keyboard.doModal()
                if keyboard.isConfirmed():
                    query = keyboard.getText().strip()
                else:
                    return
            
            if not query:
                return
            
            page = int(get('page') or 1)
            content_type = 'movies' if search_type == 'movie' else 'tvshows'
            xbmcplugin.setContent(int(sys.argv[1]), content_type)
            
            # Căutare pe TMDB
            url = 'https://api.themoviedb.org/3/search/%s?api_key=%s&language=%s&query=%s&page=%s' % (
                search_type, tmdb_api_key, lang, quote(query), page
            )
            
            data = fetchData(url, rtype='json')
            if not data: return
            
            results = data.get('results', [])
            
            for item in results:
                try:
                    title = item.get('title') or item.get('name')
                    if not title: continue
                    
                    release_date = item.get('release_date') or item.get('first_air_date')
                    year = release_date[:4] if release_date else ''
                    
                    poster = base_poster + item.get('poster_path') if item.get('poster_path') else tmdb_icon
                    backdrop = base_fanart + item.get('backdrop_path') if item.get('backdrop_path') else ''
                    
                    overview = item.get('overview', '')
                    if overview: overview = overview.replace('+', ' ')
                    
                    rating = str(item.get('vote_average', '0.0'))[:3]
                    tmdb_id = str(item.get('id'))
                    
                    # Verifică dacă e upcoming
                    is_upcoming = False
                    if release_date and release_date > today:
                        is_upcoming = True
                    
                    # Formatare titlu
                    if is_upcoming:
                        display_title = '[COLOR gray][B]%s[/B][/COLOR]' % title
                        if year: 
                            display_title += ' [COLOR red](%s)[/COLOR]' % year
                        display_title += ' [COLOR red][UPCOMING][/COLOR]'
                    else:
                        display_title = '[B]%s[/B]' % title
                        if year: 
                            display_title += ' [B][COLOR yellow](%s)[/COLOR][/B]' % year
                    
                    kodi_type = 'movie' if search_type == 'movie' else 'tvshow'
                    
                    info_display = {
                        'Title': title,
                        'Year': year,
                        'Plot': overview,
                        'Rating': float(rating) if rating else 0.0,
                        'Premiered': release_date,
                        'mediatype': kodi_type
                    }
                    
                    if search_type == 'movie':
                        search_params = {
                            'searchSites': 'cuvant',
                            'cuvant': title,
                            'info': str(info_display),
                            'tmdb_id': tmdb_id,
                            'Stype': self.sstype
                        }
                        next_action = 'searchSites'
                    else:
                        info_display['TVShowTitle'] = title
                        search_params = {
                            'action_tmdb': 'tv_seasons',
                            'tmdb_id': tmdb_id,
                            'show_title': quote(title),
                            'poster': quote(poster),
                            'fanart': quote(backdrop),
                            'plot': quote(overview),
                            'year': year,
                            'rating': rating,
                            'info': str(info_display)
                        }
                        next_action = 'openTMDB'
                    
                    listings.append(self.drawItem(
                        title=display_title,
                        action=next_action,
                        link=search_params,
                        image=poster
                    ))
                except:
                    pass
            
            # Paginare
            current_page = int(data.get('page', 0))
            total_pages = int(data.get('total_pages', 0))
            
            if current_page < total_pages:
                listings.append(self.drawItem(
                    title='[COLOR lime]Next >>[/COLOR]',
                    action='openTMDB',
                    link={'action_tmdb': 'search_tmdb', 'search_type': search_type, 'query': query, 'page': str(page + 1)},
                    image=next_icon
                ))
            
            xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
            xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)
            return
        
        elif action == 'list_content':
            mediatype_force = get('mediatype')
            content_type = 'movies' if mediatype_force == 'movie' else 'tvshows'
            xbmcplugin.setContent(int(sys.argv[1]), content_type)

            url = 'https://api.themoviedb.org/3/%s' % endpoint
            sep = '&' if '?' in url else '?'
            url += '%sapi_key=%s&language=%s&page=%s' % (sep, tmdb_api_key, lang, page)
            
            data = fetchData(url, rtype='json')
            if not data: return

            results = data.get('results', [])

            for item in results:
                try:
                    m_type = item.get('media_type') or mediatype_force
                    
                    if m_type == 'movie':
                        kodi_type = 'movie'
                    else:
                        kodi_type = 'tvshow'

                    title = item.get('title') or item.get('name')
                    if not title: continue
                    
                    release_date = item.get('release_date') or item.get('first_air_date')
                    year = release_date[:4] if release_date else ''
                    
                    poster = base_poster + item.get('poster_path') if item.get('poster_path') else tmdb_icon
                    backdrop = base_fanart + item.get('backdrop_path') if item.get('backdrop_path') else ''
                    
                    overview = item.get('overview', '')
                    if overview: overview = overview.replace('+', ' ')
                    
                    rating = str(item.get('vote_average', '0.0'))[:3]
                    tmdb_id = str(item.get('id'))
                    
                    # === VERIFICĂ DACĂ E UPCOMING ===
                    is_upcoming = False
                    if release_date and release_date > today:
                        is_upcoming = True
                    
                    # === FORMATARE TITLU CU CULOARE ===
                    if is_upcoming:
                        # Culoare diferită pentru nelansate (gri + indicator roșu)
                        display_title = '[COLOR red][B]%s[/B][/COLOR]' % title
                        if year: 
                            display_title += ' [COLOR yellow][B](%s)[/B][/COLOR]' % year
                        display_title += ' [COLOR pink][UPCOMING][/COLOR]'
                    else:
                        # Culoare normală pentru lansate
                        display_title = '[B]%s[/B]' % title
                        if year: 
                            display_title += ' [B][COLOR yellow](%s)[/COLOR][/B]' % year
                    # =================================

                    info_display = {
                        'Title': title,
                        'Year': year,
                        'Plot': overview,
                        'Rating': float(rating) if rating else 0.0,
                        'Premiered': release_date,
                        'mediatype': kodi_type
                    }

                    if kodi_type == 'movie':
                        search_params = {
                            'searchSites': 'cuvant',
                            'cuvant': title,
                            'info': str(info_display), 
                            'tmdb_id': tmdb_id,
                            'Stype': self.sstype
                        }
                        next_action = 'searchSites'
                    else:
                        info_display['TVShowTitle'] = title
                        search_params = {
                            'action_tmdb': 'tv_seasons',
                            'tmdb_id': tmdb_id,
                            'show_title': quote(title),
                            'poster': quote(poster),
                            'fanart': quote(backdrop),
                            'plot': quote(overview), 
                            'year': year,
                            'rating': rating,
                            'info': str(info_display) 
                        }
                        next_action = 'openTMDB'

                    listings.append(self.drawItem(
                        title=display_title,
                        action=next_action,
                        link=search_params,
                        image=poster
                    ))
                except: pass

            current_page = int(data.get('page', 0)) if data else 0
            total_pages = int(data.get('total_pages', 0)) if data else 0
            
            if data and current_page < total_pages:
                listings.append(self.drawItem(
                    title='[COLOR lime]Next >>[/COLOR]', 
                    action='openTMDB', 
                    link={'action_tmdb': 'list_content', 'endpoint': endpoint, 'page': str(page + 1), 'mediatype': mediatype_force}, 
                    image=next_icon
                ))

            xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
            xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)
            return

        elif action == 'tv_seasons':
            xbmcplugin.setContent(int(sys.argv[1]), 'seasons')
            
            show_id = get('tmdb_id')
            show_title = unquote(get('show_title'))
            show_poster = unquote(get('poster'))
            show_fanart = unquote(get('fanart'))
            
            show_plot = unquote(get('plot') or '').replace('+', ' ')
            
            show_rating = get('rating', '')
            show_year = get('year', '')
            
            url = 'https://api.themoviedb.org/3/tv/%s?api_key=%s&language=%s' % (show_id, tmdb_api_key, lang)
            data = fetchData(url, rtype='json')
            if not data: return
            
            seasons = data.get('seasons', [])
            
            for season in seasons:
                s_num = season.get('season_number')
                if s_num == 0: continue 
                
                s_name = season.get('name')
                ep_count = season.get('episode_count')
                s_air_date = season.get('air_date')
                s_year = s_air_date[:4] if s_air_date else show_year
                s_poster = base_poster + season.get('poster_path') if season.get('poster_path') else show_poster
                
                s_overview = season.get('overview')
                if not s_overview: s_overview = show_plot
                if s_overview: s_overview = s_overview.replace('+', ' ')
                
                # === VERIFICĂ DACĂ SEZONUL E UPCOMING ===
                is_upcoming = False
                if s_air_date and s_air_date > today:
                    is_upcoming = True
                
                # === FORMATARE TITLU CU CULOARE ===
                if is_upcoming:
                    title = '[COLOR red][B]%s[/B][/COLOR] [COLOR orange](%s ep)[/COLOR]' % (s_name, ep_count)
                    if s_year: 
                        title += ' [B][COLOR yellow](%s)[/COLOR][/B]' % s_year
                    title += ' [COLOR pink][UPCOMING][/COLOR]'
                else:
                    title = '[B]%s[/B] [COLOR orange](%s ep)[/COLOR]' % (s_name, ep_count)
                    if s_year: 
                        title += ' [B][COLOR yellow](%s)[/COLOR][/B]' % s_year
                # =====================================
                
                info_season = {
                    'Title': s_name,
                    'TVShowTitle': show_title,
                    'Season': int(s_num),
                    'Plot': s_overview,
                    'Rating': float(show_rating) if show_rating else 0.0,
                    'Premiered': s_air_date,
                    'Poster': s_poster,
                    'Fanart': show_fanart,
                    'mediatype': 'season'
                }
                
                params_ep = {
                    'action_tmdb': 'tv_episodes',
                    'tmdb_id': show_id,
                    'season': str(s_num),
                    'show_title': quote(show_title),
                    'poster': quote(s_poster), 
                    'fanart': quote(show_fanart),
                    'plot': quote(s_overview),
                    'rating': show_rating,
                    'info': str(info_season)
                }
                
                listings.append(self.drawItem(
                    title=title,
                    action='openTMDB',
                    link=params_ep,
                    image=s_poster
                ))
                
            xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
            xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)
            return

        elif action == 'tv_episodes':
            xbmcplugin.setContent(int(sys.argv[1]), 'episodes')
            
            show_id = get('tmdb_id')
            season_num = get('season')
            
            # === FIX DOUBLE ENCODING ===
            raw_title = get('show_title') or ''
            show_title = unquote(unquote(raw_title)).replace('+', ' ')
            
            raw_poster = get('poster') or ''
            season_poster = unquote(unquote(raw_poster))
            
            raw_fanart = get('fanart') or ''
            show_fanart = unquote(unquote(raw_fanart))
            # ===========================
            
            s_rating = get('rating', '')
            
            url = 'https://api.themoviedb.org/3/tv/%s/season/%s?api_key=%s&language=%s' % (show_id, season_num, tmdb_api_key, lang)
            data = fetchData(url, rtype='json')
            if not data: return
            
            episodes = data.get('episodes', [])
            
            for ep in episodes:
                try:
                    ep_num = ep.get('episode_number')
                    ep_name = ep.get('name')
                    
                    overview = ep.get('overview', '')
                    if overview: overview = overview.replace('+', ' ')
                    
                    air_date = ep.get('air_date')
                    
                    rating = str(ep.get('vote_average', 0.0))[:3]
                    if rating == '0.0' and s_rating: rating = s_rating 
                    
                    runtime_min = ep.get('runtime')
                    duration_sec = (runtime_min * 60) if runtime_min else 0
                    
                    ep_code = 'S%02dE%02d' % (int(season_num), int(ep_num))
                    
                    # === VERIFICĂ DACĂ EPISODUL E UPCOMING ===
                    is_upcoming = False
                    if air_date and air_date > today:
                        is_upcoming = True
                    
                    # === FORMATARE TITLU CU CULOARE ===
                    if is_upcoming:
                        # Episod nelansate - culoare gri + indicator
                        display_title = '[COLOR red][B]%s - %s[/B][/COLOR]' % (ep_code, ep_name)
                        if air_date:
                            display_title += ' [COLOR yellow](%s)[/COLOR]' % air_date
                    else:
                        # Episod lansat - culoare normală
                        display_title = '[B]%s - %s[/B]' % (ep_code, ep_name)
                    # =====================================
                    
                    search_term = '%s %s' % (show_title, ep_code)
                    
                    # --- FIX THUMBNAILS ---
                    ep_path = ep.get('still_path')
                    if ep_path:
                        still = 'https://image.tmdb.org/t/p/w500' + ep_path
                    else:
                        if season_poster: 
                            still = season_poster
                        elif show_fanart: 
                            still = show_fanart
                        else: 
                            still = tmdb_icon
                    # ----------------------

                    info_dict = {
                        'Title': ep_name,
                        'TVShowTitle': show_title,
                        'Season': int(season_num),
                        'Episode': int(ep_num),
                        'Plot': overview,
                        'Premiered': air_date,
                        'Rating': float(rating) if rating else 0.0,
                        'Duration': duration_sec,
                        'mediatype': 'episode'
                    }
                    
                    search_params = {
                        'searchSites': 'cuvant',
                        'cuvant': search_term,
                        'info': str(info_dict),
                        'tmdb_id': show_id,
                        'Stype': self.sstype
                    }
                    
                    cm = []
                    cm.append(('Cauta Variante', 'Container.Update(%s?action=searchSites&modalitate=edit&query=%s&Stype=%s)' % (sys.argv[0], quote(search_term), self.sstype)))

                    listings.append(self.drawItem(
                        title=display_title,
                        action='searchSites',
                        link=search_params,
                        image=still,
                        contextMenu=cm
                    ))
                except Exception as e:
                    pass
                
            xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
            xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)
            return

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
            # --- MENIU PRINCIPAL IMDb (Stilizat) ---
            methods['actions'] = 'list_genres'
            methods['base_start'] = 'genuri'
            listings.append(self.drawItem(title = '[B][COLOR white]Genuri[/COLOR][/B]',
                                          action = 'openIMDb',
                                          link = methods,
                                          image = i.thumb))
            methods['actions'] = 'search'
            methods['base_start'] = 'tipuri'
            methods['title_type'] = 'mini_series'
            listings.append(self.drawItem(title = '[B][COLOR white]Mini Serii[/COLOR][/B]',
                                          action = 'openIMDb',
                                          link = methods,
                                          image = i.thumb))
            methods['title_type'] = 'tv_series'
            listings.append(self.drawItem(title = '[B][COLOR white]Seriale[/COLOR][/B]',
                                          action = 'openIMDb',
                                          link = methods,
                                          image = i.thumb))
            methods['title_type'] = 'movie'
            listings.append(self.drawItem(title = '[B][COLOR white]Filme[/COLOR][/B]',
                                          action = 'openIMDb',
                                          link = methods,
                                          image = i.thumb))
            methods['title_type'] = 'video'
            listings.append(self.drawItem(title = '[B][COLOR white]Video[/COLOR][/B]',
                                          action = 'openIMDb',
                                          link = methods,
                                          image = i.thumb))
            methods['groups'] = 'top_100'
            methods['title_type'] = ''
            methods['base_start'] = ''
            listings.append(self.drawItem(title = '[B][COLOR white]Top 100[/COLOR][/B]',
                                          action = 'openIMDb',
                                          link = methods,
                                          image = i.thumb))
            methods['groups'] = 'top_250'
            listings.append(self.drawItem(title = '[B][COLOR white]Top 250[/COLOR][/B]',
                                          action = 'openIMDb',
                                          link = methods,
                                          image = i.thumb))
            methods['groups'] = 'top_1000'
            listings.append(self.drawItem(title = '[B][COLOR white]Top 1000[/COLOR][/B]',
                                          action = 'openIMDb',
                                          link = methods,
                                          image = i.thumb))
            
            # Fix pentru iconite
            xbmcplugin.setContent(int(sys.argv[1]), '')
            xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
            xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)
            return

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
        
        # Definim explicit imaginea corecta folosind variabila globala 'media'
        c_thumb = os.path.join(media, 'cinemagia.png')

        if not get('meniu'):
            listings.append(self.drawItem(title = '[B][COLOR white]Liste utilizatori[/COLOR][/B]',
                                      action = 'openCinemagia',
                                      link = {'meniu': 'liste', 'url': '%s/liste/filme/?pn=1' % c.base_url},
                                      image = c_thumb))
            listings.append(self.drawItem(title = '[B][COLOR white]Filme[/COLOR][/B]',
                                      action = 'openCinemagia',
                                      link = {'meniu': 'all', 'url': '%s/filme/?pn=1' % c.base_url},
                                      image = c_thumb))
            listings.append(self.drawItem(title = '[B][COLOR white]Seriale[/COLOR][/B]',
                                      action = 'openCinemagia',
                                      link = {'meniu': 'all', 'url': '%s/seriale-tv/?pn=1' % c.base_url},
                                      image = c_thumb))
            listings.append(self.drawItem(title = '[B][COLOR white]Filme după țări[/COLOR][/B]',
                                      action = 'openCinemagia',
                                      link = {'meniu': 'tari', 'url': '%s/filme/?pn=1' % c.base_url},
                                      image = c_thumb))
            listings.append(self.drawItem(title = '[B][COLOR white]Filme după gen[/COLOR][/B]',
                                      action = 'openCinemagia',
                                      link = {'meniu': 'gen', 'url': '%s/filme/?pn=1' % c.base_url},
                                      image = c_thumb))
            listings.append(self.drawItem(title = '[B][COLOR white]Filme după ani[/COLOR][/B]',
                                      action = 'openCinemagia',
                                      link = {'meniu': 'ani', 'url': '%s/filme/?pn=1' % c.base_url},
                                      image = c_thumb))
            listings.append(self.drawItem(title = '[B][COLOR white]Seriale după țări[/COLOR][/B]',
                                      action = 'openCinemagia',
                                      link = {'meniu': 'tari', 'url': '%s/seriale-tv/?pn=1' % c.base_url},
                                      image = c_thumb))
            listings.append(self.drawItem(title = '[B][COLOR white]Seriale după gen[/COLOR][/B]',
                                      action = 'openCinemagia',
                                      link = {'meniu': 'gen', 'url': '%s/seriale-tv/?pn=1' % c.base_url},
                                      image = c_thumb))
            listings.append(self.drawItem(title = '[B][COLOR white]Seriale după ani[/COLOR][/B]',
                                      action = 'openCinemagia',
                                      link = {'meniu': 'ani', 'url': '%s/seriale-tv/?pn=1' % c.base_url},
                                      image = c_thumb))
            
            # Fix iconite
            xbmcplugin.setContent(int(sys.argv[1]), '')
            xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
            xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)
            return

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
            # AM SCHIMBAT NUMELE VARIABILEI DIN 'media' IN 'video_item' PENTRU A EVITA CONFLICTUL
            for video_item in listmedia:
                cm = []
                getm = video_item.get
                cm.append(('Caută Variante', 'Container.Update(%s?action=searchSites&modalitate=edit&query=%s&Stype=%s)' % (sys.argv[0], quote(getm('info').get('Title')), self.sstype)))
                if getm('info').get('IMDBNumber'): self.getMetacm(url, getm('info').get('Title'), cm, getm('info').get('IMDBNumber'))
                else: self.getMetacm(url, getm('info').get('Title'), cm)
                if self.youtube == '1':
                    cm.append(('Caută în Youtube', 'RunPlugin(%s?action=YoutubeSearch&url=%s)' % (sys.argv[0], quote(getm('info').get('Title')))))
                
                # === MODIFICARE ANGELITTO: Pregatire parametri cu ID-uri ===
                search_params = {'searchSites': 'cuvant',
                                'cuvant': getm('info').get('Title'),
                                'info': getm('info')}
                
                # Adaugam explicit ID-urile ca parametri separati pentru siguranta
                if getm('info').get('imdb_id'): search_params['imdb_id'] = getm('info')['imdb_id']
                if getm('info').get('IMDBNumber'): search_params['imdb_id'] = getm('info')['IMDBNumber']
                # ==========================================================
                
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
                                      image = c_thumb))
            # Fix iconite pentru submeniuri
            xbmcplugin.setContent(int(sys.argv[1]), '')
            xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
            xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)
            return

        elif meniu == 'tarigen' or meniu == 'gentari':
            listtari = c.gettari(url, 'tari' if meniu == 'tarigen' else 'gen')
            for number, legatura, nume in listtari:
                listings.append(self.drawItem(title = nume,
                                      action = 'openCinemagia',
                                      link = {'meniu': 'listtari', 'url': legatura, 'info': {}},
                                      image = c_thumb))
            # Fix iconite
            xbmcplugin.setContent(int(sys.argv[1]), '')
            xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
            xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)
            return

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
                                      image = c_thumb))
            # Fix iconite
            xbmcplugin.setContent(int(sys.argv[1]), '')
            xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
            xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)
            return

        elif meniu == 'listtari':
            listmedia = c.listmovies(url, 'filme')
            if get('tari'):
                nume = unquote(get('tari'))
                listings.append(self.drawItem(title = '[COLOR lime]Genuri din %s[/COLOR]' % nume,
                                      action = 'openCinemagia',
                                      link = {'meniu': 'gentari', 'url': url},
                                      image = c_thumb))
            if get('genuri'):
                nume = unquote(get('genuri'))
                listings.append(self.drawItem(title = '[COLOR lime]%s pe țări[/COLOR]' % nume,
                                      action = 'openCinemagia',
                                      link = {'meniu': 'tarigen', 'url': url},
                                      image = c_thumb))
            # AM SCHIMBAT NUMELE VARIABILEI DIN 'media' IN 'video_item'
            for video_item in listmedia:
                cm = []
                getm = video_item.get
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
                    
                    # === MODIFICARE ANGELITTO: Pregatire parametri cu ID-uri ===
                    search_params = {'searchSites': 'cuvant',
                                    'cuvant': getm('info').get('Title'),
                                    'info': getm('info')}
                    
                    if getm('info').get('imdb_id'): search_params['imdb_id'] = getm('info')['imdb_id']
                    if getm('info').get('IMDBNumber'): search_params['imdb_id'] = getm('info')['IMDBNumber']
                    # ==========================================================
                    
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
            # AM SCHIMBAT NUMELE VARIABILEI DIN 'media' IN 'video_item'
            for video_item in listmedia:
                cm = []
                getm = video_item.get
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
                    
                    # === MODIFICARE ANGELITTO: Pregatire parametri cu ID-uri ===
                    search_params = {'searchSites': 'cuvant',
                                    'cuvant': getm('info').get('Title'),
                                    'info': getm('info')}
                    
                    if getm('info').get('imdb_id'): search_params['imdb_id'] = getm('info')['imdb_id']
                    if getm('info').get('IMDBNumber'): search_params['imdb_id'] = getm('info')['IMDBNumber']
                    # ==========================================================
                    
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
        # MODIFICARE: Eliminat verificarea streams. Luam direct din torrents.
        imp = getattr(torrents, site)
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
        # MODIFICARE: Folosim doar __alltr__ (torenti activi)
        result = thread_me(__alltr__, params, 'categorii')
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
                # MODIFICARE: Eliminat verificarea streams
                if cat_plot[2].get('site') in torrents.torrentsites:
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
                    # MODIFICARE: Eliminat logica streams
                    if params.get('site') in torrents.torrentsites:
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
        # ===== ÎNCEPUTUL MODIFICĂRII FINALE: Funcția a fost făcută mai robustă. =====
        # Acum, dacă un ID IMDb nu este găsit, funcția va căuta pe TMDb direct după numele torrentului,
        # în loc să afișeze o eroare. Acest lucru asigură funcționalitate maximă.
        
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

        if metadata == "IMDb":
            try:
                tmdb_id = None
                media_type = None

                # Calea 1: Avem ID IMDb. Căutăm direct folosind ID-ul (cea mai precisă metodă).
                if imdb:
                    log('[MRSP-META] Preluare date de pe TMDb folosind IMDb ID: %s' % imdb)
                    find_url = 'https://api.themoviedb.org/3/find/%s?api_key=%s&language=ro-RO&external_source=imdb_id' % (imdb, tmdb_key())
                    find_data = fetchData(find_url, rtype='json')
                    
                    if find_data.get('movie_results'):
                        tmdb_id = find_data['movie_results'][0]['id']
                        media_type = 'movie'
                        log('[MRSP-META] Găsit ca film pe TMDb (via IMDb ID). ID: %s' % tmdb_id)
                    elif find_data.get('tv_results'):
                        tmdb_id = find_data['tv_results'][0]['id']
                        media_type = 'tv'
                        log('[MRSP-META] Găsit ca serial pe TMDb (via IMDb ID). ID: %s' % tmdb_id)
                
                # Calea 2: NU avem ID IMDb. Căutăm pe TMDb după numele torrentului.
                else:
                    log('[MRSP-META] IMDb ID lipsă. Se încearcă căutarea pe TMDb după nume: "%s"' % nume)
                    search_title = nume
                    search_year = an

                    # Încercăm mai întâi să căutăm ca film
                    search_url = 'https://api.themoviedb.org/3/search/movie?api_key=%s&query=%s' % (tmdb_key(), quote(search_title))
                    if search_year: search_url += '&year=%s' % search_year
                    search_data = fetchData(search_url, rtype='json')

                    if search_data and search_data.get('results'):
                        tmdb_id = search_data['results'][0]['id']
                        media_type = 'movie'
                        log('[MRSP-META] Găsit ca film pe TMDb prin căutare după nume. ID: %s' % tmdb_id)
                    else:
                        # Dacă nu găsim film, încercăm ca serial
                        search_url = 'https://api.themoviedb.org/3/search/tv?api_key=%s&query=%s' % (tmdb_key(), quote(search_title))
                        if search_year: search_url += '&first_air_date_year=%s' % search_year
                        search_data = fetchData(search_url, rtype='json')
                        if search_data and search_data.get('results'):
                            tmdb_id = search_data['results'][0]['id']
                            media_type = 'tv'
                            log('[MRSP-META] Găsit ca serial pe TMDb prin căutare după nume. ID: %s' % tmdb_id)

                # Dacă niciuna dintre metode nu a găsit un rezultat, afișăm eroare și ieșim.
                if not tmdb_id:
                    showMessage("Eroare", "Filmul/Serialul nu a fost găsit pe TMDb.", forced=True)
                    return

                # De aici, logica este comună: preluăm detaliile folosind ID-ul TMDb găsit.
                details_url = 'https://api.themoviedb.org/3/%s/%s?api_key=%s&language=ro-RO&append_to_response=credits,videos' % (media_type, tmdb_id, tmdb_key())
                tmdb_data = fetchData(details_url, rtype='json')

                if not tmdb_data:
                    showMessage("Eroare", "Nu s-au putut prelua detaliile de pe TMDb.", forced=True)
                    return
                
                # "Traducem" datele din formatul TMDb în formatul pe care îl așteaptă fereastra video_info.xml
                cast_list = ['%s [COLOR lime]as %s[/COLOR]' % (a.get('name'), a.get('character')) if a.get('character') else a.get('name') for a in tmdb_data.get('credits', {}).get('cast', [])[:15]]
                directors = ", ".join([c.get('name') for c in tmdb_data.get('credits', {}).get('crew', []) if c.get('job') == 'Director'])
                writers = ", ".join(list(set([c.get('name') for c in tmdb_data.get('credits', {}).get('crew', []) if c.get('job') in ['Writer', 'Screenplay', 'Story']])))
                
                trailer = ''
                for video in tmdb_data.get('videos', {}).get('results', []):
                    if video.get('site') == 'YouTube' and video.get('type') == 'Trailer':
                        trailer = 'https://www.youtube.com/watch?v=%s' % video.get('key')
                        break
                
                imdb_style_meta = {
                    'poster_path': 'https://image.tmdb.org/t/p/w500%s' % tmdb_data.get('poster_path') if tmdb_data.get('poster_path') else '',
                    'backdrop_path': 'https://image.tmdb.org/t/p/w780%s' % tmdb_data.get('backdrop_path') if tmdb_data.get('backdrop_path') else '',
                    'Title': tmdb_data.get('title') or tmdb_data.get('name'),
                    'original_title': tmdb_data.get('original_title') or tmdb_data.get('original_name'),
                    'Country': ", ".join([c.get('name') for c in tmdb_data.get('production_countries', [])]),
                    'castandchar': ", ".join(cast_list),
                    'Genre': ", ".join([g.get('name') for g in tmdb_data.get('genres', [])]),
                    'Company': ", ".join([p.get('name') for p in tmdb_data.get('production_companies', [])]),
                    'overview': tmdb_data.get('overview', ''),
                    'Language': ", ".join([l.get('english_name') for l in tmdb_data.get('spoken_languages', [])]),
                    'IMdb Rating': ('%s din %s voturi' % (tmdb_data.get('vote_average'), tmdb_data.get('vote_count'))) if tmdb_data.get('vote_average') else '',
                    'Released': tmdb_data.get('release_date') or tmdb_data.get('first_air_date'),
                    'Tagline': tmdb_data.get('tagline', ''),
                    'Writer': writers,
                    'Director': directors,
                    'Runtime': str(datetime.timedelta(minutes=tmdb_data.get('runtime') or (tmdb_data.get('episode_run_time') or [0])[0])),
                    'Trailer': trailer,
                    'Seasons': str(tmdb_data.get('number_of_seasons', '')),
                    'Total aired': 'Total: %s episoade' % str(tmdb_data.get('number_of_episodes', '')) if 'number_of_episodes' in tmdb_data else '',
                    'imdb': imdb
                }
                
                # Deschidem fereastra și îi trimitem direct datele "traduse"
                from resources.lib.windows.video_info import VideoInfoXML
                transPath = xbmcvfs.translatePath if py3 else xbmc.translatePath
                try: addonpath = transPath(ROOT.decode('utf-8'))
                except: addonpath = transPath(ROOT)
                
                window = VideoInfoXML('video_info.xml', addonpath, 'Default', meta=imdb_style_meta, nameorig=nameorig, imdb=imdb)
                action, code = window.run()
                del window

                if action == 'search_name':
                    xbmc.executebuiltin('Container.Update(%s?action=searchSites&modalitate=edit&query=%s)' % (sys.argv[0], code))

            except Exception as e:
                log('Eroare critică în getMeta (TMDb): %s' % str(e))
                import traceback
                log(traceback.format_exc())
                showMessage("Eroare TMDb", "Nu s-au putut prelua datele. Verificați log-ul.", forced=True)

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
        get = params.get
        switch = get('switch')
        link = unquote(get('link'))
        nume = get('nume')
        site = get('site')
        torraction = get('torraction')
        info_str = unquote(get('info')) if get('info') else None
        
        kodi_context = {}
        kodi_dbtype = get('kodi_dbtype')
        if kodi_dbtype:
            kodi_context['kodi_dbtype'] = kodi_dbtype
            kodi_context['kodi_dbid'] = get('kodi_dbid')
            kodi_context['kodi_path'] = get('kodi_path')
        
        try:
            info_dict = eval(str(info_str)) if info_str else {}
        except:
            info_dict = {}

        if switch == 'play' or switch == 'playoutside':
            # MODIFICARE: Această secțiune era pentru streams. 
            # O putem lăsa pentru compatibilitate dacă vreun torrent returnează link direct,
            # dar ștergem referințele la 'resolveurl' dacă nu sunt necesare. 
            # Pentru siguranță, lăsăm blocul dar nu îl modificăm acum, 
            # deoarece torenții folosesc 'torrent_links'.
            xbmcgui.Window(10000).setProperty('mrsp_active_playback', 'true')
            
            dp = xbmcgui.DialogProgressBG()
            dp.create(self.__scriptname__, 'Starting...')
            liz = xbmcgui.ListItem(nume)
            if info_dict:
                liz.setInfo(type="Video", infoLabels=info_dict); liz.setArt({'thumb': info_dict.get('Poster') or os.path.join(__settings__.getAddonInfo('path'), 'resources', 'media', 'video.png')})
            else: 
                liz.setInfo(type="Video", infoLabels={'Title':unquote(nume)})
            
            dp.update(50, message='Starting...')
            try:
                params.update({'info' : info_dict})
                if kodi_context:
                    params.update(kodi_context)
                
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
            except Exception as e:
                dp.update(0)
                dp.close()
                showMessage("Eroare", "%s" % e)
        else:
            if switch == 'torrent_links':
                torraction = torraction if torraction else ''
                menu = getattr(torrents, site)().parse_menu(link, switch, info_dict, torraction=torraction)
            else:
                # MODIFICARE: Eliminat logica streams.streamsites
                # Verificam doar daca e in torrentsites
                if site in torrents.torrentsites:
                    menu = getattr(torrents, site)().parse_menu(link, switch, info_dict, limit=limit)
                else: menu = ''
            
            if menu:
                for datas in menu:
                    isfolder = True
                    nume = datas.get('nume')
                    url = datas.get('legatura')
                    imagine = datas.get('imagine')
                    switch = datas.get('switch')
                    infoa = datas.get('info')
                    
                    params = {'site': site, 'link': url, 'switch': switch, 'nume': nume, 'info': infoa, 'favorite': 'check', 'watched': 'check'}
                    if kodi_context:
                        params.update(kodi_context)

                    if switch == 'get_links':
                        isfolder = False
                    
                    cm = []
                    addcm = datas.get('cm')
                    if addcm:
                        cm.extend(addcm)
                    
                    if not nume == 'Next':
                        if infoa and isinstance(infoa, dict):
                            if infoa.get('imdb'): self.getMetacm(url, nume, cm, infoa.get('imdb'))
                            else: self.getMetacm(url, nume, cm)
                            cm.append(('Caută Variante', 'Container.Update(%s?action=searchSites&modalitate=edit&query=%s&Stype=%s)' % (sys.argv[0], quote(nume), self.sstype)))
                        
                        if self.favorite(params):
                            nume = '[COLOR yellow]Fav[/COLOR] - %s' % nume
                            cm.append(self.CM('favorite', 'delete', url, nume))
                        else: cm.append(self.CM('favorite', 'save', url, nume, str(params)))
                        
                        if self.watched(params):
                            if isinstance(params.get('info'), dict):
                                params['info'].update({'playcount': 1, 'overlay': 7})
                            cm.append(self.CM('watched', 'delete', url))
                        else:
                            cm.append(self.CM('watched', 'save', datas.get('landing', url), params=str(params)))
                        
                        if self.youtube == '1':
                            cm.append(('Caută în Youtube', 'RunPlugin(%s?action=YoutubeSearch&url=%s)' % (sys.argv[0], quote(nume))))
                        
                        if datas.get('landing'): params.update({'landing': datas.get('landing')})
                        if datas.get('subtitrare'): params.update({'subtitrare': datas.get('subtitrare')})

                    if handle:
                        if handle == '1':
                            # MODIFICARE: Verificam doar torenti
                            if site in torrents.torrentsites:
                                name = torrents.torrnames.get(site, {}).get('nume')
                            else:
                                name = 'Unknown'
                            
                            if not new:
                                all_links.append(['[COLOR red]%s:[/COLOR] %s' % (name, nume), 'OpenSite', params, imagine, cm])
                            else:
                                all_links_new.append(['[COLOR red]%s:[/COLOR] %s' % (name, nume), 'OpenSite', params, imagine, cm])
                        elif handle == '2':
                            if not new:
                                all_links.append([nume, 'OpenSite', params, imagine, cm])
                            else:
                                all_links_new.append([nume, 'OpenSite', params, imagine, cm])
                    else:
                        listings.append(self.drawItem(title=nume, action='OpenSite', link=params, image=imagine, contextMenu=cm, isFolder=isfolder))

                if not handle:
                    xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
                    xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)
            else:
                if not handle:
                    xbmcplugin.addDirectoryItems(int(sys.argv[1]), [], 0)
                    xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)
        
        if new:
            return all_links_new
    
    def recents(self, params):
        # MODIFICARE: Implicit folosim doar torenti (__alltr__)
        rtype = __alltr__
        listings = []
        all_links = []
        
        # Verifica daca e cerut explicit 'torrs', deși acum e implicit
        if params.get('Rtype') == 'torrs': rtype = __alltr__
        
        # Apeleaza thread-urile care la randul lor apeleaza OpenSite cu handle='1'
        result = thread_me(rtype, params, 'recente')
        
        try: resultitems = result.iteritems()
        except: resultitems = result.items()
        
        for key, value in resultitems:
            all_links.extend(value)
        
        # Regex pentru sortare seeders - Cauta [S/L: cifre
        patt = re.compile(r'\[S/L:\s*(\d+)')
        
        # MODIFICARE: Aplicam logica de sortare specifica torentilor implicit
        if params.get('Sortby') == 'seed':
            # Sortare dupa seederi (descrescator)
            all_links.sort(key=lambda x: int(patt.search(x[0].replace(',', '').replace('.', '')).group(1)) if patt.search(x[0]) else 0, reverse=True)
        
        elif params.get('Sortby') == 'size':
            # Sortare dupa marime (descrescator)
            all_links.sort(key=lambda x: float(x[2].get('info', {}).get('Size', 0)) if isinstance(x[2].get('info'), dict) else 0, reverse=True)
        
        elif params.get('Sortby') == 'name':
            # Sortare alfabetica
            all_links.sort(key=lambda x: re.sub(r'\[.*?\]', '', ensure_str(x[0])).strip())
        
        elif params.get('Sortby') == 'site':
             # Sortare dupa site
             all_links.sort(key=lambda x: x[0])

        for nume, action, params, imagine, cm in all_links:
            # Ignoram butoanele de "Next" din sub-liste pentru a nu umple lista de recente
            if not re.sub(r'\[.*?\]', '', nume).lstrip(' ').startswith('Next'): 
                listings.append(self.drawItem(title = nume,
                                    action = action,
                                    link = params,
                                    image = imagine,
                                    contextMenu = cm))
        
        xbmcplugin.setContent(int(sys.argv[1]), '')
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
        # log('[MRSP-WATCHED] Funcția watched() apelată cu action=%s' % action)
        
        if action == 'save':
            
            # ===== INCEPUT MODIFICARE =====
            # Extrage și transmite informațiile Kodi
            kodi_dbtype = get('kodi_dbtype')
            kodi_dbid = get('kodi_dbid')
            kodi_path = get('kodi_path')
            
            log('[MRSP-WATCHED] Parametri primiți: kodi_dbtype=%s, kodi_dbid=%s, kodi_path=%s, elapsed=%s' % (kodi_dbtype, kodi_dbid, kodi_path, elapsed))
            
            save_watched(
                unquote(get('watchedlink')), 
                unquote(get('detalii')), 
                '1' if get('norefresh') else None, 
                elapsed, 
                total,
                kodi_dbtype=kodi_dbtype,
                kodi_dbid=kodi_dbid,
                kodi_path=kodi_path
            )
            # ===== SFARSIT MODIFICARE =====
        elif action == 'delete':
            delete_watched(unquote(get('watchedlink')))
        elif action == 'check':
            return get_watched(unquote(get('link')))
        elif action == 'list':
            try:
                watch = list_watched(int(page))
                resume = list_partial_watched(int(page))
            except Exception as e:
                log('[MRSP-WATCHED-LIST] Eroare la citirea din DB: %s' % str(e))
                import traceback
                log('[MRSP-WATCHED-LIST] Traceback: %s' % traceback.format_exc())
                watch = []
                resume = []
            
            if resume:
                try: watch.extend(resume)
                except: pass
            if watch:
                if resume: 
                    try:
                        watch = sorted(watch, key=lambda x: x[4], reverse=True)
                    except:
                        pass
                
                for watcha in watch:
                    try:
                        # ===== MODIFICARE: Verificare mai robustă =====
                        if not watcha or len(watcha) < 3:
                            log('[MRSP-WATCHED-LIST] Item invalid: %s' % str(watcha))
                            continue
                        
                        if not watcha[1]:
                            log('[MRSP-WATCHED-LIST] watcha[1] este None')
                            continue
                        # ===== SFÂRȘIT MODIFICARE =====
                        
                        cm = []
                        try:
                            if watcha[4]:
                                watchtime = time.strftime('%d-%m-%Y %H:%M:%S', time.localtime(int(watcha[4])))
                            else: watchtime = ''
                        except: watchtime = ''
                        
                        try: 
                            watcha_info = eval(watcha[2])
                        except: 
                            try:
                                watcha_info = eval(unquote(watcha[2]))
                            except Exception as e:
                                log('[MRSP-WATCHED-LIST] Nu pot parsa watcha[2]: %s, eroare: %s' % (str(watcha[2]), str(e)))
                                continue
                        
                        if not watcha_info or not isinstance(watcha_info, dict):
                            log('[MRSP-WATCHED-LIST] watcha_info nu este dict valid: %s' % str(watcha_info))
                            continue
                        
                        info_data = watcha_info.get('info')
                        if info_data and not isinstance(info_data, dict):
                            try:
                                watcha_info['info'] = eval(str(info_data))
                            except:
                                log('[MRSP-WATCHED-LIST] Nu pot converti info la dict')
                                watcha_info['info'] = {}
                        elif not info_data:
                            watcha_info['info'] = {}
                        
                        # Restul codului rămâne la fel până la construirea query-ului...
                        
                        # Extragem numele
                        wtitle = watcha_info.get('info', {}).get('Title', '')
                        wnume = watcha_info.get('nume') or wtitle or 'Necunoscut'
                        wtvshow = watcha_info.get('info', {}).get('TVShowTitle', '')
                        
                        if wtvshow:
                            watcha_ii = wnume
                        elif wnume and wtitle and wnume != wtitle:
                            watcha_ii = '%s - %s' % (wtitle, wnume)
                        else:
                            watcha_ii = wtitle or wnume
                        
                        is_kodi_library = watcha_info.get('site') == 'kodi_library'
                        
                        if is_kodi_library:
                            file_path = watcha_info.get('link')
                            show_title = watcha_info.get('info', {}).get('TVShowTitle', '')
                            original_title = watcha_info.get('info', {}).get('OriginalTitle')
                            
                            if original_title:
                                show_title = original_title
                                log('[MRSP-WATCHED-LIST] Folosim titlul original pentru căutare: %s' % show_title)
                            
                            season = watcha_info.get('info', {}).get('Season')
                            episode = watcha_info.get('info', {}).get('Episode')
                            movie_title = watcha_info.get('info', {}).get('Title', '')
                            
                            if show_title and season is not None:
                                if self.context_trakt_search_mode == '0':
                                    if episode is not None:
                                        search_query = '%s S%02dE%02d' % (show_title, int(season), int(episode))
                                    else:
                                        search_query = '%s S%02d' % (show_title, int(season))
                                    search_params = {
                                        'modalitate': 'edit',
                                        'query': quote(search_query),
                                        'Stype': self.sstype
                                    }
                                elif self.context_trakt_search_mode == '1':
                                    if episode is not None:
                                        search_query = '%s S%02dE%02d' % (show_title, int(season), int(episode))
                                    else:
                                        search_query = '%s S%02d' % (show_title, int(season))
                                    search_params = {
                                        'searchSites': 'cuvant',
                                        'cuvant': quote(search_query),
                                        'Stype': self.sstype
                                    }
                                else:
                                    search_query = '%s S%02d' % (show_title, int(season))
                                    search_params = {
                                        'searchSites': 'cuvant',
                                        'cuvant': quote(search_query),
                                        'Stype': self.sstype
                                    }
                            else:
                                search_query = movie_title or wnume
                                if self.context_trakt_search_mode == '0':
                                    search_params = {
                                        'modalitate': 'edit',
                                        'query': quote(search_query),
                                        'Stype': self.sstype
                                    }
                                else:
                                    search_params = {
                                        'searchSites': 'cuvant',
                                        'cuvant': quote(search_query),
                                        'Stype': self.sstype
                                    }
                            
                            log('[MRSP-WATCHED-LIST] Query construit pentru Kodi Library: %s (mode: %s)' % (search_query, self.context_trakt_search_mode))
                            
                            if file_path:
                                cm.append(('Redare fișier original', 'PlayMedia(%s)' % file_path))
                            cm.append(('Caută variante (Edit)', 'Container.Update(%s?action=searchSites&modalitate=edit&query=%s&Stype=%s)' % (sys.argv[0], quote(search_query), self.sstype)))
                            
                            main_action = 'searchSites'
                            main_params = search_params
                        else:
                            self.getMetacm('%s' % (watcha_info.get('link') or watcha_info.get('landing')), watcha_ii, cm)
                            cm.append(('Caută Variante', 'Container.Update(%s?action=searchSites&modalitate=edit&query=%s&Stype=%s)' % (sys.argv[0], quote(watcha_ii), self.sstype)))
                            
                            main_action = 'OpenSite'
                            main_params = watcha_info
                        
                        cm.append(self.CM('watched', 'delete', watcha[1]))
                        
                        if self.favorite(watcha_info):
                            watcha_ii = '[COLOR yellow]Fav[/COLOR] - %s' % watcha_ii
                            cm.append(self.CM('favorite', 'delete', '%s' % (watcha_info.get('link') or watcha_info.get('landing')), watcha_ii))
                        else: 
                            cm.append(self.CM('favorite', 'save', '%s' % (watcha_info.get('link') or watcha_info.get('landing')), watcha_ii, str(watcha_info)))
                        
                        names = watcha_info.get('site')
                        if names == 'kodi_library':
                            name = 'Biblioteca Kodi'
                        elif names in torrents.torrentsites: 
                            name = torrents.torrnames.get(names).get('nume')
                        elif names in streams.streamsites: 
                            name = streams.streamnames.get(names).get('nume')
                        else: 
                            name = 'Necunoscut'
                        
                        if len(watcha) == 6:
                            partialdesc = '[COLOR yellow]%s din %s[/COLOR] ' % (datetime.timedelta(seconds=int(float(watcha[3]))), datetime.timedelta(seconds=int(float(watcha[5]))))
                            try: watcha_info['info']['seek_time'] = watcha[3]
                            except: pass
                        else: partialdesc = ''
                        
                        try: 
                            watcha_info['info']['played_file'] = re.findall('Played file\:\s+(.+?)\s\\n', watcha_info.get('info', {}).get('Plot', ''))[0]
                        except: pass
                        
                        listings.append(self.drawItem(
                            title = '%s%s[COLOR red]%s:[/COLOR] %s' % (
                                partialdesc,
                                (('%s ' % watchtime) if watchtime else ''),
                                name,
                                watcha_ii
                            ),
                            action = main_action,
                            link = main_params,
                            contextMenu = cm
                        ))
                        
                    except Exception as e:
                        log('[MRSP-WATCHED-LIST] Eroare la procesarea item: %s' % str(e))
                        import traceback
                        log('[MRSP-WATCHED-LIST] Traceback: %s' % traceback.format_exc())
                        continue  # ===== MODIFICARE: continue în loc de pass =====
                
                # Adaugă Next page dacă e cazul
                page = int(page) + 1
                listings.append(self.drawItem(title = '[COLOR lime]Next[/COLOR]',
                                    action = 'watched',
                                    link = {'watched': 'list', 'page': '%s' % page},
                                    image = seen_icon))
            
            # ===== MODIFICARE: Adăugăm try-except și la sfârșitul funcției =====
            try:
                xbmcplugin.addDirectoryItems(int(sys.argv[1]), listings, len(listings))
                xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)
            except Exception as e:
                log('[MRSP-WATCHED-LIST] Eroare la afișarea listei: %s' % str(e))
                import traceback
                log('[MRSP-WATCHED-LIST] Traceback: %s' % traceback.format_exc())
                xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=False)
            # ===== SFÂRȘIT MODIFICARE =====
    
    def openSettings(self, params={}):
        if params.get('script') == 'torrent2http':
            xbmcaddon.Addon(id='script.module.torrent2http').openSettings()
        else:
            __settings__.openSettings()
    
    def openTorrent(self, params={}):
        listings = []
        get = params.get
        
        # Setam flag-urile
        xbmcgui.Window(10000).setProperty('mrsp_returning_from_playback', 'true')
        xbmcgui.Window(10000).setProperty('mrsp_active_playback', 'true')

        info = unquote(get("info"),'')
        try:
            info = eval(info) if info else {}
        except: pass
        
        # --- Preluare ID-uri ---
        tmdb_id = None
        imdb_id = None
        try:
            import json
            window = xbmcgui.Window(10000)
            saved_prop = window.getProperty('mrsp.playback.info')
            if saved_prop:
                saved_data = json.loads(saved_prop)
                tmdb_id = saved_data.get('tmdb_id')
                imdb_id = saved_data.get('imdb_id') or saved_data.get('imdbnumber')
                if tmdb_id: info['tmdb_id'] = tmdb_id
                if imdb_id: info['imdb_id'] = imdb_id
        except: pass
        # -----------------------

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
            
            transPath = xbmcvfs.translatePath if py3 else xbmc.translatePath
            try: addonpath = transPath(ROOT.decode('utf-8'))
            except: addonpath = transPath(ROOT)
            
            from resources.lib.windows.browse_torrents import BrowseTorrentsXML
            window = BrowseTorrentsXML('browse_torrents.xml', addonpath, 'Default', files=files, info=info, link=url, site=site)
            action, identifier = window.run()
            del window
            if action == 'Play':
                # Reconstruim pars cu ID-urile in info
                if isinstance(info, str):
                    try: info_dict = eval(info)
                    except: info_dict = {}
                else: info_dict = info
                
                if tmdb_id: info_dict['tmdb_id'] = tmdb_id
                if imdb_id: info_dict['imdb_id'] = imdb_id
                
                pars = {'Turl': quote(url),
                        'Tid': identifier,
                        'info': quote(str(info_dict)),
                        'download': 'true' if clickactiontype == '3' else 'false',
                        'Tsite': site}
                
                # Apelam functia globala openTorrent din functions.py
                from resources.functions import openTorrent as openTorrentFunc
                openTorrentFunc(pars)
    
    def openTorrenterSettings(self, params={}):
        xbmcaddon.Addon(id='plugin.video.torrenter').openSettings()
        
    def openResolverSettings(self, params={}):
        xbmcaddon.Addon(id='script.module.resolveurl').openSettings()
    
    def searchSites(self, params={}):
        from resources.functions import get_show_ids_from_tmdb, get_movie_ids_from_tmdb
        listings = []
        get = params.get

        # ===== START MODIFICARE: Preluam ID-urile =====
        try:
            playback_data = {}
            
            # Caz 1: TMDb Helper Episod (vine cu 'showname', 'season', 'episode')
            if get('showname') and get('mediatype') == 'episode':
                showname = unquote(get('showname'))
                playback_data = {
                    'showname': showname,
                    'mediatype': get('mediatype'),
                    'season': get('season'),
                    'episode': get('episode')
                }
                
                if get('tmdb_id'): playback_data['tmdb_id'] = get('tmdb_id')
                if get('imdb_id'): playback_data['imdb_id'] = get('imdb_id')
                
                # Dacă NU avem ID-uri, le obținem de la TMDb API
                if not playback_data.get('tmdb_id') or not playback_data.get('imdb_id'):
                    try:
                        api_tmdb, api_imdb = get_show_ids_from_tmdb(showname)
                        if api_tmdb and not playback_data.get('tmdb_id'):
                            playback_data['tmdb_id'] = api_tmdb
                            log('[MRSP-SEARCH] TMDb ID obținut de la API: %s' % api_tmdb)
                        if api_imdb and not playback_data.get('imdb_id'):
                            playback_data['imdb_id'] = api_imdb
                            log('[MRSP-SEARCH] IMDb ID obținut de la API: %s' % api_imdb)
                    except Exception as e:
                        log('[MRSP-SEARCH] Eroare la obținerea ID-urilor: %s' % str(e))

            # Caz 2: TMDb Helper Film (vine cu 'mediatype=movie' și 'cuvant')
            elif get('mediatype') == 'movie':
                cuvant = unquote(get('cuvant', ''))
                
                import re
                match_year = re.search(r'\b(19|20\d{2})\s*$', cuvant.strip())
                if match_year:
                    title = cuvant[:match_year.start()].strip()
                    year = match_year.group(1)
                else:
                    title = cuvant.strip()
                    year = None
                
                playback_data = {
                    'mediatype': 'movie',
                    'title': title
                }
                
                if get('tmdb_id'): playback_data['tmdb_id'] = get('tmdb_id')
                if get('imdb_id'): playback_data['imdb_id'] = get('imdb_id')
                
                if not playback_data.get('tmdb_id') or not playback_data.get('imdb_id'):
                    try:
                        api_tmdb, api_imdb = get_movie_ids_from_tmdb(title, year)
                        if api_tmdb and not playback_data.get('tmdb_id'):
                            playback_data['tmdb_id'] = api_tmdb
                            log('[MRSP-SEARCH] Film TMDb ID: %s' % api_tmdb)
                        if api_imdb and not playback_data.get('imdb_id'):
                            playback_data['imdb_id'] = api_imdb
                            log('[MRSP-SEARCH] Film IMDb ID: %s' % api_imdb)
                    except Exception as e:
                        log('[MRSP-SEARCH] Eroare film: %s' % str(e))

            # =====================================================================
            # Caz 3: Meniu Contextual cu EPISOD din biblioteca Kodi
            # IMPORTANT: Trebuie să obținem ID-urile SERIALULUI, nu ale episodului!
            # =====================================================================
            elif get('kodi_dbtype') == 'episode' and get('kodi_dbid'):
                playback_data['kodi_dbtype'] = get('kodi_dbtype')
                playback_data['kodi_dbid'] = get('kodi_dbid')
                
                # ID-ul IMDb primit poate fi al episodului - trebuie să luăm al serialului!
                episode_imdb = get('imdb_id')  # Salvăm pentru referință
                
                if get('tmdb_id'): 
                    playback_data['tmdb_id'] = get('tmdb_id')
                
                # Dacă NU avem tmdb_id SAU imdb e al episodului (fără tt sau scurt)
                needs_show_ids = False
                if not get('tmdb_id'):
                    needs_show_ids = True
                elif episode_imdb and (not episode_imdb.startswith('tt') or len(episode_imdb) < 9):
                    # IMDb al serialului e de forma tt12345678 (min 9 caractere)
                    # Dacă e mai scurt, probabil e al episodului
                    needs_show_ids = True
                
                if needs_show_ids:
                    try:
                        import json
                        # Obținem titlul serialului din biblioteca Kodi
                        json_query = {
                            "jsonrpc": "2.0",
                            "method": "VideoLibrary.GetEpisodeDetails",
                            "params": {
                                "episodeid": int(get('kodi_dbid')),
                                "properties": ["showtitle", "tvshowid"]
                            },
                            "id": 1
                        }
                        result = xbmc.executeJSONRPC(json.dumps(json_query))
                        result_dict = json.loads(result)
                        ep_details = result_dict.get('result', {}).get('episodedetails', {})
                        showtitle = ep_details.get('showtitle', '')
                        tvshowid = ep_details.get('tvshowid')
                        
                        log('[MRSP-SEARCH] Episod din Kodi: showtitle="%s", tvshowid=%s' % (showtitle, tvshowid))
                        
                        if showtitle:
                            # Căutăm ID-urile SERIALULUI pe TMDb
                            api_tmdb, api_imdb = get_show_ids_from_tmdb(showtitle)
                            if api_tmdb:
                                playback_data['tmdb_id'] = api_tmdb
                                log('[MRSP-SEARCH] TMDb ID serial: %s' % api_tmdb)
                            if api_imdb:
                                playback_data['imdb_id'] = api_imdb
                                log('[MRSP-SEARCH] IMDb ID serial: %s (înlocuit episod: %s)' % (api_imdb, episode_imdb))
                    except Exception as e:
                        log('[MRSP-SEARCH] Eroare la obținerea ID-urilor serial: %s' % str(e))
                else:
                    # Avem deja ID-uri valide
                    if episode_imdb:
                        playback_data['imdb_id'] = episode_imdb

            # Caz 4: Alte contexte (filme din Kodi, etc.)
            else:
                if get('kodi_dbtype'): 
                    playback_data['kodi_dbtype'] = get('kodi_dbtype')
                    playback_data['kodi_dbid'] = get('kodi_dbid')
                
                if get('imdb_id'): playback_data['imdb_id'] = get('imdb_id')
                if get('tmdb_id'): playback_data['tmdb_id'] = get('tmdb_id')
                
                # === MODIFICARE ANGELITTO: Extrage ID-uri si din parametrul 'info' (folosit de meniurile Trakt) ===
                if not playback_data.get('tmdb_id') or not playback_data.get('imdb_id'):
                    try:
                        info_param = get('info')
                        if info_param:
                            import ast
                            info_dict_param = ast.literal_eval(unquote(info_param))
                            if isinstance(info_dict_param, dict):
                                if not playback_data.get('tmdb_id') and info_dict_param.get('tmdb_id'):
                                    playback_data['tmdb_id'] = info_dict_param['tmdb_id']
                                if not playback_data.get('imdb_id') and info_dict_param.get('imdb_id'):
                                    playback_data['imdb_id'] = info_dict_param['imdb_id']
                    except: pass
                # =================================================================================================

            # Salvam in fereastra 10000
            if playback_data:
                import json
                window = xbmcgui.Window(10000)
                window.setProperty('mrsp.playback.info', json.dumps(playback_data))
                log('[MRSP-SEARCH] Context salvat: %s' % json.dumps(playback_data))

        except Exception as e:
            log('[MRSP-SEARCH] Eroare salvare context: %s' % str(e))
        # ===== SFÂRȘIT MODIFICARE =====

        # ===== START MODIFICARE NOUA: Suprascriere logica pentru TMDb Helper =====
        if get('showname') and get('season') and get('episode'):
            search_mode = __settings__.getSetting('context_trakt_search_mode')
            showname = unquote(get('showname'))
            try:
                season = int(get('season'))
                episode = int(get('episode'))
                
                term_full = '%s S%02dE%02d' % (showname, season, episode)
                term_season = '%s S%02d' % (showname, season)
                
                if search_mode == '0': # Edit Box
                    params['searchSites'] = None 
                    params['modalitate'] = 'edit'
                    params['query'] = quote(term_full)
                    log('[MRSP-SEARCH] TMDb Helper Override: Mod Edit Box activat pentru %s' % term_full)
                    
                elif search_mode == '1': # D1 (Sezon + Episod)
                    params['cuvant'] = quote(term_full)
                    log('[MRSP-SEARCH] TMDb Helper Override: Mod D1 (S+E) activat: %s' % term_full)
                    
                elif search_mode == '2': # D2 (Doar Sezon)
                    params['cuvant'] = quote(term_season)
                    log('[MRSP-SEARCH] TMDb Helper Override: Mod D2 (S) activat: %s' % term_season)
                    
            except: pass
            
        elif get('mediatype') == 'movie' and get('cuvant'):
             search_mode = __settings__.getSetting('context_trakt_search_mode')
             if search_mode == '0':
                 params['searchSites'] = None
                 params['modalitate'] = 'edit'
                 params['query'] = get('cuvant')
                 log('[MRSP-SEARCH] TMDb Helper Override: Mod Edit Box activat pentru Film')
        # ===== SFARSIT MODIFICARE NOUA =====
      
        if get('Stype'): stype = get('Stype')
        else: 
            stype = self.sstype
        if get('landsearch'): landing = get('landsearch')
        else: landing = None
            
        if get('searchSites') == 'delete':
            del_search(unquote(get('cuvant')))
        elif get('searchSites') == 'edit':
            keyboard = xbmc.Keyboard(unquote(get('cuvant')))
            keyboard.doModal()
            keyword = keyboard.getText()
            if len(keyword) > 0:
                save_search(keyword)
                xbmc.executebuiltin("Container.Refresh")
        elif get('searchSites') == 'noua':
            keyboard = xbmc.Keyboard('')
            keyboard.doModal()
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
        xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=True)

    def get_searchsite(self, word, landing=None, stype='sites'):
        import difflib
        import hashlib
        from resources.lib import PTN
        
        word_safe = ensure_str(word)
        try:
            word_bytes = word_safe.encode('utf-8')
        except:
            word_bytes = word_safe
            
        cache_key = 'mrsp.search_cache.' + hashlib.md5(word_bytes).hexdigest()
        last_term_key = 'mrsp.last_search_term'
        playback_flag_key = 'mrsp_active_playback'
        
        window = xbmcgui.Window(10000)
        
        cached_data_str = window.getProperty(cache_key)
        last_term = window.getProperty(last_term_key)
        is_playback_return = window.getProperty(playback_flag_key) == 'true'
        
        gathereda = []
        used_cache = False
        
        # --- LOGICA DE CACHE IMBUNATATITA ---
        if is_playback_return and (last_term == word_safe) and cached_data_str:
            try:
                loaded_data = json.loads(cached_data_str)
                
                # ===== FIX: Verificam daca lista din cache are rezultate =====
                # Daca lista e goala (len=0), inseamna ca data trecuta nu a gasit nimic sau a fost eroare.
                # In acest caz, NU folosim cache-ul, ci lasam sa treaca spre cautare Clean.
                if loaded_data and len(loaded_data) > 0:
                    gathereda = loaded_data
                    used_cache = True
                    log('[MRSP-CACHE] Întoarcere din redare pentru "%s". Se încarcă %d rezultate din CACHE.' % (word_safe, len(gathereda)))
                else:
                    log('[MRSP-CACHE] Cache-ul există dar este GOL (posibilă eroare anterioară). Se forțează căutare CLEAN.')
                    gathereda = []
                    used_cache = False
                    # Invalidam jetonul pentru a forta o re-procesare curata
                    window.clearProperty(playback_flag_key)
            except:
                gathereda = []
                used_cache = False
        
        # --- LOGICA SCHIMBARE TERMEN / CLEAN ---
        if not used_cache:
            # Invalidam jetonul vechi
            if is_playback_return:
                window.clearProperty(playback_flag_key)
            
            # Actualizam ultimul termen cautat
            window.setProperty(last_term_key, word_safe)
            
            log('[MRSP-SEARCH] Căutare nouă (Clean) pe site-uri pentru: %s' % word_safe)
            
            word_clean = word.replace(':', '').replace('-', ' ')
            result = {}
            
            save_search(unquote(word))
            
            if landing:
                # MODIFICARE: Eliminat verificarea pentru streams
                imp = getattr(torrents, landing)
                site_name = imp().name
                result = {landing : imp().cauta(word_clean)}
            else:
                # MODIFICARE: Cautam doar in torenti (__alltr__)
                # Ignoram parametrul stype si folosim direct lista de torenti activi
                allnew = __alltr__
                result = thread_me(allnew, word_clean, 'cautare', word=word_clean)
            
            try: resultitems = result.iteritems()
            except: resultitems = result.items()
            
            for sait, results in resultitems:
                if results and len(results) > 1:
                    if results[2]:
                            for build in results[2]:
                                gathereda.append((build.get('nume'), build.get('legatura'), build.get('imagine'), build.get('switch'), build.get('info'), results[0], results[1]))
            
            try:
                # Salvam in cache, chiar daca e gol (pentru consistenta), 
                # dar logica de mai sus va ignora cache-ul gol la urmatoarea citire.
                window.setProperty(cache_key, json.dumps(gathereda))
            except Exception as e:
                log('[MRSP-CACHE] Nu s-a putut salva cache-ul: %s' % str(e))

        # (Restul funcției rămâne neschimbat)
        nextlink = []
        patt = re.compile(r'\[S/L: (\d+)')
        if getSettingAsBool('slow_system_search'):
            gatheredb = sorted(gathereda, key=lambda x:difflib.SequenceMatcher(None, x[0].strip(), unquote(word)).ratio(), reverse=True)
            if stype == 'torrs' or stype == 'both':
                gathered = sorted(gatheredb, key=lambda x: int(patt.search(x[0]).group(1)) if patt.search(x[0]) else 0, reverse=True)
            else:
                gathered = gatheredb
        else:
            try:
                gatheredb = sorted(gathereda, key=lambda x: (difflib.SequenceMatcher(None, PTN.parse(re.sub('\[COLOR.+?\].+?\[/COLOR\](?:\s+)?|\[.*?\]', '', x[0].strip())).get('title'), unquote(word)).ratio(), int(patt.search(x[0].replace(',','').replace('.','')).group(1)) if patt.search(x[0]) else 0), reverse=True)
            except:
                gatheredb = gathereda

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
                            if isinstance(params['info'], dict):
                                params['info'].update({'playcount': 1, 'overlay': 7})
                            cm.append(self.CM('watched', 'delete', url, norefresh='1'))
                        except: pass
                    else:
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
        
        # Imagine default daca lipseste
        if not image or image == '': 
            image = os.path.join(__settings__.getAddonInfo('path'), 'resources', 'media', 'video.png')
        
        fanart = image
        torrent = False
        outside = False
        
        # Procesare parametri link (identica cu originalul)
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
                    if info.get('Poster'):
                        image = info.get('Poster')
                    fanart = info.get('Fanart') or image
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
        
        # ===== FIX PENTRU ICONITE IN LISTA =====
        listitem.setArt({
            'icon': image,
            'thumb': image,
            'poster': image,
            'fanart': fanart
        })
        # =======================================

        infog = info
        if infog:
            # Curatenie in info labels
            infog.pop('Poster', None)
            infog.pop('Fanart', None)
            infog.pop('Label2', None)
            infog.pop('imdb', None)
            infog.pop('tvdb', None)
            infog.pop('seek_time', None)
            infog.pop('played_file', None)
        
        if isinstance(infog, dict) and infog.get('Size'):
            try: infog['size'] = int(float(infog.get('Size')))
            except: pass

        # ===== PĂSTRĂM setInfo() ORIGINAL - Warning-ul e doar cosmetic =====
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
        # ===================================================================
        
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
