from indexers import tmdb_api
from caches.meta_cache import MetaCache
from modules.utils import jsondate_to_datetime, subtract_dates, TaskPool
# from modules.kodi_utils import logger

EXPIRES_2_DAYS, EXPIRES_4_DAYS, EXPIRES_7_DAYS, EXPIRES_14_DAYS, EXPIRES_182_DAYS = 2, 4, 7, 14, 182
movie_data, tvshow_data = tmdb_api.movie_details, tmdb_api.tvshow_details
season_episodes_details, tmdb_english_translation = tmdb_api.season_episodes_details, tmdb_api.english_translation
movie_external_id, tvshow_external_id = tmdb_api.movie_external_id, tmdb_api.tvshow_external_id
subtract_dates_function, jsondate_to_datetime_function = subtract_dates, jsondate_to_datetime
tmdb_image_base, writer_credits = tmdb_api.tmdb_image_base, ('Author', 'Writer', 'Screenplay', 'Characters')
backup_resolutions = {'poster': 'w780', 'fanart': 'w1280', 'still': 'original', 'profile': 'h632'}
rpdb_themes = {'0': '', '1': '&theme=rounded-blocks', '2': '&theme=blocks'}
alt_titles_test, trailers_test = ('US', 'GB', 'UK', ''), ('Trailer', 'Teaser')
finished_show_check, empty_value_check = ('Ended', 'Canceled'), ('', 'None', None)
youtube_url, date_format = 'plugin://plugin.video.youtube/play/?video_id=%s', '%Y-%m-%d'
infokeys, episodekeys, seasonkeys, videoinfomethods = (
	'country', 'director', 'duration', 'genre', 'imdbnumber', 'mediatype', 'mpaa', 'originaltitle',
	'plot', 'premiered', 'rating', 'studio', 'tag', 'tagline', 'title', 'trailer', 'votes', 'writer', 'year',
	'episode', 'season', 'status', 'tvshowtitle', 'playcount', 'overlay'
), (
	'imdbnumber', 'title', 'tvshowtitle', 'plot', 'mpaa', 'studio', 'director', 'writer', 'duration',
	'premiered', 'genre', 'rating', 'votes', 'country', 'trailer', 'mediatype', 'status', 'season', 'episode',
	'playcount', 'overlay'
), (
	'imdbnumber', 'title', 'tvshowtitle', 'plot', 'mpaa', 'studio', 'premiered', 'genre', 'rating',
	'country', 'trailer', 'mediatype', 'status', 'season', 'playcount', 'overlay'
), (
	('country', 'setCountries'), ('director', 'setDirectors'), ('duration', 'setDuration'), ('genre', 'setGenres'),
	('imdbnumber', 'setIMDBNumber'), ('mediatype', 'setMediaType'), ('mpaa', 'setMpaa'), ('originaltitle', 'setOriginalTitle'),
	('playcount', 'setPlaycount'), ('plot', 'setPlot'), ('premiered', 'setPremiered'),
	('rating', 'setRating'), ('studio', 'setStudios'), ('tagline', 'setTagLine'), ('title', 'setTitle'),
	('trailer', 'setTrailer'), ('votes', 'setVotes'), ('writer', 'setWriters'), ('year', 'setYear'),
	('episode', 'setEpisode'), ('season', 'setSeason'), ('status', 'setTvShowStatus'), ('tvshowtitle', 'setTvShowTitle')
)

