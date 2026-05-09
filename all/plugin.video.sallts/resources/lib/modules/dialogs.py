import json
from indexers import metadata
from modules import kodi_utils, settings
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

def flicklist_manager_choice(params):
	if not get_setting('flicklist_user', ''): return notification(32760)
	from indexers import flicklist_api
	heading = 'FlickList'
	icon = 'DefaultPlaylist.png'
	choices = []
	choices += [
		(str(item['id']), '%s' % item['name'], '%s items' % item['item_count'])
		for item in flicklist_api.flicklist_get_lists('my_lists')
	]
	choices += [(i.lower(), '[I]%s[/I]' % i, '') for i in (ls(32453), ls(32500))]
	if params['mediatype'] == 'tvshow': choices += [('dropped', 'Toggle Dropped', '')]
	list_items = [{'line1': item[1], 'line2': item[2], 'icon': icon} for item in choices]
	kwargs = {'items': json.dumps(list_items), 'heading': heading, 'multi_line': 'true'}
	choice = select_dialog([(i[0], i[1]) for i in choices], **kwargs)
	if choice is None: return
	add_str, rem_str = 'Add to %s?' % choice[1], 'Remove from %s?' % choice[1]
	if 'dropped' in choice[0]:
		return flicklist_api.hide_unhide_flicklist_items(params['tmdb_id'], 'shows', params['tmdb_id'], 'dropped')
	if 'watchlist' in choice[0] or 'favorites' in choice[0]:
		if 'watchlist' in choice[0]: list_items = flicklist_api.flicklist_watchlist('all', None, '')
		else: list_items = flicklist_api.flicklist_favorites('all', None, '')
		action = False if int(params['tmdb_id']) in {i['tmdb_id'] for i in list_items} else True
		args = choice[0], params['mediatype'], int(params['tmdb_id'])
		if not action:
			if not confirm_dialog(text=rem_str, top_space=True): return
			return flicklist_api.remove_from_collection(*args)
		else: return flicklist_api.add_to_collection(*args)
	list_items = {i['tmdb_id'] for i in flicklist_api.get_flicklist_list_contents(choice[0])}
	action = False if int(params['tmdb_id']) in list_items else True
	args = choice[0], params['mediatype'], int(params['tmdb_id'])
	if not action:
		if not confirm_dialog(text=rem_str, top_space=True): return
		flicklist_api.remove_from_list(*args)
	else: flicklist_api.add_to_list(*args)

def random_choice(choice, meta):
	tmdb_id = meta.get('tmdb_id')
	if not tmdb_id: return
	from modules.episode_tools import get_random_episode
	from sources import Sources
	meta, play_params = get_random_episode(tmdb_id, True if choice == 'play_random_continual' else False)
	if not play_params: return notification(32760)
	Sources().source_select(play_params)

def playback_choice(content, poster, meta):
	items = [('scrape_with_custom_values', ls(32135))]
	list_items = [{'line1': i[1], 'icon': poster} for i in items]
	kwargs = {'items': json.dumps(list_items), 'heading': ls(32174)}
	choice = select_dialog([i[0] for i in items], **kwargs)
	if choice is None: return
	scrape_with_custom_values(content, meta)

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
	kwargs = {'items': json.dumps(list_items), 'heading': 'SALTS', 'multi_choice': 'true', 'preselect': preselect}
	selection = select_dialog(fl, **kwargs)
	if selection == []: return set_setting('extras.enabled_menus', 'noop')
	elif selection is None: return
	selection = [str(i) for i in selection]
	set_setting('extras.enabled_menus', ','.join(selection))

def set_subtitle_choice():
	choices = [(ls(32192), '0'), (ls(32193), '1'), (ls(32027), '2')]
	list_items = [{'line1': item[0]} for item in choices]
	kwargs = {'items': json.dumps(list_items), 'heading': 'SALTS'}
	choice = select_dialog([i[1] for i in choices], **kwargs)
	if choice: return set_setting('subtitles.subs_action', choice)

def scraper_color_choice(setting):
	choices = [
		('debrid_cloud', 'provider.debrid_cloud_colour'),
		('hoster', 'hoster.identify'),
		('torrent', 'torrent.identify'),
		('rd', 'provider.rd_colour'),
		('pm', 'provider.pm_colour'),
		('tb', 'provider.tb_colour'),
		('free', 'provider.free_colour')
	]
	setting = [i[1] for i in choices if i[0] == setting][0]
	chosen_color = color_choice()
	if chosen_color: set_setting(setting, chosen_color)

