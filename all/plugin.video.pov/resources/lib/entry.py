from threading import Thread
from datetime import datetime
from modules import kodi_utils, settings

logger, path_exists, translate_path = kodi_utils.logger, kodi_utils.path_exists, kodi_utils.translate_path
monitor, is_playing, get_visibility = kodi_utils.monitor, kodi_utils.player.isPlaying, kodi_utils.get_visibility
get_property, set_property, clear_property = kodi_utils.get_property, kodi_utils.set_property, kodi_utils.clear_property
get_setting, set_setting, make_settings_dict = kodi_utils.get_setting, kodi_utils.set_setting, kodi_utils.make_settings_dict
parse_qsl, get_infolabel, external_browse = kodi_utils.parse_qsl, kodi_utils.get_infolabel, kodi_utils.external_browse

def runmode(cls, mode):
	call = getattr(cls, mode, None)
	return call() if callable(call) else None

class Router:
	def __enter__(self):
		return self

	def __exit__(self, exc_type, exc_value, traceback):
		if get_property('pov_rli_fix') == 'true' and external_browse():
			message = f"pov not in '{get_infolabel('Container.PluginName')}'"
			raise SystemExit(message)

	def routing(self, sys):
		try: params = dict(parse_qsl(sys.argv[2][1:]))
		except Exception as e: return logger('routing error', str(e))

		params_get = params.get
		mode = params_get('mode', 'navigator.main')
		if 'navigator.' in mode:
			from menus.navigator import Navigator
			runmode(Navigator(params), mode.split('.')[1])
		elif 'menu_editor.' in mode:
			from modules.menu_editor import MenuEditor
			runmode(MenuEditor(params), mode.split('.')[1])
		elif 'discover.' in mode:
			from menus.discover import Discover
			runmode(Discover(params), mode.split('.')[1])
		elif mode == 'media_play':
			from modules.kodi_utils import player, close_all_dialog
			close_all_dialog()
			player.play(params['url'])
		elif mode == 'play_media':
			from sources import Sources
			Sources.factory(params)
		elif 'choice' in mode:
			from modules import dialogs
			if mode == 'scraper_color_choice':
				dialogs.scraper_color_choice(params['setting'])
			elif mode == 'scraper_dialog_color_choice':
				dialogs.scraper_dialog_color_choice(params['setting'])
			elif mode == 'scraper_quality_color_choice':
				dialogs.scraper_quality_color_choice(params['setting'])
			elif mode == 'set_quality_choice':
				dialogs.set_quality_choice(params['quality_setting'])
			elif mode == 'results_sorting_choice':
				dialogs.results_sorting_choice()
			elif mode == 'results_layout_choice':
				dialogs.results_layout_choice()
			elif mode == 'options_menu_choice':
				dialogs.options_menu(params)
			elif mode == 'meta_language_choice':
				dialogs.meta_language_choice()
			elif mode == 'extras_menu_choice':
				dialogs.extras_menu(params)
			elif mode == 'favorites_choice':
				dialogs.favorites_choice(params)
			elif mode == 'trakt_manager_choice':
				dialogs.trakt_manager_choice(params)
			elif mode == 'tmdb_manager_choice':
				dialogs.tmdb_manager_choice(params)
			elif mode == 'mdbl_manager_choice':
				dialogs.mdbl_manager_choice(params)
			elif mode == 'set_language_filter_choice':
				dialogs.set_language_filter_choice(params['filter_setting'])
			elif mode == 'extras_lists_choice':
				dialogs.extras_lists_choice()
			elif mode == 'random_choice':
				dialogs.random_choice(params['mode'], params)
		elif 'trakt.' in mode:
			if 'trakt_account_info' in mode:
				from menus.trakt import trakt_account_info
				trakt_account_info()
			else:
				from modules.utils import manual_function_import
				function = manual_function_import('indexers.trakt_api', mode.split('.')[-1])
				function(params)
		elif 'mdblist.' in mode:
			if 'mdbl_account_info' in mode:
				from menus.mdblist import mdbl_account_info
				mdbl_account_info()
			else:
				from modules.utils import manual_function_import
				function = manual_function_import('indexers.mdblist_api', mode.split('.')[-1])
				function(params)
		elif 'tmdb.' in mode:
			if 'edit_tmdb_list' in mode:
				from menus.tmdb import edit_tmdb_list
				edit_tmdb_list(params)
			elif 'update_tmdb_list' in mode:
				from menus.tmdb import update_tmdb_list
				update_tmdb_list(params)
			else:
				from modules.utils import manual_function_import
				function = manual_function_import('indexers.tmdb_api', mode.split('.')[-1])
				function(params)
		elif 'build' in mode:
			if 'build_trakt_list' in mode:
				from modules.utils import manual_function_import
				function = manual_function_import('menus.trakt', mode.split('.')[-1])
				function(params)
			elif 'build_mdbl_list' in mode:
				from modules.utils import manual_function_import
				function = manual_function_import('menus.mdblist', mode.split('.')[-1])
				function(params)
			elif 'build_tmdb_list' in mode:
				from modules.utils import manual_function_import
				function = manual_function_import('menus.tmdb', mode.split('.')[-1])
				function(params)
			elif mode == 'build_movie_list':
				from menus.movies import Menu
				Menu(params).run()
			elif mode == 'build_tvshow_list':
				from menus.tvshows import Menu
				Menu(params).run()
			elif mode == 'build_season_list':
				from menus.seasons import Seasons
				Seasons(params).run()
			elif mode == 'build_episode_list':
				from menus.seasons import Seasons
				Seasons(params).run()
			elif mode == 'build_in_progress_episode':
				from menus.episodes import Menu
				Menu(params).run()
			elif mode == 'build_next_episode':
				from menus.episodes import Menu
				Menu(params).run()
			elif mode == 'build_my_calendar':
				from menus.episodes import Menu
				Menu(params).run()
			elif mode == 'build_my_anime_calendar':
				from menus.episodes import Menu
				Menu(params).run()
			elif mode == 'build_anime_calendar':
				from menus.episodes import Menu
				Menu(params).run()
			elif mode == 'build_navigate_to_page':
				from modules.dialogs import build_navigate_to_page
				build_navigate_to_page(params)
			elif mode == 'build_popular_people':
				from menus.people import popular_people
				popular_people()
		elif 'watched_unwatched' in mode:
			if mode == 'mark_as_watched_unwatched_episode':
				from caches.watched_cache import mark_as_watched_unwatched_episode
				mark_as_watched_unwatched_episode(params)
			elif mode == 'mark_as_watched_unwatched_season':
				from caches.watched_cache import mark_as_watched_unwatched_season
				mark_as_watched_unwatched_season(params)
			elif mode == 'mark_as_watched_unwatched_tvshow':
				from caches.watched_cache import mark_as_watched_unwatched_tvshow
				mark_as_watched_unwatched_tvshow(params)
			elif mode == 'mark_as_watched_unwatched_movie':
				from caches.watched_cache import mark_as_watched_unwatched_movie
				mark_as_watched_unwatched_movie(params)
			elif mode == 'watched_unwatched_erase_bookmark':
				from caches.watched_cache import erase_bookmark
				erase_bookmark(
					params_get('mediatype'), params_get('tmdb_id'),
					params_get('season', ''), params_get('episode', ''),
					params_get('refresh', 'false')
				)
		elif 'toggle' in mode:
			if mode == 'toggle_provider':
				from modules.utils import toggle_provider
				toggle_provider()
			elif mode == 'toggle_language_invoker':
				from modules.kodi_utils import toggle_language_invoker
				toggle_language_invoker()
		elif 'history' in mode:
			if mode == 'search_history':
				from menus.history import search_history
				search_history(params)
			elif mode == 'clear_search_history':
				from menus.history import clear_search_history
				clear_search_history(params)
			elif mode == 'remove_from_history':
				from menus.history import remove_from_search_history
				remove_from_search_history(params)
			elif mode == 'discover_remove_from_history':
				from menus.discover import remove_from_history
				remove_from_history(params)
			elif mode == 'discover_remove_all_history':
				from menus.discover import remove_all_history
				remove_all_history(params)
		elif 'easynews.' in mode:
			from modules.utils import manual_function_import
			function = manual_function_import('menus.easynews', mode.split('.')[-1])
			function(params)
		elif 'alldebrid' in mode:
			from menus.alldebrid import Menu, resolve_ad
			if 'resolve_' in mode: resolve_ad(params)
			else: Menu().run(params)
		elif 'premiumize' in mode:
			from menus.premiumize import Menu
			Menu().run(params)
		elif 'real_debrid' in mode:
			from menus.real_debrid import Menu, resolve_rd
			if 'resolve_' in mode: resolve_rd(params)
			else: Menu().run(params)
		elif 'torbox' in mode:
			from menus.torbox import Menu, resolve_tb
			if 'resolve_' in mode: resolve_tb(params)
			else: Menu().run(params)
		elif 'offcloud' in mode:
			from menus.offcloud import Menu
			Menu().run(params)
		elif '_settings' in mode:
			if mode == 'open_settings':
				from modules.kodi_utils import open_settings
				open_settings(params_get('query'))
			elif mode == 'clean_settings':
				from modules.kodi_utils import clean_settings
				clean_settings()
			elif mode == 'clean_settings_window_properties':
				from modules.kodi_utils import clean_settings_window_properties
				clean_settings_window_properties()
		elif '_cache' in mode:
			from modules.cache import clear_all_cache, clear_cache
			if mode == 'clear_all_cache': clear_all_cache()
			else: clear_cache(params_get('cache'))
		elif '_image' in mode:
			from menus.images import Images
			Images().run(params)
		elif '_text' in mode:
			from modules.kodi_utils import show_text
			show_text(
				params_get('heading'), params_get('text'), params_get('file'),
				params_get('font_size', 'small'), params_get('kodi_log', 'false') == 'true'
			)
		elif '_view' in mode:
			if mode == 'choose_view':
				from modules.kodi_utils import choose_view
				choose_view(params['view_type'], params_get('content', ''))
			elif mode == 'set_view':
				from modules.kodi_utils import set_view
				set_view(params['view_type'])
			elif mode == 'clear_view':
				from modules.kodi_utils import clear_view
				clear_view(params['view_type'])
		##EXTRA modes##
		elif mode == 'get_search_term':
			from menus.history import get_search_term
			get_search_term(params)
		elif mode == 'person_search':
			from menus.people import person_search
			person_search(params['query'])
		elif 'person_data_dialog' in mode:
			from menus.people import person_data_dialog
			person_data_dialog(params)
		elif mode == 'downloader':
			from modules.downloader import runner
			runner(params)
		elif mode == 'clean_databases':
			from modules.cache import clean_databases
			clean_databases()
		elif mode == 'clear_streams':
			from modules.tuneup import clear_streams
			clear_streams()
		elif mode == 'clear_thumbnails':
			from modules.tuneup import clear_thumbnails
			clear_thumbnails()
		elif mode == 'manual_add_nzb_to_cloud':
			from modules.debrid import Source
			Source(params).manual_add_nzb_to_cloud()
		elif mode == 'upload_logfile':
			from modules.kodi_utils import upload_logfile
			upload_logfile()
		elif mode == 'myservices':
			from modules.myservices import authorize
			authorize()
		elif 'refer_link' in mode:
			from modules.myservices import refer_link
			refer_link(params['query'])
		##FENOM modes###
		elif mode == 'undesirablesInput':
			from caches.undesirables_cache import undesirablesInput
			undesirablesInput()
		elif mode == 'undesirablesUserRemove':
			from caches.undesirables_cache import undesirablesUserRemove
			undesirablesUserRemove()
		elif mode == 'speedTest':
			from fenom.speedtest import magneto
			magneto()

