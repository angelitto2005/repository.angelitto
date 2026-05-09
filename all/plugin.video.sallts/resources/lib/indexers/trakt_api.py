import json
import time
import requests
from threading import Thread
from caches import trakt_cache
from caches.main_cache import cache_object
from indexers.metadata import movie_external_id, tvshow_external_id
from modules import kodi_utils, settings
from modules.cache import check_databases
from modules.utils import sort_list, sort_for_article, make_thread_list, jsondate_to_datetime, paginate_list, get_datetime, TaskPool

ls, logger, js2date = kodi_utils.local_string, kodi_utils.logger, jsondate_to_datetime
get_setting, set_setting = kodi_utils.get_setting, kodi_utils.set_setting
EXPIRES_2_DAYS = 48
V2_API_KEY = get_setting('trakt.client_id')
CLIENT_SECRET = get_setting('trakt.client_secret')
REDIRECT_URI = 'urn:ietf:wg:oauth:2.0:oob'
base_url = 'https://api.trakt.tv/%s'
timeout = 10.05
session = requests.Session()
retry = requests.adapters.Retry(total=None, status=1, status_forcelist=(429, 502, 503, 504))
session.mount('https://api.trakt.tv', requests.adapters.HTTPAdapter(pool_maxsize=100, max_retries=retry))

def call_trakt(path, params=None, data=None, with_auth=True, method=None, pagination=False, page=1):
	headers = {
		'User-Agent': session.headers['User-Agent'], 'Content-Type': 'application/json',
		'trakt-api-key': V2_API_KEY, 'trakt-api-version': '2'
	}
	if with_auth is True and (token := settings.trakt_token()): headers['Authorization'] = 'Bearer %s' % token
	if pagination: params['page'] = page
	try:
		response = session.request(
			'post' if data is not None else method or 'get',
			base_url % path,
			params=None if data is not None else params,
			data=json.dumps(data) if data else None,
			headers=headers,
			timeout=timeout
		)
		result = response.json() if 'json' in response.headers.get('Content-Type', '') else response.text
		if not response.ok: response.raise_for_status()
		if 'X-Sort-By' in response.headers and 'X-Sort-How' in response.headers:
			sort_by, sort_how = response.headers['X-Sort-By'], response.headers['X-Sort-How']
#			result = sort_list(sort_by, sort_how, result, settings.ignore_articles())
			if isinstance(result, list) and sort_by in ('added', 'released') and sort_how in ('asc',):
				if get_setting('trakt.reverse') == 'true': result.reverse()
		if pagination: result = result, response.headers.get('X-Pagination-Page-Count', page)
		return result
	except requests.exceptions.RequestException as e:
		logger('trakt error', str(e))

def get_trakt(params):
	result = call_trakt(
		params['path'] % params.get('path_insert', ''),
		params=params.get('params', {}),
		data=params.get('data'),
		with_auth=params.get('with_auth', False),
		method=params.get('method'),
		pagination=params.get('pagination', True),
		page=params.get('page')
	)
	return result[0] if params.get('pagination', True) else result

def trakt_refresh():
	try:
		data = {'client_id': V2_API_KEY, 'client_secret': CLIENT_SECRET, 'redirect_uri': REDIRECT_URI}
		data.update({'refresh_token': get_setting('trakt.refresh'), 'grant_type': 'refresh_token'})
		response = call_trakt('oauth/token', data=data, with_auth=False)
		expires = int(response['created_at']) + int(response['expires_in'])
		refresh, token = response['refresh_token'], response['access_token']
		set_setting('trakt.token', token)
		set_setting('trakt.refresh', refresh)
		set_setting('trakt.expires', str(expires))
	except Exception as e: logger('trakt_refresh error', str(e))
	else: return True
	return False

