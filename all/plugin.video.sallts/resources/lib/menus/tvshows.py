import sys
from threading import Thread
from indexers.flicklist_api import flicklist_get_hidden_items
from indexers.mdblist_api import mdbl_get_hidden_items
from indexers.trakt_api import trakt_get_hidden_items
from indexers.metadata import tvshow_meta, art_infodict, movie_show_infodict
from caches.watched_cache import get_watched_info_tv, get_watched_status_tvshow
from modules import kodi_utils, settings
#from modules.utils import manual_function_import, get_datetime, make_thread_list_enumerate
from modules.utils import manual_function_import, get_datetime, TaskPool
# logger = kodi_utils.logger

tv_meta_function, get_datetime_function = tvshow_meta, get_datetime
get_watched_function, get_watched_info_function = get_watched_status_tvshow, get_watched_info_tv
KODI_VERSION, make_cast_list = kodi_utils.get_kodi_version(), kodi_utils.make_cast_list
string, ls, build_url, get_infolabel = str, kodi_utils.local_string, kodi_utils.build_url, kodi_utils.get_infolabel
run_plugin, container_refresh, container_update = 'RunPlugin(%s)', 'Container.Refresh(%s)', 'Container.Update(%s)'
fanart_empty = kodi_utils.get_addoninfo('fanart')
poster_empty = kodi_utils.media_path('box_office.png')
item_jump = kodi_utils.media_path('item_jump.png')
item_next = kodi_utils.media_path('item_next.png')
watched_str, unwatched_str, traktmanager_str = ls(32642), ls(32643), ls(32198)
favmanager_str, extras_str, options_str, recomm_str = ls(32197), ls(32645), ls(32646), '[B]%s...[/B]' % ls(32503)
random_str, exit_str, browse_str = ls(32611), ls(32650), ls(32652)
nextpage_str, switchjump_str, jumpto_str = ls(32799), ls(32784), ls(32964)
mdblmanager_str, flicklistmanager_str = ls(32200), '[B]FlickList Manager[/B]'

