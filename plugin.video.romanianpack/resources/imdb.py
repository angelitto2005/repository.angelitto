# -*- coding: utf-8 -*-
from .functions import *

base_url = 'https://www.imdb.com'

thumb = os.path.join(media, 'imdb.png')
nextimage = next_icon
searchimage = search_icon
name = 'IMDb'
#headers = {'Accept-Language': 'ro,en-US;q=0.7,en;q=0.3'}
headers = {'Accept-Language': 'en,en-US;q=0.7,en;q=0.3'}

def get_content(url):
    content = fetchData(url, headers=headers)
    return content

def get_data(regex, content):
    try: s = re.findall(regex, content, re.DOTALL | re.IGNORECASE)
    except: s = re.findall(regex, content.decode('utf-8'), re.DOTALL | re.IGNORECASE)
    return s

def get_genres(url):
    content = get_content(url)
    genres_container = '''aux-content-widget-2.+?genres.+?<table(.+?)</table'''
    genres_and_number = '''href=".+?>(.+?)<.+?\((.+?)\)'''
    try: genres = get_data(genres_and_number, get_data(genres_container, content)[0])
    except: genres = []
    return genres

def get_types(url):
    content = get_content(url)
    types_container = '''aux-content-widget-2.+?title\s+type.+?<table(.+?)</table'''
    types_and_number = '''href=".+?title_type=(.+?)\&.+?>(.+?)<.+?\((.+?)\)'''
    try: types = get_data(types_and_number, get_data(types_container, content)[0])
    except: types = []
    return types

def get_list(url):
    content = get_content(url)
    imdb_container = '''class="lister-item-image float-left">(.+?)(?:"filmosearch"\>|</p>\s+</div>\s+</div>\s+</div>\s+</div>)'''
    imdb_image = '''loadlate="(.+?)"'''
    imdb_title = '''adv_li_tt"(?:\s+)?>(.+?)<'''
    imdb_year = '''lister-item-year.+?>\((.+?)\)<'''
    imdb_runtime = '''runtime">(.+?)<'''
    imdb_genre = '''genre">(.+?)<'''
    imdb_rating = '''imdb-rating".+?value="(.+?)"'''
    imdb_tagline = '''<p\s+class="text-muted">(.+?)</p>'''
    imdb_cast_container = '''Stars:(.+?)</p'''
    imdb_cast = '''href="/name/.+?>(.+?)<'''
    imdb_votes = '''name="nv".+?value="(.+?)"'''
    imdb_number = '''/title/(.+?)/'''
    items = get_data(imdb_container, content)
    infos = []
    for item in items:
        try: 
            poster = get_data(imdb_image, item)[0]
            poster = re.sub(r'(\_V1).+?.jpg', r"\1.jpg", poster)
        except: poster = ''
        try: title = get_data(imdb_title, item)[0]
        except: title = ''
        try: year = get_data(imdb_year, item)[0]
        except: year = ''
        try: 
            runtime = get_data(imdb_runtime, item)[0]
            runtime = int(get_data('(\d+)', runtime)[0]) * 60
        except: runtime = ''
        try: genre = get_data(imdb_genre, item)[0]
        except: genre = ''
        try: rating = get_data(imdb_rating, item)[0]
        except: rating = ''
        try: tagline = striphtml(get_data(imdb_tagline, item)[0])
        except: tagline = ''
        try: cast = get_data(imdb_cast, get_data(imdb_cast_container, item)[0])
        except: cast = []
        try: votes = get_data(imdb_votes, item)[0]
        except: votes = ''
        try: imdb = get_data(imdb_number, item)[0]
        except: imdb = ''
        info = {
            "Genre": genre, 
            "Year": year,
            "Rating": rating,
            "CastAndRole": cast,
            "Plot": tagline,
            "PlotOutline": tagline,
            "Title": title,
            "Duration": runtime,
            "Tagline": tagline,
            "IMDBNumber": imdb,
            "Votes": votes,
            "Poster": poster,
            }
        infos.append(info)
    
    return infos
