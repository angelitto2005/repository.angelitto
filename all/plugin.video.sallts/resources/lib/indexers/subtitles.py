import os
import requests
from datetime import datetime, timedelta
from caches.main_cache import MainCache
from modules.meta_lists import language_choices
from modules import kodi_utils
# logger = kodi_utils.logger

ls, get_setting = kodi_utils.local_string, kodi_utils.get_setting
search_url = 'https://sub.wyzie.io/search'
timeout = 20.0
action_dict = {'0': 'auto', '1': 'select', '2': 'off'}
api_sources = ('opensubtitles', 'subdl', 'subf2m', 'gestdown', 'yify')

def _get(url, params=None, stream=False, retry=False):
	response = requests.get(url, params=params, stream=stream, timeout=timeout)
	if retry and response.status_code in (403, 429):
		kodi_utils.notification(32740)
		kodi_utils.sleep(10000)
		return _get(url, params=params, stream=stream)
	return response

class Subtitles(kodi_utils.xbmc_player):
	def subtitles_download(self, url):
		response = _get(url, stream=True, retry=True)
		return response if response.ok else response.reason

	def subtitles_search(self):
		params = {
			'encoding': 'utf-8',
			'format': 'srt',
			'source': ','.join(api_sources),
			'key': self.apikey,
			'id': self.imdb_id
		}
		if self.season: params.update({'season': self.season, 'episode': self.episode})
		maincache = MainCache()
		current_time = maincache._get_timestamp(datetime.now())
		cache = maincache.get_memory_cache(self.sub_filename, current_time)
		if cache: return cache
		response = _get(search_url, params=params, retry=True)
		if not response.ok: return response.reason
		response = response.json()
		expires = maincache._get_timestamp(datetime.now() + timedelta(hours=24))
		if response: maincache.set_memory_cache(response, self.sub_filename, expires)
		return response

	def subtitles_select(self, result):
		def _builder():
			for i in result:
				line1 = i['display'].upper(), ' (SDH)' if i['isHearingImpaired'] else ''
				line2 = i.get('origin') or 'N/A', i['source'].upper(), i.get('release') or i['media']
				listitem = kodi_utils.make_listitem()
				listitem.setLabel('%s%s' % line1)
				listitem.setLabel2('%s - %s[CR]%s' % line2)
				listitem.setArt({'icon': i['flagUrl'].replace('24.png', '64.png')})
				yield listitem
		try: video_path = self.getPlayingFile()
		except: video_path = ''
		video_path = next(iter(video_path.split('|')), video_path)
		video_path = os.path.basename(video_path)
		heading = '%s - %s' % (ls(32246).upper(), video_path)
		self.pause()
		chosen_sub = kodi_utils.dialog.select(heading, list(_builder()), useDetails=True)
		self.pause()
		return chosen_sub

	def _video_file_subs(self):
		try: available_sub_language = self.getSubtitles()
		except: available_sub_language = ''
		if not available_sub_language == self.language1: return False
		if self.auto_enable == 'true': self.showSubtitles(True)
		kodi_utils.notification(32852, icon=self.poster)
		return True

	def _downloaded_subs(self):
		files = kodi_utils.list_dirs(self.subtitle_path)[1]
		final_match = next((i for i in files if i == self.search_filename), None)
		if not final_match: return False
		subtitle = '%s%s' % (self.subtitle_path, final_match)
		kodi_utils.notification(32792, icon=self.poster)
		return subtitle

	def _searched_subs(self):
		result = self.subtitles_search()
		if isinstance(result, str): return kodi_utils.notification('Subtitles Error: %s' % result)
		if not result: return kodi_utils.notification(32793, icon=self.poster)
		search_language = kodi_utils.convert_language(self.language1, format='short')
		result.sort(key=lambda k: k['display'], reverse=False)
		result.sort(key=lambda k: k['language'] == search_language, reverse=True)
		if self.subs_action == 'select' and len(result) > 1: chosen_sub = self.subtitles_select(result)
		else: chosen_sub = next((i for i, _ in enumerate(result) if _['language'] == search_language), -1)
		if chosen_sub < 0: return kodi_utils.notification(32736, icon=self.poster)
		chosen_sub = result[chosen_sub]
		final_path = '%s%s' % (self.subtitle_path, self.search_filename)
		response = self.subtitles_download(chosen_sub['url'])
		if isinstance(response, str): return kodi_utils.notification('Subtitles Error: %s' % response)
		try: content = response.text
		except: content = response.content
		with kodi_utils.open_file(final_path, 'w') as file: file.write(content)
		kodi_utils.sleep(1000)
		return final_path

	def run(self, query, imdb_id, season, episode, poster):
		self.apikey = get_setting('subtitles.apikey')
		self.auto_enable = get_setting('subtitles.auto_enable')
		self.language1 = language_choices[get_setting('subtitles.language')]
		self.subs_action = action_dict[get_setting('subtitles.subs_action', '2')]
		if not self.subs_action in ('auto', 'select'): return
		self.imdb_id, self.season, self.episode, self.poster = imdb_id, season, episode, poster
		self.subtitle_path = 'special://temp/'
		if season: self.sub_filename = 'SALTSSubs_%s_%s_%s' % (self.imdb_id, self.season, self.episode)
		else: self.sub_filename = 'SALTSSubs_%s' % self.imdb_id
		self.search_filename = self.sub_filename + '_%s.srt' % self.language1
		kodi_utils.sleep(2500)
		subtitle = self._video_file_subs()
		if subtitle: return
		subtitle = self._downloaded_subs()
		if subtitle: return self.setSubtitles(subtitle)
		subtitle = self._searched_subs()
		if subtitle: return self.setSubtitles(subtitle)

