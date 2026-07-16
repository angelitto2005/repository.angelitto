import requests
from threading import Thread
from concurrent.futures import ThreadPoolExecutor
from caches.main_cache import cache_object
from caches.meta_cache import cache_function
from modules import kodi_utils
from modules.settings import get_language, show_unaired_watchlist, ignore_articles, lists_sort_order, paginate, page_limit
from modules.utils import paginate_list, sort_for_article, jsondate_to_datetime, get_datetime, chunks, TaskPool

ls, logger = kodi_utils.local_string, kodi_utils.logger
get_setting, set_setting = kodi_utils.get_setting, kodi_utils.set_setting
EXPIRES_4_HOURS, EXPIRES_2_DAYS, EXPIRES_1_WEEK, EXPIRES_1_MONTH = 4, 48, 168, 672
READ_TOKEN = kodi_utils.addon().getSetting('tmdb_read_token')
movies_append = 'external_ids,videos,credits,release_dates,alternative_titles,translations,images'
tvshows_append = 'external_ids,videos,credits,content_ratings,alternative_titles,translations,images'
tmdb_image_base, tmdblist_heading = 'https://image.tmdb.org/t/p/%s%s', 'TMDB Lists'
list_url = 'https://api.themoviedb.org/4'
base_url = 'https://api.themoviedb.org/3'
timeout = 3.05
session = requests.Session()
retry = requests.adapters.Retry(total=None, status=1, status_forcelist=(429, 502, 503, 504))
session.mount('https://api.themoviedb.org', requests.adapters.HTTPAdapter(pool_maxsize=100, max_retries=retry))

def get_tmdb(url):
	try:
		response = session.get(url, headers={'Authorization': 'Bearer %s' % READ_TOKEN}, timeout=timeout)
		result = response.json() if 'json' in response.headers.get('Content-Type', '') else response.text
		if not response.ok: response.raise_for_status()
		return result
	except requests.RequestException as e:
		logger('tmdb error', str(e))

def tmdb_keyword_id(query):
	string = 'tmdb_keyword_id_%s' % query
	url = '%s/search/keyword?query=%s' % (base_url, query)
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_1_WEEK)

def tmdb_company_id(query):
	string = 'tmdb_company_id_%s' % query
	url = '%s/search/company?query=%s' % (base_url, query)
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_1_WEEK)

def tmdb_media_images(mediatype, tmdb_id):
	if mediatype == 'movies': mediatype = 'movie'
	string = 'tmdb_media_images_%s_%s' % (mediatype, tmdb_id)
	url = '%s/%s/%s/images' % (base_url, mediatype, tmdb_id)
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_1_WEEK)

def tmdb_media_videos(mediatype, tmdb_id):
	if mediatype == 'movies': mediatype = 'movie'
	if mediatype in ('tvshow', 'tvshows'): mediatype = 'tv'
	string = 'tmdb_media_videos_%s_%s' % (mediatype, tmdb_id)
	url = '%s/%s/%s/videos' % (base_url, mediatype, tmdb_id)
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_1_WEEK)

def tmdb_movies_discover(query, page_no):
	string = query % page_no
	url = query % page_no
	return cache_object(get_tmdb, string, url)

def tmdb_movies_collection(collection_id):
	string = 'tmdb_movies_collection_%s' % collection_id
	url = '%s/collection/%s?language=en-US' % (base_url, collection_id)
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_1_WEEK)

def tmdb_movies_title_year(title, year=None):
	if year:
		string = 'tmdb_movies_title_year_%s_%s' % (title, year)
		url = '%s/search/movie?language=en-US&query=%s&year=%s' % (base_url, title, year)
	else:
		string = 'tmdb_movies_title_year_%s' % title
		url = '%s/search/movie?language=en-US&query=%s' % (base_url, title)
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_1_MONTH)

def tmdb_oscar_winners(page_no):
	from modules.meta_lists import oscar_winners
	results = [[{'id': x} for x in i] for i in chunks(oscar_winners, 20)]
	return {'page': page_no, 'total_pages': len(results), 'results': results[page_no - 1]}

