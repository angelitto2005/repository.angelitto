"""
	Fenomscrapers Module
"""

import re
import unicodedata
from string import printable
from threading import Thread as thread
from fenom import cleantitle, log_utils
from fenom.undesirables import Undesirables
from fenom.control import homeWindow, jsloads, setting as getSetting, setSetting


LANG = ('arabic', 'bgaudio', 'castellano', 'chinese', 'dutch', 'finnish', 'french', 'german', 'greek', 'hebrew', 'italian', 'korean', 'latino', 'polish',
				'portuguese', 'russian', 'spanish', 'tamil', 'telugu', 'truefrench', 'truespanish', 'turkish')
ABV_LANG = ('.ara.', '.ces.', '.chi.', '.chs.', '.cze.', '.dan.', '.de.', '.deu.', '.dut.', '.ell.', '.es.', '.esl.', '.esp.', '.fi.', '.fin.', '.fr.', '.fra.', '.fre.', '.frn.', '.gai.', '.ger.', '.gle.', '.gre.',
						'.gtm.', '.he.', '.heb.', '.hi.', '.hin.', '.hun.', '.hindi.', '.ind.', '.iri.', '.it.', '.ita.', '.ja.', '.jap.', '.jpn.', '.ko.', '.kor.', '.lat.', '.nl.', '.lit.', '.nld.', '.nor.', '.pl.', '.pol.',
						'.pt.', '.por.', '.ru.', '.rus.', '.som.', '.spa.', '.sv.', '.sve.', '.swe.', '.tha.', '.tr.', '.tur.', '.uae.', '.uk.', '.ukr.', '.vi.', '.vie.', '.zh.', '.zho.')
DUBBED = ('bengali.dub', 'dublado', 'dubbed', 'pldub')
SUBS = ('subita', 'subfrench', 'subspanish', 'subtitula', 'swesub', 'nl.subs')

ENG_CHECK = ('.eng.', '.en.', 'english', 'multi')
SRT_CHECK = ('with.srt', '.avi', '.mkv', '.mp4')

try: UNDESIRABLES = jsloads(homeWindow.getProperty('pov_unwanted'))['undesirables']
except: UNDESIRABLES = []
# viruseproject has lots of uploads on glotorrents and site fixes the "&dn=???" portion in html title to reflect the true range the pack covers vs. assclowns incomplete pack file name used

season_list = ('one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eigh', 'nine', 'ten', 'eleven', 'twelve', 'thirteen', 'fourteen',
			'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen', 'twenty', 'twenty-one', 'twenty-two', 'twenty-three',
			'twenty-four', 'twenty-five')
season_ordinal_list = ('first', 'second', 'third', 'fourth', 'fifth', 'sixth', 'seventh', 'eighth', 'ninth', 'tenth', 'eleventh', 'twelfth',
			'thirteenth', 'fourteenth', 'fifteenth', 'sixteenth', 'seventeenth', 'eighteenth', 'nineteenth', 'twentieth', 'twenty-first',
			'twenty-second', 'twenty-third', 'twenty-fourth', 'twenty-fifth')
season_ordinal2_list = ('1st', '2nd', '3rd', '4th', '5th', '6th', '7th', '8th', '9th', '10th', '11th', '12th', '13th', '14th', '15th', '16th',
			'17th', '18th', '19th', '20th', '21st', '22nd', '23rd', '24th', '25th')

season_dict = {'1': 'one', '2': 'two', '3': 'three', '4': 'four', '5': 'five', '6': 'six', '7': 'seven', '8': 'eigh', '9': 'nine', '10': 'ten',
			'11': 'eleven', '12': 'twelve', '13': 'thirteen', '14': 'fourteen', '15': 'fifteen', '16': 'sixteen', '17': 'seventeen',
			'18': 'eighteen', '19': 'nineteen', '20': 'twenty', '21': 'twenty-one', '22': 'twenty-two', '23': 'twenty-three',
			'24': 'twenty-four', '25': 'twenty-five'}
season_ordinal_dict = {'1': 'first', '2': 'second', '3': 'third', '4': 'fourth', '5': 'fifth', '6': 'sixth', '7': 'seventh', '8': 'eighth', '9': 'ninth',
			'10': 'tenth', '11': 'eleventh', '12': 'twelfth', '13': 'thirteenth', '14': 'fourteenth', '15': 'fifteenth', '16': 'sixteenth',
			'17': 'seventeenth', '18': 'eighteenth', '19': 'nineteenth', '20': 'twentieth', '21': 'twenty-first', '22': 'twenty-second',
			'23': 'twenty-third', '24': 'twenty-fourth', '25': 'twenty-fifth'}
