
def years():
	from datetime import datetime
	return list(range(datetime.today().year, 1899, -1))

movie_certifications, tvshow_certifications = (
	'G', 'PG', 'PG-13', 'R', 'NC-17', 'NR'
), (
	'tv-y', 'tv-y7', 'tv-g', 'tv-pg', 'tv-14', 'tv-ma'
)

languages = (
	('Arabic', 'ar'),      ('Bosnian', 'bs'),      ('Bulgarian', 'bg'),     ('Chinese', 'zh'),
	('Croatian', 'hr'),    ('Dutch', 'nl'),        ('English', 'en'),       ('Finnish', 'fi'),
	('French', 'fr'),      ('German', 'de'),       ('Greek', 'el'),         ('Hebrew', 'he'),
	('Hindi', 'hi'),       ('Hungarian', 'hu'),    ('Icelandic', 'is'),     ('Italian', 'it'),
	('Japanese', 'ja'),    ('Korean', 'ko'),       ('Macedonian', 'mk'),    ('Norwegian', 'no'),
	('Persian', 'fa'),     ('Polish', 'pl'),       ('Portuguese', 'pt'),    ('Punjabi', 'pa'),
	('Romanian', 'ro'),    ('Russian', 'ru'),      ('Serbian', 'sr'),       ('Slovenian', 'sl'),
	('Spanish', 'es'),     ('Swedish', 'sv'),      ('Turkish', 'tr'),       ('Ukrainian', 'uk')
)

meta_languages = (
	{'name': 'Arabic Saudi Arabia', 'iso': 'ar-SA'},    {'name': 'Czech', 'iso': 'cs'},
	{'name': 'Danish', 'iso': 'da'},                    {'name': 'German', 'iso': 'de'},
	{'name': 'Greek', 'iso': 'el'},                     {'name': 'English', 'iso': 'en'},
	{'name': 'Spanish', 'iso': 'es'},                   {'name': 'Spanish (Mexico)', 'iso': 'es-MX'},
	{'name': 'Finnish', 'iso': 'fi'},                   {'name': 'French', 'iso': 'fr'},
	{'name': 'Hebrew', 'iso': 'he'},                    {'name': 'Croatian', 'iso': 'hr'},
	{'name': 'Hungarian', 'iso': 'hu'},                 {'name': 'Italian', 'iso': 'it'},
	{'name': 'Japanese', 'iso': 'ja'},                  {'name': 'Korean', 'iso': 'ko'},
	{'name': 'Dutch', 'iso': 'nl'},                     {'name': 'Norwegian', 'iso': 'no'},
	{'name': 'Polish', 'iso': 'pl'},                    {'name': 'Portuguese', 'iso': 'pt'},
	{'name': 'Portuguese (Brazil)', 'iso': 'pt-BR'},    {'name': 'Russian', 'iso': 'ru'},
	{'name': 'Slovenian', 'iso': 'sl'},                 {'name': 'Swedish', 'iso': 'sv'},
	{'name': 'Turkish', 'iso': 'tr'},                   {'name': 'Vietnamese', 'iso': 'vi'},
	{'name': 'Chinese', 'iso': 'zh'}
)

language_choices =  {
	'None': None,            'Afrikaans': 'afr',     'Albanian': 'alb',              'Arabic': 'ara',
	'Armenian': 'arm',       'Basque': 'baq',        'Bengali': 'ben',               'Bosnian': 'bos',
	'Breton': 'bre',         'Bulgarian': 'bul',     'Burmese': 'bur',               'Catalan': 'cat',
	'Chinese': 'chi',        'Croatian': 'hrv',      'Czech': 'cze',                 'Danish': 'dan',
	'Dutch': 'dut',          'English': 'eng',       'Esperanto': 'epo',             'Estonian': 'est',
	'Finnish': 'fin',        'French': 'fre',        'Galician': 'glg',              'Georgian': 'geo',
	'German': 'ger',         'Greek': 'ell',         'Hebrew': 'heb',                'Hindi': 'hin',
	'Hungarian': 'hun',      'Icelandic': 'ice',     'Indonesian': 'ind',            'Italian': 'ita',
	'Japanese': 'jpn',       'Kazakh': 'kaz',        'Khmer': 'khm',                 'Korean': 'kor',
	'Latvian': 'lav',        'Lithuanian': 'lit',    'Luxembourgish': 'ltz',         'Macedonian': 'mac',
	'Malay': 'may',          'Malayalam': 'mal',     'Manipuri': 'mni',              'Mongolian': 'mon',
	'Montenegrin': 'mne',    'Norwegian': 'nor',     'Occitan': 'oci',               'Persian': 'per',
	'Polish': 'pol',         'Portuguese': 'por',    'Portuguese(Brazil)': 'pob',    'Romanian': 'rum',
	'Russian': 'rus',        'Serbian': 'scc',       'Sinhalese': 'sin',             'Slovak': 'slo',
	'Slovenian': 'slv',      'Spanish': 'spa',       'Swahili': 'swa',               'Swedish': 'swe',
	'Syriac': 'syr',         'Tagalog': 'tgl',       'Tamil': 'tam',                 'Telugu': 'tel',
	'Thai': 'tha',           'Turkish': 'tur',       'Ukrainian': 'ukr',             'Urdu': 'urd',
	'Vietnamese': 'vie'
}

