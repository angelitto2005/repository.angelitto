import sys
from queue import SimpleQueue
from threading import Thread
from indexers import mdblist_api
from menus.movies import Movies
from menus.tvshows import TVShows
from modules import kodi_utils
from modules.utils import paginate_list, jsondate_to_datetime, TaskPool
from modules.settings import paginate, page_limit, nav_jump_use_alphabet
# logger = kodi_utils.logger

KODI_VERSION, ls = kodi_utils.get_kodi_version(), kodi_utils.local_string
build_url, make_listitem = kodi_utils.build_url, kodi_utils.make_listitem
fanart = kodi_utils.get_addoninfo('fanart')
default_icon = kodi_utils.media_path('mdblist.png')
item_jump = kodi_utils.media_path('item_jump.png')
add2menu_str, add2folder_str = ls(32730), ls(32731)
deletelist_str, nextpage_str, jump2_str = ls(32781), ls(32799), ls(32964)
mdblist_str, newlist_str = 'MDBList', '[B]Make a new MDBList list[/B]'

def search_mdbl_lists(params):
	def _process():
		for item in lists:
			try:
				cm = []
				cm_append = cm.append
				name, user, slug, list_id = item['name'], item['user_name'], item['slug'], item['id']
				likes, item_count = item['likes'] or 0, item.get('items', '?')
				display = '[B]%s[/B] | [I](x%s) - %s[/I]' % (name.upper(), str(item_count), user)
				plot = '[B]Likes[/B]: %s' % likes
				url = build_url({'mode': 'build_mdbl_list', 'user': user, 'slug': slug, 'list_id': list_id, 'list_type': 'user_lists', 'name': name})
				cm_append((add2menu_str, 'RunPlugin(%s)' % build_url({'mode': 'menu_editor.add_external', 'name': name, 'iconImage': 'mdblist.png'})))
				cm_append((add2folder_str, 'RunPlugin(%s)' % build_url({'mode': 'menu_editor.shortcut_folder_add_item', 'name': name, 'iconImage': 'mdblist.png'})))
				listitem = make_listitem()
				listitem.setLabel(display)
				listitem.setArt({'icon': default_icon, 'poster': default_icon, 'thumb': default_icon, 'fanart': fanart, 'banner': default_icon})
				listitem.setInfo('video', {'plot': plot}) if KODI_VERSION < 20 else listitem.getVideoInfoTag().setPlot(plot)
				listitem.addContextMenuItems(cm)
				yield (url, listitem, True)
			except: pass
	page = params.get('new_page', '1')
	search_title = params.get('search_title') or kodi_utils.dialog.input('SALTS')
	if search_title: lists, pages = mdblist_api.mdbl_search_lists(search_title), '1'
	else: lists, pages = [], page
	__handle__ = int(sys.argv[1])
	kodi_utils.add_items(__handle__, list(_process()))
	if int(pages) > int(page):
		url = {'mode': 'build_mdbl_list.search_mdb_lists', 'search_title': search_title, 'new_page': int(page) + 1}
		kodi_utils.add_dir(__handle__, url, nextpage_str)
	kodi_utils.set_category(__handle__, search_title)
	kodi_utils.set_content(__handle__, 'files')
	kodi_utils.end_directory(__handle__)
	kodi_utils.set_view_mode('view.main')

def get_mdbl_lists(params):
	def _process():
		for item in lists:
			try:
				cm = []
				cm_append = cm.append
				list_type = 'external' if 'source' in item else 'my_lists'
				name, user, list_id = item['name'], item['user_name'], item['id']
				slug, likes, item_count = item.get('slug', ''), item.get('likes', 0), item.get('items', '?')
				display = '%s (x%s)' % (name, item_count) if item_count else name
				plot = '[B]Likes[/B]: %s' % likes if likes else ''
				if list_type == 'external': display = '[COLOR cyan][I]%s[/I][/COLOR]' % display
				elif item.get('dynamic'): display = '[COLOR magenta][I]%s[/I][/COLOR]' % display
				elif item.get('private'): display = '[I]%s[/I]' % display
				url = build_url({'mode': 'build_mdbl_list', 'user': user, 'slug': slug, 'list_id': list_id, 'list_type': list_type, 'name': name})
				cm_append((newlist_str, 'RunPlugin(%s)' % build_url({'mode': 'mdblist.make_new_mdbl_list'})))
				cm_append((deletelist_str, 'RunPlugin(%s)' % build_url({'mode': 'mdblist.delete_mdbl_list', 'list_id': list_id})))
				cm_append((add2menu_str, 'RunPlugin(%s)' % build_url({'mode': 'menu_editor.add_external', 'name': display, 'iconImage': 'mdblist.png'})))
				cm_append((add2folder_str, 'RunPlugin(%s)' % build_url({'mode': 'menu_editor.shortcut_folder_add_item', 'name': display, 'iconImage': 'mdblist.png'})))
				listitem = make_listitem()
				listitem.setLabel(display)
				listitem.setArt({'icon': default_icon, 'poster': default_icon, 'thumb': default_icon, 'fanart': fanart, 'banner': default_icon})
				listitem.setInfo('video', {'plot': plot}) if KODI_VERSION < 20 else listitem.getVideoInfoTag().setPlot(plot)
				listitem.addContextMenuItems(cm, replaceItems=False)
				yield (url, listitem, True)
			except: pass
	lists = []
	lists += mdblist_api.mdbl_get_lists('my_lists')
	lists += mdblist_api.mdbl_get_lists('external')
	__handle__ = int(sys.argv[1])
	kodi_utils.add_items(__handle__, list(_process()))
	kodi_utils.set_category(__handle__, params.get('name'))
	kodi_utils.set_sort_method(__handle__, 'label')
	kodi_utils.set_content(__handle__, 'files')
	kodi_utils.end_directory(__handle__)
	kodi_utils.set_view_mode('view.main')

