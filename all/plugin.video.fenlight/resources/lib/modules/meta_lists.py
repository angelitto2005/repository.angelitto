# -*- coding: utf-8 -*-

def get_years(start_year):
	from datetime import datetime
	current_year = datetime.now().year
	return [{'name': str(year), 'id': year} for year in range(current_year, start_year - 1, -1)]
	
	return years

def get_decades(start_decade):
	from datetime import datetime
	current_year = datetime.now().year
	current_decade = (current_year // 10) * 10
	return [{'name': '%ss' % decade, 'id': decade} for decade in range(current_decade, start_decade - 1, -10)]

def years_movies():
	return get_years(1900)

def years_tvshows():
	return get_years(1944)

def years_anime():
	return get_years(1961)

def decades_movies():
	return get_decades(1900)

def decades_tvshows():
	return get_decades(1940)

def decades_anime():
	return get_decades(1960)

def oscar_winners():
	return (
{'results': [{'id': 1064213}, {'id': 872585}, {'id': 545611}, {'id': 776503}, {'id': 581734}, {'id': 496243}, {'id': 490132}, {'id': 399055}, {'id': 376867}, {'id': 314365},
{'id': 194662}, {'id': 76203}, {'id': 68734}, {'id': 74643}, {'id': 45269}, {'id': 12162}, {'id': 12405}, {'id': 6977}, {'id': 1422}, {'id': 1640}],
'total_pages': 5, 'page': 1},
{'results': [{'id': 70}, {'id': 122}, {'id': 1574}, {'id': 453}, {'id': 98}, {'id': 14}, {'id': 1934}, {'id': 597}, {'id': 409}, {'id': 197}, {'id': 13}, {'id': 424}, {'id': 33},
{'id': 274}, {'id': 581}, {'id': 403}, {'id': 380}, {'id': 746}, {'id': 792}, {'id': 606}], 'total_pages': 5, 'page': 2},
{'results': [{'id': 279}, {'id': 11050}, {'id': 783}, {'id': 9443}, {'id': 16619}, {'id': 12102}, {'id': 11778}, {'id': 703}, {'id': 1366}, {'id': 510}, {'id': 240}, {'id': 9277},
{'id': 238}, {'id': 1051}, {'id': 11202}, {'id': 3116}, {'id': 17917}, {'id': 10633}, {'id': 874}, {'id': 15121}], 'total_pages': 5, 'page': 3},
{'results': [{'id': 11113}, {'id': 5769}, {'id': 947}, {'id': 1725}, {'id': 284}, {'id': 665}, {'id': 17281}, {'id': 826}, {'id': 2897}, {'id': 15919}, {'id': 654}, {'id': 11426},
{'id': 27191}, {'id': 2769}, {'id': 705}, {'id': 25430}, {'id': 23383}, {'id': 33667}, {'id': 887}, {'id': 28580}], 'total_pages': 5, 'page': 4},
{'results': [{'id': 17661}, {'id': 27367}, {'id': 289}, {'id': 43266}, {'id': 223}, {'id': 770}, {'id': 34106}, {'id': 43278}, {'id': 43277}, {'id': 12311}, {'id': 3078}, {'id': 56164},
{'id': 33680}, {'id': 42861}, {'id': 143}, {'id': 65203}, {'id': 28966}, {'id': 631}], 'total_pages': 5, 'page': 5}
	)

def movie_certifications():
	return [
{'name': 'G', 'id': 'G'}, {'name': 'PG', 'id': 'PG'}, {'name': 'PG-13', 'id': 'PG-13'},
{'name': 'R', 'id': 'R'}, {'name': 'NC-17', 'id': 'NC-17'}, {'name': 'NR', 'id': 'NR'}
	]

def tvshow_certifications():
	return [
{'name': 'TV-Y', 'id': 'tv-y'}, {'name': 'TV-Y7', 'id': 'tv-y7'}, {'name': 'TV-G', 'id': 'tv-g'},
{'name': 'TV-PG', 'id': 'tv-pg'}, {'name': 'TV-14', 'id': 'tv-14'}, {'name': 'TV-MA', 'id': 'tv-ma'}
	]

def languages():
	return [
{'name': 'Arabic', 'id': 'ar'}, {'name': 'Bosnian', 'id': 'bs'}, {'name': 'Bulgarian', 'id': 'bg'}, {'name': 'Chinese', 'id': 'zh'}, {'name': 'Croatian', 'id': 'hr'},
{'name': 'Dutch', 'id': 'nl'}, {'name': 'English', 'id': 'en'}, {'name': 'Finnish', 'id': 'fi'}, {'name': 'French', 'id': 'fr'}, {'name': 'German', 'id': 'de'},
{'name': 'Greek', 'id': 'el'}, {'name': 'Hebrew', 'id': 'he'}, {'name': 'Hindi', 'id': 'hi'}, {'name': 'Hungarian', 'id': 'hu'}, {'name': 'Icelandic', 'id': 'is'},
{'name': 'Italian', 'id': 'it'}, {'name': 'Japanese', 'id': 'ja'}, {'name': 'Korean', 'id': 'ko'}, {'name': 'Macedonian', 'id': 'mk'}, {'name': 'Norwegian', 'id': 'no'},
{'name': 'Persian', 'id': 'fa'}, {'name': 'Polish', 'id': 'pl'}, {'name': 'Portuguese', 'id': 'pt'}, {'name': 'Punjabi', 'id': 'pa'}, {'name': 'Romanian', 'id': 'ro'},
{'name': 'Russian', 'id': 'ru'}, {'name': 'Serbian', 'id': 'sr'}, {'name': 'Slovenian', 'id': 'sl'}, {'name': 'Spanish', 'id': 'es'}, {'name': 'Swedish', 'id': 'sv'},
{'name': 'Turkish', 'id': 'tr'}, {'name': 'Ukrainian', 'id': 'uk'}, {'name': 'Vietnamese', 'id': 'vi'}
	]

def language_choices():
	return {
'None': 'None',              'Afrikaans': 'afr',            'Albanian': 'alb',             'Arabic': 'ara',
'Armenian': 'arm',           'Basque': 'baq',               'Bengali': 'ben',              'Bosnian': 'bos',
'Breton': 'bre',             'Bulgarian': 'bul',            'Burmese': 'bur',              'Catalan': 'cat',
'Chinese': 'chi',            'Croatian': 'hrv',             'Czech': 'cze',                'Danish': 'dan',
'Dutch': 'dut',              'English': 'eng',              'Esperanto': 'epo',            'Estonian': 'est',
'Finnish': 'fin',            'French': 'fre',               'Galician': 'glg',             'Georgian': 'geo',
'German': 'ger',             'Greek': 'ell',                'Hebrew': 'heb',               'Hindi': 'hin',
'Hungarian': 'hun',          'Icelandic': 'ice',            'Indonesian': 'ind',           'Italian': 'ita',
'Japanese': 'jpn',           'Kazakh': 'kaz',               'Khmer': 'khm',                'Korean': 'kor',
'Latvian': 'lav',            'Lithuanian': 'lit',           'Luxembourgish': 'ltz',        'Macedonian': 'mac',
'Malay': 'may',              'Malayalam': 'mal',            'Manipuri': 'mni',             'Mongolian': 'mon',
'Montenegrin': 'mne',        'Norwegian': 'nor',            'Occitan': 'oci',              'Persian': 'per',
'Polish': 'pol',             'Portuguese': 'por',           'Portuguese(Brazil)': 'pob',   'Romanian': 'rum',
'Russian': 'rus',            'Serbian': 'scc',              'Sinhalese': 'sin',            'Slovak': 'slo',
'Slovenian': 'slv',          'Spanish': 'spa',              'Swahili': 'swa',              'Swedish': 'swe',
'Syriac': 'syr',             'Tagalog': 'tgl',              'Tamil': 'tam',                'Telugu': 'tel',
'Thai': 'tha',               'Turkish': 'tur',              'Ukrainian': 'ukr',            'Urdu': 'urd',
'Vietnamese': 'vie'
	}

def regions():
	return [
{'id': 'AF', 'name': 'Afghanistan'},        {'id': 'AL', 'name': 'Albania'},          {'id': 'DZ', 'name': 'Algeria'},
{'id': 'AQ', 'name': 'Antarctica'},         {'id': 'AR', 'name': 'Argentina'},        {'id': 'AM', 'name': 'Armenia'},
{'id': 'AU', 'name': 'Australia'},          {'id': 'AT', 'name': 'Austria'},          {'id': 'BD', 'name': 'Bangladesh'},
{'id': 'BY', 'name': 'Belarus'},            {'id': 'BE', 'name': 'Belgium'},          {'id': 'BR', 'name': 'Brazil'},
{'id': 'BG', 'name': 'Bulgaria'},           {'id': 'KH', 'name': 'Cambodia'},         {'id': 'CA', 'name': 'Canada'},
{'id': 'CL', 'name': 'Chile'},              {'id': 'CN', 'name': 'China'},            {'id': 'HR', 'name': 'Croatia'},
{'id': 'CZ', 'name': 'Czech Republic'},     {'id': 'DK', 'name': 'Denmark'},          {'id': 'DE', 'name': 'Egypt'},
{'id': 'FR', 'name': 'Finland'},            {'id': 'FI', 'name': 'France'},           {'id': 'EG', 'name': 'Germany'},
{'id': 'GR', 'name': 'Greece'},             {'id': 'HK', 'name': 'Hong Kong'},        {'id': 'HU', 'name': 'Hungary'},
{'id': 'IS', 'name': 'Iceland'},            {'id': 'IN', 'name': 'India'},            {'id': 'ID', 'name': 'Indonesia'},
{'id': 'IR', 'name': 'Iran'},               {'id': 'IQ', 'name': 'Iraq'},             {'id': 'IE', 'name': 'Ireland'},
{'id': 'IL', 'name': 'Israel'},             {'id': 'IT', 'name': 'Italy'},            {'id': 'JP', 'name': 'Japan'},
{'id': 'MY', 'name': 'Malaysia'},           {'id': 'NP', 'name': 'Nepal'},            {'id': 'NL', 'name': 'Netherlands'},
{'id': 'NZ', 'name': 'New Zealand'},        {'id': 'NO', 'name': 'Norway'},           {'id': 'PK', 'name': 'Pakistan'},
{'id': 'PY', 'name': 'Paraguay'},           {'id': 'PE', 'name': 'Peru'},             {'id': 'PH', 'name': 'Philippines'},
{'id': 'PL', 'name': 'Poland'},             {'id': 'PT', 'name': 'Portugal'},         {'id': 'PR', 'name': 'Puerto Rico'},
{'id': 'RO', 'name': 'Romania'},            {'id': 'RU', 'name': 'Russia'},           {'id': 'SA', 'name': 'Saudi Arabia'},
{'id': 'RS', 'name': 'Serbia'},             {'id': 'SG', 'name': 'Singapore'},        {'id': 'SK', 'name': 'Slovakia'},
{'id': 'SI', 'name': 'Slovenia'},           {'id': 'ZA', 'name': 'South Africa'},     {'id': 'ES', 'name': 'Spain'},
{'id': 'LK', 'name': 'Sri Lanka'},          {'id': 'SE', 'name': 'Sweden'},           {'id': 'CH', 'name': 'Switzerland'},
{'id': 'TH', 'name': 'Thailand'},           {'id': 'TR', 'name': 'Turkey'},           {'id': 'UA', 'name': 'Ukraine'},
{'id': 'AE', 'name': 'UAE'},                {'id': 'GB', 'name': 'UK'},               {'id': 'US', 'name': 'USA'},
{'id': 'UY', 'name': 'Uruguay'},            {'id': 'VE', 'name': 'Venezuela'},        {'id': 'VN', 'name': 'Viet Nam'},
{'id': 'YE', 'name': 'Yemen'},              {'id': 'ZW', 'name': 'Zimbabwe'}
	]

def movie_genres():
	return [
{'id': '28', 'name': 'Action'},      {'id': '12', 'name': 'Adventure'},  {'id': '16', 'name': 'Animation'},
{'id': '35', 'name': 'Comedy'},      {'id': '80', 'name': 'Crime'},      {'id': '99', 'name': 'Documentary'},
{'id': '18', 'name': 'Drama'},       {'id': '10751', 'name': 'Family'},  {'id': '14', 'name': 'Fantasy'},
{'id': '36', 'name': 'History'},     {'id': '27', 'name': 'Horror'},     {'id': '10402', 'name': 'Music'},
{'id': '9648', 'name': 'Mystery'},   {'id': '10749', 'name': 'Romance'}, {'id': '878', 'name': 'Science Fiction'},
{'id': '10770', 'name': 'TV Movie'}, {'id': '53', 'name': 'Thriller'},   {'id': '10752', 'name': 'War'},
{'id': '37', 'name': 'Western'}
	]

def tvshow_genres():
	return [
{'id': '10759', 'name': 'Action & Adventure'}, {'id': '16', 'name': 'Animation'},   {'id': '35', 'name': 'Comedy'},
{'id': '80', 'name': 'Crime'},                 {'id': '99', 'name': 'Documentary'}, {'id': '18', 'name': 'Drama'},
{'id': '10751', 'name': 'Family'},             {'id': '10762', 'name': 'Kids'},     {'id': '9648', 'name': 'Mystery'},
{'id': '10763', 'name': 'News'},               {'id': '10764', 'name': 'Reality'},  {'id': '10765', 'name': 'Sci-Fi & Fantasy'},
{'id': '10766', 'name': 'Soap'},               {'id': '10767', 'name': 'Talk'},     {'id': '10768', 'name': 'War & Politics'},
{'id': '37', 'name': 'Western'}
	]

def anime_genres():
	return [
{'id': '10759', 'name': 'Action & Adventure'}, {'id': '35', 'name': 'Comedy'},              {'id': '80', 'name': 'Crime'},
{'id': '18', 'name': 'Drama'},                 {'id': '10751', 'name': 'Family'},           {'id': '10762', 'name': 'Kids'},
{'id': '9648', 'name': 'Mystery'},             {'id': '10765', 'name': 'Sci-Fi & Fantasy'}, {'id': '10768', 'name': 'War & Politics'},
{'id': '37', 'name': 'Western'}
	]

def networks():
	return sorted([
{'id': 129, 'name': 'A&E'},              {'id': 2, 'name': 'ABC'},                  {'id': 174, 'name': 'AMC'},              {'id': 2697, 'name': 'Acorn TV'},
{'id': 1024, 'name': 'Amazon'},          {'id': 91, 'name': 'Animal Planet'},       {'id': 2552, 'name': 'Apple TV +'},      {'id': 251, 'name': 'Audience'},
{'id': 4, 'name': 'BBC 1'},              {'id': 332, 'name': 'BBC 2'},              {'id': 3, 'name': 'BBC 3'},              {'id': 100, 'name': 'BBC 4'},
{'id': 493, 'name': 'BBC America'},      {'id': 24, 'name': 'BET'},                 {'id': 74, 'name': 'Bravo'},             {'id': 23, 'name': 'CBC'},
{'id': 16, 'name': 'CBS'},               {'id': 1709, 'name': 'CBS All Access'},    {'id': 110, 'name': 'CTV'},              {'id': 56, 'name': 'Cartoon Network'},
{'id': 26, 'name': 'Channel 4'},         {'id': 99, 'name': 'Channel 5'},           {'id': 359, 'name': 'Cinemax'},          {'id': 47, 'name': 'Comedy Central'},
{'id': 928, 'name': 'Crackle'},          {'id': 2243, 'name': 'DC Universe'},       {'id': 64, 'name': 'Discovery Channel'}, {'id': 244, 'name': 'Discovery ID'},
{'id': 4353, 'name': 'Discovery+'},      {'id': 54, 'name': 'Disney Channel'},      {'id': 44, 'name': 'Disney XD'},         {'id': 2739, 'name': 'Disney+'},
{'id': 76, 'name': 'E!'},                {'id': 136, 'name': 'E4'},                 {'id': 19, 'name': 'FOX'},               {'id': 88, 'name': 'FX'},
{'id': 1267, 'name': 'Freeform'},        {'id': 49, 'name': 'HBO'},                 {'id': 3186, 'name': 'HBO Max'},         {'id': 210, 'name': 'HGTV'},
{'id': 384, 'name': 'Hallmark Channel'}, {'id': 65, 'name': 'History Channel'},     {'id': 453, 'name': 'Hulu'},             {'id': 9, 'name': 'ITV'},
{'id': 34, 'name': 'Lifetime'},          {'id': 33, 'name': 'MTV'},                 {'id': 6, 'name': 'NBC'},                {'id': 43, 'name': 'National Geographic'},
{'id': 213, 'name': 'Netflix'},          {'id': 35, 'name': 'Nick Junior'},         {'id': 13, 'name': 'Nickelodeon'},       {'id': 132, 'name': 'Oxygen'},
{'id': 14, 'name': 'PBS'},               {'id': 2076, 'name': 'Paramount Network'}, {'id': 4330, 'name': 'Paramount+'},      {'id': 3353, 'name': 'Peacock'},
{'id': 67, 'name': 'Showtime'},          {'id': 214, 'name': 'Sky 1'},              {'id': 55, 'name': 'Spike'},             {'id': 318, 'name': 'Starz'},
{'id': 270, 'name': 'SundanceTV'},       {'id': 77, 'name': 'Syfy'},                {'id': 68, 'name': 'TBS'},               {'id': 84, 'name': 'TLC'},
{'id': 41, 'name': 'TNT'},               {'id': 397, 'name': 'TV Land'},            {'id': 71, 'name': 'The CW'},            {'id': 21, 'name': 'The WB'},
{'id': 209, 'name': 'Travel Channel'},   {'id': 30, 'name': 'USA Network'},         {'id': 158, 'name': 'VH1'},              {'id': 202, 'name': 'WGN America'},
{'id': 1436, 'name': 'YouTube Red'},     {'id': 364, 'name': 'truTV'},              {'id': 80, 'name': 'Adult Swim'}
	], key=lambda k: k['name'], reverse=True)

def watch_providers_movies():
	return [
{'id': 8, 'name': 'Netflix'},                {'id': 9, 'name': 'Amazon Prime Video'},    {'id': 337, 'name': 'Disney Plus'},
{'id': 3, 'name': 'Google Play Movies'},     {'id': 309, 'name': 'Sun Nxt'},             {'id': 2, 'name': 'Apple TV'},
{'id': 11, 'name': 'MUBI'},                  {'id': 350, 'name': 'Apple TV Plus'},       {'id': 257, 'name': 'fuboTV'},
{'id': 445, 'name': 'Classix'},              {'id': 15, 'name': 'Hulu'},                 {'id': 190, 'name': 'Curiosity Stream'},
{'id': 531, 'name': 'Paramount Plus'},       {'id': 100, 'name': 'GuideDoc'},            {'id': 638, 'name': 'Public Domain Movies'},
{'id': 384, 'name': 'HBO Max'},              {'id': 175, 'name': 'Netflix Kids'},        {'id': 677, 'name': 'Eventive'},
{'id': 521, 'name': 'Spamflix'},             {'id': 526, 'name': 'AMC+'},                {'id': 692, 'name': 'Cultpix'},
{'id': 475, 'name': 'DOCSVILLE'},            {'id': 386, 'name': 'Peacock'},             {'id': 457, 'name': 'VIX '},
{'id': 701, 'name': 'FilmBox+'},             {'id': 387, 'name': 'Peacock Premium'},     {'id': 532, 'name': 'aha'},
{'id': 10, 'name': 'Amazon Video'},          {'id': 464, 'name': 'Kocowa'},              {'id': 546, 'name': 'WOW Presents Plus'},
{'id': 1771, 'name': 'Takflix'},             {'id': 283, 'name': 'Crunchyroll'},         {'id': 192, 'name': 'YouTube'},
{'id': 551, 'name': 'Magellan TV'},          {'id': 554, 'name': 'BroadwayHD'},          {'id': 575, 'name': 'KoreaOnDemand'},
{'id': 444, 'name': 'Dekkoo'},               {'id': 1855, 'name': 'Starz Apple TV'},     {'id': 559, 'name': 'Filmzie'},
{'id': 675, 'name': 'Showtime Apple TV'},    {'id': 567, 'name': 'True Story'},          {'id': 1854, 'name': 'AMC+ Apple TV '},
{'id': 569, 'name': 'DocAlliance Films'},    {'id': 1852, 'name': 'Britbox Apple TV '},  {'id': 315, 'name': 'Hoichoi'},
{'id': 151, 'name': 'BritBox'},              {'id': 300, 'name': 'Pluto TV'},            {'id': 43, 'name': 'Starz'},
{'id': 344, 'name': 'Rakuten Viki'},         {'id': 584, 'name': 'Discovery+ Amazon'},   {'id': 581, 'name': 'iQIYI'},
{'id': 203, 'name': 'Showtime Amazon'},      {'id': 528, 'name': 'AMC+ Amazon'},         {'id': 269, 'name': 'Funimation Now'},
{'id': 207, 'name': 'Roku Channel'},         {'id': 632, 'name': 'Roku Premium'},        {'id': 1875, 'name': 'Runtime'},
{'id': 635, 'name': 'AMC+ Roku Premium'},    {'id': 188, 'name': 'YouTube Premium'},     {'id': 235, 'name': 'YouTube Free'},
{'id': 212, 'name': 'Hoopla'},               {'id': 83, 'name': 'The CW'},               {'id': 7, 'name': 'Vudu'},
{'id': 634, 'name': 'Starz Roku Premium'},   {'id': 332, 'name': 'VUDU Free'},           {'id': 258, 'name': 'Criterion'},
{'id': 37, 'name': 'Showtime'},              {'id': 209, 'name': 'PBS'},                 {'id': 123, 'name': 'FXNow'},
{'id': 177, 'name': 'Pantaflix'},            {'id': 73, 'name': 'Tubi TV'},              {'id': 191, 'name': 'Kanopy'},
{'id': 243, 'name': 'Comedy Central'},       {'id': 68, 'name': 'Microsoft Store'},      {'id': 279, 'name': 'Redbox'},
{'id': 148, 'name': 'ABC'},                  {'id': 12, 'name': 'Crackle'},              {'id': 358, 'name': 'DIRECTV'},
{'id': 25, 'name': 'Fandor'},                {'id': 34, 'name': 'MGM Plus'},             {'id': 211, 'name': 'Freeform'},
{'id': 215, 'name': 'Syfy'},                 {'id': 157, 'name': 'Lifetime'},            {'id': 14, 'name': 'realeyz'},
{'id': 99, 'name': 'Shudder'},               {'id': 185, 'name': 'Screambox'},           {'id': 87, 'name': 'Acorn TV'},
{'id': 143, 'name': 'Sundance Now'},         {'id': 241, 'name': 'Popcornflix'},         {'id': 247, 'name': 'Pantaya'},
{'id': 248, 'name': 'Boomerang'},            {'id': 251, 'name': 'Urban Movie Channel'}, {'id': 254, 'name': 'Dove Channel'},
{'id': 268, 'name': 'History Vault'},        {'id': 261, 'name': 'Nickhits'},            {'id': 218, 'name': 'Eros Now'},
{'id': 255, 'name': 'Yupp TV'},              {'id': 259, 'name': 'Magnolia Selects'},    {'id': 260, 'name': 'WWE Network'},
{'id': 262, 'name': 'Noggin'},               {'id': 276, 'name': 'Smithsonian Channel'}, {'id': 275, 'name': 'Laugh Out Loud'},
{'id': 281, 'name': 'Hallmark Movies'},      {'id': 278, 'name': 'Pure Flix'},           {'id': 284, 'name': 'Lifetime Movie Club'},
{'id': 289, 'name': 'Cinemax'},              {'id': 433, 'name': 'OVID'},                {'id': 1811, 'name': 'Cohen Media Amazon'},
{'id': 295, 'name': 'Viewster Amazon'},      {'id': 322, 'name': 'USA Network'},         {'id': 299, 'name': 'Sling TV'},
{'id': 430, 'name': 'HiDive'},               {'id': 454, 'name': 'Topic'},               {'id': 455, 'name': 'Night Flight Plus'},
{'id': 446, 'name': 'Retrocrush'},           {'id': 439, 'name': 'Shout! Factory TV'},   {'id': 438, 'name': 'Chai Flicks'},
{'id': 294, 'name': 'PBS Masterpiece'},      {'id': 470, 'name': 'The Film Detective'},  {'id': 201, 'name': 'MUBI Amazon'},
{'id': 196, 'name': 'AcornTV Amazon'},       {'id': 202, 'name': 'Screambox Amazon'},    {'id': 343, 'name': 'Bet+ Amazon'},
{'id': 331, 'name': 'FlixFling'},            {'id': 355, 'name': 'Darkmatter TV'},       {'id': 352, 'name': 'AMC on Demand'},
{'id': 361, 'name': 'TCM'},                  {'id': 363, 'name': 'TNT'},                 {'id': 397, 'name': 'BBC America'},
{'id': 368, 'name': 'IndieFlix'},            {'id': 417, 'name': 'Here TV'},             {'id': 432, 'name': 'Flix Premiere'},
{'id': 506, 'name': 'TBS'},                  {'id': 514, 'name': 'AsianCrush'},          {'id': 471, 'name': 'FILMRISE'},
{'id': 473, 'name': 'Revry'},                {'id': 486, 'name': 'Spectrum On Demand'},  {'id': 504, 'name': 'VRV'},
{'id': 503, 'name': 'Hi-YAH'},               {'id': 507, 'name': 'tru TV'},              {'id': 520, 'name': 'Discovery+'},
{'id': 529, 'name': 'ARROW'},                {'id': 538, 'name': 'Plex'},                {'id': 547, 'name': 'Alamo'},
{'id': 536, 'name': 'Dogwoof'},              {'id': 562, 'name': 'MovieSaints'},         {'id': 579, 'name': 'Film Movement+'},
{'id': 585, 'name': 'Metrograph'},           {'id': 613, 'name': 'Freevee'},             {'id': 640, 'name': 'Kino Now'},
{'id': 688, 'name': 'ShortsTV Amazon'},      {'id': 1759, 'name': 'Bet+'},               {'id': 1768, 'name': 'ESPN Plus'},
{'id': 1770, 'name': 'Paramount+ Showtime'}, {'id': 1793, 'name': 'Klassiki'},           {'id': 1794, 'name': 'Starz Amazon'},
{'id': 76, 'name': 'Viaplay'},               {'id': 1832, 'name': 'Popflick'}
	]

def watch_providers_tvshows():
	return [
{'id': 8, 'name': 'Netflix'},                   {'id': 9, 'name': 'Amazon Prime Video'},             {'id': 337, 'name': 'Disney +'},
{'id': 2, 'name': 'Apple TV'},                  {'id': 3, 'name': 'Google Play Movies'},             {'id': 15, 'name': 'Hulu'},
{'id': 11, 'name': 'MUBI'},                     {'id': 485, 'name': 'Rooster Teeth'},                {'id': 257, 'name': 'fuboTV'},
{'id': 531, 'name': 'Paramount +'},             {'id': 384, 'name': 'HBO Max'},                      {'id': 1899, 'name': 'Max'},
{'id': 175, 'name': 'Netflix Kids'},            {'id': 350, 'name': 'Apple TV +'},                   {'id': 1825, 'name': 'Max Amazon'},
{'id': 583, 'name': 'MGM + Amazon'},            {'id': 309, 'name': 'Sun Nxt'},                      {'id': 1968, 'name': 'Crunchyroll Amazon'},
{'id': 190, 'name': 'Curiosity Stream'},        {'id': 457, 'name': 'VIX '},                         {'id': 532, 'name': 'aha'},
{'id': 386, 'name': 'Peacock'},                 {'id': 387, 'name': 'Peacock Premium'},              {'id': 464, 'name': 'Kocowa'},
{'id': 475, 'name': 'DOCSVILLE'},               {'id': 546, 'name': 'WOW Presents +'},               {'id': 10, 'name': 'Amazon Video'},
{'id': 551, 'name': 'Magellan TV'},             {'id': 554, 'name': 'BroadwayHD'},                   {'id': 192, 'name': 'YouTube'},
{'id': 675, 'name': 'Showtime Apple TV'},       {'id': 444, 'name': 'Dekkoo'},                       {'id': 1770, 'name': 'Paramount+'},
{'id': 1855, 'name': 'Starz Apple TV'},         {'id': 315, 'name': 'Hoichoi'},                      {'id': 1854, 'name': 'AMC + Apple TV '},
{'id': 151, 'name': 'BritBox'},                 {'id': 575, 'name': 'KoreaOnDemand'},                {'id': 1852, 'name': 'Britbox Apple TV '},
{'id': 344, 'name': 'Rakuten Viki'},            {'id': 582, 'name': 'Paramount+ Amazon'},            {'id': 300, 'name': 'Pluto TV'},
{'id': 581, 'name': 'iQIYI'},                   {'id': 692, 'name': 'Cultpix'},                      {'id': 194, 'name': 'Starz Play Amazon'},
{'id': 701, 'name': 'FilmBox+'},                {'id': 584, 'name': 'Discovery+ Amazon'},            {'id': 528, 'name': 'AMC+ Amazon'},
{'id': 1715, 'name': 'Shahid VIP'},             {'id': 269, 'name': 'Funimation Now'},               {'id': 207, 'name': 'The Roku Channel'},
{'id': 445, 'name': 'Classix'},                 {'id': 283, 'name': 'Crunchyroll'},                  {'id': 632, 'name': 'Showtime Roku'},
{'id': 633, 'name': 'Paramount+ Roku'},         {'id': 1860, 'name': 'Univer Video'},                {'id': 634, 'name': 'Starz Roku'},
{'id': 1875, 'name': 'Runtime'},                {'id': 635, 'name': 'AMC+ Roku'},                    {'id': 1853, 'name': 'Paramount+ AppleTV '},
{'id': 203, 'name': 'Showtime Amazon'},         {'id': 526, 'name': 'AMC+'},                         {'id': 636, 'name': 'MGM + Roku'},
{'id': 188, 'name': 'YouTube Premium'},         {'id': 212, 'name': 'Hoopla'},                       {'id': 83, 'name': 'The CW'},
{'id': 206, 'name': 'CW Seed'},                 {'id': 7, 'name': 'Vudu'},                           {'id': 43, 'name': 'Starz'},
{'id': 332, 'name': 'VUDU Free'},               {'id': 37, 'name': 'Showtime'},                      {'id': 209, 'name': 'PBS'},
{'id': 123, 'name': 'FXNow'},                   {'id': 177, 'name': 'Pantaflix'},                    {'id': 73, 'name': 'Tubi TV'},
{'id': 191, 'name': 'Kanopy'},                  {'id': 243, 'name': 'Comedy Central'},               {'id': 68, 'name': 'Microsoft Store'},
{'id': 279, 'name': 'Redbox'},                  {'id': 148, 'name': 'ABC'},                          {'id': 12, 'name': 'Crackle'},
{'id': 358, 'name': 'DIRECTV'},                 {'id': 80, 'name': 'AMC'},                           {'id': 79, 'name': 'NBC'},
{'id': 34, 'name': 'MGM +'},                    {'id': 211, 'name': 'Freeform'},                     {'id': 155, 'name': 'History'},
{'id': 215, 'name': 'Syfy'},                    {'id': 156, 'name': 'A&E'},                          {'id': 157, 'name': 'Lifetime'},
{'id': 99, 'name': 'Shudder'},                  {'id': 185, 'name': 'Screambox'},                    {'id': 87, 'name': 'Acorn TV'},
{'id': 143, 'name': 'Sundance Now'},            {'id': 241, 'name': 'Popcornflix'},                  {'id': 247, 'name': 'Pantaya'},
{'id': 248, 'name': 'Boomerang'},               {'id': 251, 'name': 'Urban Movie Channel'},          {'id': 254, 'name': 'Dove Channel'},
{'id': 261, 'name': 'Nickhits Amazon'},         {'id': 218, 'name': 'Eros Now'},                     {'id': 255, 'name': 'Yupp TV'},
{'id': 264, 'name': 'MyOutdoorTV'},             {'id': 259, 'name': 'Magnolia Selects'},             {'id': 260, 'name': 'WWE Network'},
{'id': 262, 'name': 'Noggin Amazon'},           {'id': 267, 'name': 'Hopster TV'},                   {'id': 276, 'name': 'Smithsonian Channel'},
{'id': 275, 'name': 'Laugh Out Loud'},          {'id': 278, 'name': 'Pure Flix'},                    {'id': 281, 'name': 'Hallmark Movies'},
{'id': 293, 'name': 'PBS Kids Amazon'},         {'id': 288, 'name': 'Boomerang Amazon'},             {'id': 289, 'name': 'Cinemax Amazon'},
{'id': 292, 'name': 'Pantaya Amazon'},          {'id': 290, 'name': 'Hallmark Amazon'},              {'id': 294, 'name': 'PBS Masterpiece Amazon'},
{'id': 291, 'name': 'MZ Choice Amazon'},        {'id': 295, 'name': 'Viewster Amazon'},              {'id': 430, 'name': 'HiDive'},
{'id': 454, 'name': 'Topic'},                   {'id': 453, 'name': 'MTV'},                          {'id': 446, 'name': 'Retrocrush'},
{'id': 439, 'name': 'Shout! Factory TV'},       {'id': 438, 'name': 'Chai Flicks'},                  {'id': 427, 'name': 'Mhz Choice'},
{'id': 458, 'name': 'Vice TV '},                {'id': 204, 'name': 'Shudder Amazon'},               {'id': 201, 'name': 'MUBI Amazon'},
{'id': 196, 'name': 'AcornTV Amazon'},          {'id': 197, 'name': 'BritBox Amazon'},               {'id': 199, 'name': 'Fandor Amazon'},
{'id': 202, 'name': 'Screambox Amazon'},        {'id': 205, 'name': 'Sundance Now Amazon'},          {'id': 317, 'name': 'Cartoon Network'},
{'id': 318, 'name': 'Adult Swim'},              {'id': 322, 'name': 'USA Network'},                  {'id': 328, 'name': 'Fox'},
{'id': 343, 'name': 'Bet+ Amazon'},             {'id': 331, 'name': 'FlixFling'},                    {'id': 355, 'name': 'Darkmatter TV'},
{'id': 365, 'name': 'Bravo TV'},                {'id': 363, 'name': 'TNT'},                          {'id': 366, 'name': 'Food Network'},
{'id': 397, 'name': 'BBC America'},             {'id': 368, 'name': 'IndieFlix'},                    {'id': 412, 'name': 'TLC'},
{'id': 398, 'name': 'AHCTV'},                   {'id': 406, 'name': 'HGTV'},                         {'id': 405, 'name': 'DIY Network'},
{'id': 408, 'name': 'Investigation Discovery'}, {'id': 411, 'name': 'Science Channel'},              {'id': 402, 'name': 'Destination America'},
{'id': 404, 'name': 'Discovery Life'},          {'id': 399, 'name': 'Animal Planet'},                {'id': 403, 'name': 'Discovery'},
{'id': 410, 'name': 'Motor Trend'},             {'id': 413, 'name': 'Travel Channel'},               {'id': 400, 'name': 'Cooking Channel'},
{'id': 418, 'name': 'Paramount Network'},       {'id': 417, 'name': 'Here TV'},                      {'id': 419, 'name': 'TV Land'},
{'id': 422, 'name': 'VH1'},                     {'id': 420, 'name': 'Logo TV'},                      {'id': 263, 'name': 'DreamWorksTV Amazon'},
{'id': 506, 'name': 'TBS'},                     {'id': 514, 'name': 'AsianCrush'},                   {'id': 471, 'name': 'FILMRISE'},
{'id': 473, 'name': 'Revry'},                   {'id': 487, 'name': 'OXYGEN'},                       {'id': 486, 'name': 'Spectrum On Demand'},
{'id': 507, 'name': 'tru TV'},                  {'id': 508, 'name': 'DisneyNOW'},                    {'id': 509, 'name': 'WeTV'},
{'id': 538, 'name': 'Plex'},                    {'id': 1945, 'name': 'Plex Player'},                 {'id': 555, 'name': 'Oprah Winfrey Network'},
{'id': 613, 'name': 'Freevee'},                 {'id': 1759, 'name': 'Bet+'},                        {'id': 1794, 'name': 'Starz Amazon'},
{'id': 1796, 'name': 'Netflix Basic'},          {'id': 1811, 'name': 'Cohen Media'},                 {'id': 1832, 'name': 'Popflick'},
{'id': 76, 'name': 'Viaplay'},                  {'id': 520, 'name': 'Discovery+'},                   {'id': 1948, 'name': 'Reveel'},
{'id': 1953, 'name': 'Ovation TV'},             {'id': 1956, 'name': 'Angel Studios'},               {'id': 1957, 'name': 'Cineverse'},
{'id': 1958, 'name': 'AD tv'},                  {'id': 1960, 'name': 'Midnight Pulp'},               {'id': 1962, 'name': 'FYI Network'},
{'id': 1963, 'name': 'Xumo Play'},              {'id': 1964, 'name': 'National Geographic'},         {'id': 1971, 'name': 'DistroTV'},
{'id': 1972, 'name': 'myfilmfriend'},           {'id': 1966, 'name': 'Hallmark Movies & Mysteries'}, {'id': 1976, 'name': 'Outside Watch'},
{'id': 1985, 'name': 'Citytv'}
	]

def movie_sorts():
	return [
{'name': 'Popularity (asc)', 'id': '&sort_by=popularity.asc'}, {'name': 'Popularity (desc)', 'id': '&sort_by=popularity.desc'},
{'name': 'Release Date (asc)', 'id': '&sort_by=primary_release_date.asc'}, {'name': 'Release Date (desc)', 'id': '&sort_by=primary_release_date.desc'},
{'name': 'Total Revenue (asc)', 'id': '&sort_by=revenue.asc'}, {'name': 'Total Revenue (desc)', 'id': '&sort_by=revenue.desc'},
{'name': 'Title (asc)', 'id': '&sort_by=original_title.asc'}, {'name': 'Title (desc)', 'id': '&sort_by=original_title.desc'},
{'name': 'Rating (asc)', 'id': '&sort_by=vote_average.asc'}, {'name': 'Rating (desc)', 'id': '&sort_by=vote_average.desc'},
{'name': 'Random', 'id': '[random]'}
	]

def tvshow_sorts():
	return [
{'name': 'Popularity (asc)', 'id': '&sort_by=popularity.asc'}, {'name': 'Popularity (desc)', 'id': '&sort_by=popularity.desc'},
{'name': 'First Aired (asc)', 'id': '&sort_by=first_air_date.asc'}, {'name': 'First Aired (desc)', 'id': '&sort_by=first_air_date.desc'},
{'name': 'Rating (asc)', 'id': '&sort_by=vote_average.asc'}, {'name': 'Rating (desc)', 'id': '&sort_by=vote_average.desc'},
{'name': 'Random', 'id': '[random]'}
	]

def discover_items():
	return {
'with_year_start': {'label': 'Year Start', 'key': 'with_year_start', 'display_key': 'with_year_start_display', 'action': 'years',
'url_insert_movie': '&primary_release_date.gte=%s-01-01', 'url_insert_tvshow': '&first_air_date.gte=%s-01-01', 'name_value': ' | %s onwards', 'icon': 'calender'},
'with_year_end': {'label': 'Year End', 'key': 'with_year_end', 'display_key': 'with_year_end_display', 'action': 'years',
'url_insert_movie': '&primary_release_date.lte=%s-12-31', 'url_insert_tvshow': '&first_air_date.lte=%s-12-31', 'name_value': ' | up to %s', 'icon': 'calender'},
'with_genres': {'label': 'With Genres', 'key': 'with_genres', 'display_key': 'with_genres_display', 'action': 'genres',
'url_insert': '&with_genres=%s', 'name_value': ' | %s', 'icon': 'genres'},
'without_genres': {'label': 'Without Genres', 'key': 'without_genres', 'display_key': 'without_genres_display', 'action': 'genres',
'url_insert': '&without_genres=%s', 'name_value': ' | exclude %s', 'icon': 'genres'},
'with_network': {'label': 'Network', 'key': 'with_network', 'display_key': 'with_network_display', 'action': 'network',
'url_insert': '&with_networks=%s', 'name_value': ' | %s', 'limited': 'tvshow', 'icon': 'networks'},
'with_provider': {'label': 'Provider', 'key': 'with_provider', 'display_key': 'with_provider_display', 'action': 'provider',
'url_insert': '&with_watch_providers=%s', 'name_value': ' | %s', 'icon': 'providers'},
'with_certification': {'label': 'Certification', 'key': 'with_certification', 'display_key': 'with_certification_display', 'action': 'certifications',
'url_insert': '&certification_country=US&certification=%s', 'name_value': ' | %s', 'limited': 'movie', 'icon': 'certifications'},
'with_certification_and_lower': {'label': 'Certification (& lower)', 'key': 'with_certification_and_lower', 'display_key': 'with_certification_and_lower_display',
'action': 'certification_and_lowers', 'url_insert': '&certification_country=US&certification.lte=%s', 'name_value': ' | %s', 'limited': 'movie', 'icon': 'certifications'},
'with_language': {'label': 'Language', 'key': 'with_language', 'display_key': 'with_language_display', 'action': 'languages',
'url_insert': '&with_original_language=%s', 'name_value': ' | %s', 'icon': 'languages'},	
'with_keywords': {'label': 'With Keywords', 'key': 'with_keywords', 'display_key': 'with_keywords_display', 'action': 'keywords',
'url_insert': '&with_keywords=%s', 'name_value': ' | Keywords: %s', 'icon': 'fantasy'},
'with_rating': {'label': 'Minimum Rating', 'key': 'with_rating', 'display_key': 'with_rating_display', 'action': 'ratings',
'url_insert': '&vote_average.gte=%s', 'name_value': ' | %s+', 'icon': 'most_watched'},
'with_rating_votes': {'label': 'Minimum Number of Votes', 'key': 'with_rating_votes', 'display_key': 'with_rating_votes_display', 'action': 'votes',
'url_insert': '&vote_count.gte=%s', 'name_value': ' | %s votes', 'icon': 'most_voted'},
'with_cast': {'label': 'Include Cast', 'key': 'with_cast', 'display_key': 'with_cast_display', 'action': 'casts',
'url_insert': '&with_cast=%s', 'name_value': ' | with %s', 'limited': 'movie', 'icon': 'people'},
'with_sort': {'label': 'Sort By', 'key': 'with_sort', 'display_key': 'with_sort_display', 'action': 'sort',
'url_insert': '%s', 'name_value': ' | %s', 'icon': 'lists'},
'with_released': {'label': 'Released Only', 'key': 'with_released', 'display_key': 'with_released_display', 'action': 'released',
'url_insert_movie': '&primary_release_date.lte=%s', 'url_insert_tvshow': '&include_null_first_air_dates=false&first_air_date.lte=%s', 'name_value': ' | Released Only', 'icon': 'dvd'},
'with_adult': {'label': 'Include Adult', 'key': 'with_adult', 'display_key': 'with_adult_display', 'action': 'adult',
'url_insert': '&include_adult=%s', 'name_value': ' | Include Adult', 'limited': 'movie', 'icon': 'romance'},
	}

def color_palette():
	return [
'FFFFFFE3', 'FFFFFAE6', 'FFFEF5E6', 'FFFEF0E5', 'FFFEEBE5', 'FFFFEFEF', 'FFFFE6EA', 'FFFFE6F1', 'FFFEE6F4', 'FFFFE6FB', 'FFFEE6FE', 'FFFAE6FF', 'FFF4E6FF', 'FFF0E6FF', 'FFEAE7FC',
'FFE6E7FC', 'FFE6EBFF', 'FFE7F0FF', 'FFE7F5FF', 'FFE7FAFF', 'FFE6FFFF', 'FFE6FFFB', 'FFE7FEF4', 'FFE7FFF1', 'FFE6FFEA', 'FFE7FFE7', 'FFEBFFF3', 'FFF1FFE6', 'FFF5FFE6', 'FFFBFFE6',
'FFFFFFFF', 'FFFFFFCB', 'FFFEFACA', 'FFFFEACB', 'FFFFE0CC', 'FFFED6CC', 'FFFFCACD', 'FFFFCCD5', 'FFFFCDE0', 'FFFFCCEB', 'FFFFCBF5', 'FFFECCFD', 'FFF6CBFF', 'FFECCCFE', 'FFE0CCFF',
'FFD6CCFE', 'FFCCCCFE', 'FFCDD6FF', 'FFCAE1FF', 'FFCCEBFF', 'FFCEF4FD', 'FFCAFFFF', 'FFCCFFF6', 'FFCBFEEB', 'FFCCFFE0', 'FFCCFFD6', 'FFCDFFCC', 'FFD7FFCB', 'FFE1FFCD', 'FFEBFFCC',
'FFF5FFCB', 'FFEFEFEF', 'FFFEFFB3', 'FFFFF1B2', 'FFFFE0B2', 'FFFDD2B2', 'FFFFC2B3', 'FFFFB3B3', 'FFFFB2C2', 'FFFFB3D1', 'FFFFB3E1', 'FFFFB2F4', 'FFFFB3FE', 'FFF0B3FF', 'FFE1B2FF',
'FFD2B3FF', 'FFC1B3FE', 'FFB4B3FF', 'FFB3C1FE', 'FFB2D1FF', 'FFB3E0FF', 'FFB2F0FF', 'FFB3FFFF', 'FFB3FFF0', 'FFB4FFE0', 'FFB3FFD1', 'FFB4FEC3', 'FFB3FFB4', 'FFC2FFB2', 'FFD1FFB4',
'FFE0FFB3', 'FFF1FFB4', 'FFE0E0E0', 'FFFEFF99', 'FFFFEB9A', 'FFFED699', 'FFFFC299', 'FFFFAD98', 'FFFF9899', 'FFFF99AE', 'FFFF99C1', 'FFFE99D5', 'FFFF99EC', 'FFFF99FF', 'FFEB99FF',
'FFD699FF', 'FFC299FF', 'FFAE99FF', 'FF9A99FF', 'FF98ADFE', 'FF9AC2FF', 'FF98D6FF', 'FF99EBFF', 'FF99FFFF', 'FF99FFEA', 'FF99FFD7', 'FF9AFFC3', 'FF99FFAC', 'FF99FF99', 'FFADFF99',
'FFC2FF98', 'FFD6FF99', 'FFEAFF98', 'FFD0D0D0', 'FFFFFF80', 'FFFFE681', 'FFFFCC80', 'FFFFB381', 'FFFF9980', 'FFFE8081', 'FFFF8199', 'FFFF80B3', 'FFFF80CD', 'FFFF80E7', 'FFFC81FE',
'FFE680FF', 'FFCC7FFF', 'FFB380FF', 'FF9980FF', 'FF807FFE', 'FF8099FE', 'FF7FB3FF', 'FF80CCFE', 'FF80E6FF', 'FF7FFFFE', 'FF7FFEE0', 'FF80FFCC', 'FF80FFB2', 'FF80FF98', 'FF81FF81',
'FF99FF80', 'FFB3FF80', 'FFCCFF80', 'FFE6FF80', 'FFC0C0C0', 'FFFFFF6B', 'FFFEE066', 'FFFFC267', 'FFFFA366', 'FFFF8566', 'FFFF6766', 'FFFF6685', 'FFFF66A4', 'FFFF66C1', 'FFFF66E0',
'FFFF66FF', 'FFE166FF', 'FFC366FF', 'FFA366FF', 'FF8566FF', 'FF6665FE', 'FF6785FF', 'FF66A3FE', 'FF65C2FF', 'FF65E0FF', 'FF65FFFF', 'FF66FFE0', 'FF65FFC1', 'FF66FFA4', 'FF65FF85',
'FF66FF66', 'FF84FF66', 'FFA2FF66', 'FFC2FF66', 'FFE0FF66', 'FFAFAFAF', 'FFFFFF4D', 'FFFFDB4E', 'FFFFB84E', 'FFFF944C', 'FFFF714D', 'FFFF4D4D', 'FFFF4D6F', 'FFFE4D93', 'FFFE4DB7',
'FFFE4DDB', 'FFFF4DFF', 'FFDC4DFF', 'FFB84DFF', 'FF944EFF', 'FF704DFF', 'FF4D4CFF', 'FF4D70FE', 'FF4D94FE', 'FF4DB8FF', 'FF4DDBFF', 'FF4DFFFF', 'FF4DFFDB', 'FF4EFFB9', 'FF4EFF95',
'FF4DFE70', 'FF4CFF4C', 'FF70FF4D', 'FF94FF4D', 'FFB8FE4D', 'FFDAFF4D', 'FF8C8C8C', 'FFFFFF33', 'FFFFD634', 'FFFFAD33', 'FFFF8532', 'FFFF5C33', 'FFFF3334', 'FFFF335C', 'FFFF3287',
'FFFF33AE', 'FFFF33D6', 'FFFE33FF', 'FFD633FE', 'FFAD34FF', 'FF8534FF', 'FF5D33FF', 'FF3233FF', 'FF325CFE', 'FF3285FF', 'FF33ADFF', 'FF33D6FF', 'FF33FFFE', 'FF32FFD6', 'FF34FFAD',
'FF33FF84', 'FF32FF5C', 'FF34FF33', 'FF5CFF34', 'FF85FE33', 'FFADFE33', 'FFD5FF33', 'FF7C7C7C', 'FFFFFF19', 'FFFFD119', 'FFFFA418', 'FFFF751A', 'FFFF4719', 'FFFF1919', 'FFFF1947',
'FFFF1874', 'FFFF19A3', 'FFFF19D1', 'FFFF19FF', 'FFD019FF', 'FFA219FF', 'FF751AFE', 'FF4719FF', 'FF1819FF', 'FF1947FF', 'FF1974FF', 'FF19A3FE', 'FF18D1FF', 'FF19FFFF', 'FF19FFD1',
'FF19FFA4', 'FF18FF75', 'FF19FF47', 'FF19FF19', 'FF48FF19', 'FF76FF19', 'FFA3FE1A', 'FFD1FF19', 'FF6B6B6B', 'FFFFFF00', 'FFFFCC00', 'FFFE9900', 'FFFF6600', 'FFFF3300', 'FFFE0000',
'FFFE0032', 'FFFF0066', 'FFFF0198', 'FFFF00CC', 'FFFF00FE', 'FFCC00FF', 'FF9A00FF', 'FF6601FF', 'FF3300FF', 'FF0000FE', 'FF0033FF', 'FF0166FF', 'FF0097FE', 'FF00CCFF', 'FF00FFFF',
'FF01FFCD', 'FF00FF99', 'FF00FE67', 'FF00FF33', 'FF00FF01', 'FF33FF00', 'FF65FF00', 'FF99FE00', 'FFCCFF00', 'FF5D5D5D', 'FFE8E500', 'FFE6B800', 'FFE68B00', 'FFE65C01', 'FFE72E00',
'FFE60000', 'FFE6002E', 'FFE6005B', 'FFE80183', 'FFE600B8', 'FFE600E6', 'FFB700E6', 'FF8900E6', 'FF5C01E5', 'FF2E00E6', 'FF0000E6', 'FF012EE1', 'FF005BE7', 'FF008AE5', 'FF00B8E6',
'FF00E6E6', 'FF00E6B7', 'FF00E78B', 'FF00E65F', 'FF00E532', 'FF00E600', 'FF2FE600', 'FF5DE600', 'FF8AE501', 'FFB8E600', 'FF4F4F4F', 'FFCDCC00', 'FFCDA301', 'FFCA7B02', 'FFCC5200',
'FFCC2900', 'FFCC0001', 'FFCD0029', 'FFCE0052', 'FFCC007B', 'FFCD00A3', 'FFCB00CC', 'FFA300CB', 'FF7A01CC', 'FF5201CC', 'FF2A00D0', 'FF0000CC', 'FF0029CB', 'FF0052CC', 'FF007ACD',
'FF00A3CC', 'FF00CCCB', 'FF00CCA3', 'FF01CC7A', 'FF03CB51', 'FF00CC29', 'FF01CC00', 'FF29CC01', 'FF52CB00', 'FF7ACB00', 'FFA2CC00', 'FF434343', 'FFB4B300', 'FFB38E00', 'FFB36B00',
'FFB34700', 'FFB32501', 'FFB30101', 'FFB40025', 'FFB40047', 'FFB4006B', 'FFB5008B', 'FFB300B3', 'FF8F00B2', 'FF6B00B2', 'FF4700B4', 'FF2300B2', 'FF0000B2', 'FF0025B4', 'FF0047B3',
'FF006BB3', 'FF008EB2', 'FF00B3B2', 'FF00B38E', 'FF00B36C', 'FF00B346', 'FF00B324', 'FF00B300', 'FF24B301', 'FF47B200', 'FF6CB201', 'FF90B301', 'FF373737', 'FF999A00', 'FF987A00',
'FF995C01', 'FF9A3D00', 'FF9A1F00', 'FF990100', 'FF99001F', 'FF9A003E', 'FF99005B', 'FF9A007A', 'FF990099', 'FF7B0099', 'FF5D0099', 'FF3D0099', 'FF1F0099', 'FF000098', 'FF011F99',
'FF003D98', 'FF005C99', 'FF007A99', 'FF009999', 'FF00997A', 'FF00995B', 'FF00993E', 'FF00991F', 'FF009900', 'FF1E9900', 'FF3C9900', 'FF5C9900', 'FF7A9900', 'FF2E2E2E', 'FF7F8000',
'FF7F6601', 'FF804C00', 'FF803201', 'FF801A01', 'FF800000', 'FF800019', 'FF800033', 'FF80004B', 'FF810065', 'FF81007F', 'FF660080', 'FF4C007F', 'FF33007F', 'FF1A0080', 'FF010080',
'FF011A7F', 'FF003480', 'FF004C80', 'FF00667F', 'FF008081', 'FF008067', 'FF037F4B', 'FF008033', 'FF00801B', 'FF008001', 'FF1A8000', 'FF338000', 'FF4C8001', 'FF668100', 'FF242424',
'FF656600', 'FF675201', 'FF653D00', 'FF672900', 'FF661400', 'FF660000', 'FF660015', 'FF660028', 'FF65003C', 'FF660053', 'FF660066', 'FF550069', 'FF3D0067', 'FF290066', 'FF150067',
'FF010066', 'FF001465', 'FF012966', 'FF003D66', 'FF005267', 'FF006766', 'FF006651', 'FF00663E', 'FF01662A', 'FF006613', 'FF006600', 'FF146600', 'FF296600', 'FF3D6600', 'FF516600',
'FF181818', 'FF4B4C00', 'FF4C3E01', 'FF4D2E00', 'FF4C1F00', 'FF4D0F00', 'FF4C0000', 'FF4C000F', 'FF4B001F', 'FF4C002E', 'FF4C003E', 'FF4C004B', 'FF3D004D', 'FF2E004B', 'FF1F004C',
'FF0E004B', 'FF01004C', 'FF000E4B', 'FF001F4D', 'FF012E4D', 'FF003D4C', 'FF004C4C', 'FF004D3D', 'FF004C2E', 'FF004C1E', 'FF004C0E', 'FF004C01', 'FF0F4C00', 'FF204C01', 'FF2D4C00',
'FF3E4C01', 'FF000000'
	]

def list_display_choices(list_type):
	return {
'tmdb': {'choices': [('Title', '0'), ('Date Created (asc)', '1'), ('Date Created (desc)', '2'), ('Recently Updated (asc)', '3'), ('Recently Updated (desc)', '4'),
('Item Count (asc)', '5'), ('Item Count (desc)', '6'), ('Average Rating (asc)', '7'), ('Average Rating (desc)', '8'), ('Total Runtime (asc)', '9'),
('Total Runtime (desc)', '10'), ('Total Revenue (asc)', '11'), ('Total Revenue (desc)', '12')],
'setting': 'tmdblist'},
'personal': {'choices': [('Title', '0'), ('Author', '1'), ('Date Created (asc)', '2'), ('Date Created (desc)', '3'),
('Recently Updated (asc)', '4'), ('Recently Updated (desc)', '5'), ('Item Count (asc)', '6'), ('Item Count (desc)', '7')],
'setting': 'personal_list'}
	}[list_type]