import json
import os, ssl
from urllib.parse import unquote, parse_qsl, urlparse
from urllib.request import Request, urlopen
from indexers.metadata import get_title
from modules import kodi_utils
from modules.settings import download_directory, get_art_provider, get_language
from modules.utils import clean_file_name, clean_title, safe_string, remove_accents
# from modules.kodi_utils import logger

ls = kodi_utils.local_string
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS)
levels = ['../../../..', '../../..', '../..', '..']
poster_empty = kodi_utils.media_path('box_office.png')
video_extensions = ('m4v', '3g2', '3gp', 'nsv', 'tp', 'ts', 'ty', 'pls', 'rm', 'rmvb', 'mpd', 'ifo', 'mov', 'qt', 'divx', 'xvid', 'bivx', 'vob', 'nrg', 'img', 'iso', 'udf', 'pva',
					'wmv', 'asf', 'asx', 'ogm', 'm2v', 'avi', 'bin', 'dat', 'mpg', 'mpeg', 'mp4', 'mkv', 'mk3d', 'avc', 'vp3', 'svq3', 'nuv', 'viv', 'dv', 'fli', 'flv', 'wpl',
					'xspf', 'vdr', 'dvr-ms', 'xsp', 'mts', 'm2t', 'm2ts', 'evo', 'ogv', 'sdp', 'avs', 'rec', 'url', 'pxml', 'vc1', 'h264', 'rcv', 'rss', 'mpls', 'mpl', 'webm',
					'bdmv', 'bdm', 'wtv', 'trp', 'f4v', 'pvr', 'disc')
image_extensions = ('jpg', 'jpeg', 'jpe', 'jif', 'jfif', 'jfi', 'bmp', 'dib', 'png', 'gif', 'webp', 'tiff', 'tif',
					'psd', 'raw', 'arw', 'cr2', 'nrw', 'k25', 'jp2', 'j2k', 'jpf', 'jpx', 'jpm', 'mj2')

def runner(params):
	action = params.get('action')
	if action == 'image':
		for item in ('thumb_url', 'image_url'):
			image_params = params
			image_params['url'] = params.pop(item)
			image_params['mediatype'] = item
			Downloader(image_params).run()
	else: Downloader(params).run()