class POVMonitor(kodi_utils.xbmc_monitor):
	def __enter__(self):
		self.threads = (Thread(target=traktMonitor), Thread(target=premAccntNotification))
		return self

	def __exit__(self, exc_type, exc_value, traceback):
		for i in self.threads: i.join()

	def startUpServices(self):
		try: initializeDatabases()
		except: pass
		try: checkSettingsFile()
		except: pass
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

	def onScreensaverActivated(self):
		set_property('pov_pause_services', 'true')

	def onScreensaverDeactivated(self):
		clear_property('pov_pause_services')

	def onSettingsChanged(self):
		clear_property('pov_settings')
		kodi_utils.sleep(50)
		make_settings_dict()
		set_property('pov_kodi_menu_cache', get_setting('kodi_menu_cache'))
		set_property('pov_rli_fix', get_setting('rli_fix'))

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
	clear_property('pov_settings')
	profile_dir = kodi_utils.get_addoninfo('profile')
	profile_xml = profile_dir + 'settings.xml'
	if not path_exists(profile_xml):
		kodi_utils.make_directorys(profile_dir)
		kodi_utils.addon().setSetting('kodi_menu_cache', 'true')
		kodi_utils.sleep(500)
	make_settings_dict()
	set_property('pov_kodi_menu_cache', get_setting('kodi_menu_cache'))
	set_property('pov_rli_fix', get_setting('rli_fix'))
	return logger('POV', 'CheckSettingsFile Service Finished')