def art_infodict(meta, art_provider, meta_user_info, extra_art=None):
	meta_get = meta.get
	tmdb_id, imdb_id = meta_get('tmdb_id'), meta_get('imdb_id')
	poster_main, poster_backup, fanart_main, fanart_backup, poster_empty, fanart_empty = art_provider
	poster = meta_get(poster_main) or meta_get(poster_backup) or poster_empty
	fanart = meta_get(fanart_main) or meta_get(fanart_backup) or fanart_empty
	clearlogo = meta_get('clearlogo') or ''
	banner, clearart, landscape, discart = '', '', '', ''
	if meta_user_info['extra_rpdb_movies' if meta_get('mediatype') == 'movie' else 'extra_rpdb_series']:
		key = 'movie' if meta_get('mediatype') == 'movie' else 'series'
		args = meta_user_info['rpdb_api_key'], meta_user_info['rpdb_theme']
		poster = rpdb_get(key, imdb_id or str(tmdb_id), *args) or poster
	art = {
		'poster': poster, 'fanart': fanart, 'icon': poster, 'clearlogo': clearlogo,
		'banner': banner, 'clearart': clearart, 'landscape': landscape, 'discart': discart
	}
	if meta_get('mediatype') == 'movie': return art
	art.update({
		'tvshow.poster': poster, 'tvshow.clearlogo': clearlogo,
		'tvshow.banner': banner, 'tvshow.clearart': clearart, 'tvshow.landscape': landscape
	})
	if not extra_art: return art
	if extra_art.get('background') or False:
		art['fanart'] = extra_art.get('background') or fanart
	if extra_art.get('season_poster') or False:
		art.update(dict.fromkeys(('season.poster', 'poster'), extra_art.get('season_poster') or poster))
	if extra_art.get('thumb') or False:
		art.update(dict.fromkeys(('thumb', 'icon', 'landscape', 'tvshow.landscape'), extra_art.get('thumb')))
	return art

def movie_show_infodict(meta):
	obj = {k: v for k in infokeys if (v := meta.get(k))}
	if meta.get('mediatype') in ('movie', 'tvshow'):
		obj['originaltitle'] = meta.get('original_title')
	obj['tag'] = [
		str(tag) for i in ('imdb_id', 'tmdb_id', 'tvdb_id')
		if not (tag := meta.get(i)) in ('', 'None', None)
	]
	return obj

def episode_infodict(meta, **kwargs):
	obj = {k: v for k in episodekeys if (v := meta.get(k))}
	obj.update({k: v for k, v in kwargs.items() if k in episodekeys})
	obj['mediatype'] = 'episode'
	return obj

def season_infodict(meta, **kwargs):
	obj = {k: v for k in seasonkeys if (v := meta.get(k))}
	obj.update({k: v for k, v in kwargs.items() if k in seasonkeys})
	obj['mediatype'] = 'season'
	obj['premiered'] = kwargs['air_date']
	obj['rating'] = kwargs['vote_average']
	obj['season'] = kwargs['season_number']
	obj['title'] = kwargs['name']
	return obj

def info_tagger(listitem, meta=None):
	infotag = listitem.getVideoInfoTag(offscreen=True)
	if not meta: return infotag
	for key, val in videoinfomethods:
		try:
			if not key in meta or not (arg := meta[key]): continue
			if   key == 'premiered' and 'episode' in meta: val = 'setFirstAired'
			if   key in {'episode', 'season', 'year'}: arg = int(arg)
			elif key in {'director', 'genre', 'studio', 'writer'}: arg = arg.split(', ')
			getattr(infotag, val)(arg)
		except: pass
	return infotag

def movie_meta(id_type, media_id, user_info, current_date):
	if id_type == 'trakt_dict':
		if media_id.get('tmdb'): id_type, media_id = 'tmdb_id', media_id['tmdb']
		elif media_id.get('imdb'): id_type, media_id = 'imdb_id', media_id['imdb']
		else: id_type, media_id = None, None
	if media_id is None: return {}
	metacache = MetaCache()
	metacache_get, metacache_set = metacache.get, metacache.set
	meta = metacache_get('movie', id_type, media_id)
	if meta: return meta
	try:
		tmdb_api, language = user_info['tmdb_api'], user_info['language']
		if id_type == 'tmdb_id' or id_type == 'imdb_id':
			data = movie_data(media_id, language, tmdb_api)
		else:
			external_result = movie_external_id(id_type, media_id, tmdb_api)
			if not external_result: data = None
			else: data = movie_data(external_result['id'], language, tmdb_api)
		if not data or data.get('success', True) is False:
			if id_type == 'tmdb_id': meta = {'tmdb_id': media_id, 'imdb_id': 'tt0000000', 'tvdb_id': '0000000', 'fanart_added': True, 'blank_entry': True}
			else: meta = {'tmdb_id': '0000000', 'imdb_id': media_id, 'tvdb_id': '0000000', 'fanart_added': True, 'blank_entry': True}
			metacache_set('movie', id_type, meta, EXPIRES_2_DAYS)
			return meta
		if language != 'en' and data['overview'] in empty_value_check:
			eng_all_trailers = english_trailers('movie', data, tmdb_api)
			if eng_all_trailers: data['videos']['results'] = eng_all_trailers
		meta = build_movie_meta(data, user_info)
		metacache_set('movie', id_type, meta, movie_expiry(current_date, meta))
	except: pass
	return meta

