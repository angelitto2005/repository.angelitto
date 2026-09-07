import re
import requests
from modules import kodi_utils
# logger = kodi_utils.logger

base_url = 'https://offcloud.com/api/'
custom_errors = requests.exceptions.ConnectionError, requests.exceptions.Timeout
session = requests.Session()
session.mount('https://offcloud.com', requests.adapters.HTTPAdapter(max_retries=1))

class OffcloudAPI:
	icon = 'offcloud.png'
	defaults_to_cloud = False

	def __init__(self):
		self.timeout = int(kodi_utils.get_setting('scrapers_timeout') or 10)
		self.token = kodi_utils.get_setting('oc.token')
		session.headers.update(self.headers())

	def _request(self, method, path, params=None, data=None):
		url = base_url + path
		try: response = session.request(method, url, params=params, json=data, timeout=self.timeout)
		except custom_errors: return kodi_utils.notification('%s timeout' % __name__)
		if not response.ok: kodi_utils.logger(__name__, f"{response.reason}\n{response.url}")
		return response.json() if 'json' in response.headers.get('Content-Type', '') else response

	def _get(self, path, params=None):
		return self._request('get', path, params=params)

	def _post(self, path, data=None):
		return self._request('post', path, data=data)

	def headers(self):
		return {'Authorization': 'Bearer %s' % self.token}

	def days_remaining(self):
		from datetime import date
		try:
			account_info = self.account_info()
			expires = date.fromisoformat(account_info['expiration_date'])
			days = (expires - date.today()).days
		except: days = None
		return days

	def account_info(self):
		url = 'account/info'
		result = self._get(url)
		return result

	def user_cloud(self):
		url = 'cloud/history'
		return self._get(url)

	def user_folder(self, folder_id):
		url = folder_id
		return self.torrent_info(url)

	def torrent_info(self, request_id):
		params = {'format': 'detailed'}
		url = 'cloud/explore/%s' % request_id
		result = self._get(url, params=params)
		return result

	def delete_torrent(self, request_id):
		url = 'cloud/remove/%s' % request_id
		result = self._get(url)
		return True if result is not None and result['success'] else False

	def unrestrict_link(self, link):
		return link

	def check_cache(self, hashes):
		pattern = re.compile(r'^[a-f0-9]{40}$', re.I)
		hashes = [(i, f"magnet:?xt=urn:btih:{i}") for i in hashes if pattern.match(i)]
		url = 'cache/info'
		data = {'urls': [i[1] for i in hashes]}
		result = self._post(url, data=data)
		return [h for h, i in zip((i[0] for i in hashes), result) if i['cached']]

	def instant_transfer(self, magnet):
		url = 'cache/download'
		data = {'url': magnet}
		result = self._post(url, data)
		return result

	def add_magnet(self, magnet):
		url = 'cloud'
		data = {'url': magnet}
		result = self._post(url, data=data)
		return result

	def create_transfer(self, magnet):
		result = self.add_magnet(magnet)
		return result.get('requestId', '')

	def parse_magnet_pack(self, magnet_url, info_hash):
		from modules.source_utils import supported_video_extensions
		try:
			extensions = tuple(supported_video_extensions())
			torrent_files = self.instant_transfer(magnet_url)
			return [
				{'link': item['url'],
				 'size': item['size'],
				 'filename': item['filename']}
				for item in torrent_files
				if item['filename'].lower().endswith(extensions)
			]
		except: pass

	def clear_cache(*args):
		from modules.kodi_utils import clear_property, path_exists, database_connect, maincache_db
		try:
			if not path_exists(maincache_db): return True
			from caches.debrid_cache import DebridCache
			dbcon = database_connect(maincache_db)
			dbcur = dbcon.cursor()
			# USER CLOUD
			try:
				dbcur.execute("""SELECT id FROM maincache WHERE id LIKE ?""", ('pov_oc_user_cloud%',))
				user_cloud_cache = [str(i[0]) for i in dbcur.fetchall()]
				if user_cloud_cache:
					for i in user_cloud_cache: clear_property(i)
					dbcur.execute("""DELETE FROM maincache WHERE id LIKE ?""", ('pov_oc_user_cloud%',))
					dbcon.commit()
				user_cloud_success = True
			except: user_cloud_success = False
			dbcon.close()
			# HASH CACHED STATUS
			try:
				DebridCache().delete_cache_single('oc')
				hash_cache_status_success = True
			except: hash_cache_status_success = False
		except: return False
		if False in (user_cloud_success, hash_cache_status_success): return False
		return True

