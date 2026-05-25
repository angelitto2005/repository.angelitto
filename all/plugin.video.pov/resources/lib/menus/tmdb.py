import sys
import json
from queue import SimpleQueue
from threading import Thread
from indexers import tmdb_api
from menus.movies import Movies
from menus.tvshows import TVShows
from modules import kodi_utils
from modules.settings import paginate, page_limit, nav_jump_use_alphabet, get_resolution
from modules.utils import paginate_list, TaskPool
# logger = kodi_utils.logger

KODI_VERSION, ls = kodi_utils.get_kodi_version(), kodi_utils.local_string
build_url, make_listitem = kodi_utils.build_url, kodi_utils.make_listitem
default_fanart = kodi_utils.get_addoninfo('fanart')
default_icon = kodi_utils.media_path('tmdb.png')
item_jump = kodi_utils.media_path('item_jump.png')
add2menu_str, add2folder_str, jump2_str = ls(32730), ls(32731), ls(32964)
newlist_str, deletelist_str, nextpage_str = ls(32780), ls(32781), ls(32799)
editprop_str, clearprop_str = '[B]Edit List Properties[/B]', '[B]Clear List Cache[/B]'
tmdb_image_base = tmdb_api.tmdb_image_base

def get_tmdb_lists(params):
	def _process():
		for item in lists:
			try:
				cm = []
				cm_append = cm.append
				poster_path, fanart_path = item['poster_path'], item['backdrop_path']
				poster = tmdb_image_base % (image_resolution['poster'], poster_path) if poster_path else default_icon
				fanart = tmdb_image_base % (image_resolution['fanart'], fanart_path) if fanart_path else default_fanart
				name, user = item['name'], item['account_object_id']
				item_count, list_id = item['number_of_items'], item['id']
				display = '%s (x%s)' % (name, item_count) if item_count else name
#				if not item['public']: display = '[COLOR cyan][I]%s[/I][/COLOR]' % display
#				plot = '[B]Updated[/B]: %s[CR]%s' % (item['updated_at'][:10], item['description'])
				edit_params = {'list_id': list_id, 'name': name, 'poster': poster_path, 'fanart': fanart_path, 'public': item['public']}
				url = build_url({'mode': 'build_tmdb_list', 'user': user, 'list_id': list_id, 'name': name})
				cm_append((add2menu_str, 'RunPlugin(%s)' % build_url({'mode': 'menu_editor.add_external', 'name': display, 'iconImage': 'tmdb.png'})))
				cm_append((add2folder_str, 'RunPlugin(%s)' % build_url({'mode': 'menu_editor.shortcut_folder_add_item', 'name': display, 'iconImage': 'tmdb.png'})))
				cm_append((editprop_str, 'RunPlugin(%s)' % build_url({'mode': 'tmdb.edit_tmdb_list', **edit_params})))
				cm_append((deletelist_str, 'RunPlugin(%s)' % build_url({'mode': 'tmdb.update_tmdb_list', 'action': 'delete', **edit_params})))
				cm_append((clearprop_str, 'RunPlugin(%s)' % build_url({'mode': 'tmdb.update_tmdb_list'})))
				listitem = make_listitem()
				listitem.setLabel(display)
				listitem.setArt({'icon': poster, 'poster': poster, 'thumb': poster, 'fanart': fanart, 'banner': poster})
#				listitem.setInfo('video', {'plot': plot}) if KODI_VERSION < 20 else listitem.getVideoInfoTag().setPlot(plot)
				listitem.addContextMenuItems(cm, replaceItems=False)
				yield (url, listitem, True)
			except: pass
	image_resolution = get_resolution()
	lists = tmdb_api.user_lists()
	__handle__ = int(sys.argv[1])
	kodi_utils.add_items(__handle__, list(_process()))
	kodi_utils.set_category(__handle__, params.get('name'))
	kodi_utils.set_sort_method(__handle__, 'label')
	kodi_utils.set_content(__handle__, 'files')
	kodi_utils.end_directory(__handle__)
	kodi_utils.set_view_mode('view.main')