def tvshow_meta(id_type, media_id, user_info, current_date):
	if id_type == 'trakt_dict':
		if media_id.get('tmdb'): id_type, media_id = 'tmdb_id', media_id['tmdb']
		elif media_id.get('imdb'): id_type, media_id = 'imdb_id', media_id['imdb']
		elif media_id.get('tvdb'): id_type, media_id = 'tvdb_id', media_id['tvdb']
		else: id_type, media_id = None, None
	if media_id is None: return {}
	metacache = MetaCache()
	metacache_get, metacache_set = metacache.get, metacache.set
	meta = metacache_get('tvshow', id_type, media_id)
	if meta: return meta
	try:
		tmdb_api, language = user_info['tmdb_api'], user_info['language']
		if id_type == 'tmdb_id':
			data = tvshow_data(media_id, language, tmdb_api)
		else:
			external_result = tvshow_external_id(id_type, media_id, tmdb_api)
			if not external_result: data = None
			else: data = tvshow_data(external_result['id'], language, tmdb_api)
		if not data or data.get('success', True) is False:
			if id_type == 'tmdb_id': meta = {'tmdb_id': media_id, 'imdb_id': 'tt0000000', 'tvdb_id': '0000000', 'fanart_added': True, 'blank_entry': True}
			elif id_type == 'imdb_id': meta = {'tmdb_id': '0000000', 'imdb_id': media_id, 'tvdb_id': '0000000', 'fanart_added': True, 'blank_entry': True}
			else: meta = {'tmdb_id': '0000000', 'imdb_id': 'tt0000000', 'tvdb_id': media_id, 'fanart_added': True, 'blank_entry': True}
			metacache_set('tvshow', id_type, meta, EXPIRES_2_DAYS)
			return meta
		if language != 'en' and data['overview'] in empty_value_check:
			eng_all_trailers = english_trailers('tvshow', data, tmdb_api)
			if eng_all_trailers: data['videos']['results'] = eng_all_trailers
		meta = build_tvshow_meta(data, user_info)
		metacache_set('tvshow', id_type, meta, tvshow_expiry(current_date, meta))
	except: pass
	return meta

def season_episodes_meta(season, meta, user_info):
	def _process():
		for ep_data in data:
			writer, director, guest_stars = '', '', []
			ep_data_get = ep_data.get
			title, plot, premiered = ep_data_get('name'), ep_data_get('overview'), ep_data_get('air_date')
			season, episode, ep_type = ep_data_get('season_number'), ep_data_get('episode_number'), ep_data_get('episode_type')
			rating, votes, still_path = ep_data_get('vote_average'), ep_data_get('vote_count'), ep_data_get('still_path')
			ep_type = ep_details.get(ep_type) or ep_details.get(episode) or ep_type or ''
			if ep_type == 'mid_season_finale': ep_details[episode + 1] = 'mid_season_premiere'
			poster = season_posters.get(int(season)) or ''
			if still_path: thumb = tmdb_image_base % (still_resolution, still_path)
			else: thumb = ''
			try: duration = ep_data_get('runtime') * 60
			except: duration = 0
			guest_stars_list = ep_data_get('guest_stars')
			if guest_stars_list:
				try: guest_stars = [
					{'name': i['name'], 'role': i['character'], 'thumbnail': tmdb_image_base % (profile_resolution, i['profile_path']) if i['profile_path'] else ''}
					for i in guest_stars_list
				]
				except: pass
			crew = ep_data_get('crew')
			if crew:
				try: writer = ', '.join([i['name'] for i in crew if i['job'] in writer_credits])
				except: pass
				try: director = [i['name'] for i in crew if i['job'] == 'Director'][0]
				except: pass
			yield {
				'season_poster': poster, 'thumb': thumb, 'guest_stars': guest_stars, 'director': director,
				'writer': writer, 'plot': plot, 'title': title, 'premiered': premiered,
				'rating': rating, 'votes': votes, 'duration': duration, 'episode_type': ep_type,
				'mediatype': 'episode', 'season': season, 'episode': episode
			}
	image_resolution = user_info.get('image_resolution', backup_resolutions)
	metacache = MetaCache()
	metacache_get, metacache_set = metacache.get, metacache.set
	media_id, data = meta['tmdb_id'], None
	string = '%s_%s' % (media_id, season)
	data = metacache_get('season', 'tmdb_id', string)
	if data: return data
	try: season_posters = {
		i['season_number']: tmdb_image_base % (image_resolution['poster'], i['poster_path']) if i['poster_path'] else ''
		for i in meta.get('season_data')
		if 'poster_path' in i
	}
	except: season_posters = {}
	try:
		show_ended, total_seasons = meta['status'] in finished_show_check, meta['total_seasons']
		expiration = EXPIRES_182_DAYS if show_ended or total_seasons > int(season) else EXPIRES_4_DAYS
		premiere = 'series_premiere' if int(season) == 1 else 'season_premiere'
		finale = 'series_finale' if show_ended and int(season) == total_seasons else 'season_finale'
		ep_details = {1: premiere, 'mid_season': 'mid_season_finale', 'finale': finale}
		still_resolution, profile_resolution = image_resolution['still'], image_resolution['profile']
		data = season_episodes_details(media_id, season, user_info['language'], user_info['tmdb_api'])['episodes']
		data = list(_process())
		metacache_set('season', 'tmdb_id', data, expiration, string)
	except: pass
	return data

