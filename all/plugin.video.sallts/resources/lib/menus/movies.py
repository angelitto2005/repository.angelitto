import sys
from threading import Thread
from indexers.metadata import movie_meta, art_infodict, movie_show_infodict, tmdb_image_base
from caches.watched_cache import get_watched_info_movie, get_watched_status_movie, get_bookmarks, get_resumetime, set_resumetime
from modules import kodi_utils, settings
#from modules.utils import manual_function_import, get_datetime, make_thread_list_enumerate
from modules.utils import manual_function_import, get_datetime, TaskPool
# logger = kodi_utils.logger

movie_meta_function, get_datetime_function, default_duration = movie_meta, get_datetime, 5400
get_watched_function, get_watched_info_function = get_watched_status_movie, get_watched_info_movie
KODI_VERSION, make_cast_list = kodi_utils.get_kodi_version(), kodi_utils.make_cast_list
string, ls, build_url, get_infolabel = str, kodi_utils.local_string, kodi_utils.build_url, kodi_utils.get_infolabel
run_plugin, container_refresh, container_update = 'RunPlugin(%s)', 'Container.Refresh(%s)', 'Container.Update(%s)'
fanart_empty = kodi_utils.get_addoninfo('fanart')
poster_empty = kodi_utils.media_path('box_office.png')
item_jump = kodi_utils.media_path('item_jump.png')
item_next = kodi_utils.media_path('item_next.png')
watched_str, unwatched_str, traktmanager_str = ls(32642), ls(32643), ls(32198)
favmanager_str, extras_str, options_str, recomm_str = ls(32197), ls(32645), ls(32646), '[B]%s...[/B]' % ls(32503)
hide_str, exit_str, clearprog_str, play_str = ls(32648), ls(32649), ls(32651), '[B]%s...[/B]' % ls(32174)
nextpage_str, switchjump_str, jumpto_str = ls(32799), ls(32784), ls(32964)
mdblmanager_str, flicklistmanager_str = ls(32200), '[B]FlickList Manager[/B]'

