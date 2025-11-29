# -*- coding: utf-8 -*-
from modules.kodi_utils import progress_dialog, notification, sleep, make_session
from caches.tmdb_lists import tmdb_lists_cache_object, tmdb_lists_cache
from caches.settings_cache import get_setting, set_setting
from modules.utils import copy2clip, make_qrcode, make_tinyurl, make_thread_list
# from modules.kodi_utils import logger

session = make_session('https://api.themoviedb.org')

class TMDbListAPI:
	def __init__(self):
		self.base_url = 'https://api.themoviedb.org/4'
		self.read_access_token = 'eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiJiMzcwYjYwNDQ3NzM3NzYyY2EzODQ1N2JkNzc1NzliMyIsIm5iZiI6MTY1MDIzNTExOS4wOSwic3ViIjoiNjI1Yzk2ZWZiYjI2MDIxMT'\
								'gzNTQ0MTZhIiwic2NvcGVzIjpbImFwaV9yZWFkIl0sInZlcnNpb24iOjF9.8uevSMakSrdZb1t0ze4OIxq6PoL4N6DZN4VVkKUCayg'
	
	def auth(self):
		import requests
		headers = {'accept': 'application/json', 'content-type': 'application/json', 'Authorization': 'Bearer %s' % self.read_access_token}
		data = requests.post('%s/auth/request_token' % self.base_url, headers=headers, timeout=20).json()
		if not 'success' in data: return notification('Failed to Auth Account')
		request_token = data['request_token']
		token_url = 'https://www.themoviedb.org/auth/access?request_token=%s' % request_token
		qr_code = make_qrcode(token_url) or ''
		short_url = make_tinyurl(token_url)
		copy2clip(short_url)
		if short_url: p_dialog_insert = '[CR]OR visit this URL: [B]%s[/B]' % short_url
		else: p_dialog_insert = ''
		progressDialog = progress_dialog(heading='TMDb Account Authorization', icon=qr_code)
		count, success = 72, None
		while not progressDialog.iscanceled() and count >= 0 and success == None:
			try:
				count -= 1
				response = requests.post('%s/auth/access_token' % self.base_url, json={'request_token': request_token}, headers=headers, timeout=20).json()
				if response.get('success') and response.get('access_token'): success = True
				progressDialog.update('Please Scan the QR Code%s[CR]Confirm Access to your TMDb Account' % p_dialog_insert, count)
				sleep(2500)
			except: success = False
		progressDialog.close()
		if success:
			set_setting('tmdb.token', response['access_token'])
			set_setting('tmdb.account_id', response['account_id'])
			notice = 'Success'
		else: notice = 'Failed'
		tmdb_lists_cache.clear_all()
		notification(notice)
	
	def revoke(self):
		import requests
		headers = {'accept': 'application/json', 'content-type': 'application/json', 'Authorization': 'Bearer %s' % self.read_access_token}
		data = requests.delete('%s/auth/access_token' % self.base_url, json={'access_token': self.read_access_token}, headers=headers, timeout=20).json()
		if not 'success' in data: notice = 'Failed to Revoke Account Auth'
		else:
			notice = 'Success Auth Revoke'
			set_setting('tmdb.token', 'empty_setting')
			set_setting('tmdb.account_id', 'empty_setting')
			tmdb_lists_cache.clear_all()
		return notification(notice)

	def get_user_lists(self):
		def _process_multi(page_no):
			try: results_extend(self.request_data(url % (self.base_url, account_id, page_no))['results'])
			except: pass
		def _process(dummy):
			result = self.request_data(url % (self.base_url, account_id, 1))
			results_extend(result['results'])
			total_pages = result['total_pages']
			if total_pages > 1:
				threads = list(make_thread_list(_process_multi, range(2, total_pages + 1)))
				[i.join() for i in threads]
			return results
		account_id = get_setting('fenlight.tmdb.account_id')
		string = 'get_user_lists'
		url = '%s/account/%s/lists?page=%s'
		results = []
		results_extend = results.extend
		return tmdb_lists_cache_object(_process, string, 'dummy')

	def get_list_details(self, list_id):
		def _process_multi(page_no):
			try: results_extend(self.request_data(url % (self.base_url, list_id, page_no))['results'])
			except: pass
		def _process(dummy):
			result = self.request_data(url % (self.base_url, list_id, 1))
			results_extend(result['results'])
			total_pages = result['total_pages']
			if total_pages > 1:
				threads = list(make_thread_list(_process_multi, range(2, total_pages + 1)))
				[i.join() for i in threads]
			return results
		string = 'get_list_details_%s' % (list_id)
		url = '%s/list/%s?page=%s'
		results = []
		results_extend = results.extend
		return tmdb_lists_cache_object(_process, string, 'dummy')

	def add_remove_from_list(self, list_id, items, action):
		url = '%s/list/%s/items' % (self.base_url, list_id)
		return self.request_data(url, data=items, method=action)

	def make_list(self, list_name):
		url = '%s/list' % self.base_url
		return self.request_data(url, data={'description': '', 'name': list_name, 'iso_3166_1': 'US', 'iso_639_1': 'en', 'public': True}, method='post')

	def delete_list(self, list_id):
		url = '%s/list/%s' % (self.base_url, list_id)
		return self.request_data(url, method='delete')

	def rename_list(self, list_id, new_name):
		data = {'description': '', 'name': new_name, 'iso_3166_1': 'US', 'iso_639_1': 'en', 'public': True}
		url = '%s/list/%s' % (self.base_url, list_id)
		return self.request_data(url, data=data, method='put')

	def clear_list(self, list_id):
		url = '%s/list/%s/clear' % (self.base_url, list_id)
		return self.request_data(url)

	def item_status(self, list_id, media_type, media_id):
		url = '%s/list/%s/item_status' % (self.base_url, list_id)
		return self.request_data(url, params={'media_type': media_type, 'media_id': int(media_id)})

	def request_data(self, url, params=None, data=None, method='get'):
		headers = {'accept': 'application/json', 'content-type': 'application/json', 'Authorization': 'Bearer %s' % get_setting('fenlight.tmdb.token')}
		try: result = session.request(method, url, params=params, json=data, headers=headers, timeout=90).json()
		except: result = None
		return result

tmdb_list_api = TMDbListAPI()