def tmdb_movies_popular(page_no):
	string = 'tmdb_movies_popular_%s' % page_no
	url = '%s/discover/movie?with_original_language=en&language=en-US&region=US&page=%s' % (base_url, page_no)
	url += '&sort_by=popularity.desc'
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_2_DAYS)

def tmdb_movies_blockbusters(page_no):
	string = 'tmdb_movies_blockbusters_%s' % page_no
	url = '%s/discover/movie?language=en-US&region=US&page=%s&sort_by=revenue.desc' % (base_url, page_no)
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_2_DAYS)

def tmdb_movies_premieres(page_no):
	current_date, previous_date = get_dates(31, reverse=True)
	string = 'tmdb_movies_premieres_%s' % page_no
	url = '%s/discover/movie?language=en-US&region=US&page=%s' % (base_url, page_no)
	url += '&with_release_type=1|3|2&release_date.gte=%s&release_date.lte=%s' % (previous_date, current_date)
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_2_DAYS)

def tmdb_movies_latest_releases(page_no):
	current_date, previous_date = get_dates(31, reverse=True)
	string = 'tmdb_movies_latest_releases_%s' % page_no
	url = '%s/discover/movie?language=en-US&region=US&page=%s' % (base_url, page_no)
	url += '&with_release_type=4|5&release_date.gte=%s&release_date.lte=%s' % (previous_date, current_date)
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_2_DAYS)

def tmdb_movies_upcoming(page_no):
	current_date, future_date = get_dates(31, reverse=False)
	string = 'tmdb_movies_upcoming_%s' % page_no
	url = '%s/discover/movie?language=en-US&region=US&page=%s' % (base_url, page_no)
	url += '&with_release_type=3|2|1&release_date.gte=%s&release_date.lte=%s' % (current_date, future_date)
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_2_DAYS)

def tmdb_movies_genres(genre_id, page_no):
	string = 'tmdb_movies_genres_%s_%s' % (genre_id, page_no)
	url = '%s/discover/movie?language=en-US&region=US&page=%s&with_genres=%s&sort_by=popularity.desc' % (base_url, page_no, genre_id)
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_2_DAYS)

def tmdb_movies_year(year, page_no):
	string = 'tmdb_movies_year_%s_%s' % (year, page_no)
	url = '%s/discover/movie?language=en-US&region=US&page=%s' % (base_url, page_no)
	url += '&sort_by=popularity.desc&certification_country=US&primary_release_year=%s' % year
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_2_DAYS)

def tmdb_movies_networks(network_id, page_no):
	string = 'tmdb_movies_networks_%s_%s' % (network_id, page_no)
	url = '%s/discover/movie?language=en-US&region=US&page=%s' % (base_url, page_no)
	url += '&sort_by=popularity.desc&certification_country=US&with_companies=%s' % network_id
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_2_DAYS)

def tmdb_movies_similar(tmdb_id, page_no):
	string = 'tmdb_movies_similar_%s_%s' % (tmdb_id, page_no)
	url = '%s/movie/%s/similar?language=en-US&page=%s' % (base_url, tmdb_id, page_no)
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_2_DAYS)

def tmdb_movies_recommendations(tmdb_id, page_no):
	string = 'tmdb_movies_recommendations_%s_%s' % (tmdb_id, page_no)
	url = '%s/movie/%s/recommendations?language=en-US&page=%s' % (base_url, tmdb_id, page_no)
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_2_DAYS)

def tmdb_movies_search(query, page_no):
	string = 'tmdb_movies_search_%s_%s' % (query, page_no)
	url = '%s/search/movie?language=en-US&query=%s&page=%s' % (base_url, query, page_no)
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_4_HOURS)

def tmdb_movies_search_collections(query, page_no):
	string = 'tmdb_movies_search_collections_%s_%s' % (query, page_no)
	url = '%s/search/collection?language=en-US&query=%s&page=%s' % (base_url, query, page_no)
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_1_WEEK)

def tmdb_tv_discover(query, page_no):
	string = url = query % page_no
	return cache_object(get_tmdb, string, url)

