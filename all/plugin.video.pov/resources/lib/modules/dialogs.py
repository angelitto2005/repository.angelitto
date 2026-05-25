import json
from indexers import metadata
from modules import kodi_utils, source_utils, settings
from modules.cache import clear_cache
from modules.utils import get_datetime, clean_file_name
# logger = kodi_utils.logger

ls, build_url, media_path, select_dialog = kodi_utils.local_string, kodi_utils.build_url, kodi_utils.media_path, kodi_utils.select_dialog
show_busy_dialog, hide_busy_dialog, notification, ok_dialog = kodi_utils.show_busy_dialog, kodi_utils.hide_busy_dialog, kodi_utils.notification, kodi_utils.ok_dialog
get_property, set_property, clear_property, container_refresh = kodi_utils.get_property, kodi_utils.set_property, kodi_utils.clear_property, kodi_utils.container_refresh
execute_builtin, confirm_dialog, container_content, sleep = kodi_utils.execute_builtin, kodi_utils.confirm_dialog, kodi_utils.container_content, kodi_utils.sleep
get_setting, set_setting = kodi_utils.get_setting, kodi_utils.set_setting

def imdb_videos_choice(videos, poster):
	try: videos = json.loads(videos)
	except: pass
	videos.sort(key=lambda x: x['quality_rank'])
	list_items = [{'line1': i['quality'], 'icon': poster} for i in videos]
	kwargs = {'items': json.dumps(list_items), 'heading': ls(32241)}
	return select_dialog([i['url'] for i in videos], **kwargs)

def trailer_choice(mediatype, poster, tmdb_id, trailer_url, all_trailers=None):
	if settings.get_language() != 'en' and not trailer_url and not all_trailers:
		from indexers.tmdb_api import tmdb_media_videos
		try: all_trailers = tmdb_media_videos(mediatype, tmdb_id)['results']
		except: pass
	if not all_trailers: return trailer_url
	if len(all_trailers) > 1:
		all_trailers.sort(key=lambda k: k.get('published_at'))
		list_items = [
			{'line1': clean_file_name(i['name']),
			 'line2': '%s (%s)' % (i['type'], i.get('site') or 'NA'),
			 'icon': poster}
			for i in all_trailers
		]
		kwargs = {'items': json.dumps(list_items), 'heading': ls(32606), 'multi_line': 'true'}
		video_id = select_dialog([i['key'] for i in all_trailers], **kwargs)
	else: video_id = next(iter(all_trailers), {}).get('key')
	if video_id is None: trailer_url = 'canceled'
	else: trailer_url = 'plugin://plugin.video.youtube/play/?video_id=%s' % video_id
	return trailer_url

def genres_choice(mediatype, genres, poster, return_genres=False):
	from modules.meta_lists import movie_genres, tvshow_genres
	def _process_dicts(genre_str, _dict):
		final_genres_list = []
		append = final_genres_list.append
		for key, value in _dict.items():
			if key in genre_str: append({'genre': key, 'value': value})
		return final_genres_list
	if mediatype in ('movie', 'movies'):
		genre_action, meta_type, action = movie_genres, 'movie', 'tmdb_movies_genres'
	else: genre_action, meta_type, action = tvshow_genres, 'tvshow', 'tmdb_tv_genres'
	genre_list = _process_dicts(genres, genre_action)
	if return_genres: return genre_list
	if len(genre_list) == 0: return notification(32760, 1500)
	mode = 'build_%s_list' % meta_type
	choices = [{'mode': mode, 'action': action, 'genre_id': i['value'][0]} for i in genre_list]
	list_items = [{'line1': i['genre'], 'icon': poster} for i in genre_list]
	kwargs = {'items': json.dumps(list_items), 'heading': ls(32470)}
	return select_dialog(choices, **kwargs)

