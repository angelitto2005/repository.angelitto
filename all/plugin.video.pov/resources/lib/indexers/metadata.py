from indexers import tmdb_api
from caches.meta_cache import MetaCache
from modules.utils import jsondate_to_datetime, subtract_dates, TaskPool
# from modules.kodi_utils import logger

EXPIRES_2_DAYS, EXPIRES_4_DAYS, EXPIRES_7_DAYS, EXPIRES_14_DAYS, EXPIRES_182_DAYS = 2, 4, 7, 14, 182
backup_resolutions = {'logo': 'w500', 'poster': 'w780', 'fanart': 'w1280', 'still': 'original', 'profile': 'h632'}
finished_show_check, empty_value_check = ('Ended', 'Canceled'), ('', 'None', None)
alt_titles_test, trailers_test = ('US', 'GB', 'UK', ''), ('Trailer', 'Teaser')
writer_credits = ('Author', 'Writer', 'Screenplay', 'Characters')
tmdb_image_base, youtube_url = tmdb_api.tmdb_image_base, 'plugin://plugin.video.youtube/play/?video_id=%s'
rpdb_url = 'https://api.ratingposterdb.com/%s/%s/poster-default/%s.jpg?fallback=true'
rpdb_themes = {'1': '&theme=rounded-blocks', '2': '&theme=blocks'}
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
		if (tag := meta.get(i)) not in ('', 'None', None)
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
			if key not in meta or not (arg := meta[key]): continue
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
		if id_type == 'tmdb_id' or id_type == 'imdb_id':
			data = tmdb_api.movie_details(media_id, user_info['language'])
		else:
			external_result = tmdb_api.movie_external_id(id_type, media_id)
			if not external_result: data = None
			else: data = tmdb_api.movie_details(external_result['id'], user_info['language'])
		if not data or data.get('success', True) is False:
			if id_type == 'tmdb_id': meta = {'blank_entry': True, 'tmdb_id': media_id, 'imdb_id': 'tt0000000', 'tvdb_id': '0000000'}
			else: meta = {'blank_entry': True, 'tmdb_id': '0000000', 'imdb_id': media_id, 'tvdb_id': '0000000'}
			metacache_set('movie', id_type, meta, EXPIRES_2_DAYS)
			return meta
		if user_info['language'] != 'en' and data['overview'] in empty_value_check:
			eng_all_trailers = english_trailers(tmdb_api.movie_details, data)
			if eng_all_trailers: data['videos']['results'] = eng_all_trailers
#		meta = build_movie_meta(data, user_info)
		parser = TmdbParser(data, user_info)
		writer, director = parser.get_crew()
		country, country_codes = parser.get_country_codes()
		title = parser.get_text(('title', 'original_title'))
		premiered = parser.get_text('release_date')
		year = next(iter(premiered.split('-')), '')
		logos = data.get('images', {}).get('logos', [])
		logo_path = next((i['file_path'] for i in logos if i.get('file_path', '').endswith('png')), None)
		videos = data.get('videos', {}).get('results', [])
		belongs_to_collection = data.get('belongs_to_collection')
		if belongs_to_collection:
			ei_collection_name, ei_collection_id = belongs_to_collection['name'], belongs_to_collection['id']
		else: ei_collection_name, ei_collection_id = None, None
		extra_info = {
			'status': data.get('status', 'N/A'),
			'budget': '${:,}'.format(data.get('budget', 0)),
			'revenue': '${:,}'.format(data.get('revenue', 0)),
			'homepage': data.get('homepage', 'N/A'),
			'collection_name': ei_collection_name,
			'collection_id': ei_collection_id
		}
		meta = {
			'tmdb_id': data.get('id', ''),
			'tvdb_id': 'None',
			'imdb_id': data.get('imdb_id', ''),
			'imdbnumber': data.get('imdb_id', ''),
			'mediatype': parser.mediatype,
			'meta_language': parser.lang,
			'rootname': f"{title} ({year})",
			'title': title,
			'original_title': parser.get_text('original_title'),
			'english_title': parser.get_english_title('title'),
			'alternative_titles': parser.get_alternative_titles('titles'),
			'premiered': premiered,
			'year': year,
			'tagline': parser.get_text('tagline'),
			'plot': parser.get_text('overview'),
			'mpaa': parser.get_mpaa('release_dates', user_info['mpaa_region']),
			'studio': parser.get_studio(),
			'director': director,
			'writer': writer,
			'genre': ', '.join([i['name'] for i in data.get('genres', [])]),
			'duration': data.get('runtime', 0) * 60,
			'rating': data.get('vote_average', 0.0),
			'votes': data.get('vote_count', 0),
			'clearlogo': parser.get_image('logo', logo_path),
			'poster': parser.get_image('poster', data.get('poster_path')),
			'fanart': parser.get_image('fanart', data.get('backdrop_path')),
			'trailer': parser.get_trailer(videos),
			'country': country,
			'country_codes': country_codes,
			'extra_info': extra_info,
			'all_trailers': videos,
			'cast': parser.get_cast()
		}
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
	if meta: return _adjust_total_aired_eps(meta, current_date)
	try:
		if id_type == 'tmdb_id':
			data = tmdb_api.tvshow_details(media_id, user_info['language'])
		else:
			external_result = tmdb_api.tvshow_external_id(id_type, media_id)
			if not external_result: data = None
			else: data = tmdb_api.tvshow_details(external_result['id'], user_info['language'])
		if not data or data.get('success', True) is False:
			if id_type == 'tmdb_id': meta = {'blank_entry': True, 'tmdb_id': media_id, 'imdb_id': 'tt0000000', 'tvdb_id': '0000000'}
			elif id_type == 'imdb_id': meta = {'blank_entry': True, 'tmdb_id': '0000000', 'imdb_id': media_id, 'tvdb_id': '0000000'}
			else: meta = {'blank_entry': True, 'tmdb_id': '0000000', 'imdb_id': 'tt0000000', 'tvdb_id': media_id}
			metacache_set('tvshow', id_type, meta, EXPIRES_2_DAYS)
			return meta
		if user_info['language'] != 'en' and data['overview'] in empty_value_check:
			eng_all_trailers = english_trailers(tmdb_api.tvshow_details, data)
			if eng_all_trailers: data['videos']['results'] = eng_all_trailers
