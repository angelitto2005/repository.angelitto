import re
import json
import unicodedata
from html import unescape
from string import printable
from urllib.parse import unquote, unquote_plus
from indexers.metadata import season_episodes_meta
from modules import kodi_utils
from modules.settings import date_offset, metadata_user_info
from modules.utils import adjust_premiered_date, get_datetime, jsondate_to_datetime, subtract_dates
# from modules.kodi_utils import logger

string = str

RESOLUTIONS = {
	'4K': r'(?:\b|_)(4k|hd4k|4khd|uhd|ultrahd|ultra\.hd|hd2160|2160hd|2160|2160p|216o|216op)(?:\b|_)',
	'1080p': r'(?:\b|_)(1080|1080p|1080i|hd1080|1080hd|hd1080p|m1080p|fullhd|full\.hd|1o8o|1o8op|108o|108op|1o80|1o80p)(?:\b|_)',
	'720p': r'(?:\b|_)(720|720p|720i|hd720|720hd|hd720p|72o|72op)(?:\b|_)',
	'CAM': r'(?:\b|_)(cam|camrip|hdcam|hd\.cam|cam\.rip|dvdcam)(?:\b|_)',
	'SCR': r'(?:\b|_)(scr|screener|dvdscr|dvd\.scr|r5|r6)(?:\b|_)',
	'TELE': r'(?:\b|_)(tc|tsrip|hdts|hdtc|hd\.tc|dvdts|telesync|ts)(?:\b|_)'
}

