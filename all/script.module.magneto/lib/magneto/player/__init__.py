#import sys
import json
import time
from threading import Thread
from . import cinemeta, kore, settings
from .window_base import open_window, create_window
logger = kore.logger

int_window_prop, xbmc_player, make_listitem = kore.int_window_prop, kore.xbmc_player, kore.make_listitem
get_property, set_property, clear_property = kore.get_property, kore.set_property, kore.clear_property
get_setting, sleep, notification = kore.get_setting, kore.sleep, kore.notification
hide_busy_dialog, close_all_dialog = kore.hide_busy_dialog, kore.close_all_dialog
active_internal_scrapers, auto_play = settings.active_internal_scrapers, settings.auto_play
results_format, filter_status = settings.results_format, settings.filter_status
priority_language, scraping_settings = settings.priority_language, settings.scraping_settings
default_internal_scrapers = ('aiostreams',)
sd_check, main_line = ('SD', '480p', '360p', 'CAM', 'TELE', 'SYNC'), '%s[CR]%s[CR]%s'
quality_ranks = {'4K': 1, '1080p': 2, '720p': 3, 'SD': 4, 'SCR': 5, 'CAM': 5, 'TELE': 5}

def videoplayer(url, listitem, close_action=None):
	def onAVStarted(self): self.playback_event = True
	Player = type('Player', (xbmc_player,), {'onAVStarted': onAVStarted})
	player = Player()
	player.max_attempts = 0
	player.playback_event = False
	try:
#		kore.xbmcplugin.setResolvedUrl(int(sys.argv[1]), True, listitem=listitem)
		player.play(url, listitem=listitem)
		hide_busy_dialog()
		while not player.playback_event and player.max_attempts < 50:
			player.max_attempts += 1
			sleep(200)
	except: pass
	if callable(close_action): close_action()
	return player

class MagnetoPlayer:
	def __init__(self):
		self.params = {}
		self.sources, self.remove_scrapers = [], ['external']
		self.threads, self.providers, self.internal_scraper_names = [], [], []
		self.clear_properties, self.progress_dialog = True, None
		self.sources_total = self.sources_4k = self.sources_1080p = self.sources_720p = self.sources_sd = 0
		self.count_tuple = (
			('sources_4k', '2160p', self._quality_length), ('sources_4k', '4K', self._quality_length),
			('sources_1080p', '1080p', self._quality_length), ('sources_720p', '720p', self._quality_length),
			('sources_sd', '', self._quality_length_sd), ('sources_total', '', self.quality_length_final)
		)

	def source_select(self, params=None):
		hide_busy_dialog()
		if params: self.params = params
		params_get = self.params.get
		self.tmdb_id, self.imdb_id = params_get('tmdb_id'), params_get('imdb_id')
		self.season = int(params_get('season')) if 'season' in self.params else ''
		self.episode = int(params_get('episode')) if 'episode' in self.params else ''
		self.custom_title, self.custom_year = params_get('custom_title', None), params_get('custom_year', None)
		self.custom_season, self.custom_episode = params_get('custom_season', None), params_get('custom_episode', None)
		self.mediatype = 'episode' if self.episode else 'movie' # params_get('mediatype')
		if 'autoplay' in self.params: self.autoplay = params_get('autoplay', 'false') == 'true'
		else: self.autoplay = auto_play(self.mediatype) # params_get('mediatype')
		self._grab_meta()
		self.active_internal_scrapers = active_internal_scrapers()
		self.priority_language = priority_language()
		self.scraper_settings = scraping_settings()
		self.scraper_timeout = settings.scraping_timeout()
		self.sleep_time = 100
		self.filter_hevc, self.hevc_filter_key = filter_status('hevc'), '[B]HEVC[/B]'
		self.filter_av1, self.av1_filter_key = filter_status('av1'), '[B]AV1[/B]'
		self.filter_dv, self.dolby_vision_filter_key = filter_status('dv'), '[B]D/VISION[/B]'
		self.filter_hdr, self.hdr_filter_key = filter_status('hdr'), '[B]HDR[/B]'
		self.hybrid_allowed = self.filter_hdr in (0, 2)
		self._update_meta()
		self._search_info()
		return self.get_sources()

	def get_sources(self):
		if not self.progress_dialog: self._make_progress_dialog()
		results = []
		if self.prepare_internal_scrapers():
			self.providers.extend(self.internal_sources())
			if not self.providers: return notification('No Providers', 2000)
			threads = (Thread(target=self.activate_providers, args=(i[0], i[1]), name=i[2]) for i in self.providers)
			self.threads.extend(threads)
			for i in self.threads: i.start()
			if self.active_internal_scrapers: self.scrapers_dialog()
			results.extend(self.sources)
		else: logger('', 'prepare_internal_scrapers failed')
		if results: return self.play_source(results)
		return self._no_results()

	def prepare_internal_scrapers(self):
		active_internal_scrapers = [i for i in self.active_internal_scrapers if not i in self.remove_scrapers]
		self.internal_scraper_names = active_internal_scrapers[:]
		self.active_internal_scrapers = active_internal_scrapers
		if self.clear_properties: self._clear_properties()
		return True

	def internal_sources(self):
		try: from .aiostreams import source
		except Exception as e: logger('internal_sources', str(e))
		else: return [('internal', source, 'aiostreams')]
		return []
