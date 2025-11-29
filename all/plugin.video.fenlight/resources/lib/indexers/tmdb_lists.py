# -*- coding: utf-8 -*-
import os
import sys
import json
from random import shuffle
from threading import Thread
from urllib.parse import unquote
from apis.tmdblist_api import tmdb_list_api
from caches.tmdb_lists import tmdb_lists_cache
from indexers.movies import Movies
from indexers.tvshows import TVShows
from modules.utils import paginate_list, sort_for_article, jsondate_to_datetime as js2date
from modules.settings import paginate, page_limit, lists_sort_order, widget_hide_next_page
from modules import kodi_utils
# logger = kodi_utils.logger

def get_tmdb_lists(params):
	def get_custom_image(list_name, image_type, images):
		try:
			custom_image = [i for i in images if i.rsplit('_', 1)[0] == list_name][0]
			return os.path.join(profile_path, 'images', 'tmdb_lists_%s' % image_type, custom_image)
		except: return ''
	def _process():
		for item in data:
			try:
				list_name, list_id, item_count = item['name'], item['id'], item['number_of_items']
				updated_at = item['updated_at']
				custom_poster = get_custom_image(list_name, 'poster', all_posters)
				if custom_poster: poster = custom_poster
				else: poster = icon
				custom_fanart = get_custom_image(list_name, 'fanart', all_fanart)
				if custom_fanart: fanart = custom_fanart
				else: fanart = background
				mode = 'random.build_tmdb_lists_contents' if random else 'tmdblist.build_tmdb_list'
				url_params = {'mode': mode, 'list_id': list_id, 'list_name': list_name, 'updated_at': updated_at}
				if random: url_params['random'] = 'true'
				if shuffle_lists: url_params['shuffle'] = 'true'
				url = build_url(url_params)
				display = '%s [I](x%02d)[/I]' % (list_name, item_count)
				cm = [('[B]Make New List[/B]', 'RunPlugin(%s)' % build_url({'mode': 'tmdblist.make_new_tmdb_list'})),
				('[B]Edit Properties[/B]', 'RunPlugin(%s)' % build_url({'mode': 'tmdblist.adjust_tmdb_list_properties', 'list_id': list_id, 'updated_at': updated_at,
					'original_list_name': list_name, 'custom_poster': custom_poster, 'custom_fanart': custom_fanart})),
				('[B]Delete List[/B]', 'RunPlugin(%s)' % build_url({'mode': 'tmdblist.delete_tmdb_list', 'list_id': list_id})),
				('[B]Clear Contents Cache[/B]', 'RunPlugin(%s)' % build_url({'mode': 'tmdblist.cache_delete_list_tmdb', 'list_id': list_id})),
				('[B]Clear All Lists Cache[/B]', 'RunPlugin(%s)' % build_url({'mode': 'tmdblist.cache_delete_all_tmdb'}))]
				listitem = kodi_utils.make_listitem()
				listitem.setLabel(display)
				listitem.setArt({'icon': poster, 'poster': poster, 'thumb': poster, 'fanart': fanart, 'banner': fanart})
				info_tag = listitem.getVideoInfoTag()
				info_tag.setPlot(' ')
				listitem.addContextMenuItems(cm)
				yield (url, listitem, True)
			except: pass
	def _new_process():
		url = build_url({'mode': 'tmdblist.make_new_tmdb_list'})
		new_icon = kodi_utils.get_icon('new')
		listitem = kodi_utils.make_listitem()
		listitem.setLabel('[I]Make New TMDb List...[/I]')
		listitem.setArt({'icon': new_icon, 'poster': new_icon, 'thumb': new_icon, 'fanart': background, 'banner': background})
		info_tag = listitem.getVideoInfoTag()
		info_tag.setPlot(' ')
		yield (url, listitem, False)
	handle, icon, background = int(sys.argv[1]), kodi_utils.get_icon('tmdb'), kodi_utils.get_addon_fanart()
	tmdb_image_url = 'https://image.tmdb.org/t/p/%s%s'
	profile_path = kodi_utils.addon_profile()
	all_posters = kodi_utils.list_dirs(os.path.join(profile_path, 'images', 'tmdb_lists_poster'))[1]
	all_fanart = kodi_utils.list_dirs(os.path.join(profile_path, 'images', 'tmdb_lists_fanart'))[1]
	build_url = kodi_utils.build_url
	random, shuffle_lists = params.get('random', 'false') == 'true', params.get('shuffle', 'false') == 'true'
	returning_to_list = False
	try:
		data = get_all_tmdb_lists()
		if data:
			if shuffle_lists:
				returning_to_list = 'build_tmdb_lists_contents' in kodi_utils.folder_path()
				if returning_to_list:
					try: data = json.loads(kodi_utils.get_property('fenlight.tmdb.lists.order'))
					except: pass
				else:
					shuffle(data)
					kodi_utils.set_property('fenlight.tmdb.lists.order', json.dumps(data))
			else:
				kodi_utils.clear_property('fenlight.tmdb.lists.order')
				data.sort(key=lambda k: k['name'])
			result = list(_process())
		else: result = list(_new_process())
		kodi_utils.add_items(handle, result)
	except: pass
	kodi_utils.set_content(handle, 'files')
	kodi_utils.set_category(handle, params.get('category_name', ''))
	if shuffle_lists and not returning_to_list: kodi_utils.focus_index(0)
	kodi_utils.end_directory(handle)
	kodi_utils.set_view_mode('view.main')

