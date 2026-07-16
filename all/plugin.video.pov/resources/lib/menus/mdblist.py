from indexers import mdblist_api, list_helper
from menus.movies import Movies
from menus.tvshows import TVShows
from modules import kodi_utils
# logger = kodi_utils.logger

KODI_VERSION, ls = kodi_utils.get_kodi_version(), kodi_utils.local_string
build_url, make_listitem = kodi_utils.build_url, kodi_utils.make_listitem
fanart = kodi_utils.get_addoninfo('fanart')
default_icon = kodi_utils.media_path('mdblist.png')
add2menu_str, add2folder_str, copy2str = ls(32730), ls(32731), '[B]Export to TMDB[/B]'
newlist_str, deletelist_str, nextpage_str = '[B]Make a new MDBList list[/B]', ls(32781), ls(32799)
watchl_str, fav_str, coll_str = ls(32500), ls(32453), ls(32499)

def search_mdbl_lists(params):
	return SearchMdblLists(params).build()

def get_mdbl_lists(params):
	return GetMdblLists(params).build()

def get_mdbl_top_lists(params):
	return GetTopLists(params).build()

def build_mdbl_list(params):
	return MdblistBuilder(params).build()

def mdbl_account_info():
	from modules.utils import jsondate_to_datetime
	try:
		kodi_utils.show_busy_dialog()
		account_info = mdblist_api.call_mdblist('user')
		joined = jsondate_to_datetime(account_info['date_joined']).astimezone()
		api_requests = account_info['api_requests']
		remaining = api_requests - account_info['api_requests_count']
		body = []
		append = body.append
		append('[B]Username:[/B] %s' % account_info['username'])
		append('[B]Joined:[/B] %s' % joined.date())
		append('[B]Supporter:[/B] %s' % account_info['is_supporter'])
		append('[B]API Request Limit:[/B] %s' % api_requests)
		append('[B]API Request Remaining:[/B] %s' % remaining)
		kodi_utils.hide_busy_dialog()
		return kodi_utils.show_text('MDBList'.upper(), '\n\n'.join(body), font_size='large')
	except: kodi_utils.hide_busy_dialog()

class BaseMdblList(list_helper.BaseList):
	def process_results(self):
		for item in self.lists:
			try:
				cm = []
				cm_append = cm.append
				item, list_type = self.parse_item(item)
				if not item: continue
				name, user, slug, list_id = item['name'], item['user_name'], item.get('slug', ''), item['id']
				item_count = item.get('items')
				url = build_url({'mode': 'build_mdbl_list', 'user': user, 'slug': slug, 'list_id': list_id, 'list_type': list_type, 'name': name})
				display, plot = self.get_display_and_plot(item, name, item_count, user)
				if list_type == 'my_lists':
					cm_append((newlist_str, 'RunPlugin(%s)' % build_url({'mode': 'mdblist.make_new_mdbl_list'})))
					cm_append((deletelist_str, 'RunPlugin(%s)' % build_url({'mode': 'mdblist.delete_mdbl_list', 'list_id': list_id})))
				cm_append((add2menu_str, 'RunPlugin(%s)' % build_url({'mode': 'menu_editor.add_external', 'name': name, 'iconImage': 'mdblist.png'})))
				cm_append((add2folder_str, 'RunPlugin(%s)' % build_url({'mode': 'menu_editor.shortcut_folder_add_item', 'name': name, 'iconImage': 'mdblist.png'})))
				cm_append((copy2str, 'RunPlugin(%s)' % build_url({'mode': 'tmdb_manager_choice', 'mdbl_list_id': list_id, 'mdbl_list_name': name, 'user': user, 'list_slug': slug})))
				listitem = make_listitem()
				listitem.setLabel(display)
				listitem.setArt({'icon': default_icon, 'poster': default_icon, 'thumb': default_icon, 'fanart': fanart, 'banner': default_icon})
				if plot: listitem.setInfo('video', {'plot': plot}) if KODI_VERSION < 20 else listitem.getVideoInfoTag().setPlot(plot)
				listitem.addContextMenuItems(cm)
				yield (url, listitem, True)
			except: pass

class SearchMdblLists(BaseMdblList):
	def __init__(self, params):
		super().__init__(params)
		self.page = params.get('new_page', '1')
		self.pages = self.page
		self.search_title = params.get('search_title') or kodi_utils.dialog.input('POV')
		self.category_name = self.search_title

	def fetch_results(self):
		if self.search_title: self.lists, self.pages = mdblist_api.mdbl_search_lists(self.search_title), '1'
		else: self.lists, self.pages = [], self.page

	def add_next_page(self):
		if int(self.pages) <= int(self.page): return
		url = {'mode': 'build_mdbl_list.search_mdb_lists', 'search_title': self.search_title, 'new_page': int(self.page) + 1}
		kodi_utils.add_dir(self.handle, url, nextpage_str)