def trakt_manager_choice(params):
	if not get_setting('trakt_user', ''): return notification(32760)
	from indexers import trakt_api
	heading = ls(32198).replace('[B]', '').replace('[/B]', '')
	icon = media_path('trakt.png')
	choices = []
	choices += [
		((item['ids']['trakt'], item['user']['ids']['slug'], item['ids']['slug']),
		 item['name'],
		 '%s items' % item['item_count'])
		for item in trakt_api.trakt_get_lists('my_lists')
	]
	choices += [(i.lower(), '[I]%s[/I]' % i, '') for i in (ls(32499), ls(32453), ls(32500))]
	if params['mediatype'] == 'tvshow': choices += [('dropped', 'Toggle Dropped', '')]
	list_items = [{'line1': item[1], 'line2': item[2], 'icon': icon} for item in choices]
	kwargs = {'items': json.dumps(list_items), 'heading': heading, 'multi_line': 'true'}
	choice = select_dialog([(i[0], i[1]) for i in choices], **kwargs)
	if choice is None: return
	add_str, rem_str = 'Add to %s?' % choice[1], 'Remove from %s?' % choice[1]
	if 'dropped' in choice[0]:
		return trakt_api.hide_unhide_trakt_items(params['tmdb_id'], 'shows', params['imdb_id'], 'dropped')
	if 'watchlist' in choice[0] or 'favorites' in choice[0] or 'collection' in choice[0]:
		list_items = trakt_api.trakt_fetch_collection_watchlist(choice[0], params['mediatype'])
		action = False if int(params['tmdb_id']) in {i['media_ids']['tmdb'] for i in list_items} else True
		data = [{'ids': {'tmdb': int(params['tmdb_id'])}}]
		data = {'shows' if params['mediatype'] == 'tvshow' else 'movies': data}
		if not action:
			if not confirm_dialog(text=rem_str, top_space=True): return
			return trakt_api.remove_from_sync(choice[0], data)
		else: return trakt_api.add_to_sync(choice[0], data)
	list_items = {
		i['movie']['ids']['tmdb'] if i['type'] == 'movie' else i['show']['ids']['tmdb']
		for i in trakt_api.get_trakt_list_contents('my_lists', *choice[0])
	}
	action = False if int(params['tmdb_id']) in list_items else True
	data = {'shows' if params['mediatype'] == 'tvshow' else 'movies': [{'ids': {'tmdb': int(params['tmdb_id'])}}]}
	if not action:
		if not confirm_dialog(text=rem_str, top_space=True): return
		trakt_api.remove_from_list(choice[0][1], choice[0][2], data)
	else: trakt_api.add_to_list(choice[0][1], choice[0][2], data)

def mdbl_manager_choice(params):
	if not get_setting('mdblist_user', ''): return notification(32760)
	from indexers import mdblist_api
	heading = ls(32200).replace('[B]', '').replace('[/B]', '')
	icon = media_path('mdblist.png')
	choices = []
	choices += [
		(str(item['id']), item['name'], '%s items' % item['items'])
		for item in mdblist_api.mdbl_get_lists('my_lists') if not item['dynamic']
	]
	choices += [(i.lower(), '[I]%s[/I]' % i, '') for i in (ls(32499), ls(32500))]
	if params['mediatype'] == 'tvshow': choices += [('dropped', 'Toggle Dropped', '')]
	list_items = [{'line1': item[1], 'line2': item[2], 'icon': icon} for item in choices]
	kwargs = {'items': json.dumps(list_items), 'heading': heading, 'multi_line': 'true'}
	choice = select_dialog([(i[0], i[1]) for i in choices], **kwargs)
	if choice is None: return
	add_str, rem_str = 'Add to %s?' % choice[1], 'Remove from %s?' % choice[1]
	if 'dropped' in choice[0]:
		return mdblist_api.hide_unhide_mdbl_items(params['tmdb_id'], 'shows', params['imdb_id'], 'dropped')
	if 'collection' in choice[0]:
		list_items = mdblist_api.mdblist_collection('all', None, '')
		action = False if int(params['tmdb_id']) in {i['id'] for i in list_items} else True
		data = [{'ids': {'tmdb': int(params['tmdb_id'])}}]
		data = {'shows' if params['mediatype'] == 'tvshow' else 'movies': data}
		if not action:
			if not confirm_dialog(text=rem_str, top_space=True): return
			return mdblist_api.remove_from_collection(data)
		else: return mdblist_api.add_to_collection(data)
	if 'watchlist' in choice[0]: list_items = mdblist_api.mdblist_watchlist('all', None, '')
	else: list_items = mdblist_api.get_mdbl_list_contents('my_lists', choice[0])
	action = False if int(params['tmdb_id']) in {i['id'] for i in list_items} else True
	data = {'shows' if params['mediatype'] == 'tvshow' else 'movies': [{'tmdb': int(params['tmdb_id'])}]}
	if not action:
		if not confirm_dialog(text=rem_str, top_space=True): return
		mdblist_api.remove_from_list(choice[0], data)
	else: mdblist_api.add_to_list(choice[0], data)

