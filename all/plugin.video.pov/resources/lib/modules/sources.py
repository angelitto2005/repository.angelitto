import json
import time
import re, random
from concurrent.futures import ThreadPoolExecutor as TPE, as_completed
from threading import Thread
from magneto import sources as magneto_sources
from windows import open_window, create_window
from caches.providers_cache import ExternalProvidersCache
from indexers.metadata import movie_meta, tvshow_meta, season_episodes_meta, get_title
from modules.debrid import debrid_enabled, debrid_type_enabled, Source, DebridCheck
from modules import player, kodi_utils, settings, source_utils
from modules.utils import manual_function_import, get_datetime, safe_string, string_to_float
#from modules.kodi_utils import logger

POVPlayer, progressDialogBG, notification = player.POVPlayer, kodi_utils.progressDialogBG, kodi_utils.notification
show_busy_dialog, hide_busy_dialog, close_all_dialog = kodi_utils.show_busy_dialog, kodi_utils.hide_busy_dialog, kodi_utils.close_all_dialog
get_property, set_property, clear_property = kodi_utils.get_property, kodi_utils.set_property, kodi_utils.clear_property
ls, monitor, sleep, get_setting = kodi_utils.local_string, kodi_utils.monitor, kodi_utils.sleep, kodi_utils.get_setting
check_prescrape_sources, quality_filter, sort_to_top = settings.check_prescrape_sources, settings.quality_filter, settings.sort_to_top
results_xml_style, results_xml_window_number = settings.results_xml_style, settings.results_xml_window_number
default_internal_scrapers, cloud_scrapers = settings.default_internal_scrapers, settings.cloud_scrapers
pack_enable_check, sources_quality_count = source_utils.pack_enable_check, source_utils.sources_quality_count
get_cache_expiry, get_file_info = source_utils.get_cache_expiry, source_utils.get_file_info
quality_ranks = {'4K': 1, '1080p': 2, '720p': 3, 'SD': 4, 'SCR': 5, 'CAM': 5, 'TELE': 5}
av1_filter_key, hevc_filter_key, hdr_filter_key, dolby_vision_filter_key = '[B]AV1[/B]', '[B]HEVC[/B]', '[B]HDR[/B]', '[B]D/VISION[/B]'
total_format, int_format, ext_format = '[COLOR %s][B]%s[/B][/COLOR]', '[COLOR %s][B]Int: [/B][/COLOR]%s', '[COLOR %s][B]Ext: [/B][/COLOR]%s'
ext_scr_format, unfinshed_import_format, format_line = '[COLOR %s][B]%s[/B][/COLOR]', '[COLOR red]+%s[/COLOR]', '%s[CR]%s[CR]%s'
diag_format, resolutions, pack_display = '4K: %s | 1080p: %s | 720p: %s | SD: %s | Total: %s', '4K 1080p 720p SD total', '%s (%s)'
dialog_format = '[COLOR %s][B]%s[/B][/COLOR] 4K: %s | 1080p: %s | 720p: %s | SD: %s | Total: %s'
remaining_format, season_str, show_str, nores_str = ls(32676), ls(32537), ls(32089), ls(32760)
season_display, show_display = ls(32537), ls(32089)
pack_check = (season_display, show_display)