season_ordinal2_dict = {'1': '1st', '2': '2nd', '3': '3rd', '4': '4th', '5': '5th', '6': '6th', '7': '7th', '8': '8th', '9': '9th', '10': '10th',
			'11': '11th', '12': '12th', '13': '13th', '14': '14th', '15': '15th', '16': '16th', '17': '17th', '18': '18th', '19': '19th',
			'20': '20th', '21': '21st', '22': '22nd', '23': '23rd', '24': '24th', '25': '25th'}

try: unwanted_tags = jsloads(homeWindow.getProperty('pov_unwanted'))['unwanted']
except: unwanted_tags = []

home_getProperty = homeWindow.getProperty


class Thread(thread):
	def __init__(self, target, *args):
		self._target = target
		self._args = args
		thread.__init__(self, target=self._target, args=self._args)

def log_utils_error(*args):
	return log_utils.error(*args)

def get_undesirables():
	if not getSetting('filter.undesirables') == 'true' or home_getProperty('fs_filterless_search') == 'true' : return []
	try: undesirables = Undesirables().get_enabled()
	except: undesirables = UNDESIRABLES
	return undesirables

def remove_undesirables(release_info, undesirables):
	if any(value in release_info for value in undesirables): return True

def check_foreign_audio():
	return False if home_getProperty('fs_filterless_search') == 'true' else getSetting('filter.foreign.single.audio') == 'true'

def remove_lang(release_info, check_foreign_audio):
	if not release_info: return False

	def match(text_list):
		return any(value in release_info for value in text_list)

	try:
		if match(DUBBED) or match(SUBS): return True
		if check_foreign_audio and not match(ENG_CHECK):
			if match(LANG) or match(ABV_LANG): return True
		if release_info.endswith('.srt.') and not match(SRT_CHECK): return True
		return False
	except:
		log_utils_error()
		return False

COMPILED_RESOLUTIONS = {k: re.compile(v, re.I) for k, v in {
	'4K': r'\b(2160p?|216o|4k|ultrahd|ultra\.hd|uhd)\b',
	'1080p': r'\b(1080p?|1o8o|108o|1o80|fhd)\b',
	'720p': r'\b(720p?|72o)\b(?!mb)',
	'SCR': r'\b(dvdscr|screener|\.scr\.|r5|r6)\b',
	'CAM': r'\b(cam|camrip|dvdcam|dvdts|hdcam|hctc|hdtc|hdts|hqcam|ts|tc|tsrip|telecine|telesync)\b'
}.items()}

def get_qual(term):
	if not term: return None
	term_lower = term.lower()
	for quality, pattern in COMPILED_RESOLUTIONS.items():
		if pattern.search(term_lower): return quality
	if '.hd.' in term_lower: return '720p'
	return 'SD'

def get_release_quality(release_info, release_link=None):
	try:
		quality = get_qual(release_info) or get_qual(release_link) or 'SD'
		return quality, []
	except:
		log_utils_error()
		return 'SD', []

def aliases_to_array(aliases, filter=None):
	try:
#		if all(isinstance(x, str) for x in aliases): return aliases
		if all(isinstance(x, str) for x in aliases): return tuple(aliases)
		if not filter: filter = []
		if isinstance(filter, str): filter = [filter]
#		return [x.get('title') for x in aliases if not filter or x.get('country') in filter]
		return tuple(x.get('title') for x in aliases if not filter or x.get('country') in filter)
	except:
		log_utils_error()
		return []

RE_YEAR_PARENTHESIS = re.compile(r'([(])(?=((19|20)[0-9]{2})).*?([)])')

RE_VIDEO_RESOLUTIONS = re.compile(r'2160p|216op|4k|1080p|1o8op|108op|1o80p|720p|72op|480p|48op', re.I)

