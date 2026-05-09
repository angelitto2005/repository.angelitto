import re
import time
import requests
from threading import Thread
from caches import mdbl_cache
from caches.main_cache import cache_object
from caches.meta_cache import cache_function
from indexers.metadata import movie_external_id, tvshow_external_id
from modules import kodi_utils, settings
from modules.cache import check_databases
from modules.utils import make_thread_list, sort_for_article, jsondate_to_datetime, paginate_list, get_datetime, TaskPool

EXPIRES_1_HOURS, MAX_LIST_ITEMS = 1, 250_000
get_setting, logger, js2date = kodi_utils.get_setting, kodi_utils.logger, jsondate_to_datetime
review_provider_id = {1: 'Trakt', 2: 'TMDb', 3: 'RT', 4: 'Metacritics'}
rank_map = {'0': 'mild', '1': 'mild', '2': 'moderate', '3': 'moderate', '4': 'severe', '5': 'severe'}
guide_map = {'Nudity': 'nudity', 'Violence': 'violence', 'Profanity': 'profanity', 'Alcohol': 'alcohol'}
base_url = 'https://api.mdblist.com/%s'
timeout = 5.05
session = requests.Session()
session.mount('https://api.mdblist.com', requests.adapters.HTTPAdapter(pool_maxsize=100))

def call_mdblist(path, params=None, json=None, method=None):
	params = params or {}
	params['apikey'] = get_setting('mdblist.token')
	try:
		response = session.request(method or 'get', base_url % path, params=params, json=json, timeout=timeout)
		result = response.json() if 'json' in response.headers.get('Content-Type', '') else response.text
		if not response.ok: response.raise_for_status()
		return result
	except requests.exceptions.RequestException as e:
		logger('mdblist error', str(e))

def mdbl_parentsguide(imdb_id, mediatype):
	def _process(url):
		items = []
		append = items.append
		html = requests.get(url, timeout=timeout).text
		for key, val in guide_map.items():
			try:
				match = re.search(rf"{key}\:\ \d", html, re.S)
				if not match: continue
				rank = rank_map[match.group().split(': ')[-1]]
				append({'title': val, 'ranking': rank, 'listings': []})
			except: pass
		return items
	mediatype = 'show' if mediatype == 'tvshow' else 'movie'
	string = 'mdbl_%s_parentsguide_%s' % (mediatype, imdb_id)
	url = 'https://www.mdblist.com/%s/%s' % (mediatype, imdb_id)
	return cache_function(_process, string, url)

def mdbl_media_info(imdb_id, mediatype):
	if not get_setting('mdblist.token'): return
	mediatype = 'show' if mediatype == 'tvshow' else 'movie'
	string = 'mdbl_%s_mediainfo_%s' % (mediatype, imdb_id)
	url = '%s/%s/%s?append_to_response=review' % ('imdb', mediatype, imdb_id)
	return cache_function(call_mdblist, string, url)

def mdblist_droplist(mediatype, page_no, letter):
	results = mdbl_get_hidden_items('dropped')
	return [{'imdb_id': '', 'id': i} for i in results], 1

def mdbl_get_hidden_items(list_type):
	def _get_mdbl_ids(item):
		tmdb_id = get_mdbl_tvshow_id(item['show']['ids'])
		results_append(tmdb_id)
	def _process(url):
		hidden_data = call_mdblist(url)['shows']
		threads = list(make_thread_list(_get_mdbl_ids, hidden_data, Thread))
		[i.join() for i in threads]
		return results
	results = []
	results_append = results.append
	string = 'mdbl_hidden_items_%s' % list_type
	url = 'sync/dropped'
	return mdbl_cache.cache_mdbl_object(_process, string, url)