regions = (
	{'code': 'AF', 'name': 'Afghanistan'},       {'code': 'AL', 'name': 'Albania'},               {'code': 'DZ', 'name': 'Algeria'},           {'code': 'AQ', 'name': 'Antarctica'},
	{'code': 'AR', 'name': 'Argentina'},         {'code': 'AM', 'name': 'Armenia'},               {'code': 'AU', 'name': 'Australia'},         {'code': 'AT', 'name': 'Austria'},
	{'code': 'BD', 'name': 'Bangladesh'},        {'code': 'BY', 'name': 'Belarus'},               {'code': 'BE', 'name': 'Belgium'},           {'code': 'BR', 'name': 'Brazil'},
	{'code': 'BG', 'name': 'Bulgaria'},          {'code': 'KH', 'name': 'Cambodia'},              {'code': 'CA', 'name': 'Canada'},            {'code': 'CL', 'name': 'Chile'},
	{'code': 'CN', 'name': 'China'},             {'code': 'HR', 'name': 'Croatia'},               {'code': 'CZ', 'name': 'Czech Republic'},    {'code': 'DK', 'name': 'Denmark'},
	{'code': 'EG', 'name': 'Germany'},           {'code': 'FI', 'name': 'France'},                {'code': 'FR', 'name': 'Finland'},           {'code': 'DE', 'name': 'Egypt'},
	{'code': 'GR', 'name': 'Greece'},            {'code': 'HK', 'name': 'Hong Kong'},             {'code': 'HU', 'name': 'Hungary'},           {'code': 'IS', 'name': 'Iceland'},
	{'code': 'IN', 'name': 'India'},             {'code': 'ID', 'name': 'Indonesia'},             {'code': 'IR', 'name': 'Iran'},              {'code': 'IQ', 'name': 'Iraq'},
	{'code': 'IE', 'name': 'Ireland'},           {'code': 'IL', 'name': 'Israel'},                {'code': 'IT', 'name': 'Italy'},             {'code': 'JP', 'name': 'Japan'},
	{'code': 'MY', 'name': 'Malaysia'},          {'code': 'NP', 'name': 'Nepal'},                 {'code': 'NL', 'name': 'Netherlands'},       {'code': 'NZ', 'name': 'New Zealand'},
	{'code': 'NO', 'name': 'Norway'},            {'code': 'PK', 'name': 'Pakistan'},              {'code': 'PY', 'name': 'Paraguay'},          {'code': 'PE', 'name': 'Peru'},
	{'code': 'PH', 'name': 'Philippines'},       {'code': 'PL', 'name': 'Poland'},                {'code': 'PT', 'name': 'Portugal'},          {'code': 'PR', 'name': 'Puerto Rico'},
	{'code': 'RO', 'name': 'Romania'},           {'code': 'RU', 'name': 'Russian Federation'},    {'code': 'SA', 'name': 'Saudi Arabia'},      {'code': 'RS', 'name': 'Serbia'},
	{'code': 'SG', 'name': 'Singapore'},         {'code': 'SK', 'name': 'Slovakia'},              {'code': 'SI', 'name': 'Slovenia'},          {'code': 'ZA', 'name': 'South Africa'},
	{'code': 'ES', 'name': 'Spain'},             {'code': 'LK', 'name': 'Sri Lanka'},             {'code': 'SE', 'name': 'Sweden'},            {'code': 'CH', 'name': 'Switzerland'},
	{'code': 'TH', 'name': 'Thailand'},          {'code': 'TR', 'name': 'Turkey'},                {'code': 'UA', 'name': 'Ukraine'},           {'code': 'AE', 'name': 'United Arab Emirates'},
	{'code': 'GB', 'name': 'United Kingdom'},    {'code': 'US', 'name': 'United States'},         {'code': 'UY', 'name': 'Uruguay'},           {'code': 'VE', 'name': 'Venezuela'},
	{'code': 'VN', 'name': 'Viet Nam'},          {'code': 'YE', 'name': 'Yemen'},                 {'code': 'ZW', 'name': 'Zimbabwe'}
)