RE_EPISODE_RANGES = [re.compile(i, re.I) for i in (
	r's\d{1,3}e\d{1,3}[-.]e\d{1,3}',
	r's\d{1,3}e\d{1,3}[-.]\d{1,3}(?!p|bit|gb)(?!\d{1,3})',
	r's\d{1,3}[-.]e\d{1,3}[-.]e\d{1,3}',
	r'season[.-]?\d{1,3}[.-]?ep[.-]?\d{1,3}[-.]ep[.-]?\d{1,3}',
	r'season[.-]?\d{1,3}[.-]?episode[.-]?\d{1,3}[-.]episode[.-]?\d{1,3}'
)]

def check_title(title, aliases, release_title, hdlr, year, years=None): # non pack file title check, single eps and movies
	if years: # for movies only, scraper to pass None for episodes
		if not any(val in release_title for val in years): return False
	else:
		if not re.search(r'%s' % hdlr, release_title, re.I): return False
#	aliases = aliases_to_array(aliases)
	title_list = set()
	title_list_append = title_list.add
	if aliases:
		for item in aliases:
			try:
				alias = item.replace('&', 'and').replace(year, '')
				if years: # for movies only, scraper to pass None for episodes
					for i in years: alias = alias.replace(i, '')
				title_list_append(alias)
			except:
				log_utils_error()
	try:
		title = title.replace('&', 'and')
		title_list_append(title)

		release_title = RE_YEAR_PARENTHESIS.sub('\\2', release_title) # remove parenthesis only if surrounding a 4 digit date
		t = re.split(r'%s' % hdlr, release_title, 1, re.I)[0].replace(year, '').replace('&', 'and')
		if years:
			for i in years: t = t.split(i)[0]
		t = RE_VIDEO_RESOLUTIONS.split(t, 1)[0]
		t = cleantitle.get(t)
		if all(cleantitle.get(i) != t for i in title_list): return False

# filter to remove episode ranges that should be picked up in "filter_season_pack()" ex. "s01e01-08"
		if hdlr != year: # equal for movies but not for shows
			for regex in RE_EPISODE_RANGES: # may need to add "to", "thru"
				if regex.search(release_title): return False
		return True
	except:
		log_utils_error()
		return False

SEASON_CACHE = {}

RE_SEASON_SINGLE_EPISODE = [re.compile(i, re.I) for i in (
	r's\d{1,3}e\d{1,3}[-.](?!\d{2,3}[-.])(?!e\d{1,3})(?!\d{2}gb)',
	r'season[.-]?\d{1,3}[.-]?ep[.-]?\d{1,3}[-.](?!\d{2,3}[-.])(?!e\d{1,3})(?!\d{2}gb)',
	r'season[.-]?\d{1,3}[.-]?episode[.-]?\d{1,3}[-.](?!\d{2,3}[-.])(?!e\d{1,3})(?!\d{2}gb)'
)]

RE_SEASON_EPISODE_RANGES = [re.compile(i, re.I) for i in (
	r's\d{1,3}e(\d{1,3})[-.]e(\d{1,3})',
	r's\d{1,3}e(\d{1,3})[-.](\d{1,3})(?!p|bit|gb)(?!\d{1,3})',
	r's\d{1,3}[-.]e(\d{1,3})[-.]e(\d{1,3})',
	r'season[.-]?\d{1,3}[.-]?ep[.-]?(\d{1,3})[-.]ep[.-]?(\d{1,3})',
	r'season[.-]?\d{1,3}[.-]?episode[.-]?(\d{1,3})[-.]episode[.-]?(\d{1,3})' # may need to add "to", "thru"
)]

def filter_season_pack(show_title, aliases, year, season, release_title):
#	aliases = aliases_to_array(aliases)
	title_list = []
	title_list_append = title_list.append
	if aliases:
		for item in aliases:
			try:
				alias = item.replace('!', '').replace('(', '').replace(')', '').replace('&', 'and').replace(year, '')
				if alias in title_list: continue
				title_list_append(alias)
			except:
				log_utils_error()
	try:
		show_title = show_title.replace('!', '').replace('(', '').replace(')', '').replace('&', 'and')
		if show_title not in title_list: title_list_append(show_title)

		season_fill = season.zfill(2)
		season_check = '.s%s.' % season
		season_fill_check = '.s%s.' % season_fill
		season_fill_checke = '.s%se' % season_fill # added 3/2/22 to pick up episode range packs ex "Reacher.s01e01-08"
		season_full_check = '.season.%s.' % season
		season_full_check_ns = '.season%s.' % season
		season_full_fill_check = '.season.%s.' % season_fill
		season_full_fill_check_ns = '.season%s.' % season_fill
		split_list = (season_check, season_fill_check, season_fill_checke, '.' + season + '.season', 'total.season', 'season', 'the.complete', 'complete', year)
		string_list = (season_check, season_fill_check, season_fill_checke, season_full_check, season_full_check_ns, season_full_fill_check, season_full_fill_check_ns)

		release_title = release_title_format(release_title)
		t = release_title.replace('-', '.')
		for i in split_list: t = t.split(i)[0]
		t = cleantitle.get(t)
		if all(cleantitle.get(i) != t for i in title_list): return False, 0, 0