def hide_unhide_mdbl_items(action, mediatype, media_id, list_type):
	if not action in ('hide', 'unhide'):
		try:
			hidden_data = set(map(str, mdbl_get_hidden_items('dropped')))
			action = 'unhide' if action in hidden_data else 'hide'
		except: return kodi_utils.notification(32574)
	mediatype = 'movies' if mediatype in ['movie', 'movies'] else 'shows'
	key = 'tmdb' if mediatype == 'movies' else 'imdb'
	url = 'sync/dropped' if action == 'hide' else 'sync/dropped/remove'
	data = {mediatype: [{'ids': {key: media_id}}]}
	call_mdblist(url, json=data, method='post')
	mdbl_sync_activities()
	kodi_utils.container_refresh()

def mdblist_collection(mediatype, page_no, letter):
	string = 'mdbl_collection'
	url = 'sync/collection'
	original_list = mdbl_cache.cache_mdbl_object(mdbl_collection_watchlist_items, string, url)
	if mediatype == 'all':
		original_list = original_list['movies'] + original_list['shows']
		for i in original_list: i.update({'id': i['movie' if 'movie' in i else 'show']['ids']['tmdb']})
		return original_list
	original_list = original_list[mediatype]
	key = 'movie' if mediatype == 'movies' else 'show'
	for i in original_list: i.update({
		'id': i[key]['ids']['tmdb'], 'imdb_id': i[key]['ids']['imdb'],
		'title': i[key]['title'], 'release_year': i[key]['year']
	})
	sort_key = settings.lists_sort_order('collection')
	if   sort_key == 2: original_list.sort(key=lambda k: k['release_year'], reverse=True)
	elif sort_key == 1: original_list.sort(key=lambda k: k['collected_at'], reverse=True)
	else: original_list = sort_for_article(original_list, 'title', settings.ignore_articles())
	if settings.paginate():
		limit = settings.page_limit()
		final_list, total_pages = paginate_list(original_list, page_no, letter, limit)
	else: final_list, total_pages = original_list, 1
	return final_list, total_pages

def mdblist_watchlist(mediatype, page_no, letter):
	string = 'mdbl_watchlist'
	url = 'watchlist/items'
	original_list = mdbl_cache.cache_mdbl_object(mdbl_collection_watchlist_items, string, url)
	if mediatype == 'all':
		original_list = original_list['movies'] + original_list['shows']
		return original_list
	original_list = original_list[mediatype]
	if not settings.show_unaired_watchlist():
		current_date = get_datetime()
		str_format = '%Y-%m-%d'
		original_list = [i for i in original_list if i.get('release_date') and js2date(i.get('release_date'), str_format, remove_time=True) <= current_date]
	sort_key = settings.lists_sort_order('watchlist')
	if   sort_key == 2: original_list.sort(key=lambda k: k['release_date'] or '', reverse=True)
	elif sort_key == 1: original_list.sort(key=lambda k: k['watchlist_at'], reverse=True)
	else: original_list = sort_for_article(original_list, 'title', settings.ignore_articles())
	if settings.paginate():
		limit = settings.page_limit()
		final_list, total_pages = paginate_list(original_list, page_no, letter, limit)
	else: final_list, total_pages = original_list, 1
	return final_list, total_pages

