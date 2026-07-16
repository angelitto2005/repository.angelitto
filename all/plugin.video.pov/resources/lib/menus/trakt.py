from indexers import trakt_api, list_helper
from menus.episodes import Episodes
from menus.movies import Movies
from menus.seasons import Seasons
from menus.tvshows import TVShows
from modules import kodi_utils
# logger = kodi_utils.logger

KODI_VERSION, ls = kodi_utils.get_kodi_version(), kodi_utils.local_string
build_url, make_listitem = kodi_utils.build_url, kodi_utils.make_listitem
fanart = kodi_utils.get_addoninfo('fanart')
default_icon = kodi_utils.media_path('trakt.png')
add2menu_str, add2folder_str, copy2str = ls(32730), ls(32731), '[B]Export to TMDB[/B]'
newlist_str, deletelist_str, nextpage_str = ls(32780), ls(32781), ls(32799)
likelist_str, unlikelist_str = ls(32776), ls(32783)
watchl_str, fav_str, coll_str = ls(32500), ls(32453), ls(32499)

def search_trakt_lists(params):
	return SearchTraktLists(params).build()

def get_trakt_lists(params):
	return GetTraktLists(params).build()

def get_trakt_trending_popular_lists(params):
	return GetTrendingPopularLists(params).build()

def build_trakt_list(params):
	return TraktListBuilder(params).build()

def integrity_check():
	try:
		trakt_db = kodi_utils.translate_path(kodi_utils.trakt_db)
		with kodi_utils.database.connect(trakt_db) as dbcon:
			cur = dbcon.cursor()
			cur.execute("""PRAGMA integrity_check""")
			result = cur.fetchone()
		if 'ok' in result: status = 'passed'
		else: raise kodi_utils.database.Error(result)
		return status
	except kodi_utils.database.Error as e: status = str(e)
	try:
		with open(trakt_db, 'w') as _: pass
		from modules.cache import check_databases, clear_cache
		check_databases()
		clear_cache('trakt', silent=True)
		status = 'repaired'
	except Exception as e: kodi_utils.logger('trakt integrity error', '\n%s\n%s' % (status, e))
	return status

def trakt_account_info():
	from datetime import timedelta
	from modules.utils import jsondate_to_datetime
	try:
		kodi_utils.show_busy_dialog()
		db_status = integrity_check()
		account_info = trakt_api.call_trakt('users/settings', with_auth=True)
		stats = trakt_api.call_trakt('users/%s/stats' % account_info['user']['ids']['slug'], with_auth=True)
		username = account_info['user']['username']
		timezone = account_info['account']['timezone']
		joined = jsondate_to_datetime(account_info['user']['joined_at']).astimezone()
		private = account_info['user']['private']
		vip = account_info['user']['vip']
		if vip: vip = '%s Years' % str(account_info['user']['vip_years'])
		total_given_ratings = stats['ratings']['total']
		movies_collected = stats['movies']['collected']
		movies_watched = stats['movies']['watched']
		movie_minutes = stats['movies']['minutes']
		if movie_minutes == 0: movies_watched_minutes = ['0 days', '0:00:00']
		elif movie_minutes < 1440: movies_watched_minutes = ['0 days', '{:0>8}'.format(str(timedelta(minutes=movie_minutes)))]
		else: movies_watched_minutes = ('{:0>8}'.format(str(timedelta(minutes=movie_minutes)))).split(', ')
		movies_watched_minutes = ('%s %s hours %s minutes' % (movies_watched_minutes[0], movies_watched_minutes[1].split(':')[0], movies_watched_minutes[1].split(':')[1]))
		shows_collected = stats['shows']['collected']
		shows_watched = stats['shows']['watched']
		episodes_watched = stats['episodes']['watched']
		episode_minutes = stats['episodes']['minutes']
		if episode_minutes == 0: episodes_watched_minutes = ['0 days', '0:00:00']
		elif episode_minutes < 1440: episodes_watched_minutes = ['0 days', '{:0>8}'.format(str(timedelta(minutes=episode_minutes)))]
		else: episodes_watched_minutes = ('{:0>8}'.format(str(timedelta(minutes=episode_minutes)))).split(', ')
		episodes_watched_minutes = ('%s %s hours %s minutes' % (episodes_watched_minutes[0], episodes_watched_minutes[1].split(':')[0], episodes_watched_minutes[1].split(':')[1]))
		body = []
		append = body.append
		append('[B]Username:[/B] %s' % username)
		append('[B]Timezone:[/B] %s' % timezone)
		append('[B]Joined:[/B] %s' % joined.date())
		append('[B]Private:[/B] %s' % private)
		append('[B]VIP Status:[/B] %s' % vip)
		append('[B]Ratings Given:[/B] %s' % str(total_given_ratings))
		append('[B]Shows:[/B] [B]%s[/B] Collected, [B]%s[/B] Watched' % (shows_collected, shows_watched))
		append('[B]Episodes:[/B] [B]%s[/B] Watched for [B]%s[/B]' % (episodes_watched, episodes_watched_minutes))
		append('[B]Movies:[/B] [B]%s[/B] Collected, [B]%s[/B] Watched for [B]%s[/B]' % (movies_collected, movies_watched, movies_watched_minutes))
		append('[B]Cache Integrity:[/B] %s' % db_status.upper())
		kodi_utils.hide_busy_dialog()
		return kodi_utils.show_text(ls(32037).upper(), '\n\n'.join(body), font_size='large')
	except: kodi_utils.hide_busy_dialog()

