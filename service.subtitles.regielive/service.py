# -*- coding: utf-8 -*-

try:
    from cStringIO import StringIO
    py3 = False
except:
    from io import BytesIO as StringIO
    py3 = True
import os
import re
import shutil
import sys
import unicodedata
import urllib
try: 
    import urllib
    import urllib2
except ImportError: 
    import urllib.parse as urllib
import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs
from zipfile import ZipFile


def ensure_str(string, encoding='utf-8'):
    if py3:
        return string
    if isinstance(string, unicode):
        string = string.encode(encoding)
    if not isinstance(string, str):
        string = str(string)
    return string

__addon__ = xbmcaddon.Addon()
__scriptid__   = __addon__.getAddonInfo('id')
__scriptname__ = __addon__.getAddonInfo('name')

if py3:
    xpath = xbmcvfs.translatePath
    __cwd__        = xpath(__addon__.getAddonInfo('path'))
else:
    xpath = xbmc.translatePath
    __cwd__        = xpath(__addon__.getAddonInfo('path')).decode("utf-8")
__profile__    = ensure_str(xpath(__addon__.getAddonInfo('profile')))
__resource__   = ensure_str(xpath(os.path.join(__cwd__, 'resources', 'lib')))
__temp__       = ensure_str(xpath(os.path.join(__profile__, 'temp', '')))


BASE_URL = "https://subtitrari.regielive.ro/cauta.html?s="

if xbmcvfs.exists(__temp__):
    shutil.rmtree(__temp__)
xbmcvfs.mkdirs(__temp__)

sys.path.append (__resource__)

import requests
s = requests.Session()
ua = 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:50.0) Gecko/20100101 Firefox/50.0'
def log(msg):
    if py3:
        loginfo = xbmc.LOGINFO
    else:
        loginfo = xbmc.LOGNOTICE
    try:
        xbmc.log("### %s" % (msg), level=loginfo )
    except UnicodeEncodeError:
        xbmc.log("### : %s" % (msg.encode("utf-8", "ignore")), level=loginfo )
    except:
        xbmc.log("### : %s" % ('ERROR LOG'), level=loginfo )

def get_episode_pattern(episode):
    parts = episode.split(':')
    if len(parts) < 2:
        return "%%%%%"
    season = int(parts[0])
    epnr = int(parts[1])
    patterns = [
        "s%#02de%#02d" % (season, epnr),
        "%#02dx%#02d" % (season, epnr),
        "%#01de%#02d" % (season, epnr),
    ]
    if season < 10:
        patterns.append("(?:\A|\D)%dx%#02d" % (season, epnr))
    return '(?:%s)' % '|'.join(patterns)

def Search(item):
    search_data = []
    search_data = searchsubtitles(item)
    if search_data != None:
        for item_data in search_data:
            if ((item['season'] == item_data['SeriesSeason'] and
                item['episode'] == item_data['SeriesEpisode']) or
                (item['season'] == "" and item['episode'] == "")
                ):
                listitem = xbmcgui.ListItem(label=item_data["LanguageName"],
                                            label2=item_data["SubFileName"])
                listitem.setArt({'icon': str(item_data["SubRating"]),
                                 'thumb': str(item_data["ISO639"])})

                listitem.setProperty("sync", ("false", "true")[str(item_data["MatchedBy"]) == "moviehash"])
                listitem.setProperty("hearing_imp", ("false", "true")[int(item_data["SubHearingImpaired"]) != 0])
                url = "plugin://%s/?action=download&link=%s&filename=%s&format=%s&promo=%s" % (__scriptid__,
                                                                                      item_data["ZipDownloadLink"],
                                                                                      item_data["SubFileName"],
                                                                                      item_data["SubFormat"],
                                                                                      item_data["promo"]
                                                                                      )
                
                xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=url, listitem=listitem, isFolder=False)