def databaseMaintenance():
	from caches.meta_cache import MetaCache
	from modules.cache import clean_databases
	MetaCache().prefetch()
	current_time = int(datetime.now().timestamp())
	next_clean = current_time + 259200 # 3 days
	due_clean = int(get_setting('database.maintenance.due', '0'))
	if current_time < due_clean: return
	logger('POV', 'Database Maintenance Service Starting')
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

def traktMonitor():
	from caches.trakt_cache import clear_trakt_list_contents_data
	from indexers.trakt_api import trakt_sync_activities
	from indexers.mdblist_api import mdbl_sync_activities
	from indexers.tmdb_api import tmdb_clean_watchlist, clear_tmdbl_cache
	logger('POV', 'TraktMonitor Service Starting')
	trakt_service_string = 'TraktMonitor Service Update %s - %s'
	update_string = 'Next Update in %s minutes...'
	if get_property('pov_traktmonitor_first_run') != 'true':
		for i in ('user_lists', 'liked_lists', 'my_lists'): clear_trakt_list_contents_data(i)
		clear_tmdbl_cache()
		set_property('pov_traktmonitor_first_run', 'true')
	while not monitor.abortRequested():
		while is_playing() or get_visibility('Container().isUpdating') or get_property('pov_pause_services') == 'true':
			monitor.waitForAbort(10)
		if get_property('pov_traktmonitor_first_run') != 'true':
			monitor.waitForAbort(5)
		value, interval = settings.trakt_sync_interval()
		next_update_string = update_string % value
		try: status = trakt_sync_activities()
		except: status = 'failed'
		if status == 'success':
			logger('POV', trakt_service_string % ('POV TraktMonitor - Success', 'Trakt Update Performed'))
			if settings.trakt_sync_refresh_widgets():
				kodi_utils.widget_refresh()
				logger('POV', trakt_service_string % ('POV TraktMonitor - Widgets Refresh', 'Setting Activated. Widget Refresh Performed'))
			else: logger('POV', trakt_service_string % ('POV TraktMonitor - Widgets Refresh', 'Setting Disabled. Skipping Widget Refresh'))
		elif status == 'no account':
			logger('POV', trakt_service_string % ('POV TraktMonitor - Aborted. No Trakt Account Active', next_update_string))
		elif status == 'failed':
			logger('POV', trakt_service_string % ('POV TraktMonitor - Failed. Error from Trakt', next_update_string))
		else:# 'not needed'
			logger('POV', trakt_service_string % ('POV TraktMonitor - Success. No Changes Needed', next_update_string))
		try: status = mdbl_sync_activities()
		except: status = 'failed'
		if status == 'success':
			logger('POV', trakt_service_string % ('POV MDBListMonitor - Success', 'MDBList Update Performed'))
			if settings.trakt_sync_refresh_widgets():
				kodi_utils.widget_refresh()
				logger('POV', trakt_service_string % ('POV MDBListMonitor - Widgets Refresh', 'Setting Activated. Widget Refresh Performed'))
			else: logger('POV', trakt_service_string % ('POV MDBListMonitor - Widgets Refresh', 'Setting Disabled. Skipping Widget Refresh'))
		elif status == 'no account':
			logger('POV', trakt_service_string % ('POV MDBListMonitor - Aborted. No MDBList Account Active', next_update_string))
		elif status == 'failed':
			logger('POV', trakt_service_string % ('POV MDBListMonitor - Failed. Error from MDBList', next_update_string))
		else:# 'not needed'
			logger('POV', trakt_service_string % ('POV MDBListMonitor - Success. No Changes Needed', next_update_string))
		try:
			if get_setting('tmdb.token') and get_setting('tmdblist.watchlist_sync') == 'true':
				status = tmdb_clean_watchlist(silent=True)
				if status: logger('POV', 'TMDB Lists Service Update - Success. %s' % status)
		except: pass
		monitor.waitForAbort(interval)
	return logger('POV', 'TraktMonitor Service Finished')

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
	from fenom.undesirables import Undesirables, add_new_default_keywords
	old_database = Undesirables().check_database()
	if old_database: add_new_default_keywords()
	return logger('POV', 'CheckUndesirablesDatabase Service Finished')