def tmdb_manager_choice(params):
	if not get_setting('tmdb.token', ''): return notification(32760)
	from indexers import tmdb_api
	image_resolution, tmdb_image_base = settings.get_resolution(), tmdb_api.tmdb_image_base
	heading = ls(tmdb_api.tmdb_list_heading).replace('[B]', '').replace('[/B]', '')
	icon = media_path('tmdb.png')
	list_name = params.get('trakt_list_name') or params.get('mdbl_list_name') or ''
	choices = []
	choices += [
		(str(item['id']), item['name'], '%s items' % item['number_of_items'],
		 tmdb_image_base % (image_resolution['poster'], item['poster_path']) if item['poster_path'] else icon)
		for item in tmdb_api.user_lists()
	]
	if not list_name:
		choices += [(i.lower(), '[I]%s[/I]' % i, '', icon) for i in (ls(32453), ls(32500))]
	choices += [('clear', 'Clear list cache', '', icon), ('new', 'Create a new list', list_name, icon)]
	if not choices: return
	list_items = [{'line1': item[1], 'line2': item[2], 'icon': item[3]} for item in choices]
	kwargs = {'items': json.dumps(list_items), 'heading': heading, 'multi_line': 'true'}
	choice = select_dialog([(i[0], i[1]) for i in choices], **kwargs)
	if choice is None: return
	if 'clear' in choice[0]:
		tmdb_api.clear_tmdbl_cache()
		return tmdb_manager_choice(params)
	if 'new' in choice[0]:
		show_busy_dialog()
		try:
			result = tmdb_api.list_create(list_name)
			if result is None: return tmdb_manager_choice(params)
			if not result['success']: raise Exception
		except: return notification(32574)
		finally: hide_busy_dialog()
		tmdb_api.clear_tmdbl_cache()
		return tmdb_manager_choice(params)
	if 'trakt_list_id' in params or 'mdbl_list_id' in params:
		function = tmdb_api.import_trakt_list if 'trakt_list_id' in params else tmdb_api.import_mdbl_list
		return function({**params, 'list_id': choice[0]})
	add_str, rem_str = 'Add to %s?' % choice[1], 'Remove from %s?' % choice[1]
	params['mediatype'] = 'tv' if params['mediatype'] == 'tvshow' else 'movie'
	if 'watchlist' in choice[0] or 'favorites' in choice[0]:
		if 'watchlist' == choice[0]:
			list_items = tmdb_api.watchlist(params['mediatype'])
		else: list_items = tmdb_api.favorites(params['mediatype'])
		list_type = 'favorite' if choice[0] == 'favorites' else 'watchlist'
		action = False if int(params['tmdb_id']) in {i['id'] for i in list_items} else True
		data = {'media_type': params['mediatype'], 'media_id': params['tmdb_id'], list_type: action}
		if not action and not confirm_dialog(text=rem_str, top_space=True): return
		if tmdb_api.add_to_watchlist_favorites(data, list_type)['success']:
			tmdb_api.clear_tmdbl_cache()
			if not action: container_refresh()
			return notification(32576)
		else: return notification(32574)
	data = {'items': [{'media_type': params['mediatype'], 'media_id': params['tmdb_id']}]}
	status = tmdb_api.list_status(choice[0], params['mediatype'], params['tmdb_id'])
	if status and status['success']:
		if not confirm_dialog(text=rem_str, top_space=True): return
		action, function = False, tmdb_api.list_remove_items
	else: action, function = True, tmdb_api.list_add_items
	if function(choice[0], data)['success']:
		tmdb_api.clear_tmdbl_cache()
		if not action: container_refresh()
		notification(32576)
	else: notification(32574)

def random_choice(choice, meta):
	tmdb_id = meta.get('tmdb_id')
	if not tmdb_id: return
	from modules.episode_tools import get_random_episode
	from modules.sources import Sources
	meta, play_params = get_random_episode(tmdb_id, True if choice == 'play_random_continual' else False)
	if not play_params: return notification(32760)
	Sources.factory(play_params)

def playback_choice(content, poster, meta):
	items = [
		('clear_and_rescrape', ls(32014)),
		('rescrape_with_disabled', ls(32006)),
		('scrape_with_filters_ignored', ls(32807)),
		('scrape_with_custom_values', ls(32135))
	]
	list_items = [{'line1': i[1], 'icon': poster} for i in items]
	kwargs = {'items': json.dumps(list_items), 'heading': ls(32174)}
	choice = select_dialog([i[0] for i in items], **kwargs)
	if choice is None: return
	if choice == 'clear_and_rescrape': clear_and_rescrape(content, meta)
	elif choice == 'rescrape_with_disabled': rescrape_with_disabled(content, meta)
	elif choice == 'scrape_with_filters_ignored': scrape_with_filters_ignored(content, meta)
	else: scrape_with_custom_values(content, meta)