class Movies:
	def __init__(self, params):
		self.params = params
		self.id_type = self.params.get('id_type', 'tmdb_id')
		self.list = self.params.get('list', [])
		self.action = self.params.get('action')
		self.exit_list_params = self.params.get('exit_list_params')
		self.items, self.new_page, self.total_pages = [], {}, None
		self.append = self.items.append
		self.current_date = get_datetime_function()
		self.meta_user_info = settings.metadata_user_info()
		self.watched_indicators = settings.watched_indicators()
		self.watched_title = settings.watched_title(self.watched_indicators)
		self.watched_info = get_watched_info_function(self.watched_indicators)
		self.bookmarks = get_bookmarks(self.watched_indicators, 'movie')
		self.include_year_in_title = settings.include_year_in_title('movie')
		self.open_extras = settings.extras_open_action('movie')
		self.cm_sort = settings.context_menu_sort()
		self.is_widget = kodi_utils.external_browse()
		self.widget_hide_watched = self.is_widget and self.meta_user_info['widget_hide_watched']
		if not self.exit_list_params: self.exit_list_params = get_infolabel('Container.FolderPath')
		self.art_provider = (*settings.get_art_provider(), poster_empty, fanart_empty)

	def build_movie_content(self, position, tag):
		try:
			meta = movie_meta_function(self.id_type, tag, self.meta_user_info, self.current_date)
			meta_get = meta.get
			if not meta or meta_get('blank_entry', False): return
			playcount, overlay = get_watched_function(self.watched_info, string(meta['tmdb_id']))
			if self.widget_hide_watched and playcount: return
			meta.update({'playcount': playcount, 'overlay': overlay})
			resumetime, progress = get_resumetime(self.bookmarks, string(meta['tmdb_id']))
			cm = []
			cm_append = cm.append
			rootname, title, year = meta_get('rootname'), meta_get('title'), meta_get('year')
			display = rootname if self.include_year_in_title else title
			tmdb_id, imdb_id = meta_get('tmdb_id'), meta_get('imdb_id')
			play_params = build_url({
				'mode': 'play_media', 'mediatype': 'movie', 'tmdb_id': tmdb_id, 'imdb_id': imdb_id
			})
			extras_params = build_url({
				'mode': 'extras_menu_choice', 'mediatype': 'movie',
				'tmdb_id': tmdb_id, 'is_widget': self.is_widget
			})
			options_params = build_url({
				'mode': 'options_menu_choice', 'mediatype': 'movie',
				'tmdb_id': tmdb_id, 'is_widget': self.is_widget
			})
			recommended_params = build_url({
				'mode': 'build_movie_list', 'action': 'tmdb_movies_recommendations', 'tmdb_id': tmdb_id
			})
			trakt_manager_params = build_url({
				'mode': 'trakt_manager_choice', 'mediatype': 'movie',
				'tmdb_id': tmdb_id, 'imdb_id': imdb_id, 'tvdb_id': 'None'
			})
			mdbl_manager_params = build_url({
				'mode': 'mdbl_manager_choice', 'mediatype': 'movie',
				'tmdb_id': tmdb_id, 'imdb_id': imdb_id, 'tvdb_id': 'None'
			})
			flicklist_manager_params = build_url({
				'mode': 'flicklist_manager_choice', 'mediatype': 'movie',
				'tmdb_id': tmdb_id, 'imdb_id': imdb_id, 'tvdb_id': 'None'
			})
			fav_manager_params = build_url({
				'mode': 'favorites_choice', 'mediatype': 'movie',
				'tmdb_id': tmdb_id, 'title': title
			})
			cm_append((self.cm_sort['options'], options_str, run_plugin % options_params))
			if self.open_extras:
				url_params = extras_params
				cm_append((self.cm_sort['extras'], play_str, run_plugin % play_params))
			else:
				url_params = play_params
				cm_append((self.cm_sort['extras'], extras_str, run_plugin % extras_params))
			cm_append((self.cm_sort['trakt'], traktmanager_str, run_plugin % trakt_manager_params))
			cm_append((self.cm_sort['mdblist'], mdblmanager_str, run_plugin % mdbl_manager_params))
			cm_append((self.cm_sort['flicklist'], flicklistmanager_str, run_plugin % flicklist_manager_params))
			cm_append((self.cm_sort['favorites'], favmanager_str, run_plugin % fav_manager_params))
			if progress != '0' or resumetime != '0': cm_append((
				self.cm_sort['mark'], clearprog_str, run_plugin % build_url({
					'mode': 'watched_unwatched_erase_bookmark', 'mediatype': 'movie',
					'tmdb_id': tmdb_id, 'refresh': 'true'
			})))
			if playcount: cm_append((
				self.cm_sort['mark'], unwatched_str % self.watched_title, run_plugin % build_url({
					'mode': 'mark_as_watched_unwatched_movie', 'action': 'mark_as_unwatched',
					'tmdb_id': tmdb_id, 'title': title, 'year': year
			})))
			else: cm_append((
				self.cm_sort['mark'], watched_str % self.watched_title, run_plugin % build_url({
					'mode': 'mark_as_watched_unwatched_movie', 'action': 'mark_as_watched',
					'tmdb_id': tmdb_id, 'title': title, 'year': year
			})))
			cm_append((self.cm_sort['exit'], exit_str, container_refresh % self.exit_list_params))
			cm.sort(key=lambda k: k[0])
			cm = [v for k, *v in cm if k]
			props = {'salts_sort_order': string(position), 'watchedprogress': progress}
			listitem = kodi_utils.make_listitem()
			listitem.addContextMenuItems(cm)
			listitem.setProperties(props)
			listitem.setLabel(display)
			listitem.setArt(art_infodict(meta, self.art_provider, self.meta_user_info))
			if KODI_VERSION < 20:
				listitem.setUniqueIDs({'imdb': imdb_id, 'tmdb': string(tmdb_id)})
				listitem.setInfo('video', movie_show_infodict(meta))
				listitem.setCast(meta_get('cast', []))
				listitem.setProperty('resumetime', resumetime)
			else:
				videoinfo = listitem.getVideoInfoTag(offscreen=True)
				videoinfo.setTitle(display)
				videoinfo.setUniqueIDs({'imdb': imdb_id, 'tmdb': string(tmdb_id)})
				videoinfo.setCast(make_cast_list(meta_get('cast', [])))
				videoinfo.setCountries(meta_get('country'))
				videoinfo.setDirectors(meta_get('director').split(', '))
				videoinfo.setDuration(int(meta_get('duration') or default_duration))
				videoinfo.setGenres(meta_get('genre').split(', '))
				videoinfo.setIMDBNumber(imdb_id)
				videoinfo.setMediaType('movie')
				videoinfo.setMpaa(meta_get('mpaa'))
				videoinfo.setPlaycount(playcount)
				videoinfo.setPlot(meta_get('plot'))
				videoinfo.setPremiered(meta_get('premiered'))
				videoinfo.setRating(meta_get('rating'))
				videoinfo.setResumePoint(*set_resumetime(resumetime, progress, videoinfo.getDuration()))
				videoinfo.setStudios((meta_get('studio'),))
				videoinfo.setTagLine(meta_get('tagline'))
				videoinfo.setTags((imdb_id, string(tmdb_id)))
				videoinfo.setTrailer(meta_get('trailer'))
				videoinfo.setVotes(meta_get('votes'))
				videoinfo.setWriters(meta_get('writer').split(', '))
			self.append((url_params, listitem, False))
		except: pass

