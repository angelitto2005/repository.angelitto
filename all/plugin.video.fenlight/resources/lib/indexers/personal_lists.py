# -*- coding: utf-8 -*-
import os
import sys
import json
from random import shuffle
from threading import Thread
from urllib.parse import unquote
from caches.personal_lists_cache import personal_lists_cache, get_timestamp
from indexers.movies import Movies
from indexers.tvshows import TVShows
from modules.utils import paginate_list, sort_for_article
from modules.settings import paginate, page_limit, lists_sort_order, widget_hide_next_page
from modules import kodi_utils
# logger = kodi_utils.logger

def get_personal_lists(params):
	def get_custom_image(list_name, image_type, images):
		try:
			custom_image = [i for i in images if i.rsplit('_', 1)[0] == list_name][0]
			return os.path.join(profile_path, 'images', 'personal_lists_%s' % image_type, custom_image)
		except: return ''
	def _process():
		for item in data:
			try:
				cm = []
				cm_append = cm.append
				list_name, sort_order, list_total = item['name'], item['sort_order'], item['total']
				custom_poster = get_custom_image(list_name, 'poster', all_posters)
				if custom_poster: poster = custom_poster
				else: poster = icon
				custom_fanart = get_custom_image(list_name, 'fanart', all_fanart)
				if custom_fanart: fanart = custom_fanart
				else: fanart = background
				mode = 'random.build_personal_lists_contents' if random else 'personal_lists.build_personal_list'
				url_params = {'mode': mode, 'list_name': list_name, 'category_name': list_name, 'sort_order': sort_order}
				if random: url_params['random'] = 'true'
				if shuffle_lists: url_params['shuffle'] = 'true'
				url = build_url(url_params)
				display = '%s [I](x%02d)[/I]' % (list_name, list_total)
				cm = [('[B]Make New List[/B]', 'RunPlugin(%s)' % build_url({'mode': 'personal_lists.make_new_personal_list'})),
				('[B]Edit Properties[/B]', 'RunPlugin(%s)' % build_url({'mode': 'personal_lists.adjust_personal_list_properties',
					'original_list_name': list_name, 'original_sort_order': sort_order, 'custom_poster': custom_poster, 'custom_fanart': custom_fanart})),
				('[B]Delete List[/B]', 'RunPlugin(%s)' % build_url({'mode': 'personal_lists.delete_personal_list', 'list_name': list_name}))]
				listitem = kodi_utils.make_listitem()
				listitem.setLabel(display)
				listitem.setArt({'icon': poster, 'poster': poster, 'thumb': poster, 'fanart': fanart, 'banner': fanart})
				info_tag = listitem.getVideoInfoTag()
				info_tag.setPlot(' ')
				listitem.addContextMenuItems(cm)
				yield (url, listitem, True)
			except: pass
	def _new_process():
		url = build_url({'mode': 'personal_lists.make_new_personal_list'})
		new_icon = kodi_utils.get_icon('new')
		listitem = kodi_utils.make_listitem()
		listitem.setLabel('[I]Make New Personal List...[/I]')
		listitem.setArt({'icon': new_icon, 'poster': new_icon, 'thumb': new_icon, 'fanart': background, 'banner': background})
		info_tag = listitem.getVideoInfoTag()
		info_tag.setPlot(' ')
		yield (url, listitem, False)
	profile_path = kodi_utils.addon_profile()
	all_posters = kodi_utils.list_dirs(os.path.join(profile_path, 'images', 'personal_lists_poster'))[1]
	all_fanart = kodi_utils.list_dirs(os.path.join(profile_path, 'images', 'personal_lists_fanart'))[1]
	icon, background = kodi_utils.get_icon('lists'), kodi_utils.get_addon_fanart()
	build_url = kodi_utils.build_url
	random, shuffle_lists = params.get('random', 'false') == 'true', params.get('shuffle', 'false') == 'true'
	handle = int(sys.argv[1])
	try:
		data = get_all_personal_lists()
		if data:
			if shuffle_lists:
				returning_to_list = 'build_personal_lists_contents' in kodi_utils.folder_path()
				if returning_to_list:
					try: data = json.loads(kodi_utils.get_property('fenlight.personal.lists.order'))
					except: pass
				else:
					shuffle(data)
					kodi_utils.set_property('fenlight.personal.lists.order', json.dumps(data))
			else:
				kodi_utils.clear_property('fenlight.personal.lists.order')
				data.sort(key=lambda k: k['name'])
			result = list(_process())
		else: result = list(_new_process())
		kodi_utils.add_items(handle, result)
	except: pass
	kodi_utils.set_content(handle, 'files')
	kodi_utils.set_category(handle, 'Personal Lists')
	if shuffle_lists and not returning_to_list: kodi_utils.focus_index(0)
	kodi_utils.end_directory(handle)
	kodi_utils.set_view_mode('view.main')