def set_quality_choice(quality_setting):
	include = ls(32188)
	dl = ['%s SD' % include, '%s 720p' % include, '%s 1080p' % include, '%s 4K' % include]
	fl = ['SD', '720p', '1080p', '4K']
	try: preselect = [fl.index(i) for i in get_setting(quality_setting).split(', ')]
	except: preselect = []
	list_items = [{'line1': item} for item in dl]
	kwargs = {'items': json.dumps(list_items), 'heading': 'POV', 'multi_choice': 'true', 'preselect': preselect}
	choice = select_dialog(fl, **kwargs)
	if choice is None: return
	if choice == []:
		ok_dialog(text=32574, top_space=True)
		return set_quality_choice(quality_setting)
	set_setting(quality_setting, ', '.join(choice))

def extras_lists_choice():
	fl = [2050, 2051, 2052, 2053, 2054, 2055, 2056, 2057, 2058, 2059, 2060, 2061, 2062]
	dl = [
		ls(32664), ls(32503), ls(32607), ls(32984), ls(32986), ls(32989), ls(32531), ls(32616), ls(32617),
		'%s %s' % (ls(32612), ls(32543)), '%s %s' % (ls(32612), ls(32470)),
		'%s %s' % (ls(32612), ls(32480)), '%s %s' % (ls(32612), ls(32499))
	]
	try: preselect = [fl.index(i) for i in settings.extras_enabled_menus()]
	except: preselect = []
	list_items = [{'line1': item} for item in dl]
	kwargs = {'items': json.dumps(list_items), 'heading': 'POV', 'multi_choice': 'true', 'preselect': preselect}
	selection = select_dialog(fl, **kwargs)
	if selection == []: return set_setting('extras.enabled_menus', 'noop')
	elif selection is None: return
	selection = [str(i) for i in selection]
	set_setting('extras.enabled_menus', ','.join(selection))

def set_language_filter_choice(filter_setting):
	from modules.meta_lists import meta_languages
	dl = list(k for k, v in meta_languages.items() if v['long'])
	fl = list(v['long'] for v in meta_languages.values() if v['long'])
	try: preselect = [fl.index(i) for i in get_setting(filter_setting).split(', ')]
	except: preselect = []
	list_items = [{'line1': item} for item in dl]
	kwargs = {'items': json.dumps(list_items), 'heading': 'POV', 'multi_choice': 'true', 'preselect': preselect}
	choice = select_dialog(fl, **kwargs)
	if choice is None: return
	if choice == []: return set_setting(filter_setting, 'eng')
	set_setting(filter_setting, ', '.join(choice))

def results_sorting_choice():
	quality, provider, size = ls(32241), ls(32583), ls(32584)
	choices = [
		('%s, %s, %s' % (quality, provider, size), '0'), ('%s, %s, %s' % (quality, size, provider), '1'),
		('%s, %s, %s' % (provider, quality, size), '2'), ('%s, %s, %s' % (provider, size, quality), '3'),
		('%s, %s, %s' % (size, quality, provider), '4'), ('%s, %s, %s' % (size, provider, quality), '5')
	]
	list_items = [{'line1': item[0]} for item in choices]
	kwargs = {'items': json.dumps(list_items), 'heading': 'POV'}
	choice = select_dialog(choices, **kwargs)
	if choice:
		set_setting('results.sort_order_display', choice[0])
		set_setting('results.sort_order', choice[1])

def results_highlights_choice():
	choices = [(ls(32240), '0'), (ls(32583), '1'), (ls(32241), '2')]
	list_items = [{'line1': item[0]} for item in choices]
	kwargs = {'items': json.dumps(list_items), 'heading': 'POV'}
	choice = select_dialog([i[1] for i in choices], **kwargs)
	if choice: return set_setting('highlight.type', choice)

def results_layout_choice():
	xml_choices = [
		'List Default', 'List Contrast Default',
		'InfoList Default', 'InfoList Contrast Default',
		'WideList Default', 'WideList Contrast Default'
	]
	list_items = [{'line1': item} for item in xml_choices]
	kwargs = {'items': json.dumps(list_items), 'heading': 'POV'}
	choice = select_dialog(xml_choices, **kwargs)
	if choice in xml_choices: set_setting('results.xml_style', choice)

def set_subtitle_choice():
	choices = [(ls(32192), '0'), (ls(32193), '1'), (ls(32027), '2')]
	list_items = [{'line1': item[0]} for item in choices]
	kwargs = {'items': json.dumps(list_items), 'heading': 'POV'}
	choice = select_dialog([i[1] for i in choices], **kwargs)
	if choice: return set_setting('subtitles.subs_action', choice)

