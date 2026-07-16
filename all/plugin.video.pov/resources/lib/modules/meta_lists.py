
def years():
	from datetime import date
	return list(range(date.today().year, 1899, -1))

movie_certifications = 'G', 'PG', 'PG-13', 'R', 'NC-17', 'NR'
tvshow_certifications = 'tv-y', 'tv-y7', 'tv-g', 'tv-pg', 'tv-14', 'tv-ma'
media_lists = 'tmdb%', 'trakt%', 'mdb%', 'imdb%', 'pov%', 'POV%', 'subtitles%', 'https%'

movie_genres, tvshow_genres = {
	'Action':             ['28', 'genre_action.png'],
	'Adventure':          ['12', 'genre_adventure.png'],
	'Animation':          ['16', 'genre_animation.png'],
	'Comedy':             ['35', 'genre_comedy.png'],
	'Crime':              ['80', 'genre_crime.png'],
	'Documentary':        ['99', 'genre_documentary.png'],
	'Drama':              ['18', 'genre_drama.png'],
	'Family':             ['10751', 'genre_family.png'],
	'Fantasy':            ['14', 'genre_fantasy.png'],
	'History':            ['36', 'genre_history.png'],
	'Horror':             ['27', 'genre_horror.png'],
	'Music':              ['10402', 'genre_music.png'],
	'Mystery':            ['9648', 'genre_mystery.png'],
	'Romance':            ['10749', 'genre_romance.png'],
	'Science Fiction':    ['878', 'genre_scifi.png'],
	'TV Movie':           ['10770', 'genre_tv.png'],
	'Thriller':           ['53', 'genre_thriller.png'],
	'War':                ['10752', 'genre_war.png'],
	'Western':            ['37', 'genre_western.png']
}, {
	'Animation':          ['16', 'genre_animation.png'],
	'Action & Adventure': ['10759', 'genre_action.png'],
	'Comedy':             ['35', 'genre_comedy.png'],
	'Crime':              ['80', 'genre_crime.png'],
	'Documentary':        ['99', 'genre_documentary.png'],
	'Drama':              ['18', 'genre_drama.png'],
	'Family':             ['10751', 'genre_family.png'],
	'Kids':               ['10762', 'genre_kids.png'],
	'Mystery':            ['9648', 'genre_mystery.png'],
	'News':               ['10763', 'genre_news.png'],
	'Reality':            ['10764', 'genre_reality.png'],
	'Sci-Fi & Fantasy':   ['10765', 'genre_scifi.png'],
	'Soap':               ['10766', 'genre_soap.png'],
	'Talk':               ['10767', 'genre_talk.png'],
	'War & Politics':     ['10768', 'genre_war.png'],
	'Western':            ['37', 'genre_western.png']
}