def all_episodes_meta(meta, user_info, Thread):
	def _get_tmdb_episodes(season):
		try: data.extend(season_episodes_meta(season, meta, user_info))
		except: pass
	try:
		data = []
		seasons = [(i['season_number'],) for i in meta['season_data']] # TaskPool requires tuple
		for i in TaskPool().tasks(_get_tmdb_episodes, seasons, Thread): i.join()
	except: pass
	return data

def english_trailers(mediatype, data, tmdb_api):
	media_id, id_type = data['id'], 'tmdb_id'
	if mediatype == 'tvshow': eng_data = tvshow_data(media_id, 'en', tmdb_api)
	else: eng_data = movie_data(media_id, 'en', tmdb_api)
	eng_overview = eng_data['overview']
	data['overview'] = eng_overview
	if 'videos' in data:
		all_trailers = data['videos']['results']
		if all_trailers:
			try: trailer_test = [i for i in all_trailers if i['site'] == 'YouTube' and i['type'] in trailers_test]
			except: trailer_test = False
		else: trailer_test = False
	else: trailer_test = False
	if not trailer_test:
		if 'videos' in eng_data:
			eng_all_trailers = eng_data['videos']['results']
			if eng_all_trailers: return eng_all_trailers
	return None

def english_translation(mediatype, media_id, user_info):
	key = 'title' if mediatype == 'movie' else 'name'
	translations = tmdb_english_translation(mediatype, media_id, user_info['tmdb_api'])
	try: english = [i['data'][key] for i in translations if i['iso_639_1'] == 'en'][0]
	except: english = ''
	return english

def movie_expiry(current_date, meta):
	try:
		difference = subtract_dates_function(current_date, jsondate_to_datetime_function(meta['premiered'], date_format, remove_time=True))
		if difference < 0: expiration = abs(difference) + 1
		elif difference <= 14: expiration = EXPIRES_7_DAYS
		elif difference <= 30: expiration = EXPIRES_14_DAYS
		else: expiration = EXPIRES_182_DAYS
	except: return EXPIRES_7_DAYS
	return max(expiration, EXPIRES_7_DAYS)

def tvshow_expiry(current_date, meta):
	try:
		if meta['status'] in finished_show_check: return EXPIRES_182_DAYS
		next_episode_to_air = meta['extra_info'].get('next_episode_to_air')
		if not next_episode_to_air: return EXPIRES_7_DAYS
		expiration = subtract_dates_function(jsondate_to_datetime_function(next_episode_to_air['air_date'], date_format, remove_time=True), current_date)
	except: return EXPIRES_4_DAYS
	return max(expiration, EXPIRES_4_DAYS)