def get_mdbl_top_lists(params):
	def _process():
		for item in lists:
			try:
				cm = []
				cm_append = cm.append
				name, user, slug, list_id = item['name'], item['user_name'], item['slug'], item['id']
				likes, item_count = item['likes'], item.get('items', '?')
				display = '[B]%s[/B] | [I](x%s) - %s[/I]' % (name, item_count, user)
				plot = '[B]Likes[/B]: %s' % likes
				url = build_url({'mode': 'build_mdbl_list', 'user': user, 'slug': slug, 'list_id': list_id, 'name': name})
				cm_append((add2menu_str, 'RunPlugin(%s)' % build_url({'mode': 'menu_editor.add_external', 'name': name, 'iconImage': 'mdblist.png'})))
				cm_append((add2folder_str, 'RunPlugin(%s)' % build_url({'mode': 'menu_editor.shortcut_folder_add_item', 'name': name, 'iconImage': 'mdblist.png'})))
				listitem = make_listitem()
				listitem.setLabel(display)
				listitem.setArt({'icon': default_icon, 'poster': default_icon, 'thumb': default_icon, 'fanart': fanart, 'banner': default_icon})
				listitem.setInfo('video', {'plot': plot}) if KODI_VERSION < 20 else listitem.getVideoInfoTag().setPlot(plot)
				listitem.addContextMenuItems(cm)
				yield (url, listitem, True)
			except: pass
	lists = mdblist_api.mdbl_top_lists()
	__handle__ = int(sys.argv[1])
	kodi_utils.add_items(__handle__, list(_process()))
	kodi_utils.set_category(__handle__, params.get('name'))
	kodi_utils.set_content(__handle__, 'files')
	kodi_utils.end_directory(__handle__)
	kodi_utils.set_view_mode('view.main')

def build_mdbl_list(params):
	def _thread_target(q):
		while not q.empty():
			try: target, *args = q.get()
			except: pass
			else: target(*args)
	__handle__, _queue, is_widget = int(sys.argv[1]), SimpleQueue(), kodi_utils.external_browse()
	max_threads = int(kodi_utils.get_setting('salts.max_threads', '100'))
	use_alphabet = nav_jump_use_alphabet() > 0
	user, slug, name = params.get('user'), params.get('slug'), params.get('name')
	list_type, list_id = params.get('list_type'), params.get('list_id')
	letter, page = params.get('new_letter', 'None'), int(params.get('new_page', '1'))
	results = mdblist_api.get_mdbl_list_contents(list_type, list_id)
	if paginate() and results: process_list, total_pages = paginate_list(results, page, letter, page_limit())
	else: process_list, total_pages = results, 1
	movies, tvshows = Movies({'id_type': 'trakt_dict'}), TVShows({'id_type': 'trakt_dict'})
	for idx, tag in enumerate(process_list, 1):
		mtype = tag['mediatype']
		if   mtype == 'movie':
			_queue.put((movies.build_movie_content, idx, {'imdb': tag['imdb_id'], 'tmdb': tag['id']}))
		elif mtype == 'show':
			_queue.put((tvshows.build_tvshow_content, idx, {'imdb': tag['imdb_id'], 'tmdb': tag['id']}))
	max_threads = min(_queue.qsize(), max_threads)
	threads = (Thread(target=_thread_target, args=(_queue,)) for i in range(max_threads))
	threads = list(TaskPool.process(threads))
	[i.join() for i in threads]
	items = movies.items + tvshows.items
	items.sort(key=lambda k: int(k[1].getProperty('salts_sort_order')))
	content, total = max(
		('movies', movies), ('tvshows', tvshows), key=lambda k: len(k[1].items)
	)
	if total_pages > 2 and not is_widget and use_alphabet:
		url = {'mode': 'build_navigate_to_page', 'current_page': page, 'total_pages': total_pages,
				'user': user, 'slug': slug, 'name': name, 'list_id': list_id, 'list_type': list_type,
				'transfer_mode': 'build_mdbl_list', 'mediatype': 'Media'}
		kodi_utils.add_dir(__handle__, url, jump2_str, iconImage=item_jump, isFolder=False)
	kodi_utils.add_items(__handle__, items)
	if total_pages > page:
		url = {'mode': 'build_mdbl_list', 'new_page': page + 1, 'new_letter': letter,
				'user': user, 'slug': slug, 'name': name, 'list_id': list_id, 'list_type': list_type}
		kodi_utils.add_dir(__handle__, url, nextpage_str)
	kodi_utils.set_category(__handle__, name)
	kodi_utils.set_content(__handle__, content)
	kodi_utils.end_directory(__handle__, False if is_widget else None)
	kodi_utils.set_view_mode('view.%s' % content, content)

def mdbl_account_info():
	try:
		kodi_utils.show_busy_dialog()
		account_info = mdblist_api.call_mdblist('user')
		joined = jsondate_to_datetime(account_info['date_joined'], '%Y-%m-%dT%H:%M:%SZ')
		api_requests = account_info['api_requests']
		remaining = api_requests - account_info['api_requests_count']
		body = []
		append = body.append
		append('[B]Username:[/B] %s' % account_info['username'])
		append('[B]Joined:[/B] %s' % joined)
		append('[B]Supporter:[/B] %s' % account_info['is_supporter'])
		append('[B]API Request Limit:[/B] %s' % api_requests)
		append('[B]API Request Remaining:[/B] %s' % remaining)
		kodi_utils.hide_busy_dialog()
		return kodi_utils.show_text(mdblist_str.upper(), '\n\n'.join(body), font_size='large')
	except: kodi_utils.hide_busy_dialog()

