import re
import json
import unicodedata
from string import printable
from urllib.parse import unquote, unquote_plus
from fenom.control import setting as fenom_getSetting, setSetting as fenom_setSetting
from indexers.metadata import season_episodes_meta
from modules import kodi_utils
from modules.settings import check_prescrape_sources, date_offset, metadata_user_info
from modules.utils import manual_function_import, adjust_premiered_date, get_datetime, jsondate_to_datetime, subtract_dates
# from modules.kodi_utils import logger

string = str
RES_4K = ('.4k', 'hd4k', '4khd', '.uhd', 'ultrahd', 'ultra.hd', 'hd2160', '2160hd', '2160', '2160p', '216o', '216op')
RES_1080 = ('1080', '1080p', '1080i', 'hd1080', '1080hd', 'hd1080p', 'm1080p', 'fullhd', 'full.hd', '1o8o', '1o8op', '108o', '108op', '1o80', '1o80p')
RES_720 = ('720', '720p', '720i', 'hd720', '720hd', 'hd720p', '72o', '72op')
CAM = ('.cam.', 'camrip', 'hdcam', '.hd.cam', 'cam.rip', 'dvdcam')
SCR = ('.scr.', 'screener', 'dvdscr', 'dvd.scr', '.r5', '.r6')
TELE = ('.tc.', 'tsrip', 'hdts', 'hdtc', '.hd.tc', 'dvdts', 'telesync', '.ts.')
VIDEO_3D = ('.3d.', '.sbs.', '.hsbs', 'sidebyside', 'side.by.side', 'stereoscopic', '.tab.', '.htab.', 'topandbottom', 'top.and.bottom')
DOLBY_VISION = ('dolby.vision', 'dolbyvision', '.dovi.', '.dv.')
HDR = ('2160p.uhd.bluray', '2160p.uhd.blu.ray', '2160p.bluray.hevc.truehd', '2160p.blu.ray.hevc.truehd', '2160p.bluray.hevc.dts.hd.ma', '2160p.blu.ray.hevc.dts.hd.ma',
		'.hdr.', 'hdr10', 'hdr.10', 'uhd.bluray.2160p', 'uhd.blu.ray.2160p')
HDR_TRUE = ('.hdr.', 'hdr10', 'hdr.10')
CODEC_H264 = ('avc', 'h264', 'h.264', 'x264', 'x.264')
CODEC_H265 = ('h265', 'h.265', 'hevc', 'x265', 'x.265')
CODEC_XVID = ('xvid', '.x.vid')
CODEC_DIVX = ('divx', 'div2', 'div3', 'div4')
CODEC_MPEG = ('.mpg', '.mp2', '.mpeg', '.mpe', '.mpv', '.mp4', '.m4p', '.m4v', 'msmpeg', 'mpegurl')
CODEC_MKV = ('.mkv', 'matroska')
REMUX = ('remux', 'bdremux')
BLURAY = ('bluray', 'blu.ray', 'bdrip', 'bd.rip')
DVD = ('dvdrip', 'dvd.rip')
WEB = ('.web.', 'webdl', 'web.dl', 'web-dl', 'webrip', 'web.rip')
HDRIP = ('.hdrip', '.hd.rip')
DOLBY_TRUEHD = ('true.hd', 'truehd')
DOLBY_DIGITALPLUS = ('dolby.digital.plus', 'dolbydigital.plus', 'dolbydigitalplus', 'dd.plus.', 'ddplus', '.ddp.', 'ddp2', 'ddp5', 'ddp7', 'eac3', '.e.ac3')
DOLBY_DIGITALEX = ('.dd.ex.', 'ddex', 'dolby.ex.', 'dolby.digital.ex.', 'dolbydigital.ex.')
DOLBYDIGITAL = ('dd2.', 'dd5', 'dd7', 'dolby.digital', 'dolbydigital', '.ac3', '.ac.3.', '.dd.')
DTSX = ('dts.x.', 'dtsx')
DTS_HDMA = ('hd.ma', 'hdma')
DTS_HD = ('dts.hd.', 'dtshd')
AUDIO_8CH = ('ch8.', '8ch.', '7.1ch', '7.1.')
AUDIO_7CH = ('ch7.', '7ch.', '6.1ch', '6.1.')
AUDIO_6CH = ('ch6.', '6ch.', '5.1ch', '5.1.')
AUDIO_2CH = ('ch2', '2ch', '2.0ch', '2.0.', 'audio.2.0.', 'stereo')
MULTI_LANG = ('hindi.eng', 'ara.eng', 'ces.eng', 'chi.eng', 'cze.eng', 'dan.eng', 'dut.eng', 'ell.eng', 'esl.eng', 'esp.eng', 'fin.eng', 'fra.eng', 'fre.eng',
			'frn.eng', 'gai.eng', 'ger.eng', 'gle.eng', 'gre.eng', 'gtm.eng', 'heb.eng', 'hin.eng', 'hun.eng', 'ind.eng', 'iri.eng', 'ita.eng', 'jap.eng', 'jpn.eng',
			'kor.eng', 'lat.eng', 'lebb.eng', 'lit.eng', 'nor.eng', 'pol.eng', 'por.eng', 'rus.eng', 'som.eng', 'spa.eng', 'sve.eng', 'swe.eng', 'tha.eng', 'tur.eng',
			'uae.eng', 'ukr.eng', 'vie.eng', 'zho.eng', 'dual.audio', 'multi')