class Sources:
	nextep_params = []

	@classmethod
	def factory(cls, params):
		try: int(params['episode'])
		except: return cls().source_select(params)
		cls.nextep_callback(params)
		while cls.nextep_params:
			try: cls().source_select(cls.nextep_params.pop())
			except: pass

	@classmethod
	def nextep_callback(cls, params):
		if not isinstance(params, dict): return
		cls.nextep_params.insert(0, params)

	@classmethod
	def background_prep(cls, params):
		self = cls()
		self.source_select({**params, 'background': 'true'})
		return self.pov_background_url

	def __init__(self):
		self.params = {}
		self.clear_properties, self.filters_ignored = True, False
		self.progress_dialog, self.pov_background_url = None, None
		self.threads, self.providers, self.sources, self.internal_scraper_names = [], [], [], []
		self.prescrape_scrapers, self.prescrape_threads, self.prescrape_sources = [], [], []
		self.remove_scrapers = ['external']# needs to be mutable so leave as list.
		self.exclude_list = ['easynews', 'library']# needs to be mutable so leave as list.
		self.internal_resolutions = dict.fromkeys('4K 1080p 720p SD total'.split(), 0)
		self.prescrape, self.disabled_ignored = 'true', 'false'
		self.config_loader = ConfigLoader()
		self.meta_builder = MetaBuilder()
		self.scraper_processor = ScraperProcessor(self)
		self.results_processor = ResultsProcessor(self)

	def source_select(self, params=None):
		if self.clear_properties: self._clear_properties()
		self.config_loader.apply(self, params)
		if not hasattr(self, 'meta'): self.meta = self.meta_builder.get(self)
		results = self.get_sources()
		if not results: return self._process_post_results()
		self.play_source(results)

	def get_sources(self):
		start_time = time.monotonic()
		self.progress_dialog = DialogProgress(getattr(self, 'full_screen', False))
		self.scraper_processor.prepare_internal()
		if self.prescrape and any(x in self.active_internal_scrapers for x in default_internal_scrapers):
			results = self.collect_prescrape_results()
			if results: results = self.results_processor.process(results)
		else: results = []
		if not results:
			self.prescrape = False
			if self.active_external: self.scraper_processor.activate_external()
			self.orig_results = self.collect_results()
			results = self.results_processor.process(self.orig_results)
		self.meta.update({'scrape_time': time.monotonic() - start_time})
		return results

	def collect_results(self):
		self.sources.extend(self.prescrape_sources)
		self.providers.extend(self.scraper_processor.internal_sources(self.active_internal_scrapers, self.mediatype))
		if self.providers:
			threads = (Thread(target=self.activate_providers, args=(i[0], i[1], False), name=i[2]) for i in self.providers)
			self.threads.extend(threads)
			for i in self.threads: i.start()
		if self.active_external or self.background:
			if self.active_external:
				args = (
					self.meta, self.external_providers, self.debrid_torrent_enabled, # self.internal_scraper_names,
					self.threads, self.prescrape_sources, self.progress_dialog, self.disabled_ignored
				)
				self.activate_providers('external', (ExternalManager, args), False)
			elif self.providers and self.background: [i.join() for i in self.threads]
		else: self.scrapers_dialog('internal')
		return self.sources

	def collect_prescrape_results(self):
		self.prescrape_scrapers.extend(self.scraper_processor.internal_sources(self.active_internal_scrapers, self.mediatype, True))
		if not self.prescrape_scrapers: return []
		threads = (Thread(target=self.activate_providers, args=(i[0], i[1], True), name=i[2]) for i in self.prescrape_scrapers)
		self.prescrape_threads.extend(threads)
		for i in self.prescrape_threads: i.start()
		self.remove_scrapers.extend(i[2] for i in self.prescrape_scrapers)
		if self.background: [i.join() for i in self.prescrape_threads]
		else: self.scrapers_dialog('pre_scrape')
		return self.prescrape_sources

	def activate_providers(self, module_type, function, prescrape):
		if module_type == 'external': module = function[0](*function[1])
		else: module = function()
		sources = module.results(self.meta['search_info'])
		if not sources: return
		if prescrape: self.prescrape_sources.extend(sources)
		else: self.sources.extend(sources)

	def scrapers_dialog(self, scrape_type):
		if scrape_type == 'internal':
			scraper_list, _threads, line1_inst, line2_inst = self.providers, self.threads, ls(32096), 'Int:'
		else:
			scraper_list, _threads = self.prescrape_scrapers, self.prescrape_threads,
			line1_inst, line2_inst = '%s %s' % (ls(32829), ls(32830)), 'Pre:'
		self.internal_scrapers = [i[2] for i in scraper_list]
		if not self.internal_scrapers: return
		int_dialog_hl = get_setting('int_dialog_highlight') or 'dodgerblue'
		line1 = total_format % (int_dialog_hl, line1_inst)
		_total_format = total_format % (int_dialog_hl, '%s')
		timeout = self.timeout
		start_time = time.monotonic()
		end_time = start_time + timeout
		self.progress_dialog.make(self.meta)
		while alive_threads := [x.name for x in _threads if x.is_alive()]:
			if monitor.abortRequested() or time.monotonic() > end_time: break
			try:
				self.scraper_processor.process_internal_results()
				int_totals = [_total_format % v for v in self.internal_resolutions.values()]
				current_progress = time.monotonic() - start_time
				line2 = dialog_format % (int_dialog_hl, line2_inst, *int_totals)
				line3 = remaining_format % ', '.join(alive_threads).upper()
				percent = int((current_progress/float(timeout))*100)
				self.progress_dialog.update(format_line % (line1, line2, line3), percent)
			except: pass
			sleep(self.sleep_time)
		self.progress_dialog.kill()

	def _process_post_results(self):
		if self.ignore_results_filter and self.orig_results:
			return self._process_ignore_filters()
		return self._no_results()

	def _process_ignore_filters(self):
		if self.autoplay: notification(32686)
		self.autoplay = False
		self.filters_ignored = True
		results = self.results_processor.sort_results(self.orig_results)
		results = self.results_processor.sort_first(results)
		if not results: return self._no_results()
		return self.play_source(results)

	def _no_results(self):
		hide_busy_dialog()
		if self.background: return
		notification(nores_str)

	def _clear_properties(self):
		for item in default_internal_scrapers: clear_property('%s.internal_results' % item)

	def display_results(self, results):
		window_style = results_xml_style()
		chosen_item = open_window(
			('windows.sources', 'SourceResults'),
			'sources_results.xml',
			window_style=window_style,
			window_id=results_xml_window_number(window_style),
			results=results,
			meta=self.meta,
			scraper_settings=self.scraper_settings,
			prescrape=self.prescrape,
			filters_ignored=self.filters_ignored
		)
		if not chosen_item: return self.progress_dialog.kill()
		action, chosen_item = chosen_item
		if action == 'play':
			return self.play_file(results, chosen_item)
		if action == 'perform_full_search' and self.prescrape:
			self.prescrape, self.clear_properties = False, False
			return self.source_select()

	def play_source(self, results):
		if self.background: self.pov_background_url = bool(results)
		elif self.autoplay: return self.play_file(results)
		else: return self.display_results(results)

	def play_file(self, results, source=None):
		try:
			if source is None:
				source_index, items = 0, results
			elif source in results:
				source_index = results.index(source)
				items = [i for i in results[source_index:] if 'Uncached' not in i.get('cache_provider', '')]
			else: source_index, items = None, [source]
			if self.progress_dialog.full_screen:
				self.progress_dialog.make(self.meta)
				progress_media = self.progress_dialog.kill
			else:
				progressDialogBG.create('POV', 'POV loading...')
				progress_media = None
			for count, item in enumerate(items[:self.limit_resolve], 1):
				link = None
				try:
					if monitor.abortRequested(): break
					elif self.progress_dialog.full_screen and self.progress_dialog.iscanceled(): break
					percent = int(((total_items := len(items))-count)/total_items*100)
					name = (item.get('URLName') or item['name']).upper()
					line1 = item.get('scrape_provider'), item.get('cache_provider'), item.get('provider')
					if source_index is not None: line1 = ('[B]%02d[/B]' % (source_index + count), *line1)
					line2 = item.get('size_label', ''), item.get('extraInfo', '')
					line1 = ' | '.join(i for i in line1 if i and i != 'external').upper()
					line2 = ' | '.join(i for i in line2 if i)
					if self.progress_dialog.full_screen:
						self.progress_dialog.update(format_line % (line1, line2, name), percent)
					else: progressDialogBG.update(percent, name)
				except: pass
				if 'unrestricted_link' in item:
					link = item['unrestricted_link']
					sleep(500)
				else: link = Source(item, self.meta).resolve_sources()
				if link is not None: break
			else:
				if self.progress_dialog.full_screen: self.progress_dialog.kill()
				else: progressDialogBG.close()
				return self._no_results()
			if not self.progress_dialog.full_screen: progressDialogBG.close()
			return POVPlayer().run(link, self.meta, progress_media)
		except: pass