# remove single episodes ONLY (returned in single ep scrape), keep episode ranges as season packs
		for pattern in RE_SEASON_SINGLE_EPISODE:
			if pattern.search(release_title): return False, 0, 0

# return and identify episode ranges
		for pattern in RE_SEASON_EPISODE_RANGES:
			match = pattern.search(release_title)
			if not match: continue
			episode_start = int(match.group(1))
			episode_end = int(match.group(2))
			return True, episode_start, episode_end

# remove season ranges - returned in showPack scrape, plus non conforming season and specific crap
		rt = release_title.replace('-', '.')
		if any(i in rt for i in string_list):
			if season not in SEASON_CACHE:
				SEASON_CACHE[season] = [re.compile(i, re.I) for i in (
				r'%s[.-]s([2-9]{1}|[1-3]{1}[0-9]{1})(?:[.-]|$)' % season_check.rstrip('.'), # ex. ".s1-s9.", .s1-s39.
				r'%s[.-]s\d{2}(?:[.-]|$)' % season_fill_check.rstrip('.'), # ".s01-s09.", .s01-s39.
				r'%s[.-]\d{2}(?:[.-]|$)' % season_fill_check.rstrip('.'), # ".s01.09."
				r'\Ws\d{2}\W%s' % season_fill_check.lstrip('.'), # may need more reverse ranges
				r'%s[.-]to[.-]([2-9]{1}|[1-3]{1}[0-9]{1})(?:[.-]|$)' % season_full_check.rstrip('.'), # ".season.1.to.9.", ".season.1.to.39"
				r'%s[.-]season[.-]([2-9]{1}|[1-3]{1}[0-9]{1})(?:[.-]|$)' % season_full_check.rstrip('.'), # ".season.1.season.9.", ".season.1.season.39"
				r'%s[.-]([2-9]{1}|[1-3]{1}[0-9]{1})(?:[.-]|$)' % season_full_check.rstrip('.'), # "season.1.9.", "season.1.39.
				r'%s[.-]\d{1}[.-]\d{1,2}(?:[.-]|$)' % season_full_check.rstrip('.'), # "season.1.9.09."
				r'%s[.-]\d{3}[.-](?:19|20)[0-9]{2}(?:[.-]|$)' % season_full_check.rstrip('.'), # single season followed by 3 digit followed by 4 digit year ex."season.1.004.1971"
				r'%s[.-]\d{3}[.-]\d{3}(?:[.-]|$)' % season_full_fill_check.rstrip('.'), # 2 digit season followed by 3 digit dash range ex."season.10.001-025."
				r'%s[.-]season[.-]\d{2}(?:[.-]|$)' % season_full_fill_check.rstrip('.') # 2 digit season followed by 2 digit season range ex."season.01-season.09."
				)]
			for pattern in SEASON_CACHE[season]:
				if pattern.search(release_title): return False, 0, 0
			return True, 0, 0

		return False, 0, 0
	except:
		log_utils_error()

RE_SHOW_SINGLE_EPISODE = [re.compile(i, re.I) for i in (
	r's\d{1,3}e\d{1,3}',
	r's[0-3]{1}[0-9]{1}[.-]e\d{1,2}',
	r's\d{1,3}[.-]\d{1,3}e\d{1,3}',
	r'season[.-]?\d{1,3}[.-]?ep[.-]?\d{1,3}',
	r'season[.-]?\d{1,3}[.-]?episode[.-]?\d{1,3}'
)]

RE_SHOW_SEASON_RANGES = [
	re.compile(r'(?:season|seasons|s)[.-]?(?:0?[2-9]{1}|[1-3]{1}[0-9]{1})(?:[.-]?to[.-]?|[.-]?thru[.-]?|[.-])(?:season|seasons|s|)[.-]?(?:0?[3-9]{1}(?!\d{2}p)|[1-3]{1}[0-9]{1}(?!\d{2}p))', re.I)
]