class GetMdblLists(BaseMdblList):
	def __init__(self, params):
		super().__init__(params)
		self.sort_method = 'label'

	def fetch_results(self):
		self.lists = []
		for i in ('my_lists', 'external'):
			items = mdblist_api.mdbl_get_lists(i)
			if isinstance(items, list): self.lists.extend(items)

	def parse_item(self, item):
		list_type = 'external' if 'source' in item else 'my_lists'
		return item, list_type

	def get_display_and_plot(self, item, name, item_count, user):
		display = '%s (x%s)' % (name, item_count) if item_count else name
		if 'source' in item: display = '[COLOR cyan][I]%s[/I][/COLOR]' % display
		elif item.get('dynamic'): display = '[COLOR magenta][I]%s[/I][/COLOR]' % display
		elif item.get('private'): display = '[I]%s[/I]' % display
		plot = '[B]Likes[/B]: %s' % item.get('likes')
		return display, plot

class GetTopLists(BaseMdblList):
	def fetch_results(self):
		self.lists = mdblist_api.mdbl_top_lists()

class MdblistBuilder(list_helper.BaseMediaListBuilder):
	mode = 'build_mdbl_list'

	def __init__(self, params):
		super().__init__(params)
		self.slug = params.get('slug')
		self.list_type = params.get('list_type')

	def fetch_results(self):
		return mdblist_api.get_mdbl_list_contents(self.list_type, self.list_id)

	def process_media_types(self, queue, process_list):
		movies, tvshows = Movies({'id_type': 'trakt_dict'}), TVShows({'id_type': 'trakt_dict'})
		for idx, tag in enumerate(process_list, 1):
			mtype = tag['mediatype']
			if   mtype == 'movie':
				queue.put((movies.build_movie_content, idx, {'imdb': tag['imdb_id'], 'tmdb': tag['id']}))
			elif mtype == 'show':
				queue.put((tvshows.build_tvshow_content, idx, {'imdb': tag['imdb_id'], 'tmdb': tag['id']}))
		return {'movies': movies, 'tvshows': tvshows}

class MdbListManager(list_helper.BaseListManager):
	setting_key = 'mdblist_user'
	icon_file = 'mdblist.png'
	heading_id = 32200

	def _get_api(self):
		return mdblist_api

	def get_custom_lists(self):
		list1 = [
			(str(item['id']), item['name'], '%s items' % item['items'], self.icon)
			for item in self.api.mdbl_get_lists('my_lists') if not item['dynamic']
		]
		list2 = [('new', 'Create a new list', '', self.icon)]
		return list1, list2

	def get_default_choices(self):
		choices = [(i.lower(), i, '', self.icon) for i in (watchl_str, coll_str)]
		if self.mediatype == 'tvshow': choices.append(('dropped', 'Toggle Dropped', '', self.icon))
		return choices

	def handle_special_action(self, choice_id, choice_name):
		if 'new' in choice_id:
			kodi_utils.show_busy_dialog()
			try: self.api.make_new_mdbl_list(None)
			except: return kodi_utils.notification(32574)
			finally: kodi_utils.hide_busy_dialog()
			return self.manage()
		if 'dropped' in choice_id:
			args = self.params['tmdb_id'], 'shows', self.params['imdb_id']
			return self.api.hide_unhide_mdbl_items(*args, 'dropped')
		return False

	def check_item_exists(self, choice_id):
		if 'collection' in choice_id: list_items = self.api.mdblist_collection('all', None)
		elif 'watchlist' in choice_id: list_items = self.api.mdblist_watchlist('all', None)
		else: list_items = self.api.get_mdbl_list_contents('my_lists', choice_id)
		return self.tmdb_id in {i['id'] for i in list_items}

	def execute_toggle(self, choice, action_add):
		if 'collection' in choice[0]:
			data = {'shows' if self.mediatype == 'tvshow' else 'movies': [{'ids': {'tmdb': self.tmdb_id}}]}
			return self.api.add_to_collection(data) if action_add else self.api.remove_from_collection(data)
		data = {'shows' if self.mediatype == 'tvshow' else 'movies': [{'tmdb': self.tmdb_id}]}
		return self.api.add_to_list(choice[0], data) if action_add else self.api.remove_from_list(choice[0], data)