def scraper_dialog_color_choice(setting):
	setting = 'int_dialog_highlight' if setting == 'internal' else 'ext_dialog_highlight'
	chosen_color = color_choice()
	if chosen_color: set_setting(setting, chosen_color)

def scraper_quality_color_choice(setting):
	chosen_color = color_choice()
	if chosen_color: set_setting(setting, chosen_color)

def scraper_color_choice(setting):
	choices = [
		('easynews', 'provider.easynews_colour'),
		('debrid_cloud', 'provider.debrid_cloud_colour'),
		('hoster', 'hoster.identify'),
		('torrent', 'torrent.identify'),
		('rd', 'provider.rd_colour'),
		('pm', 'provider.pm_colour'),
		('ad', 'provider.ad_colour'),
		('tb', 'provider.tb_colour'),
		('oc', 'provider.oc_colour'),
		('free', 'provider.free_colour')
	]
	setting = [i[1] for i in choices if i[0] == setting][0]
	chosen_color = color_choice()
	if chosen_color: set_setting(setting, chosen_color)

def color_choice(msg_dialog='POV', no_color=False):
	from modules.meta_lists import meta_colors
	color_chart = meta_colors
	color_display = ['[COLOR %s]%s[/COLOR]' % (i, i.capitalize()) for i in color_chart]
	if no_color:
		color_chart.insert(0, 'No Color')
		color_display.insert(0, 'No Color')
	list_items = [{'line1': item} for item in color_display]
	kwargs = {'items': json.dumps(list_items), 'heading': 'POV'}
	choice = select_dialog(color_chart, **kwargs)
	if choice is None: return
	return choice

def meta_language_choice():
	from modules.meta_lists import meta_languages
	langs = [{'iso': v['iso'], 'name': k} for k, v in meta_languages.items()]
	list_items = [{'line1': i['name'], 'line2': i['iso']} for i in langs]
	kwargs = {'items': json.dumps(list_items), 'heading': ls(32145), 'multi_line': 'true'}
	list_choose = select_dialog(langs, **kwargs)
	if list_choose is None: return None
	chosen_language, chosen_language_display = list_choose['iso'], list_choose['name']
	set_setting('meta_language', chosen_language)
	set_setting('meta_language_display', chosen_language_display)
	clear_cache('meta', silent=True)

def favorites_choice(params):
	from caches.favorites_cache import Favorites
	favorites = Favorites()
	icon = media_path('favorites.png')
	if params.get('cache'):
		list = [('%s %s' % (ls(32028), ls(32453)), 'movie'), ('%s %s' % (ls(32029), ls(32453)), 'tvshow')]
		list_items = [{'line1': item[0], 'icon': icon} for item in list]
		kwargs = {'items': json.dumps(list_items), 'heading': ls(32453)}
		mediatype = select_dialog([item[1] for item in list], **kwargs)
		if mediatype is None: return
		if not favorites.clear(mediatype): notification(32574)
	else:
		mediatype, tmdb_id, title = params['mediatype'], params['tmdb_id'], params['title']
		current_favorites, refresh = favorites.get(mediatype), False
		if tmdb_id in {i['tmdb_id'] for i in current_favorites}:
			action, refresh = favorites.remove, True
			text = '%s POV %s?' % (ls(32603), ls(32453))
		else: action, text = favorites.add, '%s POV %s?' % (ls(32602), ls(32453))
		if not confirm_dialog(text='%s[CR][CR]%s' % (title, text)): return
		notification(32576) if action(mediatype, tmdb_id, title) else notification(32574)
		if refresh: container_refresh()

def dropped_choice(params):
	from caches.favorites_cache import Dropped
	dropped = Dropped()
	mediatype, tmdb_id, title = params['mediatype'], params['tmdb_id'], params['title']
	current_favorites = dropped.get(mediatype)
	if tmdb_id in {int(i['tmdb_id']) for i in current_favorites}:
		action, text = dropped.remove, '%s POV %s?' % (ls(32603), 'Dropped')
	else: action, text = dropped.add, '%s POV %s?' % (ls(32602), 'Dropped')
	if not confirm_dialog(text='%s[CR][CR]%s' % (title, text)): return
	notification(32576) if action(mediatype, tmdb_id, title) else notification(32574)
	container_refresh()

