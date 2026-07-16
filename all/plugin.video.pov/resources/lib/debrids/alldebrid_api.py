import requests
from caches.main_cache import cache_object
from modules import kodi_utils
# logger = kodi_utils.logger

ls, get_setting = kodi_utils.local_string, kodi_utils.get_setting
base_url = 'https://api.alldebrid.com/'
timeout = 10.0
session = requests.Session()
session.custom_errors = requests.exceptions.ConnectionError, requests.exceptions.Timeout
session.mount('https://api.alldebrid.com', requests.adapters.HTTPAdapter(max_retries=1))

class AllDebridAPI:
	icon = 'alldebrid.png'

	@staticmethod
	def flatten_magnet_files(files_list):
		def flatten(items):
			for i in items:
				if not isinstance(i, dict): continue
				if 'e' in i: flatten(i['e'])
				else: files_append(i)
		files = []
		files_append = files.append
		flatten(files_list)
		return files

	def __init__(self):
		self.token = get_setting('ad.token')
		session.headers.update(self.headers())

	def _request(self, method, path, params=None, data=None):
		url = base_url + path
		try: response = session.request(method, url, params=params, data=data, timeout=timeout)
		except session.custom_errors: return kodi_utils.notification('%s timeout' % __name__)
		if not response.ok: kodi_utils.logger(__name__, f"{response.reason}\n{response.url}")
		response = response.json() if 'json' in response.headers.get('Content-Type', '') else response
		if 'data' in response and response.get('status') == 'success': response = response['data']
		return response

	def _get(self, path, params=None):
		return self._request('get', path, params=params)

	def _post(self, path, data=None):
		return self._request('post', path, data=data)

	def headers(self):
		return {'Authorization': 'Bearer %s' % self.token}

	def days_remaining(self):
		from datetime import datetime
		try:
			account_info = self.account_info()['user']
			expires = datetime.fromtimestamp(account_info['premiumUntil'])
			days = (expires - datetime.today()).days
		except: days = None
		return days

	def account_info(self):
		url = 'v4/user'
		result = self._get(url)
		return result

	def torrent_info(self, transfer_id):
		url = 'v4.1/magnet/status'
		params = {'id': transfer_id}
		result = self._get(url, params)
		result = result['magnets']
		return result

	def delete_torrent(self, transfer_id):
		url = 'v4/magnet/delete'
		params = {'id': transfer_id}
		result = self._get(url, params)
		return True if result is not None and 'error' not in result else False

	def unrestrict_link(self, link):
		url = 'v4/link/unlock'
		params = {'link': link}
		result = self._get(url, params)
		try: return result['link']
		except: return None

	def check_cache(self, hashes):
		data = {'v4/magnets[]': hashes}
		result = self._post('magnet/instant', data)
		return result

	def create_transfer(self, magnet):
		url = 'v4/magnet/upload'
		params = {'magnet': magnet}
		result = self._get(url, params)
		result = result['magnets'][0]
		return result.get('id', '')

	def parse_magnet_pack(self, magnet_url, info_hash, errors=False):
		from modules.source_utils import supported_video_extensions
		try:
			extensions = supported_video_extensions()
			torrent_id = self.create_transfer(magnet_url)
			for key in ['completionDate'] * 3:
				kodi_utils.sleep(500)
				torrent_info = self.torrent_info(torrent_id)
				if torrent_info[key]: break
			else: raise Exception('alldebrid uncached magnet')
			torrent_info['links'] = self.flatten_magnet_files(torrent_info['files'])
			return [
				{'link': item['l'],
				 'size': item['s'],
				 'torrent_id': torrent_id,
				 'filename': item['n']}
				for item in torrent_info['links']
				if item['n'].lower().endswith(tuple(extensions))
			]
		except Exception as e:
			if torrent_id: self.delete_torrent(torrent_id)
			if errors: raise

	def downloads(self):
		url = 'v4/user/history'
		string = 'pov_ad_downloads'
		return cache_object(self._get, string, url, 0.5)

	def user_cloud(self, completed=True):
		url = 'v4.1/magnet/status'
		string = 'pov_ad_user_cloud'
		result = cache_object(self._get, string, url, 0.5)
		if completed: result['magnets'] = [i for i in result['magnets'] if i['statusCode'] == 4]
		return result

	def clear_cache(self):
		from modules.kodi_utils import clear_property, path_exists, database_connect, maincache_db
		try:
			if not path_exists(maincache_db): return True
			from caches.debrid_cache import DebridCache
			dbcon = database_connect(maincache_db)
			dbcur = dbcon.cursor()
			# USER CLOUD
			try:
				dbcur.execute("""DELETE FROM maincache WHERE id = ?""", ('pov_ad_user_cloud',))
				clear_property('pov_ad_user_cloud')
				dbcon.commit()
				user_cloud_success = True
			except: user_cloud_success = False
			# DOWNLOAD LINKS
			try:
				dbcur.execute("""DELETE FROM maincache WHERE id = ?""", ('pov_ad_downloads',))
				clear_property('pov_ad_downloads')
				dbcon.commit()
				download_links_success = True
			except: download_links_success = False
			# HOSTERS
			try:
				dbcur.execute("""DELETE FROM maincache WHERE id = ?""", ('pov_ad_valid_hosts',))
				clear_property('pov_ad_valid_hosts')
				dbcon.commit()
				hoster_links_success = True
			except: hoster_links_success = False
			dbcon.close()
			# HASH CACHED STATUS
			try:
				DebridCache().clear_debrid_results('ad')
				hash_cache_status_success = True
			except: hash_cache_status_success = False
		except: return False
		if False in (user_cloud_success, download_links_success, hoster_links_success, hash_cache_status_success): return False
		return True