class ConfigLoader:
	def _as_bool(self, value, default=False):
		if value in (None, ''): value = default
		if isinstance(value, bool): return value
		return str(value).lower() == 'true'

	def _as_int(self, value, default=''):
		if value in (None, ''): return default
		return int(value)

	def quality_filter(self, source):
		if not source.autoplay: setting = 'results_quality_%s' % source.mediatype
		else: setting = 'autoplay_quality_%s' % source.mediatype
		filter_list = quality_filter(setting)
		if source.include_prerelease_results and 'SD' in filter_list: filter_list += ['SCR', 'CAM', 'TELE']
		return filter_list

	def apply(self, source, params=None):
		if params: source.params = params
		params_get = source.params.get
		source.prescrape = self._as_bool(params_get('prescrape'), True)
		source.background = self._as_bool(params_get('background'), False)
		if source.background: hide_busy_dialog()
		else: show_busy_dialog()
		source.disabled_ignored = self._as_bool(params_get('disabled_ignored'), False)
		source.ignore_scrape_filters = self._as_bool(params_get('ignore_scrape_filters'), False)
		source.tmdb_id = params_get('tmdb_id')
		source.season = self._as_int(params_get('season'), '')
		source.episode = self._as_int(params_get('episode'), '')
		source.custom_title = params_get('custom_title')
		source.custom_year = params_get('custom_year')
		source.custom_season = self._as_int(params_get('custom_season'), None)
		source.custom_episode = self._as_int(params_get('custom_episode'), None)
		source.mediatype = 'episode' if source.episode else 'movie'
		if 'autoplay' in source.params: source.autoplay = self._as_bool(params_get('autoplay'), False)
		else: source.autoplay = settings.auto_play(source.mediatype)
		source.active_internal_scrapers = settings.active_internal_scrapers()
		source.active_external = 'external' in source.active_internal_scrapers
		source.display_uncached_torrents = settings.display_uncached_torrents()
		source.ignore_results_filter = settings.ignore_results_filter()
		source.provider_sort_ranks = settings.provider_sort_ranks()
		source.scraper_settings = settings.scraping_settings()
		source.sort_function = settings.results_sort_order()
		source.filter_av1 = settings.filter_status('av1')
		source.filter_hevc = settings.filter_status('hevc')
		source.filter_hdr = settings.filter_status('hdr')
		source.filter_dv = settings.filter_status('dv')
		source.hybrid_allowed = source.filter_hdr in (0, 2)
		source.include_prerelease_results, source.include_3D_results = settings.include_prerelease_3d_results()
		source.quality_filter = self.quality_filter(source)
		source.limit_resolve = max(int(get_setting('limit_resolve', '10')), 1)
		if get_property('pov_total_autoplays') != '': source.full_screen = False
		else: source.full_screen = get_setting('load_action') == '1'
		source.size_filter = int(get_setting('results.size_filter', '0'))
		source.include_unknown_size = self._as_bool(get_setting('results.include.unknown.size'), False)
		source.sleep_time = settings.display_sleep_time()
		if source.disabled_ignored:
			source.timeout = int(get_setting('scrapers.timeout.1', '10')) * 2
		else: source.timeout = int(get_setting('scrapers.timeout.1', '10'))
		if self._as_bool(get_setting('results.language_filter'), False):
			source.priority_language = get_setting('results.language')
		else: source.priority_language = None

