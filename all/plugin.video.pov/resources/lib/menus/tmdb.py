import json
from indexers import tmdb_api, list_helper
from menus.movies import Movies
from menus.tvshows import TVShows
from modules import kodi_utils, settings
from modules.settings import get_resolution
# logger = kodi_utils.logger

KODI_VERSION, ls = kodi_utils.get_kodi_version(), kodi_utils.local_string
build_url, make_listitem, media_path = kodi_utils.build_url, kodi_utils.make_listitem, kodi_utils.media_path
show_busy_dialog, hide_busy_dialog = kodi_utils.show_busy_dialog, kodi_utils.hide_busy_dialog
select_dialog, confirm_dialog = kodi_utils.select_dialog, kodi_utils.confirm_dialog
notification, container_refresh = kodi_utils.notification, kodi_utils.container_refresh
fanart = kodi_utils.get_addoninfo('fanart')
default_icon = kodi_utils.media_path('tmdb.png')
add2menu_str, add2folder_str = ls(32730), ls(32731)
newlist_str, deletelist_str = ls(32780), ls(32781)
watchl_str, fav_str, coll_str = ls(32500), ls(32453), ls(32499)
editprop_str, clearprop_str = '[B]Edit List Properties[/B]', '[B]Clear List Cache[/B]'
tmdb_image_base = tmdb_api.tmdb_image_base

def get_tmdb_lists(params):
	return BaseTmdbList(params).build()

def build_tmdb_list(params):
	return TmdbListBuilder(params).build()

def update_tmdb_list(params):
	if params.get('action', '') == 'delete':
		if not confirm_dialog(): return
		tmdb_api.list_delete(params['list_id'])
	tmdb_api.clear_tmdbl_cache()
	container_refresh()

def artwork_choice_tmdb_list(key, list_id, list_title, resolution, icon):
	path = 'poster_path' if key == 'poster' else 'backdrop_path'
	choices = [
		(item[path], item['title'] if item['media_type'] == 'movie' else item['name'],
		tmdb_image_base % (resolution[key], item[path]) if item[path] else icon)
		for item in tmdb_api.list_details(list_id)
	]
	choices += [('clear', 'Clear', icon)]
	list_items = [{'line1': item[1], 'line2': item[0], 'icon': item[2]} for item in choices]
	kwargs = {'items': json.dumps(list_items), 'heading': list_title, 'enumerate': 'true'}
	return select_dialog([i[0] for i in choices], **kwargs)

def edit_tmdb_list(params):
	res = settings.get_resolution()
	default_icon = media_path('tmdb.png')
	heading = ls(tmdb_api.tmdblist_heading).replace('[B]', '').replace('[/B]', '')

	def get_icon(key, val):
		if key in ('poster', 'fanart') and val not in ('clear', 'None'): return tmdb_image_base % (res[key], val)
		return default_icon

	while True:
		is_pub = 'true' if params.get('public') in ('true', '1') else 'false'
		choices = [
			('name', params['name']), ('poster', params['poster']),  ('fanart', params['fanart']),
			('public', is_pub),       ('save', 'Save and Exit'),     ('cancel', 'Cancel')
		]
		list_items = [{'line1': v, 'line2': k, 'icon': get_icon(k, v)} for k, v in choices]
		choice = select_dialog([c[0] for c in choices], items=json.dumps(list_items), heading=heading)
		if choice in ('cancel', None): return
		if choice == 'name':
			name = kodi_utils.dialog.input('New List Name', defaultt=params['name'])
			if name.strip(): params['name'] = name.strip()
		elif choice == 'public':
			text = 'Make %s Private?' % params['name']
			params['public'] = 'false' if confirm_dialog(text=text) else 'true'
		elif choice in ('poster', 'fanart'):
			art = artwork_choice_tmdb_list(choice, params['list_id'], params['name'], res, default_icon)
			if art is not None: params[choice] = art
		elif choice == 'save':
			data = {
				'name': params['name'],
				'poster_path': '' if params['poster'] == 'clear' else params['poster'],
				'backdrop_path': '' if params['fanart'] == 'clear' else params['fanart'],
				'public': is_pub,
			}
			data = {k: v for k, v in data.items() if v not in ('None', None)}
			success = tmdb_api.list_update(params['list_id'], data).get('success')
			if not success: notification(32574)
			tmdb_api.clear_tmdbl_cache()
			container_refresh()
			return notification(32576)

