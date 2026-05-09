from modules import kodi_utils
# from modules.kodi_utils import logger

ls, translate_path, get_setting = kodi_utils.local_string, kodi_utils.translate_path, kodi_utils.get_setting

def addon_fanart(fallback='salts_fanart.jpg'):
	fanart = get_setting('fanart_image', fallback)
	if fanart == 'salts_fanart.jpg': return kodi_utils.get_addoninfo('fanart')
	return translate_path(fanart)

def auto_resume(mediatype):
	auto_resume = get_setting('auto_resume_%s' % mediatype)
	if auto_resume == '1': return True
	if auto_resume == '2' and auto_play(mediatype): return True
	else: return False

def auto_start_salts():
	return get_setting('auto_start_salts') == 'true'

def auto_play(mediatype):
	return get_setting('auto_play_%s' % mediatype) == 'true'

def autoplay_next_episode():
	if auto_play('episode') and get_setting('autoplay_next_episode') == 'true': return True
	else: return False

def autoplay_next_check_threshold():
	return int(get_setting('autoplay_next_check_threshold', '3'))

def autoplay_next_show_window():
	return get_setting('autoplay_next_show_window') == 'true'

def autoplay_next_window_time():
	return int(get_setting('autoplay_next_window_time', '20'))

def autoplay_next_window_percentage():
	return int(get_setting('autoplay_next_window_percentage', '95'))

def autoplay_next_window_timer_method():
	return {'0': 'time', '1': 'percentage'}[get_setting('autoplay_next_window_timer_method')]

def autoplay_next_settings():
	scraper_time = int(get_setting('scraping.timeout', '30')) + 20
	threshold = autoplay_next_check_threshold()
	run_popup = autoplay_next_show_window()
	timer_method = autoplay_next_window_timer_method()
	window_time = autoplay_next_window_time() + 1
	window_percentage = 100 - autoplay_next_window_percentage()
	return {
		'scraper_time': scraper_time, 'threshold': threshold, 'run_popup': run_popup,
		'timer_method': timer_method, 'window_time': window_time, 'window_percentage': window_percentage
	}

def calendar_focus_today():
	return get_setting('trakt.calendar_focus_today') == 'true'

def calendar_sort_order():
	return int(get_setting('trakt.calendar_sort_order', '0'))

def context_menu_sort():
	return {
		'options': int(get_setting('context.options', '1')),
		'extras': int(get_setting('context.extras', '2')),
		'trakt': int(get_setting('context.trakt', '3')),
		'mdblist': int(get_setting('context.mdblist', '4')),
		'flicklist': int(get_setting('context.flicklist', '4')),
		'favorites': int(get_setting('context.favorites', '5')),
		'mark': int(get_setting('context.mark', '6')),
		'exit': int(get_setting('context.exit', '7'))
	}

def date_offset():
	return int(get_setting('datetime.offset', '0')) + 5

def default_all_episodes():
	return int(get_setting('default_all_episodes'))

def display_sleep_time():
	return 100

def download_directory(mediatype):
	if mediatype == 'movie': setting = 'movie_download_directory'
	elif mediatype == 'episode': setting = 'tvshow_download_directory'
	elif mediatype in ('thumb_url', 'image_url', 'image'): setting = 'image_download_directory'
	else: setting = 'premium_download_directory'
	if get_setting(setting) != '': return translate_path(get_setting(setting))
	else: return False

def enabled_debrids_check(debrid_service):
	enabled = get_setting('%s.enabled' % debrid_service) == 'true'
	if not enabled: return False
	authed = get_setting('%s.token' % debrid_service)
	if authed in ('', None): return False
	return True

def extras_enable_scrollbars():
	return get_setting('extras.enable_scrollbars', 'true')

def extras_exclude_non_acting():
	return get_setting('extras.exclude_non_acting_roles', 'true') == 'true'

def extras_enabled_menus():
	setting = get_setting('extras.enabled_menus')
	if setting in ('', None, 'noop', []): return []
	return [int(i) for i in setting.split(',')]

def extras_open_action(mediatype):
	return int(get_setting('extras.open_action', '0')) in {'movie': (1, 3), 'tvshow': (2, 3)}[mediatype]

def filter_by_name(scraper):
	return get_setting('%s.title_filter' % scraper, 'false') == 'true'

def get_art_provider():
	return {
		True: ('poster2', 'poster', 'fanart2', 'fanart'),
		False: ('poster', 'poster2', 'fanart', 'fanart2')
	}[False]

def get_language():
	return get_setting('meta_language', 'en')

def get_resolution():
	return (
		{'poster': 'w185', 'fanart': 'w300', 'still': 'w185', 'profile': 'w185'},
		{'poster': 'w342', 'fanart': 'w780', 'still': 'w300', 'profile': 'w342'},
		{'poster': 'w780', 'fanart': 'w1280', 'still': 'original', 'profile': 'h632'},
		{'poster': 'original', 'fanart': 'original', 'still': 'original', 'profile': 'original'}
	)[int(get_setting('image_resolutions', '2'))]

