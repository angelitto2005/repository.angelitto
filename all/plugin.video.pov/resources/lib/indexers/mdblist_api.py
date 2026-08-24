import requests
from threading import Thread
from concurrent.futures import ThreadPoolExecutor
from caches import mdbl_cache
from caches.main_cache import cache_object
from indexers.tmdb_api import movie_external_id, tvshow_external_id
from magneto.modules import client
from modules import kodi_utils, settings
from modules.cache import check_databases
from modules.utils import sort_for_article, jsondate_to_datetime, paginate_list, get_datetime

EXPIRES_1_HOURS, EXPIRES_2_DAYS, MAX_LIST_ITEMS = 1, 48, 250_000
get_setting, set_setting, logger = kodi_utils.get_setting, kodi_utils.set_setting, kodi_utils.logger
base_url = 'https://api.mdblist.com/%s'
timeout = 10.05
session = requests.Session()
retry = requests.adapters.Retry(total=None, status=1, status_forcelist=(502, 503, 504))
session.mount('https://api.mdblist.com', requests.adapters.HTTPAdapter(pool_maxsize=100, max_retries=retry))

def call_mdblist(path, params=None, json=None, method=None):
	headers = None
	params = params or {}
	if not bool(get_setting('mdblist.refresh')): params['apikey'] = get_setting('mdblist.token')
	else: headers = {'Authorization': 'Bearer %s' % get_setting('mdblist.token')}
	try:
		response = session.request(
			method or 'get',
			base_url % path,
			params=params,
			json=json,
			headers=headers,
			timeout=timeout
		)
		result = response.json() if 'json' in response.headers.get('Content-Type', '') else response.text
		if not response.ok: response.raise_for_status()
		if isinstance(result, list):
			result = {'items': result, 'pagination': {'has_more': response.headers.get('X-Has-More') == 'true'}}
			if (next := response.headers.get('X-Next-Cursor')): result['pagination']['next_cursor'] = next
		return result
	except requests.RequestException as e:
		logger('mdblist error', str(e))