movie_genres = {
	'Action': ['28', 'genre_action.png'],             'Adventure': ['12', 'genre_adventure.png'],
	'Animation': ['16', 'genre_animation.png'],       'Comedy': ['35', 'genre_comedy.png'],
	'Crime': ['80', 'genre_crime.png'],               'Documentary': ['99', 'genre_documentary.png'],
	'Drama': ['18', 'genre_drama.png'],               'Family': ['10751', 'genre_family.png'],
	'Fantasy': ['14', 'genre_fantasy.png'],           'History': ['36', 'genre_history.png'],
	'Horror': ['27', 'genre_horror.png'],             'Music': ['10402', 'genre_music.png'],
	'Mystery': ['9648', 'genre_mystery.png'],         'Romance': ['10749', 'genre_romance.png'],
	'Science Fiction': ['878', 'genre_scifi.png'],    'TV Movie': ['10770', 'genre_tv.png'],
	'Thriller': ['53', 'genre_thriller.png'],         'War': ['10752', 'genre_war.png'],
	'Western': ['37', 'genre_western.png']
}

tvshow_genres = {
	'%s & %s' % ('Action', 'Adventure'): ['10759', 'genre_action.png'],    'Animation': ['16', 'genre_animation.png'],
	'Comedy': ['35', 'genre_comedy.png'],                                  'Crime': ['80', 'genre_crime.png'],
	'Documentary': ['99', 'genre_documentary.png'],                        'Drama': ['18', 'genre_drama.png'],
	'Family': ['10751', 'genre_family.png'],                               'Kids': ['10762', 'genre_kids.png'],
	'Mystery': ['9648', 'genre_mystery.png'],                              'News': ['10763', 'genre_news.png'],
	'Reality': ['10764', 'genre_reality.png'],                             'Sci-Fi & Fantasy': ['10765', 'genre_scifi.png'],
	'Soap': ['10766', 'genre_soap.png'],                                   'Talk': ['10767', 'genre_talk.png'],
	'War & Politics': ['10768', 'genre_war.png'],                          'Western': ['37', 'genre_western.png']
}