class DialogProgress:
	def __init__(self, full_screen=True):
		self.full_screen = full_screen
		self.dialog_progress = None

	def make(self, meta):
		self.dialog_progress = create_window(('windows.progress', 'ProgressMedia'), 'progress_media.xml', meta=meta)
		self.iscanceled = self.dialog_progress.iscanceled
		self.update = self.dialog_progress.update
		Thread(target=self.dialog_progress.run).start()

	def kill(self):
		try: self.dialog_progress.close()
		except: close_all_dialog()
		try: del self.dialog_progress
		except: pass
		self.dialog_progress = None

class MetaBuilder:
	def get(self, source):
		if 'meta' in source.params: meta = json.loads(source.params['meta'])
		else: meta = self.get_meta(source)
		for i in ('custom_title', 'custom_year', 'custom_season', 'custom_episode'):
			if getattr(source, i, False): meta[i] = getattr(source, i, '')
		expiry_times = get_cache_expiry(source.mediatype, meta, source.season)
		title = get_title(meta)
		aliases = self.make_alias_dict(meta, title)
		year = self.get_search_year(source, meta)
		ep_name = self.get_ep_name(meta)
		search_info = {
			'scrape_timeout': source.timeout, 'mediatype': source.mediatype, 'expiry_times': expiry_times,
			'tmdb_id': source.tmdb_id, 'imdb_id': meta.get('imdb_id'), 'tvdb_id': meta.get('tvdb_id'),
			'title': title, 'aliases': aliases, 'year': year, 'ep_name': ep_name,
			'total_seasons': meta.get('total_seasons', ''),
			'season': source.custom_season or source.season,
			'episode': source.custom_episode or source.episode,
		}
		meta.update({
			'search_info': search_info, 'background': source.background,
			'mediatype': source.mediatype, 'season': source.season, 'episode': source.episode
		})
		return meta

	def get_meta(self, source):
		meta_user_info, current_date = settings.metadata_user_info(), get_datetime()
		if source.mediatype == 'episode':
			meta = tvshow_meta('tmdb_id', source.tmdb_id, meta_user_info, current_date)
			try:
				episodes_data = season_episodes_meta(source.season, meta, meta_user_info)
				ep_data = next((i for i in episodes_data if i['episode'] == int(source.episode)))
				meta.update({
					'mediatype': 'episode', 'season': ep_data['season'], 'episode': ep_data['episode'],
					'ep_name': ep_data['title'], 'premiered': ep_data['premiered'], 'plot': ep_data['plot']
				})
			except: pass
		else: meta = movie_meta('tmdb_id', source.tmdb_id, meta_user_info, current_date)
		return meta

	def make_alias_dict(self, meta, title):
		seen = set()
		country_codes = (i.replace('GB', 'UK') for i in meta.get('country_codes', []))
		country_codes = tuple(dict.fromkeys(country_codes))
		raw_titles = (meta['title'], meta['original_title'], *meta.get('alternative_titles', []))
		raw_titles = tuple(dict.fromkeys(raw_titles))
		aliases = [{'title': i, 'country': ''} for i in raw_titles]
		aliases.extend({'title': '%s %s' % (title, i), 'country': ''} for i in country_codes)
		valid_titles = (i for i in aliases if i['title'] != title and safe_string(i['title']).strip())
		aliases = [i for i in valid_titles if i['title'] not in seen and not seen.add(i['title'])]
		return aliases

	def get_search_year(self, source, meta):
		if 'custom_year' in meta: return meta['custom_year']
		year = meta.get('year') or '0'
		if source.active_external and get_setting('search.enable.yearcheck', 'false') == 'true':
			from indexers.imdb_api import imdb_movie_year
			try: year = imdb_movie_year(meta.get('imdb_id')) or year
			except: pass
		return year

	def get_ep_name(self, meta):
		if meta.get('mediatype') == 'episode':
			ep_name = meta.get('ep_name') or ''
			try: ep_name = safe_string(ep_name)
			except: pass
		else: ep_name = None
		return ep_name