def tmdb_tv_title_year(title, year=None):
	if year:
		string = 'tmdb_tv_title_year_%s_%s' % (title, year)
		url = '%s/search/tv?query=%s&first_air_date_year=%s&language=en-US' % (base_url, title, year)
	else:
		string = 'tmdb_tv_title_year_%s' % title
		url = '%s/search/tv?query=%s&language=en-US' % (base_url, title)
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_1_MONTH)

def tmdb_tv_popular(page_no):
	string = 'tmdb_tv_popular_%s' % page_no
	url = '%s/discover/tv?with_original_language=en&language=en-US&region=US&page=%s' % (base_url, page_no)
	url += '&sort_by=popularity.desc&without_genres=10763,10767'
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_2_DAYS)

def tmdb_tv_premieres(page_no):
	current_date, previous_date = get_dates(31, reverse=True)
	string = 'tmdb_tv_premieres_%s' % page_no
	url = '%s/discover/tv?with_original_language=en&language=en-US&region=US&page=%s' % (base_url, page_no)
	url += '&sort_by=popularity.desc&first_air_date.gte=%s&first_air_date.lte=%s' % (previous_date, current_date)
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_2_DAYS)

def tmdb_tv_upcoming(page_no):
	current_date, future_date = get_dates(31, reverse=False)
	string = 'tmdb_tv_upcoming_%s' % page_no
	url = '%s/discover/tv?with_original_language=en&language=en-US&region=US&page=%s' % (base_url, page_no)
	url += '&sort_by=popularity.desc&first_air_date.gte=%s&first_air_date.lte=%s' % (current_date, future_date)
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_2_DAYS)

def tmdb_tv_genres(genre_id, page_no):
	string = 'tmdb_tv_genres_%s_%s' % (genre_id, page_no)
	url = '%s/discover/tv?page=%s' % (base_url, page_no)
	url += '&with_genres=%s&sort_by=popularity.desc&include_null_first_air_dates=false' % genre_id
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_2_DAYS)

def tmdb_tv_year(year, page_no):
	string = 'tmdb_tv_year_%s_%s' % (year, page_no)
	url = '%s/discover/tv?language=en-US&region=US&page=%s' % (base_url, page_no)
	url += '&sort_by=popularity.desc&include_null_first_air_dates=false&first_air_date_year=%s' % year
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_2_DAYS)

def tmdb_tv_networks(network_id, page_no):
	string = 'tmdb_tv_networks_%s_%s' % (network_id, page_no)
	url = '%s/discover/tv?language=en-US&region=US&page=%s' % (base_url, page_no)
	url += '&sort_by=popularity.desc&include_null_first_air_dates=false&with_networks=%s' % network_id
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_2_DAYS)

def tmdb_tv_similar(tmdb_id, page_no):
	string = 'tmdb_tv_similar_%s_%s' % (tmdb_id, page_no)
	url = '%s/tv/%s/similar?language=en-US&page=%s' % (base_url, tmdb_id, page_no)
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_2_DAYS)

def tmdb_tv_recommendations(tmdb_id, page_no):
	string = 'tmdb_tv_recommendations_%s_%s' % (tmdb_id, page_no)
	url = '%s/tv/%s/recommendations?language=en-US&page=%s' % (base_url, tmdb_id, page_no)
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_2_DAYS)

def tmdb_tv_search(query, page_no):
	string = 'tmdb_tv_search_%s_%s' % (query, page_no)
	url = '%s/search/tv?language=en-US&query=%s&page=%s' % (base_url, query, page_no)
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_4_HOURS)

def tmdb_moviesanime_popular(page_no):
	string = 'tmdb_moviesanime_popular_%s' % page_no
	url = '%s/discover/movie?page=%s&with_keywords=%s&sort_by=popularity.desc' % (base_url, page_no, '210024')
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_2_DAYS)

