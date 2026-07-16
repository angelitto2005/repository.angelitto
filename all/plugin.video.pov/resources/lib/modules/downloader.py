import json
import os, ssl
from threading import Thread
from urllib.parse import unquote, parse_qsl, urlparse
from urllib.request import Request, urlopen
from indexers.metadata import get_title
from modules import debrid, kodi_utils
from modules.settings import download_directory, get_art_provider
from modules.source_utils import clean_file_name, find_season_in_release_title
# from modules.kodi_utils import logger

ctx = ssl.SSLContext(ssl.PROTOCOL_TLS)
levels = ['../../../..', '../../..', '../..', '..']
ls, user_agent = kodi_utils.local_string, kodi_utils.xbmc.getUserAgent()
poster_empty = kodi_utils.media_path('box_office.png')
image_extensions, video_extensions = (
	'jpg', 'jpeg', 'jpe', 'jif', 'jfif', 'jfi', 'bmp', 'dib', 'png', 'gif', 'webp', 'tiff', 'tif',
	'psd', 'raw', 'arw', 'cr2', 'nrw', 'k25', 'jp2', 'j2k', 'jpf', 'jpx', 'jpm', 'mj2'
), (
	'm4v', '3g2', '3gp', 'nsv', 'tp', 'ts', 'ty', 'pls', 'rm', 'rmvb', 'mpd', 'ifo', 'mov', 'qt', 'divx',
	'xvid', 'bivx', 'vob', 'nrg', 'img', 'iso', 'udf', 'pva', 'wmv', 'asf', 'asx', 'ogm', 'm2v', 'avi', 'bin',
	'dat', 'mpg', 'mpeg', 'mp4', 'mkv', 'mk3d', 'avc', 'vp3', 'svq3', 'nuv', 'viv', 'dv', 'fli', 'flv', 'wpl',
	'xspf', 'vdr', 'dvr-ms', 'xsp', 'mts', 'm2t', 'm2ts', 'evo', 'ogv', 'sdp', 'avs', 'rec', 'url', 'pxml',
	'vc1', 'h264', 'rcv', 'rss', 'mpls', 'mpl', 'webm', 'bdmv', 'bdm', 'wtv', 'trp', 'f4v', 'pvr', 'disc'
)