PATTERNS = {
	'VIDEO_3D': ('[B]3D[/B]', r'(?:\b|_)(3d|sbs|hsbs|sidebyside|side\.by\.side|stereoscopic|tab|htab|topandbottom|top\.and\.bottom)(?:\b|_)'),
	'SDR': ('SDR', r'\.sdr(?:\b|_)'),
	'DOLBY_VISION': ('[B]D/VISION[/B]', r'(?:\b|_)(dolby\.vision|dolbyvision|\.dovi\.|\.dv\.)(?:\b|_)'),
	'HDR': ('[B]HDR[/B]', r'(?:\b|_)(2160p\.uhd\.bluray|2160p\.uhd\.blu\.ray|2160p\.bluray\.hevc\.truehd|2160p\.blu\.ray\.hevc\.truehd|2160p\.bluray\.hevc\.dts\.hd\.ma|2160p\.blu\.ray\.hevc\.dts\.hd\.ma|\.hdr\.|hdr10|hdr\.10|uhd\.bluray\.2160p|uhd\.blu\.ray\.2160p)(?:\b|_)'),
	'HDR_TRUE': ('[B]HDR[/B]', r'(?:\b|_)(?:\.hdr\.|hdr10|hdr\.10)(?:\b|_)'),

	'CODEC_H264': ('AVC', r'(?:\b|_)(avc|h264|h\.264|x264|x\.264)(?:\b|_)'),
	'CODEC_AV1': ('[B]AV1[/B]', r'\.av1\.'),
	'CODEC_H265': ('[B]HEVC[/B]', r'(?:\b|_)(h265|h\.265|hevc|x265|x\.265)(?:\b|_)'),
	'CODEC_XVID': ('XVID', r'(?:\b|_)(xvid|\.x\.vid)(?:\b|_)'),
	'CODEC_DIVX': ('DIVX', r'(?:\b|_)(divx|div2|div3|div4)(?:\b|_)'),

	'REMUX': ('REMUX', r'(?:\b|_)(remux|bdremux)(?:\b|_)'),
	'BLURAY': ('BLURAY', r'(?:\b|_)(bluray|blu\.ray|bdrip|bd\.rip)(?:\b|_)'),
	'DVD': ('DVD', r'(?:\b|_)(dvdrip|dvd\.rip)(?:\b|_)'),
	'WEB': ('WEB', r'(?:\b|_)(?:\.web\.|webdl|web\.dl|web-dl|webrip|web\.rip)(?:\b|_)'),
	'HDTV': ('HDTV', r'(?:\b|_)hdtv(?:\b|_)'),
	'PDTV': ('PDTV', r'(?:\b|_)pdtv(?:\b|_)'),
	'HDRIP': ('HDRIP', r'(?:\b|_)(?:\.hdrip|\.hd\.rip)(?:\b|_)'),

	'ATMOS': ('ATMOS', r'(?:\b|_)atmos(?:\b|_)'),
	'DOLBY_TRUEHD': ('TRUEHD', r'(?:\b|_)(true\.hd|truehd)(?:\b|_)'),
	'DOLBY_DIGITALPLUS': ('DD+', r'(?:\b|_)(dolby\.digital\.plus|dolbydigital\.plus|dolbydigitalplus|dd\.plus\.|ddplus|\.ddp\.|ddp2|ddp5|ddp7|eac3|\.e\.ac3)(?:\b|_)'),
	'DOLBY_DIGITALEX': ('DD-EX', r'(?:\b|_)(?:\.dd\.ex\.|ddex|dolby\.ex\.|dolby\.digital\.ex\.|dolbydigital\.ex\.)(?:\b|_)'),
	'DOLBYDIGITAL': ('DD', r'(?:\b|_)(dd2\.|dd5|dd7|dolby\.digital|dolbydigital|\.ac3|\.ac\.3\.|\.dd\.)(?:\b|_)'),

	'AAC': ('AAC', r'(?:\b|_)aac(?:\b|_)'),
	'MP3': ('MP3', r'(?:\b|_)mp3(?:\b|_)'),
	'DTSX': ('DTS-X', r'(?:\b|_)(dts\.x\.|dtsx)(?:\b|_)'),
	'DTS_HDMA': ('DTS-HD MA', r'(?:\b|_)(hd\.ma|hdma)(?:\b|_)'),
	'DTS_HD': ('DTS-HD', r'(?:\b|_)(dts\.hd\.|dtshd)(?:\b|_)'),
	'DTS_PLAIN': ('DTS', r'\.dts(?:\b|_)'),

	'AUDIO_8CH': ('8CH', r'(?:\b|_)(ch8\.|8ch\.|7\.1ch|7\.1\.)(?:\b|_)'),
	'AUDIO_7CH': ('7CH', r'(?:\b|_)(ch7\.|7ch\.|6\.1ch|6\.1\.)(?:\b|_)'),
	'AUDIO_6CH': ('6CH', r'(?:\b|_)(ch6\.|6ch\.|5\.1ch|5\.1\.)(?:\b|_)'),
	'AUDIO_2CH': ('2CH', r'(?:\b|_)(ch2|2ch|2\.0ch|2\.0\.|audio\.2\.0\.|stereo)(?:\b|_)'),

	'WMV': ('WMV', r'\.wmv(?:\b|_)'),
	'CODEC_MPEG': ('MPEG', r'(?:\b|_)(?:\.mpg|\.mp2|\.mpeg|\.mpe|\.mpv|\.mp4|\.m4p|\.m4v|msmpeg|mpegurl)(?:\b|_)'),
	'AVI': ('AVI', r'\.avi(?:\b|_)'),
	'CODEC_MKV': ('MKV', r'(?:\b|_)(?:\.mkv|matroska)(?:\b|_)'),

	'MULTI_LANG': ('MULTI-LANG', r'(?:\b|_)(hindi\.eng|ara\.eng|ces\.eng|chi\.eng|cze\.eng|dan\.eng|dut\.eng|ell\.eng|esl\.eng|esp\.eng|fin\.eng|fra\.eng|fre\.eng|frn\.eng|gai\.eng|ger\.eng|gle\.eng|gre\.eng|gtm\.eng|heb\.eng|hin\.eng|hun\.eng|ind\.eng|iri\.eng|ita\.eng|jap\.eng|jpn\.eng|kor\.eng|lat\.eng|lebb\.eng|lit\.eng|nor\.eng|pol\.eng|por\.eng|rus\.eng|som\.eng|spa\.eng|sve\.eng|swe\.eng|tha\.eng|tur\.eng|uae\.eng|ukr\.eng|vie\.eng|zho\.eng|dual\.audio|multi)(?:\b|_)'),
	'ADS': ('ADS', r'(?:\b|_)(1xbet|betwin)(?:\b|_)'),
	'SUBS': ('SUBS', r'(?:\b|_)(subita|subfrench|subspanish|subtitula|swesub|nl\.subs)(?:\b|_)')
}

