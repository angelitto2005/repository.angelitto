import json
from indexers import metadata
from modules import kodi_utils, settings
from modules.cache import clear_cache
from modules.utils import get_datetime, safe_string
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
			{'line1': safe_string(i['name']),
			 'line2': '%s (%s)' % (i['type'], i.get('site') or 'NA'),
			 'icon': poster}
			for i in all_trailers
		]
		kwargs = {'items': json.dumps(list_items), 'heading': ls(32606)}
		video_id = select_dialog([i['key'] for i in all_trailers], **kwargs)
	else: video_id = next(iter(all_trailers), {}).get('key')
	if video_id is None: trailer_url = 'canceled'
	else: trailer_url = 'plugin://plugin.video.youtube/play/?video_id=%s' % video_id
	return trailer_url

def genres_choice(mediatype, genres, poster, return_genres=False):
	from modules.meta_lists import movie_genres, tvshow_genres
	if mediatype in ('movie', 'movies'):
		genre_action, meta_type, action = movie_genres, 'movie', 'tmdb_movies_genres'
	else: genre_action, meta_type, action = tvshow_genres, 'tvshow', 'tmdb_tv_genres'
	genre_list = [{'genre': k, 'value': v} for k, v in genre_action.items() if k in genres]
	if return_genres: return genre_list
	if len(genre_list) == 0: return notification(32760, 1500)
	mode = 'build_%s_list' % meta_type
	choices = [{'mode': mode, 'action': action, 'genre_id': i['value'][0]} for i in genre_list]
	list_items = [{'line1': i['genre'], 'icon': poster} for i in genre_list]
	kwargs = {'items': json.dumps(list_items), 'heading': ls(32470)}
	return select_dialog(choices, **kwargs)

def browse_choice(meta, is_widget=False):
	tmdb_id = meta.get('tmdb_id')
	if not tmdb_id: return
	container_update = ('Container.Update(%s)', 'ActivateWindow(Videos,%s,return)')[is_widget]
	url_params = {'mode': 'build_season_list', 'tmdb_id': tmdb_id}
	execute_builtin(container_update % build_url(url_params))

def random_choice(choice, meta):
	tmdb_id = meta.get('tmdb_id')
	if not tmdb_id: return
	from modules.episode_tools import get_random_episode
	from modules.sources import Sources
	continual = True if choice == 'play_random_continual' else False
	meta, play_params = get_random_episode(tmdb_id, continual)
	if not play_params: return notification(32760)
	Sources.factory(play_params)

