import sys
from modules.kodi_utils import parse_qsl, logger, get_property, get_infolabel, external_browse

def runmode(cls, params, mode):
	call = getattr(cls(params), mode, None)
	return call() if callable(call) else None

class Router:
	def __enter__(self):
		return self

	def __exit__(self, exc_type, exc_value, traceback):
		if get_property('salts_rli_fix') == 'true' and external_browse():
			message = f"salts not in '{get_infolabel('Container.PluginName')}'"
			raise SystemExit(message)

	def routing(self, sys):
		try: params = dict(parse_qsl(sys.argv[2][1:]))
		except Exception as e: return logger('routing error', str(e))

		params_get = params.get
		mode = params_get('mode', 'navigator.main')
		if 'navigator.' in mode:
			from menus.navigator import Navigator
			runmode(Navigator, params, mode.split('.')[1])
		elif 'menu_editor.' in mode:
			from modules.menu_editor import MenuEditor
			runmode(MenuEditor, params, mode.split('.')[1])
		elif 'discover.' in mode:
			from menus.discover import Discover
			runmode(Discover, params, mode.split('.')[1])
		elif mode == 'media_play':
			from modules.kodi_utils import player, close_all_dialog
			close_all_dialog()
			player.play(params['url'])
		elif mode == 'play_media':
			from sources import Sources
			Sources().source_select(params)
		elif 'choice' in mode:
			from modules import dialogs
			if mode == 'scraper_color_choice':
				dialogs.scraper_color_choice(params['setting'])
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
			elif mode == 'mdbl_manager_choice':
				dialogs.mdbl_manager_choice(params)
			elif mode == 'flicklist_manager_choice':
				dialogs.flicklist_manager_choice(params)
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
		elif 'flicklist.' in mode:
			if 'flicklist_account_info' in mode:
				from menus.flicklist import flicklist_account_info
				flicklist_account_info()
			else:
				from modules.utils import manual_function_import
				function = manual_function_import('indexers.flicklist_api', mode.split('.')[-1])
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
			elif 'build_flicklist_list' in mode:
				from modules.utils import manual_function_import
				function = manual_function_import('menus.flicklist', mode.split('.')[-1])
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
				erase_bookmark(params_get('mediatype'), params_get('tmdb_id'), params_get('season', ''), params_get('episode', ''), params_get('refresh', 'false'))
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
		elif 'premiumize' in mode:
			from menus.premiumize import Menu
			Menu().run(params)
		elif 'realdebrid' in mode:
			from menus.realdebrid import Menu, resolve_rd
			if 'resolve_' in mode: resolve_rd(params)
			else: Menu().run(params)
		elif 'torbox' in mode:
			from menus.torbox import Menu, resolve_tb
			if 'resolve_' in mode: resolve_tb(params)
			else: Menu().run(params)
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
			show_text(params_get('heading'), params_get('text'), params_get('file'), params_get('font_size', 'small'), params_get('kodi_log', 'false') == 'true')
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
		elif mode == 'upload_logfile':
			from modules.kodi_utils import upload_logfile
			upload_logfile()
		elif mode == 'myservices':
			from modules.myservices import authorize
			authorize()
		elif 'refer_link' in mode:
			from modules.myservices import refer_link
			refer_link(params['query'])
		##EXTRA EXTRA modes##
		elif mode == 'color_pick':
			from magneto.settings import color_pick
			color_pick(params)


if __name__ == '__main__':
	with Router() as r: r.routing(sys)

