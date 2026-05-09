import sys
from threading import Thread
from indexers.metadata import tvshow_meta, season_episodes_meta, all_episodes_meta, episode_infodict, season_infodict, info_tagger, tmdb_image_base
from caches.watched_cache import get_watched_info_tv, get_watched_status_season, get_bookmarks, get_resumetime, set_resumetime, get_watched_status_episode
from modules import kodi_utils, settings
from modules.utils import adjust_premiered_date, get_datetime
# from modules.kodi_utils import logger

tv_meta_function, season_meta_function, default_duration = tvshow_meta, season_episodes_meta, 3600
KODI_VERSION, make_cast_list = kodi_utils.get_kodi_version(), kodi_utils.make_cast_list
string, ls, build_url = str, kodi_utils.local_string, kodi_utils.build_url
get_art_provider, show_specials = settings.get_art_provider, settings.show_specials
adjust_premiered_date_function, get_datetime_function = adjust_premiered_date, get_datetime
run_plugin, container_refresh, container_update = 'RunPlugin(%s)', 'Container.Refresh(%s)', 'Container.Update(%s)'
fanart_empty = kodi_utils.get_addoninfo('fanart')
poster_empty = kodi_utils.media_path('box_office.png')
watched_str, unwatched_str, extras_str, options_str = ls(32642), ls(32643), ls(32645), ls(32646)
clearprog_str, season_str, unaired_label = ls(32651), ls(32537), '[COLOR cyan]%s[/COLOR]'