def build_tmdb_list(params):
	def _process(function, _list, _type):
		if not _list['list']: return
		item_list_extend(function(_list).worker())
	def _paginate_list(data, page_no, paginate_start):
		if use_result: total_pages = 1
		elif paginate_enabled:
			limit = page_limit(is_home)
			data, total_pages = paginate_list(data, page_no, limit, paginate_start)
			if is_home: paginate_start = limit
		else: total_pages = 1
		return data, total_pages, paginate_start
	handle, is_external, is_home, content = int(sys.argv[1]), kodi_utils.external(), kodi_utils.home(), 'movies'
	hide_next_page = is_home and widget_hide_next_page()
	try:
		threads, item_list = [], []
		item_list_extend = item_list.extend
		user, slug, list_type = '', '', ''
		paginate_enabled = paginate(is_home)
		use_result = 'result' in params
		list_name, list_id, updated_at = params.get('list_name'), params.get('list_id'), params.get('updated_at')
		page_no, paginate_start = int(params.get('new_page', '1')), int(params.get('paginate_start', '0'))
		if page_no == 1 and not is_external: kodi_utils.set_property('fenlight.exit_params', kodi_utils.folder_path())
		if use_result: result = params.get('result', [])
		else: result = get_tmdb_list(list_id)
		result, total_pages, paginate_start = _paginate_list(result, page_no, paginate_start)
		all_movies = [dict(i, **{'order': c}) for c, i in enumerate(result) if i['media_type'] == 'movie']
		all_tvshows = [dict(i, **{'order': c}) for c, i in enumerate(result) if i['media_type'] == 'tv']
		movie_list = {'list': [(i['order'], i['id']) for i in all_movies], 'custom_order': 'true'}
		tvshow_list = {'list': [(i['order'], i['id']) for i in all_tvshows], 'custom_order': 'true'}
		content = max([('movies', len(all_movies)), ('tvshows', len(all_tvshows))], key=lambda k: k[1])[0]
		for item in ((Movies, movie_list, 'movies'), (TVShows, tvshow_list, 'tvshows')):
			threaded_object = Thread(target=_process, args=item)
			threaded_object.start()
			threads.append(threaded_object)
		[i.join() for i in threads]
		if use_result: return content, [i[0] for i in item_list]
		item_list.sort(key=lambda k: k[1])
		kodi_utils.add_items(handle, [i[0] for i in item_list])
		if total_pages > page_no and not hide_next_page:
			new_page = str(page_no + 1)
			new_params = {'mode': 'tmdblist.build_tmdb_list', 'list_id': list_id, 'paginate_start': paginate_start, 'new_page': new_page}
			kodi_utils.add_dir(new_params, 'Next Page (%s) >>' % new_page, handle, 'nextpage', kodi_utils.get_icon('nextpage_landscape'))
	except: pass
	kodi_utils.set_content(handle, content)
	kodi_utils.set_category(handle, list_name)
	kodi_utils.end_directory(handle, cacheToDisc=False if is_external else True)
	if not is_external:
		if params.get('refreshed') == 'true': kodi_utils.sleep(1000)
		kodi_utils.set_view_mode('view.%s' % content, content, is_external)