class ScraperProcessor:
	@staticmethod
	def internal_sources(active_sources, mediatype, prescrape=False):
		source_list = []
		source_list_append = source_list.append
		files = kodi_utils.list_dirs(kodi_utils.scrapers_path)[1]
		for item in files:
			try:
				module_name = item.split('.')[0]
				if module_name in ('__init__',): continue
				if module_name not in active_sources: continue
				if prescrape and not check_prescrape_sources(module_name, mediatype): continue
				module = manual_function_import('scrapers.%s' % module_name, 'source')
				source_list_append(('internal', module, module_name))
			except: pass
		return source_list

	def __init__(self, source_instance):
		self.source = source_instance

	def prepare_internal(self):
		if self.source.active_external and len(self.source.active_internal_scrapers) == 1: return
		active_internal_scrapers = [i for i in self.source.active_internal_scrapers if i not in self.source.remove_scrapers]
		self.source.internal_scraper_names = active_internal_scrapers[:]
		self.source.active_internal_scrapers = active_internal_scrapers

	def activate_external(self):
		self.source.debrid_enabled = debrid_enabled()
		self.source.debrid_torrent_enabled = debrid_type_enabled('torrent', self.source.debrid_enabled)
		if not self.source.debrid_torrent_enabled:
			self.source.progress_dialog.kill()
			self.source.active_external = False
			return notification(32854) if ''.join(self.source.active_internal_scrapers) == 'external' else None
#		if not self.source.debrid_torrent_enabled: self.source.exclude_list.extend(scraper_names('torrents'))
		external_providers = magneto_sources(ret_all=self.source.disabled_ignored)
		self.source.external_providers = [
			i for i in external_providers if i[0] not in self.source.exclude_list
			and (i[1].hasEpisodes if self.source.mediatype == 'episode' else i[1].hasMovies)
		]
		if self.source.mediatype != 'episode': return
		self.source.external_providers = [(i[0], i[1], '') for i in self.source.external_providers]
		season_packs, show_packs = pack_enable_check(self.source.meta, self.source.season, self.source.episode)
		if not season_packs: return
		pack_capable = [i for i in self.source.external_providers if i[1].pack_capable]
		if pack_capable:
			self.source.external_providers.extend([(i[0], i[1], season_str) for i in pack_capable])
		if pack_capable and show_packs:
			self.source.external_providers.extend([(i[0], i[1], show_str) for i in pack_capable])

	def process_internal_results(self):
		for i in self.source.internal_scrapers:
			win_property = get_property('%s.internal_results' % i)
			if win_property in ('checked', '', None): continue
			try: sources = json.loads(win_property)
			except: continue
			set_property('%s.internal_results' % i, 'checked')
			for k in self.source.internal_resolutions:
				self.source.internal_resolutions[k] += sources.get(k, 0)

