import sys
from threading import Thread
from indexers.metadata import tvshow_meta, season_episodes_meta, art_infodict, episode_infodict, info_tagger
from indexers.flicklist_api import flicklist_get_hidden_items
from indexers.mdblist_api import mdbl_get_hidden_items
from indexers.trakt_api import trakt_fetch_collection_watchlist, trakt_get_hidden_items, trakt_get_my_calendar, trakt_my_anime_calendar, trakt_anime_calendar
from caches.watched_cache import get_resumetime, set_resumetime, get_watched_status_episode, get_watched_info_tv, get_bookmarks, get_next_episodes, get_in_progress_episodes
from modules import kodi_utils, settings
#from modules.utils import jsondate_to_datetime, adjust_premiered_date, make_day, get_datetime, title_key, date_difference, make_thread_list_enumerate
from modules.utils import jsondate_to_datetime, adjust_premiered_date, make_day, get_datetime, title_key, date_difference, TaskPool
# logger = kodi_utils.logger

tv_meta_function, season_meta_function, default_duration = tvshow_meta, season_episodes_meta, 3600
get_watched_status, get_watched_info = get_watched_status_episode, get_watched_info_tv
KODI_VERSION, make_cast_list = kodi_utils.get_kodi_version(), kodi_utils.make_cast_list
string, ls, build_url, get_infolabel = str, kodi_utils.local_string, kodi_utils.build_url, kodi_utils.get_infolabel
calendar_sort_order, calendar_focus_today = settings.calendar_sort_order, settings.calendar_focus_today
nextep_content_settings, nextep_display_settings = settings.nextep_content_settings, settings.nextep_display_settings
thumb_fanart_info, date_offset_info, default_all_episodes = settings.thumb_fanart, settings.date_offset, settings.default_all_episodes
single_ep_display_title, single_ep_format = settings.single_ep_display_title, settings.single_ep_format
adjust_premiered_date_function, jsondate_to_datetime_function = adjust_premiered_date, jsondate_to_datetime
date_difference_function, make_day_function, title_key_function, get_datetime_function = date_difference, make_day, title_key, get_datetime
run_plugin, container_refresh, container_update = 'RunPlugin(%s)', 'Container.Refresh(%s)', 'Container.Update(%s)'
fanart_empty = kodi_utils.get_addoninfo('fanart')
poster_empty = kodi_utils.media_path('box_office.png')
watched_str, unwatched_str, extras_str, options_str = ls(32642), ls(32643), ls(32645), ls(32646)
clearprog_str, browse_str, browse_seas_str = ls(32651), ls(32652), ls(32544)
traktmanager_str, mdblmanager_str, flicklistmanager_str = ls(32198), ls(32200), '[B]FlickList Manager[/B]'

