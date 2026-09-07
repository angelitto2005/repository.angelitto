import requests
from modules import kodi_utils
# logger = kodi_utils.logger

ip_url = 'https://api.ipify.org'
base_url = 'https://api.torbox.app/v1/api/'
custom_errors = requests.exceptions.ConnectionError, requests.exceptions.Timeout
session = requests.Session()
session.mount('https://api.torbox.app', requests.adapters.HTTPAdapter(max_retries=1))

class TorBoxAPI:
	icon = 'torbox.png'
	defaults_to_cloud = True

	def __init__(self):
		self.timeout = int(kodi_utils.get_setting('scrapers_timeout') or 10)
		self.token = kodi_utils.get_setting('tb.token')
		session.headers.update(self.headers())

	def _request(self, method, path, params=None, json=None, data=None):
		url = base_url + path
		try: response = session.request(method, url, params=params, json=json, data=data, timeout=self.timeout)
		except custom_errors: return kodi_utils.notification('%s timeout' % __name__)
		if not response.ok: kodi_utils.logger(__name__, f"{response.reason}\n{response.url}")
		response = response.json() if 'json' in response.headers.get('Content-Type', '') else response
		if not self._is_control(path) and 'data' in response and 'success' in response: response = response['data']
		return response

	def _get(self, path, params=None):
		return self._request('get', path, params=params)

	def _post(self, path, params=None, json=None, data=None):
		return self._request('post', path, params=params, json=json, data=data)

	def _is_control(self, path):
		return any(i in path for i in ('/control', '/edit'))

	def headers(self):
		return {'Authorization': 'Bearer %s' % self.token}

	def days_remaining(self):
		from datetime import datetime, timezone
		try:
			account_info = self.account_info()
			expires = datetime.fromisoformat(account_info['premium_expires_at'].replace('Z', '+00:00'))
			days = (expires - datetime.now(timezone.utc)).days
		except: days = None
		return days

	def account_info(self):
		url = 'user/me'
		return self._get(url)

	def user_cloud(self, mediatype):
		url = '%s/mylist?bypass_cache=true' % mediatype
		return self._get(url)

	def user_folder(self, mediatype, request_id):
		url = '%s/mylist?id=%s' % (mediatype, request_id)
		return self._get(url)

	def torrent_info(self, request_id, path='torrents'):
		if 'usenet' in path: url = 'usenet/mylist?id=%s' % request_id
		else: url = 'torrents/mylist?id=%s' % request_id
		return self._get(url)

	def toggle_airlock(self, mediatype, request_id, airlock_value):
		if 'usenet' in mediatype: path, key = 'usenet/editusenetdownload', 'usenet_download_id'
		elif 'webdl' in mediatype: path, key = 'webdl/editwebdownload', 'webdl_id'
		else: path, key = 'torrents/edittorrent', 'torrent_id'
		data = {key: request_id, 'airlocked': airlock_value in ('true', True)}
		result = self._request('put', path, json=data)
		return True if result is not None and result['success'] else False

	def delete_torrent(self, request_id):
		if 'usenet' in request_id: path, key = 'usenet/controlusenetdownload', 'usenet_id'
		elif 'webdl' in request_id: path, key = 'webdl/controlwebdownload', 'webdl_id'
		else: path, key = 'torrents/controltorrent', 'torrent_id'
		ids = request_id.split(',')
		data = {key: int(ids[0]), 'operation': 'delete'}
		result = self._post(path, json=data)
		return True if result is not None and result['success'] else False

	def unrestrict_link(self, file_id):
		if 'usenet' in file_id: path, key = 'usenet/requestdl', 'usenet_id'
		elif 'webdl' in file_id: path, key = 'webdl/requestdl', 'web_id'
		else: path, key = 'torrents/requestdl', 'torrent_id'
		ids = file_id.split(',')
		params = {key: ids[0], 'file_id': ids[1], 'token': self.token}
		try: user_ip = requests.get(ip_url, timeout=2.0).text.strip()
		except: user_ip = ''
		if user_ip: params['user_ip'] = user_ip
		return self._get(path, params=params)

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
			extensions = tuple(supported_video_extensions())
			path = 'torrents' if magnet_url.startswith('magnet') else 'usenet'
			torrent_id = self.create_transfer(magnet_url)
			torrent_files = self.torrent_info(torrent_id, path)
			return [
				{'link': '%s,%s,%s' % (torrent_id, item['id'], path),
				 'size': item['size'],
				 'torrent_id': '%s,%s' % (torrent_id, path),
				 'filename': item['short_name']}
				for item in torrent_files['files']
				if item['short_name'].lower().endswith(extensions)
			]
		except Exception as e:
			if torrent_id: self.delete_torrent('%s,%s' % (torrent_id, path))

	def clear_cache(*args):
		from modules.kodi_utils import clear_property, path_exists, database_connect, maincache_db
		try:
			if not path_exists(maincache_db): return True
			from caches.debrid_cache import DebridCache
			dbcon = database_connect(maincache_db)
			dbcur = dbcon.cursor()
			# USER CLOUD
			try:
				dbcur.execute("""SELECT id FROM maincache WHERE id LIKE ?""", ('pov_tb_user_cloud%',))
				user_cloud_cache = [str(i[0]) for i in dbcur.fetchall()]
				if user_cloud_cache:
					for i in user_cloud_cache: clear_property(i)
					dbcur.execute("""DELETE FROM maincache WHERE id LIKE ?""", ('pov_tb_user_cloud%',))
					dbcon.commit()
				user_cloud_success = True
			except: user_cloud_success = False
			dbcon.close()
			# HASH CACHED STATUS
			try:
				DebridCache().delete_cache_single('tb')
				hash_cache_status_success = True
			except: hash_cache_status_success = False
		except: return False
		if False in (user_cloud_success, hash_cache_status_success): return False
		return True