def trakt_list_to_tmdb(params, api):
	from threading import Thread
	from indexers.trakt_api import get_trakt_list_contents
	from modules.utils import chunks
	send_str = 'Sending list to TMDB...'
	progressBG = kodi_utils.progressDialogBG
	progressBG.create(send_str, api.tmdblist_heading)
	try:
		list_id, user, slug = params['trakt_list_id'], params['user'], params['list_slug']
		items = get_trakt_list_contents(params.get('list_type'), list_id, user, slug)
		len_items, wait = len(items), sum(1000 for i in chunks(items, 500))
		for count, item in enumerate(items, 1):
			kodi_utils.sleep(int(wait / len_items))
			if (mtype := item['type']) in ('movie', 'show') and 'tmdb' in item[mtype]['ids'] and item[mtype]['ids']['tmdb']:
				item['export'] = {'media_type': 'tv' if mtype == 'show' else mtype, 'media_id': item[mtype]['ids']['tmdb']}
			else: item['export'] = None
			progressBG.update(int(count / len_items * 100), send_str)
		items = {'items': [i['export'] for i in items if i['export']]}
		Thread(target=api.list_add_items, args=(params['list_id'], items)).start()
		api.clear_tmdbl_cache()
	except: notification(32574)
	else: notification('List sent to TMDB')
	finally: progressBG.close()

def mdbl_list_to_tmdb(params, api):
	from threading import Thread
	from indexers.mdblist_api import get_mdbl_list_contents
	from modules.utils import chunks
	send_str = 'Sending list to TMDB...'
	progressBG = kodi_utils.progressDialogBG
	progressBG.create(send_str, api.tmdblist_heading)
	try:
		items = get_mdbl_list_contents(params.get('list_type'), params['mdbl_list_id'])
		len_items, wait = len(items), sum(1000 for i in chunks(items, 500))
		for count, item in enumerate(items, 1):
			kodi_utils.sleep(int(wait / len_items))
			if (mtype := item['mediatype']) in ('movie', 'show') and item['id']:
				item['export'] = {'media_type': 'tv' if mtype == 'show' else mtype, 'media_id': item['id']}
			else: item['export'] = None
			progressBG.update(int(count / len_items * 100), send_str)
		items = {'items': [i['export'] for i in items if i['export']]}
		Thread(target=api.list_add_items, args=(params['list_id'], items)).start()
		api.clear_tmdbl_cache()
	except: notification(32574)
	else: notification('List sent to TMDB')
	finally: progressBG.close()

class BaseTmdbList(list_helper.BaseList):
	def process_results(self):
		for item in self.lists:
			try:
				cm = []
				cm_append = cm.append
				poster_path, fanart_path = item['poster_path'], item['backdrop_path']
				poster = tmdb_image_base % (self.image_resolution['poster'], poster_path) if poster_path else default_icon
				_fanart = tmdb_image_base % (self.image_resolution['fanart'], fanart_path) if fanart_path else fanart
				name, user, list_id = item['name'], item['account_object_id'], item['id']
				item_count = item.get('number_of_items')
				edit_params = {'list_id': list_id, 'name': name, 'poster': poster_path, 'fanart': fanart_path, 'public': item['public']}
				url = build_url({'mode': 'build_tmdb_list', 'user': user, 'list_id': list_id, 'name': name})
				display = '%s (x%s)' % (name, item_count) if item_count else name
				plot = None
				cm_append((add2menu_str, 'RunPlugin(%s)' % build_url({'mode': 'menu_editor.add_external', 'name': display, 'iconImage': 'tmdb.png'})))
				cm_append((add2folder_str, 'RunPlugin(%s)' % build_url({'mode': 'menu_editor.shortcut_folder_add_item', 'name': display, 'iconImage': 'tmdb.png'})))
				cm_append((editprop_str, 'RunPlugin(%s)' % build_url({'mode': 'tmdb.edit_tmdb_list', **edit_params})))
				cm_append((deletelist_str, 'RunPlugin(%s)' % build_url({'mode': 'tmdb.update_tmdb_list', 'action': 'delete', **edit_params})))
				cm_append((clearprop_str, 'RunPlugin(%s)' % build_url({'mode': 'tmdb.update_tmdb_list'})))
				listitem = make_listitem()
				listitem.setLabel(display)
				listitem.setArt({'icon': poster, 'poster': poster, 'thumb': poster, 'fanart': _fanart, 'banner': poster})
				if plot: listitem.setInfo('video', {'plot': plot}) if KODI_VERSION < 20 else listitem.getVideoInfoTag().setPlot(plot)
				listitem.addContextMenuItems(cm, replaceItems=False)
				yield (url, listitem, True)
			except: pass

	def fetch_results(self):
		self.image_resolution = get_resolution()
		self.lists = tmdb_api.user_lists()