class Episodes:
	def __init__(self, params):
		self.params = params
		self.list_type = self.params.get('id_type', '')
		self.list = self.params.get('list', [])
		self.items = []
		self.append = self.items.append
		self.current_date = get_datetime_function()
		self.adjust_hours = date_offset_info()
		self.meta_user_info = settings.metadata_user_info()
		self.watched_indicators = settings.watched_indicators()
		self.watched_title = settings.watched_title(self.watched_indicators)
		self.watched_info = get_watched_info(self.watched_indicators)
		self.bookmarks = get_bookmarks(self.watched_indicators, 'episode')
		self.ignore_articles = settings.ignore_articles()
		self.cm_sort = settings.context_menu_sort()
		self.show_unaired = settings.show_unaired()
		self.all_episodes = default_all_episodes()
		self.thumb_fanart = thumb_fanart_info()
		self.display_title, self.date_format = single_ep_display_title(), single_ep_format()
		self.is_widget = kodi_utils.external_browse()
		self.widget_hide_watched = self.is_widget and self.meta_user_info['widget_hide_watched']
		self.art_provider = (*settings.get_art_provider(), poster_empty, fanart_empty)
		self.container_update = 'ActivateWindow(Videos,%s,return)' if self.is_widget else 'Container.Update(%s)'

	def build_episode_content(self, position, ep_data):
		try:
			ep_data_get = ep_data.get
			meta = tv_meta_function('trakt_dict', ep_data_get('media_ids'), self.meta_user_info, self.current_date)
			meta_get = meta.get
			if not meta: return
			if self.list_type.startswith('next_episode'): props = {'salts_last_played': ep_data_get('last_played', self.resinsert)}
			else: props = {'salts_sort_order': string(ep_data_get('sort', position))}
			orig_season, orig_episode = ep_data_get('season'), ep_data_get('episode')
			if self.list_type.startswith('next_episode'):
				episode_count = (i['episode_count'] for i in meta_get('season_data') if i['season_number'] == orig_season)
				if orig_episode >= next(episode_count): orig_season, orig_episode, new_season = orig_season + 1, 1, True
				else: orig_episode, new_season = orig_episode + 1, False
				if new_season and orig_season > meta_get('total_seasons'): return
			episodes_data = season_meta_function(orig_season, meta, self.meta_user_info)
			try: item = next((i for i in episodes_data if i['episode'] == orig_episode))
			except: return
			cm = []
			cm_append = cm.append
			item_get = item.get
			item['background'] = item_get('thumb') if self.thumb_fanart else ''
			tmdb_id, tvdb_id, imdb_id = meta_get('tmdb_id'), meta_get('tvdb_id'), meta_get('imdb_id')
			title, year = meta_get('title'), meta_get('year')
			cast, episode_run_time = meta_get('cast', []), meta_get('duration')
			season, episode = item_get('season'), item_get('episode')
			orig_premiered, ep_name = item_get('premiered'), item_get('title')
			str_season_zfill2, str_episode_zfill2 = string(season).zfill(1), string(episode).zfill(2)
			episode_date, premiered = adjust_premiered_date_function(orig_premiered, self.adjust_hours)
			if not episode_date or self.current_date < episode_date:
				if self.list_type.startswith('next_episode'):
					if not self.nextep_include_unaired or not episode_date: return
					if new_season and not date_difference_function(self.current_date, episode_date, 7): return
				elif not self.show_unaired: return
				unaired = True
			else: unaired = False
			playcount, overlay = get_watched_status(self.watched_info, string(tmdb_id), season, episode)
			if self.widget_hide_watched and playcount and not unaired: return
			resumetime, progress = get_resumetime(self.bookmarks, tmdb_id, season, episode)
			if self.display_title == 0: title_string = ''.join([title, ': '])
			else: title_string = ''
			if self.display_title in (0, 1): seas_ep = ''.join([str_season_zfill2, 'x', str_episode_zfill2, ' - '])
			else: seas_ep = ''
			if self.list_type.startswith('next_episode'):
				unwatched = ep_data_get('unwatched', False)
				if episode_date: display_premiered = make_day_function(self.current_date, episode_date, self.date_format)
				else: display_premiered == 'UNKNOWN'
				airdate = ''.join(['[[COLOR magenta]', display_premiered, '[/COLOR]] ']) if self.nextep_include_airdate else ''
				highlight_color = self.nextep_unaired_color if unaired else self.nextep_unwatched_color if unwatched else ''
				italics_open, italics_close = ('[I]', '[/I]') if highlight_color else ('', '')
				if highlight_color: episode_info = ''.join([seas_ep, italics_open, '[COLOR', highlight_color, ']', ep_name, '[/COLOR]', italics_close])
				else: episode_info = ''.join([seas_ep, italics_open, ep_name, italics_close])
				display = ''.join([airdate, title_string.upper(), episode_info])
			elif self.list_type == 'trakt_calendar':
				if episode_date: display_premiered = make_day_function(self.current_date, episode_date, self.date_format)
				else: display_premiered == 'UNKNOWN'
				if unaired: display_premiered = ''.join(['[COLOR magenta]', display_premiered, '[/COLOR]'])
				color_tags = ('[COLOR cyan][I]', '[/I][/COLOR]') if unaired else ('', '')
				display = ''.join(['[', display_premiered, '] ', title_string.upper(), seas_ep, color_tags[0], ep_name, color_tags[1]])
			else:
				color_tags = ('[COLOR cyan]', '[/COLOR]') if unaired else ('', '')
				display = ''.join([title_string.upper(), seas_ep, color_tags[0], ep_name, color_tags[1]])
			item.update({
				'title': display, 'premiered': premiered, 'playcount': playcount, 'overlay': overlay,
				'duration': item_get('duration') or episode_run_time or default_duration
			})
			extras_params = build_url({
				'mode': 'extras_menu_choice', 'mediatype': 'tvshow',
				'tmdb_id': tmdb_id, 'is_widget': self.is_widget
			})
			options_params = build_url({
				'mode': 'options_menu_choice', 'content': 'episode',
				'tmdb_id': tmdb_id, 'season': season, 'episode': episode, 'is_widget': self.is_widget
			})
			url_params = build_url({
				'mode': 'play_media', 'mediatype': 'episode',
				'tmdb_id': tmdb_id, 'imdb_id': imdb_id, 'season': season, 'episode': episode
			})
			if self.all_episodes and self.all_episodes == 1 and meta_get('total_seasons') > 1: browse_params = build_url({
				'mode': 'build_season_list', 'tmdb_id': tmdb_id
			})
			elif self.all_episodes: browse_params = build_url({
				'mode': 'build_episode_list', 'tmdb_id': tmdb_id, 'season': 'all'
			})
			else: browse_params = build_url({
				'mode': 'build_season_list', 'tmdb_id': tmdb_id
			})
			browse_seas_params = build_url({
				'mode': 'build_episode_list', 'tmdb_id': tmdb_id, 'season': season
			})
			cm_append((self.cm_sort['options'], options_str, run_plugin % options_params))
			cm_append((self.cm_sort['extras'], extras_str, run_plugin % extras_params))
			cm_append((self.cm_sort['extras'], browse_str, self.container_update % browse_params))
			cm_append((self.cm_sort['extras'], browse_seas_str, self.container_update % browse_seas_params))
			if not unaired:
				if progress != '0' or resumetime != '0': cm_append((
					self.cm_sort['mark'], clearprog_str, run_plugin % build_url({
						'mode': 'watched_unwatched_erase_bookmark', 'mediatype': 'episode',
						'tmdb_id': tmdb_id, 'season': season, 'episode': episode, 'refresh': 'true'
				})))
				if playcount: cm_append((
					self.cm_sort['mark'], unwatched_str % self.watched_title, run_plugin % build_url({
						'mode': 'mark_as_watched_unwatched_episode', 'action': 'mark_as_unwatched', 'year': year,
						'tmdb_id': tmdb_id, 'tvdb_id': tvdb_id, 'season': season, 'episode': episode, 'title': title
				})))
				else: cm_append((
					self.cm_sort['mark'], watched_str % self.watched_title, run_plugin % build_url({
						'mode': 'mark_as_watched_unwatched_episode', 'action': 'mark_as_watched', 'year': year,
						'tmdb_id': tmdb_id, 'tvdb_id': tvdb_id, 'season': season, 'episode': episode,  'title': title
				})))
			if self.watched_indicators == 1: cm_append((
				self.cm_sort['trakt'], traktmanager_str, run_plugin % build_url({
					'mode': 'trakt_manager_choice', 'mediatype': 'tvshow',
					'tmdb_id': tmdb_id, 'imdb_id': imdb_id, 'tvdb_id': tvdb_id
			})))
			if self.watched_indicators == 2: cm_append((
				self.cm_sort['mdblist'], mdblmanager_str, run_plugin % build_url({
					'mode': 'mdbl_manager_choice', 'mediatype': 'tvshow',
					'tmdb_id': tmdb_id, 'imdb_id': imdb_id, 'tvdb_id': tvdb_id
			})))
			if self.watched_indicators == 3: cm_append((
				self.cm_sort['flicklist'], flicklistmanager_str, run_plugin % build_url({
					'mode': 'flickList_manager_choice', 'mediatype': 'tvshow',
					'tmdb_id': tmdb_id, 'imdb_id': imdb_id, 'tvdb_id': tvdb_id
			})))
			cm.sort(key=lambda k: k[0])
			cm = [v for k, *v in cm if k]
			props['episode_type'] = item_get('episode_type')
			props['watchedprogress'] = progress
			props['salts_unaired'] = 'true' if unaired else 'false'
			props['salts_name'] = '%s - %sx%s' % (title, str_season_zfill2, str_episode_zfill2)
			props['salts_first_aired'] = premiered
			listitem = kodi_utils.make_listitem()
			listitem.addContextMenuItems(cm)
			listitem.setProperties(props)
			listitem.setLabel(display)
			listitem.setArt(art_infodict(meta, self.art_provider, self.meta_user_info, item))
			if KODI_VERSION < 20:
				listitem.setUniqueIDs({'imdb': imdb_id, 'tmdb': string(tmdb_id), 'tvdb': string(tvdb_id)})
				listitem.setInfo('video', episode_infodict(meta, **item))
				listitem.setCast(cast + item_get('guest_stars', []))
				listitem.setProperty('resumetime', resumetime)
			else:
				videoinfo = info_tagger(listitem, episode_infodict(meta, **item))
				videoinfo.setTitle(display)
				videoinfo.setUniqueIDs({'imdb': imdb_id, 'tmdb': string(tmdb_id), 'tvdb': string(tvdb_id)})
				videoinfo.setCast(make_cast_list(cast + item_get('guest_stars', [])))
				videoinfo.setResumePoint(*set_resumetime(resumetime, progress, videoinfo.getDuration()))
			self.append((url_params, listitem, False))
		except: pass