def color_choice(msg_dialog='SALTS', no_color=False):
	from modules.meta_lists import meta_colors
	color_chart = meta_colors
	color_display = ['[COLOR %s]%s[/COLOR]' % (i, i.capitalize()) for i in color_chart]
	if no_color:
		color_chart.insert(0, 'No Color')
		color_display.insert(0, 'No Color')
	list_items = [{'line1': item} for item in color_display]
	kwargs = {'items': json.dumps(list_items), 'heading': 'SALTS'}
	choice = select_dialog(color_chart, **kwargs)
	if choice is None: return
	return choice

def meta_language_choice():
	from modules.meta_lists import meta_languages
	langs = meta_languages
	list_items = [{'line1': i['name']} for i in langs]
	kwargs = {'items': json.dumps(list_items), 'heading': ls(32145)}
	list_choose = select_dialog(langs, **kwargs)
	if list_choose is None: return None
	chosen_language, chosen_language_display = list_choose['iso'], list_choose['name']
	set_setting('meta_language', chosen_language)
	set_setting('meta_language_display', chosen_language_display)
	clear_cache('meta', silent=True)

def favorites_choice(params):
	from caches.favorites_cache import favorites_cache
	icon = media_path('favorites.png')
	if params.get('cache'):
		list = [('%s %s' % (ls(32028), ls(32453)), 'movie'), ('%s %s' % (ls(32029), ls(32453)), 'tvshow')]
		list_items = [{'line1': item[0], 'icon': icon} for item in list]
		kwargs = {'items': json.dumps(list_items), 'heading': ls(32453)}
		mediatype = select_dialog([item[1] for item in list], **kwargs)
		if mediatype is None: return
		if not favorites_cache.clear_favorites(mediatype): notification(32574)
	else:
		mediatype, tmdb_id, title = params['mediatype'], params['tmdb_id'], params['title']
		current_favorites = favorites_cache.get_favorites(mediatype)
		if any(i['tmdb_id'] == tmdb_id for i in current_favorites): action, text = favorites_cache.remove_from_favorites, '%s SALTS %s?' % (ls(32603), ls(32453))
		else: action, text = favorites_cache.add_to_favorites, '%s SALTS %s?' % (ls(32602), ls(32453))
		if not confirm_dialog(text='%s[CR][CR]%s' % (title, text)): return
		if action(mediatype, tmdb_id, title): notification(32576)
		else: notification(32574)

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
	watched_indicators = settings.watched_indicators()
	open_str, settings_str = ls(32641), ls(32247)
	scraper_options_str, cache_options_str = '%s %s' % (ls(32533), ls(32841)), '%s %s' % ('Cache', ls(32841))
	multi_line = 'true' if content in ('movie', 'tvshow', 'episode') else 'false'
	listing = (
		('scrape_from_episode_group', 'Scrape From Episode Group', scraper_options_str, meta['poster']) if content == 'episode' else None,
		('scrape_with_custom_values', ls(32135), scraper_options_str, meta['poster']) if multi_line == 'true' else None,
		('play_random', ls(32541), scraper_options_str, meta['poster']) if content in ('tvshow') and meta else None,
		('clear_trakt_cache', ls(32497) % ls(32037), cache_options_str) if watched_indicators == 1 else None,
		('clear_mdbl_cache', ls(32497) % 'MDBList', cache_options_str) if watched_indicators == 2 else None,
		('clear_flicklist_cache', ls(32497) % 'FlickList', cache_options_str) if watched_indicators == 3 else None,
		('clear_media_cache', ls(32604) % (ls(32028) if content in ('movie') else ls(32029)), cache_options_str, meta['poster'])
		if content in ('movie', 'tvshow') and meta
		else None,
		('open_salts_settings', '%s %s %s' % (open_str, ls(32036), settings_str), '%s %s %s' % (open_str, ls(32036), settings_str)),
		('reload_widgets', 'SALTS: Refresh Widgets', cache_options_str) if is_widget else None
	)
	listing = [item for item in listing if item]
	list_items = list(_builder())
	heading = ls(32646).replace('[B]', '').replace('[/B]', '')
	kwargs = {'items': json.dumps(list_items), 'heading': heading, 'multi_line': multi_line}
	choice = select_dialog([i[0] for i in listing], **kwargs)
	if   choice in ('save_and_exit', None): return
	elif choice == 'scrape_from_episode_group': return scrape_from_episode_group(meta, season, episode)
	elif choice == 'scrape_with_custom_values': return scrape_with_custom_values(content, meta, season, episode)
	elif choice == 'play_random': return random_choice(choice, meta)
	elif choice == 'clear_trakt_cache': return clear_cache('trakt')
	elif choice == 'clear_mdbl_cache': return clear_cache('mdblist')
	elif choice == 'clear_flicklist_cache_cache': return clear_cache('flicklist')
	elif choice == 'clear_media_cache': return refresh_cached_meta(meta)
	elif choice == 'open_salts_settings': return kodi_utils.open_settings('0.0')
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
		mediatype, tmdb_id = meta['mediatype'], meta['tmdb_id']
		MetaCache().delete(mediatype, 'tmdb_id', tmdb_id, meta)
		if mediatype == 'tvshow': MetaCache().delete_all_seasons_memory_cache(tmdb_id)
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
			else: line1, line2 = '%s %s' % (ls(32022), i), ls(32822) % i
			yield {'line1': line1, 'line2': line2, 'icon': icon}
	if use_alphabet:
		start_list = [chr(i) for i in range(97,123)]
	else:
		start_list = [str(i) for i in range(1, int(params.get('total_pages'))+1)]
		start_list.remove(params.get('current_page'))
	list_items = list(_builder(use_alphabet))
	kwargs = {'items': json.dumps(list_items), 'heading': 'SALTS'}
	new_start = select_dialog(start_list, **kwargs)
	sleep(100)
	if new_start is None: return
	if use_alphabet: new_page, new_letter = '', new_start
	else: new_page, new_letter = new_start, None
	url_params = {'mode': params.get('transfer_mode', ''), 'action': params.get('transfer_action', ''), 'new_page': new_page, 'new_letter': new_letter,
				'mediatype': params.get('mediatype', ''), 'query': params.get('query', ''), 'actor_id': params.get('actor_id', ''),
				'user': params.get('user', ''), 'slug': params.get('slug', ''), 'list_id': params.get('list_id', ''), 'name': params.get('name', '')}
	execute_builtin('Container.Update(%s)' % build_url(url_params))