SUBS = ('subita', 'subfrench', 'subspanish', 'subtitula', 'swesub', 'nl.subs')
ADS = ('1xbet', 'betwin')
try: UNWANTED_TAGS = json.loads(kodi_utils.get_property('pov_unwanted'))['unwanted']
except: UNWANTED_TAGS = []

def internal_sources(active_sources, mediatype, prescrape=False):
	source_list = []
	append = source_list.append
	files = kodi_utils.list_dirs('special://home/addons/plugin.video.pov/resources/lib/scrapers')[1]
	for item in files:
		try:
			module_name = item.split('.')[0]
			if module_name in ('__init__',): continue
			if module_name not in active_sources: continue
			if prescrape and not check_prescrape_sources(module_name, mediatype): continue
			module = manual_function_import('scrapers.%s' % module_name, 'source')
			append(('internal', module, module_name))
		except: pass
	return source_list

def get_aliases_titles(aliases):
	try: result = [i['title'] for i in aliases]
	except: result = []
	return result

def internal_results(provider, sources):
	quality_count = sources_quality_count(sources)
	kodi_utils.set_property('%s.internal_results' % provider, json.dumps(quality_count))

def sources_quality_count(sources):
	sourcesTotal = sources4K = sources1080p = sources720p = sourcesSD = 0
	for i in sources:
		quality = i['quality']
		if quality == '4K': sources4K += 1
		elif quality in ('1440p', '1080p'): sources1080p += 1
		elif quality in ('720p', 'HD'): sources720p += 1
		else: sourcesSD += 1
		sourcesTotal += 1
	return {'4K': sources4K, '1080p': sources1080p, '720p': sources720p, 'SD': sourcesSD, 'total': sourcesTotal}

def normalize(title):
	try:
		title = ''.join(c for c in unicodedata.normalize('NFKD', title) if unicodedata.category(c) != 'Mn')
		return string(title)
	except: return title

def enable_disable(folder):
	try:
		icon = 'special://home/addons/plugin.video.pov/resources/lib/fenom/fenom_icon.png'
		enabled, disabled = scrapers_status(folder)
		all_sources = sorted(enabled + disabled)
		preselect = [all_sources.index(i) for i in enabled]
		list_items = [{'line1': i.upper(), 'icon': icon} for i in all_sources]
		kwargs = {'items': json.dumps(list_items), 'heading': 'POV', 'multi_choice': 'true', 'preselect': preselect}
		chosen = kodi_utils.select_dialog(all_sources, **kwargs)
		if chosen is None: return
		for i in all_sources:
			if i in chosen: fenom_setSetting('provider.' + i, 'true')
			else: fenom_setSetting('provider.' + i, 'false')
		return kodi_utils.notification(32576, 1500)
	except: return kodi_utils.notification(32574, 1500)