def mdbl_collection_watchlist_items(url):
	params = {'limit': 5000 if 'sync' in url else 1000}
	items = {'movies': [], 'shows': []}
	try:
		for _ in range(MAX_LIST_ITEMS // params['limit']):
			result = call_mdblist(url, params=params)
			if result is None: break
			if 'movies' in result: items['movies'] += result['movies']
			if 'shows' in result: items['shows'] += result['shows']
			if not result['pagination']['has_more']: break
			if 'page' in result['pagination']:
				params['offset'] = result['pagination']['page'] * result['pagination']['limit']
			else: params['offset'] = result['pagination']['offset'] + result['pagination']['limit']
	finally: return items

def add_to_list(list_id, data):
	url = 'watchlist/items/add' if list_id == 'watchlist' else 'lists/%s/items/add' % list_id
	result = call_mdblist(url, json=data, method='post')
	if result['added']['movies'] + result['added']['shows'] == 0: return kodi_utils.notification(32574)
	kodi_utils.notification(32576)
	mdbl_sync_activities()
	return result

def remove_from_list(list_id, data):
	url = 'watchlist/items/remove' if list_id == 'watchlist' else 'lists/%s/items/remove' % list_id
	result = call_mdblist(url, json=data, method='post')
	if result['removed']['movies'] + result['removed']['shows'] == 0: return kodi_utils.notification(32574)
	kodi_utils.notification(32576)
	mdbl_sync_activities()
	kodi_utils.container_refresh()
	return result

def add_to_collection(data):
	result = call_mdblist('sync/collection', json=data, method='post')
	if result['updated']['movies'] + result['updated']['shows'] == 0: return kodi_utils.notification(32574)
	kodi_utils.notification(32576)
	mdbl_sync_activities()
	return result

def remove_from_collection(data):
	result = call_mdblist('sync/collection/remove', json=data, method='post')
	if result['removed']['movies'] + result['removed']['shows'] == 0: return kodi_utils.notification(32574)
	kodi_utils.notification(32576)
	mdbl_sync_activities()
	kodi_utils.container_refresh()
	return result

def mdbl_search_lists(query):
	query = requests.utils.quote(query)
	string = 'mdbl_search_lists_%s' % query
	url = 'lists/search?query=%s' % query
	return cache_object(call_mdblist, string, url, json=False, expiration=EXPIRES_1_HOURS)

def mdbl_top_lists():
	string = 'mdbl_top_lists'
	url = 'lists/top'
	return cache_object(call_mdblist, string, url, json=False)

def get_mdbl_list_contents(list_type, list_id):
	string = 'mdbl_list_contents_%s_%s' % (list_type, list_id)
	if list_type == 'external': url = 'external/lists/%s/items?unified=true' % list_id
	else: url = 'lists/%s/items?unified=true' % list_id
	return mdbl_cache.cache_mdbl_object(call_mdblist, string, url)

def mdbl_get_lists(list_type):
	if list_type == 'external': string, url = 'mdbl_external', 'external/lists/user'
	else: string, url = 'mdbl_my_lists', 'lists/user'
	return mdbl_cache.cache_mdbl_object(call_mdblist, string, url)

def make_new_mdbl_list(params):
	from urllib.parse import unquote
	list_title = kodi_utils.dialog.input('SALTS')
	if not list_title: return
	list_name = unquote(list_title)
	data = {'name': list_name, 'private': False}
	result = call_mdblist('lists/user/add', json=data, method='post')
	if result is None: return kodi_utils.notification(32574)
	mdbl_cache.clear_mdbl_list_data('my_lists')
	kodi_utils.notification(32576)
	kodi_utils.container_refresh()

def delete_mdbl_list(params):
	if not kodi_utils.confirm_dialog(): return
	list_id = params['list_id']
	url = 'lists/%s' % list_id
	result = call_mdblist(url, method='delete')
	if result is None: return kodi_utils.notification(32574)
	mdbl_cache.clear_mdbl_list_data('my_lists')
	kodi_utils.notification(32576)
	kodi_utils.container_refresh()

def get_mdbl_movie_id(item):
	if item['tmdb']: return item['tmdb']
	tmdb_id = None
	if item['imdb']:
		try:
			meta = movie_external_id('imdb_id', item['imdb'])
			tmdb_id = meta['id']
		except: pass
	return tmdb_id

def get_mdbl_tvshow_id(item):
	if item['tmdb']: return item['tmdb']
	tmdb_id = None
	if item['imdb']:
		try:
			meta = tvshow_external_id('imdb_id', item['imdb'])
			tmdb_id = meta['id']
		except: tmdb_id = None
	if not tmdb_id:
		if item['tvdb']:
			try:
				meta = tvshow_external_id('tvdb_id', item['tvdb'])
				tmdb_id = meta['id']
			except: tmdb_id = None
	return tmdb_id

def mdbl_watched_unwatched(action, media, media_id, tvdb_id=0, season=None, episode=None, key='tmdb'):
	if action == 'mark_as_watched': url, result_key = 'sync/watched', 'updated'
	else: url, result_key = 'sync/watched/remove', 'removed'
	try: media_id = int(media_id)
	except: pass
	if media == 'movies':
		success_key = 'movies'
		data = {'movies': [{'ids': {key: media_id}}]}
	else:
		success_key = 'episodes'
		if media == 'episode':
			seasons = [{'number': int(season), 'episodes': [{'number': int(episode)}]}]
			data = {'shows': [{'ids': {key: media_id}, 'seasons': seasons}]}
		elif media == 'shows': data = {'shows': [{'ids': {key: media_id}}]}
		else: data = {'shows': [{'ids': {key: media_id}, 'seasons': [{'number': int(season)}]}]}#season
	result = call_mdblist(url, json=data, method='post')
	success = result[result_key][success_key] > 0
	if not success:
		if media != 'movies' and tvdb_id != 0:
			return mdbl_watched_unwatched(action, media, tvdb_id, 0, season, episode, 'tvdb')
	return success

def mdbl_progress(action, media, media_id, percent, season=None, episode=None, resume_id=None, refresh_mdb=False):
	if action == 'clear_progress':
		url = 'scrobble/clear'
		data = {'id': resume_id}
	else:
		url = 'scrobble/pause'
		try: media_id = int(media_id)
		except: pass
		if media in ('movie', 'movies'): data = {'movie': {'ids': {'tmdb': media_id}}, 'progress': float(percent)}
		else: data = {'show': {'ids': {'tmdb': media_id}, 'season': {'number': int(season), 'episode': {'number': int(episode)}}}, 'progress': float(percent)}
	call_mdblist(url, json=data, method='post')
	if refresh_mdb: mdbl_sync_activities()

def mdbl_indicators_movies(watched_info):
	def _process(item):
		tmdb_id = get_mdbl_movie_id(item['movie']['ids'])
		if not tmdb_id: return
		insert_append((
			'movie', str(tmdb_id), '', '', item['last_watched_at'], item['movie']['title']
		))
	insert_list = []
	insert_append = insert_list.append
	watched_items = [(i,) for i in watched_info['movies']] # TaskPool requires tuple
	if not watched_items: return
	for i in TaskPool().tasks(_process, watched_items, Thread): i.join()
#	threads = list(make_thread_list(_process, watched_items, Thread))
#	[i.join() for i in threads]
	mdbl_cache.MDBLCache().set_bulk_movie_watched(insert_list)

def mdbl_indicators_tv(watched_info):
	def _process(item):
		tmdb_id = get_mdbl_tvshow_id(item['episode']['show']['ids'])
		if not tmdb_id: return
		season, episode = item['episode']['season'], item['episode']['number']
		insert_append((
			'episode', str(tmdb_id), season, episode, item['last_watched_at'], item['episode']['show']['title']
		))
	insert_list = []
	insert_append = insert_list.append
	watched_items = [(i,) for i in watched_info['episodes']] # TaskPool requires tuple
	if not watched_items: return
	for i in TaskPool().tasks(_process, watched_items, Thread): i.join()
#	threads = list(make_thread_list(_process, watched_items, Thread))
#	[i.join() for i in threads]
	mdbl_cache.MDBLCache().set_bulk_tvshow_watched(insert_list)

def mdbl_progress_movies(progress_info):
	def _process(item):
		tmdb_id = get_mdbl_movie_id(item['movie']['ids'])
		if not tmdb_id: return
		season, episode = '', ''
		insert_append((
			'movie', str(tmdb_id), season, episode, str(round(float(item['progress']), 1)),
			0, item['paused_at'], item['id'], item['movie']['title']
		))
	insert_list = []
	insert_append = insert_list.append
	progress_items = [i for i in progress_info if i['type'] == 'movie' and float(i['progress']) > 1]
	if not progress_items: return
	threads = list(make_thread_list(_process, progress_items, Thread))
	[i.join() for i in threads]
	mdbl_cache.MDBLCache().set_bulk_movie_progress(insert_list)

def mdbl_progress_tv(progress_info):
	def _process(item):
		tmdb_id = get_mdbl_tvshow_id(item['show']['ids'])
		if not tmdb_id: return
		season, episode = item['episode']['season'], item['episode']['number']
		if season < 1: return
		insert_append((
			'episode', str(tmdb_id), season, episode, str(round(float(item['progress']), 1)),
			0, item['paused_at'], item['id'], item['show']['title']
		))
	insert_list = []
	insert_append = insert_list.append
	progress_items = [i for i in progress_info if i['type'] == 'episode' and float(i['progress']) > 1]
	if not progress_items: return
	threads = list(make_thread_list(_process, progress_items, Thread))
	[i.join() for i in threads]
	mdbl_cache.MDBLCache().set_bulk_tvshow_progress(insert_list)

def mdbl_get_activity():
	url = 'sync/last_activities'
	return call_mdblist(url)

def mdbl_playback_progress():
	url = 'sync/playback'
	return call_mdblist(url)

def mdbl_watched_progress():
	params = {'limit': 5000}
	watched = {'movies': [], 'episodes': []}
	try:
		for _ in range(MAX_LIST_ITEMS // params['limit']):
			result = call_mdblist('sync/watched', params=params)
			if result is None: break
			if 'movies' in result: watched['movies'] += result['movies']
			if 'episodes' in result: watched['episodes'] += result['episodes']
			if not result['pagination']['has_more']: break
			params['offset'] = result['pagination']['offset'] + result['pagination']['limit']
	finally: return watched

def mdbl_sync_activities_thread(*args, **kwargs):
	Thread(target=mdbl_sync_activities, args=args, kwargs=kwargs).start()

def mdbl_sync_activities(force_update=False):
	def _get_timestamp(date_time):
		return int(time.mktime(date_time.timetuple()))
	def _compare(latest, cached, res_format='%Y-%m-%dT%H:%M:%SZ'):
		if latest is None and cached is None: return False
		try: result = _get_timestamp(js2date(latest, res_format)) > _get_timestamp(js2date(cached, res_format))
		except: result = True
		return result
	if not get_setting('mdblist_user', ''): return 'no account'
	if force_update:
		check_databases()
		mdbl_cache.clear_all_mdbl_cache_data(refresh=False)
	latest = mdbl_get_activity()
	if latest is None:
		mdbl_cache.clear_all_mdbl_cache_data(refresh=False)
		return 'failed'
	cached = mdbl_cache.reset_activity(latest)
	refresh_movies_watched = _compare(latest['watched_at'], cached['watched_at'])
	refresh_episodes_watched = _compare(latest['episode_watched_at'], cached['episode_watched_at'])
	refresh_movies_paused = _compare(latest['paused_at'], cached['paused_at'])
	refresh_episodes_paused = _compare(latest['episode_paused_at'], cached['episode_paused_at'])
	success = 'not needed'
	if refresh_movies_watched or refresh_episodes_watched:
		success = 'success'
		watched_info = mdbl_watched_progress()
		if refresh_movies_watched: mdbl_indicators_movies(watched_info)
		if refresh_episodes_watched: mdbl_indicators_tv(watched_info)
	if refresh_movies_paused or refresh_episodes_paused:
		success = 'success'
		progress_info = mdbl_playback_progress()
		if refresh_movies_paused: mdbl_progress_movies(progress_info)
		if refresh_episodes_paused: mdbl_progress_tv(progress_info)
	if _compare(latest['watchlisted_at'], cached['watchlisted_at']):
		success = 'success'
		mdbl_cache.clear_mdbl_collection_watchlist_data('watchlist')
	if _compare(latest['collected_at'], cached['collected_at']):
		success = 'success'
		mdbl_cache.clear_mdbl_collection_watchlist_data('collection')
	if _compare(latest['dropped_at'], cached['dropped_at']):
		success = 'success'
		mdbl_cache.clear_mdbl_list_data('hidden_items_dropped')
	if _compare(latest['list_updated_at'], cached['list_updated_at']):
		success = 'success'
		for i in ('external', 'my_lists'): mdbl_cache.clear_mdbl_list_contents_data(i)
		for i in ('external', 'my_lists'): mdbl_cache.clear_mdbl_list_data(i)
	return success