def adjust_tmdb_list_properties(params):
	list_id = params.get('list_id')
	custom_poster, custom_fanart = params.get('custom_poster', ''), params.get('custom_fanart', '')
	current_name = params.get('list_name', '') or params.get('original_list_name', '')
	choices = [('Change Name', 'Currently [B]%s[/B]' % (current_name), 'list_name'),
				('Make Custom Poster', '', 'make_poster'),
				('Make Custom Fanart', '', 'make_fanart')]
	if custom_poster: choices.append(('Delete Custom Poster', '', 'delete_poster'))
	if custom_fanart: choices.append(('Delete Custom Fanart', '', 'delete_fanart'))
	choices.extend([('Empty List Contents', 'Delete All Contents of %s' % current_name, 'empty_contents'),
					('Import Trakt List', 'Import a Trakt List into %s' % current_name, 'import_trakt')])
	list_items = [{'line1': item[0], 'line2': item[1] or item[0]} for item in choices]
	kwargs = {'items': json.dumps(list_items), 'heading': 'TMDb List Properties', 'multi_line': 'true', 'narrow_window': 'true'}
	action = kodi_utils.select_dialog([i[2] for i in choices], **kwargs)
	if action == None:
		if params.get('refresh_cache', 'false') == 'true': cache_delete_all_tmdb()
		elif params.get('refresh', 'false') == 'true': return kodi_utils.kodi_refresh()
		return None
	if action in ('make_poster', 'make_fanart'):
		art_type = 'Posters' if action == 'make_poster' else 'Fanart'
		shuffle_sort_order = kodi_utils.confirm_dialog(heading='TMDb Lists', text='Use [B]4 Random[/B] %s from List?[CR]OR[CR]Use [B]First 4[/B] %s from List?' % (art_type, art_type),
												ok_label='4 Random', cancel_label='First 4')
		if shuffle_sort_order == None: return adjust_tmdb_list_properties(params)
	if action == 'list_name':
		list_name = rename_tmdb_list(current_name, list_id)
		if not list_name: return adjust_tmdb_list_properties(params)
		current_name = list_name
		params.update({'list_name': current_name, 'refresh_cache': 'true'})
	elif action == 'make_poster':
		new_poster = tmdb_image_maker(current_name, list_id, 'poster', custom_poster, shuffle_sort_order)
		if new_poster is None: return adjust_tmdb_list_properties(params)
		params.update({'custom_poster': new_poster, 'refresh': 'true'})
	elif action == 'make_fanart':
		new_fanart = tmdb_image_maker(current_name, list_id, 'fanart', custom_fanart, shuffle_sort_order)
		if new_fanart is None: return adjust_tmdb_list_properties(params)
		params.update({'custom_fanart': new_fanart, 'refresh': 'true'})
	elif action == 'delete_poster':
		success = delete_current_image(custom_poster)
		if not success: return adjust_tmdb_list_properties(params)
		params.update({'custom_poster': None, 'refresh': 'true'})
	elif action == 'delete_fanart':
		success = delete_current_image(custom_fanart)
		if not success: return adjust_tmdb_list_properties(params)
		params.update({'custom_fanart': None, 'refresh': 'true'})
	elif action == 'empty_contents':
		if not clear_tmdb_list(current_name, list_id): return adjust_tmdb_list_properties(params)
		params.update({'refresh_cache': 'true'})
	elif action == 'import_trakt':
		import_trakt_list_tmdb({'list_name': current_name, 'list_id': list_id})
		params.update({'refresh_cache': 'true'})
	return adjust_tmdb_list_properties(params)

