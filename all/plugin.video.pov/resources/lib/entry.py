from threading import Thread
from datetime import datetime
from modules import kodi_utils, settings

logger, path_exists, translate_path = kodi_utils.logger, kodi_utils.path_exists, kodi_utils.translate_path
monitor, is_playing, get_visibility = kodi_utils.monitor, kodi_utils.player.isPlaying, kodi_utils.get_visibility
get_property, set_property, clear_property = kodi_utils.get_property, kodi_utils.set_property, kodi_utils.clear_property
get_setting, set_setting, make_settings_dict = kodi_utils.get_setting, kodi_utils.set_setting, kodi_utils.make_settings_dict

POV_ROUTES = {
	'smart_play_media': lambda p: _import('modules.episode_tools', 'SmartPlay')(p),
	'play_media': lambda p: _import('modules.sources', 'Sources').factory(p),
	'media_play': lambda p: _import('modules.debrid', 'play_from_cloud')(p),
	'downloader': lambda p: _import('modules.downloader', 'factory')(p),

	'scraper_color_choice': lambda p: _import('modules.dialogs', 'scraper_color_choice')(p['setting']),
	'scraper_dialog_color_choice': lambda p: _import('modules.dialogs', 'scraper_dialog_color_choice')(p['setting']),
	'scraper_quality_color_choice': lambda p: _import('modules.dialogs', 'scraper_quality_color_choice')(p['setting']),
	'set_quality_choice': lambda p: _import('modules.dialogs', 'set_quality_choice')(p['quality_setting']),
	'results_sorting_choice': lambda p: _import('modules.dialogs', 'results_sorting_choice')(),
	'results_layout_choice': lambda p: _import('modules.dialogs', 'results_layout_choice')(),
	'options_menu_choice': lambda p: _import('modules.dialogs', 'options_menu')(p),
	'meta_language_choice': lambda p: _import('modules.dialogs', 'meta_language_choice')(),
	'favorites_choice': lambda p: _import('modules.dialogs', 'favorites_choice')(p),
	'set_language_filter_choice': lambda p: _import('modules.dialogs', 'set_language_filter_choice')(p['filter_setting']),
	'extras_lists_choice': lambda p: _import('modules.dialogs', 'extras_lists_choice')(),
	'random_choice': lambda p: _import('modules.dialogs', 'random_choice')(p['mode'], p),
	'extras_menu_choice': lambda p: _import('windows.extras', 'extras_menu')(p),
	'trakt_manager_choice': lambda p: _import('menus.trakt', 'TraktManager')(p).manage(),
	'mdbl_manager_choice': lambda p: _import('menus.mdblist', 'MdbListManager')(p).manage(),
	'tmdb_manager_choice': lambda p: _import('menus.tmdb', 'TmdbManager')(p).manage(),

	'build_movie_list': lambda p: _import('menus.movies', 'Menu')(p).run(),
	'build_tvshow_list': lambda p: _import('menus.tvshows', 'Menu')(p).run(),
	'build_season_list': lambda p: _import('menus.seasons', 'Seasons')(p).run(),
	'build_episode_list': lambda p: _import('menus.seasons', 'Episodes')(p).run(),
	'build_in_progress_episode': lambda p: _import('menus.episodes', 'Menu')(p).run(),
	'build_next_episode': lambda p: _import('menus.episodes', 'Menu')(p).run(),
	'build_my_calendar_trakt': lambda p: _import('menus.episodes', 'Menu')(p).run(),
	'build_my_anime_calendar': lambda p: _import('menus.episodes', 'Menu')(p).run(),
	'build_my_calendar_mdbl': lambda p: _import('menus.episodes', 'Menu')(p).run(),
	'build_anime_calendar': lambda p: _import('menus.episodes', 'Menu')(p).run(),
	'build_navigate_to_page': lambda p: _import('modules.dialogs', 'build_navigate_to_page')(p),
	'build_popular_people': lambda p: _import('menus.people', 'popular_people')(),

	'open_settings': lambda p: _import('modules.kodi_utils', 'open_settings')(p.get('query')),
	'clean_settings': lambda p: _import('modules.kodi_utils', 'clean_settings')(),
	'clean_settings_window_properties': lambda p: _import('modules.kodi_utils', 'clean_settings_window_properties')(),
	'clear_all_cache': lambda p: _import('modules.cache', 'clear_all_cache')(),
	'clear_cache': lambda p: _import('modules.cache', 'clear_cache')(p.get('cache')),
	'clean_databases': lambda p: _import('modules.cache', 'clean_databases')(),
	'clear_streams': lambda p: _import('modules.tuneup', 'clear_streams')(),
	'clear_thumbnails': lambda p: _import('modules.tuneup', 'clear_thumbnails')(),

	'search_history': lambda p: _import('menus.history', 'search_history')(p),
	'clear_search_history': lambda p: _import('menus.history', 'clear_search_history')(p),
	'remove_from_history': lambda p: _import('menus.history', 'remove_from_search_history')(p),
	'discover_remove_from_history': lambda p: _import('menus.discover', 'remove_from_history')(p),
	'discover_remove_all_history': lambda p: _import('menus.discover', 'remove_all_history')(p),
	'get_search_term': lambda p: _import('menus.history', 'get_search_term')(p),
	'person_search': lambda p: _import('menus.people', 'person_search')(p['query']),
	'person_data_dialog': lambda p: _import('menus.people', 'person_data_dialog')(p),

	'mark_as_watched_unwatched_episode': lambda p: _import('caches.watched_cache', 'mark_as_watched_unwatched_episode')(p),
	'mark_as_watched_unwatched_season': lambda p: _import('caches.watched_cache', 'mark_as_watched_unwatched_season')(p),
	'mark_as_watched_unwatched_tvshow': lambda p: _import('caches.watched_cache', 'mark_as_watched_unwatched_tvshow')(p),
	'mark_as_watched_unwatched_movie': lambda p: _import('caches.watched_cache', 'mark_as_watched_unwatched_movie')(p),
	'watched_unwatched_erase_bookmark': lambda p: _import('caches.watched_cache', 'erase_bookmark')(
		p.get('mediatype'), p.get('tmdb_id'), p.get('season', ''), p.get('episode', ''), p.get('refresh', 'false')
	),

	'choose_view': lambda p: _import('modules.kodi_utils', 'choose_view')(p['view_type'], p.get('content', '')),
	'set_view': lambda p: _import('modules.kodi_utils', 'set_view')(p['view_type']),
	'clear_view': lambda p: _import('modules.kodi_utils', 'clear_view')(p['view_type']),
	'show_text': lambda p: _import('modules.kodi_utils', 'show_text')(
		p.get('heading'), p.get('text'), p.get('file'), p.get('font_size', 'small'), p.get('kodi_log', 'false') == 'true'
	),

	'toggle_provider': lambda p: _import('modules.utils', 'toggle_provider')(),
	'toggle_language_invoker': lambda p: _import('modules.kodi_utils', 'toggle_language_invoker')(),
	'upload_logfile': lambda p: _import('modules.kodi_utils', 'upload_logfile')(),
	'myservices': lambda p: _import('modules.myservices', 'authorize')(),
	'refer_link': lambda p: _import('modules.myservices', 'refer_link')(p['query']),
	'undesirablesInput': lambda p: _import('caches.undesirables_cache', 'undesirablesInput')(),
	'undesirablesUserRemove': lambda p: _import('caches.undesirables_cache', 'undesirablesUserRemove')(),
	'speedTest': lambda p: _import('magneto.modules.speedtest', 'magneto')(),
	'aioHelp': lambda p: _import('scrapers.aiostreams', 'aio_help')(),
}