def get_rpdb_data():
	return get_setting('get_rpdb_movies') == 'true', get_setting('get_rpdb_series') == 'true'

def ignore_articles():
	return get_setting('ignore_articles') == 'true'

def include_year_in_title(mediatype):
	settings_dict = {'movie': (1, 3), 'tvshow': (2, 3)}
	setting = int(get_setting('include_year_in_title', '0'))
	return setting in settings_dict[mediatype]

def lists_sort_order(setting):
	return int(get_setting('sort.%s' % setting, '0'))

def metadata_user_info():
	tmdb_api = tmdb_api_key()
	image_resolution = get_resolution()
	meta_language = get_language()
	hide_watched = widget_hide_watched()
	rpdb_api, rpdb_theme = rpdb_api_key()
	if rpdb_api: extra_rpdb_movies, extra_rpdb_series = get_rpdb_data()
	else: extra_rpdb_movies, extra_rpdb_series = False, False
	return {
		'image_resolution': image_resolution , 'language': meta_language,
		'widget_hide_watched': hide_watched, 'tmdb_api': tmdb_api, 'rpdb_api_key': rpdb_api,
		'rpdb_theme': rpdb_theme, 'extra_rpdb_movies': extra_rpdb_movies, 'extra_rpdb_series': extra_rpdb_series
	}

def movies_directory():
	return translate_path(get_setting('movies_directory'))

def nav_jump_use_alphabet():
#	return get_setting('nav_jump') == '1'
	return int(get_setting('nav_jump', '0'))

def nextep_content_settings():
	include_unaired = get_setting('nextep.include_unaired') == 'true'
	include_unwatched = False # get_setting('nextep.include_unwatched') == 'true'
	sort_type = int(get_setting('nextep.sort_type'))
	sort_order = int(get_setting('nextep.sort_order'))
	sort_direction = sort_order == 0
	sort_key = 'salts_last_played' if sort_type == 0 else 'salts_first_aired' if sort_type == 1 else 'salts_name'
	sort_airing_today_to_top = get_setting('nextep.sort_airing_today_to_top', 'false') == 'true'
	return {
		'include_unaired': include_unaired, 'include_unwatched': include_unwatched,
		'sort_type': sort_type, 'sort_order': sort_order, 'sort_direction': sort_direction, 'sort_key': sort_key,
		'sort_airing_today_to_top': sort_airing_today_to_top
	}

def nextep_display_settings():
	include_airdate = get_setting('nextep.include_airdate') == 'true'
	return {'unaired_color': 'cyan', 'unwatched_color': 'darkgoldenrod', 'include_airdate': include_airdate}

def paginate():
	return get_setting('paginate.lists') == 'true'

def page_limit():
	return int(get_setting('page_limit', '20'))

def quality_filter(setting):
	return get_setting(setting).split(', ')

def rpdb_api_key():
	return get_setting('rpdb_api_key'), get_setting('rpdb_theme')

def store_resolved_torrent_to_cloud(debrid_service):
	return get_setting('store_torrent.%s' % debrid_service.lower()) == 'true'

def store_resolved_usenet_to_cloud(debrid_service):
	return get_setting('store_usenet.%s' % debrid_service.lower()) == 'true'

def show_specials():
	return get_setting('show_specials') == 'true'

def show_unaired():
	return get_setting('show_unaired') == 'true'

def show_unaired_watchlist():
	return get_setting('show_unaired_watchlist', 'false') == 'true'

def single_ep_display_title():
	return int(get_setting('single_ep_display', '0'))

def single_ep_format():
	return {0: '%d-%m-%Y', 1: '%Y-%m-%d', 2: '%m-%d-%Y'}[int(get_setting('single_ep_format', '1'))]

def sync_kodi_library_watchstatus():
	return get_setting('sync_kodi_library_watchstatus') == 'true'

def thumb_fanart():
	return get_setting('thumb_fanart') == 'true'

def tmdb_api_key():
#	return get_setting('tmdb_api', 'd848316a33e79095beb945a2bd2d53b1')
	return get_setting('tmdb_api')

def trakt_sync_interval():
	setting = get_setting('trakt.sync_interval', '25')
	interval = int(setting) * 60
	return setting, interval

def trakt_sync_refresh_widgets():
	return get_setting('trakt.sync_refresh_widgets') == 'true'

def trakt_token():
	return get_setting('trakt.token')

def tv_show_directory():
	return translate_path(get_setting('tv_shows_directory'))

def use_season_title():
	return get_setting('use_season_title') == 'true'

def watched_indicators():
	if not any(get_setting(i) for i in ('trakt_user', 'mdblist_user', 'flicklist_user')): return 0
	return int(get_setting('watched_indicators', '0'))

