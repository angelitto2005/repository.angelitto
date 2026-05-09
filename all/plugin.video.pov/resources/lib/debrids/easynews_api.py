import re
import json
import requests
from urllib.parse import urlencode, quote
from caches.main_cache import cache_object
from modules.kodi_utils import get_setting
# from modules.kodi_utils import logger

video_extensions = (
	'm4v,3g2,3gp,nsv,tp,ts,ty,pls,rm,rmvb,mpd,ifo,mov,qt,divx,xvid,bivx,vob,nrg,img,iso,udf,pva,wmv,asf,asx,ogm,m2v,avi,bin,dat,mpg,mpeg,mp4,mkv,'
	'mk3d,avc,vp3,svq3,nuv,viv,dv,fli,flv,wpl,xspf,vdr,dvr-ms,xsp,mts,m2t,m2ts,evo,ogv,sdp,avs,rec,url,pxml,vc1,h264,rcv,rss,mpls,mpl,webm,bdmv,bdm,wtv,trp,f4v,pvr,disc'
)
SEARCH_PARAMS = {'st': 'adv', 'sb': 1, 'fex': video_extensions, 'fty[]': 'VIDEO', 'spamf': 1, 'u': '1', 'gx': 1, 'pno': 1, 'sS': 3,
				's1': 'relevance', 's1d': '-', 's2': 'dsize', 's2d': '-', 's3': 'dtime', 's3d': '-', 'pby': 350}
timeout = 10.0
session = requests.Session()
session.mount('https://', requests.adapters.HTTPAdapter(max_retries=1))

class EasyNewsAPI:
	def __init__(self):
		self.base_url = 'https://members.easynews.com'
		self.search_link = '/2.0/search/solr-search/advanced'
		self.account_link = 'https://account.easynews.com/editinfo.php'
		self.usage_link = 'https://account.easynews.com/usageview.php'
		self.username = get_setting('easynews_user')
		self.password = get_setting('easynews_password')
		self.moderation = 1 if get_setting('easynews_moderation') == 'true' else 0

	def search(self, query, expiration=48):
		url, self.params = self._translate_search(query)
		string = 'pov_EASYNEWS_SEARCH_' + urlencode(self.params)
		return cache_object(self._process_search, string, url, expiration)

	def account(self):
		from modules.dom_parser import parseDOM
		account_info, usage_info = None, None
		try:
			account_html = self._get(self.account_link)
			account_info = parseDOM(account_html, 'form', attrs={'id': 'accountForm'})
			account_info = parseDOM(account_info, 'td')[0:11][1::3]
		except: pass
		try:
			usage_html = self._get(self.usage_link)
			usage_info = parseDOM(usage_html, 'div', attrs={'class': 'table-responsive'})
			usage_info = parseDOM(usage_info, 'td')[0:11][1::3]
			usage_info[1] = re.sub(r'[</].+?>', '', usage_info[1])
		except: pass
		return account_info, usage_info

	def _process_files(self, files):
		def _process():
			for item in files:
				try:
					post_hash, size, post_title, ext, duration = item['0'], item['4'], item['10'], item['11'], item['14']
					language = item['alangs'] if 'alangs' in item and item['alangs'] else ''
					if 'type' in item and item['type'].upper() != 'VIDEO': continue
					if 'virus' in item and item['virus']: continue
					if re.match(r'^\d+s', duration) or re.match(r'^[0-5]m', duration): continue
					url_dl = down_url + quote('/%s/%s/%s%s/%s%s' % (dl_farm, dl_port, post_hash, ext, post_title, ext))
					thumbnail = 'https://th.easynews.com/thumbnails-%s/pr-%s.jpg' % (post_hash[0:3], post_hash)
					yield {
						'version': 'version2', 'full_item': item, 'thumbnail': thumbnail, 'url_dl': url_dl,
						'name': post_title, 'size': size, 'rawSize': item['rawSize'], 'language': language
					}
				except Exception as e:
					from modules.kodi_utils import logger
					logger('POV easynews API Exception', str(e))
		down_url = files.get('downURL')
		dl_farm = files.get('dlFarm')
		dl_port = files.get('dlPort')
		files = files.get('data', [])
		results = list(_process())
		return results

	def _translate_search(self, query):
		params = SEARCH_PARAMS
		params['safeO'] = self.moderation
		params['gps'] = query
		url = self.base_url + self.search_link
		return url, params

	def _process_search(self, url):
		results = self._get(url, self.params)
		files = self._process_files(results)
		return files

	def _get(self, url, params=None):
		response = session.get(url, auth=(self.username, self.password), params=params, timeout=timeout).text
		try: return json.loads(response)
		except: return response

	def unrestrict_link(self, url_dl):
		response = session.get(url_dl, auth=(self.username, self.password), stream=True, timeout=timeout*3)
		if not response.ok: return None
		chunk = next(response.iter_content(chunk_size=1048576), b'')
		if len(chunk): resolved_link = response.url # direct/unrestricted link
		else: resolved_link = None
		return resolved_link

def clear_media_results_database():
	from modules.kodi_utils import clear_property, database_connect, maincache_db
	dbcon = database_connect(maincache_db)
	dbcur = dbcon.cursor()
	dbcur.execute("""PRAGMA synchronous = OFF""")
	dbcur.execute("""PRAGMA journal_mode = OFF""")
	dbcur.execute("""SELECT id FROM maincache WHERE id LIKE 'pov_EASYNEWS_SEARCH_%'""")
	easynews_results = [str(i[0]) for i in dbcur.fetchall()]
	if not easynews_results: return 'success'
	try:
		dbcur.execute("""DELETE FROM maincache WHERE id LIKE 'pov_EASYNEWS_SEARCH_%'""")
		for i in easynews_results: clear_property(i)
		return 'success'
	except: return 'failed'