def build_personal_list(params):
	def _process(function, _list):
		item_list_extend(function(_list).worker())
	def _paginate_list(data, page_no, paginate_start):
		if use_result: total_pages = 1
		elif paginate_enabled:
			limit = page_limit(is_home)
			data, total_pages = paginate_list(data, page_no, limit, paginate_start)
			if is_home: paginate_start = limit
		else: total_pages = 1
		return data, total_pages, paginate_start
	handle, is_external, is_home, list_name = int(sys.argv[1]), kodi_utils.external(), kodi_utils.home(), 'Personal List'
	hide_next_page = is_home and widget_hide_next_page()
	try:
		threads, item_list, content = [], [], 'movies'
		item_list_extend = item_list.extend
		paginate_enabled = paginate(is_home)
		use_result = 'result' in params
		page_no, paginate_start = int(params.get('new_page', '1')), int(params.get('paginate_start', '0'))
		if page_no == 1 and not is_external: kodi_utils.set_property('fenlight.exit_params', kodi_utils.folder_path())
		if use_result: result = params.get('result', [])
		else: result = get_personal_list(params)
		process_list, total_pages, paginate_start = _paginate_list(result, page_no, paginate_start)
		movie_list = {'list': [(c, i['media_id']) for c, i in enumerate(process_list) if i['type'] == 'movie'], 'custom_order': 'true'}
		tvshow_list = {'list': [(c, i['media_id']) for c, i in enumerate(process_list) if i['type'] == 'tvshow'], 'custom_order': 'true'}
		content = 'movies' if len(movie_list['list']) > len(tvshow_list['list']) else 'tvshows'
		for item in ((Movies, movie_list), (TVShows, tvshow_list)):
			if not item[1]['list']: continue
			threaded_object = Thread(target=_process, args=item)
			threaded_object.start()
			threads.append(threaded_object)
		[i.join() for i in threads]
		if use_result: return content, [i[0] for i in item_list]
		item_list.sort(key=lambda k: k[1])
		list_name, sort_order = params.get('list_name'), params.get('sort_order')
		kodi_utils.add_items(handle, [i[0] for i in item_list])
		if total_pages > page_no and not hide_next_page:
			new_page = str(page_no + 1)
			new_params = {'mode': 'personal_lists.build_personal_list', 'list_name': list_name, 'sort_order': sort_order,
			'paginate_start': paginate_start, 'new_page': new_page}
			kodi_utils.add_dir(new_params, 'Next Page (%s) >>' % new_page, handle, 'nextpage', kodi_utils.get_icon('nextpage_landscape'))
	except: pass
	kodi_utils.set_content(handle, content)
	kodi_utils.set_category(handle, list_name)
	kodi_utils.end_directory(handle, cacheToDisc=False if is_external else True)
	if not is_external:
		if params.get('refreshed') == 'true': kodi_utils.sleep(1000)
		kodi_utils.set_view_mode('view.%s' % content, content, is_external)

def get_all_personal_lists():
	return personal_lists_cache.get_lists()

def delete_personal_list(params):
	list_name = params.get('list_name', '')
	if not kodi_utils.confirm_dialog(heading='Personal Lists', text='Delete [B]%s[/B] Personal List?' % list_name): return
	if personal_lists_cache.delete_list(list_name): return kodi_utils.kodi_refresh()
	kodi_utils.notification('Error Deleting List', 3000)

def delete_personal_list_contents(params):
	list_name = params.get('list_name', '')
	if not list_change_warning(list_name): return
	if personal_lists_cache.delete_list_contents(list_name): return
	kodi_utils.notification('Error Deleting List Contents', 3000)

def get_personal_list(params):
	list_name, sort_order = params['list_name'], params['sort_order']
	contents = personal_lists_cache.get_list(list_name)
	try:
		if sort_order == 'shuffle':
			shuffle(contents)
		elif sort_order in ('', '0', 'None', '1'):
			contents = sort_for_article(contents, 'title')
		elif sort_order in ('1', '2'):
			reverse = sort_order != '1'
			contents.sort(key=lambda k: k['date_added'], reverse=reverse)
		else:
			reverse = sort_order != '3'
			contents.sort(key=lambda k: (k['release_date'] is None, k['release_date']), reverse=reverse)
	except: pass
	return contents