class Seasons:
	def __init__(self, params):
		self.params = params
		self.items = []
		self.append = self.items.append
		self.current_date = get_datetime_function()
		self.meta_user_info = settings.metadata_user_info()
		self.watched_indicators = settings.watched_indicators()
		self.watched_title = settings.watched_title(self.watched_indicators)
		self.watched_info = get_watched_info_tv(self.watched_indicators)
		self.show_unaired = settings.show_unaired()
		self.is_widget = kodi_utils.external_browse()
		self.image_resolution = self.meta_user_info['image_resolution']
		self.widget_hide_watched = self.is_widget and self.meta_user_info['widget_hide_watched']
		self.poster_main, self.poster_backup, self.fanart_main, self.fanart_backup = get_art_provider()

	def build_season_list(self, params):
		def _process_season_list():
			use_season_title = settings.use_season_title()
			season_data = meta_get('season_data')
			if season_data:
				if 'season' in params: season_data = [i for i in season_data if i['season_number'] == params['season']]
				if not show_specials(): season_data = [i for i in season_data if not i['season_number'] == 0]
				season_data.sort(key=lambda k: k['season_number'])
			else: season_data = []
			running_ep_count = total_aired_eps
			for item in season_data:
				try:
					cm = []
					cm_append = cm.append
					item_get = item.get
					season_number, episode_count = item_get('season_number'), item_get('episode_count')
					poster_path, name = item_get('poster_path'), item_get('name')
					if poster_path: poster = tmdb_image_base % (self.image_resolution['poster'], poster_path)
					else: poster = show_poster
					if season_number == total_seasons:
						episode_airs = adjust_premiered_date_function(item_get('air_date'), 0)[0]
						unaired = True if not episode_airs or self.current_date < episode_airs else False
					elif episode_count == 0: unaired = True
					else: unaired = False
					if unaired:
						if not self.show_unaired: return
						episode_count = 0
					elif season_number != 0:
						running_ep_count -= episode_count
						if running_ep_count < 0: episode_count = running_ep_count + episode_count
					display = name if use_season_title and name else ' '.join([season_str, string(season_number)])
					if unaired: display = '[I]%s[/I]' % (unaired_label % display)
					if 'season' in params: display = '%s: %s' % (show_title, display)
					playcount, overlay, watched, unwatched = get_watched_status_season(self.watched_info, string(tmdb_id), season_number, episode_count)
					if self.widget_hide_watched and watched: continue
					item.update({'name': display, 'playcount': playcount, 'overlay': overlay})
					url_params = build_url({
						'mode': 'build_episode_list', 'tmdb_id': tmdb_id, 'season': season_number
					})
					if not playcount: cm_append((watched_str % self.watched_title, run_plugin % build_url({
						'mode': 'mark_as_watched_unwatched_season', 'action': 'mark_as_watched', 'year': show_year,
						'tmdb_id': tmdb_id, 'tvdb_id': tvdb_id, 'season': season_number, 'title': show_title
					})))
					if watched: cm_append((unwatched_str % self.watched_title, run_plugin % build_url({
						'mode': 'mark_as_watched_unwatched_season', 'action': 'mark_as_unwatched', 'year': show_year,
						'tmdb_id': tmdb_id, 'tvdb_id': tvdb_id, 'season': season_number, 'title': show_title
					})))
					props = {
						'salts_sort_order': string(params.get('sort', '')), 'totalepisodes': string(episode_count),
						'watchedepisodes': string(watched), 'unwatchedepisodes': string(unwatched)
					}
					listitem = kodi_utils.make_listitem()
					listitem.addContextMenuItems(cm)
					listitem.setProperties(props)
					listitem.setLabel(display)
					listitem.setArt({
						'poster': poster, 'fanart': fanart, 'icon': poster, 'clearlogo': clearlogo,
						'banner': banner, 'clearart': clearart, 'landscape': landscape, 'thumb': poster,
						'season.poster': poster, 'tvshow.poster': poster, 'tvshow.clearlogo': clearlogo,
						'tvshow.banner': banner, 'tvshow.clearart': clearart, 'tvshow.landscape': landscape
					})
					if KODI_VERSION < 20:
						listitem.setUniqueIDs({'imdb': imdb_id, 'tmdb': string(tmdb_id), 'tvdb': string(tvdb_id)})
						listitem.setInfo('video', season_infodict(meta, **item))
						listitem.setCast(show_cast)
					else:
						videoinfo = info_tagger(listitem, season_infodict(meta, **item))
						videoinfo.setTitle(display)
						videoinfo.setUniqueIDs({'imdb': imdb_id, 'tmdb': string(tmdb_id), 'tvdb': string(tvdb_id)})
						videoinfo.setCast(make_cast_list(show_cast))
					self.append((url_params, listitem, True))
				except: pass
		def _process_episode_list():
			thumb_fanart = settings.thumb_fanart()
			adjust_hours = settings.date_offset()
			bookmarks = get_bookmarks(self.watched_indicators, 'episode')
			all_episodes = True if params.get('season') == 'all' else False
			if all_episodes:
				episodes_data = all_episodes_meta(meta, self.meta_user_info, Thread)
				if not show_specials(): episodes_data = [i for i in episodes_data if not i['season'] == 0]
			else: episodes_data = season_meta_function(params['season'], meta, self.meta_user_info)
			for item in episodes_data:
				try:
					cm = []
					cm_append = cm.append
					item_get = item.get
					season, episode, ep_name = item_get('season'), item_get('episode'), item_get('title')
					premiered, cast = item_get('premiered'), show_cast + item_get('guest_stars', [])
					season_poster = item_get('season_poster') or show_poster
					thumb = item_get('thumb') or fanart
					background = thumb if thumb_fanart else fanart
					episode_date, premiered = adjust_premiered_date_function(premiered, adjust_hours)
					if not episode_date or self.current_date < episode_date:
						if not self.show_unaired: continue
						if season != 0: display = '[I]%s[/I]' % (unaired_label % ep_name)
						unaired = True
					else: display, unaired = ep_name, False
					playcount, overlay = get_watched_status_episode(self.watched_info, string(tmdb_id), season, episode)
					if self.widget_hide_watched and playcount and not unaired: continue
					resumetime, progress = get_resumetime(bookmarks, tmdb_id, season, episode)
					item.update({
						'title': display, 'premiered': premiered, 'playcount': playcount, 'overlay': overlay,
						'duration': item_get('duration') or meta_get('duration') or default_duration
					})
					url_params = build_url({
						'mode': 'play_media', 'mediatype': 'episode',
						'tmdb_id': tmdb_id, 'imdb_id': imdb_id, 'season': season, 'episode': episode
					})
					extras_params = build_url({
						'mode': 'extras_menu_choice', 'mediatype': 'tvshow',
						'tmdb_id': tmdb_id, 'is_widget': self.is_widget
					})
					options_params = build_url({
						'mode': 'options_menu_choice', 'content': 'episode',
						'tmdb_id': tmdb_id, 'season': season, 'episode': episode, 'is_widget': self.is_widget
					})
					cm_append((options_str, run_plugin % options_params))
					cm_append((extras_str, run_plugin % extras_params))
					clearprog_params, unwatched_params, watched_params = '', '', ''
					if not unaired:
						if progress != '0' or resumetime != '0': cm_append((clearprog_str, run_plugin % build_url({
							'mode': 'watched_unwatched_erase_bookmark', 'mediatype': 'episode',
							'tmdb_id': tmdb_id, 'season': season, 'episode': episode, 'refresh': 'true'
						})))
						if playcount: cm_append((unwatched_str % self.watched_title, run_plugin % build_url({
							'mode': 'mark_as_watched_unwatched_episode', 'action': 'mark_as_unwatched', 'year': show_year,
							'tmdb_id': tmdb_id, 'tvdb_id': tvdb_id, 'season': season, 'episode': episode, 'title': show_title
						})))
						else: cm_append((watched_str % self.watched_title, run_plugin % build_url({
							'mode': 'mark_as_watched_unwatched_episode', 'action': 'mark_as_watched', 'year': show_year,
							'tmdb_id': tmdb_id, 'tvdb_id': tvdb_id, 'season': season, 'episode': episode, 'title': show_title
						})))
					props = {'episode_type': item_get('episode_type'), 'watchedprogress': progress}
					listitem = kodi_utils.make_listitem()
					listitem.addContextMenuItems(cm)
					listitem.setProperties(props)
					listitem.setLabel(display)
					listitem.setArt({
						'poster': season_poster, 'fanart': background, 'icon': thumb, 'clearlogo': clearlogo,
						'banner': banner, 'clearart': clearart, 'landscape': thumb, 'thumb': thumb,
						'season.poster': season_poster, 'tvshow.poster': show_poster, 'tvshow.clearlogo': clearlogo,
						'tvshow.banner': banner, 'tvshow.clearart': clearart, 'tvshow.landscape': thumb
					})
					if KODI_VERSION < 20:
						listitem.setUniqueIDs({'imdb': imdb_id, 'tmdb': string(tmdb_id), 'tvdb': string(tvdb_id)})
						listitem.setInfo('video', episode_infodict(meta, **item))
						listitem.setCast(cast)
						listitem.setProperty('resumetime', resumetime)
					else:
						videoinfo = info_tagger(listitem, episode_infodict(meta, **item))
						videoinfo.setTitle(display)
						videoinfo.setUniqueIDs({'imdb': imdb_id, 'tmdb': string(tmdb_id), 'tvdb': string(tvdb_id)})
						videoinfo.setCast(make_cast_list(cast))
						videoinfo.setResumePoint(*set_resumetime(resumetime, progress, videoinfo.getDuration()))
					self.append((url_params, listitem, False))
				except: pass
		meta = tv_meta_function('tmdb_id', params['tmdb_id'], self.meta_user_info, self.current_date)
		meta_get = meta.get
		tmdb_id, tvdb_id, imdb_id = meta_get('tmdb_id'), meta_get('tvdb_id'), meta_get('imdb_id')
		show_title, show_year, show_cast = meta_get('title'), meta_get('year'), meta_get('cast', [])
		total_seasons, total_aired_eps = meta_get('total_seasons'), meta_get('total_aired_eps')
		show_poster = meta_get(self.poster_main) or meta_get(self.poster_backup) or poster_empty
		fanart = meta_get(self.fanart_main) or meta_get(self.fanart_backup) or fanart_empty
		clearlogo = meta_get('clearlogo') or ''
		banner, clearart, landscape = '', '', ''
		mode = self.params.get('mode', 'build_season_list')
		if 'episode' in mode: _process_episode_list()
		else: _process_season_list()
		self.params['show_title'] = show_title
		return self.items

	def run(self):
		__handle__, is_widget = int(sys.argv[1]), kodi_utils.external_browse()
		mode = self.params.get('mode', 'build_season_list')
		if 'episode' in mode: content_type, view_type = 'episodes', 'view.episodes'
		else: content_type, view_type = 'seasons', 'view.seasons'
		kodi_utils.add_items(__handle__, self.build_season_list(self.params))
		kodi_utils.set_category(__handle__, self.params.get('show_title'))
		kodi_utils.set_sort_method(__handle__, content_type)
		kodi_utils.set_content(__handle__, content_type)
		kodi_utils.end_directory(__handle__, False if is_widget else None)
		kodi_utils.set_view_mode(view_type, content_type)

