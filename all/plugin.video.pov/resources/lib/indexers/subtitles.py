import requests
from datetime import datetime
from modules.meta_lists import meta_languages
from modules import kodi_utils
# logger = kodi_utils.logger

ls, get_setting = kodi_utils.local_string, kodi_utils.get_setting
timeout = 20.0
action_dict = {'0': 'off', '1': 'auto'}

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
		if self.season: params = 'subtitles/series/%s:%s:%s' % (self.imdb_id, self.season, self.episode)
		else: params = 'subtitles/movie/%s' % self.imdb_id
		try: response = _get(self.manifest.replace('manifest', params), retry=True)
		except requests.RequestException as e: return str(e)
		return response.json()['subtitles'] if response.ok else response.reason

	def _video_file_subs(self):
		try: available_sub_language = self.getSubtitles()
		except: available_sub_language = ''
		if available_sub_language != self.language1: return False
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
		subs = self.subtitles_search()
		if isinstance(subs, str): return kodi_utils.notification('Subtitles Error: %s' % subs)
		if not subs: return kodi_utils.notification(32793, icon=self.poster)
		choices = (i for i in subs if i['lang'] == self.language1)
		try: chosen_sub = next(choices, None) or next(iter(subs))
		except: return kodi_utils.notification(32793, icon=self.poster)
		response = self.subtitles_download(chosen_sub['url'])
		if isinstance(response, str): return kodi_utils.notification('Subtitles Error: %s' % response)
		if 'error' in chosen_sub['lang'].lower():
			now = int(datetime.now().timestamp())
			final_path = '%s%s' % (self.subtitle_path, '%s_%s' % (now, self.search_filename))
		else: final_path = '%s%s' % (self.subtitle_path, self.search_filename)
		try: content = response.text
		except: content = response.content
		with kodi_utils.open_file(final_path, 'w') as file: file.write(content)
		kodi_utils.sleep(1000)
		return final_path

	def run(self, query, imdb_id, season, episode, poster):
		language_choices = {k: v['long'] for k, v in meta_languages.items() if v['long']}
		self.manifest = get_setting('subtitles.manifest')
		self.auto_enable = get_setting('subtitles.auto_enable')
		self.language1 = language_choices[get_setting('subtitles.language')]
		self.subs_action = action_dict[get_setting('subtitles.subs_action', '0')]
		if self.subs_action not in ('auto',): return
		self.imdb_id, self.season, self.episode, self.poster = imdb_id, season, episode, poster
		self.subtitle_path = 'special://temp/'
		if season: self.sub_filename = 'POVSubs_%s_%s_%s' % (self.imdb_id, self.season, self.episode)
		else: self.sub_filename = 'POVSubs_%s' % self.imdb_id
		self.search_filename = self.sub_filename + '_%s.srt' % self.language1
		kodi_utils.sleep(2500)
		subtitle = self._video_file_subs()
		if subtitle: return
		subtitle = self._downloaded_subs()
		if subtitle: return self.setSubtitles(subtitle)
		subtitle = self._searched_subs()
		if subtitle: return self.setSubtitles(subtitle)