def delete_current_image(custom_image):
	os.remove(custom_image)
	kodi_utils.sleep(1000)
	if kodi_utils.path_exists(custom_image): return False
	return True

def tmdb_image_maker(list_name, list_id, image_type, custom_image, shuffle_sort_order):
	from modules.utils import make_image
	kodi_utils.show_busy_dialog()
	content = get_tmdb_list(list_id)
	if shuffle_sort_order: shuffle(content)
	images = []
	if image_type == 'poster': image_dimension, image_key = 'w780', 'poster_path'
	else: image_dimension, image_key = 'w1280', 'backdrop_path'
	for item in content:
		if item[image_key]: images.append('https://image.tmdb.org/t/p/%s%s' % (image_dimension, item[image_key]))
		if len(images) == 4: break
	final_image = make_image('tmdb_lists', image_type, list_name, images, custom_image)
	kodi_utils.hide_busy_dialog()
	return final_image

def add_to_tmdb_list(list_id, items):
	data = tmdb_list_api.add_remove_from_list(list_id, items, 'post')
	if not data.get('success'):
		kodi_utils.notification('Error Adding to List')
		return False
	return True

def remove_from_tmdb_list(list_id, items):
	data = tmdb_list_api.add_remove_from_list(list_id, items, 'delete')
	if not data.get('success'):
		kodi_utils.notification('Error Removing from List')
		return False
	return True

def rename_tmdb_list(current_name, list_id):
	list_name = kodi_utils.kodi_dialog().input('Please Choose a Name for the New List', defaultt=current_name)
	if list_name == None: return None
	tmdb_list_api.rename_list(list_id, list_name)
	return list_name

def check_item_status(list_id, media_type, media_id):
	item_status = tmdb_list_api.item_status(list_id, media_type, media_id)
	return item_status['success']

def make_new_tmdb_list(params):
	suggested_list_name, chosen_list = '', None
	external_creation = params.get('external_creation', 'false') == 'true'
	if not external_creation and kodi_utils.confirm_dialog(heading='TMDb Lists', text='Import a Trakt List to populate this new list?',
																				ok_label='Yes', cancel_label='No'):
		from apis.trakt_api import get_trakt_list_selection
		chosen_list = get_trakt_list_selection(['default', 'personal'])
		if chosen_list == None: return
		suggested_list_name = chosen_list.get('name')
	list_name = kodi_utils.kodi_dialog().input('Please Choose a Name for the New TMDb List', defaultt=suggested_list_name)
	if not list_name:
		kodi_utils.notification('List Creation Cancelled', 3000)
		return None
	list_name = unquote(list_name)
	data = tmdb_list_api.make_list(list_name)
	if not data.get('success'):
		kodi_utils.notification('Error Creating List')
		return None
	if chosen_list:
		new_contents = process_trakt_list(chosen_list)
		success = process_add_to_list(data.get('id'), new_contents)
	tmdb_lists_cache.clear_all_lists()
	if not external_creation: kodi_utils.kodi_refresh()
	return data.get('id')

def delete_tmdb_list(params):
	if not kodi_utils.confirm_dialog(heading='TMDb Lists', text='Are You Sure?', ok_label='Yes', cancel_label='No'): return
	list_id = params['list_id']
	data = tmdb_list_api.delete_list(list_id)
	if not data.get('success'): return kodi_utils.notification('Error Deleting List')
	tmdb_lists_cache.clear_list(list_id)
	tmdb_lists_cache.clear_all_lists()
	kodi_utils.kodi_refresh()

def clear_tmdb_list(list_name, list_id):
	if not list_change_warning(list_name): return None
	data = tmdb_list_api.clear_list(list_id)
	if not data.get('success'):
		kodi_utils.notification('Error Clearing List Contents')
		return None
	tmdb_lists_cache.clear_list(list_id)
	tmdb_lists_cache.clear_all_lists()
	return True

