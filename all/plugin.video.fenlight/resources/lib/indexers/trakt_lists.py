# -*- coding: utf-8 -*-
import sys
import json
from random import shuffle
from threading import Thread
from apis.trakt_api import trakt_get_lists, trakt_search_lists, get_trakt_list_contents, trakt_lists_with_media
from indexers.movies import Movies
from indexers.tvshows import TVShows
from indexers.seasons import single_seasons
from indexers.episodes import build_single_episode
from modules import kodi_utils
from modules.utils import paginate_list
from modules.settings import paginate, page_limit, widget_hide_next_page
# logger = kodi_utils.logger

def search_trakt_lists(params):
	def _builder():
		for item in lists:
			try:
				list_key = item['type']
				list_info = item[list_key]
				if list_key == 'officiallist': continue
				item_count = list_info['item_count']
				if list_info['privacy'] == 'private' or item_count == 0: continue
				list_name, user, slug = list_info['name'], list_info['username'], list_info['ids']['slug']
				if not slug: continue
				cm = []
				cm_append = cm.append
				display = '%s | [I]%s (x%s)[/I]' % (list_name, user, str(item_count))
				url = kodi_utils.build_url({'mode': 'trakt.list.build_trakt_list', 'user': user, 'slug': slug, 'list_type': 'user_lists', 'list_name': list_name})
				cm_append(('[B]Like List[/B]', 'RunPlugin(%s)' % kodi_utils.build_url({'mode': 'trakt.trakt_like_a_list', 'user': user, 'list_slug': slug})))
				cm_append(('[B]Unlike List[/B]', 'RunPlugin(%s)' % kodi_utils.build_url({'mode': 'trakt.trakt_unlike_a_list', 'user': user, 'list_slug': slug})))
				listitem = kodi_utils.make_listitem()
				listitem.setLabel(display)
				listitem.setArt({'icon': trakt_icon, 'poster': trakt_icon, 'thumb': trakt_icon, 'fanart': fanart, 'banner': fanart})
				info_tag = listitem.getVideoInfoTag()
				info_tag.setPlot(' ')
				listitem.addContextMenuItems(cm)
				yield (url, listitem, True)
			except: pass
	handle, search_title, trakt_icon, fanart = int(sys.argv[1]), '', kodi_utils.get_icon('trakt'), kodi_utils.get_addon_fanart()
	try:
		mode = params.get('mode')
		page = params.get('new_page', '1')
		search_title = params.get('key_id') or params.get('query')
		lists, pages = trakt_search_lists(search_title, page)
		kodi_utils.add_items(handle, list(_builder()))
		if pages > page:
			new_page = str(int(page) + 1)
			kodi_utils.add_dir({'mode': mode, 'key_id': search_title, 'new_page': new_page}, 'Next Page (%s) >>' % new_page, handle,
								'nextpage', kodi_utils.get_icon('nextpage_landscape'))
	except: pass
	kodi_utils.set_content(handle, 'files')
	kodi_utils.set_category(handle, search_title.capitalize())
	kodi_utils.end_directory(handle)
	kodi_utils.set_view_mode('view.main')

def get_trakt_lists(params):
	def _process():
		for item in data:
			try:
				cm = []
				cm_append = cm.append
				list_name, user, slug, item_count = item['name'], item['user']['ids']['slug'], item['ids']['slug'], item['item_count']
				mode = 'random.build_trakt_lists_contents' if random else 'trakt.list.build_trakt_list'
				url_params = {'mode': mode, 'user': user, 'slug': slug, 'list_type': list_type, 'list_name': list_name}
				if random: url_params['random'] = 'true'
				elif shuffle_lists: url_params['shuffle'] = 'true'
				url = kodi_utils.build_url(url_params)
				if list_type == 'liked_lists':
					display = '%s | [I]%s (x%s)[/I]' % (list_name, user, str(item_count))
					cm_append(('[B]Unlike List[/B]', 'RunPlugin(%s)' % kodi_utils.build_url({'mode': 'trakt.trakt_unlike_a_list', 'user': user, 'list_slug': slug})))
				else:
					display = '%s [I](x%s)[/I]' % (list_name, str(item_count))
					cm_append(('[B]Make New List[/B]', 'RunPlugin(%s)' % kodi_utils.build_url({'mode': 'trakt.make_new_trakt_list'})))
					cm_append(('[B]Delete List[/B]', 'RunPlugin(%s)' % kodi_utils.build_url({'mode': 'trakt.delete_trakt_list', 'user': user, 'list_slug': slug})))
				listitem = kodi_utils.make_listitem()
				listitem.setLabel(display)
				listitem.setArt({'icon': trakt_icon, 'poster': trakt_icon, 'thumb': trakt_icon, 'fanart': fanart, 'banner': fanart})
				info_tag = listitem.getVideoInfoTag()
				info_tag.setPlot(' ')
				listitem.addContextMenuItems(cm)
				yield (url, listitem, True)
			except: pass
	handle, trakt_icon, fanart = int(sys.argv[1]), kodi_utils.get_icon('trakt'), kodi_utils.get_addon_fanart()
	try:
		list_type, random, shuffle_lists = params['list_type'], params.get('random', 'false') == 'true', params.get('shuffle', 'false') == 'true'
		returning_to_list = False
		data = trakt_get_lists(list_type)
		if list_type == 'liked_lists': data = [i['list'] for i in data]
		if data:
			if shuffle_lists:
				returning_to_list = 'build_trakt_lists_contents' in kodi_utils.folder_path()
				if returning_to_list:
					try: data = json.loads(kodi_utils.get_property('fenlight.trakt.lists.order'))
					except: pass
				else:
					shuffle(data)
					kodi_utils.set_property('fenlight.trakt.lists.order', json.dumps(data))
			else:
				kodi_utils.clear_property('fenlight.trakt.lists.order')
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

