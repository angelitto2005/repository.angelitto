import requests
from modules.meta_lists import meta_languages
from modules import kodi_utils
# logger = kodi_utils.logger

ls, get_setting = kodi_utils.local_string, kodi_utils.get_setting
subsfound_str, dlfound_str = ls(32792), ls(32793)
nosubs_str, ratelimit_str = ls(32794), ls(32791)
timeout = 20.0

def _get(url, params=None, stream=False, retry=False):
	response = requests.get(url, params=params, stream=stream, timeout=timeout)
	if retry and response.status_code in (429,):
		kodi_utils.notification(ratelimit_str)
		kodi_utils.sleep(10000)
		return _get(url, params=params, stream=stream)
	return response

def subtitles_download(url):
	try: response = _get(url, stream=True, retry=True)
	except requests.RequestException as e: return str(e)
	return response if response.ok else response.reason

def subtitles_search(url):
	try: response = _get(url, retry=True)
	except requests.RequestException as e: return str(e)
	return response.json()['subtitles'] if response.ok else response.reason

class SubtitleScraper:
	def __init__(self, player_object, poster):
		self.player = player_object
		self.poster = poster

	def _video_file_subs(self):
		try: available_sub_language = self.player.getSubtitles()
		except: available_sub_language = ''
		if available_sub_language != self.language1: return False
		if self.auto_enable: self.player.showSubtitles(True)
		kodi_utils.notification(subsfound_str, icon=self.poster)
		return True

	def _downloaded_subs(self):
		files = kodi_utils.list_dirs(self.subtitle_path)[1]
		final_match = next((i for i in files if i == self.search_filename), None)
		if not final_match: return False
		subtitle = '%s%s' % (self.subtitle_path, final_match)
		self.player.setSubtitles(subtitle)
		kodi_utils.notification(dlfound_str, icon=self.poster)
		return True

	def _searched_subs(self):
		subs = subtitles_search(self.manifest.replace('manifest', self.path))
		if isinstance(subs, str): return kodi_utils.notification('Subtitles Error: %s' % subs)
		if not subs: return kodi_utils.notification(nosubs_str, icon=self.poster)
		preferred = (i for i in subs if i['lang'] == self.language1)
		alternate = (i for i in subs if 'toolbox' not in i['lang'])
		try: chosen_sub = next(preferred, None) or next(alternate)
		except: return kodi_utils.notification(nosubs_str, icon=self.poster)
		response = subtitles_download(chosen_sub['url'])
		if isinstance(response, str): return kodi_utils.notification('Subtitles Error: %s' % response)
		if 'error' in chosen_sub['lang'].lower():
			final_path = '%s%s_%s' % (self.subtitle_path, hex(id(self))[2:], self.search_filename)
		else: final_path = '%s%s' % (self.subtitle_path, self.search_filename)
		try: content = response.text
		except: content = response.content
		with kodi_utils.open_file(final_path, 'w') as file: file.write(content)
		kodi_utils.sleep(1000)
		self.player.setSubtitles(final_path)
		return True

	def run(self):
		if get_setting('subtitles.subs_action', '0') not in ('1',): return
		language_choices = {k: v['long'] for k, v in meta_languages.items() if v['long']}
		self.language1 = language_choices[get_setting('subtitles.language')]
		self.auto_enable = get_setting('subtitles.auto_enable') == 'true'
		self.manifest = get_setting('subtitles.manifest').strip()
		self.subtitle_path = 'special://temp/'
		sub_filename = 'POVSubs_%s' % self.player.imdb_id
		if self.player.mediatype == 'episode':
			self.path = 'subtitles/series/%s:%s:%s' % (self.player.imdb_id, self.player.season, self.player.episode)
			sub_filename = '%s_%s_%s' % (sub_filename, self.player.season, self.player.episode)
		else: self.path = 'subtitles/movie/%s' % self.player.imdb_id
		self.search_filename = '%s_%s.srt' % (sub_filename, self.language1)
		kodi_utils.sleep(2000)
		return self._video_file_subs() or self._downloaded_subs() or self._searched_subs()