RE_SHOW_SINGLE_SEASONS = [re.compile(i, re.I) for i in (
	r'season[.-]?([1-9]{1})[.-]0{1}\1[.-]?complete', # "season.1.01.complete" when 2nd number matches the fiirst group with leading 0
	r'season[.-]?([2-9]{1})[.-](?:[0-9]+)[.-]?complete', # "season.9.10.complete" when first number is >1 followed by 2 digit number
	r'season[.-]?\d{1,2}[.-]s\d{1,2}', # season.02.s02
	r'season[.-]?\d{1,2}[.-]complete', # season.02.complete
	r'season[.-]?\d{1,2}[.-]\d{3,4}p{0,1}', # "season.02.1080p" and no seperator "season02.1080p"
	r'season[.-]?\d{1,2}[.-](?!thru|to|\d{1,2}[.-])', # "season.02." or "season.1" not followed by "to", "thru", or another single or 2 digit number then a dot(which would be a range)
	r'season[.-]?\d{1,2}[.]?$', # end of line ex."season.1", "season.01", "season01" can also have trailing dot or end of line(dash would be a range)
	r'season[.-]?\d{1,2}[.-](?:19|20)[0-9]{2}', # single season followed by 4 digit year ex."season.1.1971", "season.01.1971", or "season01.1971"
	r'season[.-]?\d{1,2}[.-]\d{3}[.-]{1,2}(?:19|20)[0-9]{2}', # single season followed by 3 digits then 4 digit year ex."season.1.004.1971" or "season.01.004.1971" (comic book format)
	r'(?<!thru)(?<!to)(?<!\d{2})[.-]s\d{2}[.-]complete', # ".s01.complete" not preceded by "thru", "to", or 2 digit number
	r'(?<!thru)(?<!to)(?<!s\d{2})[.-]s\d{2}(?![.-]thru)(?![.-]to)(?![.-]s\d{2})(?![.-]\d{2}[.-])' # .s02. not preceded by "thru", "to", or "s01". Not followed by ".thru", ".to", ".s02", "-s02", ".02.", or "-02."
)]

RE_SHOW_SPELLED_SEASONS = [re.compile(k % x, re.I) for k, v in (
	(r'complete[.-]%s[.-]season', season_ordinal_list),
	(r'complete[.-]%s[.-]season', season_ordinal2_list),
	(r'season[.-]%s', season_list)
) for x in v]

def filter_show_pack(show_title, aliases, imdb, year, season, release_title, total_seasons):
#	aliases = aliases_to_array(aliases)
	title_list = []
	title_list_append = title_list.append
	if aliases:
		for item in aliases:
			try:
				alias = item.replace('!', '').replace('(', '').replace(')', '').replace('&', 'and').replace(year, '')
				if alias in title_list: continue
				title_list_append(alias)
			except:
				log_utils_error()
	try:
		show_title = show_title.replace('!', '').replace('(', '').replace(')', '').replace('&', 'and')
		if show_title not in title_list: title_list_append(show_title)

		split_list = ('.all.seasons', 'seasons', 'season', 'the.complete', 'complete', 'all.torrent', 'total.series', 'tv.series', 'series', 'edited', 's1', 's01', year)#s1 or s01 used so show pack only kept that begin with 1
		release_title = release_title_format(release_title)
		t = release_title.replace('-', '.')

		for i in split_list: t = t.split(i)[0]
		t = cleantitle.get(t)
		if all(cleantitle.get(i) != t for i in title_list): return False, 0

# remove single episodes(returned in single ep scrape)
		for pattern in RE_SHOW_SINGLE_EPISODE:
			if pattern.search(release_title):
				return False, 0

# remove season ranges that do not begin at 1
		for pattern in RE_SHOW_SEASON_RANGES:
			if pattern.search(release_title):
				return False, 0

# remove single seasons - returned in seasonPack scrape
		for pattern in RE_SHOW_SINGLE_SEASONS:
			if pattern.search(release_title):
				return False, 0

# remove spelled out single seasons
		for pattern in RE_SHOW_SPELLED_SEASONS:
			if pattern.search(release_title):
				return False, 0

