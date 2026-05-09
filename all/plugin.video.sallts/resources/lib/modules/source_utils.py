import re
from urllib.parse import unquote
from modules import kodi_utils
# from modules.kodi_utils import logger

string = str

def supported_video_extensions():
	supported_video_extensions = kodi_utils.supported_media().split('|')
	return [i for i in supported_video_extensions if not i in ('','.iso','.zip')]

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
			if not match: continue
			match = int(string(match.group(1)).lstrip('0'))
			break
		except: pass
	return match

