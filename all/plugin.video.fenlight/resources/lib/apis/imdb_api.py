# -*- coding: utf-8 -*-
import re
import json
import requests
from caches.base_cache import connect_database
from caches.main_cache import cache_object
from caches.settings_cache import get_setting
from modules.dom_parser import parseDOM
from modules.kodi_utils import sleep
from modules.utils import remove_accents, replace_html_codes, normalize
# from modules.kodi_utils import logger

def imdb_more_like_this(imdb_id):
	url = 'https://www.imdb.com/title/%s' % imdb_id
	string = 'imdb_more_like_this_%s' % imdb_id
	params = {'url': url, 'action': 'imdb_more_like_this', 'imdb_id': imdb_id}
	return cache_object(get_imdb, string, params, False, 168)[0]

def imdb_people_id(actor_name):
	name = actor_name.lower()
	string = 'imdb_people_id_%s' % name
	url, url_backup = 'https://sg.media-imdb.com/suggests/%s/%s.json' % (name[0], name.replace(' ', '%20')), 'https://www.imdb.com/search/name/?name=%s' % name
	params = {'url': url, 'action': 'imdb_people_id', 'name': name, 'url_backup': url_backup}
	return cache_object(get_imdb, string, params, False, 8736)[0]

def imdb_reviews(imdb_id):
	url = 'https://www.imdb.com/title/%s/reviews/?sort=featured,desc' % imdb_id
	string = 'imdb_reviews_%s' % imdb_id
	params = {'url': url, 'action': 'imdb_reviews'}
	return cache_object(get_imdb, string, params, False, 168)[0]

def imdb_parentsguide(imdb_id):
	url = 'https://www.imdb.com/title/%s/parentalguide' % imdb_id
	string = 'imdb_parentsguide_%s' % imdb_id
	params = {'url': url, 'action': 'imdb_parentsguide'}
	return cache_object(get_imdb, string, params, False, 168)[0]

def imdb_trivia(imdb_id):
	url = 'https://www.imdb.com/title/%s/trivia' % imdb_id
	string = 'imdb_trivia_%s' % imdb_id
	params = {'url': url, 'action': 'imdb_trivia'}
	return cache_object(get_imdb, string, params, False, 168)[0]

def imdb_blunders(imdb_id):
	url = 'https://www.imdb.com/title/%s/goofs' % imdb_id
	string = 'imdb_blunders_%s' % imdb_id
	params = {'url': url, 'action': 'imdb_blunders'}
	return cache_object(get_imdb, string, params, False, 168)[0]

def imdb_people_trivia(imdb_id):
	url = 'https://www.imdb.com/name/%s/trivia' % imdb_id
	string = 'imdb_people_trivia_%s' % imdb_id
	params = {'url': url, 'action': 'imdb_people_trivia'}
	return cache_object(get_imdb, string, params, False, 168)[0]

def imdb_year_check(imdb_id):
	url = 'https://v2.sg.media-imdb.com/suggestion/t/%s.json' % imdb_id
	string = 'imdb_year_check%s' % imdb_id
	params = {'url': url, 'imdb_id': imdb_id, 'action': 'imdb_year_check'}
	return cache_object(get_imdb, string, params, False, 720)[0]