class TVShows:
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
		self.all_episodes = settings.default_all_episodes()
		self.include_year_in_title = settings.include_year_in_title('tvshow')
		self.open_extras = settings.extras_open_action('tvshow')
		self.cm_sort = settings.context_menu_sort()
		self.is_folder = False if self.open_extras else True
		self.is_widget = kodi_utils.external_browse()
		self.widget_hide_watched = self.is_widget and self.meta_user_info['widget_hide_watched']
		if not self.exit_list_params: self.exit_list_params = get_infolabel('Container.FolderPath')
		self.art_provider = (*settings.get_art_provider(), poster_empty, fanart_empty)

	def build_tvshow_content(self, position, tag):
		try:
			meta = tv_meta_function(self.id_type, tag, self.meta_user_info, self.current_date)
			meta_get = meta.get
			if not meta or meta_get('blank_entry', False): return
			playcount, overlay, total_watched, total_unwatched = get_watched_function(self.watched_info, string(meta['tmdb_id']), meta.get('total_aired_eps'))
			if self.widget_hide_watched and playcount: return
			meta.update({'playcount': playcount, 'overlay': overlay})
			total_seasons, total_aired_eps = meta_get('total_seasons'), meta_get('total_aired_eps')
			watchedprogress = total_watched / total_aired_eps * 100 if total_watched else 0
			cm = []
			cm_append = cm.append
			rootname, title, year = meta_get('rootname'), meta_get('title'), meta_get('year')
			display = rootname if self.include_year_in_title else title
			tmdb_id, tvdb_id, imdb_id = meta_get('tmdb_id'), meta_get('tvdb_id'), meta_get('imdb_id')
			if self.all_episodes and self.all_episodes == 1 and total_seasons > 1: url_params = build_url({
				'mode': 'build_season_list', 'tmdb_id': tmdb_id
			})
			elif self.all_episodes: url_params = build_url({
				'mode': 'build_episode_list', 'tmdb_id': tmdb_id, 'season': 'all'
			})
			else: url_params = build_url({
				'mode': 'build_season_list', 'tmdb_id': tmdb_id
			})
			extras_params = build_url({
				'mode': 'extras_menu_choice', 'mediatype': 'tvshow',
				'tmdb_id': tmdb_id, 'is_widget': self.is_widget
			})
			options_params = build_url({
				'mode': 'options_menu_choice', 'mediatype': 'tvshow',
				'tmdb_id': tmdb_id, 'is_widget': self.is_widget
			})
			recommended_params = build_url({
				'mode': 'build_tvshow_list', 'action': 'tmdb_tv_recommendations',
				'tmdb_id': tmdb_id
			})
			trakt_manager_params = build_url({
				'mode': 'trakt_manager_choice', 'mediatype': 'tvshow',
				'tmdb_id': tmdb_id, 'imdb_id': imdb_id, 'tvdb_id': tvdb_id
			})
			mdbl_manager_params = build_url({
				'mode': 'mdbl_manager_choice', 'mediatype': 'tvshow',
				'tmdb_id': tmdb_id, 'imdb_id': imdb_id, 'tvdb_id': tvdb_id
			})
			flicklist_manager_params = build_url({
				'mode': 'flicklist_manager_choice', 'mediatype': 'tvshow',
				'tmdb_id': tmdb_id, 'imdb_id': imdb_id, 'tvdb_id': 'None'
			})
			fav_manager_params = build_url({
				'mode': 'favorites_choice', 'mediatype': 'tvshow',
				'tmdb_id': tmdb_id, 'title': title
			})
			cm_append((self.cm_sort['options'], options_str, run_plugin % options_params))
			if self.open_extras:
				url_params = extras_params
				cm_append((self.cm_sort['extras'], browse_str, container_update % url_params))
			else:
				cm_append((self.cm_sort['extras'], extras_str, run_plugin % extras_params))
			cm_append((self.cm_sort['trakt'], traktmanager_str, run_plugin % trakt_manager_params))
			cm_append((self.cm_sort['mdblist'], mdblmanager_str, run_plugin % mdbl_manager_params))
			cm_append((self.cm_sort['flicklist'], flicklistmanager_str, run_plugin % flicklist_manager_params))
			cm_append((self.cm_sort['favorites'], favmanager_str, run_plugin % fav_manager_params))
			if not playcount: cm_append((
				self.cm_sort['mark'], watched_str % self.watched_title, run_plugin % build_url({
					'mode': 'mark_as_watched_unwatched_tvshow', 'action': 'mark_as_watched', 'year': year,
					'tmdb_id': tmdb_id, 'imdb_id': imdb_id, 'tvdb_id': tvdb_id, 'title': title
			})))
			if total_watched: cm_append((
				self.cm_sort['mark'], unwatched_str % self.watched_title, run_plugin % build_url({
					'mode': 'mark_as_watched_unwatched_tvshow', 'action': 'mark_as_unwatched', 'year': year,
					'tmdb_id': tmdb_id, 'imdb_id': imdb_id, 'tvdb_id': tvdb_id, 'title': title
			})))
			cm_append((self.cm_sort['exit'], exit_str, container_refresh % self.exit_list_params))
			cm.sort(key=lambda k: k[0])
			cm = [v for k, *v in cm if k]
			props = {
				'salts_sort_order': string(position), 'unwatchedepisodes': string(total_unwatched),
				'totalseasons': string(total_seasons), 'totalepisodes': string(total_aired_eps),
				'watchedepisodes': string(total_watched), 'watchedprogress': string(int(watchedprogress))
			}
			listitem = kodi_utils.make_listitem()
			listitem.addContextMenuItems(cm)
			listitem.setProperties(props)
			listitem.setLabel(display)
			listitem.setArt(art_infodict(meta, self.art_provider, self.meta_user_info))
			if KODI_VERSION < 20:
				listitem.setUniqueIDs({'imdb': imdb_id, 'tmdb': string(tmdb_id), 'tvdb': string(tvdb_id)})
				listitem.setInfo('video', movie_show_infodict(meta))
				listitem.setCast(meta_get('cast', []))
			else:
				videoinfo = listitem.getVideoInfoTag(offscreen=True)
				videoinfo.setTitle(display)
				videoinfo.setUniqueIDs({'imdb': imdb_id, 'tmdb': string(tmdb_id), 'tvdb': string(tvdb_id)})
				videoinfo.setCast(make_cast_list(meta_get('cast', [])))
				videoinfo.setCountries(meta_get('country'))
				videoinfo.setDirectors(meta_get('director').split(', '))
				videoinfo.setDuration(meta_get('duration'))
				videoinfo.setGenres(meta_get('genre').split(', '))
				videoinfo.setIMDBNumber(imdb_id)
				videoinfo.setMediaType('tvshow')
				videoinfo.setMpaa(meta_get('mpaa'))
				videoinfo.setPlaycount(playcount)
				videoinfo.setPlot(meta_get('plot'))
				videoinfo.setPremiered(meta_get('premiered'))
				videoinfo.setRating(meta_get('rating'))
				videoinfo.setStudios((meta_get('studio'),))
				videoinfo.setTagLine(meta_get('tagline'))
				videoinfo.setTags((imdb_id, string(tmdb_id), string(tvdb_id)))
				videoinfo.setTrailer(meta_get('trailer'))
				videoinfo.setTvShowStatus(meta_get('status'))
				videoinfo.setTvShowTitle(title)
				videoinfo.setVotes(meta_get('votes'))
				videoinfo.setWriters(meta_get('writer').split(', '))
			self.append((url_params, listitem, self.is_folder))
		except: pass