def scrapers_status(folder='all'):
	providers = scraper_names(folder)
	enabled = [i for i in providers if fenom_getSetting('provider.' + i) == 'true']
	disabled = [i for i in providers if i not in enabled]
	return enabled, disabled

def scraper_names(folder):
	providerList = []
	append = providerList.append
	source_folder_location = 'special://home/addons/plugin.video.pov/resources/lib/magneto/%s'
	sourceSubFolders = {'hosters': '', 'torrents': ''}
	if folder == 'all': sourceSubFolders = ['']
	else: sourceSubFolders = [v for k, v in sourceSubFolders.items() if k == folder]
	for item in sourceSubFolders:
		files = kodi_utils.list_dirs(source_folder_location % item)[1]
		for item in files:
			module_name = item.split('.')[0]
			if module_name == '__init__': continue
			append(module_name)
	return providerList

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

def get_filename_match(title, url, name=None):
	from modules.utils import clean_file_name
	if name: return clean_file_name(name)
	from modules.utils import clean_title, normalize
	title_match = None
	try:
		title = clean_title(normalize(title))
		name_url = unquote(url)
		try: file_name = clean_title(name_url.split('/')[-1])
		except: return title_match
		test = name_url.split('/')
		for item in test:
			test_url = string(clean_title(normalize(item)))
			if title in test_url:
				title_match = clean_file_name(string(item)).replace('html', ' ').replace('+', ' ')
				break
	except: pass
	return title_match

def supported_video_extensions():
	supported_video_extensions = kodi_utils.supported_media().split('|')
	return [i for i in supported_video_extensions if i not in ('','.iso','.zip')]

def seas_ep_query_list(season, episode):
	season = int(season)
	episode = int(episode)
	return ['s%de%02d' % (int(season), int(episode)),
			's%02de%02d' % (int(season), int(episode)),
			'%dx%02d' % (int(season), int(episode)),
			'%02dx%02d' % (int(season), int(episode)),
			'season%02depisode%02d' % (int(season), int(episode)),
			'season%depisode%02d' % (int(season), int(episode)),
			'season%depisode%d' % (int(season), int(episode))]

