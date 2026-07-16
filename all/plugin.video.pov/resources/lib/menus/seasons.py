from threading import Thread
from indexers.metadata import tvshow_meta, season_episodes_meta, all_episodes_meta, episode_infodict, season_infodict, info_tagger, tmdb_image_base
from caches.watched_cache import get_watched_info_tv, get_watched_status_season, get_bookmarks, get_resumetime, set_resumetime, get_watched_status_episode
from modules import kodi_utils, settings
from modules.utils import adjust_premiered_date, get_datetime
# from modules.kodi_utils import logger

KODI_VERSION, make_cast_list = kodi_utils.get_kodi_version(), kodi_utils.make_cast_list
string, ls, build_url, default_duration = str, kodi_utils.local_string, kodi_utils.build_url, 3600
get_art_provider, show_specials = settings.get_art_provider, settings.show_specials
run_plugin, container_refresh, container_update = 'RunPlugin(%s)', 'Container.Refresh(%s)', 'Container.Update(%s)'
fanart_empty = kodi_utils.get_addoninfo('fanart')
poster_empty = kodi_utils.media_path('box_office.png')
watched_str, unwatched_str, extras_str, options_str = ls(32642), ls(32643), ls(32645), ls(32646)
clearprog_str, season_str, unaired_label = ls(32651), ls(32537), 'cyan'

class BaseSeason:
	def __init__(self, params):
		self.params = params
		self.items = []
		self.append = self.items.append
		self.current_date = get_datetime()
		self.meta_user_info = settings.metadata_user_info()
		self.watched_indicators = settings.watched_indicators()
		self.watched_title = settings.watched_title(self.watched_indicators)
		self.watched_info = get_watched_info_tv(self.watched_indicators)
		self.show_unaired = settings.show_unaired()
		self.use_season_title = settings.use_season_title()
		self.is_widget = kodi_utils.external_browse()
		self.image_resolution = self.meta_user_info['image_resolution']
		self.widget_hide_watched = self.is_widget and self.meta_user_info['widget_hide_watched']
		self.poster_main, self.poster_backup, self.fanart_main, self.fanart_backup = get_art_provider()

	def run(self):
		__handle__, is_widget = int(kodi_utils.argv1()), kodi_utils.external_browse()
		mode = self.params.get('mode', 'build_season_list')
		if 'episode' in mode: content_type, view_type = 'episodes', 'view.episodes'
		else: content_type, view_type = 'seasons', 'view.seasons'
		kodi_utils.add_items(__handle__, self.build_season_list(self.params))
		kodi_utils.set_category(__handle__, self.params.get('show_title'))
		kodi_utils.set_sort_method(__handle__, content_type)
		kodi_utils.set_content(__handle__, content_type)
		kodi_utils.end_directory(__handle__, False if is_widget else None)
		kodi_utils.set_view_mode(view_type, content_type, is_widget)

	def build_season_list(self, params):
		return self.items