#		meta = build_tvshow_meta(data, user_info)
		parser = TmdbParser(data, user_info)
		writer, director = parser.get_crew()
		country, country_codes = parser.get_country_codes()
		title = parser.get_text(('name', 'original_name'))
		premiered = parser.get_text('first_air_date')
		year = next(iter(premiered.split('-')), '')
		logos = data.get('images', {}).get('logos', [])
		logo_path = next((i['file_path'] for i in logos if i.get('file_path', '').endswith('png')), None)
		videos = data.get('videos', {}).get('results', [])
		season_data = data.get('seasons')
		total_aired_eps = data.get('number_of_episodes')
		status = data.get('status', 'N/A')
		try:
			created_by = data.get('created_by', [])
			ei_created_by = ', '.join([i['name'] for i in created_by])
		except: ei_created_by = 'N/A'
		try:
			ei_last_ep = data.get('last_episode_to_air')
			if ei_last_ep and status not in finished_show_check:
				aired_eps = [i['episode_count'] for i in season_data if 0 < i['season_number'] < ei_last_ep['season_number']]
				total_aired_eps = ei_last_ep['episode_number'] + sum(aired_eps)
		except: ei_last_ep = {}
		extra_info = {
			'status': status,
			'type': data.get('status', 'N/A'),
			'homepage': data.get('homepage', 'N/A'),
			'created_by': ei_created_by,
			'next_episode_to_air': data.get('next_episode_to_air'),
			'last_episode_to_air': ei_last_ep
		}
		meta = {
			'tmdb_id': data.get('id', ''),
			'tvdb_id': data.get('external_ids', {}).get('tvdb_id', 'None'),
			'imdb_id': data.get('external_ids', {}).get('imdb_id', 'None'),
			'imdbnumber': data.get('external_ids', {}).get('imdb_id', ''),
			'mediatype': parser.mediatype,
			'meta_language': parser.lang,
			'rootname': f"{title} ({year})",
			'title': title,
			'tvshowtitle': title, # tvshow
			'original_title': parser.get_text('original_name'),
			'english_title': parser.get_english_title('name'),
			'alternative_titles': parser.get_alternative_titles('results'),
			'status': status, # tvshow
			'total_aired_eps': total_aired_eps, # tvshow
			'total_seasons': data.get('number_of_seasons'), # tvshow
			'premiered': premiered,
			'year': year,
			'tagline': parser.get_text('tagline'),
			'plot': parser.get_text('overview'),
			'mpaa': parser.get_mpaa('content_ratings', user_info['mpaa_region']),
			'studio': parser.get_studio(),
			'director': director,
			'writer': writer,
			'genre': ', '.join([i['name'] for i in data.get('genres', [])]),
			'duration': max(data.get('episode_run_time') or [0]) * 60,
			'rating': data.get('vote_average', 0.0),
			'votes': data.get('vote_count', 0),
			'clearlogo': parser.get_image('logo', logo_path),
			'poster': parser.get_image('poster', data.get('poster_path')),
			'fanart': parser.get_image('fanart', data.get('backdrop_path')),
			'trailer': parser.get_trailer(videos),
			'country': country,
			'country_codes': country_codes,
			'extra_info': extra_info,
			'all_trailers': videos,
			'cast': parser.get_cast(),
			'season_data': season_data # tvshow
		}
		metacache_set('tvshow', id_type, meta, tvshow_expiry(current_date, meta))
	except: pass
	return _adjust_total_aired_eps(meta, current_date)