def get_title(meta, language=None):
	if 'custom_title' in meta: return meta['custom_title']
	if not language: language = meta.get('meta_language', '')
	title = meta['title'] if language == 'en' else meta.get('english_title')
	if not title:
		try:
			from settings import metadata_user_info
			mediatype = 'movie' if meta['mediatype'] == 'movie' else 'tv'
			english_title = tmdb_english_translation(mediatype, meta['tmdb_id'], metadata_user_info())
			title = english_title if english_title else meta['original_title']
		except: pass
	if not title: title = meta['original_title']
	if '(' in title: title = title.split('(')[0]
	if '/' in title: title = title.replace('/', ' ')
	return title

def build_movie_meta(data, user_info):
	image_resolution, language = user_info.get('image_resolution', backup_resolutions), user_info['language']
	data_get = data.get
	cast, all_trailers, country, country_codes = [], [], [], []
	mpaa, trailer, writer, director, studio = '', '', '', '', ''
	tmdb_id, imdb_id = data_get('id', ''), data_get('imdb_id', '')
	rating, votes = data_get('vote_average', ''), data_get('vote_count', '')
	plot, tagline, premiered = data_get('overview', ''), data_get('tagline', ''), data_get('release_date', '')
	poster_path, backdrop_path = data_get('poster_path'), data_get('backdrop_path')
	logo_path = next((i['file_path'] for i in data['images'].get('logos', []) if i['file_path'].endswith('png')), None)
	if not language in 'en,en-US':
		try:
			path = (i['file_path'] for i in data['images']['logos'] if str(i['iso_639_1']) in language and i['file_path'].endswith('png'))
			logo_path = next(path)
		except: pass
	if poster_path: poster = tmdb_image_base % (image_resolution['poster'], poster_path)
	else: poster = ''
	if backdrop_path: fanart = tmdb_image_base % (image_resolution['fanart'], backdrop_path)
	else: fanart = ''
	if logo_path: tmdblogo = tmdb_image_base % (image_resolution['fanart'], logo_path)
	else: tmdblogo = ''
	title, original_title = data_get('title'), data_get('original_title')
	try: english_title = [i['data']['title'] for i in data_get('translations')['translations'] if i['iso_639_1'] == 'en'][0]
	except: english_title = None
	try: year = str(data_get('release_date').split('-')[0] or 0)
	except: year = ''
	try: duration = data_get('runtime') * 60
	except: duration = 0
	try: genre = ', '.join([i['name'] for i in data_get('genres')])
	except: genre = ''
	rootname = '%s (%s)' % (title, year)
	companies = data_get('production_companies')
	if companies:
		if not len(companies) == 1:
			try:
				studio = [i['name'] for i in companies if i['logo_path'] not in empty_value_check][0]
				if not studio: studio = [i['name'] for i in companies][0]
			except: pass
		else: studio = [i['name'] for i in companies][0]
	production_countries = data_get('production_countries')
	if production_countries:
		country = [i['name'] for i in production_countries]
		country_codes = [i['iso_3166_1'] for i in production_countries]
	release_dates = data_get('release_dates')
	if release_dates:
		try: mpaa = [
			x['certification']
			for i in release_dates['results']
			for x in i['release_dates']
			if i['iso_3166_1'] == 'US' and x['certification']
		][0]
		except: pass
	credits = data_get('credits')
	if credits:
		all_cast = credits.get('cast')
		if all_cast:
			try: cast = [
				{'name': i['name'], 'role': i['character'], 'thumbnail': tmdb_image_base % (image_resolution['profile'], i['profile_path']) if i['profile_path'] else ''}
				for i in all_cast
			]
			except: pass
		crew = credits.get('crew')
		if crew:
			try: writer = ', '.join([i['name'] for i in crew if i['job'] in writer_credits])
			except: pass
			try: director = [i['name'] for i in crew if i['job'] == 'Director'][0]
			except: pass
	alternative_titles = data_get('alternative_titles')
	if alternative_titles:
		alternatives = alternative_titles['titles']
		alternative_titles = [i['title'] for i in alternatives if i['iso_3166_1'] in alt_titles_test]
	videos = data_get('videos')
	if videos:
		all_trailers = videos['results']
		try: trailer = [youtube_url % i['key'] for i in all_trailers if i['site'] == 'YouTube' and i['type'] in trailers_test][0]
		except: pass
	status, homepage = data_get('status', 'N/A'), data_get('homepage', 'N/A')
	belongs_to_collection = data_get('belongs_to_collection')
	if belongs_to_collection: ei_collection_name, ei_collection_id = belongs_to_collection['name'], belongs_to_collection['id']
	else: ei_collection_name, ei_collection_id = None, None
	try: ei_budget = '${:,}'.format(data_get('budget'))
	except: ei_budget = '$0'
	try: ei_revenue = '${:,}'.format(data_get('revenue'))
	except: ei_revenue = '$0'
	extra_info = {
		'status': status, 'collection_name': ei_collection_name, 'collection_id': ei_collection_id,
		'budget': ei_budget, 'revenue': ei_revenue, 'homepage': homepage
	}
	meta_dict = {
		'tmdb_id': tmdb_id, 'tvdb_id': 'None', 'imdb_id': imdb_id, 'imdbnumber': imdb_id, 'clearlogo': tmdblogo,
		'poster': poster, 'fanart': fanart, 'year': year, 'title': title, 'rootname': rootname,
		'original_title': original_title, 'english_title': english_title, 'alternative_titles': alternative_titles,
		'tagline': tagline, 'plot': plot, 'mpaa': mpaa, 'studio': studio, 'director': director, 'writer': writer,
		'duration': duration, 'premiered': premiered, 'genre': genre, 'rating': rating, 'votes': votes,
		'country': country, 'country_codes': country_codes, 'trailer': trailer, 'all_trailers': all_trailers,
		'cast': cast, 'extra_info': extra_info, 'mediatype': 'movie', 'meta_language': language
	}
	return meta_dict