def get_all_tmdb_lists():
	return tmdb_list_api.get_user_lists()

def get_tmdb_list(list_id):
	return tmdb_list_api.get_list_details(list_id)

def cache_delete_all_tmdb(params=None):
	tmdb_lists_cache.clear_all()
	kodi_utils.notification('Success')
	kodi_utils.kodi_refresh()

def cache_delete_list_tmdb(params):
	tmdb_lists_cache.clear_list(params['list_id'])
	tmdb_lists_cache.clear_all_lists()
	kodi_utils.notification('Success')
	kodi_utils.kodi_refresh()

def import_trakt_list_tmdb(params):
	if not list_change_warning(params['list_name']): return None
	from apis.trakt_api import get_trakt_list_selection
	list_id = params.get('list_id', '')
	chosen_list = get_trakt_list_selection(['default', 'personal'])
	if chosen_list == None: return None
	if kodi_utils.confirm_dialog(heading='TMDb Lists', text='Rename List to Match Trakt List Name?', ok_label='Yes', cancel_label='No'): rename_list = True
	else: rename_list = False
	trakt_list_name = chosen_list.get('name')
	new_contents = process_trakt_list(chosen_list)
	success = process_add_to_list(list_id, new_contents)
	if success and rename_list:
			tmdb_list_api.rename_list(list_id, trakt_list_name)
	kodi_utils.notification('Success. Items added' if success else 'Error adding items', 2000)

def process_trakt_list(chosen_list):
	from apis.trakt_api import trakt_fetch_collection_watchlist, get_trakt_list_contents
	tmdb_media_converter = {'movie': 'movie', 'tvshow': 'tv', 'show': 'tv'}
	media_type_check = {'movie': 'movie', 'show': 'tvshow', 'tvshow': 'tvshow'}
	new_contents = []
	new_contents_append = new_contents.append
	trakt_list_type, trakt_list_name = chosen_list.get('list_type'), chosen_list.get('name')
	if trakt_list_type in ('collection', 'watchlist'):
		trakt_media_type = chosen_list.get('media_type')
		result = trakt_fetch_collection_watchlist(trakt_list_type, trakt_media_type)
		try:
			sort_order = lists_sort_order(trakt_list_type)
			if sort_order == 0: result = sort_for_article(result, 'title')
			elif sort_order == 1: result.sort(key=lambda k: k['collected_at'], reverse=True)
			else: result.sort(key=lambda k: k.get('released'), reverse=True)
		except: pass
	else:
		result = get_trakt_list_contents(trakt_list_type, chosen_list.get('user'), chosen_list.get('slug'), trakt_list_type == 'my_lists')
		try: result.sort(key=lambda k: (k['order']))
		except: pass
	for item in result:
		try:
			media_type = item.get('type') or media_type_check[trakt_media_type]
			if trakt_list_type in ('my_lists', 'liked_lists') and item['type'] not in ('movie', 'show'): continue
			media_id = item['media_ids']['tmdb']
			if media_id in (None, 'None', ''): continue
			new_contents_append({'media_type': tmdb_media_converter[media_type], 'media_id': media_id})
		except: continue
	return new_contents

def process_add_to_list(list_id, new_contents):
	success = False
	kodi_utils.show_busy_dialog()
	try:
		if add_to_tmdb_list(list_id, {'items': new_contents}):
			success = True
			tmdb_lists_cache.clear_list(list_id)
			tmdb_lists_cache.clear_all_lists()
		else: pass
	except: pass
	kodi_utils.hide_busy_dialog()
	return success

def list_change_warning(list_name, text='[B]CAUTION!!![/B][CR][CR]This will change the contents of [B]%s[/B]. Continue?'):
	return kodi_utils.confirm_dialog(heading='TMDb Lists', text=text % list_name, ok_label='Yes', cancel_label='No')