# from here down we don't filter out, we set and pass "last_season" it covers for the range and addon can filter it so the db will have full valid showPacks.
		dot_release_title = release_title.replace('-', '.')

		# match sequential dot/dash/and ranges like "1.2.3.4" or "1.2.3.and.4"
		series_match = re.findall(r'\b\d+\b', dot_release_title)
		if series_match and series_match[0] == '1':
			try:
				seasons_found = [int(x) for x in series_match if x.isdigit()]
				if len(seasons_found) >= 2 and seasons_found[1] == 2:
					last_season = seasons_found[-1]
					if last_season <= int(total_seasons):
						return True, last_season
			except ValueError: pass

		# match standard range formats: "1.to.9", "01-09", "s1~s9", "s01.thru.s09", "s01.s09"
		range_match = re.search(r'\b(?:s|0)?1[.-]?(?:to|thru|and|~|-|\.)[.-]?(?:s|0)?(\d+)\b', dot_release_title)
		if range_match:
			last_season = int(range_match.group(1))
			if last_season <= int(total_seasons):
				return True, last_season

		return True, total_seasons
	except:
		log_utils_error()

def info_from_name(release_title, title, year, hdlr=None, episode_title=None, season=None, pack=None):
	try:
		release_title = release_title.lower().replace('&', 'and').replace("'", "")
		release_title = re.sub(r'[^a-z0-9]+', '.', release_title)
		title = title.lower().replace('&', 'and').replace("'", "")
		title = re.sub(r'[^a-z0-9]+', '.', title)
		name_info = release_title.replace(title, '').replace(year, '')
		if hdlr: name_info = name_info.replace(hdlr.lower(), '')
		if episode_title:
			episode_title = episode_title.lower().replace('&', 'and').replace("'", "")
			episode_title = re.sub(r'[^a-z0-9]+', '.', episode_title)
			name_info = name_info.replace(episode_title, '')
		if pack:
			if pack == 'season':
				season_fill = season.zfill(2)
				str1_replace = ('.s%s' % season, '.s%s' % season_fill, '.season.%s' % season, '.season%s' % season, '.season.%s' % season_fill, '.season%s' % season_fill, 'complete')
				for i in str1_replace: name_info = name_info.replace(i, '')
			elif pack == 'show':
				str2_replace = ('.all.seasons', 'seasons', 'season', 'the.complete', 'complete', 'all.torrent', 'total.series', 'tv.series', 'series', 'edited', 's1', 's01')
				for i in str2_replace: name_info = name_info.replace(i, '')
		name_info = name_info.lstrip('.').rstrip('.')
		name_info = '.%s.' % name_info
		return name_info
	except:
		log_utils_error()
		return release_title

def release_title_format(release_title):
	try:
		release_title = release_title.lower().replace("'", "").lstrip('.').rstrip('.')
		fmt = '.%s.' % re.sub(r'[^a-z0-9-~]+', '.', release_title).replace('.-.', '-').replace('-.', '-').replace('.-', '-').replace('--', '-')
		return fmt
	except:
		log_utils_error()
		return release_title

UNWANTED_REGEX_CACHE = {}
RE_BRACKETS_JP = re.compile(r'【.*?】', re.I)
RE_BRACKETS_SQ = re.compile(r'^\[.*?]', re.I)

def clean_name(release_title):
	try:
		release_title = RE_BRACKETS_JP.sub('', release_title)
		release_title = strip_non_ascii_and_unprintable(release_title).lstrip('+.-:/ ').replace(' ', '.')
		title_lower = release_title.lower()
		if title_lower.startswith('rifftrax'): return release_title # removed by "undesirables" anyway so exit
		for tag in unwanted_tags:
			if title_lower.startswith(tag):
				if tag not in UNWANTED_REGEX_CACHE:
					UNWANTED_REGEX_CACHE[tag] = re.compile(r'^%s' % tag.replace('+', '\\+'), re.I)
				release_title = UNWANTED_REGEX_CACHE[tag].sub('', release_title, 1)
				break
		release_title = release_title.lstrip('+.-:/ ')
		release_title = RE_BRACKETS_SQ.sub('', release_title, 1).lstrip('.-[](){}:/')
		return release_title
	except:
		log_utils_error()
		return release_title

def strip_non_ascii_and_unprintable(text):
	try:
		ascii_chars = (
			c for c in unicodedata.normalize('NFKD', text)
			if ord(c) < 128
			and c in printable
			and not unicodedata.combining(c)
		)
		text = ''.join(ascii_chars)
		return text
	except:
		log_utils_error()
		return text