def _adjust_total_aired_eps(meta, current_date):
	try: meta['total_aired_eps'] += meta['extra_info']['next_episode_to_air']['air_date'] == str(current_date)
	except: pass
	return meta

def season_episodes_meta(season, meta, user_info):
	def _make_poster(item):
		if not item['poster_path']: return item['season_number'], ''
		return item['season_number'], tmdb_image_base % (image_resolution['poster'], item['poster_path'])
	def _make_profile(item):
		if item['profile_path']: thumbnail = tmdb_image_base % (profile_resolution, item['profile_path'])
		else: thumbnail = ''
		return {'name': item['name'], 'role': item['character'], 'thumbnail': thumbnail}
	image_resolution = user_info.get('image_resolution', backup_resolutions)
	metacache = MetaCache()
	metacache_get, metacache_set = metacache.get, metacache.set
	media_id, data = meta['tmdb_id'], None
	string = '%s_%s' % (media_id, season)
	data = metacache_get('season', 'tmdb_id', string)
	if data: return data
	try: season_posters = dict(_make_poster(i) for i in meta.get('season_data') if 'poster_path' in i)
	except: season_posters = dict()
	episodes_data = []
	append = episodes_data.append
	try:
		show_ended, total_seasons = meta['status'] in finished_show_check, meta['total_seasons']
		expiration = EXPIRES_182_DAYS if show_ended or total_seasons > int(season) else EXPIRES_4_DAYS
		premiere = 'series_premiere' if int(season) == 1 else 'season_premiere'
		finale = 'series_finale' if show_ended and int(season) == total_seasons else 'season_finale'
		ep_details = {1: premiere, 'mid_season': 'mid_season_finale', 'finale': finale}
		still_resolution, profile_resolution = image_resolution['still'], image_resolution['profile']
		data = tmdb_api.season_episodes_details(media_id, season, user_info['language'])['episodes']
		for ep_data in data:
			writer, director, guest_stars = '', '', []
			ep_data_get = ep_data.get
			title, plot, premiered = ep_data_get('name'), ep_data_get('overview'), ep_data_get('air_date')
			season, episode, ep_type = ep_data_get('season_number'), ep_data_get('episode_number'), ep_data_get('episode_type')
			rating, votes, still_path = ep_data_get('vote_average'), ep_data_get('vote_count'), ep_data_get('still_path')
			ep_type = ep_details.get(ep_type) or ep_details.get(episode) or ep_type or ''
			if ep_type == 'mid_season_finale': ep_details[episode + 1] = 'mid_season_premiere'
			poster = season_posters.get(int(season)) or ''
			thumb = tmdb_image_base % (still_resolution, still_path) if still_path else ''
			try: duration = ep_data_get('runtime') * 60
			except: duration = 0
			guest_stars_list = ep_data_get('guest_stars')
			if guest_stars_list:
				try: guest_stars = [_make_profile(i) for i in guest_stars_list]
				except: pass
			crew = ep_data_get('crew')
			if crew:
				try: writer = ', '.join([i['name'] for i in crew if i['job'] in writer_credits])
				except: pass
				try: director = [i['name'] for i in crew if i['job'] == 'Director'][0]
				except: pass
			append({
				'season_poster': poster, 'thumb': thumb, 'guest_stars': guest_stars, 'director': director,
				'writer': writer, 'plot': plot, 'title': title, 'premiered': premiered,
				'rating': rating, 'votes': votes, 'duration': duration, 'episode_type': ep_type,
				'mediatype': 'episode', 'season': season, 'episode': episode
			})
		metacache_set('season', 'tmdb_id', episodes_data, expiration, string)
	except: pass
	return episodes_data

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

def english_trailers(function, data):
	media_id, id_type = data['id'], 'tmdb_id'
	eng_data = function(media_id, 'en')
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

def movie_expiry(current_date, meta):
	try:
		premiered = jsondate_to_datetime(meta['premiered']).date()
		difference = subtract_dates(current_date, premiered)
		if difference < 0: expiration = abs(difference) + 1
		elif difference <= 14: expiration = EXPIRES_7_DAYS
		elif difference <= 30: expiration = EXPIRES_14_DAYS
		else: expiration = EXPIRES_182_DAYS
	except: return EXPIRES_7_DAYS
	return max(expiration, EXPIRES_7_DAYS)

