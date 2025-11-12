# -*- coding: utf-8 -*-
from .functions import *

base_url = 'https://www.cinemagia.ro'
#http://www.cinemagia.ro/filme/%s?&pn=%s

thumb = os.path.join(media, 'cinemagia.jpg')
nextimage = next_icon
searchimage = search_icon
name = 'Cinemagia'
    
def get_search_url( keyword):
    url = base_url + '/?s=' + quote(keyword)
    return url

def getKey(item):
    return item[1]

def cauta(keyword, result):
    #/cauta/?q=%s&pn=1&search_type=filme %s keyword
    return

def get_data(regex, tosearch, number=None):
    if number: data = re.compile(regex, re.IGNORECASE | re.MULTILINE | re.DOTALL).findall(tosearch)[number - 1]
    else: data = re.compile(regex, re.IGNORECASE | re.MULTILINE | re.DOTALL).findall(tosearch)
    return data

def getliste(url):
    htmlpage = fetchData(url)
    liste = []
    order = 0
    regex = '''<div class="list_preview clearfix">(.+?)<div class="list_meta">(.+?)</div>'''
    regex2 = '''img src="(.+?)".+?"up">(.+?)<.+?"down">(.+?)<.+?list_name.+?<a href="(.+?)">(.+?)</a>'''
    for lists in get_data(regex, htmlpage):
        for imagine, aprecieri, deprecieri, link, nume in re.compile(regex2, re.DOTALL).findall(lists[0]):
            imagine = re.sub('(-\d+x.+?.(jpg|png)$)', r'-imagine.\2', imagine)
            order += 1
            nume = ' '.join(striphtml(nume).split())
            nume += ' (%s filme) ' % (re.findall('cu.+?(\d+)', lists[1])[0])
            info = ' '.join((striphtml(lists[1])).split())
            info += ' | Cu %s aprecieri si %s deprecieri' % (aprecieri, deprecieri)
            descriere = {'Plot': info, 'Title': nume, 'Poster': imagine}
            liste.append([order, imagine, link, nume, descriere])
    return liste

def listmovies(url, tip):
    sendlist = []
    order = 0
    if tip == 'liste':
        htmlpage = fetchData(url, rtype='1')
        regex = '''<li class="list_item clearfix">(.+?)</div>\s*</li>'''
        for lists in get_data(regex, htmlpage):
            try: 
                imagine = get_data('img src="(.+?)"', lists, 1)
                imagine = re.sub('(-\d+x.+?.(jpg|png)$)', r'-imagine.\2', imagine)
            except: imagine = ''
            try: nume = ' '.join(striphtml(get_data('<h2>.+?>(.+?)<', lists, 1)).split())
            except: nume = ''
            try: aka = ' '.join(striphtml(get_data('<h2>.+?title">(.+?)<.+?/a>', lists, 1)).split())
            except: aka = ''
            try: an = get_data('\((\d+)\)', lists, 1)
            except: an = ''
            try: regia = ' '.join(striphtml(get_data('Regia:(.+?)</li>', lists, 1)).split())
            except: regia = ''
            try: actori = ' '.join(striphtml(get_data('Cu:(.+?)</li>', lists, 1)).split())
            except: actori = ''
            try: gen = ' '.join(get_data('Gen film:(.+?)</li>', lists, 1).split())
            except: gen = ''
            try: nota = get_data('\((IMDB.+?)\)', lists, 1)
            except: nota = ''
            try: descriere = get_data('description">(.+?)<', lists, 1)
            except: descriere = ''
            try: imdb = get_data('/title/(tt.+?)/', lists, 1)
            except: imdb = ''
            try: 
                trailerlink = get_data('href="(https://www.imdb.+?)"', lists, 1)
                trailer = '%s?action=GetTrailerimdb&link=%s&nume=%s&poster=%s&plot=%s' % (sys.argv[0], quote(trailerlink), quote(nume), quote(imagine), quote(descriere))
            except: trailer = ''
            order += 1
            nume = nume.replace('&#039;', '\'')
            #nume = nume.decode('utf-8')
            sendlist.append(getinfodata([order, imagine, nume, aka, an, regia, actori, gen, nota, trailer, descriere, imdb]))
    elif tip == 'filme':
        headers = {'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:51.0) Gecko/20100101 Firefox/51.0',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Referer': url,
            'Cookie': 'ps=30'}
        htmlpage = fetchData(url, headers=headers)
        regex = '''<div class="(?:picture|poza)">(.+?)</div>\s+</li>'''
        for lists in get_data(regex, htmlpage):
            try: 
                imagine = get_data('img src="(.+?)"', lists, 1)
                imagine = re.sub('(-\d+x.+?.(jpg|png)$)', r'-imagine.\2', imagine)
                imagine = re.sub('(-thumbnail.(jpg|png)$)', r'-imagine.\2', imagine)
            except: imagine = ''
            try: nume = ' '.join(striphtml(get_data('<h2>.+?title.+?>(.+?)<', lists, 1)).split())
            except: nume = ''
            try: aka = ' '.join(striphtml(get_data('<h2>.+?title.+?>.+?<.+?/a>(.+?)</', lists, 1)).split())
            except: aka = ''
            try: an = get_data('\((\d+)\)', lists, 1)
            except: an = ''
            try: regia = ' '.join(striphtml(get_data('Regia:(.+?)</li>', lists, 1)).split())
            except: regia = ''
            try: actori = ' '.join(striphtml(get_data('Cu:(.+?)</li>', lists, 1)).split())
            except: actori = ''
            try: gen = ''.join(get_data('Gen film:(.+?)</li>', lists, 1).split())
            except: gen = ''
            try: nota = get_data('imdb">(?:\()?(.+?)(?:\))?<', lists, 1)
            except: nota = ''
            try: descriere = ' '.join(get_data('short_body">(.+?)</div', lists, 1).split())
            except: descriere = ''
            try: imdb = get_data('/title/(tt.+?)/', lists, 1)
            except: imdb = ''
            order += 1
            nume = nume.replace('&#039;', '\'')
            try: 
                trailerlink = get_data('short_body">.+?<a href="(.+?)"', lists, 1)
                if '/trailer/' in trailerlink:
                    trailer = '%s?action=Trailercnmg&link=%s&nume=%s&poster=%s&plot=%s' % (sys.argv[0], quote(trailerlink), quote(nume), quote(imagine), quote(descriere))
                else: 
                    trailerlink = get_data('href="(https://www.imdb.+?)"', lists, 1)
                    trailer = '%s?action=GetTrailerimdb&link=%s&nume=%s&poster=%s&plot=%s' % (sys.argv[0], quote(trailerlink), quote(nume), quote(imagine), quote(descriere))
            except: trailer = ''
            sendlist.append(getinfodata([order, imagine, nume, aka, an, regia, actori, gen, nota, trailer, descriere, imdb]))
        match = re.compile('_go_next"', re.IGNORECASE).findall(htmlpage)
        if len(match) > 0:
            sendlist.append({'label': 'Next', 'poster': nextimage, 'info': {}})
    
    return sendlist

    