class Menu(Episodes):
	def next_episode_filters(self):
		self.nextep_settings, nextep_disp_settings = nextep_content_settings(), nextep_display_settings()
		self.nextep_unaired_color, self.nextep_unwatched_color = nextep_disp_settings['unaired_color'], nextep_disp_settings['unwatched_color']
		self.nextep_include_airdate, self.nextep_include_unaired = nextep_disp_settings['include_airdate'], self.nextep_settings['include_unaired']
		if self.watched_indicators == 1:
			try:
				hidden_data = trakt_get_hidden_items('dropped')
				self.list = [i for i in self.list if not i['media_ids']['tmdb'] in hidden_data]
			except: pass
#			if self.nextep_settings['include_unwatched']:
#				try: unwatched = [
#					{'media_ids': i['media_ids'], 'season': 1, 'episode': 0, 'unwatched': True}
#					for i in trakt_fetch_collection_watchlist('watchlist', 'tvshow')
#				]
#				except: unwatched = []
#				if unwatched: self.list += unwatched
			self.resformat, self.resinsert = '%Y-%m-%dT%H:%M:%S.000Z', '2000-01-01T00:00:00.000Z'
		elif self.watched_indicators == 2:
			try:
				hidden_data = mdbl_get_hidden_items('dropped')
				self.list = [i for i in self.list if not i['media_ids']['tmdb'] in hidden_data]
			except: pass
			self.resformat, self.resinsert = '%Y-%m-%dT%H:%M:%SZ', '2000-01-01T00:00:00Z'
		elif self.watched_indicators == 3:
			try:
				hidden_data = flicklist_get_hidden_items('dropped')
				self.list = [i for i in self.list if not i['media_ids']['tmdb'] in hidden_data]
			except: pass
			self.resformat, self.resinsert = '%Y-%m-%dT%H:%M:%S.%fZ', '2000-01-01T00:00:00.%fZ'
		else: self.resformat, self.resinsert = '%Y-%m-%d %H:%M:%S', '2000-01-01 00:00:00'

	def worker(self):