def seas_ep_filter(season, episode, release_title, split=False, return_match=False):
	str_season, str_episode = string(season), string(episode)
	season_fill, episode_fill = str_season.zfill(2), str_episode.zfill(2)
	str_ep_plus_1, str_ep_minus_1 = string(episode+1), string(episode-1)
	release_title = re.sub(r'[^A-Za-z0-9-]+', '.', unquote(release_title).replace('\'', '')).lower()
	string1 = r'(s<<S>>[.-]?e[p]?[.-]?<<E>>[.-])'
	string2 = r'(season[.-]?<<S>>[.-]?episode[.-]?<<E>>[.-])|([s]?<<S>>[x.]<<E>>[.-])'
	string3 = r'(s<<S>>e<<E1>>[.-]?e?<<E2>>[.-])'
	string4 = r'([.-]<<S>>[.-]?<<E>>[.-])'
	string5 = r'(episode[.-]?<<E>>[.-])'
	string6 = r'([.-]e[p]?[.-]?<<E>>[.-])'
	string7 = r'(^(?=.*\.e?0*<<E>>\.)(?:(?!((?:s|season)[.-]?\d+[.-x]?(?:ep?|episode)[.-]?\d+)|\d+x\d+).)*$)'
	string_list = []
	string_list_append = string_list.append
	string_list_append(string1.replace('<<S>>', season_fill).replace('<<E>>', episode_fill))
	string_list_append(string1.replace('<<S>>', str_season).replace('<<E>>', episode_fill))
	string_list_append(string1.replace('<<S>>', season_fill).replace('<<E>>', str_episode))
	string_list_append(string1.replace('<<S>>', str_season).replace('<<E>>', str_episode))
	string_list_append(string2.replace('<<S>>', season_fill).replace('<<E>>', episode_fill))
	string_list_append(string2.replace('<<S>>', str_season).replace('<<E>>', episode_fill))
	string_list_append(string2.replace('<<S>>', season_fill).replace('<<E>>', str_episode))
	string_list_append(string2.replace('<<S>>', str_season).replace('<<E>>', str_episode))
	string_list_append(string3.replace('<<S>>', season_fill).replace('<<E1>>', str_ep_minus_1.zfill(2)).replace('<<E2>>', episode_fill))
	string_list_append(string3.replace('<<S>>', season_fill).replace('<<E1>>', episode_fill).replace('<<E2>>', str_ep_plus_1.zfill(2)))
	string_list_append(string4.replace('<<S>>', season_fill).replace('<<E>>', episode_fill))
	string_list_append(string4.replace('<<S>>', str_season).replace('<<E>>', episode_fill))
	string_list_append(string5.replace('<<E>>', episode_fill))
	string_list_append(string5.replace('<<E>>', str_episode))
	string_list_append(string6.replace('<<E>>', episode_fill))
	string_list_append(string7.replace('<<E>>', episode_fill))
	final_string = '|'.join(string_list)
	reg_pattern = re.compile(final_string)
	if split: return release_title.split(re.search(reg_pattern, release_title).group(), 1)[1]
	elif return_match: return re.search(reg_pattern, release_title).group()
	else: return bool(re.search(reg_pattern, release_title))

def extras_filter():
	return ('sample', 'extra', 'extras', 'deleted', 'unused', 'footage', 'inside', 'blooper', 'bloopers', 'making.of', 'feature',
			'featurette', 'behind.the.scenes', 'trailer')

def find_season_in_release_title(release_title):
	release_title = re.sub(r'[^A-Za-z0-9-]+', '.', unquote(release_title).replace('\'', '')).lower()
	match = None
	regex_list = [r's(\d+)', r's\.(\d+)', r'(\d+)x', r'(\d+)\.x', r'season(\d+)', r'season\.(\d+)']
	for item in regex_list:
		try:
			match = re.search(item, release_title)
			if match:
				match = int(string(match.group(1)).lstrip('0'))
				break
		except: pass
	return match

def check_title(title, release_title, aliases, year, season, episode):
	try:
		all_titles = [title]
		if aliases: all_titles += aliases
		cleaned_titles = []
		cleaned_titles_append = cleaned_titles.append
		year = string(year)
		for i in all_titles:
			cleaned_titles_append(
				i.lower().replace('\'', '').replace(':', '').replace('!', '').replace('(', '').replace(')', '').replace('&', 'and').replace(' ', '.').replace(year, ''))
		release_title = strip_non_ascii_and_unprintable(release_title).lstrip('/ ').replace(' ', '.').replace(':', '.').lower()
		releasetitle_startswith = release_title.lower().startswith
		for i in UNWANTED_TAGS:
			if releasetitle_startswith(i):
				i_startswith = i.startswith
				pattern = r'\%s' % i if i_startswith('[') or i_startswith('+') else r'%s' % i
				release_title = re.sub(r'^%s' % pattern, '', release_title, 1, re.I)
		release_title = release_title.lstrip('.-:/')
		release_title = re.sub(r'^\[.*?]', '', release_title, 1, re.I)
		release_title = release_title.lstrip('.-[](){}:/')
		if season:
			if season == 'pack': hdlr = ''
			else:
				try: hdlr = seas_ep_filter(season, episode, release_title, return_match=True)
				except: return False
		else: hdlr = year
		if hdlr:
			release_title = release_title.split(hdlr.lower())[0]
			release_title = release_title.replace(year, '').replace('(', '').replace(')', '').replace('&', 'and').rstrip('.-').rstrip('.').rstrip('-').replace(':', '')
			if not any(release_title == i for i in cleaned_titles): return False
		else:
			release_title = release_title.replace(year, '').replace('(', '').replace(')', '').replace('&', 'and').rstrip('.-').rstrip('.').rstrip('-').replace(':', '')
			if not any(i in release_title for i in cleaned_titles): return False
		return True
	except: return True