def _import(module_path, attr_name):
	mod = __import__(module_path, fromlist=[attr_name])
	return getattr(mod, attr_name)

def _run_class_method(cls_module, cls_name, params, mode):
	cls = _import(cls_module, cls_name)
	method_name = mode.split('.')[-1]
	method = getattr(cls(params), method_name, None)
	if callable(method): return method()

def _run_debrid_method(cls_module, cls_name, params, mode):
	cls = _import(cls_module, cls_name)
	method_name = mode.split('.')[-1]
	method = getattr(cls(), method_name, None)
	if callable(method): return method(params)

def _run_dynamic_func(module_path, mode, params):
	from modules.utils import manual_function_import
	func_name = mode.split('.')[-1]
	function = manual_function_import(module_path, func_name)
	return function(params)

def routing(sys_obj):
	params = kodi_utils.parsed_query(sys_obj.argv[2])
	mode = params.get('mode', 'navigator.main')

	if mode in POV_ROUTES: return POV_ROUTES[mode](params)

	if mode.startswith('navigator.'): return _run_class_method('menus.navigator', 'Navigator', params, mode)

	if mode.startswith('discover.'): return _run_class_method('menus.discover', 'Discover', params, mode)

	if mode.startswith('menu_editor.'): return _run_class_method('modules.menu_editor', 'MenuEditor', params, mode)

	if '_image' in mode: return _import('menus.images', 'Images')().run(params)

	if mode.startswith('trakt.'):
		if mode == 'trakt.trakt_account_info': return _import('menus.trakt', 'trakt_account_info')()
		return _run_dynamic_func('indexers.trakt_api', mode, params)

	if mode.startswith('mdblist.'):
		if mode == 'mdblist.mdbl_account_info': return _import('menus.mdblist', 'mdbl_account_info')()
		return _run_dynamic_func('indexers.mdblist_api', mode, params)

	if mode.startswith('tmdb.'):
		if mode == 'tmdb.edit_tmdb_list': return _import('menus.tmdb', 'edit_tmdb_list')(params)
		if mode == 'tmdb.update_tmdb_list': return _import('menus.tmdb', 'update_tmdb_list')(params)
		return _run_dynamic_func('indexers.tmdb_api', mode, params)

	if mode.startswith('build_'):
		if mode.startswith('build_trakt_'): return _run_dynamic_func('menus.trakt', mode, params)
		if mode.startswith('build_mdbl_'): return _run_dynamic_func('menus.mdblist', mode, params)
		if mode.startswith('build_tmdb_'): return _run_dynamic_func('menus.tmdb', mode, params)

	if mode.startswith('alldebrid.'): return _run_debrid_method('menus.alldebrid', 'Menu', params, 'run')
	if mode.startswith('premiumize.'): return _run_debrid_method('menus.premiumize', 'Menu', params, 'run')
	if mode.startswith('real_debrid.'): return _run_debrid_method('menus.real_debrid', 'Menu', params, 'run')
	if mode.startswith('torbox.'): return _run_debrid_method('menus.torbox', 'Menu', params, 'run')
	if mode.startswith('offcloud.'): return _run_debrid_method('menus.offcloud', 'Menu', params, 'run')
	if mode.startswith('easynews.'): return _run_dynamic_func('menus.easynews', mode, params)

