import sys
import xbmc
try:
    import urllib
    from urllib import pathname2url
except:
    import urllib.parse as urllib
import xbmcaddon

def ensure_str(string, encoding='utf-8'):
    try:
        if isinstance(string, unicode):
            string = string.encode(encoding)
        if not isinstance(string, str):
            string = str(string)
        return string
    except:
        return string

def quote(string, ret=None):
    string = ensure_str(string)
    try:
        return urllib.quote_plus(string)
    except:
        if ret:
            return ret
        else:
            return string

if __name__ == '__main__':
    addon = 'plugin.video.romanianpack'
    searchmode = xbmcaddon.Addon(id=addon).getSetting('context_trakt_search_mode')
    base = 'plugin://%s' % (addon)
    info = sys.listitem.getVideoInfoTag()
    tip = info.getMediaType()
    url = '%s?action=searchSites' % (base)
    #%s?action=searchSites&modalitate=edit&query=%s&Stype=%s
    if tip == 'episode':
        word = quote(info.getTVShowTitle())
        try:
            if info.getSeason(): word = '%s S%02d' % (word, int(info.getSeason()))
        except:
            word = '%s S01' % (word)
        if searchmode != '2':
            try:
                if info.getEpisode():
                    word = '%sE%02d' % (word, int(info.getEpisode()))
            except:
                word = '%sE01' % (word)
        if searchmode == '0': url += '&modalitate=edit&query=%s' % (word)
        else: url += '&searchSites=cuvant&cuvant=%s' % (word)
    elif tip == 'movie':
        word = quote(info.getTitle())
        if searchmode == '0':
            url += '&modalitate=edit&query=%s' % (word)
        else: url += '&searchSites=cuvant&cuvant=%s' % (word)
    xbmc.executebuiltin('Container.Update(%s)' % url)