def searchsubtitles(item):
    lists = ''
    import PTN
    parsed = PTN.parse(item['title'])
    if parsed.get('title'): 
        item_orig = parsed.get('title')
        item['title'] = parsed.get('title')
    else:
        item_orig = item['title']
    if len(item['tvshow']) > 0:
        search_string = item['tvshow'].replace(" ", "+")
    else:
        if not (item['year']):
            item['year'] = parsed.get('year') or ''
            item['title'] = parsed.get('title')
        search_string = item['title']
    if parsed.get('episode') or parsed.get('season'):
        item['season'] = str(parsed.get('season')) or ''
        item['episode'] = str(parsed.get('episode')) or ''
            
    if item['mansearch']:
        search_string = urllib.unquote(item['mansearchstr'])
        episodes = re.compile('S(\d{1,2})E(\d{1,2})', re.IGNORECASE).findall(search_string)
        if episodes:
            sezon = episodes[0][0]
            episod = episodes[0][1]
            item['season'] = sezon
            item['episode'] = episod
            search_string = (re.sub('S(\d{1,2})E(\d{1,2})', '', search_string, flags=re.I))
            lists = search_links(search_string, sezon=sezon, episod=episod, item=item, parsed=parsed)
        else:
            item['episode'] = ''
            item['season'] = ''
            lists = search_links(search_string, item=item, parsed=parsed)
        return lists
    #with open('/storage/test.txt', 'w') as the_file:
        #the_file.write(str(parsed))
    lists = search_links(search_string, item['year'], item['season'], item['episode'], item_orig, item=item, parsed=parsed)
    if not lists:
        if not item['file_original_path'].startswith('http') and xbmcvfs.exists(item['file_original_path']):
            head = os.path.basename(os.path.dirname(item['file_original_path']))
            lists = search_links(search_string, item['year'], item['season'], item['episode'], (re.compile(r'\[.*?\]').sub('', head)), item=item, parsed=parsed)
    return lists

def search_links(nume='', an='', sezon='', episod='', fisier='', item=None, parsed=None):
    subs_list = []
    urlcautare = '%s%s' % (BASE_URL, nume.replace(" ", "+"))
    continuturl = get_search(urlcautare)
    first_search = re.compile('"imagine">.*?href="(.*?)".*?<img.*?alt="(.*?)".*?tag-.*?">(.*?)<', re.IGNORECASE | re.DOTALL).findall(continuturl)
    if first_search:
        selected = []
        if len(first_search) > 0:
            if len(first_search) > 1:
                dialog = xbmcgui.Dialog()
                sel = dialog.select("RegieLive",['%s - %s' % (x[1], x[2]) for x in first_search])
            else:
                sel = 0
            if sel >= 0:
                if sezon == "" or episod == "":
                    continuturl = get_search(first_search[sel][0])
                else:
                    continuturl = get_search('%ssezonul-%s/' % (first_search[sel][0], sezon.lstrip("0")))
                regex = '''<li class="subtitrare.*?id=".*?>(.*?)<.*?(?: |.*?title="Nota (.*?) d).*?href="(.*?descarca.*?)"'''
                search = re.compile(regex, re.IGNORECASE | re.DOTALL).findall(continuturl)
                if len(search) > 0:
                    subs_list = []
                    for item_search in search:
                        if item_search[1]:
                            rate = int(float(item_search[1]))
                        else: rate = item_search[1]
                        subfilename = item_search[0].strip()
                        selected.append({'SeriesSeason': (item['season']), 'SeriesEpisode': item['episode'], 'LanguageName': 'Romanian',
                                'promo': '', 'SubFileName': subfilename, 'SubRating': rate,
                                'ZipDownloadLink': item_search[2], 'ISO639': 'ro', 'SubFormat': 'srt', 'MatchedBy': 'fulltext', 'SubHearingImpaired': '0'})
                    season = item['season']
                    episode = item['episode']
                    if episode != "" and season !="" and episode !="None" and season !="None":
                        epstr = '{season}:{episode}'.format(**locals())
                        episode_regex = re.compile(get_episode_pattern(epstr), re.IGNORECASE)
                    else: episode_regex = None
                    if episode_regex:
                        for subs in selected:
                            if episode_regex.search(subs.get('SubFileName')):
                                subs_list.append(subs)
                        if len(subs_list) > 0:
                            selected = subs_list
                    return selected