class Router:
	def __enter__(self):
		return self

	def __exit__(self, exc_type, exc_value, traceback):
		if get_property('pov_rli_fix') != 'true' or not kodi_utils.external_browse(): return
		message = f"pov not in '{kodi_utils.get_infolabel('Container.PluginName')}'"
		raise SystemExit(message)

	def run(self, sys):
		with self: return routing(sys)

class POVMonitor(kodi_utils.xbmc_monitor):
	def __enter__(self):
		initializeDatabases()
		checkSettingsFile()
		self.threads = (Thread(target=SyncMonitorService().run), Thread(target=premAccntNotification))
		return self

	def __exit__(self, exc_type, exc_value, traceback):
		for i in getattr(self, 'threads', ()): i.join()

	def run(self):
		with self:
			try: databaseMaintenance()
			except: pass
			try: viewsSetWindowProperties()
			except: pass
			try: reuseLanguageInvokerCheck()
			except: pass
			for i in getattr(self, 'threads', ()): i.start()
			try: autoRun()
			except: pass
			try: clearSubs()
			except: pass
			try: checkUndesirablesDatabase()
			except: pass
			self.waitForAbort()

	def ver(*args):
		return f"{kodi_utils.get_addoninfo('id')}-{kodi_utils.get_addoninfo('version')}"

	def onSettingsChanged(self):
		clear_property('pov_settings')
		kodi_utils.sleep(50)
		make_settings_dict()
		set_property('pov_kodi_menu_cache', get_setting('kodi_menu_cache'))
		set_property('pov_rli_fix', get_setting('rli_fix'))

	def onScreensaverActivated(self):
		set_property('pov_pause_services', 'true')

	def onScreensaverDeactivated(self):
		clear_property('pov_pause_services')

	def onNotification(self, sender, method, data):
		if method == 'System.OnSleep': set_property('pov_pause_services', 'true')
		elif method == 'System.OnWake': clear_property('pov_pause_services')

def initializeDatabases():
	from modules.cache import check_databases
	logger('POV', 'InitializeDatabases Service Starting')
	check_databases()
	return logger('POV', 'InitializeDatabases Service Finished')