def factory(params):
	action = params.get('action')
	if 'meta' in action and params.get('magnet_url') != 'None':
		source, meta = json.loads(params['source']), json.loads(params['meta'])
		pack_choices = debrid.Source(source, meta).browse_packs(download=True)
		if not pack_choices: return kodi_utils.notification(32692)
		if len(pack_choices) > 1:
			heading = clean_file_name(source.get('name'))
			preselect = list(range(len(pack_choices)))
			kwargs = {'heading': heading, 'highlight': params['highlight'], 'preselect': preselect}
			kwargs.update({'items': json.dumps(pack_choices), 'multi_choice': 'true'})
			chosen_list = kodi_utils.select_dialog(pack_choices, **kwargs)
		else: chosen_list = next(([i] for i in pack_choices), None)
		if not chosen_list: return
		size_label = sum(i['size'] for i in chosen_list) / (1024 * 1024)
		text = '%s[CR]%s' % (ls(32688) % size_label, ls(32689))
		if not kodi_utils.confirm_dialog(text=text): return
		show_package = source.get('package') == 'show'
		default_name = '%s (%s)' % (clean_file_name(get_title(meta)), meta.get('year'))
		default_foldername = kodi_utils.dialog.input(ls(32228), defaultt=default_name)
		for item in chosen_list:
			item = {**params, 'default_foldername': default_foldername, 'pack_files': item}
			if show_package:
				season = find_season_in_release_title(item['pack_files']['filename'])
				if season: meta.update({'season': season}), item.update({'meta': json.dumps(meta)})
			Thread(target=Downloader(item).run).start()
	elif action == 'image':
		for item in ('thumb_url', 'image_url'):
			url = params.pop(item)
			Downloader({**params, 'url': url, 'mediatype': item}).run()
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
		self.start_download(self.url, os.path.join(self.final_destination, self.final_name + self.extension))

	def download_prep(self):
		if 'meta' in self.params:
			poster_main, poster_backup = get_art_provider()[:2]
			self.meta = json.loads(self.params_get('meta'))
			self.meta_get = self.meta.get
			self.mediatype = self.meta_get('mediatype')
			self.image = self.meta_get(poster_main) or self.meta_get(poster_backup) or poster_empty
			self.year = self.meta_get('year')
			self.season = self.meta_get('season')
			self.name = self.params_get('name')
			title = get_title(self.meta)
		else:
			self.meta = None
			self.mediatype = self.params_get('mediatype')
			self.image = self.params_get('image')
			self.name = None
			title = self.params_get('name')
		self.title = clean_file_name(title)
		self.provider = self.params_get('provider')
		self.action = self.params_get('action')
		self.source = self.params_get('source')
		self.final_name = None

	def get_url_and_headers(self):
		url = self.params_get('url')
		if url in (None, 'None', ''):
			if 'meta' in self.action and 'pack_files' in self.params:
				link = self.params_get('pack_files')['link']
				debrid_function = debrid.import_debrid(self.provider)
				url = debrid_function.unrestrict_link(link)
			else:
				source = json.loads(self.params_get('source'))
				url = debrid.Source(source, self.meta).resolve_sources()
		elif 'cloud' in self.action:
			source = debrid.Source.fromcloud(self.params)
			url = source.resolve_internal_sources(source.direct_debrid_link)
		else: pass
		url, *headers = url.rsplit('|', 1)
		try: headers = dict(parse_qsl(*headers))
		except: headers = dict()
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
		if 'meta' in self.action:
			default_name = '%s (%s)' % (self.title, self.year)
			folder_rootname = self.params_get('default_foldername', default_name)
			if not folder_rootname: return False
			if self.mediatype == 'episode':
				inter = os.path.join(self.down_folder, folder_rootname)
				kodi_utils.make_directory(inter)
				self.final_destination = os.path.join(inter, 'Season %02d' %  int(self.season))
			else: self.final_destination = os.path.join(self.down_folder, folder_rootname)
		elif self.action == 'image':
			self.final_destination = self.down_folder
		else: self.final_destination = self.down_folder
		kodi_utils.make_directory(self.final_destination)
		return True

	def get_filename(self):
		if self.final_name:
			final_name = self.final_name
		elif self.action == 'image':
			final_name = self.title
		elif 'meta' in self.action:
			if 'pack_files' in self.params:
				name = self.params_get('pack_files')['filename']
			else: name = self.url
			final_name = os.path.splitext(urlparse(name).path)[0].split('/')[-1]
		else:
			name_url = self.params_get('name') or unquote(self.url)
			name_url = name_url.split('/')[-1]
			final_name = os.path.splitext(urlparse(name_url).path)[0].split('/')[-1]
		self.final_name = clean_file_name(final_name, False)

	def get_extension(self):
		if self.action == 'archive':
			ext = '.zip'
		elif self.action == 'image':
			ext = os.path.splitext(urlparse(self.url).path)[1][1:]
			if ext not in image_extensions: ext = 'jpg'
			ext = '.%s' % ext
		elif 'meta' in self.action:
			if 'pack_files' in self.params:
				name = self.params_get('pack_files')['filename']
			else: name = self.url
			ext = os.path.splitext(urlparse(name).path)[1][1:]
			if ext not in video_extensions: ext = 'mp4'
			ext = '.%s' % ext
		else:
			name_url = self.params_get('name') or self.url
			ext = os.path.splitext(urlparse(name_url).path)[1][1:]
			if ext not in video_extensions: ext = 'mp4'
			ext = '.%s' % ext
		self.extension = ext

	def download_check(self):
		self.headers['User-Agent'] = user_agent
		self.resp = self.get_response(self.url, self.headers, 0)
		if not self.resp: self.return_notification(ok_dialog=32575)
		info_get = self.resp.info().get
		try: self.content = int(info_get('Content-Length'))
		except: self.content = 0
		try: self.resumable = 'bytes' in info_get('Accept-Ranges').lower()
		except: self.resumable = False
		if self.content < 1: self.return_notification(ok_dialog=32575)
		self.size_label = self.content / (1024 * 1024)
		kodi_utils.hide_busy_dialog()

	def start_download(self, url, dest):
		if self.action in ('image', 'meta.pack'):
			if self.action == 'meta.pack': kodi_utils.notification(32134, 3000, self.image)
			show_notifications, notification_frequency = False, 0
		else: show_notifications, notification_frequency = True, 25
		errors, resume, sleep_time = 0, 0, 0,
		file_info = self.final_name + self.extension, self.image
		f = kodi_utils.open_file(dest, 'w')
		p = WriteProxy(f, self.content, file_info, show_notifications, notification_frequency)
		from shutil import copyfileobj
		while True:
			error = False
			try:
				if not self.resumable: f.seek(0)
				copyfileobj(self.resp, p)
				f.close()
				try: progressDialog.close()
				except: pass
				return self.finish_download(self.final_name, self.mediatype, True, self.image)
			except OSError as e:
				from traceback import format_exc
				return kodi_utils.logger('download error', f"\n{format_exc()}")
			except Exception as e:
				from traceback import format_exc
				kodi_utils.logger('download error', f"\n{format_exc()}")
				error = True
				sleep_time = 10
				errno = getattr(e, 'errno', 0)
				if errno == 10035: # 'A non-blocking socket operation could not be completed immediately'
					pass
				if errno == 10054: # 'An existing connection was forcibly closed by the remote host'
					errors = 10    # force resume
					sleep_time  = 30
				if errno == 11001: # 'getaddrinfo failed'
					errors = 10    # force resume
					sleep_time  = 30
			if error:
				errors += 1
				kodi_utils.sleep(sleep_time*1000)
			if (self.resumable and errors > 0) or errors >= 10:
				if (not self.resumable and resume >= 50) or resume >= 500:
					f.close()
					try: progressDialog.close()
					except: pass
					return self.finish_download(self.final_name, self.mediatype, False, self.image)
				resume += 1
				errors  = 0
				if self.resumable: self.resp = self.get_response(url, self.headers, p.total_write + 1)

	def get_response(self, url, headers, size):
		try:
			if size > 0: headers['Range'] = 'bytes=%d-' % int(size)
			req = Request(url, headers=headers)
			resp = urlopen(req, context=ctx, timeout=30)
			return resp
		except: return None

	def finish_download(self, title, mediatype, downloaded, image):
		if self.mediatype == 'thumb_url': return
		if self.mediatype == 'image_url':
			text = ls(32576) if downloaded else ls(32691)
			return kodi_utils.notification('%s' % text, 3000, image)
		playing = kodi_utils.player.isPlaying()
		if downloaded: text = '%s %s:[CR]%s' % (ls(32107), ls(32576), title)
		else: text = '%s %s:[CR]%s' % (ls(32107), ls(32575), title)
		if not downloaded or not playing: kodi_utils.ok_dialog(text=text)

	def confirm_download(self):
		if self.action == 'image' or 'pack_files' in self.params: return True
		text = '%s[CR]%s' % (ls(32688) % self.size_label, ls(32689))
		return kodi_utils.confirm_dialog(text=text)

	def return_notification(self, notification=None, ok_dialog=None):
		kodi_utils.hide_busy_dialog()
		if notification: kodi_utils.notification(notification)
		elif ok_dialog: kodi_utils.ok_dialog(text=ok_dialog)
		else: return

class WriteProxy:
	def __init__(self, file_obj, length=0, file_info=None, notify=True, frequency=25):
		self.file_obj = file_obj
		self.total_size = length
		self.destination, self.image = file_info or ('', '')
		self.show_notifications = notify
		self.notification_frequency = frequency
		self.total_write = 0
		self.notices = set()

	def write(self, chunk):
		self.file_obj.write(chunk)
		self.total_write += len(chunk)
		try:
			percent = min(round(self.total_write / self.total_size * 100), 100)
			line1 = '%d%% - [I]%s[/I]' % (percent, self.destination)
			if (not (self.total_size and self.show_notifications)
				or percent % self.notification_frequency
				or percent in self.notices
				or kodi_utils.player.isPlaying()
			): return
			self.notices.add(percent)
			timeout = 1250 if percent < 51 else 750
			if 0 < percent < 100: kodi_utils.notification(line1, timeout, self.image)
		except: pass