class ResultsProcessor:
	def __init__(self, source_instance):
		self.source = source_instance

	def process(self, results):
		if self.source.prescrape:
			self.source.all_scrapers = self.source.active_internal_scrapers
		else:
			all_scrapers = {*self.source.active_internal_scrapers, *self.source.remove_scrapers}
			self.source.all_scrapers = list(all_scrapers)
		if self.source.ignore_scrape_filters:
			self.source.filters_ignored = True
			results = self.sort_results(results)
			results = self.sort_first(results)
		else:
			results = self.filter_results(results)
			results = self.sort_results(results)
			results = self.special_filter(results, hevc_filter_key, self.source.filter_hevc)
			results = self.special_filter(results, hdr_filter_key, self.source.filter_hdr)
			results = self.special_filter(results, dolby_vision_filter_key, self.source.filter_dv)
			results = self.special_filter(results, av1_filter_key, self.source.filter_av1)
			results = self.sort_first(results)
		return results

	def filter_results(self, results):
		results = [i for i in results if i['quality'] in self.source.quality_filter]
		if not self.source.include_3D_results:
			results = [i for i in results if '3D' not in i['extraInfo']]
		if not self.source.size_filter:
			return results
		if self.source.size_filter == 1:
			duration = self.source.meta['duration'] or (3600 if self.source.mediatype == 'episode' else 5400)
			max_size = string_to_float(get_setting('results.size.speed', '20'), '20')
			max_size = ((0.125 * (0.90 * max_size)) * duration)/1000
		if self.source.size_filter == 2:
			max_size = string_to_float(get_setting('results.size.file', '10000'), '10000') / 1000
		if self.source.include_unknown_size:
			results = [i for i in results if i['scrape_provider'].startswith('folder') or i['size'] <= max_size]
		else: results = [
			i for i in results if i['scrape_provider'].startswith('folder') or 0.01 < i['size'] <= max_size
		]
		return results

	def sort_results(self, results):
		for item in results:
			provider, quality = item['scrape_provider'], item.get('quality', 'SD')
			account_type = item['debrid'].lower() if provider == 'external' else provider.lower()
			item['provider_rank'] = self.get_provider_rank(account_type)
			item['quality_rank'] = self.get_quality_rank(quality)
		results.sort(key=self.source.sort_function)
		if self.source.priority_language:
			results = self.sort_language_to_top(results)
		results = self.sort_uncached_torrents(results)
		clear_property('fs_filterless_search')
		return results

	def get_provider_rank(self, account_type):
		return self.source.provider_sort_ranks[account_type] or 11

	def get_quality_rank(self, quality):
		return quality_ranks[quality]

	def sort_language_to_top(self, results):
		from modules.meta_lists import meta_languages
		try:
			tokens = meta_languages[self.source.priority_language].values()
			tokens = [re.sub(r'\W', '', self.source.priority_language), *tokens]
			if 'Spanish' in self.source.priority_language: tokens += 'latino', 'lat', 'esp'
			if 'Brazil' in self.source.priority_language: tokens += 'portuguese', 'por', 'pt'
			pattern = re.compile(r'\b(%s)\b' % '|'.join(i for i in tokens if i), re.I)
			sort_first = [i for i in results if pattern.search(i.get('name_info', ''))]
			sort_last = [i for i in results if i not in sort_first]
			results = sort_first + sort_last
		except: pass
		return results

	def sort_uncached_torrents(self, results):
		results.sort(key=lambda k: 'Unchecked' in k.get('cache_provider', ''), reverse=False)
		if self.source.background or self.source.autoplay:
			return [i for i in results if 'Uncached' not in i.get('cache_provider', '')]
		if self.source.display_uncached_torrents or get_property('fs_filterless_search') == 'true':
			return sorted(results, key=lambda k: 'Uncached' in k.get('cache_provider', ''), reverse=False)
		return [i for i in results if 'Uncached' not in i.get('cache_provider', '')]

	def special_filter(self, results, key, enable_setting):
		if enable_setting == 1:
			if key == dolby_vision_filter_key and self.source.hybrid_allowed:
				results = [
					i for i in results if all(x in i['extraInfo']
					for x in (key, hdr_filter_key)) or key not in i['extraInfo']
				]
			else: results = [i for i in results if key not in i['extraInfo']]
		elif enable_setting == 2 and self.source.autoplay:
			priority_list = [i for i in results if key in i['extraInfo']]
			remainder_list = [i for i in results if i not in priority_list]
			results = priority_list + remainder_list
		elif enable_setting == 3:
			results.sort(
				key=lambda k: key in k['extraInfo'] and 'Uncached' not in k.get('cache_provider', ''),
				reverse=True
			)
		return results

	def sort_first(self, results):
		try:
			sort_first_scrapers = []
			sort_first_scrapers.extend([i for i in self.source.all_scrapers if i in cloud_scrapers and sort_to_top(i)])
			if not sort_first_scrapers: return results
			sort_first = [i for i in results if i['scrape_provider'] in sort_first_scrapers]
			sort_first.sort(key=lambda k: k['quality_rank'])
			sort_last = [i for i in results if i not in sort_first]
			results = sort_first + sort_last
		except: pass
		return results