def trakt_expires(func):
	def wrapper(*args, **kwargs):
		if get_setting('trakt.refresh', ''):
			interval = settings.trakt_sync_interval()[1]
			expires = float(get_setting('trakt.expires', '0'))
			refresh = ((-1 * time.time() // 1 * -1) + interval) >= expires
			if refresh and trakt_refresh(): kodi_utils.sleep(1000)
		return func(*args, **kwargs)
	return wrapper

def id_lookup(media_id, key='tmdb'):
	return call_trakt('search/%s/%s' % (key, media_id))

def trakt_recommendations(mediatype):
	string = 'trakt_recommendations_%s' % mediatype
	url = {'path': '/recommendations/%s', 'path_insert': mediatype, 'params': {'limit': 50}, 'with_auth': True, 'pagination': False}
	return trakt_cache.cache_trakt_object(get_trakt, string, url)

def trakt_movies_trending(page_no):
	string = 'trakt_movies_trending_%s' % page_no
	url = {'path': 'movies/trending/%s', 'params': {'limit': 20}, 'page': page_no}
	return cache_object(get_trakt, string, url, json=False, expiration=EXPIRES_2_DAYS)

def trakt_movies_trending_recent(page_no):
	year = get_datetime().year
	years = '%s-%s' % (year-1, year)
	string = 'trakt_movies_trending_recent_%s' % page_no
	url = {'path': 'movies/trending/%s', 'params': {'years': years, 'limit': 20}, 'page': page_no}
	return cache_object(get_trakt, string, url, json=False, expiration=EXPIRES_2_DAYS)

def trakt_movies_most_watched(page_no):
	string = 'trakt_movies_most_watched_%s' % page_no
	url = {'path': 'movies/watched/weekly/%s', 'params': {'limit': 20}, 'page': page_no}
	return cache_object(get_trakt, string, url, json=False, expiration=EXPIRES_2_DAYS)

def trakt_tv_trending(page_no):
	string = 'trakt_tv_trending_%s' % page_no
	url = {'path': 'shows/trending/%s', 'params': {'limit': 20}, 'page': page_no}
	return cache_object(get_trakt, string, url, json=False, expiration=EXPIRES_2_DAYS)

def trakt_tv_trending_recent(page_no):
	year = get_datetime().year
	years = '%s-%s' % (year-1, year)
	string = 'trakt_tv_trending_recent_%s' % page_no
	url = {'path': 'shows/trending/%s', 'params': {'years': years, 'limit': 20}, 'page': page_no}
	return cache_object(get_trakt, string, url, json=False, expiration=EXPIRES_2_DAYS)

def trakt_tv_most_watched(page_no):
	string = 'trakt_tv_most_watched_%s' % page_no
	url = {'path': 'shows/watched/weekly/%s', 'params': {'limit': 20}, 'page': page_no}
	return cache_object(get_trakt, string, url, json=False, expiration=EXPIRES_2_DAYS)

def trakt_moviesanime_trending(page_no):
	string = 'trakt_moviesanime_trending_%s' % page_no
	url = {'path': 'movies/trending/%s', 'params': {'limit': 100, 'genres': 'anime'}, 'page': page_no}
	return cache_object(get_trakt, string, url, json=False, expiration=EXPIRES_2_DAYS)

def trakt_moviesanime_most_watched(page_no):
	string = 'trakt_moviesanime_most_watched_%s' % page_no
	url = {'path': 'movies/watched/all/%s', 'params': {'limit': 20, 'genres': 'anime'}, 'page': page_no}
	return cache_object(get_trakt, string, url, json=False, expiration=EXPIRES_2_DAYS)

def trakt_tvanime_trending(page_no):
	string = 'trakt_tvanime_trending_%s' % page_no
	url = {'path': 'shows/trending/%s', 'params': {'limit': 20, 'genres': 'anime'}, 'page': page_no}
	return cache_object(get_trakt, string, url, json=False, expiration=EXPIRES_2_DAYS)

def trakt_tvanime_most_watched(page_no):
	string = 'trakt_tvanime_most_watched_%s' % page_no
	url = {'path': 'shows/watched/all/%s', 'params': {'limit': 20, 'genres': 'anime'}, 'page': page_no}
	return cache_object(get_trakt, string, url, json=False, expiration=EXPIRES_2_DAYS)

def trakt_droplist(mediatype, page_no, letter):
	results = trakt_get_hidden_items('dropped')
	return [{'media_ids': {'tmdb': i}} for i in results], 1

def trakt_get_hidden_items(list_type):
	def _get_trakt_ids(item):
		tmdb_id = get_trakt_tvshow_id(item['show']['ids'])
		results_append(tmdb_id)
	def _process(url):
		hidden_data = get_trakt(url)
		threads = list(make_thread_list(_get_trakt_ids, hidden_data, Thread))
		[i.join() for i in threads]
		return results
	results = []
	results_append = results.append
	string = 'trakt_hidden_items_%s' % list_type
	url = {'path': 'users/hidden/%s', 'path_insert': list_type, 'params': {'limit': 1000, 'type': 'show'}, 'with_auth': True, 'pagination': False}
	return trakt_cache.cache_trakt_object(_process, string, url)

def hide_unhide_trakt_items(action, mediatype, media_id, list_type):
	if not action in ('hide', 'unhide'):
		try:
			hidden_data = set(map(str, trakt_get_hidden_items('dropped')))
			action = 'unhide' if action in hidden_data else 'hide'
		except: return kodi_utils.notification(32574)
	mediatype = 'movies' if mediatype in ['movie', 'movies'] else 'shows'
	key = 'tmdb' if mediatype == 'movies' else 'imdb'
	url = 'users/hidden/%s' % list_type if action == 'hide' else 'users/hidden/%s/remove' % list_type
	data = {mediatype: [{'ids': {key: media_id}}]}
	call_trakt(url, data=data)
	trakt_sync_activities()
	kodi_utils.container_refresh()

def trakt_collection_lists(mediatype, param1, param2):
	# param1 = the type of list to be returned (from 'new_page' param), param2 is currently not used
	limit = 20
#	string_insert = 'movie' if mediatype in ('movie', 'movies') else 'tvshow'
#	window_property_name = 'salts_trakt_collection_%s' % string_insert
#	try: data = json.loads(kodi_utils.get_property(window_property_name))
#	except: data = trakt_fetch_collection_watchlist('collection', mediatype)
	data = trakt_fetch_collection_watchlist('collection', mediatype)
	if param1 == 'recent':
		data.sort(key=lambda k: k['collected_at'], reverse=True)
	elif param1 == 'random':
		import random
		random.shuffle(data)
	data = data[:limit]
	return data, 1

def trakt_collection(mediatype, page_no, letter):
	string_insert = 'movie' if mediatype in ('movie', 'movies') else 'tvshow'
	original_list = trakt_fetch_collection_watchlist('collection', mediatype)
	sort_key = settings.lists_sort_order('collection')
	if   sort_key == 2: original_list.sort(key=lambda k: k['premiered'], reverse=True)
	elif sort_key == 1: original_list.sort(key=lambda k: k['collected_at'], reverse=True)
	else: original_list = sort_for_article(original_list, 'title', settings.ignore_articles())
	if settings.paginate():
		limit = settings.page_limit()
		final_list, total_pages = paginate_list(original_list, page_no, letter, limit)
	else: final_list, total_pages = original_list, 1
	return final_list, total_pages

def trakt_watchlist(mediatype, page_no, letter):
	string_insert = 'movie' if mediatype in ('movie', 'movies') else 'tvshow'
	original_list = trakt_fetch_collection_watchlist('watchlist', mediatype)
	if not settings.show_unaired_watchlist():
		current_date = get_datetime()
		str_format = '%Y-%m-%d' if mediatype in ('movie', 'movies') else '%Y-%m-%dT%H:%M:%S.000Z'
		original_list = [i for i in original_list if i.get('premiered') and js2date(i.get('premiered'), str_format, remove_time=True) <= current_date]
	sort_key = settings.lists_sort_order('watchlist')
	if   sort_key == 2: original_list.sort(key=lambda k: k['premiered'], reverse=True)
	elif sort_key == 1: original_list.sort(key=lambda k: k['collected_at'], reverse=True)
	else: original_list = sort_for_article(original_list, 'title', settings.ignore_articles())
	if settings.paginate():
		limit = settings.page_limit()
		final_list, total_pages = paginate_list(original_list, page_no, letter, limit)
	else: final_list, total_pages = original_list, 1
	return final_list, total_pages

def trakt_favorites(mediatype, page_no, letter):
	string_insert = 'movie' if mediatype in ('movie', 'movies') else 'tvshow'
	original_list = trakt_fetch_collection_watchlist('favorites', mediatype)
	if settings.paginate():
		limit = settings.page_limit()
		final_list, total_pages = paginate_list(original_list, page_no, letter, limit)
	else: final_list, total_pages = original_list, 1
	return final_list, total_pages

def trakt_fetch_collection_watchlist(list_type, mediatype):
	if mediatype in ('movie', 'movies'): key, string_insert, path_insert = ('movie', 'movie', 'movies')
	else: key, string_insert, path_insert = ('show', 'tvshow', 'shows')
	premiered = 'released' if key == 'movie' else 'first_aired'
	if list_type == 'collection':
		if mediatype in ('movie', 'movies'): collected_at = 'collected_at'
		else: collected_at = 'last_collected_at'
	else: collected_at = 'listed_at'
	string = 'trakt_%s_%s' % (list_type, string_insert)
	url = 'sync/%s/%s' % (list_type, path_insert)
	data = trakt_cache.cache_trakt_object(_get_trakt_paginated_list, string, url)
	return [
		{'title': i[key]['title'], 'media_ids': i[key]['ids'],
		 'collected_at': i.get(collected_at), 'premiered': i[key].get(premiered) or ''}
		for i in data
	]

def add_to_list(user, slug, data):
	result = call_trakt('users/%s/lists/%s/items' % (user, slug), data=data)
	if result['added']['movies'] + result['added']['shows'] == 0: return kodi_utils.notification(32574)
	kodi_utils.notification(32576)
	trakt_sync_activities()
	return result

def remove_from_list(user, slug, data):
	result = call_trakt('users/%s/lists/%s/items/remove' % (user, slug), data=data)
	if result['deleted']['movies'] + result['deleted']['shows'] == 0: return kodi_utils.notification(32574)
	kodi_utils.notification(32576)
	trakt_sync_activities()
	kodi_utils.container_refresh()
	return result

def add_to_sync(list_type, data):
	key = 'episodes' if list_type == 'collection' else 'shows'
	result = call_trakt('sync/%s' % list_type, data=data)
	if result['added']['movies'] + result['added'][key] == 0: return kodi_utils.notification(32574)
	kodi_utils.notification(32576)
	trakt_sync_activities()
	return result

def remove_from_sync(list_type, data):
	key = 'episodes' if list_type == 'collection' else 'shows'
	result = call_trakt('sync/%s/remove' % list_type, data=data)
	if result['deleted']['movies'] + result['deleted'][key] == 0: return kodi_utils.notification(32574)
	kodi_utils.notification(32576)
	trakt_sync_activities()
	kodi_utils.container_refresh()
	return result

def trakt_search_lists(search_title, page):
#	lists, pages = call_trakt('search', params={'type': 'list', 'fields': 'name, description', 'query': search_title, 'limit': 50}, pagination=True, page=page)
	lists, pages = call_trakt('search/list', params={'query': search_title, 'limit': 50}, pagination=True, page=page)
	return lists, pages

def trakt_trending_popular_lists(list_type):
	string = 'trakt_%s_user_lists' % list_type
	url = {'path': 'lists/%s', 'path_insert': list_type, 'params': {'limit': 100}}
	return cache_object(get_trakt, string, url, json=False)

def get_trakt_list_contents(list_type, list_id, user, slug):
	string = 'trakt_list_contents_%s_%s_%s' % (list_type, user, slug)
	url = 'users/%s/lists/%s/items' % (user, list_id)
	return trakt_cache.cache_trakt_object(_get_trakt_paginated_list, string, url)

def _get_trakt_paginated_list(url):
	items = []
	try:
		params = {'limit': 1000}
		if 'sync' in url: params['extended'] = 'full'
		items, pages = call_trakt(url, params, pagination=True)
		for page in range(2, int(pages) + 1):
			params['page'] = page
			result = call_trakt(url, params)
			if result is None: break
			items += result
	finally: return items

def trakt_get_lists(list_type):
	if list_type == 'liked_lists': string, path_insert = 'trakt_liked_lists', 'likes/lists'
	else: string, path_insert = 'trakt_my_lists', 'lists'
	url = {'path': 'users/me/%s', 'path_insert': path_insert, 'params': {'limit': 100}, 'with_auth': True}
	return trakt_cache.cache_trakt_object(get_trakt, string, url)

def make_new_trakt_list(params):
	from urllib.parse import unquote
	list_title = kodi_utils.dialog.input('SALTS')
	if not list_title: return
	list_name = unquote(list_title)
	data = {'name': list_name, 'privacy': 'public', 'allow_comments': False, 'sort_by': 'added', 'sort_how': 'desc'}
	call_trakt('users/me/lists', data=data)
	trakt_sync_activities()
	kodi_utils.notification(32576)
	kodi_utils.container_refresh()

def delete_trakt_list(params):
	user = params['user']
	list_slug = params['list_slug']
	if not kodi_utils.confirm_dialog(): return
	url = 'users/%s/lists/%s' % (user, list_slug)
	call_trakt(url, method='delete')
	trakt_sync_activities()
	kodi_utils.notification(32576)
	kodi_utils.container_refresh()

def trakt_like_a_list(params):
	user = params['user']
	list_slug = params['list_slug']
	try:
		call_trakt('users/%s/lists/%s/like' % (user, list_slug), method='post')
		kodi_utils.notification(32576)
		trakt_sync_activities()
	except: kodi_utils.notification(32574)

def trakt_unlike_a_list(params):
	user = params['user']
	list_slug = params['list_slug']
	try:
		call_trakt('users/%s/lists/%s/like' % (user, list_slug), method='delete')
		kodi_utils.notification(32576)
		trakt_sync_activities()
		kodi_utils.container_refresh()
	except: kodi_utils.notification(32574)

def get_trakt_movie_id(item):
	if item['tmdb']: return item['tmdb']
	tmdb_id = None
	if item['imdb']:
		try:
			meta = movie_external_id('imdb_id', item['imdb'])
			tmdb_id = meta['id']
		except: pass
	return tmdb_id

def get_trakt_tvshow_id(item):
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

def trakt_watched_unwatched(action, media, media_id, tvdb_id=0, season=None, episode=None, key='tmdb'):
	if action == 'mark_as_watched': url, result_key = 'sync/history', 'added'
	else: url, result_key = 'sync/history/remove', 'deleted'
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
	result = call_trakt(url, data=data)
	success = result[result_key][success_key] > 0
	if not success:
		if media != 'movies' and tvdb_id != 0:
			return trakt_watched_unwatched(action, media, tvdb_id, 0, season, episode, 'tvdb')
	return success

def trakt_progress(action, media, media_id, percent, season=None, episode=None, resume_id=None, refresh_trakt=False):
	if action == 'clear_progress':
		url = 'sync/playback/%s' % resume_id
		call_trakt(url, method='delete')
	else:
		url = 'scrobble/pause'
		if media in ('movie', 'movies'): data = {'movie': {'ids': {'tmdb': media_id}}, 'progress': float(percent)}
		else: data = {'show': {'ids': {'tmdb': media_id}}, 'episode': {'season': int(season), 'number': int(episode)}, 'progress': float(percent)}
		call_trakt(url, data=data)
	if refresh_trakt: trakt_sync_activities()

def trakt_indicators_movies():
	def _process(item):
		movie = item['movie']
		title = movie['title']
		tmdb_id = get_trakt_movie_id(movie['ids'])
		if not tmdb_id: return
		insert_append(('movie', tmdb_id, '', '', item['last_watched_at'], title))
	insert_list = []
	insert_append = insert_list.append
	result = [(i,) for i in call_trakt('sync/watched/movies')] # TaskPool requires tuple
	if not result: return
	for i in TaskPool().tasks(_process, result, Thread): i.join()
#	threads = list(make_thread_list(_process, result, Thread))
#	[i.join() for i in threads]
	trakt_cache.TraktCache().set_bulk_movie_watched(insert_list)

def trakt_indicators_tv():
	def _process(item):
		show, seasons = item['show'], item['seasons']
		title = show['title']
		tmdb_id = get_trakt_tvshow_id(show['ids'])
		if not tmdb_id: return
		reset_at = item.get('reset_at')
		if reset_at: reset_at = js2date(reset_at, '%Y-%m-%dT%H:%M:%S.000Z')
		for s in seasons:
			season_no, episodes = s['number'], s['episodes']
			for e in episodes:
				if reset_at and reset_at > js2date(e['last_watched_at'], '%Y-%m-%dT%H:%M:%S.000Z'): continue
				insert_append(('episode', tmdb_id, season_no, e['number'], e['last_watched_at'], title))
	insert_list = []
	insert_append = insert_list.append
	result = [(i,) for i in call_trakt('sync/watched/shows')] # TaskPool requires tuple
	if not result: return
	for i in TaskPool().tasks(_process, result, Thread): i.join()
#	threads = list(make_thread_list(_process, result, Thread))
#	[i.join() for i in threads]
	trakt_cache.TraktCache().set_bulk_tvshow_watched(insert_list)

def trakt_progress_movies(progress_info):
	def _process(item):
		tmdb_id = get_trakt_movie_id(item['movie']['ids'])
		if not tmdb_id: return
		insert_append((
			'movie', str(tmdb_id), '', '', str(round(item['progress'], 1)),
			0, item['paused_at'], item['id'], item['movie']['title']
		))
	insert_list = []
	insert_append = insert_list.append
	progress_items = [i for i in progress_info if i['type'] == 'movie' and i['progress'] > 1]
	if not progress_items: return
	threads = list(make_thread_list(_process, progress_items, Thread))
	[i.join() for i in threads]
	trakt_cache.TraktCache().set_bulk_movie_progress(insert_list)

def trakt_progress_tv(progress_info):
	def _process_tmdb_ids(item):
		tmdb_id = get_trakt_tvshow_id(item['ids'])
		tmdb_list_append((tmdb_id, item['title']))
	def _process():
		for item in tmdb_list:
			try:
				tmdb_id, title = item[0], item[1]
				if not tmdb_id: continue
				for p_item in progress_items:
					if not p_item['show']['title'] == title: continue
					season, episode = p_item['episode']['season'], p_item['episode']['number']
					if season > 0: yield (
						'episode', str(tmdb_id), season, episode, str(round(p_item['progress'], 1)),
						0, p_item['paused_at'], p_item['id'], p_item['show']['title']
					)
			except: pass
	tmdb_list = []
	tmdb_list_append = tmdb_list.append
	progress_items = [i for i in progress_info if i['type'] == 'episode' and i['progress'] > 1]
	if not progress_items: return
	all_shows = [i['show'] for i in progress_items]
	all_shows = [i for n, i in enumerate(all_shows) if i not in all_shows[n + 1:]] # remove duplicates
	threads = list(make_thread_list(_process_tmdb_ids, all_shows, Thread))
	[i.join() for i in threads]
	insert_list = list(_process())
	trakt_cache.TraktCache().set_bulk_tvshow_progress(insert_list)

def trakt_official_status(mediatype):
	if not kodi_utils.addon_installed('script.trakt'): return True
	trakt_addon = kodi_utils.addon('script.trakt')
	try: authorization = trakt_addon.getSetting('authorization')
	except: authorization = ''
	if authorization == '': return True
	try: exclude_http = trakt_addon.getSetting('ExcludeHTTP')
	except: exclude_http = ''
	if exclude_http in ('true', ''): return True
	media_setting = 'scrobble_movie' if mediatype in ('movie', 'movies') else 'scrobble_episode'
	try: scrobble = trakt_addon.getSetting(media_setting)
	except: scrobble = ''
	if scrobble in ('false', ''): return True
	return False

def trakt_get_my_calendar(recently_aired, current_date):
	def _process(dummy):
		data = get_trakt(url)
		data = [
			{'sort_title': '%s s%s e%s' % (i['show']['title'], str(i['episode']['season']).zfill(2), str(i['episode']['number']).zfill(2)),
			'media_ids': i['show']['ids'], 'season': i['episode']['season'], 'episode': i['episode']['number'], 'first_aired': i['first_aired']}
			for i in data
			if i['episode']['season'] > 0 and not 'anime' in i['show']['genres']
		]
		data = [i for n, i in enumerate(data) if i not in data[n + 1:]] # remove duplicates
		return data
	start, finish = trakt_calendar_days(recently_aired, current_date)
	string = 'trakt_get_my_calendar_%s_%s' % (start, finish)
	url = {'path': 'calendars/my/shows/%s/%s', 'path_insert': (start, finish), 'params': {'extended': 'full'}, 'with_auth': True, 'pagination': False}
	return trakt_cache.cache_trakt_object(_process, string, url)

def trakt_my_anime_calendar(current_date):
	def _process(dummy):
		data = get_trakt(url)
		data = [
			{'sort_title': '%s s%s e%s' % (i['show']['title'], str(i['episode']['season']).zfill(2), str(i['episode']['number']).zfill(2)),
			'media_ids': i['show']['ids'], 'season': i['episode']['season'], 'episode': i['episode']['number'], 'first_aired': i['first_aired']}
			for i in data
			if i['episode']['season'] > 0
		]
		data = [i for n, i in enumerate(data) if i not in data[n + 1:]] # remove duplicates
		return data
	start, finish = trakt_calendar_days(False, current_date)
	string = 'trakt_get_my_calendar_anime_%s_%s' % (start, finish)
	url = {'path': 'calendars/my/shows/%s/%s', 'path_insert': (start, finish), 'params': {'genres': 'anime'}, 'with_auth': True, 'pagination': False}
	return trakt_cache.cache_trakt_object(_process, string, url)

def trakt_anime_calendar(current_date):
	def _process(dummy):
		data = get_trakt(url)
		data = [
			{'sort_title': '%s s%s e%s' % (i['show']['title'], str(i['episode']['season']).zfill(2), str(i['episode']['number']).zfill(2)),
			'media_ids': i['show']['ids'], 'season': i['episode']['season'], 'episode': i['episode']['number'], 'first_aired': i['first_aired']}
			for i in data
			if i['episode']['season'] > 0
		]
		data = [i for n, i in enumerate(data) if i not in data[n + 1:]] # remove duplicates
		return data
	start, finish = trakt_calendar_days(False, current_date)
	string = 'trakt_anime_calendar_%s_%s' % (start, finish)
	url = {'path': 'calendars/all/shows/%s/%s', 'path_insert': (start, finish), 'params': {'genres': 'anime'}, 'with_auth': True, 'pagination': False}
	return trakt_cache.cache_trakt_object(_process, string, url)

def trakt_calendar_days(recently_aired, current_date):
	from datetime import timedelta
	if recently_aired: start, finish = (current_date - timedelta(days=7)).strftime('%Y-%m-%d'), '7'
	else:
		previous_days = int(get_setting('trakt.calendar_previous_days', '3'))
		future_days = int(get_setting('trakt.calendar_future_days', '7'))
		start = (current_date - timedelta(days=previous_days)).strftime('%Y-%m-%d')
		finish = str(previous_days + future_days)
	return start, finish

def trakt_get_activity():
	url = {'path': 'sync/%s', 'path_insert': 'last_activities', 'with_auth': True, 'pagination': False}
	return get_trakt(url)

def trakt_playback_progress():
	url = {'path': 'sync/%s', 'path_insert': 'playback', 'with_auth': True, 'pagination': False}
	return get_trakt(url)

def trakt_sync_activities_thread(*args, **kwargs):
	Thread(target=trakt_sync_activities, args=args, kwargs=kwargs).start()

@trakt_expires
def trakt_sync_activities(force_update=False):
	def _get_timestamp(date_time):
		return int(time.mktime(date_time.timetuple()))
	def _compare(latest, cached, res_format='%Y-%m-%dT%H:%M:%S.000Z'):
		try: result = _get_timestamp(js2date(latest, res_format)) > _get_timestamp(js2date(cached, res_format))
		except: result = True
		return result
	if not get_setting('trakt_user', ''): return 'no account'
	if force_update:
		check_databases()
		trakt_cache.clear_all_trakt_cache_data(refresh=False)
	trakt_cache.clear_trakt_calendar()
	latest = trakt_get_activity()
	if not latest:
		trakt_cache.clear_all_trakt_cache_data(refresh=False)
		return 'failed'
	cached = trakt_cache.reset_activity(latest)
	if not _compare(latest['all'], cached['all']):
		trakt_cache.clear_trakt_list_contents_data('liked_lists')
		return 'not needed'
	clear_list_contents, lists_actions = False, []
	refresh_movies_progress, refresh_shows_progress = False, False
	cached_movies, latest_movies = cached['movies'], latest['movies']
	cached_shows, latest_shows = cached['shows'], latest['shows']
	cached_episodes, latest_episodes = cached['episodes'], latest['episodes']
	cached_lists, latest_lists = cached['lists'], latest['lists']
	if _compare(latest_movies['collected_at'], cached_movies['collected_at']): trakt_cache.clear_trakt_collection_watchlist_data('collection', 'movie')
	if _compare(latest_episodes['collected_at'], cached_episodes['collected_at']): trakt_cache.clear_trakt_collection_watchlist_data('collection', 'tvshow')
	if _compare(latest_movies['watchlisted_at'], cached_movies['watchlisted_at']): trakt_cache.clear_trakt_collection_watchlist_data('watchlist', 'movie')
	if _compare(latest_shows['watchlisted_at'], cached_shows['watchlisted_at']): trakt_cache.clear_trakt_collection_watchlist_data('watchlist', 'tvshow')
	if _compare(latest_movies['favorited_at'], cached_movies['favorited_at']): trakt_cache.clear_trakt_collection_watchlist_data('favorites', 'movie')
	if _compare(latest_shows['favorited_at'], cached_shows['favorited_at']): trakt_cache.clear_trakt_collection_watchlist_data('favorites', 'tvshow')
	if _compare(latest_shows['dropped_at'], cached_shows['dropped_at']): trakt_cache.clear_trakt_hidden_data('dropped')
	if _compare(latest_movies['recommendations_at'], cached_movies['recommendations_at']): trakt_cache.clear_trakt_recommendations('movies')
	if _compare(latest_shows['recommendations_at'], cached_shows['recommendations_at']): trakt_cache.clear_trakt_recommendations('shows')
	if _compare(latest_movies['watched_at'], cached_movies['watched_at']): trakt_indicators_movies()
	if _compare(latest_episodes['watched_at'], cached_episodes['watched_at']): trakt_indicators_tv()
	if _compare(latest_movies['paused_at'], cached_movies['paused_at']): refresh_movies_progress = True
	if _compare(latest_episodes['paused_at'], cached_episodes['paused_at']): refresh_shows_progress = True
	if _compare(latest_lists['updated_at'], cached_lists['updated_at']):
		clear_list_contents = True
		lists_actions.append('my_lists')
	if _compare(latest_lists['liked_at'], cached_lists['liked_at']):
		clear_list_contents = True
		lists_actions.append('liked_lists')
	if refresh_movies_progress or refresh_shows_progress:
		progress_info = trakt_playback_progress()
		if refresh_movies_progress: trakt_progress_movies(progress_info)
		if refresh_shows_progress: trakt_progress_tv(progress_info)
	if clear_list_contents:
		for item in lists_actions:
			trakt_cache.clear_trakt_list_data(item)
			trakt_cache.clear_trakt_list_contents_data(item)
	else: trakt_cache.clear_trakt_list_contents_data('liked_lists')
	return 'success'