meta_languages = {
	'English':             {'long': 'eng', 'short': 'en', 'iso': 'en'},
	'Arabic':              {'long': 'ara', 'short': 'ar', 'iso': 'ar'},
	'Arabic Saudi Arabia': {'long':    '', 'short':   '', 'iso': 'ar-SA'},
	'Bengali':             {'long': 'ben', 'short': 'bn', 'iso': 'bn'},
	'Bulgarian':           {'long': 'bul', 'short': 'bg', 'iso': 'bg'},
	'Chinese':             {'long': 'chi', 'short': 'zh', 'iso': 'zh'},
	'Croatian':            {'long': 'hrv', 'short': 'hr', 'iso': 'hr'},
	'Czech':               {'long': 'cze', 'short': 'cs', 'iso': 'cs'},
	'Danish':              {'long': 'dan', 'short': 'da', 'iso': 'da'},
	'Dutch':               {'long': 'dut', 'short': 'nl', 'iso': 'nl'},
	'Finnish':             {'long': 'fin', 'short': 'fi', 'iso': 'fi'},
	'French':              {'long': 'fre', 'short': 'fr', 'iso': 'fr'},
	'German':              {'long': 'ger', 'short': 'de', 'iso': 'de'},
	'Greek':               {'long': 'ell', 'short': 'el', 'iso': 'el'},
	'Hebrew':              {'long': 'heb', 'short': 'he', 'iso': 'he'},
	'Hindi':               {'long': 'hin', 'short': 'hi', 'iso': 'hi'},
	'Hungarian':           {'long': 'hun', 'short': 'hu', 'iso': 'hu'},
	'Icelandic':           {'long': 'ice', 'short': 'is', 'iso': 'is'},
	'Indonesian':          {'long': 'ind', 'short': 'id', 'iso': 'id'},
	'Italian':             {'long': 'ita', 'short': 'it', 'iso': 'it'},
	'Japanese':            {'long': 'jpn', 'short': 'ja', 'iso': 'ja'},
	'Korean':              {'long': 'kor', 'short': 'ko', 'iso': 'ko'},
	'Malay':               {'long': 'may', 'short': 'ms', 'iso': 'ms'},
	'Norwegian':           {'long': 'nor', 'short': 'no', 'iso': 'no'},
	'Persian':             {'long': 'per', 'short': 'fa', 'iso': 'fa'},
	'Polish':              {'long': 'pol', 'short': 'pl', 'iso': 'pl'},
	'Portuguese':          {'long': 'por', 'short': 'pt', 'iso': 'pt'},
	'Portuguese (Brazil)': {'long': 'pob', 'short': 'pb', 'iso': 'pt-BR'},
	'Punjabi':             {'long': 'pan', 'short': 'pa', 'iso': 'pa'},
	'Romanian':            {'long': 'rum', 'short': 'ro', 'iso': 'ro'},
	'Russian':             {'long': 'rus', 'short': 'ru', 'iso': 'ru'},
	'Serbian':             {'long': 'scc', 'short': 'sr', 'iso': 'sr'},
	'Slovenian':           {'long': 'slv', 'short': 'sl', 'iso': 'sl'},
	'Spanish':             {'long': 'spa', 'short': 'es', 'iso': 'es'},
	'Spanish (Mexico)':    {'long':    '', 'short':   '', 'iso': 'es-MX'},
	'Swedish':             {'long': 'swe', 'short': 'sv', 'iso': 'sv'},
	'Tagalog':             {'long': 'tgl', 'short': 'tl', 'iso': 'tl'},
	'Tamil':               {'long': 'tam', 'short': 'ta', 'iso': 'ta'},
	'Telugu':              {'long': 'tel', 'short': 'te', 'iso': 'te'},
	'Thai':                {'long': 'tha', 'short': 'th', 'iso': 'th'},
	'Turkish':             {'long': 'tur', 'short': 'tr', 'iso': 'tr'},
	'Ukrainian':           {'long': 'ukr', 'short': 'uk', 'iso': 'uk'},
	'Urdu':                {'long': 'urd', 'short': 'ur', 'iso': 'ur'},
	'Vietnamese':          {'long': 'vie', 'short': 'vi', 'iso': 'vi'}
}