class TmdbListBuilder(list_helper.BaseMediaListBuilder):
	mode = 'build_tmdb_list'

	def fetch_results(self):
		return tmdb_api.list_details(self.list_id)

	def process_media_types(self, queue, process_list):
		movies, tvshows = Movies({'id_type': 'tmdb_id'}), TVShows({'id_type': 'tmdb_id'})
		for idx, tag in enumerate(process_list, 1):
			mtype = tag['media_type']
			if   mtype == 'movie':
				queue.put((movies.build_movie_content, idx, tag['id']))
			elif mtype == 'tv':
				queue.put((tvshows.build_tvshow_content, idx, tag['id']))
		return {'movies': movies, 'tvshows': tvshows}

class TmdbManager(list_helper.BaseListManager):
	setting_key = 'tmdb.token'
	icon_file = 'tmdb.png'

	def __init__(self, params):
		super().__init__(params)
		self.mediatype = 'tv' if params.get('mediatype') == 'tvshow' else 'movie'
		self.heading_id = self.api.tmdblist_heading

	def _get_api(self):
		return tmdb_api

	def get_default_choices(self):
		if self.params.get('trakt_list_name') or self.params.get('mdbl_list_name'): return []
		return [(i.lower(), i, '', self.icon) for i in (watchl_str, fav_str)]

	def get_custom_lists(self):
		res, tmdb_img_base = settings.get_resolution(), self.api.tmdb_image_base
		list1 = [
			(str(item['id']),
			 item['name'],
			 '%s items' % item['number_of_items'],
			 tmdb_img_base % (res['poster'], item['poster_path']) if item['poster_path'] else self.icon)
			for item in self.api.user_lists()
		]
		list_name = self.params.get('trakt_list_name') or self.params.get('mdbl_list_name') or ''
		list2 = [('new', 'Create a new list', list_name, self.icon), ('clear', 'Clear list cache', '', self.icon)]
		return list1, list2

	def handle_special_action(self, choice_id, choice_name):
		if 'clear' in choice_id:
			self.api.clear_tmdbl_cache()
			return self.manage()
		if 'new' in choice_id:
			show_busy_dialog()
			try:
				list_name = self.params.get('trakt_list_name') or self.params.get('mdbl_list_name') or ''
				result = self.api.list_create(list_name)
				if result and result.get('success'): self.api.clear_tmdbl_cache()
			except: return notification(32574)
			finally: hide_busy_dialog()
			return self.manage()
		if 'trakt_list_id' in self.params or 'mdbl_list_id' in self.params:
			func = trakt_list_to_tmdb if 'trakt_list_id' in self.params else mdbl_list_to_tmdb
			return func({**self.params, 'list_id': choice_id}, self.api)
		return False

	def check_item_exists(self, choice_id):
		if choice_id in ('watchlist', 'favorites'):
			list_items = self.api.watchlist(self.mediatype) if choice_id == 'watchlist' else self.api.favorites(self.mediatype)
			return self.tmdb_id in {i['id'] for i in list_items}
		status = self.api.list_status(choice_id, self.mediatype, self.tmdb_id)
		return bool(status and status.get('success'))

	def execute_toggle(self, choice, action_add):
		if choice[0] in ('watchlist', 'favorites'):
			list_type = 'favorite' if choice[0] == 'favorites' else 'watchlist'
			data = {'media_type': self.mediatype, 'media_id': self.tmdb_id, list_type: action_add}
			success = self.api.add_to_watchlist_favorites(data, list_type).get('success')
		else:
			data = {'items': [{'media_type': self.mediatype, 'media_id': self.tmdb_id}]}
			func = self.api.list_add_items if action_add else self.api.list_remove_items
			success = func(choice[0], data).get('success')
		if success:
			self.api.clear_tmdbl_cache()
			if not action_add: container_refresh()
			return notification(32576)
		return notification(32574)