def pack_enable_check(meta, season, episode):
	try:
		extra_info = meta['extra_info']
		status = extra_info['status']
		if status in ('Ended', 'Canceled'): return True, True
		adjust_hours = date_offset()
		current_date = get_datetime()
		meta_user_info = metadata_user_info()
		episodes_data = season_episodes_meta(season, meta, meta_user_info)
		unaired_episodes = [adjust_premiered_date(i['premiered'], adjust_hours)[0] for i in episodes_data]
		if None in unaired_episodes or any(i > current_date for i in unaired_episodes): return False, False
		else: return True, False
	except: pass
	return False, False

def get_cache_expiry(mediatype, meta, season):
	try:
		current_date = get_datetime()
		if mediatype == 'movie':
			premiered = jsondate_to_datetime(meta['premiered']).date()
			difference = subtract_dates(current_date, premiered)
			if difference == 0: single_expiry = 3
			elif difference <= 90: single_expiry = 8
			else: single_expiry = 4
			season_expiry, show_expiry = 0, 0
		else:
			extra_info = meta['extra_info']
			ended = extra_info['status'] in ('Ended', 'Canceled')
			episode_date, premiered = adjust_premiered_date(meta['premiered'], date_offset())
			difference = subtract_dates(current_date, episode_date)
			last_episode_to_air = jsondate_to_datetime(extra_info['last_episode_to_air']['air_date']).date()
			last_ep_difference = subtract_dates(current_date, last_episode_to_air)
			recently_ended = True if ended and last_ep_difference <= 14 else False
			if not ended or recently_ended:
				if difference == 0: single_expiry = 3
				elif difference <= 3: single_expiry = 24
				elif difference <= 7: single_expiry = 72
				else: single_expiry = 168
				if meta['total_seasons'] == season:
					if last_ep_difference <= 7: season_expiry = 72
					else: season_expiry = 240
				else: season_expiry = 720
				show_expiry = 240
			else: single_expiry, season_expiry, show_expiry = 240, 720, 720
	except: single_expiry, season_expiry, show_expiry = 72, 72, 240
	return single_expiry, season_expiry, show_expiry

def sources_quality_count(sources):
	result = {'4K': 0, '1080p': 0, '720p': 0, 'SD': 0, 'total': len(sources)}
	quality_map = {'4K': '4K', '1440p': '1080p', '1080p': '1080p', '720p': '720p', 'HD': '720p'}
	for i in sources: result[quality_map.get(i.get('quality', 'SD'), 'SD')] += 1
	return result

def get_aliases_titles(aliases):
	try: result = [i['title'] for i in aliases]
	except: result = []
	return result

def internal_results(provider, sources):
	quality_count = sources_quality_count(sources)
	kodi_utils.set_property('%s.internal_results' % provider, json.dumps(quality_count))

def supported_video_extensions():
	supported_video_extensions = kodi_utils.supported_media().split('|')
	return [i for i in supported_video_extensions if i not in ('','.iso','.zip')]

def extras_filter():
	return ('trailer', 'sample', 'extra', 'extras', 'blooper', 'bloopers', 'deleted', 'inside',
			'unused', 'footage', 'feature', 'featurette', 'making.of', 'behind.the.scenes')