class Downloader:
	def __init__(self, params):
		self.params = params
		self.params_get = self.params.get

	def run(self):
		kodi_utils.show_busy_dialog()
		self.download_prep()
		self.get_url_and_headers()
		if self.url in (None, 'None', ''): return self.return_notification(notification=32692)
		self.get_filename()
		self.get_extension()
		self.download_check()
		if not self.confirm_download(): return self.return_notification(notification=32736)
		self.get_download_folder()
		if not self.get_destination_folder(): return self.return_notification(notification=32736)
		self.download_runner(self.url, self.final_destination, self.extension)

	def download_prep(self):
		if 'meta' in self.params:
			art_provider = get_art_provider()
			self.meta = json.loads(self.params_get('meta'))
			self.meta_get = self.meta.get
			title = get_title(self.meta, get_language())
			self.mediatype = self.meta_get('mediatype')
			self.year = self.meta_get('year')
			self.image = self.meta_get('poster')
			self.image = self.meta_get(art_provider[0]) or self.meta_get(art_provider[1]) or poster_empty
			self.season = self.meta_get('season')
			self.name = self.params_get('name')
		else:
			self.meta = None
			title = self.params_get('name')
			self.mediatype = self.params_get('mediatype')
			self.image = self.params_get('image')
			self.name = None
		self.title = clean_file_name(title)
		self.provider = self.params_get('provider')
		self.action = self.params_get('action')
		self.source = self.params_get('source')
		self.final_name = None

	def download_runner(self, url, folder_dest, ext):
		dest = os.path.join(folder_dest, self.final_name + ext)
		self.start_download(url, dest)

	def get_url_and_headers(self):
		url = self.params_get('url')
		if not url in (None, 'None', ''):
			if '_direct' in self.action:
				url = self.params_get('url')
			elif 'realdebrid' in self.action:
				from menus.realdebrid import resolve_rd
				url = resolve_rd(self.params)
			elif 'premiumize' in self.action:
				from debrids.premiumize_api import PremiumizeAPI
				url = PremiumizeAPI().add_headers_to_url(url)
			elif 'torbox' in self.action:
				from menus.torbox import resolve_tb
				url = resolve_tb(self.params)
		try: headers = dict(parse_qsl(url.rsplit('|', 1)[1]))
		except: headers = dict()
		try: url = url.split('|')[0]
		except: pass
		self.headers = headers
		self.url = url

	def get_download_folder(self):
		self.down_folder = download_directory(self.mediatype)
		if self.mediatype == 'thumb_url':
			self.down_folder = os.path.join(self.down_folder, '.thumbs')
		for level in levels:
			try: kodi_utils.make_directory(os.path.abspath(os.path.join(self.down_folder, level)))
			except: pass

	def get_destination_folder(self):
		if self.action == 'image':
			self.final_destination = self.down_folder
		else: self.final_destination = self.down_folder
		kodi_utils.make_directory(self.final_destination)
		return True

	def get_filename(self):
		if self.final_name: final_name = self.final_name
		elif self.action == 'image':
			final_name = self.title
		elif self.action == 'meta.pack':
			name = self.params_get('pack_files')['filename']
			final_name = os.path.splitext(urlparse(name).path)[0].split('/')[-1]
		else:
			name_url = unquote(self.url)
			file_name = clean_title(name_url.split('/')[-1])
			if clean_title(self.title).lower() in file_name.lower():
				final_name = os.path.splitext(urlparse(name_url).path)[0].split('/')[-1]
			else:
				try: final_name = self.name.translate(None, r'\/:*?"<>|').strip('.')
				except: final_name = os.path.splitext(urlparse(name_url).path)[0].split('/')[-1]
		self.final_name = safe_string(remove_accents(final_name))

	def get_extension(self):
		if self.action == 'archive':
			ext = '.zip'
		elif self.action == 'image':
			ext = os.path.splitext(urlparse(self.url).path)[1][1:]
			if not ext in image_extensions: ext = 'jpg'
			ext = '.%s' % ext
		else:
			ext = os.path.splitext(urlparse(self.url).path)[1][1:]
			if not ext in video_extensions: ext = 'mp4'
			ext = '.%s' % ext
		self.extension = ext

	def download_check(self):
		self.resp = self.get_response(self.url, self.headers, 0)
		if not self.resp: self.return_notification(ok_dialog=32575)
		try: self.content = int(self.resp.headers['Content-Length'])
		except: self.content = 0
		try: self.resumable = 'bytes' in self.resp.headers['Accept-Ranges'].lower()
		except: self.resumable = False
		if self.content < 1: self.return_notification(ok_dialog=32575)
		self.size = 1024 * 1024
		self.mb = self.content / (1024 * 1024)
		if self.content < self.size: self.size = self.content
		kodi_utils.hide_busy_dialog()

	def start_download(self, url, dest):
		if self.action not in ('image',):
			show_notifications = True
			notification_frequency = 25
		else:
			show_notifications = False
			notification_frequency = 0
		notify, total, errors, count, resume, sleep_time  = 25, 0, 0, 0, 0, 0
		f = kodi_utils.open_file(dest, 'w')
		chunk  = None
		chunks = []
		while True:
			downloaded = total
			for c in chunks: downloaded += len(c)
			percent = min(round(float(downloaded)*100 / self.content), 100)
			playing = kodi_utils.player.isPlaying()
			if show_notifications:
				if percent >= notify:
					notify += notification_frequency
					try:
						line1 = '%s - [I]%s[/I]' % (str(percent)+'%', self.final_name)
						if not playing: kodi_utils.notification(line1, 3000, self.image)
					except: pass
			chunk = None
			error = False
			try:
				chunk  = self.resp.read(self.size)
				if not chunk:
					if percent < 99:
						error = True
					else:
						while len(chunks) > 0:
							c = chunks.pop(0)
							f.write(c)
							del c
						f.close()
						try: progressDialog.close()
						except: pass
						return self.finish_download(self.final_name, self.mediatype, True, self.image)
			except Exception as e:
				error = True
				sleep_time = 10
				errno = 0
				if hasattr(e, 'errno'):
					errno = e.errno
				if errno == 10035: # 'A non-blocking socket operation could not be completed immediately'
					pass
				if errno == 10054: #'An existing connection was forcibly closed by the remote host'
					errors = 10 #force resume
					sleep_time  = 30
				if errno == 11001: # 'getaddrinfo failed'
					errors = 10 #force resume
					sleep_time  = 30
			if chunk:
				errors = 0
				chunks.append(chunk)
				if len(chunks) > 5:
					c = chunks.pop(0)
					f.write(c)
					total += len(c)
					del c
			if error:
				errors += 1
				count  += 1
				kodi_utils.sleep(sleep_time*1000)
			if (self.resumable and errors > 0) or errors >= 10:
				if (not self.resumable and resume >= 50) or resume >= 500:
					try: progressDialog.close()
					except: pass
					return self.finish_download(self.final_name, self.mediatype, False, self.image)
				resume += 1
				errors  = 0
				if self.resumable:
					chunks  = []
					self.resp = self.get_response(url, self.headers, total)
				else: pass

	def get_response(self, url, headers, size):
		try:
			if size > 0:
				size = int(size)
				headers['Range'] = 'bytes=%d-' % size
			req = Request(url, headers=headers)
			resp = urlopen(req, context=ctx, timeout=30)
			return resp
		except: return None

	def finish_download(self, title, mediatype, downloaded, image):
		if self.mediatype == 'thumb_url': return
		if self.mediatype == 'image_url':
			if downloaded: kodi_utils.notification('[I]%s[/I]' % ls(32576), 3000, image)
			else: kodi_utils.notification('[I]%s[/I]' % ls(32691), 3000, image)
		else:
			playing = kodi_utils.player.isPlaying()
			if downloaded: text = '[COLOR forestgreen]%s %s[/COLOR]:[CR][B]%s[/B]' % (ls(32107), ls(32576), title)
			else: text = '[COLOR red]%s %s[/COLOR]:[CR][B]%s[/B]' % (ls(32107), ls(32575), title)
			if not downloaded or not playing: kodi_utils.ok_dialog(text=text)

	def confirm_download(self):
		choice = True
		if self.action not in ('image',):
			text = '%s[CR]%s' % (ls(32688) % self.mb, ls(32689))
			choice = kodi_utils.confirm_dialog(text=text)
		return choice

	def return_notification(self, notification=None, ok_dialog=None):
		kodi_utils.hide_busy_dialog()
		if notification: kodi_utils.notification(notification)
		elif ok_dialog: kodi_utils.ok_dialog(text=ok_dialog, top_space=True)
		else: return