#		active_sources = [i for i in self.active_internal_scrapers if i in default_internal_scrapers]
#		source_dict = []
#		sources = (('internal', manual_function_import('scrapers.%s' % i, 'source'), i) for i in active_sources)
#		try: source_dict.extend(sources)
#		except: pass
#		return source_dict

	def activate_providers(self, module_type, function):
		sources = function().results(self.search_info)
		sleep(400)
		if sources: self.sources.extend(sources)

	def scrapers_dialog(self):
		scraper_list, _threads = self.providers, self.threads
		self.internal_scrapers = self._get_active_scraper_names(scraper_list)
		if not self.internal_scrapers: return
		monitor = kore.monitor
		start_time = time.monotonic()
		while remaining_providers := [x.name for x in _threads if x.is_alive() is True]:
			try:
				if self.progress_dialog.iscanceled() or monitor.abortRequested(): break
				self._process_internal_results()
				current_progress = max((time.monotonic() - start_time), 0)
				line1 = ', '.join(remaining_providers).upper()
				percent = int((current_progress/float(self.scraper_timeout))*100)
				self.progress_dialog.update_scraper(
					self.sources_sd,
					self.sources_720p,
					self.sources_1080p,
					self.sources_4k,
					self.sources_total,
					line1,
					percent
				)
				sleep(self.sleep_time)
				if percent >= 100: break
			except: return self._kill_progress_dialog()
		try: del monitor
		except: pass

	def play_source(self, results):
		if self.autoplay: return self.play_file(results)
		return self.display_results(results)

	def display_results(self, results):
		window_format, window_number = results_format()
		chosen_item = open_window(
			('magneto.player.window_sources', 'SourcesResults'),
			'sources_results.xml',
			window_format=window_format,
			window_id=window_number,
			results=results,
			meta=self.meta,
			priority_language=self.priority_language,
			scraper_settings=self.scraper_settings
		)
		if not chosen_item: return self._kill_progress_dialog()
		action, chosen_item = chosen_item
		if action == 'play': return self.play_file(results, chosen_item)
		return self.play_cancelled()

	def _get_active_scraper_names(self, scraper_list):
		return [i[2] for i in scraper_list]

	def _no_results(self):
		self._kill_progress_dialog()
		hide_busy_dialog()
		notification('No Results', 2000)

	def _update_meta(self):
		self.meta.update({
			'mediatype': self.mediatype, 'season': self.season, 'episode': self.episode,
			'custom_year': self.custom_year, 'custom_title': self.custom_title,
			'custom_season': self.custom_season, 'custom_episode': self.custom_episode
		})

	def _search_info(self):
		title, year = self.get_search_title(), self.get_search_year()
		season, episode, ep_name = self.get_season(), self.get_episode(), self.get_ep_name()
		aliases = self.make_alias_dict(self.meta, title)
		total_seasons = self.meta.get('total_seasons', 1)
		self.search_info = {
			'mediatype': self.mediatype, 'year': year, 'title': title, 'aliases': aliases,
			'imdb_id': self.meta.get('imdb_id'), 'tvdb_id': self.meta.get('tvdb_id'),
			'tmdb_id': self.tmdb_id, 'season': season, 'episode': episode, 'ep_name': ep_name,
			'total_seasons': total_seasons, 'timeout': self.scraper_timeout
		}

	def get_search_title(self):
		search_title = self.meta.get('custom_title', None) or self.meta.get('english_title') or self.meta.get('title')
		return search_title

	def get_search_year(self):
		custom_year = self.meta.get('custom_year', None)
		if custom_year: year = custom_year
		else: year = self.meta.get('year')
		return year

	def get_season(self):
		season = self.meta.get('custom_season', None) or self.meta.get('season')
		try: season = int(season)
		except: season = None
		return season

	def get_episode(self):
		episode = self.meta.get('custom_episode', None) or self.meta.get('episode')
		try: episode = int(episode)
		except: episode = None
		return episode

	def get_ep_name(self):
		ep_name = None
		if self.meta['mediatype'] == 'episode': ep_name = self.meta.get('ep_name')
		return ep_name

	def make_alias_dict(self, meta, title):
		aliases = []
		alternative_titles = meta.get('alternative_titles', [])
		original_title = meta.get('original_title')
		country_codes = set([i.replace('GB', 'UK') for i in meta.get('country_codes', [])])
		if alternative_titles: aliases = [{'title': i, 'country': ''} for i in alternative_titles]
		if original_title not in alternative_titles: aliases.append({'title': original_title, 'country': ''})
		if country_codes: aliases.extend([{'title': '%s %s' % (title, i), 'country': ''} for i in country_codes])
		return aliases

	def _quality_length(self, items, quality):
		return sum(1 for i in items if i.get('resolution', 'SD') == quality)

	def _quality_length_sd(self, items, dummy):
		return sum(1 for i in items if i.get('resolution', 'SD') in sd_check)

	def quality_length_final(self, items, dummy):
		return len(items)

	def _sources_quality_count(self, sources):
		for item in self.count_tuple: setattr(self, item[0], getattr(self, item[0]) + item[2](sources, item[1]))

	def _process_internal_results(self):
		for i in self.internal_scrapers:
			win_property = get_property(int_window_prop % i)
			if win_property in ('checked', '', None): continue
			try: sources = json.loads(win_property)
			except: continue
			set_property(int_window_prop % i, 'checked')
			self._sources_quality_count(sources)

	def _get_quality_rank(self, quality):
		return quality_ranks[quality]

	def _special_filter(self, results, key, enable_setting):
		if key == self.hevc_filter_key and enable_setting in (0,2):
			hevc_max_quality = self._get_quality_rank(get_setting('filter_hevc.%s' % ('max_autoplay_quality' if self.autoplay else 'max_quality'), '4K'))
			results = [i for i in results if not key in i['extraInfo'] or i['quality_rank'] >= hevc_max_quality]
		if enable_setting == 1:
			if key == self.dolby_vision_filter_key and self.hybrid_allowed:
				results = [i for i in results if all(x in i['extraInfo'] for x in (key, self.hdr_filter_key)) or not key in i['extraInfo']]
			else: results = [i for i in results if not key in i['extraInfo']]
		elif enable_setting == 2 and self.autoplay:
			priority_list = [i for i in results if key in i['extraInfo']]
			remainder_list = [i for i in results if not i in priority_list]
			results = priority_list + remainder_list
		elif enable_setting == 3: results = [i for i in results if not any(x in i['extraInfo'] for x in key)]
		return results

	def process_results(self, results):
		self.all_scrapers = list(set(self.active_internal_scrapers + self.remove_scrapers))
		clear_property('fs_filterless_search')
		results = self._special_filter(results, self.hdr_filter_key, self.filter_hdr)
		results = self._special_filter(results, self.dolby_vision_filter_key, self.filter_dv)
		results = self._special_filter(results, self.av1_filter_key, self.filter_av1)
		results = self._special_filter(results, self.hevc_filter_key, self.filter_hevc)
		return results

	def _grab_meta(self):
		if self.mediatype == 'episode':
			self.meta = cinemeta.series_meta(self.imdb_id)
			self.meta.update({'mediatype': 'episode', 'tvshow_plot': self.meta['plot']})
			try:
				episodes_data = self.meta.pop('episodes')
				ep_data = (i for i in episodes_data if i['season'] == self.season and i['episode'] == self.episode)
				episode_data = next(ep_data)
				thumb = episode_data.get('thumb', None) or self.meta.get('fanart') or ''
				self.meta.update({
					'ep_name': episode_data['title'], 'ep_thumb': thumb,
					'season': episode_data['season'], 'episode': episode_data['episode'],
					'premiered': episode_data['premiered'], 'plot': episode_data['plot']
				})
			except: pass
		else: self.meta = cinemeta.movie_meta(self.imdb_id)
		(Thread(target=cinemeta.external_ids, args=('imdb_id', self.imdb_id))).start()

	def _clear_properties(self):
		for item in default_internal_scrapers: clear_property(int_window_prop % item)

	def _make_progress_dialog(self):
		self.progress_dialog = create_window(('magneto.player.window_sources', 'SourcesPlayback'), 'sources_playback.xml', meta=self.meta)
		Thread(target=self.progress_dialog.run).start()

	def _kill_progress_dialog(self):
		try: self.progress_dialog.close()
		except: close_all_dialog()
		try: del self.progress_dialog
		except: pass
		self.progress_dialog = None

	def set_trakt_ids(self):
		import re
		name = self.meta.get('title')
		name = name.lower()
		name = re.sub('[^a-z0-9_]', '-', name)
		name = re.sub('--+', '-', name)
		trakt_ids = {'tmdb': self.tmdb_id, 'imdb': self.imdb_id, 'slug': name}
		if self.mediatype == 'episode': trakt_ids['tvdb'] = self.meta.get('tvdb_id')
		set_property('script.trakt.ids', json.dumps(trakt_ids))

	def set_playback_properties(self):
		try:
			try: self.playing_filename = self.url.split('/')[-1]
			except: self.playing_filename = self.url
			if self.playing_filename: set_property('subs.player_filename', self.playing_filename)
			self.set_trakt_ids()
		except: pass

	def clear_playback_properties(self):
		clear_property('subs.player_filename')
		clear_property('script.trakt.ids')

	def get_listitem(self):
		try:
			li = self.meta.get_listitem()
			if self.mediatype == 'episode': li.toepisode(self.meta, self.meta.get('ep_name'))
		except: li = make_listitem()
		return li

	def resolve_sources(self, item):
		logger('aiostreams', f"resolve_sources\n{json.dumps(item, indent=2)}")
		headers = item.get('requestHeaders')
		if headers: url = '|'.join((item.get('url'), kore.urlencode(headers)))
		else: url = item.get('url')
		return url

	def play_cancelled(self):
