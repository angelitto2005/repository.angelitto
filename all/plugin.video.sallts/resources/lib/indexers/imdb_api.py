import re
import requests
from html import unescape
from caches.main_cache import cache_object
# from modules.kodi_utils import logger

graphql_url = 'https://api.graphql.imdb.com/'
api_url = 'https://api.imdbapi.dev'
base_url = 'https://www.imdb.com/%s'
timeout = 10.0
session = requests.Session()
retry = requests.adapters.Retry(total=None, status=1, status_forcelist=(429, 502, 503, 504))
session.mount('https://', requests.adapters.HTTPAdapter(pool_maxsize=100, max_retries=retry))

def remove_html_tags(text):
	lines = re.compile(r'(<br>|<br\s?/>)')
	clean = re.compile(r'<.*?>')
	return re.sub(clean, '', re.sub(lines, '\n', text))

def people_get_imdb_id(actor_name, actor_tmdbID=None):
	name = actor_name.lower()
	url = 'https://sg.media-imdb.com/suggests/%s/%s.json' % (name[0], name.replace(' ', '%20'))
	string = 'imdb_people_get_imdb_id_%s' % name
	params = {'url': url, 'action': 'imdb_people_id', 'actor_tmdbID': actor_tmdbID, 'name': name}
	return cache_object(get_imdb, string, params, False, 8736)[0]

def imdb_extended_info(imdb_id):
	url = imdb_id
	string = 'imdb_extended_info_%s' % imdb_id
	params = {'url': url, 'action': 'imdb_extended_info'}
	return cache_object(get_imdb, string, params, False, 168)[0]

def imdb_tagged_images(imdb_id):
	url = '%s/names/%s/images' % (api_url, imdb_id)
	string = 'imdb_images_tagged_%s' % imdb_id
	params = {'url': url, 'action': 'imdb_tagged_images'}
	return cache_object(get_imdb, string, params, False, 168)[0]

def imdb_parentsguide(imdb_id):
	url = '%s/titles/%s/parentsGuide' % (api_url, imdb_id)
	string = 'imdb_parentsguide_%s' % imdb_id
	params = {'url': url, 'action': 'imdb_parentsguide'}
	return cache_object(get_imdb, string, params, False, 168)[0]

def imdb_movie_year(imdb_id):
	url = 'https://v2.sg.media-imdb.com/suggestion/t/%s.json' % imdb_id
	string = 'imdb_movie_year_%s' % imdb_id
	params = {'url': url, 'action': 'imdb_movie_year'}
	return cache_object(get_imdb, string, params, False, 720)[0]

