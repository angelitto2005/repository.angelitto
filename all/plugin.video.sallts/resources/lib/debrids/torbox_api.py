import requests
from threading import Thread
from caches.main_cache import cache_object
from modules import kodi_utils
# logger = kodi_utils.logger

ls, get_setting = kodi_utils.local_string, kodi_utils.get_setting
user_agent = 'SALTS/%s' % kodi_utils.get_addoninfo('version')
ip_url = 'https://api.ipify.org'
base_url = 'https://api.torbox.app/v1/api/'
timeout = 20.0
session = requests.Session()
session.custom_errors = requests.exceptions.ConnectionError, requests.exceptions.Timeout
session.mount('https://api.torbox.app', requests.adapters.HTTPAdapter(max_retries=1))

class TorBoxAPI:
	icon = 'torbox.png'

	def __init__(self):
		self.token = get_setting('tb.token')
		session.headers.update(self.headers())

	def _request(self, method, path, params=None, json=None, data=None):
		url = (base_url + path) if not path.startswith('http') else path
		try: response = session.request(method, url, params=params, json=json, data=data, timeout=timeout)
		except session.custom_errors: return kodi_utils.notification('%s timeout' % __name__)
		if not response.ok: kodi_utils.logger(__name__, f"{response.reason}\n{response.url}")
		response = response.json() if 'json' in response.headers.get('Content-Type', '') else response
		if 'data' in response and 'success' in response and not 'control' in path: response = response['data']
		return response

	def _get(self, url, params=None):
		return self._request('get', url, params=params)

	def _post(self, url, params=None, json=None, data=None):
		return self._request('post', url, params=params, json=json, data=data)

	def add_headers_to_url(self, url):
		return '|'.join((str(url), kodi_utils.urlencode(self.headers())))

	def headers(self):
		return {'User-Agent': user_agent, 'Authorization': 'Bearer %s' % self.token}

	def days_remaining(self):
		import datetime, time
		try:
			account_info = self.account_info()
			FormatDateTime = '%Y-%m-%dT%H:%M:%SZ'
			try: expires = datetime.datetime.strptime(account_info['premium_expires_at'], FormatDateTime)
			except: expires = datetime.datetime(*(time.strptime(account_info['premium_expires_at'], FormatDateTime)[0:6]))
			days = (expires - datetime.datetime.today()).days
		except: days = None
		return days

	def account_info(self):
		url = 'user/me'
		return self._get(url)

	def torrent_info(self, request_id):
		url = 'torrents/mylist?id=%s' % request_id
		return self._get(url)

	def nzb_info(self, request_id):
		url = 'usenet/mylist?id=%s' % request_id
		return self._get(url)

	def delete_torrent(self, request_id):
		data = {'torrent_id': request_id, 'operation': 'delete'}
		url = 'torrents/controltorrent'
		result = self._post(url, json=data)
		return True if not result is None and result['success'] else False

	def delete_usenet(self, request_id):
		data = {'usenet_id': request_id, 'operation': 'delete'}
		url = 'usenet/controlusenetdownload'
		result = self._post(url, json=data)
		return True if not result is None and result['success'] else False

	def delete_webdl(self, request_id):
		data = {'webdl_id': request_id, 'operation': 'delete'}
		url = 'webdl/controlwebdownload'
		result = self._post(url, json=data)
		return True if not result is None and result['success'] else False

	def unrestrict_link(self, file_id):
		try: user_ip = requests.get(ip_url, timeout=2.0).text
		except: user_ip = ''
		params = {'user_ip': user_ip} if user_ip else {}
		torrent_id, file_id = file_id.split(',')
		params.update({'token': self.token, 'torrent_id': torrent_id, 'file_id': file_id})
		url = 'torrents/requestdl'
		return self._get(url, params=params)

	def unrestrict_usenet(self, file_id):
		try: user_ip = requests.get(ip_url, timeout=2.0).text
		except: user_ip = ''
		params = {'user_ip': user_ip} if user_ip else {}
		usenet_id, file_id = file_id.split(',')
		params.update({'token': self.token, 'usenet_id': usenet_id, 'file_id': file_id})
		url = 'usenet/requestdl'
		return self._get(url, params=params)

	def unrestrict_webdl(self, file_id):
		try: user_ip = requests.get(ip_url, timeout=2.0).text
		except: user_ip = ''
		params = {'user_ip': user_ip} if user_ip else {}
		webdl_id, file_id = file_id.split(',')
		params.update({'token': self.token, 'web_id': webdl_id, 'file_id': file_id})
		url = 'webdl/requestdl'
		return self._get(url, params=params)

	def check_cache(self, hashes):
		data = {'hashes': hashes}
		url = 'torrents/checkcached'
		result = self._post(url, params={'format': 'list'}, json=data)
		return [i['hash'] for i in result]

	def add_magnet(self, magnet):
		data = {'magnet': magnet, 'seed': 3, 'allow_zip': 'false'}
		url = 'torrents/createtorrent'
		return self._post(url, data=data)

	def add_nzb(self, nzb, name=''):
		data = {'link': nzb}
		if name: data['name'] = name
		url = 'usenet/createusenetdownload'
		return self._post(url, data=data)

	def create_transfer(self, link, name=''):
		if link.startswith('magnet'): key, result = 'torrent_id', self.add_magnet(link)
		else: key, result = 'usenetdownload_id', self.add_nzb(link, name)
		return result.get(key, '') if result else ''

	def parse_magnet_pack(self, magnet_url, info_hash):
		from modules.source_utils import supported_video_extensions
		try:
			extensions = supported_video_extensions()
			torrent_id = self.create_transfer(magnet_url)
			torrent_files = self.torrent_info(torrent_id)
			return [
				{'link': '%d,%d' % (torrent_id, item['id']),
				 'size': item['size'],
				 'torrent_id': torrent_id,
				 'filename': item['short_name']}
				for item in torrent_files['files']
				if item['short_name'].lower().endswith(tuple(extensions))
			]
		except Exception as e:
			if torrent_id: self.delete_torrent(torrent_id)

	def resolve_nzb(self, nzb_url, info_hash, store_to_cloud, title, season, episode, nzb_info=None):
		from modules.source_utils import supported_video_extensions, seas_ep_filter, extras_filter
		try:
			extensions = supported_video_extensions()
			extras_filtering_list = tuple(i for i in extras_filter() if not i in title.lower())
			if not nzb_info:
				nzb_id = self.create_transfer(nzb_url)
				nzb_files = self.nzb_info(nzb_id)
			else: nzb_id, nzb_files = nzb_info['id'], nzb_info
			selected_files = []
			for i in nzb_files['files']:
				link, filename, size = '%d,%d' % (nzb_id, i['id']), i['short_name'].lower(), i['size']
				if filename.endswith('.m2ts'): raise Exception('_m2ts_check failed')
				if not filename.endswith(tuple(extensions)): continue
				if (seas_ep_filter(season, episode, filename)
					if season else
					not any(x in filename for x in extras_filtering_list)
				): selected_files += [{'link': link, 'size': size}]
			if not selected_files: return None
			if not season: selected_files.sort(key=lambda k: k['size'], reverse=True)
			file_key = next((i['link'] for i in selected_files), None)
			file_url = self.unrestrict_usenet(file_key)
			if not store_to_cloud: Thread(target=self.delete_usenet, args=(nzb_id,)).start()
			return file_url
		except Exception as e:
			kodi_utils.logger('main exception', str(e))
			if nzb_id: Thread(target=self.delete_usenet, args=(nzb_id,)).start()
			return None

	def user_cloud(self, request_id=None, check_cache=True, completed=True):
		string = 'salts_tb_user_cloud_info_%s' % request_id if request_id else 'salts_tb_user_cloud'
		url = 'torrents/mylist?id=%s' % request_id if request_id else 'torrents/mylist'
		if check_cache: result = cache_object(self._get, string, url, False, 0.5)
		else: result = self._get(url)
		if not request_id and completed: result = [i for i in result if i['download_finished'] and i['files']]
		return result

	def user_cloud_usenet(self, request_id=None, check_cache=True, completed=True):
		string = 'salts_tb_user_cloud_usenet_info_%s' % request_id if request_id else 'salts_tb_user_cloud_usenet'
		url = 'usenet/mylist?id=%s' % request_id if request_id else 'usenet/mylist'
		if check_cache: result = cache_object(self._get, string, url, False, 0.5)
		else: result = self._get(url)
		if not request_id and completed: result = [i for i in result if i['download_finished'] and i['files']]
		return result

	def user_cloud_webdl(self, request_id=None, check_cache=True, completed=True):
		string = 'salts_tb_user_cloud_webdl_info_%s' % request_id if request_id else 'salts_tb_user_cloud_webdl'
		url = 'webdl/mylist?id=%s' % request_id if request_id else 'webdl/mylist'
		if check_cache: result = cache_object(self._get, string, url, False, 0.5)
		else: result = self._get(url)
		if not request_id and completed: result = [i for i in result if i['download_finished'] and i['files']]
		return result

	def clear_cache(*args):
		from modules.kodi_utils import clear_property, path_exists, database_connect, maincache_db
		try:
			if not path_exists(maincache_db): return True
			from caches.debrid_cache import DebridCache
			dbcon = database_connect(maincache_db)
			dbcur = dbcon.cursor()
			try:
				dbcur.execute("""DELETE FROM maincache WHERE id = ?""", ('torbox_usenet_queries',))
				clear_property('torbox_usenet_queries')
				dbcon.commit()
				usenet_queries_success = True
			except: usenet_queries_success = False
			# USER CLOUD
			try:
				dbcur.execute("""SELECT id FROM maincache WHERE id LIKE ?""", ('salts_tb_user_cloud%',))
				user_cloud_cache = [str(i[0]) for i in dbcur.fetchall()]
				if user_cloud_cache:
					dbcur.execute("""DELETE FROM maincache WHERE id LIKE ?""", ('salts_tb_user_cloud%',))
					for i in user_cloud_cache: clear_property(i)
					dbcon.commit()
				user_cloud_success = True
			except: user_cloud_success = False
			dbcon.close()
			# HASH CACHED STATUS
			try:
				DebridCache().clear_debrid_results('tb')
				hash_cache_status_success = True
			except: hash_cache_status_success = False
		except: return False
		if False in (usenet_queries_success, user_cloud_success, hash_cache_status_success): return False
		return True

