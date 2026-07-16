import requests
from threading import Thread
from operator import itemgetter
from concurrent.futures import ThreadPoolExecutor
from caches import trakt_cache
from caches.main_cache import cache_object
from indexers.tmdb_api import movie_external_id, tvshow_external_id
from modules import kodi_utils, settings
from modules.cache import check_databases
from modules.utils import sort_list, sort_for_article, make_thread_list, jsondate_to_datetime, paginate_list, get_datetime, TaskPool

ls, logger = kodi_utils.local_string, kodi_utils.logger
get_setting, set_setting = kodi_utils.get_setting, kodi_utils.set_setting
EXPIRES_2_DAYS = 48
READ_TOKEN = kodi_utils.addon().getSetting('trakt.client_id')
base_url = 'https://api.trakt.tv/%s'
timeout = 10.05
session = requests.Session()
session.headers.update({'User-Agent': kodi_utils.xbmc.getUserAgent()})
retry = requests.adapters.Retry(total=None, status=1, status_forcelist=(429, 502, 503, 504))
session.mount('https://api.trakt.tv', requests.adapters.HTTPAdapter(pool_maxsize=100, max_retries=retry))

def call_trakt(path, params=None, data=None, with_auth=True, method=None, pagination=False, page=1):
	if isinstance(path, dict): return call_trakt(str(path.pop('path')), **path)
	else: path = str(path)
	headers = {'Content-Type': 'application/json', 'trakt-api-key': READ_TOKEN, 'trakt-api-version': '2'}
	if with_auth and (token := get_setting('trakt.token')): headers['Authorization'] = 'Bearer %s' % token
	try:
		response = session.request(
			'post' if data is not None else method or 'get',
			base_url % path,
			params=None if data is not None else params,
			json=data if data else None,
			headers=headers,
			timeout=timeout
		)
		result = response.json() if 'json' in response.headers.get('Content-Type', '') else response.text
		if not response.ok: response.raise_for_status()
		if (sort_by := response.headers.get('X-Sort-By')) and (sort_how := response.headers.get('X-Sort-How')):
#			result = sort_list(sort_by, sort_how, result, settings.ignore_articles())
			if sort_how in ('asc',) and sort_by in ('added', 'released'):
				if isinstance(result, list) and get_setting('trakt.reverse') == 'true': result.reverse()
		if pagination: return result, int(response.headers.get('X-Pagination-Page-Count', page))
		return result
	except requests.RequestException as e:
		logger('trakt error', str(e))

def _get_trakt_paginated_list(url):
	if 'extended=progress' in url: params = {'limit': 100, 'page': 1}
	else: params = {'limit': 250, 'page': 1}
	try: items, pages = call_trakt(url, params=params, pagination=True)
	except: return []
	if pages <= 1: return items
	args = ({'path': url, 'params': {**params, 'page': page}} for page in range(2, pages + 1))
	with ThreadPoolExecutor() as tpe: # keep max_workers as default, min(32, os.cpu_count() + 4)
		for result in tpe.map(call_trakt, args): # ThreadPoolExecutor map preserves order
			if isinstance(result, list): items.extend(result) # caution, hides thread exceptions
	return items

def trakt_refresh():
	try:
		data = {'grant_type': 'refresh_token', 'redirect_uri': 'urn:ietf:wg:oauth:2.0:oob'}
		data['refresh_token'] = get_setting('trakt.refresh')
		data['client_secret'] = get_setting('trakt.client_secret')
		data['client_id'] = get_setting('trakt.client_id')
		response = requests.post(base_url % 'oauth/token', json=data, timeout=timeout).json()
		expires = int(response['created_at']) + int(response['expires_in'])
		refresh, token = response['refresh_token'], response['access_token']
		set_setting('trakt.token', token)
		set_setting('trakt.refresh', refresh)
		set_setting('trakt.expires', str(expires))
		kodi_utils.sleep(500)
	except Exception as e: logger('trakt_refresh error', str(e))