def watched_title(watched_indicators):
	return ('SALTS', 'Trakt', 'MDBList', 'FlickList')[watched_indicators]

def widget_hide_watched():
	return get_setting('widget_hide_watched') == 'true'

cloud_scrapers = ('pm_cloud', 'rd_cloud', 'tb_cloud')
default_internal_scrapers = (*cloud_scrapers, 'torboxnews')

def active_internal_scrapers():
	settings = ['provider.external']
	settings.extend(item[1] for item in (
		('pm', 'provider.pm_cloud'),
		('rd', 'provider.rd_cloud'),
		('tb', 'provider.tb_cloud'),
		('tb', 'provider.torboxnews')
	) if enabled_debrids_check(item[0]))
	active = [i.split('.')[1] for i in settings if get_setting(i) == 'true']
	return active

def check_prescrape_sources(scraper, mediatype):
	if scraper in default_internal_scrapers[:-1]: return get_setting('check.%s' % scraper) == 'true'
	if get_setting('check.%s' % scraper) == 'true' and get_setting('auto_play_%s' % mediatype) != 'true': return True
	else: return False

def debrid_enabled():
	return [i[0] for i in (
		('realdebrid', 'rd'),
		('premiumize', 'pm'),
		('torbox', 'tb')
	) if enabled_debrids_check(i[1])]

def provider_sort_ranks():
	pm_priority = int(get_setting('pm.priority', '8'))
	tb_priority = int(get_setting('tb.priority', '9'))
	rd_priority = int(get_setting('rd.priority', '10'))
	return {
		'premiumize': pm_priority, 'pm_cloud': pm_priority,
		'realdebrid': rd_priority, 'rd_cloud': rd_priority,
		'torbox': tb_priority, 'tb_cloud': tb_priority, 'torboxnews': tb_priority
	}

def sort_to_top(provider):
	return get_setting({
		'pm_cloud': 'results.sort_pmcloud_first',
		'rd_cloud': 'results.sort_rdcloud_first',
		'tb_cloud': 'results.sort_tbcloud_first'
	}[provider]) == 'true'

def scraping_settings():
	def provider_color(provider, fallback):
		return get_setting('provider.%s_colour' % provider, fallback)
	highlight_type = int(get_setting('highlight.type', '0'))
	hoster_highlight, torrent_highlight = '', ''
	debrid_cloud_highlight, folders_highlight = '', ''
	rd_highlight, pm_highlight, tb_highlight = '', '', ''
	highlight_4K, highlight_1080P, highlight_720P, highlight_SD = '', '', '', ''
	if highlight_type in (0, 1):
		if highlight_type == 0:
			hoster_highlight = get_setting('hoster.identify', 'dodgerblue')
			torrent_highlight = get_setting('torrent.identify', 'magenta')
		else:
			rd_highlight = provider_color('rd', 'seagreen')
			pm_highlight = provider_color('pm', 'orangered')
			tb_highlight = provider_color('tb', 'darkseagreen')
		debrid_cloud_highlight = provider_color('debrid_cloud', 'darkviolet')
		folders_highlight = provider_color('folders', 'darkgoldenrod')
	else:
		highlight_4K = get_setting('scraper_4k_highlight', 'magenta')
		highlight_1080P = get_setting('scraper_1080p_highlight', 'lawngreen')
		highlight_720P = get_setting('scraper_720p_highlight', 'gold')
		highlight_SD = get_setting('scraper_SD_highlight', 'lightsaltegray')
	return {
		'premiumize': pm_highlight, 'pm_cloud': debrid_cloud_highlight,
		'realdebrid': rd_highlight, 'rd_cloud': debrid_cloud_highlight,
		'torbox': tb_highlight, 'tb_cloud': debrid_cloud_highlight, 'torboxnews': debrid_cloud_highlight,
		'uncached': 'dimgray', 'highlight_type': highlight_type,
		'hoster_highlight': hoster_highlight, 'torrent_highlight': torrent_highlight,
		'4k': highlight_4K, '1080p': highlight_1080P, '720p': highlight_720P, 'sd': highlight_SD,
		'cam': highlight_SD, 'tele': highlight_SD, 'scr': highlight_SD, 'folders': folders_highlight
	}

def info_icons():
	return (
		('premiumize', 'premiumize.png'), ('pm_cloud', 'premiumize.png'),
		('realdebrid', 'realdebrid.png'), ('rd_cloud', 'realdebrid.png'),
		('torbox', 'torbox.png'), ('tb_cloud', 'torbox.png'), ('torboxnews', 'torbox.png'),
		('4k', 'flag4k.png'), ('1080p', 'flag1080p.png'), ('720p', 'flag720p.png'), ('sd', 'flagSD.png'),
		('cam', 'flagSD.png'), ('tele', 'flagSD.png'), ('scr', 'flagSD.png'), ('folders', 'folder.png')
	)