def _get_mdbl_paginated_list(url):
	params = {'limit': 1000}
	items = {'movies': [], 'shows': [], 'episodes': [], 'items': []}
	try:
		for _ in range(MAX_LIST_ITEMS // params['limit']):
			result = call_mdblist(url, params=params)
			if not isinstance(result, dict): break
			for k in items:
				if k in result and isinstance(result[k], list):
					items[k].extend(result[k])
			if not result['pagination']['has_more']: break
			params['cursor'] = result['pagination']['next_cursor']
	except: pass
	return items

def mdbl_refresh():
	try:
		created_at = __import__('time').time()
		data = {'grant_type': 'refresh_token'}
		data['refresh_token'] = get_setting('mdblist.refresh')
		data['client_id'] = get_setting('mdblist.client_id')
		response = requests.post(base_url % 'oauth/token/', data=data, timeout=timeout).json()
		expires = int(created_at) + int(response['expires_in'])
		refresh, token = response['refresh_token'], response['access_token']
		set_setting('mdblist.token', token)
		set_setting('mdblist.refresh', refresh)
		set_setting('mdblist.expires', str(expires))
		kodi_utils.sleep(500)
	except Exception as e: logger('mdbl_refresh error', str(e))

def mdbl_expires():
	if not get_setting('mdblist.refresh', ''): return
	from datetime import datetime, timezone
	interval = settings.trakt_sync_interval()[1]
	current = int(datetime.now(timezone.utc).timestamp())
	expires = int(get_setting('mdblist.expires', '0'))
	if interval + current >= expires: mdbl_refresh()

def mdbl_calendar_days(recently_aired, current_date):
	from datetime import timedelta
	if recently_aired: return (current_date - timedelta(days=7)).strftime('%Y-%m-%d'), '7'
	previous_days = int(get_setting('trakt.calendar_previous_days', '3'))
	future_days = int(get_setting('trakt.calendar_future_days', '7'))
	start = (current_date - timedelta(days=previous_days)).strftime('%Y-%m-%d')
	finish = (current_date + timedelta(days=future_days)).strftime('%Y-%m-%d')
	return start, finish

def mdbl_ratings_info(mediatype, imdb_id):
	mediatype = 'movie' if mediatype == 'movie' else 'show'
	string = 'mdbl_ratings_%s_%s' % (mediatype, imdb_id)
	url = '%s/%s/%s' % ('https://mdblist.com', mediatype, imdb_id)
	return cache_object(mdbl_ratings_info_handler, string, url, expiration=EXPIRES_2_DAYS)

def mdbl_ratings_info_handler(url):
	html = client.request(url, timeout=6.05)
	labels = client.parseDOM(html, 'span', {'class': ['mdblist-label', 'movie-rating-name']})
	scores = client.parseDOM(html, 'span', {'class': ['mdblist-rating', 'movie-rating-score']})
	sources = ('imdb', 'metacritic', 'mdblist', 'tomatoes', 'trakt', 'tmdb')
	data = []
	for k, v in zip(labels, scores):
		try:
			k, v = k.split()[0].strip().lower(), v.strip()
			if k not in sources: continue
			data.append({'source': k, 'value': v})
		except: pass
	return data

def mdbl_top_lists():
	string = 'mdbl_top_lists'
	url = 'lists/top'
	return cache_object(call_mdblist, string, url)['items']

def mdbl_search_lists(query):
	query = requests.utils.quote(query)
	string = 'mdbl_search_lists_%s' % query
	url = 'lists/search?query=%s' % query
	return cache_object(call_mdblist, string, url, expiration=EXPIRES_1_HOURS)['items']

def mdblist_droplist(mediatype, page_no):
	def _process(url):
		response = _get_mdbl_paginated_list(url)
		hidden_data = response.get('shows', []) if response else []
		if not hidden_data: return []
		results = []
		for item in hidden_data:
			show_ids = item['show']['ids']
			tmdb_id = show_ids.get('tmdb')
			if tmdb_id: results.append({
				'id': tmdb_id,
				'title': item['show']['title']
			})
		return results
	string = 'mdbl_hidden_items_dropped'
	url = 'sync/dropped'
	data = mdbl_cache.cache_mdbl_object(_process, string, url)
	if page_no == 'all': return data
	original_list = sort_for_article(data, 'title', settings.ignore_articles())
	return original_list, 1

def mdbl_calendar_data(url):
	result = []
	seen = set()
	for i in call_mdblist(url)['events'] or []:
		try:
			if i['type'] != 'episode' or i['season_number'] <= 0: continue
			tmdb_id = i.get('show_tmdb') or i.get('show_id') or ''
			season, episode = i['season_number'], i['episode_number']
			sort_title = '%s s%02d e%02d' % (i['title'], season, episode)
			if sort_title not in seen and not seen.add(sort_title): result.append({
				'sort_title': sort_title, 'first_aired': i['start'],
				'media_ids': {'tmdb': tmdb_id}, 'season': season, 'episode': episode
			})
		except: pass
	return result

def mdbl_get_my_calendar(recently_aired, current_date):
	start, finish = mdbl_calendar_days(recently_aired, current_date)
	string = 'mdbl_get_my_calendar_%s_%s' % (start, finish)
	url = 'calendar/events?limit=1000&start=%s&end=%s' % (start, finish)
	return mdbl_cache.cache_mdbl_object(lambda u: mdbl_calendar_data(u), string, url)

def mdblist_collection(mediatype, page_no):
	string = 'mdbl_collection'
	url = 'sync/collection'
	original_list = mdbl_collection_watchlist_items(string, url)
	if mediatype == 'all':
		original_list = original_list['movies'] + original_list['shows']
		for i in original_list: i.update({'id': i['movie' if 'movie' in i else 'show']['ids']['tmdb']})
		return original_list
	def _year(item):
		if isinstance(item.get('year'), int): return str(item['year'])
		return item.get('year')
	key = 'movie' if mediatype in ('movie', 'movies') else 'show'
	original_list = [
		{'collected_at': i['collected_at'],
		 'id': i[key]['ids']['tmdb'],
		 'imdb_id': i[key]['ids']['imdb'],
		 'title': i[key]['title'],
		 'year': _year(i[key])}
		for i in original_list[mediatype]
	] # only endpoint with nested media. no response to feature req to flatten.
	sort_key = settings.lists_sort_order('collection')
	if   sort_key == 2: original_list.sort(key=lambda k: k.get('year') or '', reverse=True)
	elif sort_key == 1: original_list.sort(key=lambda k: k['collected_at'], reverse=True)
	else: original_list = sort_for_article(original_list, 'title', settings.ignore_articles())
	if settings.paginate(): return paginate_list(original_list, page_no, settings.page_limit())
	return original_list, 1

def mdblist_watchlist(mediatype, page_no):
	def first_aired(item):
		if not item.get('release_date'): return False
		return jsondate_to_datetime(item['release_date']).astimezone().date() <= current_date
	string = 'mdbl_watchlist'
	url = 'watchlist/items'
	original_list = mdbl_collection_watchlist_items(string, url)
	if mediatype == 'all':
		original_list = original_list['movies'] + original_list['shows']
		return original_list
	original_list = original_list[mediatype]
	if not settings.show_unaired_watchlist():
		current_date = get_datetime()
		original_list = [i for i in original_list if first_aired(i)]
	sort_key = settings.lists_sort_order('watchlist', mediatype)
	if   sort_key == 2: original_list.sort(key=lambda k: k.get('release_date') or '', reverse=True)
	elif sort_key == 1: original_list.sort(key=lambda k: k['watchlist_at'], reverse=True)
	else: original_list = sort_for_article(original_list, 'title', settings.ignore_articles())
	if settings.paginate(): return paginate_list(original_list, page_no, settings.page_limit())
	return original_list, 1

def mdbl_collection_watchlist_items(string, url):
	return mdbl_cache.cache_mdbl_object(_get_mdbl_paginated_list, string, url)

def get_mdbl_list_contents(list_type, list_id):
	string = 'mdbl_list_contents_%s_%s' % (list_type, list_id)
	if list_type == 'external': url = 'external/lists/%s/items?unified=true' % list_id
	else: url = 'lists/%s/items?unified=true' % list_id
	return mdbl_cache.cache_mdbl_object(_get_mdbl_paginated_list, string, url)['items']

def mdbl_get_lists(list_type):
	if list_type == 'liked_lists': key, string, url = 'lists', 'mdbl_liked_lists', 'lists/liked'
	elif list_type == 'external': key, string, url = 'items', 'mdbl_external', 'external/lists/user'
	else: key, string, url = 'items', 'mdbl_my_lists', 'lists/user'
	return mdbl_cache.cache_mdbl_object(call_mdblist, string, url)[key]

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

def make_new_mdbl_list(params):
	from urllib.parse import unquote
	list_title = kodi_utils.dialog.input('POV')
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

def mdbl_progress(action, media, media_id, percent, season=None, episode=None, resume_id=None, refresh=False):
	if action == 'clear_progress':
		data = {'id': resume_id}
		url = 'scrobble/clear'
	else:
		try: media_id = int(media_id)
		except: pass
		if media in ('movie', 'movies'): data = {'movie': {'ids': {'tmdb': media_id}}, 'progress': float(percent)}
		else: data = {'show': {'ids': {'tmdb': media_id}, 'season': {'number': int(season), 'episode': {'number': int(episode)}}}, 'progress': float(percent)}
		url = 'scrobble/pause'
	call_mdblist(url, json=data, method='post')
	if refresh: mdbl_sync_activities()

def hide_unhide_mdbl_items(action, mediatype, media_id, list_type):
	if action not in ('hide', 'unhide'):
		try:
			hidden_data = mdbl_get_hidden_items('dropped')
			action = 'unhide' if int(action) in hidden_data else 'hide'
		except: return kodi_utils.notification(32574)
	mediatype = 'movies' if mediatype in ('movie', 'movies') else 'shows'
	key = 'tmdb' if mediatype == 'movies' else 'imdb'
	url = 'sync/dropped' if action == 'hide' else 'sync/dropped/remove'
	data = {mediatype: [{'ids': {key: media_id}}]}
	call_mdblist(url, json=data, method='post')
	mdbl_sync_activities()
	kodi_utils.container_refresh()

def mdbl_get_hidden_items(list_type):
	results = mdblist_droplist('shows', 'all')
	return [i['id'] for i in results]

def get_mdbl_movie_id(item):
	if item.get('tmdb'): return item['tmdb']
	for k, v in (('imdb_id', 'imdb'),):
		try: return movie_external_id(k, item[v])['id']
		except: pass

def get_mdbl_tvshow_id(item):
	if item.get('tmdb'): return item['tmdb']
	for k, v in (('imdb_id', 'imdb'), ('tvdb_id', 'tvdb')):
		try: return tvshow_external_id(k, item[v])['id']
		except: pass

def mdbl_indicators_movies(watched_info):
	items = watched_info['movies']
	if not items: return mdbl_cache.MDBLCache().set_bulk_movie_watched([])
	def _build_movie_row(item, tmdb_id):
		movie = item['movie']
		return ('movie', str(tmdb_id), '', '', item['last_watched_at'], movie['title'])
	insert_list, lookup_list = [], []
	for item in items:
		tmdb_id = item['movie']['ids'].get('tmdb')
		if tmdb_id: insert_list.append(_build_movie_row(item, tmdb_id))
		else: lookup_list.append(item)
	if lookup_list:
		def _process_lookup(item):
			tmdb_id = get_mdbl_movie_id(item['movie']['ids'])
			return _build_movie_row(item, tmdb_id) if tmdb_id else None
		with ThreadPoolExecutor() as executor: results = executor.map(_process_lookup, lookup_list)
		insert_list.extend([i for i in results if i is not None])
	mdbl_cache.MDBLCache().set_bulk_movie_watched(insert_list)

def mdbl_indicators_tv(watched_info):
	items = watched_info['episodes']
	if not items: return mdbl_cache.MDBLCache().set_bulk_tvshow_watched([])
	def _build_episode_row(item, tmdb_id):
		episode_data = item['episode']
		show_data = episode_data['show']
		season, episode = episode_data['season'], episode_data['number']
		return ('episode', str(tmdb_id), season, episode, item['last_watched_at'], show_data['title'])
	insert_list, lookup_list = [], []
	for item in items:
		tmdb_id = item['episode']['show']['ids'].get('tmdb')
		if tmdb_id: insert_list.append(_build_episode_row(item, tmdb_id))
		else: lookup_list.append(item)
	if lookup_list:
		def _process_lookup(item):
			tmdb_id = get_mdbl_tvshow_id(item['episode']['show']['ids'])
			return _build_episode_row(item, tmdb_id) if tmdb_id else None
		with ThreadPoolExecutor() as executor: results = executor.map(_process_lookup, lookup_list)
		insert_list.extend([i for i in results if i is not None])
	mdbl_cache.MDBLCache().set_bulk_tvshow_watched(insert_list)

def mdbl_progress_movies(progress_info):
	def _build_progress_row(item, tmdb_id):
		movie = item['movie']
		p_str = str(round(float(item['progress']), 1))
		return ('movie', str(tmdb_id), '', '', p_str, 0, item['paused_at'], item['id'], movie['title'])
	insert_list, lookup_list = [], []
	for item in progress_info:
		if item['type'] != 'movie' or float(item['progress']) <= 1: continue
		tmdb_id = item['movie']['ids'].get('tmdb')
		if tmdb_id: insert_list.append(_build_progress_row(item, tmdb_id))
		else: lookup_list.append(item)
	if lookup_list:
		def _process_lookup(item):
			tmdb_id = get_mdbl_movie_id(item['movie']['ids'])
			return _build_progress_row(item, tmdb_id) if tmdb_id else None
		with ThreadPoolExecutor() as executor: results = executor.map(_process_lookup, lookup_list)
		insert_list.extend([i for i in results if i is not None])
	mdbl_cache.MDBLCache().set_bulk_movie_progress(insert_list)

def mdbl_progress_tv(progress_info):
	id_lookup_map, lookup_list = {}, {}
	progress_items, insert_list = [], []
	for item in progress_info:
		if item['type'] != 'episode' or float(item['progress']) <= 1: continue
		progress_items.append(item)
		show, slug = item['show'], item['show']['ids']['mdblist']
		if slug in id_lookup_map: continue
		tmdb_id = show['ids'].get('tmdb')
		if tmdb_id: id_lookup_map[slug] = tmdb_id
		else: lookup_list[slug] = show
	if lookup_list:
		def _process_lookup(show):
			tmdb_id = get_mdbl_tvshow_id(show['ids'])
			return (show['ids']['mdblist'], tmdb_id) if tmdb_id else None
		with ThreadPoolExecutor() as executor: results = executor.map(_process_lookup, lookup_list.values())
		for res in results:
			if not res: continue
			slug, tmdb_id = res
			id_lookup_map[slug] = tmdb_id
	for item in progress_items:
		show = item['show']
		tmdb_id = id_lookup_map.get(show['ids']['mdblist'])
		if not tmdb_id: continue
		season, episode = item['episode']['season'], item['episode']['number']
		if season < 1: continue
		p_str = str(round(float(item['progress']), 1))
		insert_list.append(('episode', str(tmdb_id), season, episode, p_str, 0, item['paused_at'], item['id'], show['title']))
	mdbl_cache.MDBLCache().set_bulk_tvshow_progress(insert_list)

def mdbl_playback_progress():
	url = 'sync/playback'
	return call_mdblist(url)

def mdbl_get_activity():
	url = 'sync/last_activities'
	return call_mdblist(url)

def mdbl_sync_activities_thread(*args, **kwargs):
	Thread(target=mdbl_sync_activities, args=args, kwargs=kwargs).start()

def mdbl_sync_activities(force_update=False, init_callback=None, monitor=None):
	def _compare(latest, cached):
		try: return (latest or '') > (cached or '')
		except: return True
	if not get_setting('mdblist_user', ''): return 'no account'
	if monitor and monitor.abortRequested(): return
	if callable(init_callback): init_callback()
	elif init_callback is True: mdbl_expires()
	else: pass
	if force_update:
		check_databases()
		mdbl_cache.clear_all_mdbl_cache_data(refresh=False)
	mdbl_cache.clear_mdbl_calendar()
	latest = mdbl_get_activity()
	if not isinstance(latest, dict):
		logger('mdblist error', str(latest))
		mdbl_cache.clear_all_mdbl_cache_data(refresh=False)
		return 'failed'
	cached = mdbl_cache.reset_activity(latest)
	success = 'not needed'
	# format: (timestamp_key, callback_args, callback_func)
	for key, args, func in (
		('collected_at',   ('collection',),           mdbl_cache.clear_mdbl_collection_watchlist_data),
		('watchlisted_at', ('watchlist',),            mdbl_cache.clear_mdbl_collection_watchlist_data),
		('dropped_at',     ('hidden_items_dropped',), mdbl_cache.clear_mdbl_list_data)
	):
		if _compare(latest[key], cached[key]):
			success = 'success'
			func(*args)
	if _compare(latest['list_updated_at'], cached['list_updated_at']):
		success = 'success'
		for i in ('external', 'liked_lists', 'my_lists'):
			mdbl_cache.clear_mdbl_list_data(i)
			mdbl_cache.clear_mdbl_list_contents_data(i)
	refresh_movies_watched = _compare(latest['watched_at'], cached['watched_at'])
	refresh_episodes_watched = _compare(latest['episode_watched_at'], cached['episode_watched_at'])
	if refresh_movies_watched or refresh_episodes_watched:
		success = 'success'
		watched_info = _get_mdbl_paginated_list('sync/watched')
		if refresh_movies_watched: mdbl_indicators_movies(watched_info)
		if refresh_episodes_watched: mdbl_indicators_tv(watched_info)
	refresh_movies_progress = _compare(latest['paused_at'], cached['paused_at'])
	refresh_episodes_progress = _compare(latest['episode_paused_at'], cached['episode_paused_at'])
	if refresh_movies_progress or refresh_episodes_progress:
		success = 'success'
		progress_info = mdbl_playback_progress()['items']
		if refresh_movies_progress: mdbl_progress_movies(progress_info)
		if refresh_episodes_progress: mdbl_progress_tv(progress_info)
	return success

