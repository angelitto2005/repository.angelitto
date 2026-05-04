# -*- coding: utf-8 -*-

import os
import shutil
import sys
import six
from six.moves import urllib_parse, urllib_request
from kodi_six import xbmc, xbmcgui, xbmcplugin, xbmcaddon
import xbmcvfs
import uuid

__addon__ = xbmcaddon.Addon()
__author__ = __addon__.getAddonInfo('author')
__scriptid__ = __addon__.getAddonInfo('id')
__scriptname__ = __addon__.getAddonInfo('name')
__version__ = __addon__.getAddonInfo('version')
__language__ = __addon__.getLocalizedString

translatePath = xbmcvfs.translatePath if six.PY3 else xbmc.translatePath
__cwd__ = translatePath(__addon__.getAddonInfo('path'))
__profile__ = translatePath(__addon__.getAddonInfo('profile'))
__resource__ = translatePath(os.path.join(__cwd__, 'resources', 'lib'))
__temp__ = translatePath(os.path.join(__profile__, 'temp', ''))

if xbmcvfs.exists(__temp__):
    shutil.rmtree(__temp__)
xbmcvfs.mkdirs(__temp__)

sys.path.append(__resource__)

from OSUtilities import OSDBServer, log, hashFile, normalizeString  # noqa


def Search(item):
    search_data = []
    try:
        search_data = OSDBServer().searchsubtitles(item)
    except:
        log(__name__, "failed to connect to service for subtitle search")
        xbmcgui.Dialog().notification(__scriptname__, __language__(32001), "", 3000, False)
        return

    if search_data is not None:
        search_data.sort(key=lambda x: [x['MatchedBy'] != 'moviehash',
                                        os.path.splitext(x['SubFileName'])[0] != os.path.splitext(os.path.basename(urllib_parse.unquote(item['file_original_path'])))[0],
                                        normalizeString(xbmc.getInfoLabel("VideoPlayer.OriginalTitle")).lower() not in x['SubFileName'].replace('.', ' ').lower(),
                                        x['LanguageName'] != PreferredSub])
        for item_data in search_data:
            # hack to work around issue where Brazilian is not found as language in XBMC
            if item_data["LanguageName"] == "Brazilian":
                item_data["LanguageName"] = "Portuguese (Brazil)"

            if ((item['season'] == item_data['SeriesSeason'] and item['episode'] == item_data['SeriesEpisode'])
               or (item['season'] == "" and item['episode'] == "")):  # for file search, season and episode == ""
                listitem = xbmcgui.ListItem(label=item_data["LanguageName"],
                                            label2=item_data["SubFileName"])
                listitem.setArt({'thumb': item_data["ISO639"],
                                 'icon': str(int(round(float(item_data["SubRating"]) / 2)))})
                listitem.setProperty("sync", ("false", "true")[str(item_data["MatchedBy"]) == "moviehash"])
                listitem.setProperty("hearing_imp", ("false", "true")[int(item_data["SubHearingImpaired"]) != 0])
                url = "plugin://{0}/?action=download&link={1}&ID={2}&filename={3}&format={4}".format(
                    __scriptid__,
                    item_data["ZipDownloadLink"],
                    item_data["IDSubtitleFile"],
                    item_data["SubFileName"].encode('utf-8') if six.PY2 else item_data["SubFileName"],
                    item_data["SubFormat"]
                )

                xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=url, listitem=listitem, isFolder=False)


def Download(id, url, format, stack=False):
    subtitle_list = []
    exts = [".srt", ".sub", ".txt", ".smi", ".ssa", ".ass"]
    if stack:
        """
        we only want XMLRPC download if movie is not in stack,
        you can only retreive multiple subs in zip
        """
        result = False
    else:
        subtitle = os.path.join(__temp__, "{0}.{1}".format(str(uuid.uuid4()), format))
        try:
            result = OSDBServer().download(id, subtitle)
        except:
            log(__name__, "failed to connect to service for subtitle download")
            return subtitle_list
    if not result:
        log(__name__, "Download Using HTTP")
        zip = os.path.join(__temp__, "OpenSubtitles.zip")
        f = urllib_request.urlopen(url)
        if not xbmcvfs.exists(__temp__):
            xbmcvfs.mkdir(__temp__)
        with open(zip, "wb") as subFile:
            subFile.write(f.read())
        subFile.close()
        xbmc.sleep(500)
        xcmd = 'XBMC.Extract("{0}","{1}")'.format(zip, __temp__,)
        xbmc.executebuiltin(xcmd if six.PY3 else xcmd.encode('utf-8'), True)
        for file in xbmcvfs.listdir(zip)[1]:
            file = os.path.join(__temp__, file)
            if (os.path.splitext(file)[1] in exts):
                subtitle_list.append(file)
    else:
        subtitle_list.append(subtitle)

    if xbmcvfs.exists(subtitle_list[0]):
        return subtitle_list