def trakt_expires():
	if not get_setting('trakt.refresh', ''): return
	from datetime import datetime, timezone
	expires = float(get_setting('trakt.expires', '0'))
	interval = settings.trakt_sync_interval()[1]
	current = datetime.now(timezone.utc).timestamp()
	current = (-1 * current // 1 * -1) + interval
	if current >= expires: trakt_refresh()

def trakt_movies_trending(page_no):
	params = {'limit': 20, 'page': page_no}
	string = 'trakt_movies_trending_%s' % page_no
	url = {'path': 'movies/trending', 'params': params, 'with_auth': False, 'pagination': True}
	return cache_object(call_trakt, string, url, expiration=EXPIRES_2_DAYS)

def trakt_movies_trending_recent(page_no):
	year = get_datetime().year
	params = {'languages': 'en', 'limit': 250, 'page': page_no, 'years': '%s-%s' % (year-1, year)}
	string = 'trakt_movies_trending_recent_%s' % page_no
	url = {'path': 'movies/trending', 'params': params, 'with_auth': False, 'pagination': True}
	return cache_object(call_trakt, string, url, expiration=EXPIRES_2_DAYS)

def trakt_movies_most_watched(page_no):
	params = {'limit': 20, 'page': page_no}
	string = 'trakt_movies_most_watched_%s' % page_no
	url = {'path': 'movies/watched/weekly', 'params': params, 'with_auth': False, 'pagination': True}
	return cache_object(call_trakt, string, url, expiration=EXPIRES_2_DAYS)

def trakt_tv_trending(page_no):
	params = {'limit': 20, 'page': page_no}
	string = 'trakt_tv_trending_%s' % page_no
	url = {'path': 'shows/trending', 'params': params, 'with_auth': False, 'pagination': True}
	return cache_object(call_trakt, string, url, expiration=EXPIRES_2_DAYS)

def trakt_tv_trending_recent(page_no):
	year = get_datetime().year
	params = {'languages': 'en', 'limit': 250, 'page': page_no, 'years': '%s-%s' % (year-1, year)}
	string = 'trakt_tv_trending_recent_%s' % page_no
	url = {'path': 'shows/trending', 'params': params , 'with_auth': False, 'pagination': True}
	return cache_object(call_trakt, string, url, expiration=EXPIRES_2_DAYS)

def trakt_tv_most_watched(page_no):
	params = {'limit': 20, 'page': page_no}
	string = 'trakt_tv_most_watched_%s' % page_no
	url = {'path': 'shows/watched/weekly', 'params': params, 'with_auth': False, 'pagination': True}
	return cache_object(call_trakt, string, url, expiration=EXPIRES_2_DAYS)

def trakt_moviesanime_trending(page_no):
	params = {'limit': 20, 'page': page_no, 'genres': 'anime'}
	string = 'trakt_moviesanime_trending_%s' % page_no
	url = {'path': 'movies/trending', 'params': params, 'with_auth': False, 'pagination': True}
	return cache_object(call_trakt, string, url, expiration=EXPIRES_2_DAYS)

def trakt_moviesanime_most_watched(page_no):
	params = {'limit': 20, 'page': page_no, 'genres': 'anime'}
	string = 'trakt_moviesanime_most_watched_%s' % page_no
	url = {'path': 'movies/watched/all', 'params': params, 'with_auth': False, 'pagination': True}
	return cache_object(call_trakt, string, url, expiration=EXPIRES_2_DAYS)

def trakt_tvanime_trending(page_no):
	params = {'limit': 20, 'page': page_no, 'genres': 'anime'}
	string = 'trakt_tvanime_trending_%s' % page_no
	url = {'path': 'shows/trending', 'params': params, 'with_auth': False, 'pagination': True}
	return cache_object(call_trakt, string, url, expiration=EXPIRES_2_DAYS)

def trakt_tvanime_most_watched(page_no):
	params = {'limit': 20, 'page': page_no, 'genres': 'anime'}
	string = 'trakt_tvanime_most_watched_%s' % page_no
	url = {'path': 'shows/watched/all', 'params': params, 'with_auth': False, 'pagination': True}
	return cache_object(call_trakt, string, url, expiration=EXPIRES_2_DAYS)

def trakt_trending_popular_lists(list_type):
	string = 'trakt_%s_user_lists' % list_type
	url = {'path': 'lists/%s' % list_type, 'params': {'limit': 100}, 'with_auth': False}
	return cache_object(call_trakt, string, url)

def trakt_search_lists(search_title, page):
	params = {'limit': 100, 'page': page, 'query': search_title}
	return call_trakt('search/list', params=params, with_auth=False, pagination=True)

def trakt_recommendations(mediatype):
	params = {'limit': 100, 'ignore_collected': 'true', 'ignore_watchlisted': 'true'}
	string = 'trakt_recommendations_%s' % mediatype
	url = {'path': 'recommendations/%s' % mediatype, 'params': params}
	return trakt_cache.cache_trakt_object(call_trakt, string, url)

def trakt_droplist(mediatype, page_no):
	results = trakt_get_hidden_items('dropped')
	return [{'media_ids': {'tmdb': i}} for i in results], 1

def trakt_get_hidden_items(list_type):
	def _get_trakt_ids(item):
		tmdb_id = get_trakt_tvshow_id(item['show']['ids'])
		results_append(tmdb_id)
	def _process(url):
		hidden_data = [(i,) for i in _get_trakt_paginated_list(url)] # TaskPool requires tuple
		for i in TaskPool().tasks(_get_trakt_ids, hidden_data, Thread): i.join()
#		threads = list(make_thread_list(_get_trakt_ids, hidden_data, Thread))
#		[i.join() for i in threads]
		return results
	results = []
	results_append = results.append
	string = 'trakt_hidden_items_%s' % list_type
	url = 'users/hidden/dropped?type=show'
	return trakt_cache.cache_trakt_object(_process, string, url)

def hide_unhide_trakt_items(action, mediatype, media_id, list_type):
	if action not in ('hide', 'unhide'):
		try:
			hidden_data = trakt_get_hidden_items('dropped')
			action = 'unhide' if int(action) in hidden_data else 'hide'
		except: return kodi_utils.notification(32574)
	mediatype = 'movies' if mediatype in ('movie', 'movies') else 'shows'
	key = 'tmdb' if mediatype == 'movies' else 'imdb'
	url = 'users/hidden/dropped' if action == 'hide' else 'users/hidden/dropped/remove'
	data = {mediatype: [{'ids': {key: media_id}}]}
	call_trakt(url, data=data)
	trakt_sync_activities()
	kodi_utils.container_refresh()

def trakt_collection_lists(mediatype, param1):
	data = trakt_fetch_collection_watchlist('collection', mediatype)
	if param1 == 'random': import random ; random.shuffle(data)
	else: data.sort(key=itemgetter('collected_at'), reverse=True)
	return data[:40], 1

def trakt_watchlist_lists(mediatype, param1):
	data = trakt_fetch_collection_watchlist('watchlist', mediatype)
	if param1 == 'random': import random ; random.shuffle(data)
	else: data.sort(key=itemgetter('collected_at'), reverse=True)
	return data[:40], 1

def trakt_collection(mediatype, page_no):
	original_list = trakt_fetch_collection_watchlist('collection', mediatype)
	sort_key = settings.lists_sort_order('collection')
	if   sort_key == 2: original_list.sort(key=itemgetter('premiered'), reverse=True)
	elif sort_key == 1: original_list.sort(key=itemgetter('collected_at'), reverse=True)
	else: original_list = sort_for_article(original_list, 'title', settings.ignore_articles())
	if settings.paginate(): return paginate_list(original_list, page_no, settings.page_limit())
	return original_list, 1

def trakt_favorites(mediatype, page_no):
	original_list = trakt_fetch_collection_watchlist('favorites', mediatype)
	sort_key = settings.lists_sort_order('collection')
	if   sort_key == 2: original_list.sort(key=itemgetter('premiered'), reverse=True)
	elif sort_key == 1: original_list.sort(key=itemgetter('collected_at'), reverse=True)
	else: original_list = sort_for_article(original_list, 'title', settings.ignore_articles())
	if settings.paginate(): return paginate_list(original_list, page_no, settings.page_limit())
	return original_list, 1

def trakt_watchlist(mediatype, page_no):
	def first_aired(item):
		if not item.get('premiered'): return False
		return jsondate_to_datetime(item['premiered']).astimezone().date() <= current_date
	original_list = trakt_fetch_collection_watchlist('watchlist', mediatype)
	if not settings.show_unaired_watchlist():
		current_date = get_datetime()
		original_list = [i for i in original_list if first_aired(i)]
	sort_key = settings.lists_sort_order('watchlist')
	if   sort_key == 2: original_list.sort(key=itemgetter('premiered'), reverse=True)
	elif sort_key == 1: original_list.sort(key=itemgetter('collected_at'), reverse=True)
	else: original_list = sort_for_article(original_list, 'title', settings.ignore_articles())
	if settings.paginate(): return paginate_list(original_list, page_no, settings.page_limit())
	return original_list, 1

def trakt_fetch_collection_watchlist(list_type, mediatype):
	def _process(dummy):
		return [
			{'collected_at': i.get(collected_at), 'premiered': i[key].get(premiered) or '',
			 'title': i[key]['title'], 'media_ids': i[key]['ids']}
			for i in _get_trakt_paginated_list(url)
		]
	if mediatype in ('movie', 'movies'):
		key, string_insert, path_insert = ('movie', 'movie', 'movies')
	else: key, string_insert, path_insert = ('show', 'tvshow', 'shows')
	premiered = 'released' if key == 'movie' else 'first_aired'
	if list_type == 'collection':
		if key == 'movie': collected_at = 'collected_at'
		else: collected_at = 'last_collected_at'
	else: collected_at = 'listed_at'
	string = 'trakt_%s_%s' % (list_type, string_insert)
	url = 'users/me/%s/%s?extended=full' % (list_type, path_insert)
	return trakt_cache.cache_trakt_object(_process, string, url)

def get_trakt_list_contents(list_type, list_id, user, slug):
	string = 'trakt_list_contents_%s_%s_%s' % (list_type, user, slug)
	url = 'users/%s/lists/%s/items' % (user, list_id)
	return trakt_cache.cache_trakt_object(_get_trakt_paginated_list, string, url)

def trakt_get_lists(list_type):
	if list_type == 'liked_lists': string, path_insert = 'trakt_liked_lists', 'likes/lists'
	else: string, path_insert = 'trakt_my_lists', 'lists'
	url = {'path': 'users/me/%s' % path_insert, 'params': {'limit': 100}}
	return trakt_cache.cache_trakt_object(call_trakt, string, url)

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

def make_new_trakt_list(params):
	from urllib.parse import unquote
	list_title = kodi_utils.dialog.input('POV')
	if not list_title: return
	list_name = unquote(list_title)
	data = {'name': list_name, 'privacy': 'public', 'sort_by': 'added', 'sort_how': 'desc'}
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
	for k, v in (('imdb_id', 'imdb'),):
		try: return movie_external_id(k, item[v])['id']
		except: pass

def get_trakt_tvshow_id(item):
	if item['tmdb']: return item['tmdb']
	for k, v in (('imdb_id', 'imdb'), ('tvdb_id', 'tvdb')):
		try: return tvshow_external_id(k, item[v])['id']
		except: pass

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
		url, kwargs = 'sync/playback/%s' % resume_id, {'method': 'delete'}
	else:
		if media in ('movie', 'movies'): data = {'movie': {'ids': {'tmdb': media_id}}, 'progress': float(percent)}
		else: data = {'show': {'ids': {'tmdb': media_id}}, 'episode': {'season': int(season), 'number': int(episode)}, 'progress': float(percent)}
		url, kwargs = 'scrobble/pause', {'data': data}
	call_trakt(url, **kwargs)
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
	url = 'sync/watched/movies'
	result = [(i,) for i in _get_trakt_paginated_list(url)] # TaskPool requires tuple
	if not result: return trakt_cache.TraktCache().set_bulk_movie_watched(insert_list)
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
		for s in seasons:
			season_no, episodes = s['number'], s['episodes']
			for e in episodes:
				if reset_at and reset_at > e['last_watched_at']: continue
				insert_append(('episode', tmdb_id, season_no, e['number'], e['last_watched_at'], title))
	insert_list = []
	insert_append = insert_list.append
	url = 'sync/watched/shows?extended=progress'
	result = [(i,) for i in _get_trakt_paginated_list(url)] # TaskPool requires tuple
	if not result: return trakt_cache.TraktCache().set_bulk_tvshow_watched(insert_list)
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
	if not progress_items: return trakt_cache.TraktCache().set_bulk_movie_progress(insert_list)
	threads = list(make_thread_list(_process, progress_items, Thread))
	[i.join() for i in threads]
	trakt_cache.TraktCache().set_bulk_movie_progress(insert_list)

def trakt_progress_tv(progress_info):
	def _process_tmdb_ids(item):
		tmdb_id = get_trakt_tvshow_id(item['ids'])
		tmdb_list_append({item['ids']['slug']: tmdb_id})
	def _process():
		for item in progress_items:
			try:
				tmdb_id = tmdb_list.get(item['show']['ids']['slug'])
				if not tmdb_id: continue
				season, episode = item['episode']['season'], item['episode']['number']
				if season > 0: yield (
					'episode', str(tmdb_id), season, episode, str(round(item['progress'], 1)),
					0, item['paused_at'], item['id'], item['show']['title']
				)
			except: pass
	tmdb_list = {}
	tmdb_list_append = tmdb_list.update
	progress_items = [i for i in progress_info if i['type'] == 'episode' and i['progress'] > 1]
	if not progress_items: return trakt_cache.TraktCache().set_bulk_tvshow_progress([])
	all_shows = {i['show']['ids']['slug']: i['show'] for i in progress_items} # remove duplicates
	threads = list(make_thread_list(_process_tmdb_ids, all_shows.values(), Thread))
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

def trakt_calendar_days(recently_aired, current_date):
	from datetime import timedelta
	if recently_aired: return (current_date - timedelta(days=7)).strftime('%Y-%m-%d'), '7'
	previous_days = int(get_setting('trakt.calendar_previous_days', '3'))
	future_days = int(get_setting('trakt.calendar_future_days', '7'))
	start = (current_date - timedelta(days=previous_days)).strftime('%Y-%m-%d')
	finish = str(previous_days + future_days)
	return start, finish

def trakt_get_my_calendar(recently_aired, current_date):
	def _process(dummy):
		data = [
			{'sort_title': '%s s%s e%s' % (i['show']['title'], str(i['episode']['season']).zfill(2), str(i['episode']['number']).zfill(2)),
			'media_ids': i['show']['ids'], 'season': i['episode']['season'], 'episode': i['episode']['number'], 'first_aired': i['first_aired']}
			for i in call_trakt(url)
			if i['episode']['season'] > 0 and 'anime' not in i['show']['genres']
		]
		data = [i for n, i in enumerate(data) if i not in data[n + 1:]] # remove duplicates
		return data
	start, finish = trakt_calendar_days(recently_aired, current_date)
	string = 'trakt_get_my_calendar_%s_%s' % (start, finish)
	url = {'path': 'calendars/my/shows/%s/%s' % (start, finish), 'params': {'extended': 'full'}}
	return trakt_cache.cache_trakt_object(_process, string, url)

def trakt_get_my_anime_calendar(current_date):
	def _process(dummy):
		data = [
			{'sort_title': '%s s%s e%s' % (i['show']['title'], str(i['episode']['season']).zfill(2), str(i['episode']['number']).zfill(2)),
			'media_ids': i['show']['ids'], 'season': i['episode']['season'], 'episode': i['episode']['number'], 'first_aired': i['first_aired']}
			for i in call_trakt(url)
			if i['episode']['season'] > 0
		]
		data = [i for n, i in enumerate(data) if i not in data[n + 1:]] # remove duplicates
		return data
	start, finish = trakt_calendar_days(False, current_date)
	string = 'trakt_get_my_calendar_anime_%s_%s' % (start, finish)
	url = {'path': 'calendars/my/shows/%s/%s' % (start, finish), 'params': {'genres': 'anime'}}
	return trakt_cache.cache_trakt_object(_process, string, url)

def trakt_anime_calendar(current_date):
	def _process(dummy):
		data = [
			{'sort_title': '%s s%s e%s' % (i['show']['title'], str(i['episode']['season']).zfill(2), str(i['episode']['number']).zfill(2)),
			'media_ids': i['show']['ids'], 'season': i['episode']['season'], 'episode': i['episode']['number'], 'first_aired': i['first_aired']}
			for i in call_trakt(url)
			if i['episode']['season'] > 0
		]
		data = [i for n, i in enumerate(data) if i not in data[n + 1:]] # remove duplicates
		return data
	start, finish = trakt_calendar_days(False, current_date)
	string = 'trakt_anime_calendar_%s_%s' % (start, finish)
	url = {'path': 'calendars/all/shows/%s/%s' % (start, finish), 'params': {'genres': 'anime'}, 'with_auth': False}
	return trakt_cache.cache_trakt_object(_process, string, url)

def trakt_playback_progress():
	url = 'sync/playback'
	return call_trakt(url)

def trakt_get_activity():
	url = 'sync/last_activities'
	return call_trakt(url)

def trakt_sync_activities_thread(*args, **kwargs):
	Thread(target=trakt_sync_activities, args=args, kwargs=kwargs).start()

def trakt_sync_activities(force_update=False, init_callback=None, monitor=None):
	def _compare(latest, cached):
		try: return latest > cached
		except: return True
	if not get_setting('trakt_user', ''): return 'no account'
	if monitor and monitor.abortRequested(): return
	if callable(init_callback): init_callback()
	elif init_callback is True: trakt_expires()
	else: pass
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
	lists_actions = []
	cached_movies, latest_movies = cached['movies'], latest['movies']
	cached_shows, latest_shows = cached['shows'], latest['shows']
	cached_episodes, latest_episodes = cached['episodes'], latest['episodes']
	cached_lists, latest_lists = cached['lists'], latest['lists']
	if _compare(latest_movies['collected_at'], cached_movies['collected_at']):
		trakt_cache.clear_trakt_collection_watchlist_data('collection', 'movie')
	if _compare(latest_episodes['collected_at'], cached_episodes['collected_at']):
		trakt_cache.clear_trakt_collection_watchlist_data('collection', 'tvshow')
	if _compare(latest_movies['watchlisted_at'], cached_movies['watchlisted_at']):
		trakt_cache.clear_trakt_collection_watchlist_data('watchlist', 'movie')
	if _compare(latest_shows['watchlisted_at'], cached_shows['watchlisted_at']):
		trakt_cache.clear_trakt_collection_watchlist_data('watchlist', 'tvshow')
	if _compare(latest_movies['favorited_at'], cached_movies['favorited_at']):
		trakt_cache.clear_trakt_collection_watchlist_data('favorites', 'movie')
	if _compare(latest_shows['favorited_at'], cached_shows['favorited_at']):
		trakt_cache.clear_trakt_collection_watchlist_data('favorites', 'tvshow')
	if _compare(latest_shows['dropped_at'], cached_shows['dropped_at']):
		trakt_cache.clear_trakt_hidden_data('dropped')
	if _compare(latest_movies['recommendations_at'], cached_movies['recommendations_at']):
		trakt_cache.clear_trakt_recommendations('movies')
	if _compare(latest_shows['recommendations_at'], cached_shows['recommendations_at']):
		trakt_cache.clear_trakt_recommendations('shows')
	if _compare(latest_lists['updated_at'], cached_lists['updated_at']):
		lists_actions.append('my_lists')
	if _compare(latest_lists['liked_at'], cached_lists['liked_at']):
		lists_actions.append('liked_lists')
	if lists_actions:
		for item in lists_actions:
			trakt_cache.clear_trakt_list_data(item)
			trakt_cache.clear_trakt_list_contents_data(item)
	if _compare(latest_movies['watched_at'], cached_movies['watched_at']): trakt_indicators_movies()
	if _compare(latest_episodes['watched_at'], cached_episodes['watched_at']): trakt_indicators_tv()
	refresh_movies_progress = _compare(latest_movies['paused_at'], cached_movies['paused_at'])
	refresh_shows_progress = _compare(latest_episodes['paused_at'], cached_episodes['paused_at'])
	if refresh_movies_progress or refresh_shows_progress:
		progress_info = trakt_playback_progress()
		if refresh_movies_progress: trakt_progress_movies(progress_info)
		if refresh_shows_progress: trakt_progress_tv(progress_info)
	return 'success'

