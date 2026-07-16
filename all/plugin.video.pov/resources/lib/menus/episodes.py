from threading import Thread
from indexers.metadata import tvshow_meta, season_episodes_meta, art_infodict, episode_infodict, info_tagger
from indexers.trakt_api import trakt_fetch_collection_watchlist, trakt_get_my_calendar, trakt_get_my_anime_calendar, trakt_anime_calendar
from caches.watched_cache import get_resumetime, set_resumetime, get_watched_status_episode, get_watched_info_tv, get_bookmarks, get_next_episodes, get_in_progress_items
from modules import kodi_utils, settings
#from modules.utils import jsondate_to_datetime, adjust_premiered_date, make_day, get_datetime, title_key, date_difference, make_thread_list_enumerate
from modules.utils import get_next_episode_pointer, adjust_premiered_date, make_day, get_datetime, title_key, date_difference, TaskPool
# logger = kodi_utils.logger

KODI_VERSION, make_cast_list = kodi_utils.get_kodi_version(), kodi_utils.make_cast_list
string, ls, build_url, default_duration = str, kodi_utils.local_string, kodi_utils.build_url, 3600
calendar_sort_order, calendar_focus_today = settings.calendar_sort_order, settings.calendar_focus_today
nextep_content_settings, nextep_display_settings = settings.nextep_content_settings, settings.nextep_display_settings
thumb_fanart_info, default_all_episodes = settings.thumb_fanart, settings.default_all_episodes
single_ep_display_title, single_ep_format = settings.single_ep_display_title, settings.single_ep_format
date_difference_function, make_day_function, title_key_function = date_difference, make_day, title_key
dt_formats = ('1970-01-01 00:00:00', '1970-01-01T00:00:00.000Z', '1970-01-01T00:00:00Z')
run_plugin, container_refresh, container_update = 'RunPlugin(%s)', 'Container.Refresh(%s)', 'Container.Update(%s)'
fanart_empty = kodi_utils.get_addoninfo('fanart')
poster_empty = kodi_utils.media_path('box_office.png')
watched_str, unwatched_str, extras_str, options_str = ls(32642), ls(32643), ls(32645), ls(32646)
clearprog_str, browse_str, browse_seas_str, today_str = ls(32651), ls(32652), ls(32544), ls(32849).upper()
traktmanager_str, mdblmanager_str, unaired_label, date_label = ls(32198), ls(32200), 'cyan', 'magenta'