def strip_non_ascii_and_unprintable(text):
	try:
		result = ''.join(char for char in text if char in printable)
		return result.encode('ascii', errors='ignore').decode('ascii', errors='ignore')
	except: pass
	return text

def release_info_format(release_title):
	try:
		release_title = url_strip(release_title)
		release_title = release_title.lower().replace("'", "").lstrip('.').rstrip('.')
		fmt = '.%s.' % re.sub(r'[^a-z0-9-~]+', '.', release_title).replace('.-.', '.').replace('-.', '.').replace('.-', '.').replace('--', '.')
		return fmt
	except:
		return release_title.lower()

def clean_title(title):
	try:
		if not title: return
		title = title.lower()
		title = re.sub(r'&#(\d+);', '', title)
		title = re.sub(r'(&#[0-9]+)([^;^0-9]+)', '\\1;\\2', title)
		title = re.sub(r'(&#[0-9]+)([^;^0-9]+)', '\\1;\\2', title)
		title = title.replace('&quot;', '\"').replace('&amp;', '&')
		title = re.sub(r'\n|([\[({].+?[})\]])|([:;–\-"\',!_.?~$@])|\s', '', title)
	except: pass
	return title

def get_release_quality(release_info):
	if any(i in release_info for i in SCR): return 'SCR'
	if any(i in release_info for i in CAM): return 'CAM'
	if any(i in release_info for i in TELE): return 'TELE'
	if any(i in release_info for i in RES_4K): return '4K'
	if any(i in release_info for i in RES_1080): return '1080p'
	if any(i in release_info for i in RES_720): return '720p'
	return 'SD'

def url_strip(url):
	try:
		url = unquote_plus(url)
		if 'magnet:' in url: url = url.split('&dn=')[1]
		url = url.lower().replace("'", "").lstrip('.').rstrip('.')
		fmt = re.sub(r'[^a-z0-9]+', ' ', url)
		if 'http' in fmt: return None
		if fmt == '': return None
		return fmt
	except: return None