class Menu(Movies):
	personal_dict = {'in_progress_movies': ('caches.watched_cache', 'get_in_progress_movies'), 'favorites_movies': ('caches.favorites_cache', 'get_favorites'), 'watched_movies': ('caches.watched_cache', 'get_watched_items')}
	tmdb_special_key_dict = {'tmdb_movies_networks': 'company', 'tmdb_movies_year': 'year', 'tmdb_moviesanime_year': 'year'}
	tmdb_main = ('tmdb_movies_popular', 'tmdb_movies_latest_releases', 'tmdb_movies_premieres', 'tmdb_movies_upcoming', 'tmdb_movies_blockbusters', 'tmdb_moviesanime_popular', 'tmdb_moviesanime_latest_releases')
	trakt_main = ('trakt_movies_trending', 'trakt_movies_trending_recent', 'trakt_movies_most_watched', 'trakt_moviesanime_trending', 'trakt_moviesanime_most_watched')
	trakt_personal = ('trakt_collection', 'trakt_watchlist', 'trakt_favorites', 'trakt_collection_lists')
	mdblist_personal = ('mdblist_collection', 'mdblist_watchlist')
	flicklist_personal = ('flicklist_watchlist', 'flicklist_favorites')
	similar = ('tmdb_movies_similar', 'tmdb_movies_recommendations')

	def build_movies_results(self):