def checkSettingsFile():
	logger('POV', 'CheckSettingsFile Service Starting')
	profile_dir = kodi_utils.get_addoninfo('profile')
	profile_xml = profile_dir + 'settings.xml'
	if not path_exists(profile_xml):
		kodi_utils.make_directorys(profile_dir)
		kodi_utils.addon().setSetting('kodi_menu_cache', 'true')
		kodi_utils.sleep(500)
	clear_property('pov_settings')
	make_settings_dict()
	set_property('pov_kodi_menu_cache', get_setting('kodi_menu_cache'))
	set_property('pov_rli_fix', get_setting('rli_fix'))
	return logger('POV', 'CheckSettingsFile Service Finished')

def databaseMaintenance():
	from caches.meta_cache import MetaCache
	MetaCache().prefetch()
	current_time = int(datetime.now().timestamp())
	next_clean = current_time + 259200 # 3 days
	due_clean = int(get_setting('database.maintenance.due', '0'))
	if current_time < due_clean: return
	logger('POV', 'Database Maintenance Service Starting')
	kodi_utils.clean_settings(silent=True)
	from modules.cache import clean_databases
	clean_databases(current_time, database_check=False, silent=True)
	set_setting('database.maintenance.due', str(next_clean))
	return logger('POV', 'Database Maintenance Service Finished')

def viewsSetWindowProperties():
	logger('POV', 'ViewsSetWindowProperties Service Starting')
	kodi_utils.set_view_properties()
	return logger('POV', 'ViewsSetWindowProperties Service Finished')

def reuseLanguageInvokerCheck():
	import xml.etree.ElementTree as ET
	logger('POV', 'ReuseLanguageInvokerCheck Service Starting')
	addon_xml = translate_path('special://home/addons/plugin.video.pov/addon.xml')
	tree = ET.parse(addon_xml)
	root = tree.getroot()
	current_addon_setting = get_setting('reuse_language_invoker', 'true')
	text = '[B]Reuse Language Invoker[/B] SETTING/XML mismatch[CR]POV will reload your profile to refresh the addon.xml'
	item, refresh = next(root.iter('reuselanguageinvoker'), None), False
	if item is None: kodi_utils.notification(text.split('[CR]')[0])
	if item is not None and item.text != current_addon_setting:
		item.text = current_addon_setting
		tree.write(addon_xml)
		refresh = True
	if refresh and kodi_utils.confirm_dialog(text=text):
		kodi_utils.execute_builtin('LoadProfile(%s)' % kodi_utils.get_infolabel('system.profilename'))
	return logger('POV', 'ReuseLanguageInvokerCheck Service Finished')

def autoRun():
	logger('POV', 'AutoRun Service Starting')
	if settings.auto_start_pov(): kodi_utils.execute_builtin('RunAddon(plugin.video.pov)')
	return logger('POV', 'AutoRun Service Finished')

def clearSubs():
	logger('POV', 'Clear Subtitles Service Starting')
	sub_formats = ('.srt', '.ssa', '.smi', '.sub', '.idx')
	subtitle_path = 'special://temp/'
	for i in kodi_utils.list_dirs(subtitle_path)[1]:
		if i.startswith('POVSubs_') or i.endswith(sub_formats):
			kodi_utils.delete_file(subtitle_path + i)
	return logger('POV', 'Clear Subtitles Service Finished')

def premAccntNotification():
	logger('POV', 'Debrid Account Expiry Notification Service Starting')
	from importlib import import_module
	for user, expires, module, cls in (
		('ad.account_id', 'ad.expires', 'alldebrid_api', 'AllDebridAPI'),
		('pm.account_id', 'pm.expires', 'premiumize_api', 'PremiumizeAPI'),
		('rd.username', 'rd.expires', 'real_debrid_api', 'RealDebridAPI'),
		('tb.account_id', 'tb.expires', 'torbox_api', 'TorBoxAPI')
	):
		try:
			if not get_setting(user): continue
			if (limit := int(get_setting(expires, '7'))) < 1: continue
			module = import_module('debrids.%s' % module)
			days_remaining = getattr(module, cls)().days_remaining()
			if days_remaining is None or days_remaining > limit: continue
			kodi_utils.notification('%s expires in %s days' % (cls, days_remaining))
		except: pass
	return logger('POV', 'Debrid Account Expiry Notification Service Finished')

def checkUndesirablesDatabase():
	logger('POV', 'CheckUndesirablesDatabase Service Starting')
	path = 'special://home/addons/%s/resources/unwanted.json' % kodi_utils.get_addoninfo('id')
	with kodi_utils.open_file(path) as file: set_property('pov_unwanted', str(file.read()))
	from magneto.modules.undesirables import Undesirables, add_new_default_keywords
	old_database = Undesirables().check_database()
	if old_database: add_new_default_keywords()
	return logger('POV', 'CheckUndesirablesDatabase Service Finished')