def options_menu(params, meta=None):
	def _builder():
		for item in listing:
			kwargs = {'line1': item[1], 'line2': item[2] or item[1]}
			if len(item) == 4: kwargs['icon'] = item[3]
			yield kwargs
	is_widget = params.get('is_widget', 'false').lower() == 'true'
	content = params.get('content') or params.get('mediatype') or container_content()[:-1]
	season, episode = params.get('season'), params.get('episode')
	if not meta:
		function = metadata.movie_meta if content == 'movie' else metadata.tvshow_meta
		meta = function('tmdb_id', params['tmdb_id'], settings.metadata_user_info(), get_datetime())
	on_str, off_str, currently_str, open_str, settings_str = ls(32090), ls(32027), ls(32598), ls(32641), ls(32247)
	base_str1, base_str2 = '%s%s', '%s: [B]%s[/B]' % (currently_str, '%s')
	scraper_options_str = '%s %s' % (ls(32533), ls(32841))
	multi_line = 'true' if content in ('movie', 'episode') else 'false'
	watched_indicators = settings.watched_indicators()
	results_xml_style_status = settings.results_xml_style()
	if settings.display_uncached_torrents(): uncached_torrents_status, uncached_torrents_toggle = (on_str, 'false')
	else: uncached_torrents_status, uncached_torrents_toggle = (off_str, 'true')
	listing = (
		('scrape_from_episode_group', 'Scrape From Episode Group', scraper_options_str, meta['poster']) if content == 'episode' else None,
		('clear_and_rescrape', ls(32014), scraper_options_str, meta['poster']) if multi_line == 'true' else None,
		('rescrape_with_disabled', ls(32006), scraper_options_str, meta['poster']) if multi_line == 'true' else None,
		('scrape_with_filters_ignored', ls(32807), scraper_options_str, meta['poster']) if multi_line == 'true' else None,
		('scrape_with_custom_values', ls(32135), scraper_options_str, meta['poster']) if multi_line == 'true' else None,
		('play_random', ls(32541), '', meta['poster']) if content in ('tvshow') and meta else None,
		('play_random_continual', ls(32542), '', meta['poster']) if content in ('tvshow') and meta else None,
		('clear_scrapers_cache', ls(32637), '') if content in ('movie', 'episode') else None,
		('open_external_scrapers_choice', '%s %s' % (ls(32118), ls(32513)), ''),
		('toggle_torrents_display_uncached', base_str1 % ('', ls(32160)), base_str2 % uncached_torrents_status) if multi_line == 'true' else None,
		('set_results_xml_display', base_str1 % ('', '%s %s' % (ls(32139), ls(32140))), base_str2 % results_xml_style_status) if multi_line == 'true' else None,
		('dropped_choice', 'Toggle Dropped', '') if watched_indicators == 0 and content in ('tvshow') else None,
		('clear_trakt_cache', ls(32497) % ls(32037), '') if watched_indicators == 1 else None,
		('clear_mdbl_cache', ls(32497) % 'MDBList', '') if watched_indicators == 2 else None,
		('clear_media_cache', ls(32604) % (ls(32028) if content in ('movie') else ls(32029)), '', meta['poster']) if content in ('movie', 'tvshow') and meta else None,
		('open_pov_settings', '%s %s %s' % (open_str, ls(32036), settings_str), ''),
		('reload_widgets', 'POV: Refresh Widgets', '') if is_widget else None
	)
	listing = [item for item in listing if item]
	list_items = list(_builder())
	heading = ls(32646).replace('[B]', '').replace('[/B]', '')
	kwargs = {'items': json.dumps(list_items), 'heading': heading, 'multi_line': multi_line}
	choice = select_dialog([i[0] for i in listing], **kwargs)
	if   choice in (None, 'save_and_exit'): return
	elif choice == 'clear_and_rescrape': return clear_and_rescrape(content, meta, season, episode)
	elif choice == 'rescrape_with_disabled': return rescrape_with_disabled(content, meta, season, episode)
	elif choice == 'scrape_with_filters_ignored': return scrape_with_filters_ignored(content, meta, season, episode)
	elif choice == 'scrape_with_custom_values': return scrape_with_custom_values(content, meta, season, episode)
	elif choice == 'scrape_from_episode_group': return scrape_from_episode_group(meta, season, episode)
	elif choice == 'play_random': return random_choice(choice, meta)
	elif choice == 'play_random_continual': return random_choice(choice, meta)
	elif choice == 'clear_scrapers_cache': return clear_scrapers_cache()
	elif choice == 'open_external_scrapers_choice': return source_utils.enable_disable('all')
	elif choice == 'toggle_torrents_display_uncached': set_setting('torrent.display.uncached', uncached_torrents_toggle)
	elif choice == 'set_results_xml_display': results_layout_choice()
	elif choice == 'dropped_choice': return dropped_choice(meta)
	elif choice == 'clear_trakt_cache': return clear_cache('trakt')
	elif choice == 'clear_mdbl_cache': return clear_cache('mdblist')
	elif choice == 'clear_media_cache': return refresh_cached_meta(meta)
	elif choice == 'open_pov_settings': return kodi_utils.open_settings('0.0')