def Download(link, urld, format, stack=False):
    url = re.sub('download', 'descarca', urld)
    url = re.sub('html', 'zip', url)
    subtitle_list = []
    pub_list = []
    exts = [".srt", ".sub", ".txt", ".smi", ".ssa", ".ass"]
    ext_pub = [".url"]
    headers = {'User-Agent': ua}
    if ((__addon__.getSetting("OSuser") and
        __addon__.getSetting("OSpass"))):
        payload = {'l_username':__addon__.getSetting("OSuser"), 'l_password':__addon__.getSetting("OSpass")}
        s.post('https://www.regielive.ro/membri/login.html', data=payload, headers=headers)
    headers['Host'] =  'subtitrari.regielive.ro'
    headers['Referer'] =  urld
    f = s.get(url, headers=headers, verify=False)
    try:
        archive = ZipFile(StringIO(f.content), 'r')
    except:
        return subtitle_list
    files = archive.namelist()
    files.sort()
    for file in files:
        contents = archive.read(file)
        if (os.path.splitext(file)[1] in exts):
            #extension = file[file.rfind('.') + 1:]
            if len(files) == 1:
                dest = os.path.join(__temp__, "%s" % (file))
            else:
                dest = os.path.join(__temp__, "%s" % (file))
            dest = ensure_str(dest)
            f = open(dest, 'wb')
            f.write(contents)
            f.close()
            subtitle_list.append(dest)
        if  __addon__.getSetting("nopop") == "false":
            if (os.path.splitext(file)[1] in ext_pub):
                pub = os.path.splitext(file)[0]
                pub_list.append(pub)
    if xbmcvfs.exists(subtitle_list[0]):
        if len(subtitle_list) > 1:
            selected = []
            subtitle_list_s = sorted(subtitle_list, key=natural_key)
            dialog = xbmcgui.Dialog()
            sel = dialog.select("%s" % ('Selecteaza o subtitrare'),
                                [((os.path.basename(os.path.dirname(x)) + '/' + os.path.basename(x))
                                  if (os.path.basename(x) == os.path.basename(subtitle_list_s[0])
                                      and os.path.basename(x) == os.path.basename(subtitle_list_s[1]))
                                  else os.path.basename(x))
                                  for x in subtitle_list_s])
            if sel >= 0:
                 selected.append(subtitle_list_s[sel])
                 return selected, pub_list
            else:
                return None
        else:
            return subtitle_list, pub_list
    else:
        return '',''

def normalizeString(str):
    if py3:
        return str
    return unicodedata.normalize('NFKD', unicode(unicode(str, 'utf-8'))).encode('ascii', 'ignore')

def natural_key(string_):
    return [int(s) if s.isdigit() else s for s in re.split(r'(\d+)', string_)]

def get_search(url):
    headers = {'User-Agent': ua, 'Content-type': 'application/x-www-form-urlencoded', 'Host': 'subtitrari.regielive.ro'}
    try:
        continut = s.get(url, headers=headers, verify=False)
        return continut.text
    except:
        return False

def get_params(string=""):
    param = []
    if string == "":
        paramstring = sys.argv[2]
    else:
        paramstring = string
    if len(paramstring) >= 2:
        params = paramstring
        cleanedparams = params.replace('?', '')
        if (params[len(params)-1] == '/'):
            params = params[0:len(params)-2]
        pairsofparams = cleanedparams.split('&')
        param = {}
        for i in range(len(pairsofparams)):
            splitparams = {}
            splitparams = pairsofparams[i].split('=')
            if (len(splitparams)) == 2:
                param[splitparams[0]] = splitparams[1]

    return param

params = get_params()
#log(params)