networks = (
	{'logo': 'https://imgup.uk/i/b0km8HUm.png', 'id': 129,  'name': 'A&E'},
	{'logo': 'https://imgup.uk/i/J3YYYGX7.png', 'id': 2,    'name': 'ABC'},
	{'logo': 'https://imgup.uk/i/v1Es9DyO.png', 'id': 2697, 'name': 'Acorn TV'},
	{'logo': 'https://imgup.uk/i/L0r8utz4.png', 'id': 80,   'name': 'Adult Swim'},
	{'logo': 'https://imgup.uk/i/EaPIAAEB.png', 'id': 1024, 'name': 'Amazon'},
	{'logo': 'https://imgup.uk/i/GyJBgNZR.png', 'id': 174,  'name': 'AMC'},
	{'logo': 'https://imgup.uk/i/600kHyoL.png', 'id': 91,   'name': 'Animal Planet'},
	{'logo': 'https://imgup.uk/i/DVrQ5987.png', 'id': 2552, 'name': 'Apple TV +'},
	{'logo': 'https://imgup.uk/i/l8sxjdh8.png', 'id': 173,  'name': 'AT-X'},
	{'logo': 'https://imgup.uk/i/zA6NpnQK.png', 'id': 251,  'name': 'Audience'},
	{'logo': 'https://imgup.uk/i/yK9xyozN.png', 'id': 493,  'name': 'BBC America'},
	{'logo': 'https://imgup.uk/i/Yy54acmd.png', 'id': 4,    'name': 'BBC One'},
	{'logo': 'https://imgup.uk/i/aTtCan3W.png', 'id': 332,  'name': 'BBC Two'},
	{'logo': 'https://imgup.uk/i/DMKp97rI.png', 'id': 3,    'name': 'BBC Three'},
	{'logo': 'https://imgup.uk/i/pocAIDTE.png', 'id': 100,  'name': 'BBC Four'},
	{'logo': 'https://imgup.uk/i/tD79Ipre.png', 'id': 24,   'name': 'BET'},
	{'logo': 'https://imgup.uk/i/Lb2oDU2U.png', 'id': 74,   'name': 'Bravo'},
	{'logo': 'https://imgup.uk/i/HGalt0MZ.png', 'id': 56,   'name': 'Cartoon Network'},
	{'logo': 'https://imgup.uk/i/NPBQEisc.png', 'id': 32,   'name': 'CBC'},
	{'logo': 'https://imgup.uk/i/6bMnwoaB.png', 'id': 1709, 'name': 'CBS All Access'},
	{'logo': 'https://imgup.uk/i/170IZ6XM.png', 'id': 16,   'name': 'CBS'},
	{'logo': 'https://imgup.uk/i/aQZjVdY1.png', 'id': 26,   'name': 'Channel 4'},
	{'logo': 'https://imgup.uk/i/AZD6RqSW.png', 'id': 99,   'name': 'Channel 5'},
	{'logo': 'https://imgup.uk/i/9bwIrv8j.png', 'id': 359,  'name': 'Cinemax'},
	{'logo': 'https://imgup.uk/i/VZESG35d.png', 'id': 47,   'name': 'Comedy Central'},
	{'logo': 'https://imgup.uk/i/vhpzDypM.png', 'id': 928,  'name': 'Crackle'},
	{'logo': 'https://imgup.uk/i/PO4kKNF7.png', 'id': 110,  'name': 'CTV'},
	{'logo': 'https://imgup.uk/i/yN7amjvR.png', 'id': 2243, 'name': 'DC Universe'},
	{'logo': 'https://imgup.uk/i/6n8wriF1.png', 'id': 64,   'name': 'Discovery Channel'},
	{'logo': 'https://imgup.uk/i/uIx0MTfw.png', 'id': 54,   'name': 'Disney Channel'},
	{'logo': 'https://imgup.uk/i/Cs0BF9Lz.png', 'id': 44,   'name': 'Disney XD'},
	{'logo': 'https://imgup.uk/i/UlvUpehj.png', 'id': 2739, 'name': 'Disney+'},
	{'logo': 'https://imgup.uk/i/bwL5PhQE.png', 'id': 76,   'name': 'E!'},
	{'logo': 'https://imgup.uk/i/bsPlewow.png', 'id': 136,  'name': 'E4'},
	{'logo': 'https://imgup.uk/i/E6cbCyrT.png', 'id': 19,   'name': 'FOX'},
	{'logo': 'https://imgup.uk/i/OylojmpZ.png', 'id': 1267, 'name': 'Freeform'},
	{'logo': 'https://imgup.uk/i/4T4wWgkc.png', 'id': 384,  'name': 'Hallmark Channel'},
	{'logo': 'https://imgup.uk/i/CjGA6ZTV.png', 'id': 3186, 'name': 'HBO Max'},
	{'logo': 'https://imgup.uk/i/XinXNgKy.png', 'id': 49,   'name': 'HBO'},
	{'logo': 'https://imgup.uk/i/qBW4f4zI.png', 'id': 210,  'name': 'HGTV'},
	{'logo': 'https://imgup.uk/i/l4GJ8jUI.png', 'id': 65,   'name': 'History Channel'},
	{'logo': 'https://imgup.uk/i/4RNRAC24.png', 'id': 453,  'name': 'Hulu'},
	{'logo': 'https://imgup.uk/i/Br8N3wq9.png', 'id': 9,    'name': 'ITV'},
	{'logo': 'https://imgup.uk/i/6ljx7vRl.png', 'id': 34,   'name': 'Lifetime'},
	{'logo': 'https://imgup.uk/i/8GhZXNIM.png', 'id': 33,   'name': 'MTV'},
	{'logo': 'https://imgup.uk/i/b8QwVqza.png', 'id': 43,   'name': 'National Geographic'},
	{'logo': 'https://imgup.uk/i/Oh5b7zV9.png', 'id': 6,    'name': 'NBC'},
	{'logo': 'https://imgup.uk/i/zIPVvGt4.png', 'id': 213,  'name': 'Netflix'},
	{'logo': 'https://imgup.uk/i/NFc8AoPj.png', 'id': 35,   'name': 'Nick Junior'},
	{'logo': 'https://imgup.uk/i/m19H8Ilu.png', 'id': 13,   'name': 'Nickelodeon'},
	{'logo': 'https://imgup.uk/i/aAfWG5vb.png', 'id': 2076, 'name': 'Paramount Network'},
	{'logo': 'https://imgup.uk/i/V8qZ0txq.png', 'id': 4330, 'name': 'Paramount+'},
	{'logo': 'https://imgup.uk/i/86kROvHA.png', 'id': 14,   'name': 'PBS'},
	{'logo': 'https://imgup.uk/i/TWdNSXIc.png', 'id': 3353, 'name': 'Peacock'},
	{'logo': 'https://imgup.uk/i/VKKHH6Yw.png', 'id': 67,   'name': 'Showtime'},
	{'logo': 'https://imgup.uk/i/hRZ8sVVK.png', 'id': 214,  'name': 'Sky One'},
	{'logo': 'https://imgup.uk/i/nYYz2jDy.png', 'id': 55,   'name': 'Spike'},
	{'logo': 'https://imgup.uk/i/AqS5xcuM.png', 'id': 318,  'name': 'Starz'},
	{'logo': 'https://imgup.uk/i/ykOpdsIU.png', 'id': 270,  'name': 'SundanceTV'},
	{'logo': 'https://imgup.uk/i/U3xBXTPn.png', 'id': 77,   'name': 'Syfy'},
	{'logo': 'https://imgup.uk/i/FKoDeNrH.png', 'id': 68,   'name': 'TBS'},
	{'logo': 'https://imgup.uk/i/VzGtJxPA.png', 'id': 71,   'name': 'The CW'},
	{'logo': 'https://imgup.uk/i/6cOuwXHV.png', 'id': 21,   'name': 'The WB'},
	{'logo': 'https://imgup.uk/i/cAjSo3b5.png', 'id': 84,   'name': 'TLC'},
	{'logo': 'https://imgup.uk/i/TgjhMo2Z.png', 'id': 41,   'name': 'TNT'},
	{'logo': 'https://imgup.uk/i/36fvsah3.png', 'id': 209,  'name': 'Travel Channel'},
	{'logo': 'https://imgup.uk/i/rfXjxgKk.png', 'id': 364,  'name': 'truTV'},
	{'logo': 'https://imgup.uk/i/9RAPA1PH.png', 'id': 397,  'name': 'TV Land'},
	{'logo': 'https://imgup.uk/i/YMEYCEdW.png', 'id': 30,   'name': 'USA Network'},
	{'logo': 'https://imgup.uk/i/4Oamxw1I.png', 'id': 158,  'name': 'VH1'},
	{'logo': 'https://imgup.uk/i/MzVh1jHB.png', 'id': 202,  'name': 'WGN America'},
	{'logo': 'https://imgup.uk/i/bxj43JrL.png', 'id': 1436, 'name': 'YouTube Red'}
)

oscar_winners = (
	1054867, 1064213, 872585, 545611, 776503, 581734, #2020s
	496243, 490132, 399055, 376867, 314365, 194662, 76203, 68734, 74643, 45269, #2010s
	12162, 12405, 6977, 1422, 1640, 70, 122, 1574, 453, 98, #2000s
	14, 1934, 597, 409, 197, 13, 424, 33, 274, 581, #1990s
	403, 380, 746, 792, 606, 279, 11050, 783, 9443, 16619, #1980s
	12102, 11778, 703, 1366, 510, 240, 9277, 238, 1051, 11202, #1970s
	3116, 17917, 10633, 874, 15121, 11113, 5769, 947, 1725, 284, #1960s
	665, 17281, 826, 2897, 15919, 654, 11426, 27191, 2769, 705, #1950s
	25430, 23383, 33667, 887, 28580, 17661, 27367, 289, 43266, 223, #1940s
	770, 34106, 43278, 43277, 12311, 3078, 56164, 33680, 42861, 143, #1930s
	65203, 28966, 631
)