def get_file_info(name_info=None, url=None):
	# thanks 123Venom, whom I knicked most of this code from. :)
	info = []
	info_append = info.append
	if name_info: fmt = name_info
	elif url: fmt = url_strip(url)
	if not fmt: return ''
	quality = get_release_quality(fmt)
	if any(i in fmt for i in VIDEO_3D):  info_append('[B]3D[/B]')
	if '.sdr' in fmt: info_append('SDR')
	elif any(i in fmt for i in DOLBY_VISION): info_append('[B]D/VISION[/B]')
	elif any(i in fmt for i in HDR): info_append('[B]HDR[/B]')
	elif all(i in fmt for i in ('2160p', 'remux')): info_append('[B]HDR[/B]')
	if '[B]D/VISION[/B]' in info:
		if any(i in fmt for i in HDR_TRUE): info_append('[B]HDR[/B]')
		if '[B]HDR[/B]' in info: info_append('[B]HYBRID[/B]')
	if any(i in fmt for i in CODEC_H264): info_append('AVC')
	elif '.av1.' in fmt: info_append('[B]AV1[/B]')
	elif any(i in fmt for i in CODEC_H265): info_append('[B]HEVC[/B]')
	elif any(i in info for i in ('[B]HDR[/B]', '[B]D/VISION[/B]')): info_append('[B]HEVC[/B]')
	elif any(i in fmt for i in CODEC_XVID): info_append('XVID')
	elif any(i in fmt for i in CODEC_DIVX): info_append('DIVX')
	if any(i in fmt for i in REMUX): info_append('REMUX')
	if any(i in fmt for i in BLURAY): info_append('BLURAY')
	elif any(i in fmt for i in DVD): info_append('DVD')
	elif any(i in fmt for i in WEB): info_append('WEB')
	elif 'hdtv' in fmt: info_append('HDTV')
	elif 'pdtv' in fmt: info_append('PDTV')
	elif any(i in fmt for i in HDRIP): info_append('HDRIP')
	if 'atmos' in fmt: info_append('ATMOS')
	if any(i in fmt for i in DOLBY_TRUEHD): info_append('TRUEHD')
	if any(i in fmt for i in DOLBY_DIGITALPLUS): info_append('DD+')
	elif any(i in fmt for i in DOLBY_DIGITALEX): info_append('DD-EX')
	elif any(i in fmt for i in DOLBYDIGITAL): info_append('DD')
	if 'aac' in fmt: info_append('AAC')
	elif 'mp3' in fmt: info_append('MP3')
	if any(i in fmt for i in DTSX): info_append('DTS-X')
	elif any(i in fmt for i in DTS_HDMA): info_append('DTS-HD MA')
	elif any(i in fmt for i in DTS_HD): info_append('DTS-HD')
	elif '.dts' in fmt: info_append('DTS')
	if any(i in fmt for i in AUDIO_8CH): info_append('8CH')
	elif any(i in fmt for i in AUDIO_7CH): info_append('7CH')
	elif any(i in fmt for i in AUDIO_6CH): info_append('6CH')
	elif any(i in fmt for i in AUDIO_2CH): info_append('2CH')
	if '.wmv' in fmt: info_append('WMV')
	elif any(i in fmt for i in CODEC_MPEG): info_append('MPEG')
	elif '.avi' in fmt: info_append('AVI')
	elif any(i in fmt for i in CODEC_MKV): info_append('MKV')
	if any(i in fmt for i in MULTI_LANG): info_append('MULTI-LANG')
	if any(i in fmt for i in ADS): info_append('ADS')
	if any(i in fmt for i in SUBS): info_append('SUBS')
	info = ' | '.join(filter(None, info))
	return quality, info

def get_cache_expiry(mediatype, meta, season):
	try:
		current_date = get_datetime()
		if mediatype == 'movie':
			premiered = jsondate_to_datetime(meta['premiered'], '%Y-%m-%d', remove_time=True)
			difference = subtract_dates(current_date, premiered)
			if difference == 0: single_expiry = int(24*0.125)
			elif difference <= 90: single_expiry = int(24*0.334)
			else: single_expiry = 24*3
			season_expiry, show_expiry = 0, 0
		else:
			extra_info = meta['extra_info']
			ended = extra_info['status'] in ('Ended', 'Canceled')
			premiered = adjust_premiered_date(meta['premiered'], date_offset())[0]
			difference = subtract_dates(current_date, premiered)
			last_episode_to_air = jsondate_to_datetime(extra_info['last_episode_to_air']['air_date'], '%Y-%m-%d', remove_time=True)
			last_ep_difference = subtract_dates(current_date, last_episode_to_air)
			recently_ended = True if ended and last_ep_difference <= 14 else False
			if not ended or recently_ended:
				if difference == 0: single_expiry = int(24*0.125)
				elif difference <= 3: single_expiry = 24*1
				elif difference <= 7: single_expiry = 24*3
				else: single_expiry = 24*7
				if meta['total_seasons'] == season:
					if last_ep_difference <= 7: season_expiry = 24*3
					else: season_expiry = 24*10
				else: season_expiry = 24*30
				show_expiry = 24*10
			else: single_expiry, season_expiry, show_expiry = 24*10, 24*30, 24*30
	except: single_expiry, season_expiry, show_expiry = 24*3, 24*3, 24*10
	return single_expiry, season_expiry, show_expiry