def tvshow_expiry(current_date, meta):
	try:
		extra_info = meta['extra_info']
		if extra_info['status'] in finished_show_check: return EXPIRES_182_DAYS
		next_episode_to_air = jsondate_to_datetime(extra_info['next_episode_to_air']['air_date']).date()
		expiration = subtract_dates(next_episode_to_air, current_date)
		expiration = max(expiration, 0) + 1
	except: return EXPIRES_4_DAYS
	return expiration

def get_title(meta):
	if 'custom_title' in meta: return meta['custom_title']
	if meta.get('meta_language', '') == 'en': title = meta['title']
	else: title = meta.get('english_title')
	if not title:
		try:
			if meta['mediatype'] == 'movie': mediatype, key = 'movie', 'title'
			else: mediatype, key = 'tv', 'name'
			translations = tmdb_api.english_translation(mediatype, meta['tmdb_id'])
			english_title = (i['data'][key] for i in translations or () if i['iso_639_1'] == 'en')
			title = next(english_title, None) or meta['original_title']
		except: pass
	if '(' in title: title = title.split('(')[0]
	if '/' in title: title = title.replace('/', ' ')
	return title.strip()

def rpdb_get(mediatype, media_id, api_key, theme):
	try:
		if not api_key or not media_id: return
		if media_id.startswith('tt'): id_type = 'imdb'
		else: id_type, media_id = 'tmdb', '%s-%s' % (mediatype, media_id)
		if theme in rpdb_themes: base_url = '%s%s' % (rpdb_url, rpdb_themes[theme])
		else: base_url = rpdb_url
		return base_url % (api_key, id_type, media_id)
	except: pass

class TmdbParser:
	def __init__(self, data, user_info):
		self.mediatype = 'tvshow' if 'name' in data else 'movie'
		self.data = data or {}
		self.res = user_info.get('image_resolution', backup_resolutions)
		self.lang = user_info.get('language', 'en')

	def get_text(self, keys, default=''):
		for key in keys if isinstance(keys, (list, tuple)) else [keys]:
			val = self.data.get(key)
			if val in empty_value_check: continue
			return val
		return default

	def get_image(self, key_type, path):
		if not path: return ''
		return tmdb_api.tmdb_image_base % (self.res[key_type], path)

	def get_crew(self):
		writer, director = '', ''
		crew = self.data.get('credits', {}).get('crew', [])
		if crew:
			writer = ', '.join([i['name'] for i in crew if i.get('job') in writer_credits])
			directors = [i['name'] for i in crew if i.get('job') == 'Director']
			director = directors[0] if directors else ''
		return writer, director

	def get_cast(self):
		cast_list = self.data.get('credits', {}).get('cast', [])
		return [
			{'name': i['name'],
			 'role': i['character'],
			 'thumbnail': self.get_image('profile', i.get('profile_path'))}
			for i in cast_list if i.get('name')
		]

	def get_mpaa(self, key='release_dates', mpaa_region='US'):
		mpaa = ''
		for res in self.data.get(key, {}).get('results', []):
			if res['iso_3166_1'] != mpaa_region: continue
			if key == 'release_dates':
				_mpaa= (x['certification'] for x in res['release_dates'] if x['certification'])
				mpaa = next(_mpaa, '')
			elif key == 'content_ratings': mpaa = res['rating']
			if mpaa and mpaa_region != 'US': mpaa = f"{mpaa_region} {mpaa}"
		return mpaa

	def get_english_title(self, key):
		translations = self.data.get('translations', {}).get('translations', [])
		translations = (i['data'][key] for i in translations if i['iso_639_1'] == 'en')
		return next(translations, '')

	def get_alternative_titles(self, key):
		alternatives = self.data.get('alternative_titles', {}).get(key, [])
		return [i['title'] for i in alternatives if i['iso_3166_1'] in alt_titles_test]

	def get_country_codes(self):
		production_countries = self.data.get('production_countries', [])
		country = [i['name'] for i in production_countries]
		country_codes = [i['iso_3166_1'] for i in production_countries]
		return country, country_codes

	def get_studio(self):
		companies = self.data.get('production_companies', [])
		companies = (i['name'] for i in companies if i['logo_path'] not in empty_value_check)
		return next(companies, '')

	def get_trailer(self, videos):
		trailer_key = (i['key'] for i in videos if i['site'] == 'YouTube' and i['type'] in trailers_test)
		trailer_key = next(trailer_key, '')
		if trailer_key: return youtube_url % trailer_key
		return trailer_key