def build_tmdb_list(params):
	def _thread_target(q):
		while not q.empty():
			try: target, *args = q.get()
			except: pass
			else: target(*args)
	__handle__, _queue, is_widget = int(sys.argv[1]), SimpleQueue(), kodi_utils.external_browse()
	max_threads = int(kodi_utils.get_setting('pov.max_threads', '100'))
	use_alphabet = nav_jump_use_alphabet() > 0
	user, name, list_id = params.get('user'), params.get('name'), params.get('list_id')
	letter, page = params.get('new_letter', 'None'), int(params.get('new_page', '1'))
	results = tmdb_api.list_details(list_id)
	if paginate() and results: process_list, total_pages = paginate_list(results, page, letter, page_limit())
	else: process_list, total_pages = results, 1
	movies, tvshows = Movies({'id_type': 'tmdb_id'}), TVShows({'id_type': 'tmdb_id'})
	for idx, tag in enumerate(process_list, 1):
		mtype = tag['media_type']
		if   mtype == 'movie':
			_queue.put((movies.build_movie_content, idx, tag['id']))
		elif mtype == 'tv':
			_queue.put((tvshows.build_tvshow_content, idx, tag['id']))
	max_threads = min(_queue.qsize(), max_threads)
	threads = (Thread(target=_thread_target, args=(_queue,)) for i in range(max_threads))
	threads = list(TaskPool.process(threads))
	[i.join() for i in threads]
	items = movies.items + tvshows.items
	items.sort(key=lambda k: int(k[1].getProperty('pov_sort_order')))
	content, total = max(
		('movies', movies), ('tvshows', tvshows), key=lambda k: len(k[1].items)
	)
	if total_pages > 2 and not is_widget and use_alphabet:
		url = {'mode': 'build_navigate_to_page', 'current_page': page, 'total_pages': total_pages,
				'user': user, 'name': name, 'list_id': list_id,
				'transfer_mode': 'build_tmdb_list', 'mediatype': 'Media'}
		kodi_utils.add_dir(__handle__, url, jump2_str, iconImage=item_jump, isFolder=False)
	kodi_utils.add_items(__handle__, items)
	if total_pages > page:
		url = {'mode': 'build_tmdb_list', 'new_page': page + 1, 'new_letter': letter,
				'user': user, 'name': name, 'list_id': list_id}
		kodi_utils.add_dir(__handle__, url, nextpage_str)
	kodi_utils.set_category(__handle__, name)
	kodi_utils.set_content(__handle__, content)
	kodi_utils.end_directory(__handle__, False if is_widget else None)
	kodi_utils.set_view_mode('view.%s' % content, content)

def update_tmdb_list(params):
	if params.get('action', '') == 'delete':
		if not kodi_utils.confirm_dialog(): return
		tmdb_api.list_delete(params['list_id'])
	tmdb_api.clear_tmdbl_cache()
	kodi_utils.container_refresh()

def edit_tmdb_list(params):
	image_resolution = get_resolution()
	heading = ls(tmdb_api.tmdb_list_heading).replace('[B]', '').replace('[/B]', '')
	choices = [
		('name', params['name']),
		('poster', params['poster']),
		('fanart', params['fanart']),
		('public', 'true' if params['public'] in ('true', '1') else 'false'),
		('save', 'Save and Exit'),
		('cancel', 'Cancel')
	]
	list_items = [
		{'line1': i[1], 'line2': i[0], 'icon':
		tmdb_image_base % (image_resolution['poster' if i[0] == 'poster' else 'fanart'], i[1])
		if i[0] in ('poster', 'fanart') and i[1] not in ('clear', 'None') else
		default_icon}
		for i in choices
	]
	kwargs = {'items': json.dumps(list_items), 'heading': heading, 'multi_line': 'true'}
	choice = kodi_utils.select_dialog([i[0] for i in choices], **kwargs)
	if choice in ('cancel', None): return
	if   'name' in choice:
		name = kodi_utils.dialog.input('New List Name', defaultt=params['name'])
		params['name'] = name.strip() or params['name']
	elif 'public' in choice:
		text = 'Make %s Private?' % params['name']
		params['public'] = 'true' if not kodi_utils.confirm_dialog(text=text, top_space=True) else 'false'
	elif choice in ('poster', 'fanart'):
		art = artwork_choice_tmdb_list(choice, params['list_id'], params['name'], image_resolution, default_icon)
		params[choice] = params[choice] if art is None else art
	else:
		data = {
			'name': params['name'],
			'poster_path': '' if params['poster'] == 'clear' else params['poster'],
			'backdrop_path': '' if params['fanart'] == 'clear' else params['fanart'],
			'public': 'true' if params.get('public') in ('true', '1') else 'false',
		}
		data = {k: v for k, v in data.items() if v not in ('None', None)}
		if tmdb_api.list_update(params['list_id'], data)['success']:
			tmdb_api.clear_tmdbl_cache()
			kodi_utils.container_refresh()
			return kodi_utils.notification(32576)
		else: return kodi_utils.notification(32574)
	return edit_tmdb_list(params)

def artwork_choice_tmdb_list(key, list_id, list_title, resolution, icon):
	path = 'poster_path' if key == 'poster' else 'backdrop_path'
	choices = [
		(item[path], item['title'] if item['media_type'] == 'movie' else item['name'],
		tmdb_image_base % (resolution[key], item[path]) if item[path] else icon)
		for item in tmdb_api.list_details(list_id)
	]
	choices += [('clear', 'Clear', icon)]
	list_items = [{'line1': item[1], 'line2': item[0], 'icon': item[2]} for item in choices]
	kwargs = {'items': json.dumps(list_items), 'heading': list_title, 'enumerate': 'true', 'multi_line': 'true'}
	return kodi_utils.select_dialog([i[0] for i in choices], **kwargs)