def tmdb_moviesanime_latest_releases(page_no):
	current_date, previous_date = get_dates(181, reverse=True)
	string = 'tmdb_moviesanime_latest_releases_%s' % page_no
	url = '%s/discover/movie?page=%s&with_keywords=%s&with_release_type=4|5' % (base_url, page_no, '210024')
	url += '&sort_by=primary_release_date.desc&release_date.gte=%s&release_date.lte=%s' % (previous_date, current_date)
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_2_DAYS)

def tmdb_moviesanime_genres(genre_id, page_no):
	string = 'tmdb_moviesanime_genres_%s_%s' % (genre_id, page_no)
	url = '%s/discover/movie?page=%s&with_keywords=%s&with_genres=%s&sort_by=popularity.desc' % (base_url, page_no, '210024', genre_id)
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_2_DAYS)

def tmdb_moviesanime_year(year, page_no):
	string = 'tmdb_moviesanime_year_%s_%s' % (year, page_no)
	url = '%s/discover/movie?page=%s&with_keywords=%s' % (base_url, page_no, '210024')
	url += '&sort_by=popularity.desc&certification_country=US&primary_release_year=%s' % year
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_2_DAYS)

def tmdb_tvanime_popular(page_no):
	string = 'tmdb_tvanime_popular_%s' % page_no
	url = '%s/discover/tv?page=%s&with_keywords=%s&sort_by=popularity.desc' % (base_url, page_no, '210024')
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_2_DAYS)

def tmdb_tvanime_premieres(page_no):
	current_date, previous_date = get_dates(181, reverse=True)
	string = 'tmdb_tvanime_premieres_%s' % page_no
	url = '%s/discover/tv?page=%s&with_keywords=%s' % (base_url, page_no, '210024')
	url += '&sort_by=first_air_date.desc&first_air_date.gte=%s&first_air_date.lte=%s' % (previous_date, current_date)
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_2_DAYS)

def tmdb_tvanime_genres(genre_id, page_no):
	string = 'tmdb_tvanime_genres_%s_%s' % (genre_id, page_no)
	url = '%s/discover/tv?page=%s&with_keywords=%s' % (base_url, page_no, '210024')
	url += '&sort_by=popularity.desc&include_null_first_air_dates=false&with_genres=%s' % genre_id
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_2_DAYS)

def tmdb_tvanime_year(year, page_no):
	string = 'tmdb_tvanime_year_%s_%s' % (year, page_no)
	url = '%s/discover/tv?page=%s&with_keywords=%s' % (base_url, page_no, '210024')
	url += '&sort_by=popularity.desc&include_null_first_air_dates=false&first_air_date_year=%s' % year
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_2_DAYS)

def tmdb_popular_people(page_no):
	string = 'tmdb_popular_people_%s' % page_no
	url = '%s/person/popular?language=en-US&page=%s' % (base_url, page_no)
	return cache_object(get_tmdb, string, url)

def tmdb_people_full_info(actor_id, language=None):
	if not language: language = get_language()
	string = 'tmdb_people_full_info_%s_%s' % (actor_id, language)
	url = '%s/person/%s?language=%s' % (base_url, actor_id, language)
	url += '&append_to_response=external_ids,combined_credits,images,tagged_images'
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_1_WEEK)

def tmdb_people_info(query):
	string = 'tmdb_people_info_%s' % query
	url = '%s/search/person?language=en-US&query=%s' % (base_url, query)
	return cache_object(get_tmdb, string, url, expiration=EXPIRES_4_HOURS)['results']

def get_dates(days, reverse=True):
	import datetime
	current_date = datetime.date.today()
	if reverse: new_date = (current_date - datetime.timedelta(days=days)).strftime('%Y-%m-%d')
	else: new_date = (current_date + datetime.timedelta(days=days)).strftime('%Y-%m-%d')
	return str(current_date), new_date

def tmdb_image_params(language):
	return ','.join(dict.fromkeys([language, language.split('-')[0], 'en,en-US,null']))

def movie_details(tmdb_id, language):
	try:
		url = '%s/movie/%s?language=%s&append_to_response=%s' % (base_url, tmdb_id, language, movies_append)
		if language not in 'en,en-US': url += '&include_image_language=%s' % tmdb_image_params(language)
		return get_tmdb(url)
	except: return None