if params['action'] == 'search' or params['action'] == 'manualsearch':
    item = {}
    item['temp']               = False
    item['rar']                = False
    item['mansearch']          = False
    item['year']               = xbmc.getInfoLabel("VideoPlayer.Year")                         # Year
    item['season']             = str(xbmc.getInfoLabel("VideoPlayer.Season"))                  # Season
    item['episode']            = str(xbmc.getInfoLabel("VideoPlayer.Episode"))                 # Episode
    item['tvshow']             = normalizeString(xbmc.getInfoLabel("VideoPlayer.TVshowtitle"))  # Show
    item['title']              = normalizeString(xbmc.getInfoLabel("VideoPlayer.OriginalTitle"))# try to get original title
    item['file_original_path'] = xbmc.Player().getPlayingFile() if py3 else xbmc.Player().getPlayingFile().decode('utf-8')                 # Full path of a playing file
    item['3let_language']      = [] #['scc','eng']

    if 'searchstring' in params:
        item['mansearch'] = True
        item['mansearchstr'] = params['searchstring']

    if py3: langsplit = urllib.unquote(params['languages']).split(",")
    else: langsplit = urllib.unquote(params['languages']).decode('utf-8').split(",")
    for lang in langsplit:
        if lang == "Portuguese (Brazil)":
            lan = "pob"
        elif lang == "Greek":
            lan = "ell"
        else:
            lan = xbmc.convertLanguage(lang, xbmc.ISO_639_2)

        item['3let_language'].append(lan)

    if item['title'] == "":
        item['title']  = normalizeString(xbmc.getInfoLabel("VideoPlayer.Title"))      # no original title, get just Title

    if item['episode'].lower().find("s") > -1:                                      # Check if season is "Special"
        item['season'] = "0"                                                          #
        item['episode'] = item['episode'][-1:]

    if (item['file_original_path'].find("http") > -1):
        item['temp'] = True

    elif (item['file_original_path'].find("rar://") > -1):
        item['rar']  = True
        item['file_original_path'] = os.path.dirname(item['file_original_path'][6:])

    elif (item['file_original_path'].find("stack://") > -1):
        stackPath = item['file_original_path'].split(" , ")
        item['file_original_path'] = stackPath[0][8:]

    Search(item)

elif params['action'] == 'download':
    subs, pubs = Download(params["link"], params["link"], params["format"])
    if len(pubs) > 0:
        promo = pubs[0]
    else:
        promo = params['promo']
    if subs:
        try:
            if len(subs) > 1:
                dialog = xbmcgui.Dialog()
                sel = dialog.select("Select item",
                                    [sub for sub in subs])
                if sel >= 0:
                    xbmc.Player().setSubtitles(subs[sel])
            else: xbmc.Player().setSubtitles(subs[0])
        except: pass
        for sub in subs:
            listitem = xbmcgui.ListItem(label=sub)
            xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=sub, listitem=listitem, isFolder=False)
        if promo and xbmc.getCondVisibility('Player.HasVideo') and __addon__.getSetting("nopop") == "false":
            from threading import Thread
            #bg_pub = os.path.join(__cwd__, 'resources', 'media', 'ContentPanel.png')
                    
            class PubRegie(xbmcgui.WindowDialog):
                def __init__(self):
                    #self.background = xbmcgui.ControlImage(0, 70, 800, 100, 'ContentPanel.png')
                    self.background = xbmcgui.ControlImage(10, 70, 1000, 100, "")
                    self.text = xbmcgui.ControlLabel(10, 70, 1000, 100, '', textColor='0xff000000', alignment=0)
                    self.text2 = xbmcgui.ControlLabel(8, 68, 1000, 100, '', alignment=0)
                    self.addControls((self.text, self.text2))
                def sP(self, promo):
                    self.show()
                    #self.background.setImage("")
                    #self.background.setImage(bg_pub)
                    self.text.setLabel(chr(10) + "[B]%s[/B]" % promo)
                    self.text2.setLabel(chr(10) + "[B]%s[/B]" % promo)
                    self.text.setAnimations([('WindowOpen', 'effect=fade start=0 end=100 time=250 delay=125 condition=true'),
                                            ('WindowClose', 'effect=fade start=100 end=0 time=250 condition=true')])
                    self.background.setAnimations([('WindowOpen', 'effect=fade start=0 end=100 time=250 delay=125 condition=true'),
                                            ('WindowClose', 'effect=fade start=100 end=0 time=250 condition=true')])
                    xbmc.sleep(4500)
                    self.close()
                    del self
            t1 = Thread(target=(PubRegie().sP), args=(str(promo),))
            t1.start()

xbmcplugin.endOfDirectory(int(sys.argv[1]))