class BaseTraktList(list_helper.BaseList):
	def process_results(self):
		for item in self.lists:
			try:
				cm = []
				cm_append = cm.append
				item, list_type = self.parse_item(item)
				if not item: continue
				name, user, slug, list_id = item['name'], item['user']['ids']['slug'], item['ids']['slug'], item['ids']['trakt']
				item_count = item.get('item_count')
				url = build_url({'mode': 'build_trakt_list', 'user': user, 'slug': slug, 'list_id': list_id, 'list_type': list_type, 'name': name})
				display, plot = self.get_display_and_plot(item, name, item_count, user)
				if list_type == 'liked_lists':
					cm_append((unlikelist_str, 'RunPlugin(%s)' % build_url({'mode': 'trakt.trakt_unlike_a_list', 'user': user, 'list_slug': slug})))
				elif list_type == 'my_lists':
					cm_append((newlist_str, 'RunPlugin(%s)' % build_url({'mode': 'trakt.make_new_trakt_list'})))
					cm_append((deletelist_str, 'RunPlugin(%s)' % build_url({'mode': 'trakt.delete_trakt_list', 'user': user, 'list_slug': slug})))
				else:  # user_lists / trending / popular / search
					cm_append((likelist_str, 'RunPlugin(%s)' % build_url({'mode': 'trakt.trakt_like_a_list', 'user': user, 'list_slug': slug})))
					cm_append((unlikelist_str, 'RunPlugin(%s)' % build_url({'mode': 'trakt.trakt_unlike_a_list', 'user': user, 'list_slug': slug})))
				cm_append((add2menu_str, 'RunPlugin(%s)' % build_url({'mode': 'menu_editor.add_external', 'name': display, 'iconImage': 'trakt.png'})))
				cm_append((add2folder_str, 'RunPlugin(%s)' % build_url({'mode': 'menu_editor.shortcut_folder_add_item', 'name': display, 'iconImage': 'trakt.png'})))
				cm_append((copy2str, 'RunPlugin(%s)' % build_url({'mode': 'tmdb_manager_choice', 'trakt_list_id': list_id, 'trakt_list_name': name, 'user': user, 'list_slug': slug})))
				listitem = make_listitem()
				listitem.setLabel(display)
				listitem.setArt({'icon': default_icon, 'poster': default_icon, 'thumb': default_icon, 'fanart': fanart, 'banner': default_icon})
				if plot: listitem.setInfo('video', {'plot': plot}) if KODI_VERSION < 20 else listitem.getVideoInfoTag().setPlot(plot)
				listitem.addContextMenuItems(cm)
				yield (url, listitem, True)
			except: pass

class SearchTraktLists(BaseTraktList):
	def __init__(self, params):
		super().__init__(params)
		self.page = params.get('new_page', '1')
		self.pages = self.page
		self.search_title = params.get('search_title') or kodi_utils.dialog.input('POV')
		self.category_name = self.search_title

	def fetch_results(self):
		if self.search_title: self.lists, self.pages = trakt_api.trakt_search_lists(self.search_title, self.page)
		else: self.lists, self.pages = [], self.page

	def parse_item(self, item):
		list_key = item['type']
		list_info = item[list_key]
		if list_info['privacy'] == 'private' or list_info['item_count'] == 0: return None, None
		return list_info, 'user_lists'

	def add_next_page(self):
		if int(self.pages) <= int(self.page): return
		url = {'mode': 'build_trakt_list.search_trakt_lists', 'search_title': self.search_title, 'new_page': int(self.page) + 1}
		kodi_utils.add_dir(self.handle, url, nextpage_str)

class GetTraktLists(BaseTraktList):
	def __init__(self, params):
		super().__init__(params)
		self.list_type = params['list_type']
		self.sort_method = 'label'

	def fetch_results(self):
		self.lists = trakt_api.trakt_get_lists(self.list_type)

	def parse_item(self, item):
		if self.list_type == 'liked_lists': return item['list'], 'liked_lists'
		return item, 'my_lists'

	def get_display_and_plot(self, item, name, item_count, user):
		privacy = item.get('privacy') == 'private'
		if self.list_type == 'liked_lists':
			display = '%s (x%s) - [I]%s[/I]' % (name, item_count, user) if item_count else '%s - [I]%s[/I]' % (name, user)
		else:
			display = '%s (x%s)' % (name, item_count) if item_count else name
			if privacy: display = '[I]%s[/I]' % display
		return display, None