class SyncMonitorService(kodi_utils.xbmc_monitor):
	def __init__(self):
		kodi_utils.xbmc_monitor.__init__(self)
		from caches.trakt_cache import clear_trakt_list_contents_data
		from indexers.trakt_api import trakt_sync_activities
		from indexers.mdblist_api import mdbl_sync_activities
		from indexers.tmdb_api import tmdb_clean_watchlist, clear_tmdbl_cache
		self.clear_trakt_list_contents_data = clear_trakt_list_contents_data
		self.trakt_sync_activities = trakt_sync_activities
		self.mdbl_sync_activities = mdbl_sync_activities
		self.tmdb_clean_watchlist = tmdb_clean_watchlist
		self.clear_tmdbl_cache = clear_tmdbl_cache
		self.service_string = 'SyncMonitor Service Update %s - %s'
		self.update_string = 'Next Update in %s minutes...'

	def run(self):
		logger('POV', 'SyncMonitor Service Starting')
		self.handle_first_run_cache()
		while not self.abortRequested():
			if get_property('pov_traktmonitor_first_run') != 'true': self.waitForAbort(5)
			else: self.wait_if_busy()
			value, interval = settings.trakt_sync_interval()
			next_update_str = self.update_string % value
			self.sync_trakt(next_update_str)
			self.sync_mdblist(next_update_str)
			self.sync_tmdb()
			self.waitForAbort(interval)
		return logger('POV', 'SyncMonitor Service Finished')

	def handle_first_run_cache(self):
		if get_property('pov_traktmonitor_first_run') != 'true':
			for i in ('user_lists', 'liked_lists', 'my_lists'): self.clear_trakt_list_contents_data(i)
			self.clear_tmdbl_cache()
			set_property('pov_traktmonitor_first_run', 'true')

	def wait_if_busy(self):
		while is_playing() or get_visibility('Container().isUpdating') or get_property('pov_pause_services') == 'true':
			self.waitForAbort(10)

	def refresh_widgets(self, monitor_name):
		if settings.trakt_sync_refresh_widgets():
			kodi_utils.widget_refresh()
			logger('POV', self.service_string % ('POV %s - Widgets Refresh' % monitor_name, 'Setting Activated. Widget Refresh Performed'))
		else:
			logger('POV', self.service_string % ('POV %s - Widgets Refresh' % monitor_name, 'Setting Disabled. Skipping Widget Refresh'))

	def sync_trakt(self, next_update_str):
		try: status = self.trakt_sync_activities(init_callback=True, monitor=self)
		except: status = 'failed'
		if status == 'success':
			logger('POV', self.service_string % ('POV TraktMonitor - Success', 'Trakt Update Performed'))
			self.refresh_widgets('TraktMonitor')
		elif status == 'no account':
			logger('POV', self.service_string % ('POV TraktMonitor - Aborted. No Trakt Account Active', next_update_str))
		elif status == 'failed':
			logger('POV', self.service_string % ('POV TraktMonitor - Failed. Error from Trakt', next_update_str))
		else:
			logger('POV', self.service_string % ('POV TraktMonitor - Success. No Changes Needed', next_update_str))

	def sync_mdblist(self, next_update_str):
		try: status = self.mdbl_sync_activities(init_callback=True, monitor=self)
		except: status = 'failed'
		if status == 'success':
			logger('POV', self.service_string % ('POV MDBListMonitor - Success', 'MDBList Update Performed'))
			self.refresh_widgets('MDBListMonitor')
		elif status == 'no account':
			logger('POV', self.service_string % ('POV MDBListMonitor - Aborted. No MDBList Account Active', next_update_str))
		elif status == 'failed':
			logger('POV', self.service_string % ('POV MDBListMonitor - Failed. Error from MDBList', next_update_str))
		else:
			logger('POV', self.service_string % ('POV MDBListMonitor - Success. No Changes Needed', next_update_str))

	def sync_tmdb(self):
		try:
			if get_setting('tmdb.token') and get_setting('tmdblist.watchlist_sync') == 'true':
				status = self.tmdb_clean_watchlist(silent=True)
				if status: logger('POV', 'TMDB Lists Service Update - Success. %s' % status)
		except: pass

