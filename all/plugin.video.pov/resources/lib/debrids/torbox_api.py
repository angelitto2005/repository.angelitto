import requests
from caches.main_cache import cache_object
from modules import kodi_utils
# logger = kodi_utils.logger

ls, get_setting = kodi_utils.local_string, kodi_utils.get_setting
user_agent = 'POV/%s' % kodi_utils.get_addoninfo('version')
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
		url = base_url + path
		try: response = session.request(method, url, params=params, json=json, data=data, timeout=timeout)
		except session.custom_errors: return kodi_utils.notification('%s timeout' % __name__)
		if not response.ok: kodi_utils.logger(__name__, f"{response.reason}\n{response.url}")
		response = response.json() if 'json' in response.headers.get('Content-Type', '') else response
		if not self._is_control(path) and 'data' in response and 'success' in response: response = response['data']
		return response

	def _get(self, path, params=None):
		return self._request('get', path, params=params)

	def _post(self, path, params=None, json=None, data=None):
		return self._request('post', path, params=params, json=json, data=data)

	def _is_control(self, path):
		return any(i in path for i in ('control', 'edit'))

	def headers(self):
		return {'User-Agent': user_agent, 'Authorization': 'Bearer %s' % self.token}

	def get_function(self, request_id, delete=False):
		action = 'delete_%s' if delete else 'unrestrict_%s'
		if 'usenet' in request_id: mediatype = 'usenet'
		elif 'webdl' in request_id: mediatype = 'webdl'
		else: mediatype = 'torrent' if delete else 'link'
		return getattr(self, action % mediatype)

	def days_remaining(self):
		from datetime import datetime
		try:
			account_info = self.account_info()
			expires = datetime.fromisoformat(account_info['premium_expires_at'].replace('Z', '+00:00'))
			days = (expires.astimezone().date() - datetime.today().date()).days
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
		if isinstance(request_id, str): ids = request_id.split(',')
		else: ids = [request_id]
		data = {'torrent_id': int(ids[0]), 'operation': 'delete'}
		url = 'torrents/controltorrent'
		result = self._post(url, json=data)
		return True if result is not None and result['success'] else False

	def delete_usenet(self, request_id):
		if isinstance(request_id, str): ids = request_id.split(',')
		else: ids = [request_id]
		data = {'usenet_id': int(ids[0]), 'operation': 'delete'}
		url = 'usenet/controlusenetdownload'
		result = self._post(url, json=data)
		return True if result is not None and result['success'] else False

	def delete_webdl(self, request_id):
		if isinstance(request_id, str): ids = request_id.split(',')
		else: ids = [request_id]
		data = {'webdl_id': int(ids[0]), 'operation': 'delete'}
		url = 'webdl/controlwebdownload'
		result = self._post(url, json=data)
		return True if result is not None and result['success'] else False

	def unrestrict_link(self, file_id):
		try: user_ip = requests.get(ip_url, timeout=2.0).text
		except: user_ip = ''
		params = {'user_ip': user_ip} if user_ip else {}
		ids = file_id.split(',')
		params.update({'token': self.token, 'torrent_id': ids[0], 'file_id': ids[1]})
		url = 'torrents/requestdl'
		return self._get(url, params=params)

	def unrestrict_usenet(self, file_id):
		try: user_ip = requests.get(ip_url, timeout=2.0).text
		except: user_ip = ''
		params = {'user_ip': user_ip} if user_ip else {}
		ids = file_id.split(',')
		params.update({'token': self.token, 'usenet_id': ids[0], 'file_id': ids[1]})
		url = 'usenet/requestdl'
		return self._get(url, params=params)

	def unrestrict_webdl(self, file_id):
		try: user_ip = requests.get(ip_url, timeout=2.0).text
		except: user_ip = ''
		params = {'user_ip': user_ip} if user_ip else {}
		ids = file_id.split(',')
		params.update({'token': self.token, 'web_id': ids[0], 'file_id': ids[1]})
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
			if magnet_url.startswith('magnet'):
				torrent_files = self.torrent_info(torrent_id)
			else: torrent_files = self.nzb_info(torrent_id)
			return [
				{'link': '%s,%s' % (torrent_id, item['id']),
				 'size': item['size'],
				 'torrent_id': torrent_id,
				 'filename': item['short_name']}
				for item in torrent_files['files']
				if item['short_name'].lower().endswith(tuple(extensions))
			]
		except Exception as e:
			if torrent_id: self.delete_torrent(torrent_id)

	def user_cloud(self, mediatype, cached=True):
		string = 'pov_tb_user_cloud_%s' % mediatype
		url = '%s/mylist?bypass_cache=true' % mediatype
		if cached: result = cache_object(self._get, string, url, 0.5)
		else: result = self._get(url)
		result = [i for i in result if i['download_finished'] and i['files']]
		for i in result: i['folder_id'] = '%s,%s' % (i['id'], mediatype)
		return result

	def user_folder(self, mediatype, request_id):
		string = 'pov_tb_user_cloud_%s_%s' % (mediatype, request_id)
		url = '%s/mylist?id=%s' % (mediatype, request_id)
		result = cache_object(self._get, string, url, 0.5)
		for i in result['files']: i['link'] = '%s,%s,%s' % (request_id, i['id'], mediatype)
		result = result['files']
		return result

	def toggle_airlock(self, mediatype, request_id, airlock_value):
		if 'usenet' in mediatype: path, key = 'usenet/editusenetdownload', 'usenet_download_id'
		elif 'webdl' in mediatype: path, key = 'webdl/editwebdownload', 'webdl_id'
		else: path, key = 'torrents/edittorrent', 'torrent_id'
		data = {key: request_id, 'airlocked': airlock_value in ('true', True)}
		result = self._request('put', path, json=data)
		return True if result is not None and result['success'] else False

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
				dbcur.execute("""SELECT id FROM maincache WHERE id LIKE ?""", ('pov_tb_user_cloud%',))
				user_cloud_cache = [str(i[0]) for i in dbcur.fetchall()]
				if user_cloud_cache:
					dbcur.execute("""DELETE FROM maincache WHERE id LIKE ?""", ('pov_tb_user_cloud%',))
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