class ExternalManager:
	def dialog_hook(function):
		def wrapper(instance, *args, **kwargs):
			if not instance.background:
				hide_busy_dialog()
				if not instance.progress_dialog.full_screen:
					progressDialogBG.create('POV', 'POV loading...')
				else: instance.progress_dialog.make(instance.meta)
			result = function(instance, *args, **kwargs)
			if not instance.background:
				if not instance.progress_dialog.full_screen:
					progressDialogBG.close()
				else: instance.progress_dialog.kill()
			return result
		return wrapper

	def __init__(
		self, meta, source_dict, debrid_torrents, internal_scrapers,
		prescrape_sources, progress_dialog, disabled_ignored=False
	):
		self.meta, self.background = meta, meta.get('background', False)
		self.source_dict, self.debrid_torrents = source_dict, debrid_torrents
		self.internal_scrapers, self.prescrape_sources = internal_scrapers, prescrape_sources
		self.disabled_ignored, self.progress_dialog = disabled_ignored, progress_dialog
		self.internal_activated = len(self.internal_scrapers) > 0
		self.internal_prescraped = len(self.prescrape_sources) > 0
		self.processed_prescrape = False
		self.processed_internal_scrapers = []
		self.processed_internal_scrapers_append = self.processed_internal_scrapers.append
		self.hostDict, self.sources, self.final_sources = [], [], []
		self.sleep_time = settings.display_sleep_time()
		self.timeout = int(self.meta.get('scrape_timeout', '10')) + 1
		self.int_dialog_highlight = get_setting('int_dialog_highlight', 'dodgerblue')
		self.ext_dialog_highlight = get_setting('ext_dialog_highlight', 'magenta')
		self.int_total = total_format % (self.int_dialog_highlight, '%s')
		self.ext_total = total_format % (self.ext_dialog_highlight, '%s')
		self.internal_resolutions = dict.fromkeys(resolutions.split(), 0)
		self.resolutions = dict.fromkeys(resolutions.split(), 0)

	@dialog_hook
	def results(self, info):
		self.threads = set()
		tpe = TPE(max(1, len(self.source_dict), len(self.debrid_torrents)))
		try:
			random.shuffle(self.source_dict)
			# shuffle because tpe returns order submitted without as_completed
			# chose not to use as_completed because status monitored by done and absolute scrape timeout
			for provider, module, *pack in self.source_dict:
				args = (provider, module, *pack) if pack else (provider, module)
				fut = tpe.submit(ExternalSource(self.meta, self.resolutions).results, info, args)
				fut.name = pack_display % (provider, *pack) if pack and pack[0] else provider
				self.threads.add(fut)
			self.wait()
			providers = [i for fut in self.threads for i in (fut.result() if fut.done() else [])]
			if self.meta.get('mediatype') not in ('movie', 'movies'):
				try: providers.sort(key=lambda k: k.get('package') or '', reverse=True)
				except: pass
			self.sources.extend(self.process_duplicates(providers))
			torrent_sources = [i for i in self.sources if 'torrent' in i['source']]
			result_hashes = list({i['hash'] for i in torrent_sources})
			DebridCheck.set_cached_hashes(result_hashes)
			self.threads = set()
			for item in self.debrid_torrents:
				fut = tpe.submit(DebridCheck(self.meta, item).cache_check)
				fut.name = item
				self.threads.add(fut)
			self.wait(debrid_check=True)
			for name, hashes in ((fut.name, fut.result() if fut.done() else []) for fut in self.threads):
				if name in ('real-debrid', 'alldebrid'): uncached = 'Unchecked %s' % name
				else: uncached = 'Uncached %s' % name
				self.final_sources.extend(
					{**i, 'cache_provider': name if i['hash'] in hashes else uncached, 'debrid': name}
				for i in torrent_sources)
		except: notification(32574)
		finally: tpe.shutdown(False)
		return self.final_sources

	def wait(self, debrid_check=False):
		if not self.background:
			if self.internal_activated or self.internal_prescraped:
				string3 = int_format % (self.int_dialog_highlight, '%s')
				string4 = ext_format % (self.ext_dialog_highlight, '%s')
			else: string4 = ext_scr_format % (self.ext_dialog_highlight, ls(32118))
			string1, string2 = ls(32579) if debrid_check else ls(32676), ls(32677)
			line1 = line2 = line3 = ''
		len_threads = len(self.threads)
		end_time = time.monotonic() + self.timeout
		while alive_threads := (
			*[x.name for x in self.threads if not x.done()],
			*[x.name for x in self.internal_scrapers if x.is_alive()]
		):
			if monitor.abortRequested() or time.monotonic() > end_time: break
			if not self.background:
				try:
					if self.progress_dialog.full_screen and self.progress_dialog.iscanceled(): break
					ext_totals = [self.ext_total % v for v in self.resolutions.values()]
					len_alive_threads = len(alive_threads)
					progress = int((len_threads-len_alive_threads)/len_threads*100)
					if self.internal_activated or self.internal_prescraped:
#						alive_threads.extend(self.process_internal_results())
						self.process_internal_results()
						int_totals = [self.int_total % v for v in self.internal_resolutions.values()]
						line1 = string3 % diag_format % tuple(int_totals)
						line2 = string4 % diag_format % tuple(ext_totals)
					else:
						line1 = string4
						line2 = diag_format % tuple(ext_totals)
					if len_alive_threads > 5: line3 = string1 % str(len_threads-len_alive_threads)
					else: line3 = string1 % ', '.join(alive_threads).upper()
					if self.progress_dialog.full_screen:
						self.progress_dialog.update(format_line % (line1, line2, line3), progress)
					else: progressDialogBG.update(progress, line3)
				except: pass
			sleep(self.sleep_time)

	def process_duplicates(self, sources):
		uniqueURLs, uniqueHashes = set(), set()
		for provider in sources:
			try:
				url = provider['url'].lower()
				if url in uniqueURLs: continue
				uniqueURLs.add(url)
				if 'hash' in provider:
					_hash = provider['hash'].lower()
					if _hash in uniqueHashes: continue
					uniqueHashes.add(_hash)
					yield provider
				else: yield provider
			except: yield provider

	def process_internal_results(self):
		def _process_quality_count(sources):
			for k in self.internal_resolutions: self.internal_resolutions[k] += sources.get(k, 0)
		if self.internal_prescraped and not self.processed_prescrape:
			_process_quality_count(sources_quality_count(self.prescrape_sources))
			self.processed_prescrape = True
		for i in self.internal_scrapers:
			win_property = get_property('%s.internal_results' % i.name)
			if win_property in ('checked', '', None): continue
			try: internal_sources = json.loads(win_property)
			except: continue
			set_property('%s.internal_results' % i.name, 'checked')
			self.processed_internal_scrapers_append(i.name)
			_process_quality_count(internal_sources)
		return [i.name for i in self.internal_scrapers if i.name not in self.processed_internal_scrapers]

