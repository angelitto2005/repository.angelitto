import re
import requests
from html import unescape
from caches.main_cache import cache_object
# from modules.kodi_utils import logger

graphql_headers, graphql_url = {
	'User-Agent': 'curl/7.55.1',
	'x-imdb-client-name': 'imdb-web-next-localized',
	'x-imdb-user-language': 'en-US',
	'x-imdb-user-country': 'US'
}, 'https://api.graphql.imdb.com/'
base_url = 'https://www.imdb.com/%s'
timeout = 10.0
session = requests.Session()
retry = requests.adapters.Retry(total=None, status=1, status_forcelist=(429, 502, 503, 504))
session.mount('https://', requests.adapters.HTTPAdapter(pool_maxsize=100, max_retries=retry))

def clean_html(text):
	if not text: return ''
	lines = re.compile(r'<br\s*/?>', re.I)
	tags = re.compile(r'<.*?>')
	return unescape(tags.sub('', lines.sub('\n', text)))

def people_get_imdb_id(actor_name, actor_id=None):
	name = actor_name.lower()
	string = 'imdb_people_get_imdb_id_%s' % name
	url = 'https://sg.media-imdb.com/suggests/%s/%s.json' % (name[0], name)
	params = {'url': url, 'actor_id': actor_id, 'name': name}
	return cache_object(people_get_imdb_id_handler, string, params, 8736)

def people_get_imdb_id_handler(params):
	actor_imdb_id = ''
	try:
		if params['actor_id']:
			from indexers.tmdb_api import tmdb_people_full_info
			actor_imdb_id = tmdb_people_full_info(params['actor_id'])['imdb_id']
		if not actor_imdb_id:
			import json
			result = session.get(params['url'], timeout=timeout)
			result = json.loads(re.sub(r'^imdb\$.*?\(', '', result.text)[:-1])['d']
			actor_imdb_id = next((i['id'] for i in result if i['l'].lower() == params['name']))
	except: pass
	return actor_imdb_id

def imdb_extended_info(imdb_id):
	string = 'imdb_extended_info_%s' % imdb_id
	return cache_object(imdb_extended_info_handler, string, imdb_id, 168)

def imdb_extended_info_handler(imdb_id):
	""" thanks https://github.com/tveronesi """
	imdb_extended_query, trivia, blunders, reviews, parentsguide = (
		'query{title(id:"%s"){id titleText{text}'
		'trivia(first:20){edges{node{displayableArticle{body{plaidHtml}}interestScore{usersVoted}}}}'
		'goofs(first:20){edges{node{displayableArticle{body{plaidHtml}}interestScore{usersVoted}}}}'
		'reviews(first:20){edges{node{spoiler author{nickName}authorRating summary{originalText}text{originalText{plaidHtml}}submissionDate}}}'
		'parentsGuide{categories{category{id}guideItems(first:10){edges{node{isSpoiler text{plaidHtml}}}}severity{id votedFor}}}}}'
	), [], [], [], []
	try:
		data = {'query': imdb_extended_query % imdb_id}
		result = session.post(graphql_url, json=data, headers=graphql_headers, timeout=timeout)
		if not result.ok: result.raise_for_status()
		result = result.json().get('data', {}).get('title', {})
		try:
			_sorted = sorted(result['trivia']['edges'], key=lambda k: k['node']['interestScore']['usersVoted'], reverse=True)
			trivia.extend(clean_html(i['node']['displayableArticle']['body']['plaidHtml']) for i in _sorted)
		except: pass
		try:
			_sorted = sorted(result['goofs']['edges'], key=lambda k: k['node']['interestScore']['usersVoted'], reverse=True)
			blunders.extend(clean_html(i['node']['displayableArticle']['body']['plaidHtml']) for i in _sorted)
		except: pass
		try:
			_sorted = sorted(result['reviews']['edges'], key=lambda k: k['node']['submissionDate'], reverse=True)
			reviews.extend(
			{'content': clean_html(i['node']['text']['originalText']['plaidHtml']),
			 'summary': i['node']['summary']['originalText'],
			 'provider_id': i['node']['author']['nickName'],
			 'rating': i['node']['authorRating'],
			 'updated_at': i['node']['submissionDate'],
			 'spoiler': i['node']['spoiler']}
			for i in _sorted)
		except: pass
		try:
			parentsguide.extend(
			{'listings': [clean_html(x['node']['text']['plaidHtml']) for x in i['guideItems']['edges']],
			 'title': i['category']['id'].lower(),
			 'ranking': i['severity']['id'].replace('Votes', '')}
			for i in result['parentsGuide']['categories'])
		except: pass
	except requests.RequestException as e:
		from modules.kodi_utils import logger
		logger('imdb error', str(e))
	return {'trivia': trivia, 'blunders': blunders, 'reviews': reviews, 'parentsguide': parentsguide}

def imdb_tagged_images(imdb_id):
	string = 'imdb_images_tagged_%s' % imdb_id
	return cache_object(imdb_tagged_images_handler, string, imdb_id, 168)

def imdb_tagged_images_handler(imdb_id):
	imdb_extended_query, excluded_types = (
		'query{name(id:"%s"){id nameText{text}'
		'images(first:500){edges{node{url caption{plainText} type}}}}}'
	), {'still_frame', 'poster', 'product'}
	try:
		data = {'query': imdb_extended_query % imdb_id}
		result = session.post(graphql_url, json=data, headers=graphql_headers, timeout=timeout)
		if not result.ok: result.raise_for_status()
		result = result.json().get('data', {}).get('name', {})
		return [
			{'type': i['node']['caption']['plainText'].strip(), 'url': i['node']['url']}
			for i in result['images']['edges'] if i['node']['type'] not in excluded_types
		]
	except requests.RequestException as e:
		from modules.kodi_utils import logger
		logger('imdb error', str(e))
	return []

def imdb_movie_year(imdb_id):
	def _process(dummy):
		try:
			result = session.get(url, timeout=timeout).json()
			result = next((int(i['y']) for i in result['d'] if 'y' in i))
			return str(result)
		except: pass
	string = 'imdb_movie_year_%s' % imdb_id
	url = 'https://v2.sg.media-imdb.com/suggestion/t/%s.json' % imdb_id
	return cache_object(_process, string, url, 720)

def clear_imdb_cache(silent=False):
	from modules.kodi_utils import path_exists, clear_property, database_connect, maincache_db
	try:
		if not path_exists(maincache_db): return True
		dbcon = database_connect(maincache_db, isolation_level=None)
		dbcur = dbcon.cursor()
		dbcur.execute("""PRAGMA synchronous = OFF""")
		dbcur.execute("""PRAGMA journal_mode = OFF""")
		dbcur.execute("""SELECT id FROM maincache WHERE id LIKE ?""", ('imdb_%',))
		imdb_results = [str(i[0]) for i in dbcur.fetchall()]
		if not imdb_results: return True
		dbcur.execute("""DELETE FROM maincache WHERE id LIKE ?""", ('imdb_%',))
		for i in imdb_results: clear_property(i)
		return True
	except: return False