def playback_choice(content, poster, meta):
	items = [
		('clear_and_rescrape', ls(32014)),          ('rescrape_with_disabled', ls(32006)),
		('scrape_with_filters_ignored', ls(32807)), ('scrape_with_custom_values', ls(32135))
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
	fl = ['SD', '720p', '1080p', '4K']
	dl = ['%s %s' % (ls(32188), i) for i in fl]
	try: preselect = [fl.index(i) for i in get_setting(quality_setting).split(', ')]
	except: preselect = []
	list_items = [{'line1': item} for item in dl]
	kwargs = {'items': json.dumps(list_items), 'heading': 'POV', 'multi_choice': 'true', 'preselect': preselect}
	choice = select_dialog(fl, multi_line='false', **kwargs)
	if choice is None: return
	if choice: return set_setting(quality_setting, ', '.join(choice))
	ok_dialog(text=32574)
	return set_quality_choice(quality_setting)

def extras_lists_choice():
	fl = [2050, 2051, 2052, 2053, 2054, 2055, 2056, 2057, 2058, 2059, 2060, 2061, 2062]
	dl = [ls(32664), ls(32503), ls(32607), ls(32984), ls(32986), ls(32989), ls(32531), ls(32616), ls(32617)]
	dl.extend('%s %s' % (ls(32612), ls(i)) for i in (32543, 32470, 32480, 32499))
	try: preselect = [fl.index(i) for i in settings.extras_enabled_menus()]
	except: preselect = []
	list_items = [{'line1': item} for item in dl]
	kwargs = {'items': json.dumps(list_items), 'heading': 'POV', 'multi_choice': 'true', 'preselect': preselect}
	selection = select_dialog(fl, multi_line='false', **kwargs)
	if selection == []: return set_setting('extras.enabled_menus', 'noop')
	elif selection is None: return
	selection = ','.join(map(str, selection))
	set_setting('extras.enabled_menus', selection)

def set_language_filter_choice(filter_setting):
	from modules.meta_lists import meta_languages
	dl = list(k for k, v in meta_languages.items() if v['long'])
	fl = list(v['long'] for v in meta_languages.values() if v['long'])
	try: preselect = [fl.index(i) for i in get_setting(filter_setting).split(', ')]
	except: preselect = []
	list_items = [{'line1': item} for item in dl]
	kwargs = {'items': json.dumps(list_items), 'heading': 'POV', 'multi_choice': 'true', 'preselect': preselect}
	choice = select_dialog(fl, multi_line='false', **kwargs)
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
	choice = select_dialog(choices, multi_line='false', **kwargs)
	if not choice: return
	set_setting('results.sort_order_display', choice[0])
	set_setting('results.sort_order', choice[1])

def results_highlights_choice():
	choices = [(ls(32240), '0'), (ls(32583), '1'), (ls(32241), '2')]
	list_items = [{'line1': item[0]} for item in choices]
	kwargs = {'items': json.dumps(list_items), 'heading': 'POV'}
	choice = select_dialog([i[1] for i in choices], multi_line='false', **kwargs)
	if choice: set_setting('highlight.type', choice)

def results_layout_choice():
	xml_choices = [
		'List Default',     'List Contrast Default',
		'InfoList Default', 'InfoList Contrast Default',
		'WideList Default', 'WideList Contrast Default'
	]
	list_items = [{'line1': item} for item in xml_choices]
	kwargs = {'items': json.dumps(list_items), 'heading': 'POV'}
	choice = select_dialog(xml_choices, multi_line='false', **kwargs)
	if choice in xml_choices: set_setting('results.xml_style', choice)

def set_subtitle_choice():
	choices = [(ls(32192), '0'), (ls(32193), '1'), (ls(32027), '2')]
	list_items = [{'line1': item[0]} for item in choices]
	kwargs = {'items': json.dumps(list_items), 'heading': 'POV'}
	choice = select_dialog([i[1] for i in choices], multi_line='false', **kwargs)
	if choice: set_setting('subtitles.subs_action', choice)

def scraper_dialog_color_choice(setting):
	setting = 'int_dialog_highlight' if setting == 'internal' else 'ext_dialog_highlight'
	chosen_color = color_choice()
	if chosen_color: set_setting(setting, chosen_color)

def scraper_quality_color_choice(setting):
	chosen_color = color_choice()
	if chosen_color: set_setting(setting, chosen_color)

def scraper_color_choice(setting):
	choices = [
		('easynews', 'provider.easynews_colour'), ('debrid_cloud', 'provider.debrid_cloud_colour'),
		('hoster', 'hoster.identify'),            ('torrent', 'torrent.identify'),
		('rd', 'provider.rd_colour'),             ('pm', 'provider.pm_colour'),
		('ad', 'provider.ad_colour'),             ('tb', 'provider.tb_colour'),
		('oc', 'provider.oc_colour'),             ('free', 'provider.free_colour')
	]
	setting = [i[1] for i in choices if i[0] == setting][0]
	chosen_color = color_choice()
	if chosen_color: set_setting(setting, chosen_color)

def color_choice(msg_dialog='POV', no_color=False):
	import xml.etree.ElementTree as ET
	root = ET.fromstring(kodi_utils.open_file('special://xbmc/system/colors.xml').read()).iter('color')
	color_chart = [(i.get('name'), i.text) for i in root if i.get('name') not in ('none', 'transparent')]
	color_chart.sort(key=lambda k: k[1], reverse=False)
	if no_color: color_chart = [('no color', ''), *color_chart]
	color_display = ['[COLOR %s]%s[/COLOR]' % (i[1], i[0].upper()) for i in color_chart]
	list_items = [{'line1': item} for item in color_display]
	kwargs = {'items': json.dumps(list_items), 'heading': 'POV'}
	choice = select_dialog([i[0] for i in color_chart], multi_line='false', **kwargs)
	if choice is None: return
	return choice

def meta_language_choice():
	from modules.meta_lists import meta_languages
	langs = [{'iso': v['iso'], 'name': k} for k, v in meta_languages.items()]
	list_items = [{'line1': i['name'], 'line2': i['iso']} for i in langs]
	kwargs = {'items': json.dumps(list_items), 'heading': ls(32145)}
	choice = select_dialog(langs, multi_line='false', **kwargs)
	if choice is None: return None
	chosen_language, chosen_language_display = choice['iso'], choice['name']
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
		notification(32576) if favorites.clear(mediatype) else notification(32574)
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
	is_widget = params.get('is_widget', False) in ('true', 'True', True)
	content = params.get('content') or params.get('mediatype') or container_content()[:-1]
	season, episode = params.get('season'), params.get('episode')
	if not meta:
		func = metadata.movie_meta if content == 'movie' else metadata.tvshow_meta
		meta = func('tmdb_id', params['tmdb_id'], settings.metadata_user_info(), get_datetime())
	scrapable = content in ('movie', 'episode')
	poster = meta.get('poster', '')
	title = meta.get('title', '')
	on_str, off_str, currently_str, open_str, settings_str = ls(32090), ls(32027), ls(32598), ls(32641), ls(32247)
	scraper_options_str = '%s %s' % (ls(32533), ls(32841))
	browse_str = ls(32652).replace('[B]', '').replace('[/B]', '')
	watched_indicators = settings.watched_indicators()
	smart_play = settings.smart_play_enabled()
	uncached_status, uncached_toggle = (on_str, 'false') if settings.display_uncached_torrents() else (off_str, 'true')
	results_xml_status = settings.results_xml_style()
	listing = []
	append = listing.append
	if content == 'episode':
		append(('scrape_from_episode_group', 'Scrape From Episode Group', scraper_options_str, poster))
	if scrapable:
		append(('clear_and_rescrape', ls(32014), scraper_options_str, poster))
		append(('rescrape_with_disabled', ls(32006), scraper_options_str, poster))
		append(('scrape_with_filters_ignored', ls(32807), scraper_options_str, poster))
		append(('scrape_with_custom_values', ls(32135), scraper_options_str, poster))
	if content == 'tvshow' and meta:
		if smart_play == 2 or (smart_play == 1 and is_widget):
			append(('browse_choice', browse_str, title, poster))
		append(('play_random', ls(32541), title, poster))
		append(('play_random_continual', ls(32542), title, poster))
	append(('clear_scrapers_cache', ls(32637), ''))
	append(('open_external_scrapers_choice', '%s %s' % (ls(32118), ls(32513)), ''))
	if scrapable:
		append(('toggle_torrents_display_uncached', ls(32160), '%s: [B]%s[/B]' % (currently_str, uncached_status)))
		append(('set_results_xml_display', '%s %s' % (ls(32139), ls(32140)), '%s: [B]%s[/B]' % (currently_str, results_xml_status)))
	if watched_indicators == 0 and content == 'tvshow':
		append(('dropped_choice', 'Toggle Dropped', title, poster))
	elif watched_indicators == 1:
		append(('clear_trakt_cache', ls(32497) % ls(32037), ''))
	elif watched_indicators == 2:
		append(('clear_mdbl_cache', ls(32497) % 'MDBList', ''))
	if content in ('movie', 'tvshow') and meta:
		append(('clear_media_cache', ls(32604) % (ls(32028) if content == 'movie' else ls(32029)), title, poster))
	listing.append(('open_pov_settings', '%s %s %s' % (open_str, ls(32036), settings_str), ''))
	if is_widget: listing.append(('reload_widgets', 'POV: Refresh Widgets', ''))
	list_items = [
		{'line1': item[1], 'line2': item[2] or item[1], **({'icon': item[3]} if len(item) == 4 else {})}
		for item in listing
	]
	heading = ls(32646).replace('[B]', '').replace('[/B]', '')
	choice = select_dialog([i[0] for i in listing], items=json.dumps(list_items), heading=heading)
	if choice in (None, 'save_and_exit'): return
	if choice == 'clear_and_rescrape': return clear_and_rescrape(content, meta, season, episode)
	if choice == 'rescrape_with_disabled': return rescrape_with_disabled(content, meta, season, episode)
	if choice == 'scrape_with_filters_ignored': return scrape_with_filters_ignored(content, meta, season, episode)
	if choice == 'scrape_with_custom_values': return scrape_with_custom_values(content, meta, season, episode)
	if choice == 'scrape_from_episode_group': return scrape_from_episode_group(meta, season, episode)
	if choice == 'browse_choice': return browse_choice(meta, is_widget)
	if choice in ('play_random', 'play_random_continual'): return random_choice(choice, meta)
	if choice == 'clear_scrapers_cache': return clear_scrapers_cache()
	if choice == 'open_external_scrapers_choice': return enable_disable('all')
	if choice == 'dropped_choice': return dropped_choice(meta)
	if choice == 'clear_media_cache': return refresh_cached_meta(meta)
	if choice == 'open_pov_settings': return kodi_utils.open_settings('')
	if choice in ('clear_trakt_cache', 'clear_mdbl_cache'):
		clear_cache({'clear_trakt_cache': 'trakt', 'clear_mdbl_cache': 'mdblist'}[choice])
		return container_refresh()
	if choice == 'toggle_torrents_display_uncached': set_setting('torrent.display.uncached', uncached_toggle)
	elif choice == 'set_results_xml_display': results_layout_choice()
#	elif choice == 'reload_widgets': return kodi_utils.widget_refresh()
	elif choice == 'reload_widgets': return execute_builtin('ReloadSkin()')
	options_menu(params, meta=meta)

def extras_menu(params):
	from windows import open_window
	function = metadata.movie_meta if params['mediatype'] == 'movie' else metadata.tvshow_meta
	meta = function('tmdb_id', params['tmdb_id'], settings.metadata_user_info(), get_datetime())
	kwargs = {'meta': meta, 'is_widget': params.get('is_widget', 'false'), 'is_home': params.get('is_home', 'false')}
	open_window(('windows.extras', 'Extras'), 'extras.xml', **kwargs)

def refresh_cached_meta(meta):
	from caches.meta_cache import MetaCache
	try:
		metacache = MetaCache()
		mediatype, tmdb_id = meta['mediatype'], meta['tmdb_id']
		if mediatype == 'tvshow': metacache.delete_all_seasons_memory_cache(tmdb_id, meta.get('total_seasons'))
		metacache.delete(mediatype, 'tmdb_id', tmdb_id, meta)
		notification(32576, 1500)
		container_refresh()
	except: notification(32574)

def build_navigate_to_page(params):
	use_alphabet = settings.nav_jump_use_alphabet() == 2
	icon = media_path('item_jump.png')
	mediatype = params.get('mediatype', '')
	if use_alphabet:
		start_list = [chr(i) for i in range(97, 123)]
	else:
		total_pages = int(params.get('total_pages', 0))
		start_list = [str(i) for i in range(1, total_pages + 1)]
		current_page = params.get('current_page')
		if current_page in start_list: start_list.remove(current_page)
	list_items = []
	for item in start_list:
		if use_alphabet: line1, line2 = item.upper(), ls(32821) % (mediatype, item.upper())
		else: line1, line2 = '%s %s' % ('Page', item), ls(32822) % item
		list_items.append({'line1': line1, 'line2': line2, 'icon': icon})
	kwargs = {'items': json.dumps(list_items), 'heading': 'POV'}
	new_start = select_dialog(start_list, **kwargs)
	sleep(100)
	if new_start is None: return
	passthrough_keys = ['mediatype', 'query', 'actor_id', 'user', 'slug', 'list_id', 'name']
	url_params = {key: params.get(key, '') for key in passthrough_keys}
	url_params.update({
		'mode': params.get('transfer_mode', ''),
		'action': params.get('transfer_action', ''),
		'new_page': '' if use_alphabet else new_start,
		'new_letter': new_start if use_alphabet else ''
	})
	execute_builtin('Container.Update(%s)' % build_url(url_params))

def _get_base_play_params(mediatype, meta, season=None, episode=None):
	play_params = {'mode': 'play_media', 'tmdb_id': meta['tmdb_id'], 'autoplay': 'false'}
	if mediatype in ('movie', 'movies'): play_params.update({'mediatype': 'movie'})
	else: play_params.update({'mediatype': 'episode', 'season': season, 'episode': episode})
	return play_params

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
	kwargs = {'items': json.dumps(list_items), 'heading': heading, 'enumerate': 'true'}
	choice = select_dialog([i[0] for i in choices], multi_line='false', **kwargs)
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
		episodes, preselect = episodes[index:] + episodes[:index], 0
	else: heading, preselect = meta['title'], -1
	choices = [(item['custom_season'], item['custom_episode'], item['custom_name'], item['custom_title']) for item in episodes]
	if not choices: return
	list_items = [{'line1': item[2], 'line2': item[3], 'icon': poster} for item in choices]
	kwargs = {'items': json.dumps(list_items), 'heading': heading, 'preselect': preselect}
	choice = select_dialog([(i[0], i[1]) for i in choices], multi_line='false', **kwargs)
	if choice is None: return
	play_params = {'mode': 'play_media', 'tmdb_id': tmdb_id, 'mediatype': 'episode', 'season': season, 'episode': episode}
	play_params.update({'custom_season': choice[0], 'custom_episode': choice[1]})
	Sources().source_select(play_params)

def clear_and_rescrape(mediatype, meta, season=None, episode=None):
	from caches.providers_cache import ExternalProvidersCache
	from modules.sources import Sources
	show_busy_dialog()
	deleted = ExternalProvidersCache().delete_cache_single(mediatype, str(meta['tmdb_id']))
	hide_busy_dialog()
	if not deleted: return notification(32574)
	play_params = _get_base_play_params(mediatype, meta, season, episode)
	Sources().source_select(play_params)

def rescrape_with_disabled(mediatype, meta, season=None, episode=None):
	from modules.sources import Sources
	play_params = _get_base_play_params(mediatype, meta, season, episode)
	play_params.update({'disabled_ignored': 'true', 'prescrape': 'false'})
	Sources().source_select(play_params)

def scrape_with_filters_ignored(mediatype, meta, season=None, episode=None):
	from modules.sources import Sources
	play_params = _get_base_play_params(mediatype, meta, season, episode)
	play_params.update({'ignore_scrape_filters': 'true'})
	set_property('fs_filterless_search', 'true')
	Sources().source_select(play_params)

def scrape_with_custom_values(mediatype, meta, season=None, episode=None):
	from windows import open_window
	from modules.sources import Sources
	play_params = _get_base_play_params(mediatype, meta, season, episode)
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

def clear_scrapers_cache(silent=False):
	for item in ('internal_scrapers', 'external_scrapers'): clear_cache(item, silent=True)
	if not silent: notification(32576)

def scraper_names(folder):
	provider_list = []
	append = provider_list.append
	source_folder_location = 'special://home/addons/plugin.video.pov/resources/lib/magneto/%s'
	source_subfolders = {'hosters': '', 'torrents': ''}
	if folder == 'all': source_subfolders = ['']
	else: source_subfolders = [v for k, v in source_subfolders.items() if k == folder]
	for item in source_subfolders:
		files = kodi_utils.list_dirs(source_folder_location % item)[1]
		for item in files:
			module_name = item.split('.')[0]
			if module_name == '__init__': continue
			append(module_name)
	return provider_list

def scrapers_status(folder='all'):
	providers = scraper_names(folder)
	enabled = [i for i in providers if kodi_utils.get_setting('provider.' + i) == 'true']
	disabled = [i for i in providers if i not in enabled]
	return enabled, disabled

def enable_disable(folder):
	try:
		icon = 'special://home/addons/plugin.video.pov/resources/lib/fenom/fenom_icon.png'
		enabled, disabled = scrapers_status(folder)
		all_sources = sorted(enabled + disabled)
		preselect = [all_sources.index(i) for i in enabled]
		list_items = [{'line1': i.upper(), 'icon': icon} for i in all_sources]
		kwargs = {'items': json.dumps(list_items), 'multi_choice': 'true', 'preselect': preselect}
		chosen = kodi_utils.select_dialog(all_sources, multi_line='false', **kwargs)
		if chosen is None: return
		for i in all_sources:
			if i in chosen: set_setting('provider.' + i, 'true')
			else: set_setting('provider.' + i, 'false')
		return kodi_utils.notification(32576, 1500)
	except: return kodi_utils.notification(32574, 1500)