#		threads = list(make_thread_list_enumerate(self.build_episode_content, self.list, Thread))
		for i in TaskPool().tasks_enumerate(self.build_episode_content, self.list, Thread): i.join()
		if self.list_type.startswith('next_episode'):
			def func(function):
				if sort_key == 'salts_name': return title_key_function(function, self.ignore_articles)
				elif sort_key == 'salts_last_played': return jsondate_to_datetime_function(function, self.resformat)
				else: return function
			def first_aired(item):
				return jsondate_to_datetime_function(item[1].getProperty('salts_first_aired'), '%Y-%m-%d').date()
			sort_key, sort_direction = self.nextep_settings['sort_key'], self.nextep_settings['sort_direction']
			self.items.sort(key=lambda k: func(k[1].getProperty(sort_key)), reverse=sort_direction)
			self.items.sort(key=lambda k: k[1].getProperty('salts_unaired') == 'true', reverse=False)
			if self.nextep_settings['sort_airing_today_to_top']:
				self.items.sort(key=lambda k: date_difference_function(self.current_date, first_aired(k), 0), reverse=True)
		elif self.list_type in ('trakt_calendar', 'trakt_recently_aired'):
			reverse = calendar_sort_order() == 0 if self.list_type == 'trakt_calendar' else True
			self.items.sort(key=lambda k: int(k[1].getProperty('salts_sort_order')))
			self.items.sort(key=lambda k: k[1].getProperty('salts_first_aired'), reverse=reverse)
		else: self.items.sort(key=lambda k: int(k[1].getProperty('salts_sort_order')))
		return self.items

	def run(self):
		try:
			params_get = self.params.get
			__handle__ = int(sys.argv[1])
			view_type, content_type = 'view.episodes_lists', 'episodes'
			sort_type, category = 'unsorted', ls(params_get('name'))
			mode = params_get('mode')
			if   'in_progress' in mode:
				self.list_type = 'in_progress'
				self.list = get_in_progress_episodes()
			elif 'next_episode' in mode:
				watched_info = get_watched_info_tv(self.watched_indicators)
				self.list_type = 'next_episode_salts'
				self.list = get_next_episodes(watched_info)
				self.next_episode_filters()
			elif 'my_calendar' in mode:
				recently_aired = params_get('recently_aired')
				self.list = trakt_get_my_calendar(recently_aired, get_datetime())
				if recently_aired:
					self.list_type = 'trakt_recently_aired'
					self.list = self.list[:20]
				else:
					self.list_type = 'trakt_calendar'
					self.list = sorted(self.list, key=lambda k: k['sort_title'])
			elif 'my_anime_calendar' in mode:
				self.list = trakt_my_anime_calendar(get_datetime())
				self.list_type = 'trakt_calendar'
				self.list = sorted(self.list, key=lambda k: k['sort_title'])
			elif 'anime_calendar' in mode:
				self.list = trakt_anime_calendar(get_datetime())
				self.list_type = 'trakt_calendar'
				self.list = sorted(self.list, key=lambda k: k['sort_title'])
			kodi_utils.add_items(__handle__, self.worker())
		except: pass
		if self.list_type == 'trakt_calendar' and calendar_focus_today():
			try:
				today = '[%s]' % ls(32849).upper()
				labels = enumerate([i[1].getLabel() for i in self.items], 1)
				index = max([i for i, x in labels if today in x])
			except: index = None
		else: index = False
		kodi_utils.set_category(__handle__, category)
		kodi_utils.set_sort_method(__handle__, sort_type)
		kodi_utils.set_content(__handle__, content_type)
		kodi_utils.end_directory(__handle__, False)
		kodi_utils.set_view_mode(view_type, content_type)
		if index: kodi_utils.focus_index(index)

