# -*- coding: utf-8 -*-
from xbmc import getInfoLabel
from urllib.parse import parse_qsl
from modules.kodi_utils import external, get_property
# from modules.kodi_utils import logger

def sys_exit_check():
	if get_property('fenlight.reuse_language_invoker') == 'false': return False
	return external()

def routing(sys):
	params = dict(parse_qsl(sys.argv[2][1:], keep_blank_values=True))
	_get = params.get
	mode = _get('mode', 'navigator.main')
	if 'navigator.' in mode:
		from indexers.navigator import Navigator
		exec('Navigator(params).%s()' % mode.split('.')[1])
	elif 'menu_editor.' in mode:
		from modules.menu_editor import MenuEditor
		exec('MenuEditor(params).%s()' % mode.split('.')[1])
	elif 'personal_lists.' in mode:
		from indexers import personal_lists
		exec('personal_lists.%s(params)' % mode.split('.')[1])
	elif 'tmdblist.' in mode:
		from indexers import tmdb_lists
		exec('tmdb_lists.%s(params)' % mode.split('.')[1])
	elif 'easynews.' in mode:
		from indexers import easynews
		exec('easynews.%s(params)' % mode.split('.')[1])
	elif 'playback.' in mode:
		if mode == 'playback.media':
			from modules.sources import Sources
			Sources().playback_prep(params)
		elif mode == 'playback.video':
			from modules.player import FenLightPlayer
			FenLightPlayer().run(_get('url', None), _get('obj', None))
	elif 'choice' in mode:
		from indexers import dialogs
		exec('dialogs.%s(params)' % mode)
	elif 'custom_key.' in mode:
		from modules import custom_keys
		exec('custom_keys.%s()' % mode.split('custom_key.')[1])
	elif 'trakt.' in mode:
		if '.list' in mode:
			from indexers import trakt_lists
			exec('trakt_lists.%s(params)' % mode.split('.')[2])
		else:
			from apis import trakt_api
			exec('trakt_api.%s(params)' % mode.split('.')[1])
	elif 'build' in mode:
		if mode == 'build_movie_list':
			from indexers.movies import Movies
			Movies(params).fetch_list()
		elif mode == 'build_tvshow_list':
			from indexers.tvshows import TVShows
			TVShows(params).fetch_list()
		elif mode == 'build_season_list':
			from indexers.seasons import build_season_list
			build_season_list(params)
		elif mode == 'build_episode_list':
			from indexers.episodes import build_episode_list
			build_episode_list(params)
		elif mode == 'build_in_progress_episode':
			from indexers.episodes import build_single_episode
			build_single_episode('episode.progress', params)
		elif mode == 'build_recently_watched_episode':
			from indexers.episodes import build_single_episode
			build_single_episode('episode.recently_watched', params)
		elif mode == 'build_next_episode':
			from indexers.episodes import build_single_episode
			build_single_episode('episode.next', params)
		elif mode == 'build_my_calendar':
			from indexers.episodes import build_single_episode
			build_single_episode('episode.trakt', params)
		elif mode == 'build_next_episode_manager':
			from modules.episode_tools import build_next_episode_manager
			build_next_episode_manager()
		elif mode == 'build_tmdb_people':
			from indexers.people import tmdb_people
			tmdb_people(params)
		elif 'random.' in mode:
			from indexers.random_lists import RandomLists
			RandomLists(params).run_random()
	elif 'watched_status.' in mode:
		if mode == 'watched_status.mark_episode':
			from modules.watched_status import mark_episode
			mark_episode(params)
		elif mode == 'watched_status.mark_season':
			from modules.watched_status import mark_season
			mark_season(params)
		elif mode == 'watched_status.mark_tvshow':
			from modules.watched_status import mark_tvshow
			mark_tvshow(params)
		elif mode == 'watched_status.mark_movie':
			from modules.watched_status import mark_movie
			mark_movie(params)
		elif mode == 'watched_status.erase_bookmark':
			from modules.watched_status import erase_bookmark
			erase_bookmark(_get('media_type'), _get('tmdb_id'), _get('season', ''), _get('episode', ''), _get('refresh', 'false'))
		elif mode == 'watched_status.unmark_previous_episode':
			from modules.watched_status import unmark_previous_episode
			unmark_previous_episode(params)
	elif 'search.' in mode:
		if mode == 'search.get_key_id':
			from modules.search import get_key_id
			get_key_id(params)
		elif mode == 'search.clear_search':
			from modules.search import clear_search
			clear_search()
		elif mode == 'search.remove':
			from modules.search import remove_from_search
			remove_from_search(params)
		elif mode == 'search.clear_all':
			from modules.search import clear_all
			clear_all(_get('setting_id'), _get('refresh', 'false'))
	elif 'real_debrid' in mode:
		if mode == 'real_debrid.rd_cloud':
			from indexers.real_debrid import rd_cloud
			rd_cloud()
		elif mode == 'real_debrid.rd_downloads':
			from indexers.real_debrid import rd_downloads
			rd_downloads()
		elif mode == 'real_debrid.browse_rd_cloud':
			from indexers.real_debrid import browse_rd_cloud
			browse_rd_cloud(_get('id'))
		elif mode == 'real_debrid.resolve_rd':
			from indexers.real_debrid import resolve_rd
			resolve_rd(params)
		elif mode == 'real_debrid.rd_account_info':
			from indexers.real_debrid import rd_account_info
			rd_account_info()
		elif mode == 'real_debrid.authenticate':
			from apis.real_debrid_api import RealDebridAPI
			RealDebridAPI().auth()
		elif mode == 'real_debrid.revoke_authentication':
			from apis.real_debrid_api import RealDebridAPI
			RealDebridAPI().revoke()
		elif mode == 'real_debrid.delete':
			from indexers.real_debrid import rd_delete
			rd_delete(_get('id'), _get('cache_type'))
	elif 'premiumize' in mode:
		if mode == 'premiumize.pm_cloud':
			from indexers.premiumize import pm_cloud
			pm_cloud(_get('id', None), _get('folder_name', None))
		elif mode == 'premiumize.pm_transfers':
			from indexers.premiumize import pm_transfers
			pm_transfers()
		elif mode == 'premiumize.pm_account_info':
			from indexers.premiumize import pm_account_info
			pm_account_info()
		elif mode == 'premiumize.authenticate':
			from apis.premiumize_api import PremiumizeAPI
			PremiumizeAPI().auth()
		elif mode == 'premiumize.revoke_authentication':
			from apis.premiumize_api import PremiumizeAPI
			PremiumizeAPI().revoke()
		elif mode == 'premiumize.rename':
			from indexers.premiumize import pm_rename
			pm_rename(_get('file_type'), _get('id'), _get('name'))
		elif mode == 'premiumize.delete':
			from indexers.premiumize import pm_delete
			pm_delete(_get('file_type'), _get('id'))
	elif 'alldebrid' in mode:
		if mode == 'alldebrid.ad_cloud':
			from indexers.alldebrid import ad_cloud
			ad_cloud(_get('id', None))
		elif mode == 'alldebrid.ad_downloads':
			from indexers.alldebrid import ad_downloads
			ad_downloads()
		elif mode == 'alldebrid.ad_saved_links':
			from indexers.alldebrid import ad_saved_links
			ad_saved_links()
		elif mode == 'alldebrid.browse_ad_cloud':
			from indexers.alldebrid import browse_ad_cloud
			browse_ad_cloud(_get('id'))
		elif mode == 'alldebrid.resolve_ad':
			from indexers.alldebrid import resolve_ad
			resolve_ad(params)
		elif mode == 'alldebrid.ad_account_info':
			from indexers.alldebrid import ad_account_info
			ad_account_info()
		elif mode == 'alldebrid.authenticate':
			from apis.alldebrid_api import AllDebridAPI
			AllDebridAPI().auth()
		elif mode == 'alldebrid.revoke_authentication':
			from apis.alldebrid_api import AllDebridAPI
			AllDebridAPI().revoke()
		elif mode == 'alldebrid.delete':
			from indexers.alldebrid import ad_delete
			ad_delete(_get('id'))
	elif 'offcloud' in mode:
		if mode == 'offcloud.oc_cloud':
			from indexers.offcloud import oc_cloud
			oc_cloud()
		elif mode == 'offcloud.browse_oc_cloud':
			from indexers.offcloud import browse_oc_cloud
			browse_oc_cloud(_get('folder_id'))
		elif mode == 'offcloud.resolve_oc':
			from indexers.offcloud import resolve_oc
			resolve_oc(params)
		elif mode == 'offcloud.oc_account_info':
			from indexers.offcloud import oc_account_info
			oc_account_info()
		elif mode == 'offcloud.authenticate':
			from apis.offcloud_api import OffcloudAPI
			OffcloudAPI().auth()
		elif mode == 'offcloud.revoke_authentication':
			from apis.offcloud_api import OffcloudAPI
			OffcloudAPI().revoke()
		elif mode == 'offcloud.delete':
			from indexers.offcloud import oc_delete
			oc_delete(_get('folder_id'))
	elif 'easydebrid' in mode:
		if mode == 'easydebrid.authenticate':
			from apis.easydebrid_api import EasyDebridAPI
			EasyDebridAPI().auth()
		elif mode == 'easydebrid.revoke_authentication':
			from apis.easydebrid_api import EasyDebridAPI
			EasyDebridAPI().revoke()
	elif 'torbox' in mode:
		if mode == 'torbox.tb_cloud':
			from indexers.torbox import tb_cloud
			tb_cloud()
		elif mode == 'torbox.browse_tb_cloud':
			from indexers.torbox import browse_tb_cloud
			browse_tb_cloud(_get('folder_id'), _get('media_type'))
		elif mode == 'torbox.resolve_tb':
			from indexers.torbox import resolve_tb
			resolve_tb(params)
		elif mode == 'torbox.tb_account_info':
			from indexers.torbox import tb_account_info
			tb_account_info()
		elif mode == 'torbox.authenticate':
			from apis.torbox_api import TorBoxAPI
			TorBoxAPI().auth()
		elif mode == 'torbox.revoke_authentication':
			from apis.torbox_api import TorBoxAPI
			TorBoxAPI().revoke()
		elif mode == 'torbox.delete':
			from indexers.torbox import tb_delete
			tb_delete(_get('folder_id'), _get('media_type'))
	elif 'tmdblist_api' in mode:
		if mode == 'tmdblist_api.authenticate':
			from apis.tmdblist_api import TMDbListAPI
			TMDbListAPI().auth()
		elif mode == 'tmdblist_api.revoke_authentication':
			from apis.tmdblist_api import TMDbListAPI
			TMDbListAPI().revoke()
	elif '_cache' in mode:
		from caches import base_cache
		if mode == 'clear_cache':
			base_cache.clear_cache(_get('cache'))
		elif mode == 'clear_all_cache':
			base_cache.clear_all_cache()
		elif mode == 'clean_databases_cache':
			base_cache.clean_databases()
		elif mode == 'check_databases_integrity_cache':
			base_cache.check_databases_integrity()
	elif '_image' in mode:
		from indexers.images import Images
		Images().run(params)
	elif '_text' in mode:
		if mode == 'show_text':
			from modules.kodi_utils import show_text
			show_text(_get('heading'), _get('text', None), _get('file', None), _get('font_size', 'small'), _get('kodi_log', 'false') == 'true')
		elif mode == 'show_text_media':
			from modules.kodi_utils import show_text_media
			show_text(_get('heading'), _get('text', None), _get('file', None), _get('meta'), {})
	elif 'settings_manager.' in mode:
		from caches import settings_cache
		exec('settings_cache.%s(params)' % mode.split('.')[1])
	elif 'downloader.' in mode:
		from modules import downloader
		exec('downloader.%s(params)' % mode.split('.')[1])
	elif 'updater' in mode:
		from modules import updater
		exec('updater.%s()' % mode.split('.')[1])
	##EXTRA modes##
	elif mode == 'set_view':
		from modules.kodi_utils import set_view
		kodi_utils.set_view(_get('view_type'))
	elif mode == 'sync_settings':
		from caches.settings_cache import sync_settings
		sync_settings(params)
	elif mode == 'person_direct.search':
		from indexers.people import person_direct_search
		person_direct_search(_get('key_id') or _get('query'))
	elif mode == 'kodi_refresh':
		from modules.kodi_utils import kodi_refresh
		kodi_refresh()
	elif mode == 'refresh_widgets':
		from indexers.random_lists import refresh_widgets
		refresh_widgets()
	elif mode == 'person_data_dialog':
		from indexers.people import person_data_dialog
		person_data_dialog(params)
	elif mode == 'favorite_people':
		from indexers.people import favorite_people
		favorite_people()
	elif mode == 'manual_add_magnet_to_cloud':
		from modules.debrid import manual_add_magnet_to_cloud
		manual_add_magnet_to_cloud(params)
	elif mode == 'upload_logfile':
		from modules.kodi_utils import upload_logfile
		upload_logfile(params)
	elif mode == 'downloader':
		from modules.downloader import runner
		runner(params)
	elif mode == 'debrid.browse_packs':
		from modules.sources import Sources
		Sources().debridPacks(_get('provider'), _get('name'), _get('magnet_url'), _get('info_hash'))
	elif mode == 'open_settings':
		from modules.kodi_utils import open_settings
		open_settings()
	elif mode == 'hide_unhide_progress_items':
		from modules.watched_status import hide_unhide_progress_items
		hide_unhide_progress_items(params)
	elif mode == 'open_external_scraper_settings':
		from modules.kodi_utils import external_scraper_settings
		external_scraper_settings()
