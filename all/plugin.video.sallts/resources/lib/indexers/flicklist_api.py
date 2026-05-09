import time
import requests
from threading import Thread
from caches import flicklist_cache
from modules import kodi_utils, settings
from modules.cache import check_databases
from modules.utils import make_thread_list, sort_for_article, jsondate_to_datetime, paginate_list, TaskPool

EXPIRES_1_HOURS, MAX_LIST_ITEMS = 1, 10_000
logger, js2date = kodi_utils.logger, jsondate_to_datetime
get_setting, set_setting = kodi_utils.get_setting, kodi_utils.set_setting
req_headers = {'User-Agent': 'SALTS/6.0', 'X-FlickList-Client-Id': 'salts_redux'}
base_url = 'https://flicklist.tv/api/%s'
timeout = 5.05
session = requests.Session()
retry = requests.adapters.Retry(total=None, status=1, status_forcelist=(429, 502, 503, 504))
session.mount('https://flicklist.tv', requests.adapters.HTTPAdapter(pool_maxsize=100, max_retries=retry))

def _media_type(mediatype):
	if mediatype in ('movie', 'movies'): return 'movie'
	return 'tv'

def call_flicklist(path, params=None, json=None, method=None):
	current_token = session.headers.get('Authorization') or 'Bearer %s' % get_setting('flicklist.token')
	session.headers.update({**req_headers, 'Authorization': current_token})
	try:
		response = session.request(method or 'get', base_url % path, params=params, json=json, timeout=timeout)
		if response.status_code in (401,) and flicklist_refresh() is True:
			response.request.headers['Authorization'] = 'Bearer %s' % get_setting('flicklist.token')
			response = session.send(response.request, timeout=timeout)
		result = response.json() if 'json' in response.headers.get('Content-Type', '') else response.text
		if not response.ok: response.raise_for_status()
		return result
	except requests.exceptions.RequestException as e:
		logger('flicklist error', str(e))

def flicklist_refresh():
	from datetime import datetime
	current_token = session.headers.get('Authorization') or 'Bearer %s' % get_setting('flicklist.token')
	headers = {**req_headers, 'Authorization': current_token}
	try:
		result = requests.post(base_url % 'auth/refresh', headers=headers, timeout=timeout).json()
		dt = datetime.strptime(result['expires_at'], '%Y-%m-%dT%H:%M:%S.%fZ')
		expires = str(int(dt.timestamp()))
		token = result['token']
		set_setting('flicklist.token', token)
		set_setting('flicklist.expires', expires)
		kodi_utils.sleep(500)
	except Exception as e: logger('flicklist_refresh error', str(e))
	else: return True
	return False