class ExternalSource:
	scrape_provider = 'external'
	timeout = 10
	hostDict = {}

	def __init__(self, meta, resolutions=None):
		self.sources = []
		self.meta = meta
		if isinstance(resolutions, dict): self.resolutions = resolutions
		else: self.resolutions = dict.fromkeys(resolutions.split(), 0)

	def results(self, info, args):
		try:
			self.mediatype, self.tmdb_id  = info['mediatype'], str(info['tmdb_id'])
			self.year, aliases = info['year'], info['aliases']
			self.season, self.episode = info['season'], info['episode']
			self.total_seasons = info['total_seasons']
			self.title, self.orig_title = safe_string(info['title']), info['title']
			self.single_expiry, self.season_expiry, self.show_expiry = info['expiry_times']
			if 'scrape_timeout' in info: self.timeout = info['scrape_timeout']
			if self.mediatype == 'episode':
				season_divider = (
					i['episode_count'] for i in self.meta['season_data']
					if int(i['season_number']) == int(self.meta['season'])
				)
				self.season_divider = int(next(season_divider, 1))
				self.show_divider = int(self.meta['total_aired_eps'])
				self.data = {
					'timeout': self.timeout, 'imdb': info['imdb_id'], 'tvdb': info['tvdb_id'],
					'title': safe_string(info['ep_name']), 'tvshowtitle': self.title, 'year': self.year,
					'season': str(self.season), 'episode': str(self.episode),
					'total_seasons': self.total_seasons, 'aliases': aliases
				}
				self.get_episode_source(*args)
			else:
				self.season_divider, self.show_divider, self.data = 1, 1, {
					'timeout': self.timeout, 'imdb': info['imdb_id'],
					'title': self.title, 'year': self.year, 'aliases': aliases
				}
				self.get_movie_source(*args)
		except: pass
		return self.sources

	def get_movie_source(self, provider, module):
		epc = ExternalProvidersCache()
		sources = epc.get(provider, self.mediatype, self.tmdb_id, self.title, self.year, '', '')
		if sources is None:
			sources = module().sources(self.data, self.hostDict)
			sources = self.process_sources(provider, sources)
			epc.set(provider, self.mediatype, self.tmdb_id, self.title, self.year, '', '', sources, self.single_expiry)
		if sources:
			self.sources.extend(sources)

	def get_episode_source(self, provider, module, pack):
		if pack in pack_check: s_check, e_check = '' if pack == show_display else self.season, ''
		else: s_check, e_check = self.season, self.episode
		epc = ExternalProvidersCache()
		sources = epc.get(provider, self.mediatype, self.tmdb_id, self.title, self.year, s_check, e_check)
		if sources is None:
			if pack == show_display:
				expiry_hours = self.show_expiry
				sources = module().sources_packs(self.data, self.hostDict, search_series=True, total_seasons=self.total_seasons)
			elif pack == season_display:
				expiry_hours = self.season_expiry
				sources = module().sources_packs(self.data, self.hostDict)
			else:
				expiry_hours = self.single_expiry
				sources = module().sources(self.data, self.hostDict)
			sources = self.process_sources(provider, sources)
			epc.set(provider, self.mediatype, self.tmdb_id, self.title, self.year, s_check, e_check, sources, expiry_hours)
		if sources:
			if pack == season_display: sources = [i for i in sources if 'episode_start' not in i or i['episode_start'] <= self.episode <= i['episode_end']]
			elif pack == show_display: sources = [i for i in sources if i['last_season'] >= self.season]
			self.sources.extend(sources)

	def process_sources(self, provider, sources):
		try:
			for i in sources:
				try:
					i_get = i.get
					if 'hash' in i: i['hash'] = str(i['hash']).lower()
					URLName = source_utils.clean_file_name(i_get('name')).replace('html', ' ')
					quality, extraInfo = get_file_info(name_info=i_get('name_info'))
					size, size_label, divider = 0, None, None
					try:
						size = i_get('size')
						if 'package' in i and not i_get('true_size', False):
							if i_get('package') == 'season': divider = self.season_divider
							else: divider = self.show_divider
							size = float(size) / divider
							size_label = '%.2f GB' % size
						else: size_label = '%.2f GB' % size
					except: pass
					i.update({
						'external': True, 'provider': provider, 'scrape_provider': self.scrape_provider, 'URLName': URLName,
						'extraInfo': extraInfo, 'quality': quality, 'size_label': size_label, 'size': round(size, 2)
					})
					if quality not in self.resolutions: self.resolutions['SD'] += 1
					else: self.resolutions[quality] += 1
					self.resolutions['total'] += 1
				except: pass
		except: pass
		return sources