class Seasons(BaseSeason):
	def build_season_list(self, params):
		show = MetaParser(params['tmdb_id'], self.meta_user_info, self.current_date,
			self.poster_main, self.poster_backup, self.fanart_main, self.fanart_backup)
		season_data = show.season_data
		if season_data:
			if 'season' in params: season_data = [i for i in season_data if i['season_number'] == params['season']]
			if not show_specials(): season_data = [i for i in season_data if i['season_number'] != 0]
			season_data.sort(key=lambda k: k['season_number'])
		else: season_data = []
		running_ep_count = show.total_aired_eps
		for item in season_data:
			try:
				cm = []
				cm_append = cm.append
				item_get = item.get
				season_number, episode_count = item_get('season_number'), item_get('episode_count')
				poster_path, name = item_get('poster_path'), item_get('name')
				if not episode_count: continue
				if poster_path: poster = tmdb_image_base % (self.image_resolution['poster'], poster_path)
				else: poster = show.poster
				if season_number == show.total_seasons:
					episode_date, premiered = adjust_premiered_date(item_get('air_date'), 0)
					unaired = True if not episode_date or self.current_date < episode_date else False
				else: unaired = episode_count == 0
				if unaired:
					if not self.show_unaired: continue
					episode_count = 0
				elif season_number != 0:
					episode_count = min(episode_count, running_ep_count)
					running_ep_count -= episode_count
				display = name if self.use_season_title and name else '%s %s' % (season_str, string(season_number))
				if unaired: display = '[COLOR %s][I]%s[/I][/COLOR]' % (unaired_label, display)
				if 'season' in params: display = '%s: %s' % (show.title, display)
				playcount, overlay, watched, unwatched = get_watched_status_season(
					self.watched_info, string(show.tmdb_id), season_number, episode_count
				)
				if self.widget_hide_watched and watched: continue
				item.update({'name': display, 'playcount': playcount, 'overlay': overlay})
				url_params = build_url({
					'mode': 'build_episode_list', 'tmdb_id': show.tmdb_id, 'season': season_number
				})
				extras_params = build_url({
					'mode': 'extras_menu_choice', 'mediatype': 'tvshow',
					'tmdb_id': show.tmdb_id, 'is_widget': self.is_widget
				})
				options_params = build_url({
					'mode': 'options_menu_choice', 'content': 'season',
					'tmdb_id': show.tmdb_id, 'season': season_number, 'is_widget': self.is_widget
				})
				cm_append((options_str, run_plugin % options_params))
				cm_append((extras_str, run_plugin % extras_params))
				if not playcount: cm_append((watched_str % self.watched_title, run_plugin % build_url({
					'mode': 'mark_as_watched_unwatched_season', 'action': 'mark_as_watched', 'year': show.year,
					'tmdb_id': show.tmdb_id, 'tvdb_id': show.tvdb_id, 'season': season_number, 'title': show.title
				})))
				if watched: cm_append((unwatched_str % self.watched_title, run_plugin % build_url({
					'mode': 'mark_as_watched_unwatched_season', 'action': 'mark_as_unwatched', 'year': show.year,
					'tmdb_id': show.tmdb_id, 'tvdb_id': show.tvdb_id, 'season': season_number, 'title': show.title
				})))
				props = {
					'pov_sort_order': string(params.get('sort', '')), 'totalepisodes': string(episode_count),
					'watchedepisodes': string(watched), 'unwatchedepisodes': string(unwatched)
				}
				listitem = kodi_utils.make_listitem()
				listitem.addContextMenuItems(cm)
				listitem.setProperties(props)
				listitem.setLabel(display)
				listitem.setArt({
					'poster': poster, 'fanart': show.fanart, 'icon': poster, 'clearlogo': show.clearlogo,
					'banner': show.banner, 'clearart': show.clearart, 'landscape': show.landscape, 'thumb': poster,
					'season.poster': poster, 'tvshow.poster': poster, 'tvshow.clearlogo': show.clearlogo,
					'tvshow.banner': show.banner, 'tvshow.clearart': show.clearart, 'tvshow.landscape': show.landscape
				})
				if KODI_VERSION < 20:
					listitem.setUniqueIDs({'imdb': show.imdb_id, 'tmdb': string(show.tmdb_id), 'tvdb': string(show.tvdb_id)})
					listitem.setInfo('video', season_infodict(show.meta, **item))
					listitem.setCast(show.cast)
				else:
					videoinfo = info_tagger(listitem, season_infodict(show.meta, **item))
					videoinfo.setTitle(display)
					videoinfo.setUniqueIDs({'imdb': show.imdb_id, 'tmdb': string(show.tmdb_id), 'tvdb': string(show.tvdb_id)})
					videoinfo.setCast(make_cast_list(show.cast))
				self.append((url_params, listitem, True))
			except: pass
		self.params['show_title'] = show.title
		return self.items

