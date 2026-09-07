import requests
from modules import kodi_utils
# logger = kodi_utils.logger

base_url = 'https://app.real-debrid.com/rest/1.0/'
custom_errors = requests.exceptions.ConnectionError, requests.exceptions.Timeout
session = requests.Session()
session.mount('https://app.real-debrid.com', requests.adapters.HTTPAdapter(max_retries=1))

class RealDebridAPI:
	icon = 'realdebrid.png'
	defaults_to_cloud = True

	def __init__(self):
		self.timeout = int(kodi_utils.get_setting('scrapers_timeout') or 10)
		self.token = kodi_utils.get_setting('rd.token')
		session.headers.update(self.headers())

	def _request(self, method, path, data=None):
		url = base_url + path
		try: response = session.request(method, url, data=data, timeout=self.timeout)
		except custom_errors: return kodi_utils.notification('%s timeout' % __name__)
		if response.status_code in (401,) and self.refresh_token() is True:
			response.request.headers['Authorization'] = 'Bearer %s' % self.token
			response = session.send(response.request, timeout=self.timeout)
		if not response.ok: kodi_utils.logger(__name__, f"{response.reason}\n{response.url}")
		return response.json() if response.content else response

	def _get(self, path):
		return self._request('get', path)

	def _post(self, path, data=None):
		return self._request('post', path, data=data)

	def headers(self):
		return {'Authorization': 'Bearer %s' % self.token}

	def refresh_token(self):
		try:
			data = {'grant_type': 'http://oauth.net/grant_type/device/1.0'}
			data['code'] = kodi_utils.get_setting('rd.refresh')
			data['client_secret'] = kodi_utils.get_setting('rd.secret')
			data['client_id'] = kodi_utils.get_setting('rd.client_id')
			response = requests.post('https://app.real-debrid.com/oauth/v2/token', data=data).json()
			self.token, refresh = response['access_token'], response['refresh_token']
			session.headers.update(self.headers())
			kodi_utils.set_setting('rd.token', self.token)
			kodi_utils.set_setting('rd.refresh', refresh)
		except Exception as e: kodi_utils.logger('refresh_token error', str(e))
		else: return True
		return False

	def days_remaining(self):
		from datetime import datetime
		try:
			account_info = self.account_info()
			expires = datetime.fromisoformat(account_info['expiration'].replace('Z', '+00:00'))
			days = (expires.astimezone().date() - datetime.today().date()).days
		except: days = None
		return days

	def account_info(self):
		url = 'user'
		result = self._get(url)
		return result

	def downloads(self):
		url = 'downloads?limit=500'
		return self._get(url)

	def user_cloud(self):
		url = 'torrents?limit=500'
		return self._get(url)

	def user_folder(self, folder_id):
		url = folder_id
		return self.torrent_info(url)

	def torrent_info(self, folder_id):
		url = 'torrents/info/%s' % folder_id
		result = self._get(url)
		return result

	def delete_torrent(self, folder_id):
		url = 'torrents/delete/%s' % folder_id
		result = self._request('delete', url)
		return True if result is not None and result.ok else False

	def delete_download(self, download_id):
		url = 'downloads/delete/%s' % download_id
		result = self._request('delete', url)
		return True if result is not None and result.ok else False

	def unrestrict_link(self, link):
		url = 'unrestrict/link'
		post_data = {'link': link}
		result = self._post(url, post_data)
		if result['download'].lower().endswith(('.rar','.zip')):
			raise Exception('link error\n%s' % result['download'])
		try: return result['download']
		except: return None

	def check_cache(self, hashes):
		hash_string = '/'.join(hashes)
		url = 'torrents/instantAvailability/%s' % hash_string
		result = self._get(url)
		return result

	def add_torrent_select(self, torrent_id, file_ids):
		self.clear_cache()
		url = 'torrents/selectFiles/%s' % torrent_id
		post_data = {'files': file_ids}
		result = self._post(url, post_data)
		return result

	def add_magnet(self, magnet):
		url = 'torrents/addMagnet'
		post_data = {'magnet': magnet}
		result = self._post(url, post_data)
		return result

	def create_transfer(self, magnet):
		result = self.add_magnet(magnet)
		if result and 'id' in result:
			torrent_id = result['id']
			self.add_torrent_select(torrent_id, 'all')
		else: torrent_id = ''
		return torrent_id

	def parse_magnet_pack(self, magnet_url, info_hash, errors=False):
		from modules.source_utils import supported_video_extensions
		try:
			extensions = tuple(supported_video_extensions())
			torrent_id = self.create_transfer(magnet_url)
			if not torrent_id: raise Exception('real debrid null magnet')
			for key in ['ended'] * 3:
				kodi_utils.sleep(500)
				torrent_info = self.torrent_info(torrent_id)
				if key in torrent_info: break
			else: raise Exception('real debrid uncached magnet')
			selected = (i for i in torrent_info['files'] if i['selected'])
			return [
				{'link': link,
				 'size': item['bytes'],
				 'torrent_id': torrent_id,
				 'filename': item['path'].replace('/', '')}
				for item, link in zip(selected, torrent_info['links'])
				if item['path'].lower().endswith(extensions)
			]
		except Exception as e:
			if torrent_id: self.delete_torrent(torrent_id)
			if errors: raise

	def clear_cache(*args):
		from modules.kodi_utils import clear_property, path_exists, database_connect, maincache_db
		try:
			if not path_exists(maincache_db): return True
			from caches.debrid_cache import DebridCache
			dbcon = database_connect(maincache_db)
			dbcur = dbcon.cursor()
			# USER CLOUD
			try:
				dbcur.execute("""SELECT id FROM maincache WHERE id LIKE ?""", ('pov_rd_user_cloud%',))
				user_cloud_cache = [str(i[0]) for i in dbcur.fetchall()]
				if user_cloud_cache:
					for i in user_cloud_cache: clear_property(i)
					dbcur.execute("""DELETE FROM maincache WHERE id LIKE ?""", ('pov_rd_user_cloud%',))
					dbcon.commit()
				user_cloud_success = True
			except: user_cloud_success = False
			# DOWNLOAD LINKS
			try:
				clear_property('pov_rd_downloads')
				dbcur.execute("""DELETE FROM maincache WHERE id = ?""", ('pov_rd_downloads',))
				dbcon.commit()
				download_links_success = True
			except: download_links_success = False
			# HOSTERS
			try:
				clear_property('pov_rd_valid_hosts')
				dbcur.execute("""DELETE FROM maincache WHERE id = ?""", ('pov_rd_valid_hosts',))
				dbcon.commit()
				hoster_links_success = True
			except: hoster_links_success = False
			dbcon.close()
			# HASH CACHED STATUS
			try:
				DebridCache().delete_cache_single('rd')
				hash_cache_status_success = True
			except: hash_cache_status_success = False
		except: return False
		if False in (user_cloud_success, download_links_success, hoster_links_success, hash_cache_status_success): return False
		return True

def tio_check_cache(imdb, season, episode):
	import re, secrets
	from magneto.modules.client import randomagent
	if str(season).isdigit(): url = 'series/%s:%s:%s.json' % (imdb, season, episode)
	else: url = 'movie/%s.json' % (imdb)
	params = 'realdebrid=%s' % str.upper(secrets.token_urlsafe(39)[:52])
	url = 'https://torrentio.strem.fun/debridoptions=nodownloadlinks,nocatalog|%s/stream/%s' % (params, url)
	headers = {'User-Agent': randomagent(), 'Accept': 'application/json'}
	pattern = re.compile(r'\b\w{40}\b')
	try:
		results = requests.get(url, headers=headers, timeout=7.05)
		if not results.ok: results.raise_for_status()
		files = results.json()['streams']
		return [pattern.findall(file['url'])[-1] for file in files if '+' in file['name'] and 'url' in file]
	except Exception as e: kodi_utils.logger('tio error', str(e))

