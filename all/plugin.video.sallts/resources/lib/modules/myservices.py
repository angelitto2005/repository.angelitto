import time
import requests
from threading import Thread, Timer
from windows import create_window
from modules import kodi_utils, cache
# logger = kodi_utils.logger

quote, clear_cache = requests.utils.quote, cache.clear_cache
get_setting, set_setting, sleep = kodi_utils.get_setting, kodi_utils.set_setting, kodi_utils.sleep
notification, confirm_dialog = kodi_utils.notification, kodi_utils.confirm_dialog
user_agent = 'SALTS/%s' % kodi_utils.get_addoninfo('version')
qr_str = 'https://api.qrserver.com/v1/create-qr-code/?size=256x256&qzone=1%s'
meta_keys = 'title year poster fanart clearlogo'
code_str, nav2_str, await_str = 'PIN CODE: [B]%s[/B]', 'LOCATION: [B]%s[/B]', 'REMAINING: [B]%02d:%02d[/B]'
auth_str, noauth_str = 'Authorized: Select to Remove', 'Unauthorized: Select to Add'
timeout = 10.05

def watch_indicators(function):
	def wrapper(instance, *args, **kwargs):
		if function(instance, *args, **kwargs): kodi_utils.ok_dialog(text=(
			'At successful activation, watched status and resume progress will be set to [B]%s[/B]. '
			'To change settings after activation, use the addon settings category:[CR]'
			'[B]Features/Watched Indicators/Watched Status Provider[/B]'
		) % instance.__class__.__name__)
	return wrapper

def _make_progress_dialog(**kwargs):
	progress_dialog = create_window(('windows.progress', 'ProgressMedia'), 'progress_media.xml', **kwargs)
	Thread(target=progress_dialog.run).start()
	return progress_dialog

def authorize():
	def _builder():
		for name, api in services:
			item = kodi_utils.make_listitem()
			item.setLabel('[B]%s[/B]' % name.upper())
			item.setLabel2(auth_str if api().token else noauth_str)
			item.setArt({
				'icon': api.icon
				if api.icon.startswith('Default') else
				'%s%s' % (icon_path, api.icon)
			})
			yield(item)
	icon_path, services = kodi_utils.media_path(), (
		('trakt', Trakt), ('mdblist', MDBList), ('flicklist', FlickList),
		('real-debrid', RealDebrid), ('premiumize.me', Premiumize), ('torbox', TorBox)
	)
	service = kodi_utils.dialog.select('My Services', list(_builder()), useDetails=True)
	if service < 0: return
	try: success = services[service][1]().set()
	except Exception as e: kodi_utils.logger('myservices error', str(e))
	else: return success
	return notification(32574)

class RepeatTimer(Timer):
	def run(self):
		while not self.finished.wait(self.interval):
			self.function(*self.args, **self.kwargs)

class RealDebrid:
	icon = 'realdebrid.png'
	def __init__(self):
		self.token = get_setting('rd.token')
		self.client_id = get_setting('rd.client_id') or 'X245A4XAIBGVM'
		self.secret = get_setting('rd.secret')

	def base_url(self, path):
		return 'https://app.real-debrid.com/%s' % path

	def poll_auth(self, data):
		params = {'client_id': self.client_id, 'code': data['code']}
		response = requests.get(self.base_url('oauth/v2/device/credentials'), params=params, timeout=timeout)
		if not response.ok: return
		data.update(response.json())
		self.secret = data['client_secret']

	def set(self):
		cls_name = 'Real Debrid'
		if self.token:
			if not confirm_dialog(): return
			set_setting('rd.username', '')
			set_setting('rd.client_id', '')
			set_setting('rd.token', '')
			set_setting('rd.refresh', '')
			set_setting('rd.secret', '')
			clear_cache('rd_cloud', silent=True)
			return notification('Removed %s Authorization' % cls_name)

		params = {'client_id': self.client_id, 'new_credentials': 'yes'}
		response = requests.get(self.base_url('oauth/v2/device/code'), params=params, timeout=timeout)
		result = response.json()
		data = {'code': result['device_code'], 'grant_type': 'http://oauth.net/grant_type/device/1.0'}
		expires_in, expires_at = result['expires_in'], result['expires_in'] + time.monotonic()
		try: qr_icon = qr_str % '&data=%s' % quote(result['direct_verification_url'])
		except: qr_icon = ''
		meta = {**dict.fromkeys(meta_keys.split(), ''), 'poster': qr_icon}
		detail = code_str % result['user_code'], nav2_str % result['verification_url']
		progress_dialog = _make_progress_dialog(meta=meta)
		timer = RepeatTimer(result['interval'], self.poll_auth, args=(data,))
		timer.start()
		for i in range(1, expires_in + 1):
			if self.secret or progress_dialog.iscanceled(): break
			lines = await_str % divmod(expires_at - time.monotonic(), 60), *detail
			progress = 100 - int(100 * i / expires_in)
			progress_dialog.update('[CR]'.join(lines), progress)
			sleep(1000)
		timer.cancel()
		progress_dialog.close()
		if progress_dialog.iscanceled(): return False
		if not self.secret: return notification(32574)
		response = requests.post(self.base_url('oauth/v2/token'), data=data, timeout=timeout)
		data.update(response.json())
		sleep(500)
		headers = {'Authorization': 'Bearer %s' % data['access_token']}
		response = requests.get(self.base_url('rest/1.0/user'), headers=headers, timeout=timeout)
		username = response.json()['username']
		client_id, secret = data['client_id'], data['client_secret']
		token, refresh = data['access_token'], data['refresh_token']
		set_setting('rd.username', str(username))
		set_setting('rd.client_id', client_id)
		set_setting('rd.token', token)
		set_setting('rd.refresh', refresh)
		set_setting('rd.secret', secret)
		notification('Set %s Authorization' % cls_name)
		return True