SEAS_EP_REGEX = re.compile('|'.join((
	r's(?:eason)? \s* (\d+) [xX\s._-]* e(?:p(?:isode)?)? [\s._-]* (\d+) (?: [\s._-]* e? (?:p(?:isode)?)? \s* (\d+) )?',
	r'(\d+) \s* [xX] \s* (\d+) (?: [\s._-]* (?:[xX]|-)? \s* (\d+) )?',
	r'\b (?: ep(?:isode)? | [._-]e ) [\s._-]* (\d+)'
)), flags=re.I | re.X)

def seas_ep_filter(season, episode, release_title, split=False, return_match=False):
	cleaned_title = clean_title(release_title)

	match = SEAS_EP_REGEX.search(cleaned_title)
	if not match:
		return '' if (split or return_match) else False

	season, episode = int(season), int(episode)
	file_season, file_episode_start, file_episode_end = None, None, None
	g = match.groups()

	if   g[0] is not None:
		file_season = int(g[0])
		file_episode_start = int(g[1])
#		if g[2] is not None: file_episode_end = int(g[2])
	elif g[3] is not None:
		file_season = int(g[3])
		file_episode_start = int(g[4])
#		if g[5] is not None: file_episode_end = int(g[5])
	elif g[6] is not None:
		file_episode_start = int(g[6])

	if file_season is not None and file_season != season:
		return '' if (split or return_match) else False

	if file_episode_end is not None:
		ep_matches = file_episode_start <= episode <= file_episode_end
	else: ep_matches = file_episode_start == episode

	if not ep_matches:
		return '' if (split or return_match) else False

	if split: return cleaned_title.split(match.group(), 1)[1]
	if return_match: return match.group()
	return True

def find_season_in_release_title(release_title):
	release_title = re.sub(r'[^a-z0-9-]+', '.', unquote(release_title).lower().replace("'", ""))
	match = re.search(r'(?:\b(?:s|season)\.?(\d+)|(\d+)\.?x\b)', release_title)
	if not match: return None
	season_str = match.group(1) or match.group(2)
	return int(season_str)

def url_strip(url):
	try:
		url = unquote_plus(url)
		if 'magnet:' in url: url = url.split('&dn=')[1]
		else: url = url.split('/')[-1]
		fmt = clean_title(url)
		return fmt
	except: return None

COMPILED_RESOLUTIONS = {
	k: re.compile(v, re.I) for k, v in RESOLUTIONS.items()
}

def get_release_quality(release_info):
	for quality, pattern in COMPILED_RESOLUTIONS.items():
		if pattern.search(release_info): return quality
	return 'SD'

COMPILED_PATTERNS = {
	key: (tag, re.compile(raw_regex, re.I))
	for key, (tag, raw_regex) in PATTERNS.items()
}