def _size(siz):
	try:
		if siz in ('0', 0, '', None): return 0, ''
		div = 1 if siz.lower().endswith(('gb', 'gib')) else 1024
		# if ',' in siz and siz.lower().endswith(('mb', 'mib')): siz = size.replace(',', '')
		# elif ',' in siz and siz.lower().endswith(('gb', 'gib')): siz = size.replace(',', '.')
		dec_count = len(re.findall(r'[.]', siz))
		if dec_count == 2: siz = siz.replace('.', ',', 1) # torrentproject2 likes to randomly use 2 decimals vs. a comma then a decimal
		float_size = round(float(re.sub(r'[^0-9|/.|/,]', '', siz.replace(',', ''))) / div, 2) #comma issue where 2,750 MB or 2,75 GB (sometimes replace with "." and sometimes not)
		str_size = '%.2f GB' % float_size
		return float_size, str_size
	except:
		log_utils_error('failed on siz=%s' % siz)
		return 0, ''

POWERS = {
	'YB': 1208925819614629174706176,
	'ZB': 1180591620717411303424,
	'EB': 1152921504606846976,
	'TB': 1099511627776,
	'GB': 1073741824,
	'MB': 1048576,
	'KB': 1024,
	'B': 1
}

def convert_size(size_bytes, to='GB'):
	try:
		if size_bytes == 0: return 0, ''
		p = POWERS[to]
		float_size = round(size_bytes / p, 2)
		# if to == 'B' or to  == 'KB': return 0, ''
		str_size = '%s %s' % (float_size, to)
		return float_size, str_size
	except:
		log_utils_error()
		return 0, ''

def base32_to_hex(hash, caller):
	from base64 import b32decode
	hex = b32decode(hash).hex()
	log_utils.log('%s: base32 hash  "%s"  converted to hex 40  "%s" ' % (caller, hash, hex), __name__, log_utils.LOGDEBUG)
	return hex

def scraper_error(provider):
	import traceback
	failure = traceback.format_exc()
	log_utils.log(provider.upper() + ' - Exception: \n' + str(failure), caller='scraper_error', level=log_utils.LOGERROR)

def is_host_valid(url, domains):
	try:
		if any(x in url.lower() for x in ('.rar.', '.zip.', '.part.', '.sample.')) or any(url.lower().endswith(x) for x in ('.bmp', '.gif', '.jpg', '.nfo', '.part', '.png', '.rar', '.sample.', '.srt', '.txt', '.zip')):
			return False, ''
		host = __top_domain(url)
		hosts = [domain.lower() for domain in domains if host and host in domain.lower()]
		if hosts and '.' not in host: host = hosts[0]
		if hosts and any([h for h in ('google', 'picasa', 'blogspot') if h in host]): host = 'gvideo'
		if hosts and any([h for h in ('akamaized', 'ocloud') if h in host]): host = 'CDN'
		return any(hosts), host
	except:
		log_utils_error()
		return False, ''

def __top_domain(url):
	from urllib.parse import urlparse
	try:
		elements = urlparse(url)
		domain = elements.netloc or elements.path
		domain = domain.split('@')[-1].split(':')[0]
		regex = r"(?:www\.)?([\w\-]*\.[\w\-]{2,3}(?:\.[\w\-]{2,3})?)$"
		res = re.search(regex, domain)
		if res: domain = res.group(1)
		domain = domain.lower()
		return domain
	except:
		log_utils_error()

def copy2clip(txt):
	from sys import platform as sys_platform
	platform = sys_platform
	if platform == "win32":
		try:
			from subprocess import check_call
			# cmd = "echo " + txt.strip() + "|clip"
			cmd = "echo " + txt.replace('&', '^&').strip() + "|clip" # "&" is a command seperator
			return check_call(cmd, shell=True)
		except:
			log_utils_error('Windows: Failure to copy to clipboard')
	elif platform == "darwin":
		try:
			from subprocess import check_call
			cmd = "echo " + txt.strip() + "|pbcopy"
			return check_call(cmd, shell=True)
		except:
			log_utils_error('Mac: Failure to copy to clipboard')
	elif platform == "linux":
		try:
			from subprocess import Popen, PIPE
			p = Popen(["xsel", "-pi"], stdin=PIPE)
			p.communicate(input=txt)
		except:
			log_utils_error('Linux: Failure to copy to clipboard')