class Menu(TVShows):
	personal_dict = {'in_progress_tvshows': ('caches.watched_cache', 'get_in_progress_tvshows'), 'favorites_tvshows': ('caches.favorites_cache', 'get_favorites'), 'watched_tvshows': ('caches.watched_cache', 'get_watched_items')}
	tmdb_special_key_dict = {'tmdb_tv_networks': 'network_id', 'tmdb_tv_year': 'year', 'tmdb_tvanime_year': 'year'}
	tmdb_main = ('tmdb_tv_popular', 'tmdb_tv_premieres', 'tmdb_tv_upcoming', 'tmdb_tvanime_popular', 'tmdb_tvanime_premieres')
	trakt_main = ('trakt_tv_trending', 'trakt_tv_trending_recent', 'trakt_tv_most_watched', 'trakt_tvanime_trending', 'trakt_tvanime_most_watched')
	trakt_personal = ('trakt_collection', 'trakt_watchlist', 'trakt_favorites', 'trakt_droplist', 'trakt_collection_lists')
	mdblist_personal = ('mdblist_collection', 'mdblist_watchlist', 'mdblist_droplist')
	flicklist_personal = ('flicklist_watchlist', 'flicklist_favorites', 'flicklist_droplist')
	similar = ('tmdb_tv_similar', 'tmdb_tv_recommendations')

	def worker(self):