class Premiumize:
	icon = 'premiumize.png'
	def __init__(self):
		self.token = get_setting('pm.token')
		self.client_id = '663882072'

	def base_url(self, path):
		return 'https://www.premiumize.me/%s' % path

	def poll_auth(self, data):
		response = requests.post(self.base_url('token'), json=data, timeout=timeout)
		if not response.ok: return
		data.update(response.json())
		self.token = data['access_token']

	def set(self):
		cls_name = 'Premiumize.me'
		if self.token:
			if not confirm_dialog(): return
			set_setting('pm.account_id', '')
			set_setting('pm.token', '')
			clear_cache('pm_cloud', silent=True)
			return notification('Removed %s Authorization' % cls_name)

		data = {'client_id': self.client_id, 'response_type': 'device_code'}
		response = requests.post(self.base_url('token'), json=data, timeout=timeout)
		result = response.json()
		data = {'client_id': self.client_id, 'code': result['device_code'], 'grant_type': 'device_code'}
		expires_in, expires_at = result['expires_in'], result['expires_in'] + time.monotonic()
		try: qr_icon = qr_str % '&data=%s' % quote(result['verification_uri'])
		except: qr_icon = ''
		meta = {**dict.fromkeys(meta_keys.split(), ''), 'poster': qr_icon}
		detail = code_str % result['user_code'], nav2_str % result['verification_uri']
		progress_dialog = _make_progress_dialog(meta=meta)
		timer = RepeatTimer(result['interval'], self.poll_auth, args=(data,))
		timer.start()
		for i in range(1, expires_in + 1):
			if self.token or progress_dialog.iscanceled(): break
			lines = await_str % divmod(expires_at - time.monotonic(), 60), *detail
			progress = 100 - int(100 * i / expires_in)
			progress_dialog.update('[CR]'.join(lines), progress)
			sleep(1000)
		timer.cancel()
		progress_dialog.close()
		if progress_dialog.iscanceled(): return False
		if not self.token: return notification(32574)
		sleep(500)
		headers = {'User-Agent': user_agent, 'Authorization': 'Bearer %s' % self.token}
		response = requests.get(self.base_url('api/account/info'), headers=headers, timeout=timeout)
		username = response.json()['customer_id']
		token = str(data['access_token'])
		set_setting('pm.account_id', str(username))
		set_setting('pm.token', token)
		notification('Set %s Authorization' % cls_name)
		return True

class TorBox:
	icon = 'torbox.png'
	def __init__(self):
		self.token = get_setting('tb.token')

	def base_url(self, path):
		return 'https://api.torbox.app/v1/api/%s' % path

	def poll_auth(self, data):
		response = requests.post(self.base_url('user/auth/device/token'), json=data, timeout=timeout)
		if not response.ok: return
		data.update(response.json())
		self.token = data

	def set(self):
		cls_name = self.__class__.__name__
		if self.token:
			if not confirm_dialog(): return
			set_setting('tb.token', '')
			set_setting('tb.account_id', '')
			clear_cache('tb_cloud', silent=True)
			return notification('Removed %s Authorization' % cls_name)

		params = {'app': user_agent}
		response = requests.get(self.base_url('user/auth/device/start'), params=params, timeout=timeout)
		result = response.json()['data']
		data = {'device_code': result['device_code']}
		expires_in, expires_at = 600, 600 + time.monotonic()
		try: qr_icon = qr_str % '&bgcolor=04bf8a&data=%s' % quote(result['verification_url'])
		except: qr_icon = ''
		meta = {**dict.fromkeys(meta_keys.split(), ''), 'poster': qr_icon}
		detail = code_str % result['code'], nav2_str % result['friendly_verification_url']
		progress_dialog = _make_progress_dialog(meta=meta)
		timer = RepeatTimer(result['interval'], self.poll_auth, args=(data,))
		timer.start()
		for i in range(1, expires_in + 1):
			if self.token or progress_dialog.iscanceled(): break
			lines = await_str % divmod(expires_at - time.monotonic(), 60), *detail
			progress = 100 - int(100 * i / expires_in)
			progress_dialog.update('[CR]'.join(lines), progress)
			sleep(1000)
		timer.cancel()
		progress_dialog.close()
		if progress_dialog.iscanceled(): return False
		self.token = data['data']['access_token']
		headers = {'Authorization': 'Bearer %s' % self.token}
		response = requests.get(self.base_url('user/me'), headers=headers, timeout=timeout)
		result = response.json()
		customer = result['data']['customer']
		set_setting('tb.account_id', str(customer))
		set_setting('tb.token', self.token)
		notification('Set %s Authorization' % cls_name)
		return True