def scrape_with_custom_values(mediatype, meta, season=None, episode=None):
	from windows import open_window
	from sources import Sources
	play_params = {'mode': 'play_media', 'tmdb_id': meta['tmdb_id'], 'imdb_id': meta.get('imdb_id')}
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
	set_property('fs_filterless_search', 'true')
	Sources().source_select(play_params)

def scrape_from_episode_group(meta, season, episode):
	from indexers.tmdb_api import episode_groups, episode_group_details
	from sources import Sources
	user_info = settings.metadata_user_info()
	tmdb_id, heading, poster = meta['tmdb_id'], meta['tvshowtitle'], meta['poster']
	groups = episode_groups(tmdb_id, user_info['tmdb_api'])
	choices = [
		(item['id'], '%s (%s)' % (item['name'], item['type']), '%s Groups, %s Episodes' % (item['group_count'], item['episode_count']))
		for item in groups
	]
	if not choices: return notification(32760)
	list_items = [{'line1': item[1], 'line2': item[2], 'icon': poster} for item in choices]
	kwargs = {'items': json.dumps(list_items), 'heading': heading, 'enumerate': 'true', 'multi_line': 'true'}
	choice = select_dialog([i[0] for i in choices], **kwargs)
	if choice is None: return
	episodes = episode_group_details(choice, user_info['tmdb_api'])
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
	if not index is None:
		heading = episodes[index]['name']
		episodes, preselect = episodes[index:] + episodes[:index], [0]
	else: heading, preselect = meta['title'], []
	choices = [(item['custom_season'], item['custom_episode'], item['custom_name'], item['custom_title']) for item in episodes]
	if not choices: return
	list_items = [{'line1': item[2], 'line2': item[3], 'icon': poster} for item in choices]
	kwargs = {'items': json.dumps(list_items), 'heading': heading, 'multi_line': 'true', 'preselect': preselect}
	choice = select_dialog([(i[0], i[1]) for i in choices], **kwargs)
	if choice is None: return
	play_params = {
		'mode': 'play_media', 'mediatype': 'episode', 'imdb_id': meta.get('imdb_id'),
		'tmdb_id': tmdb_id, 'season': season, 'episode': episode
	}
	play_params.update({'custom_season': choice[0], 'custom_episode': choice[1]})
	Sources().source_select(play_params)