class GetTrendingPopularLists(BaseTraktList):
	def __init__(self, params):
		super().__init__(params)
		self.list_type = params['list_type']

	def fetch_results(self):
		self.lists = trakt_api.trakt_trending_popular_lists(self.list_type)

	def parse_item(self, item):
		return item['list'], 'user_lists'

class TraktListBuilder(list_helper.BaseMediaListBuilder):
	mode = 'build_trakt_list'

	def __init__(self, params):
		super().__init__(params)
		self.slug = params.get('slug')
		self.list_type = params.get('list_type')

	def fetch_results(self):
		return trakt_api.get_trakt_list_contents(self.list_type, self.list_id, self.user, self.slug)

	def process_media_types(self, queue, process_list):
		movies, tvshows = Movies({'id_type': 'trakt_dict'}), TVShows({'id_type': 'trakt_dict'})
		episodes, seasons = Episodes({'id_type': 'trakt_dict'}), Seasons({'id_type': 'trakt_dict'})
		for idx, tag in enumerate(process_list, 1):
			mtype = tag['type']
			if   mtype == 'movie':
				queue.put((movies.build_movie_content, idx, tag[mtype]['ids']))
			elif mtype == 'show':
				queue.put((tvshows.build_tvshow_content, idx, tag[mtype]['ids']))
			elif mtype == 'episode':
				ids = {'media_ids': {'tmdb': tag['show']['ids']['tmdb']}, 'season': tag['episode']['season'], 'episode': tag['episode']['number']}
				queue.put((episodes.build_episode_content, idx, ids))
			elif mtype == 'season':
				ids = {'tmdb_id': tag['show']['ids']['tmdb'], 'season': tag['season']['number'], 'sort': idx}
				queue.put((seasons.build_season_list, ids))
		return {'movies': movies, 'tvshows': tvshows, 'episodes': episodes, 'seasons': seasons}

	def get_url_params(self):
		params = super().get_url_params()
		params.update({'slug': self.slug, 'list_type': self.list_type})
		return params

class TraktManager(list_helper.BaseListManager):
	setting_key = 'trakt_user'
	icon_file = 'trakt.png'
	heading_id = 32198

	def _get_api(self):
		return trakt_api

	def get_custom_lists(self):
		list1 = [
			((item['ids']['trakt'], item['user']['ids']['slug'], item['ids']['slug']),
			 item['name'],
			 '%s items' % item['item_count'],
			 self.icon)
			for item in self.api.trakt_get_lists('my_lists')
		]
		list2 = [('new', 'Create a new list', '', self.icon)]
		return list1, list2

	def get_default_choices(self):
		choices = [(i.lower(), i, '', self.icon) for i in (watchl_str, fav_str, coll_str)]
		if self.mediatype == 'tvshow': choices.append(('dropped', 'Toggle Dropped', '', self.icon))
		return choices

	def handle_special_action(self, choice_id, choice_name):
		if 'new' in choice_id:
			kodi_utils.show_busy_dialog()
			try: self.api.make_new_trakt_list(None)
			except: return kodi_utils.notification(32574)
			finally: kodi_utils.hide_busy_dialog()
			return self.manage()
		if 'dropped' in choice_id:
			args = self.params['tmdb_id'], 'shows', self.params['imdb_id']
			return self.api.hide_unhide_trakt_items(*args, 'dropped')
		return False

	def check_item_exists(self, choice_id):
		if any(x in choice_id for x in ('watchlist', 'favorites', 'collection')):
			list_items = self.api.trakt_fetch_collection_watchlist(choice_id, self.mediatype)
			return self.tmdb_id in {i['media_ids']['tmdb'] for i in list_items}
		list_items = self.api.get_trakt_list_contents('my_lists', *choice_id)
		return self.tmdb_id in {
			i['movie']['ids']['tmdb'] if i['type'] == 'movie' else i['show']['ids']['tmdb']
			for i in list_items
		}

	def execute_toggle(self, choice, action_add):
		content = 'shows' if self.mediatype == 'tvshow' else 'movies'
		data = {content: [{'ids': {'tmdb': self.tmdb_id}}]}
		if any(x in choice[0] for x in ('watchlist', 'favorites', 'collection')):
			if action_add: return self.api.add_to_sync(choice[0], data)
			else: return self.api.remove_from_sync(choice[0], data)
		if action_add: return self.api.add_to_list(choice[0][1], choice[0][2], data)
		return self.api.remove_from_list(choice[0][1], choice[0][2], data)