class Trakt:
	icon = 'trakt.png'
	def __init__(self):
		self.token = get_setting('trakt.token')
		self.client_id = get_setting('trakt.client_id')
		self.secret = get_setting('trakt.client_secret')

	def base_url(self, path):
		return 'https://api.trakt.tv/%s' % path

	def poll_auth(self, data):
		response = requests.post(self.base_url('oauth/device/token'), json=data, timeout=timeout)
		if not response.ok: return
		data.update(response.json())
		self.token = data['access_token']

	@watch_indicators
	def set(self):
		cls_name = self.__class__.__name__
		if self.token:
			if not confirm_dialog(): return
			data = {'token': self.token, 'client_id': self.client_id, 'client_secret': self.secret}
			response = requests.post(self.base_url('oauth/revoke'), json=data, timeout=timeout)
			set_setting('trakt_user', '')
			set_setting('trakt.token', '')
			set_setting('trakt.refresh', '')
			set_setting('trakt.expires', '')
			set_setting('trakt_indicators_active', 'false')
			set_setting('watched_indicators', '0')
			sleep(500)
			clear_cache('trakt', silent=True)
			return notification('Removed %s Authorization' % cls_name)

		data = {'client_id': self.client_id, 'client_secret': self.secret, 'code': ''}
		response = requests.post(self.base_url('oauth/device/code'), json=data, timeout=timeout)
		result = response.json()
		data['code'] = result['device_code']
		expires_in, expires_at = result['expires_in'], result['expires_in'] + time.monotonic()
		try: qr_icon = qr_str % '&color=f00&data=%s' % quote('%s/%s' % (result['verification_url'], result['user_code']))
		except: qr_icon = ''
		meta = {**dict.fromkeys(meta_keys.split(), ''), 'poster': qr_icon}
		detail = code_str % result['user_code'], nav2_str % result['verification_url']
		progress_dialog = _make_progress_dialog(meta=meta)
		timer = RepeatTimer(result['interval'], self.poll_auth, args=(data,))
		timer.start()
		for i in range(1, expires_in + 1):
			if self.token or progress_dialog.iscanceled(): break
			lines = await_str % divmod(expires_at - time.monotonic(), 60), *detail
			progress = 100 - int(100 * i / expires_in)
			progress_dialog.update('[CR]'.join(lines), progress)
			sleep(1000)
		timer.cancel()
		progress_dialog.close()
		if progress_dialog.iscanceled(): return False
		if not self.token: return notification(32574)
		sleep(500)
		headers = {'trakt-api-key': self.client_id, 'trakt-api-version': '2', 'Content-Type': 'application/json'}
		headers.update({'Authorization': 'Bearer %s' % self.token})
		response = requests.get(self.base_url('users/me'), headers=headers, timeout=timeout)
		username = response.json()['username']
		expires = int(data['created_at']) + int(data['expires_in'])
		refresh, token = data['refresh_token'], data['access_token']
		set_setting('trakt_user', str(username))
		set_setting('trakt.token', token)
		set_setting('trakt.refresh', refresh)
		set_setting('trakt.expires', str(expires))
		set_setting('trakt_indicators_active', 'true')
		set_setting('watched_indicators', '1')
		notification('Set %s Authorization' % cls_name)
		sleep(500)
		clear_cache('trakt', silent=True)
		return True