def tvshow_details(tmdb_id, language):
	try:
		url = '%s/tv/%s?language=%s&append_to_response=%s' % (base_url, tmdb_id, language, tvshows_append)
		if language not in 'en,en-US': url += '&include_image_language=%s' % tmdb_image_params(language)
		return get_tmdb(url)
	except: return None

def season_episodes_details(tmdb_id, season_no, language):
	try:
		url = '%s/tv/%s/season/%s?language=%s&append_to_response=credits' % (base_url, tmdb_id, season_no, language)
		return get_tmdb(url)
	except: return None

def movie_external_id(external_source, external_id):
	try:
		string = 'movie_external_id_%s_%s' % (external_source, external_id)
		url = '%s/find/%s?external_source=%s' % (base_url, external_id, external_source)
		result = cache_function(get_tmdb, string, url, EXPIRES_1_MONTH)
		result = result['movie_results']
		if result: return result[0]
		else: return None
	except: return None

def tvshow_external_id(external_source, external_id):
	try:
		string = 'tvshow_external_id_%s_%s' % (external_source, external_id)
		url = '%s/find/%s?external_source=%s' % (base_url, external_id, external_source)
		result = cache_function(get_tmdb, string, url, EXPIRES_1_MONTH)
		result = result['tv_results']
		if result: return result[0]
		else: return None
	except: return None

def movie_keywords(tmdb_id):
	try:
		url = '%s/movie/%s/keywords' % (base_url, tmdb_id)
		result = get_tmdb(url)
		result = result['keywords']
		return result
	except: return None

def english_translation(mediatype, tmdb_id):
	try:
		string = 'english_translation_%s_%s' % (mediatype, tmdb_id)
		url = '%s/%s/%s/translations' % (base_url, mediatype, tmdb_id)
		result = cache_function(get_tmdb, string, url, EXPIRES_1_WEEK * 52)
		try: result = result['translations']
		except: result = None
		return result
	except: return None

def episode_groups(tmdb_id):
	def _process(dummy):
		eps_map = (dummy, 'Original air date', 'Absolute', 'DVD', 'Digital', 'Story arc', 'Production', 'TV')
		result = get_tmdb(url)['results']
		for i in result: i['type'] = eps_map[i['type']]
		return result
	string = 'tmdb_episode_group_%s' % tmdb_id
	url = '%s/tv/%s/episode_groups' % (base_url, tmdb_id)
	return cache_function(_process, string, url, EXPIRES_1_WEEK)

def episode_group_details(group_id):
	def _process(dummy):
		result = get_tmdb(url)
		result['groups'].sort(key=lambda k: k['order'])
		return result['groups']
	string = 'tmdb_episode_group_details_%s' % group_id
	url = '%s/tv/episode_group/%s' % (base_url, group_id)
	return cache_function(_process, string, url, EXPIRES_1_WEEK)

def tmdb_region_ids():
	def _process(dummy):
		region_list = (
			'AF,AL,DZ,AQ,AR,AM,AU,AT,BD,BY,BE,BR,BG,KH,CA,CL,CN,HR,CZ,DK,EG,FI,FR,DE,'
			'GR,HK,HU,IS,IN,ID,IR,IQ,IE,IL,IT,JP,MY,NP,NL,NZ,NO,PK,PY,PE,PH,PL,PT,PR,'
			'RO,RU,SA,RS,SG,SK,SI,ZA,ES,LK,SE,CH,TH,TR,UA,AE,GB,US,UY,VE,VN,YE,ZW'
		)
		return sorted((
			{'code': i['iso_3166_1'], 'name': i['english_name']}
			for i in get_tmdb(url) if i['iso_3166_1'] in region_list
		), key=lambda k: k['name'])
	string = 'tmdb_region_ids'
	url = '%s/configuration/countries' % base_url
	return cache_object(_process, string, url, expiration=EXPIRES_1_MONTH)