def get_trakt_user_lists(params):
	def _process():
		for _list in lists:
			try:
				cm = []
				cm_append = cm.append
				item = _list['list']
				item_count = item.get('item_count', 0)
				if item_count == 0: continue
				list_name, user, slug = item['name'], item['user']['ids']['slug'], item['ids']['slug']
				if not slug: continue
				if item['type'] == 'official': user = 'Trakt Official'
				if not user: continue
				display = '%s | [I]%s (x%s)[/I]' % (list_name, user, str(item_count))
				mode = 'random.build_trakt_lists_contents' if random else 'trakt.list.build_trakt_list'
				url_params = {'mode': mode, 'user': user, 'slug': slug, 'list_type': 'user_lists', 'list_name': list_name}
				if random: url_params['random'] = 'true'
				url = kodi_utils.build_url(url_params)
				listitem = kodi_utils.make_listitem()
				if not user == 'Trakt Official':
					cm_append(('[B]Like List[/B]', 'RunPlugin(%s)' % kodi_utils.build_url({'mode': 'trakt.trakt_like_a_list', 'user': user, 'list_slug': slug})))
					cm_append(('[B]Unlike List[/B]', 'RunPlugin(%s)' % kodi_utils.build_url({'mode': 'trakt.trakt_unlike_a_list', 'user': user, 'list_slug': slug})))
				listitem.addContextMenuItems(cm)
				listitem.setLabel(display)
				listitem.setArt({'icon': trakt_icon, 'poster': trakt_icon, 'thumb': trakt_icon, 'fanart': fanart, 'banner': fanart})
				info_tag = listitem.getVideoInfoTag()
				info_tag.setPlot(' ')
				yield (url, listitem, True)
			except: pass
	handle, trakt_icon, fanart = int(sys.argv[1]), kodi_utils.get_icon('trakt'), kodi_utils.get_addon_fanart()
	try:
		list_type, random = params['list_type'], params.get('random', 'false') == 'true'
		page = params.get('new_page', '1')
		new_page = str(int(page) + 1)
		lists = trakt_get_lists(list_type, page)
		kodi_utils.add_items(handle, list(_process()))
		kodi_utils.add_dir({'mode': 'trakt.list.get_trakt_user_lists', 'list_type': list_type, 'new_page': new_page},
				'Next Page (%s) >>' % new_page, handle, 'nextpage', kodi_utils.get_icon('nextpage_landscape'))
	except: pass
	kodi_utils.set_content(handle, 'files')
	kodi_utils.set_category(handle, params.get('category_name', 'Trakt Lists'))
	kodi_utils.end_directory(handle)
	kodi_utils.set_view_mode('view.main')

def in_trakt_lists(params):
	def _process():
		for item in lists:
			try:
				cm = []
				cm_append = cm.append
				item_count = item.get('item_count', 0)
				list_name, user, slug = item['name'], item['user']['ids']['slug'], item['ids']['slug']
				display = '%s | [I]%s (x%s)[/I]' % (list_name, user, str(item_count))
				url = kodi_utils.build_url({'mode': 'trakt.list.build_trakt_list', 'user': user, 'slug': slug, 'list_type': 'user_lists', 'list_name': list_name})
				listitem = kodi_utils.make_listitem()
				if not user == 'Trakt Official':
					cm_append(('[B]Like List[/B]', 'RunPlugin(%s)' % kodi_utils.build_url({'mode': 'trakt.trakt_like_a_list', 'user': user, 'list_slug': slug})))
					cm_append(('[B]Unlike List[/B]', 'RunPlugin(%s)' % kodi_utils.build_url({'mode': 'trakt.trakt_unlike_a_list', 'user': user, 'list_slug': slug})))
				listitem.addContextMenuItems(cm)
				listitem.setLabel(display)
				listitem.setArt({'icon': trakt_icon, 'poster': trakt_icon, 'thumb': trakt_icon, 'fanart': fanart, 'banner': fanart})
				info_tag = listitem.getVideoInfoTag()
				info_tag.setPlot(' ')
				yield (url, listitem, True)
			except: pass
	handle, trakt_icon, fanart = int(sys.argv[1]), kodi_utils.get_icon('trakt'), kodi_utils.get_addon_fanart()
	try:
		lists = trakt_lists_with_media(params['media_type'], params['imdb_id'])
		kodi_utils.add_items(handle, list(_process()))
	except: pass
	kodi_utils.set_content(handle, 'files')
	kodi_utils.set_category(handle, params.get('category_name', 'Trakt Lists'))
	kodi_utils.end_directory(handle)
	kodi_utils.set_view_mode('view.main')