networks = (
	{'id': 54, 'name': 'Disney Channel','logo': 'https://i.imgur.com/ZCgEkp6.png'},         {'id': 44, 'name': 'Disney XD','logo': 'https://i.imgur.com/PAJJoqQ.png'},
	{'id': 2, 'name': 'ABC','logo': 'https://i.imgur.com/qePLxos.png'},                     {'id': 493, 'name': 'BBC America','logo': 'https://i.imgur.com/TUHDjfl.png'},
	{'id': 6, 'name': 'NBC','logo': 'https://i.imgur.com/yPRirQZ.png'},                     {'id': 13, 'name': 'Nickelodeon','logo': 'https://i.imgur.com/OUVoqYc.png'},
	{'id': 14, 'name': 'PBS','logo': 'https://i.imgur.com/r9qeDJY.png'},                    {'id': 16, 'name': 'CBS','logo': 'https://i.imgur.com/8OT8igR.png'},
	{'id': 19, 'name': 'FOX','logo': 'https://i.imgur.com/6vc0Iov.png'},                    {'id': 21, 'name': 'The WB','logo': 'https://i.imgur.com/rzfVME6.png'},
	{'id': 24, 'name': 'BET','logo': 'https://i.imgur.com/ZpGJ5UQ.png'},                    {'id': 30, 'name': 'USA Network','logo': 'https://i.imgur.com/Doccw9E.png'},
	{'id': 32, 'name': 'CBC','logo': 'https://i.imgur.com/unQ7WCZ.png'},                    {'id': 173, 'name': 'AT-X','logo': 'https://i.imgur.com/JshJYGN.png'},
	{'id': 33, 'name': 'MTV','logo': 'https://i.imgur.com/QM6DpNW.png'},                    {'id': 34, 'name': 'Lifetime','logo': 'https://i.imgur.com/tvYbhen.png'},
	{'id': 35, 'name': 'Nick Junior','logo': 'https://i.imgur.com/leuCWYt.png'},            {'id': 41, 'name': 'TNT','logo': 'https://i.imgur.com/WnzpAGj.png'},
	{'id': 43, 'name': 'National Geographic','logo': 'https://i.imgur.com/XCGNKVQ.png'},    {'id': 47, 'name': 'Comedy Central','logo': 'https://i.imgur.com/ko6XN77.png'},
	{'id': 49, 'name': 'HBO','logo': 'https://i.imgur.com/Hyu8ZGq.png'},                    {'id': 55, 'name': 'Spike','logo': 'https://i.imgur.com/BhXYytR.png'},
	{'id': 67, 'name': 'Showtime','logo': 'https://i.imgur.com/SawAYkO.png'},               {'id': 56, 'name': 'Cartoon Network','logo': 'https://i.imgur.com/zmOLbbI.png'},
	{'id': 65, 'name': 'History Channel','logo': 'https://i.imgur.com/LEMgy6n.png'},        {'id': 84, 'name': 'TLC','logo': 'https://i.imgur.com/c24MxaB.png'},
	{'id': 68, 'name': 'TBS','logo': 'https://i.imgur.com/RVCtt4Z.png'},                    {'id': 71, 'name': 'The CW','logo': 'https://i.imgur.com/Q8tooeM.png'},
	{'id': 74, 'name': 'Bravo','logo': 'https://i.imgur.com/TmEO3Tn.png'},                  {'id': 76, 'name': 'E!','logo': 'https://i.imgur.com/3Delf9f.png'},
	{'id': 77, 'name': 'Syfy','logo': 'https://i.imgur.com/9yCq37i.png'},                   {'id': 80, 'name': 'Adult Swim','logo': 'https://i.imgur.com/jCqbRcS.png'},
	{'id': 91, 'name': 'Animal Planet','logo': 'https://i.imgur.com/olKc4RP.png'},          {'id': 110, 'name': 'CTV','logo': 'https://i.imgur.com/qUlyVHz.png'},
	{'id': 129, 'name': 'A&E','logo': 'https://i.imgur.com/xLDfHjH.png'},                   {'id': 158, 'name': 'VH1','logo': 'https://i.imgur.com/IUtHYzA.png'},
	{'id': 174, 'name': 'AMC','logo': 'https://i.imgur.com/ndorJxi.png'},                   {'id': 928, 'name': 'Crackle','logo': 'https://i.imgur.com/53kqZSY.png'},
	{'id': 202, 'name': 'WGN America','logo': 'https://i.imgur.com/TL6MzgO.png'},           {'id': 209, 'name': 'Travel Channel','logo': 'https://i.imgur.com/mWXv7SF.png'},
	{'id': 213, 'name': 'Netflix','logo': 'https://i.imgur.com/jI5c3bw.png'},               {'id': 251, 'name': 'Audience','logo': 'https://i.imgur.com/5Q3mo5A.png'},
	{'id': 270, 'name': 'SundanceTV','logo': 'https://i.imgur.com/qldG5p2.png'},            {'id': 318, 'name': 'Starz','logo': 'https://i.imgur.com/Z0ep2Ru.png'},
	{'id': 359, 'name': 'Cinemax','logo': 'https://i.imgur.com/zWypFNI.png'},               {'id': 364, 'name': 'truTV','logo': 'https://i.imgur.com/HnB3zfc.png'},
	{'id': 384, 'name': 'Hallmark Channel','logo': 'https://i.imgur.com/zXS64I8.png'},      {'id': 397, 'name': 'TV Land','logo': 'https://i.imgur.com/1nIeDA5.png'},
	{'id': 1024, 'name': 'Amazon','logo': 'https://i.imgur.com/ru9DDlL.png'},               {'id': 1267, 'name': 'Freeform','logo': 'https://i.imgur.com/f9AqoHE.png'},
	{'id': 4, 'name': 'BBC One','logo': 'https://i.imgur.com/u8x26te.png'},                 {'id': 332, 'name': 'BBC Two','logo': 'https://i.imgur.com/SKeGH1a.png'},
	{'id': 3, 'name': 'BBC Three','logo': 'https://i.imgur.com/SDLeLcn.png'},               {'id': 100, 'name': 'BBC Four','logo': 'https://i.imgur.com/PNDalgw.png'},
	{'id': 214, 'name': 'Sky One','logo': 'https://i.imgur.com/xbgzhPU.png'},               {'id': 9, 'name': 'ITV','logo': 'https://i.imgur.com/5Hxp5eA.png'},
	{'id': 26, 'name': 'Channel 4','logo': 'https://i.imgur.com/6ZA9UHR.png'},              {'id': 99, 'name': 'Channel 5','logo': 'https://i.imgur.com/5ubnvOh.png'},
	{'id': 136, 'name': 'E4','logo': 'https://i.imgur.com/frpunK8.png'},                    {'id': 210, 'name': 'HGTV','logo': 'https://i.imgur.com/INnmgLT.png'},
	{'id': 453, 'name': 'Hulu','logo': 'https://i.imgur.com/uSD2Cdw.png'},                  {'id': 1436, 'name': 'YouTube Red','logo': 'https://i.imgur.com/ZfewP1Y.png'},
	{'id': 64, 'name': 'Discovery Channel','logo': 'https://i.imgur.com/8UrXnAB.png'},      {'id': 2739, 'name': 'Disney+','logo': 'https://i.imgur.com/DVrPgbM.png'},
	{'id': 2552, 'name': 'Apple TV +','logo': 'https://i.imgur.com/fAQMVNp.png'},           {'id': 2697, 'name': 'Acorn TV','logo': 'https://i.imgur.com/fSWB5gB.png'},
	{'id': 1709, 'name': 'CBS All Access','logo': 'https://i.imgur.com/ZvaWMuU.png'},       {'id': 3186, 'name': 'HBO Max','logo': 'https://i.imgur.com/mmRMG75.png'},
	{'id': 2243, 'name': 'DC Universe','logo': 'https://i.imgur.com/bhWIubn.png'},          {'id': 2076, 'name': 'Paramount Network','logo': 'https://i.imgur.com/ez3U6NV.png'},
	{'id': 4330, 'name': 'Paramount+','logo': 'https://i.imgur.com/dmUjWmU.png'},           {'id': 3353, 'name': 'Peacock', 'logo': 'https://imgur.com/1JXFkSM.png'}
)

