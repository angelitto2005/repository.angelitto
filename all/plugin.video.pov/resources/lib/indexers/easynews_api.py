import re
import json
import requests
from urllib.parse import urlencode, quote
from caches.main_cache import cache_object
from modules.kodi_utils import get_setting
from modules.source_utils import supported_video_extensions
# from modules.kodi_utils import logger

timeout = 10.0
session = requests.Session()
session.mount('https://', requests.adapters.HTTPAdapter(max_retries=1))

def video_extensions():
	return (
		'dvr-ms,bdmv,bivx,disc,divx,h264,m2ts,mk3d,mpeg,mpls,pxml,rmvb,svq3,webm,xspf,xvid,'
		'3g2,3gp,asf,asx,avc,avi,avs,bdm,bin,dat,evo,f4v,fli,flv,ifo,img,iso,m2t,m2v,m4v,mkv,mov,mp4,mpd,mpg,mpl,'
		'mts,nrg,nsv,nuv,ogm,ogv,pls,pva,pvr,rcv,rec,rss,sdp,trp,udf,url,vc1,vdr,viv,vob,vp3,wmv,wpl,wtv,xsp,'
		'dv,qt,rm,tp,ts,ty' # maybe not needed anymore, keep for reference
	)

def search_params():
	return {
		'pby': 350, 'pno': 1, 'spamf': 1, 'u': '1', 'sb': 1, 'gx': 1, 'st': 'adv', 'sS': 3,
		's1': 'relevance', 's1d': '-', 's2': 'dsize', 's2d': '-', 's3': 'dtime', 's3d': '-',
		'fty[]': 'VIDEO', 'fex': ','.join(supported_video_extensions())
	}

class EasyNewsAPI:
	def __init__(self):
		self.base_url = 'https://members.easynews.com'
		self.search_link = '/2.0/search/solr-search/advanced'
		self.account_link = 'https://account.easynews.com/editinfo.php'
		self.usage_link = 'https://account.easynews.com/usageview.php'
		self.username = get_setting('easynews_user')
		self.password = get_setting('easynews_password')
		self.moderation = 1 if get_setting('easynews_moderation') == 'true' else 0

	def _get(self, url, params=None):
		response = session.get(url, auth=(self.username, self.password), params=params, timeout=timeout)
		try: return json.loads(response.text)
		except: return response.text

	def account_info(self):
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

	def unrestrict_link(self, url_dl):
		response = session.get(url_dl, auth=(self.username, self.password), stream=True, timeout=timeout*3)
		if not response.ok: return None
		chunk = next(response.iter_content(chunk_size=1048576), b'')
		if len(chunk): resolved_link = response.url # direct/unrestricted link
		else: resolved_link = None
		return resolved_link

	def search(self, query, expiration=48):
		self.params = {'gps': query, 'safeO': self.moderation}
		string = 'pov_easynews_search_%s' % urlencode(self.params)
		url = self.base_url + self.search_link
		return cache_object(self._process_search, string, url, expiration)

	def _process_search(self, url):
		self.params.update(search_params())
		results = self._get(url, self.params)
		if not isinstance(results.get('data'), list): return []
		args = [results.get(i) for i in ('data', 'downURL', 'dlFarm', 'dlPort')]
		return self._process_files(*args)

	def _process_files(self, files, down_url, dl_farm, dl_port):
		sources = []
		sources_append = sources.append
		for item in files:
			try:
				if re.match(r'^\d+s', item['14']) or re.match(r'^[0-5]m', item['14']): continue
				if 'type' in item and item['type'].upper() != 'VIDEO': continue
				if 'virus' in item and item['virus']: continue
				post_hash, size, post_title, ext = [item[i] for i in ('0', '4', '10', '11')]
				language = item['alangs'] if 'alangs' in item and item['alangs'] else ''
				thumbnail = 'https://th.easynews.com/thumbnails-%s/pr-%s.jpg' % (post_hash[0:3], post_hash[:-4])
				url_dl = down_url + quote('/%s/%s/%s%s/%s%s' % (dl_farm, dl_port, post_hash, ext, post_title, ext))
				sources_append({
					'version': 'version2', 'full_item': item, 'thumbnail': thumbnail, 'url_dl': url_dl,
					'name': post_title, 'size': size, 'rawSize': item['rawSize'], 'language': language
				})
			except: pass
		return sources

	def clear_cache(*args):
		from modules.kodi_utils import clear_property, path_exists, database_connect, maincache_db
		try:
			if not path_exists(maincache_db): return True
			dbcon = database_connect(maincache_db, isolation_level=None)
			dbcur = dbcon.cursor()
			dbcur.execute("""PRAGMA synchronous = OFF""")
			dbcur.execute("""PRAGMA journal_mode = OFF""")
			dbcur.execute("""SELECT id FROM maincache WHERE id LIKE 'pov_easynews_search_%'""")
			easynews_results = [str(i[0]) for i in dbcur.fetchall()]
			if not easynews_results: return True
			for i in easynews_results: clear_property(i)
			dbcur.execute("""DELETE FROM maincache WHERE id LIKE 'pov_easynews_search_%'""")
			return True
		except: return False