def get_tmdblist(url, params=None, data=None, method=None):
	if isinstance(url, dict): return get_tmdblist(str(url.pop('path')), **url)
	else: url = str(url)
	if params and 'token' in params: token = params.pop('token')
	else: token = get_setting('tmdb.token')
	headers = {'Authorization': 'Bearer %s' % token}
	method = method or 'get'
	list_timeout=timeout ** 2 if method != 'get' else timeout
	try:
		response = session.request(method, url, params=params, json=data, headers=headers, timeout=list_timeout)
		result = response.json() if 'json' in response.headers.get('Content-Type', '') else response.text
		if not response.ok: response.raise_for_status()
		return result
	except requests.RequestException as e:
		logger('tmdb error', str(e))

def _get_tmdblist_paginated_list(url):
	token, account_id = get_setting('tmdb.token'), get_setting('tmdb.account_id')
	if 'account_id' in url: url = url.replace('account_id', account_id)
	params = {'token': token, 'page': 1}
	try:
		result = get_tmdblist(url, params=params)
		items, pages = result['results'], result['total_pages']
	except: return []
	if pages <= 1: return items
	args = ({'path': url, 'params': {**params, 'page': page}} for page in range(2, pages + 1))
	with ThreadPoolExecutor() as tpe: # keep max_workers as default, min(32, os.cpu_count() + 4)
		for result in tpe.map(get_tmdblist, args): # ThreadPoolExecutor map preserves order
			if isinstance(result, dict): items.extend(result['results']) # caution, hides thread exceptions
	return items

def tmdb_watchlist(mediatype, page_no):
	def first_aired(item):
		if not item.get(premiered): return False
		return jsondate_to_datetime(item[premiered]).astimezone().date() <= current_date
	title, premiered = ('title', 'release_date') if mediatype == 'movie' else ('name', 'first_air_date')
	original_list = watchlist(mediatype)
	if not show_unaired_watchlist():
		current_date = get_datetime()
		original_list = [i for i in original_list if first_aired(i)]
	sort_key = lists_sort_order('watchlist')
	if   sort_key == 2: original_list.sort(key=lambda k: k[premiered], reverse=True)
	elif sort_key == 1: pass # api call for list specifies params created_at.desc
	else: original_list = sort_for_article(original_list, title, ignore_articles())
	if paginate(): return paginate_list(original_list, page_no, page_limit())
	return original_list, 1

def tmdb_favorites(mediatype, page_no):
	original_list = favorites(mediatype)
	if paginate(): return paginate_list(original_list, page_no, page_limit())
	return original_list, 1

def tmdb_recommendations(mediatype, page_no):
	original_list = recommendations(mediatype, page_no)
	final_list, total_pages = original_list['results'], original_list['total_pages']
	return final_list, total_pages

def add_to_watchlist_favorites(item, list_type):
	session_account_id = get_setting('tmdb.session_account_id')
	session_id = get_setting('tmdb.session_id')
	params = {'session_id': session_id}
	url = '%s/account/%s/%s' % (base_url, session_account_id, list_type)
	return get_tmdblist(url, params=params, data=item, method='post')

def watchlist(mediatype):
	string = 'tmdblist_watchlist_%s' % mediatype
	url = '%s/account/%s/%s/watchlist' % (list_url, 'account_id', mediatype)
	url += '?language=en-US&sort_by=created_at.desc'
	return cache_object(_get_tmdblist_paginated_list, string, url)

def favorites(mediatype):
	string = 'tmdblist_favorites_%s' % mediatype
	url = '%s/account/%s/%s/favorites' % (list_url, 'account_id', mediatype)
	url += '?language=en-US&sort_by=created_at.desc'
	return cache_object(_get_tmdblist_paginated_list, string, url)

def recommendations(mediatype, page_no=1):
	account_id = get_setting('tmdb.account_id')
	string = 'tmdblist_recommendations_%s_%s_%s' % (account_id, mediatype, page_no)
	url = '%s/account/%s/%s/recommendations' % (list_url, account_id, mediatype)
	url += '?language=en-US&page=%s' % page_no
	return cache_object(get_tmdblist, string, url)