#	elif choice == 'reload_widgets': return kodi_utils.widget_refresh()
	elif choice == 'reload_widgets': return execute_builtin('ReloadSkin()')
	if   choice in ('clear_trakt_cache', 'clear_mdbl_cache'): container_refresh()
	options_menu(params, meta=meta)

def extras_menu(params):
	from windows import open_window
	function = metadata.movie_meta if params['mediatype'] == 'movie' else metadata.tvshow_meta
	meta = function('tmdb_id', params['tmdb_id'], settings.metadata_user_info(), get_datetime())
	open_window(
		('windows.extras', 'Extras'),
		'extras.xml',
		meta=meta,
		is_widget=params.get('is_widget', 'false'),
		is_home=params.get('is_home', 'false')
	)

def refresh_cached_meta(meta):
	from caches.meta_cache import MetaCache
	try:
		metacache = MetaCache()
		mediatype, tmdb_id = meta['mediatype'], meta['tmdb_id']
		if mediatype == 'tvshow':
			total_seasons = meta.get('total_seasons')
			metacache.delete_all_seasons_memory_cache(tmdb_id, total_seasons)
		metacache.delete(mediatype, 'tmdb_id', tmdb_id, meta)
		notification(32576, 1500)
		container_refresh()
	except: notification(32574)

def build_navigate_to_page(params):
	use_alphabet = settings.nav_jump_use_alphabet() == 2
	icon = media_path('item_jump.png')
	mediatype = params.get('mediatype')
	def _builder(use_alphabet):
		for i in start_list:
			if use_alphabet: line1, line2 = i.upper(), ls(32821) % (mediatype, i.upper())
			else: line1, line2 = '%s %s' % ('Page', i), ls(32822) % i
			yield {'line1': line1, 'line2': line2, 'icon': icon}
	if use_alphabet:
		start_list = [chr(i) for i in range(97,123)]
	else:
		start_list = [str(i) for i in range(1, int(params.get('total_pages'))+1)]
		start_list.remove(params.get('current_page'))
	list_items = list(_builder(use_alphabet))
	kwargs = {'items': json.dumps(list_items), 'heading': 'POV'}
	new_start = select_dialog(start_list, **kwargs)
	sleep(100)
	if new_start is None: return
	if use_alphabet: new_page, new_letter = '', new_start
	else: new_page, new_letter = new_start, None
	url_params = {'mode': params.get('transfer_mode', ''), 'action': params.get('transfer_action', ''), 'new_page': new_page, 'new_letter': new_letter,
				'mediatype': params.get('mediatype', ''), 'query': params.get('query', ''), 'actor_id': params.get('actor_id', ''),
				'user': params.get('user', ''), 'slug': params.get('slug', ''), 'list_id': params.get('list_id', ''), 'name': params.get('name', '')}
	execute_builtin('Container.Update(%s)' % build_url(url_params))

def clear_scrapers_cache(silent=False):
	for item in ('internal_scrapers', 'external_scrapers'): clear_cache(item, silent=True)
	if not silent: notification(32576)

def clear_and_rescrape(mediatype, meta, season=None, episode=None):
	from caches.providers_cache import ExternalProvidersCache
	from modules.sources import Sources
	show_busy_dialog()
	deleted = ExternalProvidersCache().delete_cache_single(mediatype, str(meta['tmdb_id']))
	hide_busy_dialog()
	if not deleted: return notification(32574)
	play_params = {'mode': 'play_media', 'tmdb_id': meta['tmdb_id'], 'autoplay': 'false'}
	if mediatype == 'movie': play_params.update({'mediatype': 'movie'})
	else: play_params.update({'mediatype': 'episode', 'season': season, 'episode': episode})
	Sources().source_select(play_params)

def rescrape_with_disabled(mediatype, meta, season=None, episode=None):
	from modules.sources import Sources
	play_params = {'mode': 'play_media', 'tmdb_id': meta['tmdb_id'], 'autoplay': 'false', 'disabled_ignored': 'true', 'prescrape': 'false'}
	if mediatype == 'movie': play_params.update({'mediatype': 'movie'})
	else: play_params.update({'mediatype': 'episode', 'season': season, 'episode': episode})
	Sources().source_select(play_params)