#		threads = list(make_thread_list_enumerate(self.build_tvshow_content, self.list, Thread))
		for i in TaskPool().tasks_enumerate(self.build_tvshow_content, self.list, Thread): i.join()
		self.items.sort(key=lambda k: int(k[1].getProperty('salts_sort_order')))
		return self.items

	def run(self):
		try:
			params_get = self.params.get
			__handle__ = int(sys.argv[1])
			view_type, content_type = 'view.tvshows', 'tvshows'
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
				self.list = [i['show']['ids'] for i in data]
				self.new_page = {'new_page': string(page_no + 1)}
			elif self.action in Menu.trakt_personal:
				self.id_type = 'trakt_dict'
				data, total_pages = function('shows', page_no, letter)
				self.list = [i['media_ids'] for i in data]
				if total_pages > 2: self.total_pages = total_pages
				try:
					if total_pages > page_no: self.new_page = {'new_page': string(page_no + 1), 'new_letter': letter}
				except: pass
			elif self.action in Menu.mdblist_personal:
				self.id_type = 'trakt_dict'
				data, total_pages = function('shows', page_no, letter)
				self.list = [{'imdb': i['imdb_id'], 'tmdb': i['id']} for i in data]
				if total_pages > 2: self.total_pages = total_pages
				try:
					if total_pages > page_no: self.new_page = {'new_page': string(page_no + 1), 'new_letter': letter}
				except: pass
			elif self.action in Menu.flicklist_personal:
				data, total_pages = function('shows', page_no, letter)
				self.list = [i['tmdb_id'] for i in data]
				if total_pages > 2: self.total_pages = total_pages
				try:
					if total_pages > page_no: self.new_page = {'new_page': string(page_no + 1), 'new_letter': letter}
				except: pass
			elif self.action in Menu.personal_dict:
				data, total_pages = function('tvshow', page_no, letter)
				self.list = [i['media_id'] for i in data]
				if total_pages > 2: self.total_pages = total_pages
				if total_pages > page_no: self.new_page = {'new_page': string(page_no + 1), 'new_letter': letter}
				if self.watched_indicators == 1:
					try:
						hidden_data = trakt_get_hidden_items('dropped')
						self.list = [i for i in self.list if not int(i) in hidden_data]
					except: pass
				if self.watched_indicators == 2:
					try:
						hidden_data = mdbl_get_hidden_items('dropped')
						self.list = [i for i in self.list if not int(i) in hidden_data]
					except: pass
				if self.watched_indicators == 3:
					try:
						hidden_data = flicklist_get_hidden_items('dropped')
						self.list = [i for i in self.list if not int(i) in hidden_data]
					except: pass
			elif self.action in Menu.similar:
				tmdb_id = self.params['tmdb_id']
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
			elif self.action == 'tmdb_tv_discover':
				from menus.discover import set_history
				name = self.params['name']
				query = self.params['query']
				if page_no == 1: set_history('tvshow', name, query)
				data = function(query, page_no)
				self.list = [i['id'] for i in data['results']]
				if data['page'] < data['total_pages']: self.new_page = {'query': query, 'name': name, 'new_page': string(data['page'] + 1)}
			elif self.action in ('tmdb_tv_genres', 'tmdb_tvanime_genres'):
				genre_id = self.params['genre_id']
				if not genre_id: return
				data = function(genre_id, page_no)
				self.list = [i['id'] for i in data['results']]
				if data['page'] < data['total_pages']: self.new_page = {'new_page': string(data['page'] + 1), 'genre_id': genre_id}
			elif self.action == 'tmdb_tv_search':
				query = self.params['query']
				data = function(query, page_no)
				self.list = [i['id'] for i in data['results']]
				total_pages = data['total_pages']
				if total_pages > page_no: self.new_page = {'new_page': string(page_no + 1), 'query': query}
			elif self.action == 'trakt_tv_certifications':
				self.id_type = 'trakt_dict'
				data = function(self.params['certification'], page_no)
				self.list = [i['show']['ids'] for i in data]
				self.new_page = {'new_page': string(page_no + 1), 'certification': self.params['certification']}
			elif self.action == 'trakt_recommendations':
				self.id_type = 'trakt_dict'
				data = function('shows')
				self.list = [i['ids'] for i in data]
			if self.total_pages and not self.is_widget and settings.nav_jump_use_alphabet():
				url_params = {
					'mode': 'build_navigate_to_page', 'current_page': page_no, 'total_pages': self.total_pages,
					'query': params_get('search_name', ''), 'actor_id': params_get('actor_id', ''),
					'transfer_mode': mode, 'transfer_action': self.action, 'mediatype': 'TV Shows'
				}
				kodi_utils.add_dir(__handle__, url_params, jumpto_str, item_jump, isFolder=False)
			kodi_utils.add_items(__handle__, self.worker())
			if self.new_page:
				self.new_page.update({'mode': mode, 'action': self.action, 'exit_list_params': self.exit_list_params, 'name': ls(params_get('name'))})
				kodi_utils.add_dir(__handle__, self.new_page, nextpage_str, item_next)
		except: pass
		kodi_utils.set_category(__handle__, ls(params_get('name')))
		kodi_utils.set_sort_method(__handle__, content_type)
		kodi_utils.set_content(__handle__, content_type)
		kodi_utils.end_directory(__handle__, False if self.is_widget else None)
		kodi_utils.set_view_mode(view_type, content_type)