def user_lists():
	sort = int(get_setting('tmdblist.sort_name', '0'))
	string = 'tmdblist_user_lists'
	url = '%s/account/%s/lists' % (list_url, 'account_id')
	result = cache_object(_get_tmdblist_paginated_list, string, url)
	try:
		if   sort == 2: result.sort(key=lambda k: k['updated_at'], reverse=True)
		elif sort == 1: result.sort(key=lambda k: k['number_of_items'], reverse=True)
		else: result.sort(key=lambda k: k['name'].lower(), reverse=False)
	except: pass
	return result

def list_details(list_id):
	string = 'tmdblist_detail_%s' % list_id
	url = '%s/list/%s' % (list_url, list_id)
	return cache_object(_get_tmdblist_paginated_list, string, url)

def list_add_items(list_id, items=None):
	url = '%s/list/%s/items' % (list_url, list_id)
	return get_tmdblist(url, data=items, method='post')

def list_remove_items(list_id, items=None):
	url = '%s/list/%s/items' % (list_url, list_id)
	return get_tmdblist(url, data=items, method='delete')

def list_update(list_id, data):
	url = '%s/list/%s' % (list_url, list_id)
	return get_tmdblist(url, data=data, method='put')

def list_status(list_id, mediatype, media_id):
	params = {'media_type': mediatype, 'media_id': int(media_id)}
	url = '%s/list/%s/item_status' % (list_url, list_id)
	return get_tmdblist(url, params=params)

def list_create(list_name):
	from urllib.parse import unquote
	list_title = list_name or kodi_utils.dialog.input('POV')
	if not list_title: return
	list_name = unquote(list_title)
	data = {'name': list_title, 'public': True, 'iso_3166_1': 'US', 'iso_639_1': 'en'}
	url = '%s/list' % list_url
	return get_tmdblist(url, data=data, method='post')

def list_clear(list_id):
	url = '%s/list/%s/clear' % (list_url, list_id)
	return get_tmdblist(url)

def list_delete(list_id):
	url = '%s/list/%s' % (list_url, list_id)
	return get_tmdblist(url, method='delete')

def tmdb_clean_watchlist(silent=False):
	if not get_setting('tmdb.token'): return
	if not silent and not kodi_utils.confirm_dialog(): return
	try:
		from caches.watched_cache import get_watched_info_movie, get_watched_info_tv
		from modules.settings import watched_indicators
		watched_indicators = watched_indicators()
		watchlist_ids, items = [], []
		watchlist_ids += watchlist('movie')
		watchlist_ids += watchlist('tv')
		watchlist_ids = [str(i['id']) for i in watchlist_ids]
		items += [
			({'watchlist': False, 'media_type': 'movie', 'media_id': int(i)}, 'watchlist')
			for i in get_watched_info_movie(watched_indicators) if i in watchlist_ids
		]
		items += [
			({'watchlist': False, 'media_type': 'tv', 'media_id': int(i)}, 'watchlist')
			for i in get_watched_info_tv(watched_indicators) if i in watchlist_ids
		]
		if not items: return '0 items to remove.'
		for i in TaskPool(40).tasks(add_to_watchlist_favorites, items, Thread): i.join()
		clear_tmdbl_cache()
		if not silent: kodi_utils.notification(32576)
		return '%d items removed.' % len(items)
	except: pass

def clear_tmdbl_cache(silent=False):
	from modules.kodi_utils import path_exists, clear_property, database_connect, maincache_db
	try:
		if not path_exists(maincache_db): return True
		dbcon = database_connect(maincache_db, isolation_level=None)
		dbcur = dbcon.cursor()
		dbcur.execute("""PRAGMA synchronous = OFF""")
		dbcur.execute("""PRAGMA journal_mode = OFF""")
		dbcur.execute("""SELECT id FROM maincache WHERE id LIKE ?""", ('tmdblist_%',))
		tmdb_results = [str(i[0]) for i in dbcur.fetchall()]
		if not tmdb_results: return True
		dbcur.execute("""DELETE FROM maincache WHERE id LIKE ?""", ('tmdblist_%',))
		for i in tmdb_results: clear_property(i)
		return True
	except: return False