class Episodes(BaseSeason):
	def build_season_list(self, params):
		thumb_fanart = settings.thumb_fanart()
		adjust_hours = settings.date_offset()
		bookmarks = get_bookmarks(self.watched_indicators, 'episode')
		show = MetaParser(params['tmdb_id'], self.meta_user_info, self.current_date,
			self.poster_main, self.poster_backup, self.fanart_main, self.fanart_backup)
		if params.get('season') == 'all':
			episodes_data = all_episodes_meta(show.meta, self.meta_user_info, Thread)
			if not show_specials(): episodes_data = [i for i in episodes_data if i['season'] != 0]
		else: episodes_data = season_episodes_meta(params['season'], show.meta, self.meta_user_info)
		for item in episodes_data:
			try:
				cm = []
				cm_append = cm.append
				item_get = item.get
				season, episode, ep_name = item_get('season'), item_get('episode'), item_get('title')
				premiered, cast = item_get('premiered'), show.cast + item_get('guest_stars', [])
				season_poster = item_get('season_poster') or show.poster
				thumb = item_get('thumb') or show.fanart
				background = thumb if thumb_fanart else show.fanart
				episode_date, premiered = adjust_premiered_date(premiered, adjust_hours)
				if not episode_date or self.current_date < episode_date:
					if not self.show_unaired: continue
					if season != 0: display = '[COLOR %s][I]%s[/I][/COLOR]' % (unaired_label, ep_name)
					unaired = True
				else: display, unaired = ep_name, False
				playcount, overlay = get_watched_status_episode(self.watched_info, string(show.tmdb_id), season, episode)
				if self.widget_hide_watched and playcount and not unaired: continue
				resumetime, progress = get_resumetime(bookmarks, show.tmdb_id, season, episode)
				item.update({
					'title': display, 'premiered': premiered, 'playcount': playcount, 'overlay': overlay,
					'duration': item_get('duration') or show.duration or default_duration
				})
				url_params = build_url({
					'mode': 'play_media', 'mediatype': 'episode',
					'tmdb_id': show.tmdb_id, 'season': season, 'episode': episode
				})
				extras_params = build_url({
					'mode': 'extras_menu_choice', 'mediatype': 'tvshow',
					'tmdb_id': show.tmdb_id, 'is_widget': self.is_widget
				})
				options_params = build_url({
					'mode': 'options_menu_choice', 'content': 'episode',
					'tmdb_id': show.tmdb_id, 'season': season, 'episode': episode, 'is_widget': self.is_widget
				})
				cm_append((options_str, run_plugin % options_params))
				cm_append((extras_str, run_plugin % extras_params))
				clearprog_params, unwatched_params, watched_params = '', '', ''
				if not unaired:
					if progress != '0' or resumetime != '0': cm_append((clearprog_str, run_plugin % build_url({
						'mode': 'watched_unwatched_erase_bookmark', 'mediatype': 'episode',
						'tmdb_id': show.tmdb_id, 'season': season, 'episode': episode, 'refresh': 'true'
					})))
					if playcount: cm_append((unwatched_str % self.watched_title, run_plugin % build_url({
						'mode': 'mark_as_watched_unwatched_episode', 'action': 'mark_as_unwatched', 'year': show.year,
						'tmdb_id': show.tmdb_id, 'tvdb_id': show.tvdb_id, 'season': season, 'episode': episode, 'title': show.title
					})))
					else: cm_append((watched_str % self.watched_title, run_plugin % build_url({
						'mode': 'mark_as_watched_unwatched_episode', 'action': 'mark_as_watched', 'year': show.year,
						'tmdb_id': show.tmdb_id, 'tvdb_id': show.tvdb_id, 'season': season, 'episode': episode, 'title': show.title
					})))
				props = {'episode_type': item_get('episode_type'), 'watchedprogress': progress}
				listitem = kodi_utils.make_listitem()
				listitem.addContextMenuItems(cm)
				listitem.setProperties(props)
				listitem.setLabel(display)
				listitem.setArt({
					'poster': season_poster, 'fanart': background, 'icon': thumb, 'clearlogo': show.clearlogo,
					'banner': show.banner, 'clearart': show.clearart, 'landscape': thumb, 'thumb': thumb,
					'season.poster': season_poster, 'tvshow.poster': show.poster, 'tvshow.clearlogo': show.clearlogo,
					'tvshow.banner': show.banner, 'tvshow.clearart': show.clearart, 'tvshow.landscape': thumb
				})
				if KODI_VERSION < 20:
					listitem.setUniqueIDs({'imdb': show.imdb_id, 'tmdb': string(show.tmdb_id), 'tvdb': string(show.tvdb_id)})
					listitem.setInfo('video', episode_infodict(show.meta, **item))
					listitem.setCast(cast)
					listitem.setProperty('resumetime', resumetime)
				else:
					videoinfo = info_tagger(listitem, episode_infodict(show.meta, **item))
					videoinfo.setTitle(display)
					videoinfo.setUniqueIDs({'imdb': show.imdb_id, 'tmdb': string(show.tmdb_id), 'tvdb': string(show.tvdb_id)})
					videoinfo.setCast(make_cast_list(cast))
					videoinfo.setResumePoint(*set_resumetime(resumetime, progress, videoinfo.getDuration()))
				self.append((url_params, listitem, False))
			except: pass
		self.params['show_title'] = show.title
		return self.items

class MetaParser:
	direct = 'tmdb_id', 'tvdb_id', 'imdb_id', 'title', 'year', 'total_seasons', 'total_aired_eps', 'duration'
	__slots__ = (*direct, 'meta', 'cast', 'season_data', 'poster', 'fanart', 'clearlogo', 'banner', 'clearart', 'landscape')

	def __init__(self, tmdb_id, meta_user_info, current_date, poster_main, poster_backup, fanart_main, fanart_backup):
		self.meta = tvshow_meta('tmdb_id', tmdb_id, meta_user_info, current_date) or {}
		for i in self.direct: setattr(self, i, self.meta.get(i))
		self.cast = self.meta.get('cast') or []
		self.season_data = self.meta.get('season_data') or []
		self.poster = self.meta.get(poster_main) or self.meta.get(poster_backup) or poster_empty
		self.fanart = self.meta.get(fanart_main) or self.meta.get(fanart_backup) or fanart_empty
		self.clearlogo = self.meta.get('clearlogo') or ''
		self.banner, self.clearart, self.landscape = '', '', ''