def build_trakt_list(params):
	def _process(function, _list, _type):
		if not _list['list']: return
		if _type in ('movies', 'tvshows'): item_list_extend(function(_list).worker())
		elif _type == 'seasons': item_list_extend(function(_list['list']))
		else: item_list_extend(function('episode.trakt_list', _list['list']))
	def _paginate_list(data, page_no, paginate_start):
		if use_result: total_pages = 1
		elif paginate_enabled:
			limit = page_limit(is_home)
			data, total_pages = paginate_list(data, page_no, limit, paginate_start)
			if is_home: paginate_start = limit
		else: total_pages = 1
		return data, total_pages, paginate_start
	handle, is_external, is_home, list_name, content = int(sys.argv[1]), kodi_utils.external(), kodi_utils.home(), params.get('list_name'), 'movies'
	hide_next_page = is_home and widget_hide_next_page()
	try:
		threads, item_list = [], []
		item_list_extend = item_list.extend
		user, slug, list_type = '', '', ''
		paginate_enabled = paginate(is_home)
		use_result = 'result' in params
		page_no, paginate_start = int(params.get('new_page', '1')), int(params.get('paginate_start', '0'))
		if page_no == 1 and not is_external: kodi_utils.set_property('fenlight.exit_params', kodi_utils.folder_path())
		if use_result: result = params.get('result', [])
		else:
			user, slug, list_type = params.get('user'), params.get('slug'), params.get('list_type')
			with_auth = list_type == 'my_lists'
			result = get_trakt_list_contents(list_type, user, slug, with_auth)
		process_list, total_pages, paginate_start = _paginate_list(result, page_no, paginate_start)
		all_movies = [i for i in process_list if i['type'] == 'movie']
		all_tvshows = [i for i in process_list if i['type'] == 'show']
		all_seasons = [i for i in process_list if i['type'] == 'season']
		all_episodes = [i for i in process_list if i['type'] == 'episode']
		movie_list = {'list': [(i['order'], i['media_ids']) for i in all_movies], 'id_type': 'trakt_dict', 'custom_order': 'true'}
		tvshow_list = {'list': [(i['order'], i['media_ids']) for i in all_tvshows], 'id_type': 'trakt_dict', 'custom_order': 'true'}
		season_list = {'list': all_seasons}
		episode_list = {'list': all_episodes}
		content = max([('movies', len(all_movies)), ('tvshows', len(all_tvshows)), ('seasons', len(all_seasons)), ('episodes', len(all_episodes))], key=lambda k: k[1])[0]
		for item in ((Movies, movie_list, 'movies'), (TVShows, tvshow_list, 'tvshows'),
					(single_seasons, season_list, 'seasons'), (build_single_episode, episode_list, 'episodes')):
			threaded_object = Thread(target=_process, args=item)
			threaded_object.start()
			threads.append(threaded_object)
		[i.join() for i in threads]
		if use_result: return content, [i[0] for i in item_list]
		item_list.sort(key=lambda k: k[1])
		kodi_utils.add_items(handle, [i[0] for i in item_list])
		if total_pages > page_no and not hide_next_page:
			new_page = str(page_no + 1)
			new_params = {'mode': 'trakt.list.build_trakt_list', 'list_type': list_type, 'list_name': list_name,
							'user': user, 'slug': slug, 'paginate_start': paginate_start, 'new_page': new_page}
			kodi_utils.add_dir(new_params, 'Next Page (%s) >>' % new_page, handle, 'nextpage', kodi_utils.get_icon('nextpage_landscape'))
	except: pass
	kodi_utils.set_content(handle, content)
	kodi_utils.set_category(handle, list_name)
	kodi_utils.end_directory(handle, cacheToDisc=False if is_external else True)
	if not is_external:
		if params.get('refreshed') == 'true': kodi_utils.sleep(1000)
		kodi_utils.set_view_mode('view.%s' % content, content, is_external)