def make_new_personal_list(params):
	suggested_list_name, chosen_list = '', []
	external_creation = params.get('external_creation', 'false') == 'true'
	if not external_creation and kodi_utils.confirm_dialog(
		heading='Personal Lists',text='Import a Trakt List to populate this new list?', ok_label='Yes', cancel_label='No'):
		from apis.trakt_api import get_trakt_list_selection
		chosen_list = get_trakt_list_selection(['default', 'personal', 'liked'])
		if chosen_list == None: return None, None
		suggested_list_name = chosen_list.get('name')
	list_name = personal_list_name(suggested_list_name)
	if list_name == None: return None, None
	sort_order = personal_sort_order()
	if sort_order == None: return None, None
	success = personal_lists_cache.make_list(list_name, sort_order)
	if not success:
		kodi_utils.notification('Error Creating List', 3000)
		return None, None
	if chosen_list:
		new_contents = process_trakt_list(chosen_list)
		result = personal_lists_cache.add_many_list_items(new_contents, list_name)
	if not external_creation and any([kodi_utils.path_check('get_personal_lists') or kodi_utils.external()]): kodi_utils.kodi_refresh()
	return list_name, sort_order

def adjust_personal_list_properties(params):
	sort_order_dict = {'0': 'Title', '1': 'Date Added (asc)', '2': 'Date Added (desc)', '3': 'Release Date (asc)', '4': 'Release Date (desc)'}
	original_list_name, original_sort_order = params.get('original_list_name', ''), params.get('original_sort_order', '')
	list_name, sort_order = params.get('list_name', ''), params.get('sort_order', '')
	custom_poster, custom_fanart = params.get('custom_poster', ''), params.get('custom_fanart', '')
	current_name, current_sort_order = list_name or original_list_name, sort_order or original_sort_order
	choices = [('Change Name', 'Currently [B]%s[/B]' % (current_name), 'list_name'),
				('Change Sort Order', 'Currently [B]%s[/B]' % sort_order_dict.get(current_sort_order, 'None'), 'sort_order'),
				('Make Custom Poster', '', 'make_poster'),
				('Make Custom Fanart', '', 'make_fanart')]
	if custom_poster: choices.append(('Delete Custom Poster', '', 'delete_poster'))
	if custom_fanart: choices.append(('Delete Custom Fanart', '', 'delete_fanart'))
	choices.extend([('Empty List Contents', 'Delete All Contents of %s' % current_name, 'empty_contents'),
					('Import Trakt List', 'Import a Trakt List into %s' % current_name, 'import_trakt')])
	list_items = [{'line1': item[0], 'line2': item[1] or item[0]} for item in choices]
	kwargs = {'items': json.dumps(list_items), 'heading': 'Personal List Properties', 'multi_line': 'true', 'narrow_window': 'true'}
	action = kodi_utils.select_dialog([i[2] for i in choices], **kwargs)
	if action == None: return kodi_utils.kodi_refresh() if params.get('refresh', 'false') == 'true' else None
	if action in ('make_poster', 'make_fanart'):
		art_type = 'Posters' if action == 'make_poster' else 'Fanart'
		shuffle_lists = kodi_utils.confirm_dialog(heading='Personal Lists', text='Use [B]4 Random[/B] %s from List?[CR]OR[CR]Use [B]First 4[/B] %s from List?' % (art_type, art_type),
												ok_label='4 Random', cancel_label='First 4')
		if shuffle_lists == None: return adjust_personal_list_properties(params)
		if shuffle_lists: artwork_sort_order = 'shuffle'
		else: artwork_sort_order = current_sort_order
	if action == 'list_name':
		list_name = personal_list_name(current_name)
		if list_name == None: return adjust_personal_list_properties(params)
		current_name = list_name
		params.update({'list_name': current_name, 'refresh': 'true'})
	elif action == 'sort_order':
		sort_order = personal_sort_order()
		if sort_order == None: return adjust_personal_list_properties(params)
		current_sort_order = sort_order
		params.update({'sort_order': current_sort_order, 'refresh': 'true'})
	elif action == 'make_poster':
		new_poster = personal_image_maker(current_name, 'poster', artwork_sort_order, custom_poster)
		if new_poster is None: return adjust_personal_list_properties(params)
		params.update({'custom_poster': new_poster, 'refresh': 'true'})
	elif action == 'make_fanart':
		new_fanart = personal_image_maker(current_name, 'fanart', artwork_sort_order, custom_fanart)
		if new_fanart is None: return adjust_personal_list_properties(params)
		params.update({'custom_fanart': new_fanart, 'refresh': 'true'})
	elif action == 'delete_poster':
		success = delete_current_image(custom_poster)
		if not success: return adjust_personal_list_properties(params)
		params.update({'custom_poster': None, 'refresh': 'true'})
	elif action == 'delete_fanart':
		success = delete_current_image(custom_fanart)
		if not success: return adjust_personal_list_properties(params)
		params.update({'custom_fanart': None, 'refresh': 'true'})
	elif action == 'empty_contents':
		delete_personal_list_contents({'list_name': current_name})
		params.update({'refresh': 'true'})
	elif action == 'import_trakt':
		import_trakt_list({'list_name': current_name, 'sort_order': sort_order})
		params.update({'refresh': 'true'})
	personal_lists_cache.update_list_details(current_name, current_sort_order, original_list_name)
	return adjust_personal_list_properties(params)