def takeTitleFromFocusedItem():
    labelMovieTitle = xbmc.getInfoLabel("ListItem.OriginalTitle")
    labelYear = xbmc.getInfoLabel("ListItem.Year")
    labelTVShowTitle = xbmc.getInfoLabel("ListItem.TVShowTitle")
    labelSeason = xbmc.getInfoLabel("ListItem.Season")
    labelEpisode = xbmc.getInfoLabel("ListItem.Episode")
    labelType = xbmc.getInfoLabel("ListItem.DBTYPE")    # movie/tvshow/season/episode
    isItMovie = labelType == 'movie' or xbmc.getCondVisibility("Container.Content(movies)")
    isItEpisode = labelType == 'episode' or xbmc.getCondVisibility("Container.Content(episodes)")

    title = 'SearchFor...'
    if isItMovie and labelMovieTitle and labelYear:
        title = labelMovieTitle + " " + labelYear
    elif isItEpisode and labelTVShowTitle and labelSeason and labelEpisode:
        title = ("%s S%.2dE%.2d" % (labelTVShowTitle, int(labelSeason), int(labelEpisode)))

    return title


def get_params(string=""):
    param = []
    if string == "":
        paramstring = sys.argv[2]
    else:
        paramstring = string
    if len(paramstring) >= 2:
        params = paramstring
        cleanedparams = params.replace('?', '')
        if params[len(params) - 1] == '/':
            params = params[0:len(params) - 2]
        pairsofparams = cleanedparams.split('&')
        param = {}
        for i in range(len(pairsofparams)):
            splitparams = {}
            splitparams = pairsofparams[i].split('=')
            if (len(splitparams)) == 2:
                param[splitparams[0]] = splitparams[1]

    return param


params = get_params()
if params['action'] == 'search' or params['action'] == 'manualsearch':
    log(__name__, "action '%s' called" % params['action'])
    item = {}

    if xbmc.Player().isPlaying():
        item['temp'] = False
        item['rar'] = False
        item['mansearch'] = False
        item['year'] = xbmc.getInfoLabel("VideoPlayer.Year")  # Year
        item['season'] = str(xbmc.getInfoLabel("VideoPlayer.Season"))  # Season
        item['episode'] = str(xbmc.getInfoLabel("VideoPlayer.Episode"))  # Episode
        item['tvshow'] = normalizeString(xbmc.getInfoLabel("VideoPlayer.TVshowtitle"))  # Show
        item['title'] = normalizeString(xbmc.getInfoLabel("VideoPlayer.OriginalTitle"))  # try to get original title
        item['file_original_path'] = xbmc.Player().getPlayingFile()  # Full path of a playing file
        item['3let_language'] = []  # ['scc','eng']

    else:
        item['temp'] = False
        item['rar'] = False
        item['mansearch'] = False
        item['year'] = ""
        item['season'] = ""
        item['episode'] = ""
        item['tvshow'] = ""
        item['title'] = takeTitleFromFocusedItem()
        item['file_original_path'] = ""
        item['3let_language'] = []

    PreferredSub = params.get('preferredlanguage')

    if 'searchstring' in params:
        item['mansearch'] = True
        item['mansearchstr'] = params['searchstring']

    for lang in urllib_parse.unquote(params['languages']).split(","):
        if lang == "Portuguese (Brazil)":
            lan = "pob"
        elif lang == "Greek":
            lan = "ell"
        else:
            lan = xbmc.convertLanguage(lang, xbmc.ISO_639_2)

        item['3let_language'].append(lan)

    if item['title'] == "":
        log(__name__, "VideoPlayer.OriginalTitle not found")
        item['title'] = normalizeString(xbmc.getInfoLabel("VideoPlayer.Title"))  # no original title, get just Title

    if item['episode'].lower().find("s") > -1:  # Check if season is "Special"
        item['season'] = "0"
        item['episode'] = item['episode'][-1:]

    if (item['file_original_path'].find("http") > -1):
        item['temp'] = True

    elif (item['file_original_path'].find("rar://") > -1):
        item['rar'] = True
        item['file_original_path'] = os.path.dirname(item['file_original_path'][6:])

    elif (item['file_original_path'].find("stack://") > -1):
        stackPath = item['file_original_path'].split(" , ")
        item['file_original_path'] = stackPath[0][8:]

    Search(item)

elif params['action'] == 'download':
    subs = Download(params["ID"], params["link"], params["format"])
    for sub in subs:
        listitem = xbmcgui.ListItem(label=sub)
        xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=sub, listitem=listitem, isFolder=False)


xbmcplugin.endOfDirectory(int(sys.argv[1]))
