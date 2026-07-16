import requests
from caches.main_cache import cache_object
from modules import kodi_utils
# logger = kodi_utils.logger

ls, get_setting = kodi_utils.local_string, kodi_utils.get_setting
base_url = 'https://www.premiumize.me/api/'
timeout = 10.0
session = requests.Session()
session.custom_errors = requests.exceptions.ConnectionError, requests.exceptions.Timeout
session.mount('https://www.premiumize.me', requests.adapters.HTTPAdapter(max_retries=1))

class PremiumizeAPI:
	icon = 'premiumize.png'

	def __init__(self):
		self.token = get_setting('pm.token')
		session.headers.update(self.headers())

	def _request(self, method, path, data=None):
		url = base_url + path
		try: response = session.request(method, url, data=data, timeout=timeout)
		except session.custom_errors: return kodi_utils.notification('%s timeout' % __name__)
		if not response.ok: kodi_utils.logger(__name__, f"{response.reason}\n{response.url}")
		return response.json() if 'json' in response.headers.get('Content-Type', '') else response

	def _get(self, path):
		return self._request('get', path)

	def _post(self, path, data=None):
		return self._request('post', path, data=data)

	def headers(self):
		return {'Authorization': 'Bearer %s' % self.token}

	def days_remaining(self):
		from datetime import datetime
		try:
			account_info = self.account_info()
			expires = datetime.fromtimestamp(account_info['premium_until'])
			days = (expires - datetime.today()).days
		except: days = None
		return days

	def account_info(self):
		url = 'account/info'
		result = self._get(url)
		return result

	def item_listall(self):
		url = 'item/listall'
		result = self._get(url)
		return result['files']

	def delete_torrent(self, transfer_id):
		result = self.delete_object('transfer', transfer_id)
		return result

	def unrestrict_link(self, link):
		return link

	def check_cache(self, hashes):
		url = 'cache/check'
		data = {'items[]': hashes}
		result = self._post(url, data)
		return [h for h, cached in zip(hashes, result['response']) if cached]

	def instant_transfer(self, magnet):
		url = 'transfer/directdl'
		data = {'src': magnet}
		result = self._post(url, data)
		return result

	def create_transfer(self, magnet):
		url = 'transfer/create'
		data = {'src': magnet, 'folder_id': 0}
		result = self._post(url, data)
		return result.get('id', '')

	def parse_magnet_pack(self, magnet_url, info_hash):
		from modules.source_utils import supported_video_extensions
		try:
			extensions = supported_video_extensions()
			torrent_files = self.instant_transfer(magnet_url)
			return [
				{'link': item['link'],
				 'size': item['size'],
				 'filename': item['path'].split('/')[-1]}
				for item in torrent_files['content']
				if item['path'].lower().endswith(tuple(extensions))
			]
		except: pass

	def rename_cache_item(self, file_type, file_id, new_name):
		if file_type == 'folder': url = 'folder/rename'
		else: url = 'item/rename'
		data = {'id': file_id , 'name': new_name}
		result = self._post(url, data)
		return True if result is not None and result['status'] == 'success' else False

	def delete_object(self, object_type, object_id):
		url = '%s/delete' % object_type
		data = {'id': object_id}
		result = self._post(url, data)
		return True if result is not None and result['status'] == 'success' else False

	def get_item_details(self, item_id):
		string = 'pov_pm_item_details_%s' % item_id
		url = 'item/details'
		data = {'id': item_id}
		args = [url, data]
		return cache_object(self._post, string, args, 24)

	def downloads(self, cached=True):
		string = 'pov_pm_downloads'
		url = 'transfer/list'
		if cached: result = cache_object(self._get, string, url, 0.5)
		else: result = self._get(url)
		result = result['transfers']
		return result

	def user_cloud(self, cached=True):
		string = 'pov_pm_user_cloud'
		url = 'folder/list'
		if cached: result = cache_object(self._get, string, url, 0.5)
		else: result = self._get(url)
		result = result['content']
		return result

	def user_folder(self, folder_id):
		string = 'pov_pm_user_cloud_%s' % folder_id
		url = 'folder/list?id=%s' % folder_id
		result = cache_object(self._get, string, url, 0.5)
		result = result['content']
		return result

	def clear_cache(*args):
		from modules.kodi_utils import clear_property, path_exists, database_connect, maincache_db
		try:
			if not path_exists(maincache_db): return True
			from caches.debrid_cache import DebridCache
			dbcon = database_connect(maincache_db)
			dbcur = dbcon.cursor()
			# USER CLOUD
			try:
				dbcur.execute("""SELECT id FROM maincache WHERE id LIKE ?""", ('pov_pm_user_cloud%',))
				user_cloud_cache = [str(i[0]) for i in dbcur.fetchall()]
				if user_cloud_cache:
					dbcur.execute("""DELETE FROM maincache WHERE id LIKE ?""", ('pov_pm_user_cloud%',))
					for i in user_cloud_cache: clear_property(i)
					dbcon.commit()
				user_cloud_success = True
			except: user_cloud_success = False
			# DOWNLOAD LINKS
			try:
				dbcur.execute("""DELETE FROM maincache WHERE id = ?""", ('pov_pm_downloads',))
				clear_property('pov_pm_downloads')
				dbcon.commit()
				download_links_success = True
			except: download_links_success = False
			# HOSTERS
			try:
				dbcur.execute("""DELETE FROM maincache WHERE id = ?""", ('pov_pm_valid_hosts',))
				clear_property('pov_pm_valid_hosts')
				dbcon.commit()
				hoster_links_success = True
			except: hoster_links_success = False
			dbcon.close()
			# HASH CACHED STATUS
			try:
				DebridCache().clear_debrid_results('pm')
				hash_cache_status_success = True
			except: hash_cache_status_success = False
		except: return False
		if False in (user_cloud_success, download_links_success, hoster_links_success, hash_cache_status_success): return False
		return True