def scrape_with_filters_ignored(mediatype, meta, season=None, episode=None):
	from modules.sources import Sources
	play_params = {'mode': 'play_media', 'tmdb_id': meta['tmdb_id'], 'autoplay': 'false', 'ignore_scrape_filters': 'true'}
	if mediatype == 'movie': play_params.update({'mediatype': 'movie'})
	else: play_params.update({'mediatype': 'episode', 'season': season, 'episode': episode})
	set_property('fs_filterless_search', 'true')
	Sources().source_select(play_params)

def scrape_with_custom_values(mediatype, meta, season=None, episode=None):
	from windows import open_window
	from modules.sources import Sources
	play_params = {'mode': 'play_media', 'tmdb_id': meta['tmdb_id'], 'autoplay': 'false'}
	if mediatype in ('movie', 'movies'): play_params.update({'mediatype': 'movie'})
	else: play_params.update({'mediatype': 'episode', 'season': season, 'episode': episode})
	custom_title = kodi_utils.dialog.input(ls(32228), defaultt=meta['title'])
	if not custom_title: return
	play_params['custom_title'] = custom_title
	if mediatype in ('movie', 'movies'):
		custom_year = kodi_utils.dialog.numeric(0, '%s (%s)' % (ls(32543), ls(32669)), defaultt=str(meta['year']))
		if custom_year: play_params.update({'custom_year': custom_year})
	else:
		custom_season = kodi_utils.dialog.numeric(0, '%s (%s)' % (ls(32537).title(), ls(32669)), defaultt=str(season))
		custom_episode = kodi_utils.dialog.numeric(0, '%s (%s)' % (ls(32203).title(), ls(32669)), defaultt=str(episode))
		if custom_season and custom_episode: play_params.update({'custom_season': custom_season, 'custom_episode': custom_episode})
	kwargs = {'meta': meta, 'enable_buttons': True, 'true_button': ls(32824), 'false_button': ls(32828), 'focus_button': 11}
	choice = open_window(('windows.progress', 'ProgressMedia'), 'progress_media.xml', text='%s?' % ls(32006), **kwargs)
	if choice is None: return
	if choice: play_params['disabled_ignored'] = 'true'
	choice = open_window(('windows.progress', 'ProgressMedia'), 'progress_media.xml', text=ls(32808), **kwargs)
	if choice is None: return
	if choice:
		play_params['ignore_scrape_filters'] = 'true'
		set_property('fs_filterless_search', 'true')
	Sources().source_select(play_params)

def scrape_from_episode_group(meta, season, episode):
	from indexers.tmdb_api import episode_groups, episode_group_details
	from modules.sources import Sources
	tmdb_id, heading, poster = meta['tmdb_id'], meta['tvshowtitle'], meta['poster']
	groups = episode_groups(tmdb_id)
	choices = [
		(item['id'],
		 '%s (%s)' % (item['name'], item['type']),
		 '%s Groups, %s Episodes' % (item['group_count'], item['episode_count']))
		for item in groups
	]
	if not choices: return notification(32760)
	list_items = [{'line1': item[1], 'line2': item[2], 'icon': poster} for item in choices]
	kwargs = {'items': json.dumps(list_items), 'heading': heading, 'enumerate': 'true', 'multi_line': 'true'}
	choice = select_dialog([i[0] for i in choices], **kwargs)
	if choice is None: return
	episodes = episode_group_details(choice)
	if not episodes: return notification(32760)
	episodes = [
		{**episode, 'custom_episode': episode['order'] + 1, 'custom_season': group['order'],
		'custom_name': f"S{group['order']}xE{episode['order'] + 1:02d} - {episode['name']}",
		'custom_title': f"S{episode['season_number']}xE{episode['episode_number']:02d} - {episode['name']}"}
		for group in episodes for episode in group['episodes']
	]
	index = next((
		episodes.index(i) for i in episodes
		if i['season_number'] == int(season) and i['episode_number'] == int(episode)
	), None)
	if index is not None:
		heading = episodes[index]['name']
		episodes, preselect = episodes[index:] + episodes[:index], [0]
	else: heading, preselect = meta['title'], []
	choices = [(item['custom_season'], item['custom_episode'], item['custom_name'], item['custom_title']) for item in episodes]
	if not choices: return
	list_items = [{'line1': item[2], 'line2': item[3], 'icon': poster} for item in choices]
	kwargs = {'items': json.dumps(list_items), 'heading': heading, 'multi_line': 'true', 'preselect': preselect}
	choice = select_dialog([(i[0], i[1]) for i in choices], **kwargs)
	if choice is None: return
	play_params = {'mode': 'play_media', 'tmdb_id': tmdb_id, 'mediatype': 'episode', 'season': season, 'episode': episode}
	play_params.update({'custom_season': choice[0], 'custom_episode': choice[1]})
	Sources().source_select(play_params)