def flicklist_expires(func):
	def wrapper(*args, **kwargs):
		if get_setting('flicklist.token', ''):
			interval = settings.trakt_sync_interval()[1]
			expires = float(get_setting('flicklist.expires', '0'))
			refresh = ((-1 * time.time() // 1 * -1) + interval) >= expires
			if refresh and flicklist_refresh(): kodi_utils.sleep(1000)
		return func(*args, **kwargs)
	return wrapper

def flicklist_droplist(mediatype, page_no, letter):
	results = flicklist_get_hidden_items('dropped')
	return [{'tmdb_id': i} for i in results], 1

def flicklist_get_hidden_items(list_type):
	def _process(url):
		hidden_data = call_flicklist(url, params=params)
		return [i['tmdb_id'] for i in hidden_data if i.get('status') == 'dropped']
	params = {'status': 'dropped'}
	string = 'flicklist_list_contents_hidden_items_%s' % list_type
	url = 'user/watchlist'
	return flicklist_cache.cache_flicklist_object(_process, string, url)

def hide_unhide_flicklist_items(action, mediatype, media_id, list_type):
	if not action in ('hide', 'unhide'):
		try:
			hidden_data = set(map(str, flicklist_get_hidden_items('dropped')))
			action = 'unhide' if action in hidden_data else 'hide'
		except: return kodi_utils.notification(32574)
	params = {'tmdb': 'true', 'media_type': _media_type(mediatype)}
	if action == 'hide': url = 'up-next/%s/drop' % media_id
	else: url = 'up-next/%s/undrop' % media_id
	call_flicklist(url, params=params, method='post')
#	flicklist_sync_activities() # not in last-activities
	flicklist_cache.clear_flicklist_list_contents_data('hidden_items')
	kodi_utils.container_refresh()

def flicklist_watchlist(mediatype, page_no, letter):
	def _watchlist_items(url):
		params = {'per_page': 200}
		items = []
		try:
			for page in range(1, (MAX_LIST_ITEMS // params['per_page']) + 1):
				params['page'] = page
				result = call_flicklist(url, params=params)
				if result is None: break
				if 'items' in result: items += result['items']
				if len(items) >= result['total']: break
		except: pass
		return items
	string = 'flicklist_watchlist'
	url = 'user/watchlist'
	original_list = flicklist_cache.cache_flicklist_object(_watchlist_items, string, url)
	if mediatype == 'all': return original_list
	key = _media_type(mediatype)
	original_list = [i for i in original_list if i['media_type'] == key]
	sort_key = settings.lists_sort_order('watchlist')
	if   sort_key == 2: original_list.sort(key=lambda k: k['year'] or '', reverse=True)
	elif sort_key == 1: original_list.sort(key=lambda k: k['added_at'], reverse=True)
	else: original_list = sort_for_article(original_list, 'title', settings.ignore_articles())
	if settings.paginate():
		limit = settings.page_limit()
		final_list, total_pages = paginate_list(original_list, page_no, letter, limit)
	else: final_list, total_pages = original_list, 1
	return final_list, total_pages

def flicklist_favorites(mediatype, page_no, letter):
	def _favorites_items(url):
		items = []
		try:
			result = call_flicklist(url)
			if result: items += result
		except: pass
		return items
	string = 'flicklist_favorites'
	url = 'user/favorites'
	original_list = flicklist_cache.cache_flicklist_object(_favorites_items, string, url)
	if mediatype == 'all': return original_list
	key = _media_type(mediatype)
	original_list = [i for i in original_list if i['media_type'] == key]
	if settings.paginate():
		limit = settings.page_limit()
		final_list, total_pages = paginate_list(original_list, page_no, letter, limit)
	else: final_list, total_pages = original_list, 1
	return final_list, total_pages

def add_to_list(list_id, mediatype, media_id):
	data = {'tmdb_id': media_id, 'media_type': _media_type(mediatype)}
	result = call_flicklist('user/lists/%s/items' % list_id, json=data, method='post')
	if not result: return kodi_utils.notification(32574)
	kodi_utils.notification(32576)
	flicklist_sync_activities()
	return result

def remove_from_list(list_id, mediatype, media_id):
	params = {'tmdb': 'true', 'media_type': _media_type(mediatype)}
	url = 'user/lists/%s/items/%s' % (list_id, media_id)
	result = call_flicklist(url, params=params, method='delete')
	if result is None: return kodi_utils.notification(32574)
	kodi_utils.notification(32576)
	# 6.04.01 - force, some remove events do not update last-activities
	flicklist_sync_activities(force_update=True)
	kodi_utils.container_refresh()
	return result

def add_to_collection(list_type, mediatype, media_id):
	data = {'tmdb_id': media_id, 'media_type': _media_type(mediatype)}
	if list_type == 'watchlist': data['status'] = 'plan_to_watch'
	result = call_flicklist('user/%s' % list_type, json=data, method='post')
	if result is None: return kodi_utils.notification(32574)
	kodi_utils.notification(32576)
	flicklist_sync_activities()
	return result

def remove_from_collection(list_type, mediatype, media_id):
	params = {'tmdb': 'true', 'media_type': _media_type(mediatype)}
	url = 'user/%s/%s' % (list_type, media_id)
	result = call_flicklist(url, params=params, method='delete')
	if result is None: return kodi_utils.notification(32574)
	kodi_utils.notification(32576)
	# 6.04.01 - force, some remove events do not update last-activities
	flicklist_sync_activities(force_update=True) 
	kodi_utils.container_refresh()
	return result

def get_flicklist_list_contents(list_id):
	string = 'flicklist_list_contents_%s_%s' % ('my_lists', list_id)
	url = 'user/lists/%s/items' % list_id
	return flicklist_cache.cache_flicklist_object(call_flicklist, string, url)

def flicklist_get_lists(list_type):
	string = 'flicklist_my_lists'
	url = 'user/lists'
	return flicklist_cache.cache_flicklist_object(call_flicklist, string, url)

def make_new_flicklist_list(params):
	from urllib.parse import unquote
	list_title = kodi_utils.dialog.input('POV')
	if not list_title: return
	list_name = unquote(list_title)
	data = {'name': list_name, 'private': 'public'}
	result = call_flicklist('user/lists', json=data, method='post')
	if result is None: return kodi_utils.notification(32574)
	flicklist_cache.clear_flicklist_list_data('my_lists')
	kodi_utils.notification(32576)
	kodi_utils.container_refresh()

def delete_flicklist_list(params):
	if not kodi_utils.confirm_dialog(): return
	list_id = params['list_id']
	url = 'user/lists/%s' % list_id
	result = call_flicklist(url, method='delete')
	if result is None: return kodi_utils.notification(32574)
	flicklist_cache.clear_flicklist_list_data('my_lists')
	kodi_utils.notification(32576)
	kodi_utils.container_refresh()

def _watched_api_call(action, media, media_type, tmdb_id, season, episode):
	""" thanks https://github.com/maccb """
	if action == 'mark_as_watched':
		if media == 'episode':
			data = {'tmdb_id': tmdb_id, 'media_type': media_type}
			if season is not None: data['season_number'] = int(season)
			if episode is not None: data['episode_number'] = int(episode)
			return call_flicklist('watched', json=data, method='post')
		elif media == 'shows':
			data = {'tmdb_id': tmdb_id, 'media_type': media_type, 'scope': 'show'}
			return call_flicklist('watched/batch', json=data, method='post')
		elif media == 'season':
			data = {'tmdb_id': tmdb_id, 'media_type': media_type, 'scope': 'season', 'season_number': int(season)}
			return call_flicklist('watched/batch', json=data, method='post')
		else:
			return call_flicklist('watched', json={'tmdb_id': tmdb_id, 'media_type': media_type}, method='post')
	else:
		if media == 'episode':
			delete_data = {'tmdb_id': tmdb_id, 'media_type': media_type, 'scope': 'episode'}
			if season is not None: delete_data['season_number'] = int(season)
			if episode is not None: delete_data['episode_number'] = int(episode)
			return call_flicklist('watched/batch', json=delete_data, method='delete')
		elif media == 'shows':
			check = call_flicklist('watched/check', params={'tmdb_id': tmdb_id, 'media_type': media_type})
			if check and isinstance(check, dict):
				for sn in check.get('season_progress', {}):
					data = {'tmdb_id': tmdb_id, 'media_type': media_type, 'season_number': int(sn)}
					call_flicklist('watched/batch', json=data, method='delete')
			return True
		elif media == 'season':
			data = {'tmdb_id': tmdb_id, 'media_type': media_type, 'season_number': int(season)}
			return call_flicklist('watched/batch', json=data, method='delete')
		else:
			call_flicklist('watched/%s' % tmdb_id, params={'tmdb': 'true', 'media_type': media_type}, method='delete')
			return True

def flicklist_watched_unwatched(action, media, media_id, tvdb_id=0, season=None, episode=None, key='tmdb'):
	media_type = 'movie' if media in ('movie', 'movies') else 'tv'
	try:
		tmdb_id = int(media_id)
		result = _watched_api_call(action, media, media_type, tmdb_id, season, episode)
		return result is not None
	except: return False

def flicklist_progress(action, media, media_id, percent, season=None, episode=None, resume_id=None, refresh_flicklist=False):
	if action == 'clear_progress':
		call_flicklist('sync/playback/%s' % resume_id, method='delete')
	else:
		media_type = 'movie' if media in ('movie', 'movies') else 'episode'
		data = {'event': 'pause', 'tmdb_id': int(media_id), 'media_type': media_type, 'progress': float(percent)}
		if season not in (None, ''): data['season'] = int(season)
		if episode not in (None, ''): data['episode'] = int(episode)
		call_flicklist('scrobble/event', json=data, method='post')
	if refresh_flicklist: flicklist_sync_activities()

def flicklist_indicators_movies():
	def _process(item):
		tmdb_id = item.get('tmdb_id')
		if not tmdb_id: return
		insert_append((
			'movie', str(tmdb_id), '', '', item['watched_at'], item['title']
		))
	insert_list = []
	insert_append = insert_list.append
	watched_info = flicklist_watched_progress('movie')
	for i in watched_info: _process(i) # FlickList object does not include imdb, threading not needed
	if not insert_list: return
	flicklist_cache.FlickListCache().set_bulk_movie_watched(insert_list)

def flicklist_indicators_tv():
	def _process(item):
		tmdb_id = item.get('tmdb_id')
		if not tmdb_id: return
		season, episode = item['season_number'], item['episode_number']
		insert_append((
			'episode', str(tmdb_id), season, episode, item['watched_at'], item['title']
		))
	insert_list = []
	insert_append = insert_list.append
	watched_info = flicklist_watched_progress('tv')
	for i in watched_info: _process(i) # FlickList object does not include imdb, threading not needed
	if not insert_list: return
	flicklist_cache.FlickListCache().set_bulk_tvshow_watched(insert_list)

def flicklist_progress_movies(progress_info):
	def _process(item):
		tmdb_id = item.get('tmdb_id')
		if not tmdb_id: return
		season, episode = '', ''
		insert_append((
			'movie', str(tmdb_id), season, episode, str(round(float(item['progress']), 1)),
			0, item['updated_at'], item['id'], item['title']
		))
	insert_list = []
	insert_append = insert_list.append
	for i in progress_info: # FlickList object does not include imdb, threading not needed
		if i['media_type'] == 'movie' and float(i['progress']) > 1: _process(i)
	if not insert_list: return
	flicklist_cache.FlickListCache().set_bulk_movie_progress(insert_list)

def flicklist_progress_tv(progress_info):
	def _process(item):
		tmdb_id = item.get('tmdb_id')
		if not tmdb_id: return
		season, episode = item['season_number'], item['episode_number']
		if season < 1: return
		insert_append((
			'episode', str(tmdb_id), season, episode, str(round(float(item['progress']), 1)),
			0, item['updated_at'], item['id'], item['title']
		))
	insert_list = []
	insert_append = insert_list.append
	for i in progress_info: # FlickList object does not include imdb, threading not needed
		if i['media_type'] == 'episode' and float(i['progress']) > 1: _process(i)
	if not insert_list: return
	flicklist_cache.FlickListCache().set_bulk_tvshow_progress(insert_list)

def flicklist_get_activity():
	url = 'sync/last-activities'
	return call_flicklist(url)

def flicklist_playback_progress():
	url = 'sync/playback'
	return call_flicklist(url)

def flicklist_watched_progress(mediatype):
	params = {'watch_status': 'watched', 'media_type': _media_type(mediatype), 'per_page': 500}
	watched = []
	try:
		for page in range(1, (MAX_LIST_ITEMS // params['per_page']) + 1):
			params['page'] = page
			result = call_flicklist('scrobble/history', params=params)
			if result is None: break
			if 'results' in result: watched += result['results']
			if result['page'] >= result['total_pages']: break
	except: pass
	return watched

def flicklist_sync_activities_thread(*args, **kwargs):
	Thread(target=flicklist_sync_activities, args=args, kwargs=kwargs).start()

@flicklist_expires
def flicklist_sync_activities(force_update=False):
	def _get_timestamp(date_time):
		return int(time.mktime(date_time.timetuple()))
	def _compare(latest, cached, res_format='%Y-%m-%dT%H:%M:%S.%fZ'):
		if latest is None and cached is None: return False
		try: result = _get_timestamp(js2date(latest, res_format)) != _get_timestamp(js2date(cached, res_format))
		except: result = True
		return result
	if not get_setting('flicklist_user', ''): return 'no account'
	if force_update:
		check_databases()
		flicklist_cache.clear_all_flicklist_cache_data(refresh=False)
	latest = flicklist_get_activity()
	if latest is None:
		flicklist_cache.clear_all_flicklist_cache_data(refresh=False)
		return 'failed'
	cached = flicklist_cache.reset_activity(latest)
	if not _compare(latest['all'], cached['all']):
		flicklist_cache.clear_flicklist_list_contents_data('hidden_items')
		return 'not needed'
	if _compare(latest['lists']['updated_at'], cached['lists']['updated_at']):
		flicklist_cache.clear_flicklist_list_contents_data('my_lists')
		flicklist_cache.clear_flicklist_list_data('my_lists')
	if _compare(latest['favorites'], cached['favorites']):
		flicklist_cache.clear_flicklist_collection_watchlist_data('favorites')
	if _compare(latest['movies']['watchlisted_at'], cached['movies']['watchlisted_at']):
		flicklist_cache.clear_flicklist_collection_watchlist_data('watchlist')
	elif _compare(latest['shows']['watchlisted_at'], cached['shows']['watchlisted_at']):
		flicklist_cache.clear_flicklist_collection_watchlist_data('watchlist')
	if _compare(latest['movies']['watched_at'], cached['movies']['watched_at']): flicklist_indicators_movies()
	if _compare(latest['episodes']['watched_at'], cached['episodes']['watched_at']): flicklist_indicators_tv()
	refresh_movies_paused = _compare(latest['movies']['paused_at'], cached['movies']['paused_at'])
	refresh_episodes_paused = _compare(latest['episodes']['paused_at'], cached['episodes']['paused_at'])
	if refresh_movies_paused or refresh_episodes_paused:
		progress_info = flicklist_playback_progress()
		if refresh_movies_paused: flicklist_progress_movies(progress_info)
		if refresh_episodes_paused: flicklist_progress_tv(progress_info)
	return 'success'