def getinfodata(data):
    ordine = data[0]
    imagine = data[1]
    nume = data[2]
    aka = data[3]
    an = data[4]
    regia = data[5]
    actori = data[6]
    gen = data[7]
    nota = data[8]
    trailer = data[9]
    descriere = data[10]
    imdb = data[11]
    
    genre = striphtml(gen)
    try: year = re.findall('(\d+)', an, re.DOTALL)[0]
    except: year = an
    rating = re.sub('IMDB: ', '', nota)
    if actori: listcast = striphtml(actori).split(', ')
    else: listcast = []
    director = striphtml(regia)
    plot = descriere
    title = nume if nume else aka
    dur = ''
    tagline = plot
    writer = ''
    imdb = imdb or ''
    votes = ''
    poster = imagine
    fanart = poster
    info = {
        "Genre": genre, 
        "Year": year,
        "Rating": rating, 
        "Cast": listcast,
        "CastAndRole": listcast,
        "Director": director,
        "Plot": plot,
        "PlotOutline": plot,
        "Title": title,
        "OriginalTitle": aka,
        "Duration": dur,
        "Studio": '',
        "Tagline": tagline,
        "Writer": writer,
        "IMDBNumber": imdb,
        "Votes": votes,
        "Trailer": trailer,
        "Poster": poster,
        }		
    response = {
        "label": '%s (%s)' % (title, year),
        "originallabel": '%s (%s)' % (title, year),
        "poster": poster,
        "fanart_image": fanart,
        "imdbid": imdb,
        "year": year,
        "info": info
        }
    return response

def gettari(url, tip=''):
    htmlpage = fetchData(url, rtype='1')
    tarisoara = []
    order = 0
    reg_an = '''class="filter_set.+?An<(.+?)</div'''
    regex = '''class="filter_set.+?ara<(.+?)</div'''
    reg_gen = '''<ul class="filters_list filter_genre"(.+?)</div'''
    regex2 = '''<li.+?<a href="(.+?)".+?>(.+?)<'''
    if tip == 'tari': 
        search = re.compile(regex, re.DOTALL).findall(htmlpage)[0]
    elif tip == 'gen': 
        search = re.compile(reg_gen, re.DOTALL).findall(htmlpage)[0]
    elif tip == 'ani':
        search = re.compile(reg_an, re.DOTALL).findall(htmlpage)[0]
    for link, nume in re.compile(regex2, re.DOTALL).findall(search):
        order += 1
        if not 'mai mult' in nume: tarisoara.append([order, link, nume])
    return tarisoara
              