def build_tvshow_meta(data, user_info):
	image_resolution, language = user_info.get('image_resolution', backup_resolutions), user_info['language']
	data_get = data.get
	cast, all_trailers, country, country_codes = [], [], [], []
	mpaa, trailer, writer, director, studio = '', '', '', '', ''
	external_ids = data_get('external_ids')
	tmdb_id, imdb_id, tvdb_id = data_get('id', ''), external_ids.get('imdb_id', ''), external_ids.get('tvdb_id', 'None')
	rating, votes = data_get('vote_average', ''), data_get('vote_count', '')
	plot, tagline, premiered = data_get('overview', ''), data_get('tagline', ''), data_get('first_air_date', '')
	season_data, total_seasons, total_aired_eps = data_get('seasons'), data_get('number_of_seasons'), data_get('number_of_episodes')
	poster_path, backdrop_path = data_get('poster_path'), data_get('backdrop_path')
	logo_path = next((i['file_path'] for i in data['images'].get('logos', []) if i['file_path'].endswith('png')), None)
	if not language in 'en,en-US':
		try:
			path = (i['file_path'] for i in data['images']['logos'] if str(i['iso_639_1']) in language and i['file_path'].endswith('png'))
			logo_path = next(path)
		except: pass
	if poster_path: poster = tmdb_image_base % (image_resolution['poster'], poster_path)
	else: poster = ''
	if backdrop_path: fanart = tmdb_image_base % (image_resolution['fanart'], backdrop_path)
	else: fanart = ''
	if logo_path: tmdblogo = tmdb_image_base % (image_resolution['fanart'], logo_path)
	else: tmdblogo = ''
	title, original_title = data_get('name'), data_get('original_name')
	try: english_title = [i['data']['name'] for i in data_get('translations')['translations'] if i['iso_639_1'] == 'en'][0]
	except: english_title = None
	try: year = str(data_get('first_air_date').split('-')[0] or 0)
	except: year = ''
	try: duration = min(data_get('episode_run_time')) * 60
	except: duration = 0
	try: genre = ', '.join([i['name'] for i in data_get('genres')])
	except: genre = ''
	rootname = '%s (%s)' % (title, year)
	networks = data_get('networks')
	if networks:
		if not len(networks) == 1:
			try:
				studio = [i['name'] for i in networks if i['logo_path'] not in empty_value_check][0]
				if not studio: studio = [i['name'] for i in networks][0]
			except: pass
		else: studio = [i['name'] for i in networks][0]
	production_countries = data_get('production_countries')
	if production_countries:
		country = [i['name'] for i in production_countries]
		country_codes = [i['iso_3166_1'] for i in production_countries]
	content_ratings = data_get('content_ratings')
	release_dates = data_get('release_dates')
	if content_ratings:
		try: mpaa = [i['rating'] for i in content_ratings['results'] if i['iso_3166_1'] == 'US'][0]
		except: pass
	elif release_dates:
		try: mpaa = [i['release_dates'][0]['certification'] for i in release_dates['results'] if i['iso_3166_1'] == 'US'][0]
		except: pass
	credits = data_get('credits')
	if credits:
		all_cast = credits.get('cast')
		if all_cast:
			try: cast = [
				{'name': i['name'], 'role': i['character'], 'thumbnail': tmdb_image_base % (image_resolution['profile'], i['profile_path']) if i['profile_path'] else ''}
				for i in all_cast
			]
			except: pass
		crew = credits.get('crew')
		if crew:
			try: writer = ', '.join([i['name'] for i in crew if i['job'] in writer_credits])
			except: pass
			try: director = [i['name'] for i in crew if i['job'] == 'Director'][0]
			except: pass
	alternative_titles = data_get('alternative_titles')
	if alternative_titles:
		alternatives = alternative_titles['results']
		alternative_titles = [i['title'] for i in alternatives if i['iso_3166_1'] in alt_titles_test]
	videos = data_get('videos')
	if videos:
		all_trailers = videos['results']
		try: trailer = [youtube_url % i['key'] for i in all_trailers if i['site'] == 'YouTube' and i['type'] in trailers_test][0]
		except: pass
	status, _type, homepage = data_get('status', 'N/A'), data_get('type', 'N/A'), data_get('homepage', 'N/A')
	created_by = data_get('created_by')
	if created_by:
		try: ei_created_by = ', '.join([i['name'] for i in created_by])
		except: ei_created_by = 'N/A'
	else: ei_created_by = 'N/A'
	ei_next_ep = data_get('next_episode_to_air')
	ei_last_ep = data_get('last_episode_to_air')
	if ei_last_ep and not status in finished_show_check:
		aired_eps = [i['episode_count'] for i in season_data if 0 < i['season_number'] < ei_last_ep['season_number']]
		total_aired_eps = ei_last_ep['episode_number'] + sum(aired_eps)
	extra_info = {
		'status': status, 'type': _type, 'homepage': homepage, 'created_by': ei_created_by,
		'next_episode_to_air': ei_next_ep, 'last_episode_to_air': ei_last_ep
	}
	meta_dict = {
		'tmdb_id': tmdb_id, 'tvdb_id': tvdb_id, 'imdb_id': imdb_id, 'imdbnumber': imdb_id, 'clearlogo': tmdblogo,
		'poster': poster, 'fanart': fanart, 'year': year, 'title': title, 'rootname': rootname, 'tvshowtitle': title,
		'original_title': original_title, 'english_title': english_title, 'alternative_titles': alternative_titles,
		'tagline': tagline, 'plot': plot, 'mpaa': mpaa, 'studio': studio, 'director': director, 'writer': writer,
		'duration': duration, 'premiered': premiered, 'genre': genre, 'rating': rating, 'votes': votes,
		'country': country, 'country_codes': country_codes, 'trailer': trailer, 'all_trailers': all_trailers,
		'cast': cast, 'extra_info': extra_info, 'mediatype': 'tvshow', 'meta_language': language, 'status': status,
		'total_aired_eps': total_aired_eps, 'total_seasons': total_seasons, 'season_data': season_data
	}
	return meta_dict

def rpdb_get(mediatype, media_id, api_key, theme):
	try:
		if not api_key or not media_id: raise Exception
		if media_id.startswith('tt'): id_type = 'imdb'
		else: id_type, media_id = 'tmdb', '%s-%s' % (mediatype, media_id)
		rpdb_url = 'https://api.ratingposterdb.com/%s/%s/poster-default/%s.jpg?fallback=true'
		if theme in ('1', '2'): rpdb_url += rpdb_themes[theme]
		rpdb_url = rpdb_url % (api_key, id_type, media_id)
	except: rpdb_url = ''
	return rpdb_url