def get_file_info(name_info=None, url=None):
	fmt = name_info or (url_strip(url) if url else None)
	if not fmt: return 'SD', ''

	quality = get_release_quality(fmt)
	info = []
	info_append = info.append

	def match(pattern_key):
		return bool(COMPILED_PATTERNS[pattern_key][1].search(fmt))

	def get_tag(pattern_key):
		return COMPILED_PATTERNS[pattern_key][0]

	if match('VIDEO_3D'): info_append(get_tag('VIDEO_3D'))

	if match('SDR'):
		info_append(get_tag('SDR'))
	elif match('DOLBY_VISION'):
		info_append(get_tag('DOLBY_VISION'))
		if match('HDR_TRUE'):
			info_append(get_tag('HDR_TRUE'))
			info_append('[B]HYBRID[/B]')
	elif match('HDR') or (('2160p' in fmt) and match('REMUX')):
		info_append('[B]HDR[/B]')

	if match('CODEC_H264'):        info_append(get_tag('CODEC_H264'))
	elif match('CODEC_AV1'):       info_append(get_tag('CODEC_AV1'))
	elif match('CODEC_H265'):      info_append(get_tag('CODEC_H265'))
	elif '[B]HDR[/B]' in info or '[B]D/VISION[/B]' in info:
		info_append('[B]HEVC[/B]')
	elif match('CODEC_XVID'):      info_append(get_tag('CODEC_XVID'))
	elif match('CODEC_DIVX'):      info_append(get_tag('CODEC_DIVX'))

	if match('REMUX'):             info_append(get_tag('REMUX'))

	if match('BLURAY'):            info_append(get_tag('BLURAY'))
	elif match('DVD'):             info_append(get_tag('DVD'))
	elif match('WEB'):             info_append(get_tag('WEB'))
	elif 'hdtv' in fmt:            info_append('HDTV')
	elif 'pdtv' in fmt:            info_append('PDTV')
	elif match('HDRIP'):           info_append(get_tag('HDRIP'))

	if 'atmos' in fmt:             info_append('ATMOS')
	if match('DOLBY_TRUEHD'):      info_append(get_tag('DOLBY_TRUEHD'))

	if match('DOLBY_DIGITALPLUS'): info_append(get_tag('DOLBY_DIGITALPLUS'))
	elif match('DOLBY_DIGITALEX'): info_append(get_tag('DOLBY_DIGITALEX'))
	elif match('DOLBYDIGITAL'):    info_append(get_tag('DOLBYDIGITAL'))

	if 'aac' in fmt:               info_append('AAC')
	elif 'mp3' in fmt:             info_append('MP3')

	if match('DTSX'):              info_append(get_tag('DTSX'))
	elif match('DTS_HDMA'):        info_append(get_tag('DTS_HDMA'))
	elif match('DTS_HD'):          info_append(get_tag('DTS_HD'))
	elif match('DTS_PLAIN'):       info_append(get_tag('DTS_PLAIN'))

	if match('AUDIO_8CH'):         info_append(get_tag('AUDIO_8CH'))
	elif match('AUDIO_7CH'):       info_append(get_tag('AUDIO_7CH'))
	elif match('AUDIO_6CH'):       info_append(get_tag('AUDIO_6CH'))
	elif match('AUDIO_2CH'):       info_append(get_tag('AUDIO_2CH'))

	if match('WMV'):               info_append(get_tag('WMV'))
	elif match('CODEC_MPEG'):      info_append(get_tag('CODEC_MPEG'))
	elif match('AVI'):             info_append(get_tag('AVI'))
	elif match('CODEC_MKV'):       info_append(get_tag('CODEC_MKV'))

	if match('MULTI_LANG'):        info_append(get_tag('MULTI_LANG'))
	if match('ADS'):               info_append(get_tag('ADS'))
	if match('SUBS'):              info_append(get_tag('SUBS'))

	return quality, ' | '.join(info)

def check_title(title, release_title, aliases=None, year=''):
	try:
		if isinstance(aliases, list): all_titles = [title, *aliases]
		else: all_titles = [title]
		all_titles = (re.escape(clean_title(i)) for i in all_titles)
		pattern = re.compile(r'\b(?:%s)\b' % '|'.join(all_titles), re.I)
		return bool(pattern.search(clean_title(release_title)))
	except: pass

def clean_title(title):
	try:
		text = title.replace('&', 'and')
		text = unescape(text)
		text = unquote(text)
		text = strip_non_ascii_and_unprintable(text)
		text = re.sub(r'(?i)[^a-z0-9.]', '.', text)
		text = re.sub(r'\.+', '.', text)
		title = text.strip('.').lower()
	except: pass
	return title

def clean_file_name(filename, period_to_space=True):
	try:
		text = unescape(filename)
		text = unquote(text)
		text = strip_non_ascii_and_unprintable(text)
		if period_to_space:
			text = re.sub(r'(?i)[^a-z0-9 ]', ' ', text)
		else: text = re.sub(r'[\\/:*"?%|<>]', '', text)
		text = re.sub(r'\s+', ' ', text)
		filename = text.strip()
	except: pass
	return filename

def strip_non_ascii_and_unprintable(text):
	try:
		ascii_chars = (
			c for c in unicodedata.normalize('NFKD', text)
			if ord(c) < 128
			and c in printable
			and not unicodedata.combining(c)
		)
		text = ''.join(ascii_chars)
	except: pass
	return text