def get_imdb(params):
	imdb_list = []
	action = params['action']
	url = params['url']
	next_page = None
	if 'date' in params:
		from datetime import datetime, timedelta
		date_time = (datetime.utcnow() - timedelta(hours=5))
		for i in re.findall(r'date\[(\d+)\]', url):
			url = url.replace('date[%s]' % i, (date_time - timedelta(days = int(i))).strftime('%Y-%m-%d'))
	if action == 'imdb_people_id':
		try:
			actor_tmdbID = params['actor_tmdbID']
			name = params['name']
			if actor_tmdbID:
				from indexers.tmdb_api import tmdb_people_full_info
				imdb_list = tmdb_people_full_info(actor_tmdbID)['imdb_id']
			if not imdb_list:
				import json
				result = session.get(url, timeout=timeout).text
				result = json.loads(re.sub(r'^imdb\$.*?\(', '', result)[:-1])['d']
				imdb_list = next((i['id'] for i in result if i['l'].lower() == name))
		except: pass
	elif action == 'imdb_tagged_images':
		try:
			params = {'pageSize': 50}
			result = session.get(url, params=params, timeout=timeout)
			result = result.json()['images']
			imdb_list = [i for i in result if not i['type'] in ('still_frame', 'poster', 'product')]
		except: pass
	elif action == 'imdb_parentsguide':
		try:
			append = imdb_list.append
			result = session.get(url, timeout=timeout)
			result = result.json()['parentsGuide']
			for i in result:
				try:
					listings = [x['text'] for x in i.get('reviews', [])]
					rank = max(i['severityBreakdowns'], key=lambda k: k['voteCount'])['severityLevel']
					append({'title': i['category'].lower(), 'ranking': rank, 'listings': listings})
				except: pass
		except: pass
	elif action == 'imdb_extended_info':
		""" thanks https://github.com/tveronesi """
		trivia, blunders, reviews, parentsguide = [], [], [], []
		try:
			headers = {'User-Agent': session.headers['User-Agent'], 'Content-Type': 'application/json', 'x-imdb-user-country': 'EN'}
			data = {'query': imdb_extended_query % url}
			result = session.post(graphql_url, json=data, headers=headers, timeout=timeout)
			if not result.ok: result.raise_for_status()
			result = result.json().get('data', {}).get('title', {})
			try: trivia.extend(
				unescape(remove_html_tags(i['node']['displayableArticle']['body']['plaidHtml']))
				for i in sorted(result['trivia']['edges'], key=lambda k: k['node']['interestScore']['usersVoted'], reverse=True)
			)
			except: pass
			try: blunders.extend(
				unescape(remove_html_tags(i['node']['displayableArticle']['body']['plaidHtml']))
				for i in sorted(result['goofs']['edges'], key=lambda k: k['node']['interestScore']['usersVoted'], reverse=True)
			)
			except: pass
			try: reviews.extend(
				{'content': unescape(remove_html_tags(i['node']['text']['originalText']['plaidHtml'])),
				 'summary': i['node']['summary']['originalText'],
				 'provider_id': i['node']['author']['nickName'],
				 'rating': i['node']['authorRating'],
				 'updated_at': i['node']['submissionDate'],
				 'spoiler': i['node']['spoiler']}
				for i in sorted(result['reviews']['edges'], key=lambda k: k['node']['submissionDate'], reverse=True)
			)
			except: pass
			try: parentsguide.extend(
				{'listings': [unescape(remove_html_tags(x['node']['text']['plaidHtml'])) for x in i['guideItems']['edges']],
				 'title': i['category']['id'].lower(),
				 'ranking': i['severity']['id'].replace('Votes', '')}
				for i in result['parentsGuide']['categories']
			)
			except: pass
		except requests.exceptions.RequestException as e:
			from modules.kodi_utils import logger
			logger('imdb error', str(e))
		except: pass
		imdb_list = {'trivia': trivia, 'blunders': blunders, 'reviews': reviews, 'parentsguide': parentsguide}
	elif action == 'imdb_movie_year':
		result = session.get(url, timeout=timeout).json()
		try:
			result = next((int(i['y']) for i in result['d'] if 'y' in i))
			imdb_list = str(result)
		except: pass
	return (imdb_list, next_page)

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

imdb_extended_query = """\
query {
  title(id: "%s") {
    id
    titleText {
      text
    }
    trivia(first: 20) {
      edges {
        node {
          displayableArticle {
            body {
              plaidHtml
            }
          }
          interestScore {
            usersVoted
          }
        }
      }
    }
    goofs(first: 20) {
      edges {
        node {
          displayableArticle {
            body {
              plaidHtml
            }
          }
          interestScore {
            usersVoted
          }
        }
      }
    }
    reviews(first: 20) {
      edges {
        node {
          spoiler
          author {
            nickName
          }
          authorRating
          summary {
            originalText
          }
          text {
            originalText {
              plaidHtml
            }
          }
          submissionDate
        }
      }
    }
    parentsGuide {
      categories {
        category {
          id
        }
        guideItems(first: 10) {
          edges {
            node {
              isSpoiler
              text {
                plaidHtml
              }
            }
          }
        }
        severity {
          id
          votedFor
        }
      }
    }
  }
}"""