#		kore.xbmcplugin.setResolvedUrl(int(sys.argv[1]), False, listitem=make_listitem())
		self._kill_progress_dialog()

	def play_file(self, results, source=None):
		if not source: source = results[0]
		src_idx = next((i for i, _ in enumerate(results, 1) if _ == source), 1)
		provider = (i for i in (source.get('service'), source['addon'] or source['scrape_provider']) if i)
		provider = ' | '.join(provider)
		provider_text = provider.upper()
		display_name = source['filename'].upper()
		try: size_label = f"{source['size'] / 1073741824:.2f} GB"
		except: size_label = 'N/A'
		extraInfo = source.get('quality'), source.get('encode'), *source['visualTags'], *source['subtitles']
		extraInfo = ' | '.join(i.upper() for i in extraInfo if i) or 'N/A'
		extra_info = '[B]%s[/B] | [B]%s[/B] | %s' %  (source.get('resolution', 'SD'), size_label, extraInfo)
		resolve_display = '[B]%02d.[/B] [B]%s[/B]' % (src_idx, provider_text)
		resolve_display = main_line % (resolve_display, extra_info, display_name)
		res = self.sources_sd, self.sources_720p, self.sources_1080p, self.sources_4k, self.sources_total
		self.progress_dialog.update_scraper(*res, resolve_display, 0)
		sleep(200) # needed to update window before curl url check pause
		self.url = self.resolve_sources(source) or notification('Invalid playback url')
		if not self.url: return self.play_cancelled()
		listitem = self.get_listitem()
#		listitem.setProperty('IsPlayable','true')
		listitem.setLabel(self.meta.get('title'))
		listitem.setPath(self.url)
		listitem.setContentLookup(False)
		player = videoplayer(self.url, listitem, self._kill_progress_dialog)
		self.set_playback_properties()
		while player.isPlayingVideo(): sleep(1000)
		self.clear_playback_properties()