meta_colors = (
	'black', 'white', 'whitesmoke', 'gainsboro', 'lightgray', 'silver', 'darkgray', 'gray', 'dimgray',
	'snow', 'floralwhite', 'ivory', 'beige', 'cornsilk', 'antiquewhite', 'bisque', 'blanchedalmond',
	'burlywood', 'darkgoldenrod', 'ghostwhite', 'azure', 'lightsaltegray', 'lightsteelblue',
	'powderblue', 'lightblue', 'skyblue', 'lightskyblue', 'deepskyblue', 'dodgerblue', 'royalblue',
	'blue', 'mediumblue', 'midnightblue', 'navy', 'darkblue', 'cornflowerblue', 'slateblue', 'slategray',
	'yellowgreen', 'springgreen', 'seagreen', 'steelblue', 'teal', 'magenta', 'deeppink', 'darkmagenta',
	'blueviolet', 'darkviolet', 'darkorchid', 'darkslateblue', 'darkslategray', 'indigo', 'cadetblue',
	'darkcyan', 'darkturquoise', 'turquoise', 'cyan', 'paleturquoise', 'lightcyan', 'mintcream', 'honeydew',
	'aqua', 'aquamarine', 'chartreuse', 'greenyellow', 'palegreen', 'lawngreen', 'lightgreen', 'lime',
	'mediumspringgreen', 'mediumturquoise', 'lightseagreen', 'mediumaquamarine', 'mediumseagreen',
	'limegreen', 'darkseagreen', 'forestgreen', 'green', 'darkgreen', 'darkolivegreen', 'olive', 'olivedab',
	'darkkhaki', 'khaki', 'gold', 'goldenrod', 'lightyellow', 'lightgoldenrodyellow', 'lemonchiffon',
	'yellow', 'seashell', 'lavenderblush', 'lavender', 'lightcoral', 'indianred', 'darksalmon',
	'lightsalmon', 'pink', 'lightpink', 'hotpink', 'magenta', 'plum', 'violet', 'orchid', 'palevioletred',
	'mediumvioletred', 'purple', 'maroon', 'mediumorchid', 'mediumpurple', 'mediumslateblue', 'thistle',
	'linen', 'mistyrose', 'palegoldenrod', 'oldlace', 'papayawhip', 'moccasin', 'navajowhite', 'peachpuff',
	'sandybrown', 'peru', 'chocolate', 'orange', 'darkorange', 'tomato', 'orangered', 'red', 'crimson',
	'salmon', 'coral', 'firebrick', 'brown', 'darkred', 'tan', 'rosybrown', 'sienna', 'saddlebrown'
)

media_lists = (
	"'tmdb%'",
	"'trakt%'",
	"'mdb%'",
	"'flicklist%'",
	"'imdb%'",
	"'salts%'",
	"'SALTS%'",
	"'subtitles%'",
	"'https%'"
)