def get_imdb(params):
	headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
				'Accept-Language':'en-us,en;q=0.5'}
	imdb_list = []
	action = params.get('action')
	url = params.get('url')
	next_page = None
	if action == 'imdb_more_like_this':
		def _process():
			for item in items:
				try:
					_id = item.split('href="/title/')[1].split('/?ref_')[0]
					if _id.replace('tt','').isnumeric(): yield (_id)
				except: pass
		try:
			result = requests.get(url, timeout=20, headers=headers).text
			result = result.split('<span>Storyline</span>')[0].split('<span>More like this</span>')[1]
			items = str(result).split('poster-card__title--clickable" aria-label="')
		except: items = []
		imdb_list = list(_process())
		imdb_list = [i for n, i in enumerate(imdb_list) if i not in imdb_list[n + 1:]] # remove duplicates
	if action in ('imdb_trivia', 'imdb_blunders'):
		def _process():
			for count, item in enumerate(items, 1):
				try:
					content = re.sub(r'<a class="ipc-md-link ipc-md-link--entity" href="\S+">', '', item).replace('</a>', '')
					content = replace_html_codes(content)
					content = content.replace('<br/><br/>', '\n')
					content = '[B]%s %02d.[/B][CR][CR]%s' % (_str, count, content)
					yield content
				except: pass
		if action == 'imdb_trivia': _str = 'TRIVIA'
		else: _str =  'BLUNDERS'
		result = requests.get(url, timeout=20, headers=headers)
		result = remove_accents(result.text)
		result = result.replace('\n', ' ')
		items = parseDOM(result, 'div', attrs={'class': 'ipc-html-content-inner-div'})
		imdb_list = list(_process())
	elif action == 'imdb_people_trivia':
		def _process():
			for count, item in enumerate(items, 1):
				try:
					content = re.sub(r'<a href=".+?">', '', item).replace('</a>', '').replace('<p> ', '').replace('<br />', '').replace('  ', '')
					content = re.sub(r'<a class=".+?">', '', item).replace('</a>', '').replace('<p> ', '').replace('<br />', '').replace('  ', '')
					content = replace_html_codes(content)
					content = '[B]%s %02d.[/B][CR][CR]%s' % (trivia_str, count, content)
					yield content
				except: pass
		trivia_str = 'TRIVIA'
		result = requests.get(url, timeout=20, headers=headers)
		result = remove_accents(result.text)
		result = result.replace('\n', ' ')
		items = parseDOM(result, 'div', attrs={'class': 'ipc-html-content-inner-div'})
		imdb_list = list(_process())
	elif action == 'imdb_reviews':
		def _process():
			count = 1
			for item in all_reviews:
				try:
					try:
						content = re.findall(r'plaidHtml":"(.*)","__typename":"Markdown', item)[0]
						try: content = content.encode('ascii').decode('unicode-escape')
						except: pass
						content = replace_html_codes(content.replace('</a>', '').replace('<p> ', '').replace('<br />', '').replace('  ', ''))
					except: continue
					try: spoiler = re.findall(r'"spoiler":(.*),"reportingLink', item)[0]
					except: spoiler = 'false'
					try: rating = re.findall(r'"authorRating":(.*),"submissionDate', item)[0]
					except: rating = '-'
					try:
						title = re.findall(r'"summary":{"originalText":"(.*)","__typename":"ReviewSummary', item)[0]
						title = replace_html_codes(title.replace('</a>', '').replace('<p> ', '').replace('<br />', '').replace('  ', ''))
					except: title = '-----'
					try: date = re.findall(r'"submissionDate":"(.*)","helpfulness', item)[0]
					except: date = '-----'
					try: review = '[B]%02d. [I]%s/10 - %s - %s[/I][/B][CR][CR]%s' % (count, rating, date, title, content)
					except: continue
					if spoiler == 'true': review = '[B][COLOR red][%s][/COLOR][CR][/B]' % spoiler_str + review
					count += 1
					yield review
				except: pass
		spoiler_str = 'CONTAINS SPOILERS'
		result = requests.get(url, timeout=20, headers=headers)
		result = remove_accents(result.text)
		result = result.replace('\n', ' ')
		body = re.findall(r'{"node":{"id":(.*)"__typename":"ReviewEdge"', result)[0]
		all_reviews = body.split('"__typename":"ReviewEdge"}')
		imdb_list = list(_process())
	elif action == 'imdb_people_id':
		try:
			name = params['name']
			result = requests.get(url, timeout=20)
			results = json.loads(re.sub(r'imdb\$(.+?)\(', '', result.text)[:-1])['d']
			imdb_list = [i['id'] for i in results if i['id'].startswith('nm') and i['l'].lower() == name][0]
		except: imdb_list = []
		if not imdb_list:
			try:
				result = requests.get(params['url_backup'], timeout=20)
				result = remove_accents(result.text)
				result = result.replace('\n', ' ')
				result = parseDOM(result, 'div', attrs={'class': 'lister-item-image'})[0]
				imdb_list = re.search(r'href="/name/(.+?)"', result, re.DOTALL).group(1)
			except: pass
	elif action == 'imdb_year_check':
		try:
			imdb_id = params.get('imdb_id')
			result = requests.get(url, timeout=5)
			result = result.json()
			result = result['d']
			imdb_list = [str(i['y']) for i in result if i['id'] == imdb_id][0]
		except: pass
	elif action == 'imdb_parentsguide':
		imdb_list = []
		imdb_append = imdb_list.append
		result = requests.get(url, timeout=20, headers=headers)
		result = remove_accents(result.text)
		result = result.replace('\n', ' ')
		results = parseDOM(result, 'section', attrs={'class': 'ipc-page-section ipc-page-section--base'})
		for item in results:
			if 'contentRating' in item: continue
			if 'Certifications' in item: continue
			item_dict = {}
			try:
				title_data = re.search(r'<span id="(.+?)">(.+?)</span>', item, re.DOTALL).group(0)
				title = replace_html_codes(re.search(r'">(.+?)</span>', title_data, re.DOTALL).group(1))
				item_dict['title'] = title
			except: continue
			try:
				ranking = replace_html_codes(re.search(r'<div class="ipc-signpost__text" role="presentation">(.+?)</div>', item, re.DOTALL).group(1))
				item_dict['ranking'] = ranking
			except: item_dict['ranking'] = 'none'
			try:
				listings = re.findall(r'<div class="ipc-html-content-inner-div" role="presentation">(.+?)</div>', item)
				listings = [replace_html_codes(i) for i in listings]
			except: listings = []
			if listings:
				item_dict['content'] = '\n\n'.join(['%02d. %s' % (count, i) for count, i in enumerate(listings, 1)])
			elif item_dict['ranking'] == 'none': continue
			item_dict['total_count'] = len(listings)
			if item_dict: imdb_append(item_dict)
	return (imdb_list, next_page)

def clear_imdb_cache(silent=False):
	try:
		dbcon = connect_database('maincache_db')
		results = dbcon.execute("SELECT id FROM maincache WHERE id LIKE ?", ('imdb_%',)).fetchall()
		dbcon.execute("DELETE FROM maincache WHERE id LIKE ?", ('imdb_%',))
		return True
	except: return False

def refresh_imdb_meta_data(imdb_id):
	try:
		imdb_results = []
		insert1, insert2 = '%%_%s' % imdb_id, '%%_%s_%%' % imdb_id
		dbcon = connect_database('maincache_db')
		for item in (insert1, insert2):
			results = dbcon.execute("SELECT id FROM maincache WHERE id LIKE ?", (item,)).fetchall()
		dbcon.execute("DELETE FROM maincache WHERE id LIKE ?", (insert1,))
		dbcon.execute("DELETE FROM maincache WHERE id LIKE ?", (insert2,))
		return True
	except: return False