class Episodes:
	def __init__(self, params):
		self.params = params
		self.list_type = self.params.get('id_type', '')
		self.list = self.params.get('list', [])
		self.items = []
		self.append = self.items.append
		self.current_date = get_datetime()
		self.adjust_hours = settings.date_offset()
		self.meta_user_info = settings.metadata_user_info()
		self.watched_indicators = settings.watched_indicators()
		self.watched_title = settings.watched_title(self.watched_indicators)
		self.watched_info = get_watched_info_tv(self.watched_indicators)
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
		self.container_update = ('Container.Update(%s)', 'ActivateWindow(Videos,%s,return)')[self.is_widget]
		self.resinsert = dt_formats[self.watched_indicators]

	def build_episode_content(self, position, ep_data):
		try:
			ep_data_get = ep_data.get
			meta = tvshow_meta('trakt_dict', ep_data_get('media_ids'), self.meta_user_info, self.current_date)
			meta_get = meta.get
			if not meta: return
			if self.list_type.startswith('next_episode'):
				props = {'pov_last_played': ep_data_get('last_played', self.resinsert)}
				sn, en = int(ep_data_get('season')), int(ep_data_get('episode'))
				orig_season, orig_episode, new_season = get_next_episode_pointer(meta, sn, en)
				if new_season and orig_season > meta_get('total_seasons'): return
			else:
				props = {'pov_sort_order': string(ep_data_get('sort', position))}
				orig_season, orig_episode = ep_data_get('season'), ep_data_get('episode')
			episodes_data = season_episodes_meta(orig_season, meta, self.meta_user_info)
			try: item = next((i for i in episodes_data if i['episode'] == orig_episode))
			except: return
			cm = []
			cm_append = cm.append
			item_get = item.get
			item['background'] = item_get('thumb') if self.thumb_fanart else ''
			tmdb_id, tvdb_id, imdb_id = meta_get('tmdb_id'), meta_get('tvdb_id'), meta_get('imdb_id')
			title, year, total_seasons = meta_get('title'), meta_get('year'), meta_get('total_seasons')
			cast, episode_run_time = meta_get('cast', []), meta_get('duration')
			season, episode = item_get('season'), item_get('episode')
			orig_premiered, ep_name = item_get('premiered'), item_get('title')
			str_season_zfill2, str_episode_zfill2 = string(season).zfill(1), string(episode).zfill(2)
			episode_date, premiered = adjust_premiered_date(orig_premiered, self.adjust_hours)
			if not episode_date or self.current_date < episode_date:
				if self.list_type.startswith('next_episode'):
					if not self.nextep_include_unaired or not episode_date: return
					if new_season and not date_difference_function(self.current_date, episode_date, 7): return
				if not self.show_unaired: return
				unaired = True
			else: unaired = False
			if self.list_type.startswith('next_episode'): playcount, overlay = 0, 4
			else: playcount, overlay = get_watched_status_episode(self.watched_info, string(tmdb_id), season, episode)
			if self.widget_hide_watched and playcount and not unaired: return
			resumetime, progress = get_resumetime(self.bookmarks, tmdb_id, season, episode)
			display = self._format_title(title, season, episode, ep_name, episode_date, unaired, ep_data_get('unwatched', False))
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
				'tmdb_id': tmdb_id, 'season': season, 'episode': episode
			})
			if self.all_episodes and self.all_episodes == 1 and total_seasons > 1: browse_params = build_url({
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
			cm.sort(key=lambda k: k[0])
			cm = [v for k, *v in cm if k]
			props['episode_type'] = item_get('episode_type')
			props['watchedprogress'] = progress
			props['pov_unaired'] = 'true' if unaired else 'false'
			props['pov_name'] = '%s - %sx%s' % (title, str_season_zfill2, str_episode_zfill2)
			props['pov_first_aired'] = premiered
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

	def _format_title(self, title, season, episode, ep_name, episode_date, unaired, unwatched):
		str_season, str_episode = string(season).zfill(1), string(episode).zfill(2)
		title_string = ''.join([title, ': ']) if self.display_title == 0 else ''
		seas_ep = ''.join([str_season, 'x', str_episode, ' - ']) if self.display_title in (0, 1) else ''
		if self.list_type.startswith('next_episode') or self.list_type == 'trakt_calendar':
			if episode_date: display_premiered = make_day_function(self.current_date, episode_date, self.date_format)
			else: display_premiered = 'UNKNOWN'
			if self.list_type.startswith('next_episode'):
				airdate = ('[[COLOR ', date_label, ']', display_premiered, '[/COLOR]] ') if self.nextep_include_airdate else ''
				if unaired: highlight_color = self.nextep_unaired_color
				else: highlight_color = self.nextep_unwatched_color if unwatched else ''
			else: # trakt_calendar
				airdate = ('[[COLOR ', date_label, ']', display_premiered, '[/COLOR]] ')
				highlight_color = unaired_label if unaired else ''
			italics_open, italics_close = ('[I]', '[/I]') if highlight_color else ('', '')
			if highlight_color:
				episode_info = seas_ep, '[COLOR', highlight_color, ']', italics_open, ep_name, italics_close, '[/COLOR]'
			else: episode_info = seas_ep, italics_open, ep_name, italics_close
			return ''.join([''.join(airdate), title_string.upper(), ''.join(episode_info)])
		if unaired: ep_name = '[COLOR %s][I]%s[/I][/COLOR]' % (unaired_label, ep_name)
		return ''.join([title_string.upper(), seas_ep, ep_name])

class Menu(Episodes):
	def worker(self):
#		threads = list(make_thread_list_enumerate(self.build_episode_content, self.list, Thread))
		for i in TaskPool().tasks_enumerate(self.build_episode_content, self.list, Thread): i.join()
		if self.list_type.startswith('next_episode'): self._sort_next_episode()
		elif self.list_type in ('trakt_calendar', 'trakt_recently_aired'): self._sort_calendar()
		else: self.items.sort(key=lambda k: int(k[1].getProperty('pov_sort_order')))
		return self.items

	def run(self):
		__handle__ = int(kodi_utils.argv1())
		params_get = self.params.get
		view_type, content_type = 'view.episodes_lists', 'episodes'
		sort_type, category = 'unsorted', ls(params_get('name'))
		mode = params_get('mode')
		func = next((i for key, i in {
			'in_progress': self._setup_in_progress,
			'next_episode': self._setup_next_episode,
			'my_calendar': self._setup_my_calendar,
			'my_anime_calendar': self._setup_my_anime_calendar,
			'anime_calendar': self._setup_anime_calendar
		}.items() if key in mode), None)
		if callable(func): func(params_get)
		if self.list: kodi_utils.add_items(__handle__, self.worker())
		if self.list_type == 'trakt_calendar' and calendar_focus_today():
			labels = enumerate((i[1].getLabel() for i in self.items), 1)
			index = next((i for i, x in labels if today_str in x), None)
		else: index = False
		kodi_utils.set_category(__handle__, category)
		kodi_utils.set_sort_method(__handle__, sort_type)
		kodi_utils.set_content(__handle__, content_type)
		kodi_utils.end_directory(__handle__, False)
		kodi_utils.set_view_mode(view_type, content_type, self.is_widget)
		if index: kodi_utils.focus_index(index)

	def _setup_in_progress(self, params_get):
		self.list_type = 'in_progress'
		self.list = get_in_progress_items(self.bookmarks, 'episode')

	def _setup_next_episode(self, params_get):
		self.list_type = 'next_episode_pov'
		self.list = get_next_episodes(self.watched_indicators)
		self.nextep_settings, nextep_disp_settings = nextep_content_settings(), nextep_display_settings()
		self.nextep_include_unaired = self.nextep_settings['include_unaired']
		self.nextep_include_airdate = nextep_disp_settings['include_airdate']
		self.nextep_unwatched_color = nextep_disp_settings['unwatched_color']
		self.nextep_unaired_color = nextep_disp_settings['unaired_color']
#		if self.watched_indicators != 1: return
#		if not self.nextep_settings['include_unwatched']: return
#		items = trakt_fetch_collection_watchlist('watchlist', 'tvshow')
#		watchlist = ({'media_ids': i['media_ids'], 'season': 1, 'episode': 0, 'unwatched': True} for i in items)
#		try: self.list.extend(watchlist)
#		except: pass

	def _setup_my_calendar(self, params_get):
		recently_aired = params_get('recently_aired')
		self.list = trakt_get_my_calendar(recently_aired, self.current_date)
		if recently_aired:
			self.list_type = 'trakt_recently_aired'
			self.list = self.list[:20]
		else:
			self.list_type = 'trakt_calendar'
			self.list = sorted(self.list, key=lambda k: k['sort_title'])

	def _setup_my_anime_calendar(self, params_get):
		self.list = sorted(trakt_get_my_anime_calendar(self.current_date), key=lambda k: k['sort_title'])
		self.list_type = 'trakt_calendar'

	def _setup_anime_calendar(self, params_get):
		self.list = sorted(trakt_anime_calendar(self.current_date), key=lambda k: k['sort_title'])
		self.list_type = 'trakt_calendar'

	def _sort_next_episode(self):
		def func(function):
			if sort_key == 'pov_name': return title_key_function(function, self.ignore_articles)
			return function
		def aired_today(item):
			return str(item.getProperty('pov_first_aired')) == str(self.current_date)
		sort_key, sort_direction = self.nextep_settings['sort_key'], self.nextep_settings['sort_direction']
		sort_airing_today_to_top = self.nextep_settings['sort_airing_today_to_top']
		self.items.sort(key=lambda k: func(k[1].getProperty(sort_key)), reverse=sort_direction)
		self.items.sort(key=lambda k: k[1].getProperty('pov_unaired') == 'true', reverse=False)
		if sort_airing_today_to_top: self.items.sort(key=lambda k: aired_today(k[1]), reverse=True)

	def _sort_calendar(self):
		reverse = calendar_sort_order() == 0 if self.list_type == 'trakt_calendar' else True
		self.items.sort(key=lambda k: int(k[1].getProperty('pov_sort_order')))
		self.items.sort(key=lambda k: k[1].getProperty('pov_first_aired'), reverse=reverse)