#		threads = list(make_thread_list_enumerate(self.build_movie_content, self.list, Thread))
		for i in TaskPool().tasks_enumerate(self.build_movie_content, self.list, Thread): i.join()
		self.items.sort(key=lambda k: int(k[1].getProperty('salts_sort_order')))
		return self.items

	def build_collections_results(self):
		image_resolution = self.meta_user_info['image_resolution']
		for item in self.list:
			try:
				url_params = build_url({'mode': 'build_movie_list', 'action': 'tmdb_movies_collection', 'collection_id': item['id']})
				poster_path, backdrop_path = item['poster_path'], item['backdrop_path']
				if poster_path: poster = tmdb_image_base % (image_resolution['poster'], poster_path)
				else: poster = poster_empty
				if backdrop_path: fanart = tmdb_image_base % (image_resolution['fanart'], backdrop_path)
				else: fanart = fanart_empty
				listitem = kodi_utils.make_listitem()
				listitem.setLabel(item['name'])
				listitem.setInfo('Video', {'plot': item['overview']})
				listitem.setArt({'icon': poster, 'fanart': fanart})
				self.append((url_params, listitem, True))
			except: pass
		return self.items

	def run(self):
		try:
			params_get = self.params.get
			__handle__ = int(sys.argv[1])
			worker, view_type, content_type = self.build_movies_results, 'view.movies', 'movies'
			mode = params_get('mode')
			try: page_no = int(params_get('new_page', '1'))
			except ValueError: page_no = params_get('new_page')
			letter = params_get('new_letter', 'None')
			if self.action in Menu.personal_dict: var_module, import_function = Menu.personal_dict[self.action]
			else: var_module, import_function = 'indexers.%s_api' % self.action.split('_')[0], self.action
			try: function = manual_function_import(var_module, import_function)
			except: pass
			if self.action in Menu.tmdb_main:
				data = function(page_no)
				self.list = [i['id'] for i in data['results']]
				total_pages = data['total_pages']
				if total_pages > page_no: self.new_page = {'new_page': string(data['page'] + 1)}
			elif self.action in Menu.trakt_main:
				self.id_type = 'trakt_dict'
				data = function(page_no)
				self.list = [i['movie']['ids'] for i in data]
				if self.action not in ('trakt_moviesanime_trending',):
					self.new_page = {'new_page': string(page_no + 1)}
			elif self.action in Menu.trakt_personal:
				self.id_type = 'trakt_dict'
				data, total_pages = function('movies', page_no, letter)
				self.list = [i['media_ids'] for i in data]
				if total_pages > 2: self.total_pages = total_pages
				try:
					if total_pages > page_no: self.new_page = {'new_page': string(page_no + 1), 'new_letter': letter}
				except: pass
			elif self.action in Menu.mdblist_personal:
				self.id_type = 'trakt_dict'
				data, total_pages = function('movies', page_no, letter)
				self.list = [{'imdb': i['imdb_id'], 'tmdb': i['id']} for i in data]
				if total_pages > 2: self.total_pages = total_pages
				try:
					if total_pages > page_no: self.new_page = {'new_page': string(page_no + 1), 'new_letter': letter}
				except: pass
			elif self.action in Menu.flicklist_personal:
				data, total_pages = function('movies', page_no, letter)
				self.list = [i['tmdb_id'] for i in data]
				if total_pages > 2: self.total_pages = total_pages
				try:
					if total_pages > page_no: self.new_page = {'new_page': string(page_no + 1), 'new_letter': letter}
				except: pass
			elif self.action in Menu.personal_dict:
				data, total_pages = function('movie', page_no, letter)
				self.list = [i['media_id'] for i in data]
				if total_pages > 2: self.total_pages = total_pages
				if total_pages > page_no: self.new_page = {'new_page': string(page_no + 1), 'new_letter': letter}
			elif self.action in Menu.similar:
				tmdb_id = params_get('tmdb_id')
				data = function(tmdb_id, page_no)
				self.list = [i['id'] for i in data['results']]
				if data['page'] < data['total_pages']: self.new_page = {'new_page': string(data['page'] + 1), 'tmdb_id': tmdb_id}
			elif self.action in Menu.tmdb_special_key_dict:
				key = Menu.tmdb_special_key_dict[self.action]
				function_var = params_get(key)
				if not function_var: return
				data = function(function_var, page_no)
				self.list = [i['id'] for i in data['results']]
				if data['page'] < data['total_pages']: self.new_page = {'new_page': string(data['page'] + 1), key: function_var}
			elif self.action == 'tmdb_movies_discover':
				from menus.discover import set_history
				name, query = params_get('name'), params_get('query')
				if page_no == 1: set_history('movie', name, query)
				data = function(query, page_no)
				self.list = [i['id'] for i in data['results']]
				if data['page'] < data['total_pages']: self.new_page = {'query': query, 'name': name, 'new_page': string(data['page'] + 1)}
			elif self.action in ('tmdb_movies_genres', 'tmdb_moviesanime_genres'):
				genre_id = params_get('genre_id')
				if not genre_id: return
				data = function(genre_id, page_no)
				self.list = [i['id'] for i in data['results']]
				if data['page'] < data['total_pages']: self.new_page = {'new_page': string(data['page'] + 1), 'genre_id': genre_id}
			elif self.action == 'tmdb_movies_search':
				query = params_get('query')
				data = function(query, page_no)
				self.list = [i['id'] for i in data['results']]
				total_pages = data['total_pages']
				if total_pages > page_no: self.new_page = {'new_page': string(page_no + 1), 'new_letter': letter, 'query': query}
			elif self.action == 'tmdb_movies_search_collections':
				worker, view_type, content_type = self.build_collections_results, 'view.main', ''
				query = params_get('query')
				data = function(query, page_no)
				self.list = data['results']
				total_pages = data['total_pages']
				if total_pages > page_no: self.new_page = {'new_page': string(page_no + 1), 'query': query}
			elif self.action == 'tmdb_movies_collection':
				data = sorted(function(params_get('collection_id'))['parts'], key=lambda k: k['release_date'] or '2050')
				self.list = [i['id'] for i in data]
			elif self.action == 'trakt_recommendations':
				self.id_type = 'trakt_dict'
				data = function('movies')
				self.list = [i['ids'] for i in data]
			if self.total_pages and not self.is_widget and settings.nav_jump_use_alphabet():
				url_params = {
					'mode': 'build_navigate_to_page', 'current_page': page_no, 'total_pages': self.total_pages,
					'query': params_get('search_name', ''), 'actor_id': params_get('actor_id', ''),
					'transfer_mode': mode, 'transfer_action': self.action, 'mediatype': 'Movies'
				}
				kodi_utils.add_dir(__handle__, url_params, jumpto_str, item_jump, isFolder=False)
			kodi_utils.add_items(__handle__, worker())
			if self.new_page:
				self.new_page.update({'mode': mode, 'action': self.action, 'exit_list_params': self.exit_list_params, 'name': ls(params_get('name'))})
				kodi_utils.add_dir(__handle__, self.new_page, nextpage_str, item_next)
		except: pass
		kodi_utils.set_category(__handle__, ls(params_get('name')))
		kodi_utils.set_sort_method(__handle__, content_type)
		kodi_utils.set_content(__handle__, content_type)
		kodi_utils.end_directory(__handle__, False if self.is_widget else None)
		kodi_utils.set_view_mode(view_type, content_type)

