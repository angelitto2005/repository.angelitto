import requests
from .kore import logger, get_property, set_property
from .objects import Movie, Series, Episode

list_url = 'https://cinemeta-catalogs.strem.io'
meta_url = 'https://v3-cinemeta.strem.io'

def _cache_get(string):
	try: value = eval(get_property(string))
	except: value = None
	return value

def _cache_set(result, string):
	set_property(string, repr(result))

def _cinemeta(url):
	response = requests.get(url, timeout=10.0)
	if not response.ok: return logger(__name__, f"{response.reason}\n{url}")
	return response.json()

def external_ids(external_source, external_id, tmdb_api='7b2b174744f774ba48145e2859bb2e2c'):
	result = None
	try:
		base_url = 'https://api.themoviedb.org/3'
		string = 'magneto_external_id_%s_%s' % (external_source, external_id)
		url = '%s/find/%s?api_key=%s&external_source=%s' % (base_url, external_id, tmdb_api, external_source)
		result = _cache_get(string)
		if not result: result = requests.get(url, timeout=3.0).json()
		if not result['movie_results'] and not result['tv_results']: raise
		_cache_set(result, string)
	except: pass
	return result

def top_movies():
	string = 'cinemeta_top_movies'
	url = '%s/top/catalog/movie/top/skip=0.json' % list_url
	result = _cache_get(string)
	if not result: result = _cinemeta(url)
	if not result: return []
	_cache_set(result, string)
	return [Movie(i) for i in result['metas']]

def top_series():
	string = 'cinemeta_top_series'
	url = '%s/top/catalog/series/top/skip=0.json' % list_url
	result = _cache_get(string)
	if not result: result = _cinemeta(url)
	if not result: return []
	_cache_set(result, string)
	return [Series(i) for i in result['metas']]

def movie_meta(imdb):
	string = 'cinemeta_movie_%s' % imdb
	url = '%s/meta/movie/%s.json' % (meta_url, imdb)
	data = _cache_get(string)
	if not data: data = _cinemeta(url)
	if not data: return {}
	_cache_set(data, string)
	return Movie(data['meta'])

def series_meta(imdb):
	string = 'cinemeta_series_%s' % imdb
	url = '%s/meta/series/%s.json' % (meta_url, imdb)
	data = _cache_get(string)
	if not data: data = _cinemeta(url)
	if not data: return {}
	_cache_set(data, string)
	return Series(data['meta'])

def episode_meta(imdb, season, episode):
	show = series_meta(imdb)
	return next((
		ep for ep in show.get('episodes')
		if ep['season'] == season and ep['episode'] == episode
	), Episode())