def delete_current_image(custom_image):
	os.remove(custom_image)
	kodi_utils.sleep(100)
	if kodi_utils.path_exists(custom_image): return False
	return True

def personal_image_maker(list_name, image_type, sort_order, custom_image):
	from threading import Thread
	from modules import metadata
	from modules.utils import get_datetime, get_current_timestamp, make_image
	from modules.settings import tmdb_api_key, mpaa_region
	kodi_utils.show_busy_dialog()
	content = get_personal_list({'list_name': list_name, 'sort_order': str(sort_order)})
	images = []
	api_key, mpaa, current_time, current_timestamp = tmdb_api_key(), mpaa_region(), get_datetime(), get_current_timestamp()
	for item in content:
		if item['type'] == 'movie': function = metadata.movie_meta
		else: function = metadata.tvshow_meta
		meta = function('tmdb_id', item['media_id'], api_key, mpaa, current_time, current_timestamp)
		if meta.get(image_type): images.append(meta[image_type])
		if len(images) == 4: break
	final_image = make_image('personal_lists', image_type, list_name, images, custom_image)
	kodi_utils.hide_busy_dialog()
	return final_image

def personal_list_name(current_name=''):
	list_name = kodi_utils.kodi_dialog().input('Please Choose a Name for the New List', defaultt=current_name)
	if not list_name: return None
	list_name = unquote(list_name)
	return list_name

def personal_sort_order():
	choices = [('Title (asc)', '0'), ('Date Added (asc)', '1'), ('Date Added (desc)', '2'), ('Release Date (asc)', '3'), ('Release Date (desc)', '4')]
	list_items = [{'line1': item[0]} for item in choices]
	kwargs = {'items': json.dumps(list_items), 'heading': 'List Sort Order', 'narrow_window': 'true'}
	sort_order = kodi_utils.select_dialog([i[1] for i in choices], **kwargs)
	if sort_order == None: return None
	return sort_order

def import_trakt_list(params):
	media_type_check = {'movie': 'movie', 'show': 'tvshow', 'tvshow': 'tvshow'}
	list_name, sort_order = params['list_name'], params['sort_order']
	if not list_change_warning(list_name): return
	from apis.trakt_api import get_trakt_list_selection, trakt_fetch_collection_watchlist, get_trakt_list_contents
	chosen_list = get_trakt_list_selection(['default', 'personal', 'liked'])
	if chosen_list == None: return
	trakt_list_name = chosen_list.get('name')
	new_contents = process_trakt_list(chosen_list)
	result = personal_lists_cache.add_many_list_items(new_contents, list_name)
	if result == 'Success':
		if kodi_utils.confirm_dialog(heading='Personal Lists', text='Rename List to Match Trakt List Name?', ok_label='Yes', cancel_label='No'):
			personal_lists_cache.update_list_details(trakt_list_name, sort_order, list_name)
	kodi_utils.notification(result, 3000)

def process_trakt_list(chosen_list):
	from apis.trakt_api import trakt_fetch_collection_watchlist, get_trakt_list_contents
	media_type_check = {'movie': 'movie', 'show': 'tvshow', 'tvshow': 'tvshow'}
	new_contents = []
	new_contents_append = new_contents.append
	current_time = get_timestamp()
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
		# try: result.sort(key=lambda k: (k['collected_at']))
		# except: pass
	else:
		result = get_trakt_list_contents(trakt_list_type, chosen_list.get('user'), chosen_list.get('slug'), trakt_list_type == 'my_lists')
		try: result.sort(key=lambda k: (k['order']))
		except: pass
	for count, item in enumerate(result):
		try:
			media_type = item.get('type') or media_type_check[trakt_media_type]
			if trakt_list_type in ('my_lists', 'liked_lists') and item['type'] not in ('movie', 'show'): continue
			media_id = item['media_ids']['tmdb']
			if media_id in (None, 'None', ''): continue
			title = item['title']
			try: release_date = item['released'].split('T')[0]
			except: release_date = item['released']
			date_added = current_time + count
			new_contents_append({'media_id': str(media_id), 'title': title, 'type': media_type_check[media_type],
								'release_date': release_date, 'date_added': str(date_added)})
		except: continue
	return new_contents

def list_change_warning(list_name, text='[B]CAUTION!!![/B][CR][CR]This will change the contents of [B]%s[/B]. Continue?'):
	return kodi_utils.confirm_dialog(heading='Personal Lists', text=text % list_name, ok_label='Yes', cancel_label='No')