class MDBList:
	icon = 'mdblist.png'
	def __init__(self):
		self.token = get_setting('mdblist.token')

	def base_url(self, path):
		return 'https://api.mdblist.com/%s' % path

	@watch_indicators
	def set(self):
		cls_name = self.__class__.__name__
		if self.token:
			if not confirm_dialog(): return
			set_setting('mdblist_user', '')
			set_setting('mdblist.token', '')
			set_setting('mdbl_indicators_active', 'false')
			set_setting('watched_indicators', '0')
			sleep(500)
			clear_cache('mdblist', silent=True)
			return notification('Removed %s Authorization' % cls_name)

		api_key = kodi_utils.dialog.input('MDBList API Key:')
		if not api_key: return
		params = {'apikey': api_key}
		response = requests.get(self.base_url('user'), params=params, timeout=timeout)
		result = response.json()
		user_id, username = result['user_id'], result['username']
		set_setting('mdblist_user', str(username))
		set_setting('mdblist.token', api_key)
		set_setting('mdbl_indicators_active', 'true')
		set_setting('watched_indicators', '2')
		notification('Set %s Authorization' % cls_name)
		sleep(500)
		clear_cache('mdblist', silent=True)
		return True

class FlickList:
	icon = 'DefaultPlaylist.png'
	def __init__(self):
		self.token = get_setting('flicklist.token')
		self.client_id = get_setting('flicklist.client_id') or 'salts_redux'

	def base_url(self, path):
		return 'https://flicklist.tv/api/%s' % path

	def poll_auth(self, data):
		response = requests.post(self.base_url('auth/device/token'), json=data, timeout=timeout)
		if not 'access_token' in response.text: return
		data.update(response.json())
		self.token = data['access_token']

	@watch_indicators
	def set(self):
		cls_name = self.__class__.__name__
		if self.token:
			if not confirm_dialog(): return
			set_setting('flicklist_user', '')
			set_setting('flicklist.token', '')
			set_setting('flicklist.expires', '')
			set_setting('flicklist.client_id', '')
			set_setting('flicklist_indicators_active', 'false')
			set_setting('watched_indicators', '0')
			sleep(500)
			clear_cache('flicklist', silent=True)
			return notification('Removed %s Authorization' % cls_name)

		from datetime import datetime
		data = {'client_id': self.client_id}
		response = requests.post(self.base_url('auth/device/code'), json=data, timeout=timeout)
		result = response.json()
		data['device_code'] = result['device_code']
		expires_in, expires_at = result['expires_in'], result['expires_in'] + time.monotonic()
		try: qr_icon = qr_str % '&data=%s' % quote('%s' % result['verification_uri'])
		except: qr_icon = ''
		meta = {**dict.fromkeys(meta_keys.split(), ''), 'poster': qr_icon}
		detail = code_str % result['user_code'], nav2_str % result['verification_uri']
		progress_dialog = _make_progress_dialog(meta=meta)
		timer = RepeatTimer(result['interval'], self.poll_auth, args=(data,))
		timer.start()
		for i in range(1, expires_in + 1):
			if self.token or progress_dialog.iscanceled(): break
			lines = await_str % divmod(expires_at - time.monotonic(), 60), *detail
			progress = 100 - int(100 * i / expires_in)
			progress_dialog.update('[CR]'.join(lines), progress)
			sleep(1000)
		timer.cancel()
		progress_dialog.close()
		if progress_dialog.iscanceled(): return False
		if not self.token: return notification(32574)
		dt = datetime.strptime(data['expires_at'], '%Y-%m-%dT%H:%M:%S.%fZ')
		expires = str(int(dt.timestamp()))
		username = data['user']['username']
		set_setting('flicklist_user', str(username))
		set_setting('flicklist.token', self.token)
		set_setting('flicklist.expires', expires)
		set_setting('flicklist.client_id', self.client_id)
		set_setting('flicklist_indicators_active', 'true')
		set_setting('watched_indicators', '3')
		notification('Set %s Authorization' % cls_name)
		sleep(500)
		clear_cache('flicklist', silent=True)
		return True

def refer_link(service):
	url = {'realdebrid': 'https://tinyurl.com/2db65q28', 'torbox': 'https://tinyurl.com/2d2ra6jq'}[service]
	expires_in, expires_at = 20, 20 + time.monotonic()
	try: qr_icon = qr_str % '&data=%s' % quote(url)
	except: qr_icon = kodi_utils.media_path('%s.png' % service)
	meta = {**dict.fromkeys(meta_keys.split(), ''), 'poster': qr_icon}
	detail = nav2_str % url, ''
	progress_dialog = _make_progress_dialog(meta=meta)
	for i in range(1, expires_in + 1):
		if progress_dialog.iscanceled(): break
		lines = await_str % divmod(expires_at - time.monotonic(), 60), *detail
		progress = 100 - int(100 * i / expires_in)
		progress_dialog.update('[CR]'.join(lines), progress)
		sleep(1000)
	progress_dialog.close()

