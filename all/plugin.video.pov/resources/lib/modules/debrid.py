import json
from threading import Thread
from debrids import alldebrid_api, premiumize_api, real_debrid_api, torbox_api, offcloud_api
from caches.debrid_cache import DebridCache
from indexers import metadata
from modules import kodi_utils, settings
# from modules.kodi_utils import logger

ls, get_setting, notification = kodi_utils.local_string, kodi_utils.get_setting, kodi_utils.notification
show_busy_dialog, hide_busy_dialog = kodi_utils.show_busy_dialog, kodi_utils.hide_busy_dialog
ok_dialog, confirm_dialog, select_dialog = kodi_utils.ok_dialog, kodi_utils.confirm_dialog, kodi_utils.select_dialog
default_internal_scrapers, enabled_debrids_check = settings.default_internal_scrapers, settings.enabled_debrids_check
default_external_scrapers = ('external',)
plswait_str, checking_debrid_str, remaining_debrid_str = ls(32577), ls(32578), ls(32579)

debrid_list = (
	('real-debrid', 'rd', real_debrid_api.RealDebridAPI),
	('premiumize.me', 'pm', premiumize_api.PremiumizeAPI),
	('alldebrid', 'ad', alldebrid_api.AllDebridAPI),
	('torbox', 'tb', torbox_api.TorBoxAPI),
	('offcloud', 'oc', offcloud_api.OffcloudAPI),
)

def import_debrid(debrid_provider):
	cls = next((i[2] for i in debrid_list if i[0] == debrid_provider), None)
	return cls() if cls else cls

def debrid_enabled():
	return [i[0] for i in debrid_list if enabled_debrids_check(i[1])]

def debrid_type_enabled(debrid_type, enabled_debrids):
	return [i[0] for i in debrid_list if i[0] in enabled_debrids and get_setting('%s.%s.enabled' % (i[1], debrid_type)) == 'true']

class Source:
	@classmethod
	def fromcloud(cls, params):
		self = cls(params)
		ddl = params.get('direct_debrid_link', True)
		if ddl in ('false', False): self.direct_debrid_link = False
		else: self.direct_debrid_link = True if ddl == 'true' else ddl
		self.url_dl = params['id'] if self.direct_debrid_link else ''
		return self

	def dumps(self, depth=1, width=172):
		from pprint import pformat
		return pformat(vars(self), depth=depth, width=width)

	def __init__(self, source_dict, meta=None):
		self.direct_debrid_link = False
		self.scrape_provider, self.url = '', ''
		for k, v in source_dict.items(): setattr(self, k, v)
		self.meta = meta or {}

	def resolve_sources(self):
		try:
			if self.scrape_provider in default_external_scrapers:
				if self.meta['mediatype'] == 'episode':
					title = self.meta.get('ep_name') or self.meta.get('title')
					season = self.meta.get('custom_season') or self.meta.get('season')
					episode = self.meta.get('custom_episode') or self.meta.get('episode')
				else: title, season, episode = metadata.get_title(self.meta), None, None
				return self.resolve_external_sources(title, season, episode)
			if self.scrape_provider in default_internal_scrapers:
				return self.resolve_internal_sources(self.direct_debrid_link)
			return self.url
		except: pass

	def resolve_external_sources(self, title, season, episode):
		from modules.source_utils import supported_video_extensions, seas_ep_filter, extras_filter
		try:
			extensions = supported_video_extensions()
			extras_filtering_list = tuple(i for i in extras_filter() if i not in title.lower())
			if self.url.startswith('magnet'):
				is_nzb, store_to_cloud = False, settings.store_resolved_torrent_to_cloud(self.debrid)
			else: is_nzb, store_to_cloud = True, settings.store_resolved_usenet_to_cloud(self.debrid)
			if self.debrid in ('real-debrid', 'alldebrid'): args = self.url, self.hash, True
			else: args = self.url, self.hash
			api = import_debrid(self.debrid)
			files = api.parse_magnet_pack(*args)
			selected_files = []
			selected_files_append = selected_files.append
			for i in files or []:
				torrent_id, filename = i.get('torrent_id'), i['filename'].lower()
				if filename.endswith('.m2ts'): raise Exception('_m2ts_check failed')
				if not filename.endswith(tuple(extensions)): continue
				if season:
					if not seas_ep_filter(season, episode, filename): continue
				elif any(x in filename for x in extras_filtering_list): continue
				selected_files_append(i)
			if not selected_files: raise Exception('selected_files failed')
			if not season: selected_files.sort(key=lambda k: k['size'], reverse=True)
			file_key = next((i['link'] for i in selected_files), None)
			if is_nzb: file_url = api.unrestrict_usenet(file_key)
			else: file_url = api.unrestrict_link(file_key)
			if self.debrid in ('premiumize.me', 'offcloud'):
				if store_to_cloud: Thread(target=api.create_transfer, args=(self.url,)).start()
			if self.debrid in ('real-debrid', 'alldebrid', 'torbox'):
				if not store_to_cloud: self._delete(api, torrent_id, is_nzb)
			return file_url
		except Exception as e:
			kodi_utils.logger('resolve_external_sources exception', f"{e}\n{self.dumps()}")
			if files and torrent_id: self._delete(api, torrent_id, is_nzb)

	def _delete(self, api, torrent_id, is_nzb):
		target = api.delete_usenet if is_nzb else api.delete_torrent
		Thread(target=target, args=(torrent_id,)).start()

	def resolve_internal_sources(self, direct_debrid_link=False):
		try:
			if self.scrape_provider == 'rd_cloud':
				if direct_debrid_link: url = self.url_dl
				else: url = real_debrid_api.RealDebridAPI().unrestrict_link(self.id)
			elif self.scrape_provider == 'ad_cloud':
				if direct_debrid_link: url = self.url_dl
				else: url = alldebrid_api.AllDebridAPI().unrestrict_link(self.id)
			elif self.scrape_provider == 'tb_cloud':
				url = torbox_api.TorBoxAPI().get_function(self.id)(self.id)
			elif self.scrape_provider == 'easynews':
				from debrids.easynews_api import EasyNewsAPI
				url = EasyNewsAPI().unrestrict_link(self.url_dl)
				if not direct_debrid_link: url += '|seekable=0'
			else: url = self.url_dl
			return url
		except Exception as e:
			kodi_utils.logger('resolve_internal_sources exception', f"{e}\n{self.dumps()}")

	def browse_packs(self, highlight=None, download=False):
		from modules.source_utils import clean_file_name
		show_busy_dialog()
		api = import_debrid(self.debrid)
		pack_choices = api.parse_magnet_pack(self.url, self.hash)
		hide_busy_dialog()
		if not pack_choices: return None if download else notification(32574)
		pack_choices.sort(key=lambda k: k['filename'].lower())
		for item in pack_choices: item.update({
			'icon': self.meta.get('poster') or api.icon,
			'line1': clean_file_name(item['filename']),
			'line2': '%s: %.2f GB' % (ls(32584), float(item['size'])/1073741824)
		})
		if download: return pack_choices
		kwargs = {'items': json.dumps(pack_choices), 'heading': self.name, 'highlight': highlight}
		chosen_result = select_dialog(pack_choices, **kwargs)
		if chosen_result is None: return 'cancel'
		url_dl = chosen_result['link']
		return api.unrestrict_link(url_dl)

	def unchecked_magnet_status(self):
		show_busy_dialog()
		api = import_debrid(self.debrid)
		result = api.parse_magnet_pack(self.url, self.hash)
		hide_busy_dialog()
		if not result: return ok_dialog(text='Not Cached at [B]%s[/B]' % self.debrid.upper())
		torrent_id = next((i['torrent_id'] for i in result if 'torrent_id' in i), None)
		if torrent_id: Thread(target=api.delete_torrent, args=(torrent_id,)).start()
		ok_dialog(text='Cached at [B]%s[/B]' % self.debrid.upper())

	def nzb_cache_and_play(self):
		line, status_str = '%s[CR]%s[CR]STATUS: %s', '[B]%s[/B] (%2d%%)'
		title, season, episode = self.meta['title'], self.meta['season'], self.meta['episode']
		if season and episode: line1 = '%s (S%sE%s)' % (title, season, episode)
		else: line1 = '%s (%s)' % (title, self.meta['year'])
		kodi_utils.progressDialog.create('POV', '')
		kodi_utils.progressDialog.update(0, line % (line1, '', '[B]GRAB...[/B]'))
		try:
			api = import_debrid(self.debrid)
			nzb_id = api.create_transfer(self.url, self.name)
			if not nzb_id: return kodi_utils.notification(32574)
			resolved_link = None
			data = {'files': []}
			while not data['files']:
				if kodi_utils.progressDialog.iscanceled(): return kodi_utils.notification(32736)
				line2 = 'ETA: %s' % data.get('eta', 'NA')
				progress = int(float(data.get('progress', '0')) * 100)
				status = status_str % (data.get('download_state', '...').upper(), progress)
				kodi_utils.progressDialog.update(progress, line % (line1, line2, status))
				kodi_utils.sleep(500)
				result = api.nzb_info(nzb_id)
				if result and 'id' in result: data = result
			else: resolved_link = self.resolve_external_sources(title, season, episode)
		finally: kodi_utils.progressDialog.close()
		return kodi_utils.notification(32574) if not resolved_link else resolved_link

	def manual_add_nzb_to_cloud(self):
		if self.debrid in ('torbox',) and self.meta:
			args = 'POV', '[CR]%s' % ls(32831) % self.debrid.upper()
			choice = kodi_utils.dialog.yesnocustom(*args, customlabel='Cache/Play')
		else: choice = confirm_dialog(text=ls(32831) % self.debrid.upper())
		if choice == 2: return self.nzb_cache_and_play()
		if choice in (-1, 0, False): return
		show_busy_dialog()
		api = import_debrid(self.debrid)
		api.clear_cache()
		result = api.create_transfer(self.url, self.name)
		hide_busy_dialog()
		if result: notification(32576)
		else: notification(32575)

	def manual_airlock_to_cloud(self):
		if not confirm_dialog(text=ls(32831) % self.debrid.upper()): return
		show_busy_dialog()
		api = import_debrid(self.debrid)
		api.clear_cache()
		request_id = api.create_transfer(self.url)
		if not request_id: return notification(32575)
		mediatype = 'torrents' if self.url.startswith('magnet') else 'usenet'
		result = api.toggle_airlock(mediatype, request_id, True)
		hide_busy_dialog()
		if result: notification(32576)
		else: notification(32575)

	def manual_add_magnet_to_cloud(self):
		if not confirm_dialog(text=ls(32831) % self.debrid.upper()): return
		show_busy_dialog()
		api = import_debrid(self.debrid)
		api.clear_cache()
		result = api.create_transfer(self.url)
		hide_busy_dialog()
		if result: notification(32576)
		else: notification(32575)

class DebridCheck:
	_debrid_dict = {i[0]: i for i in debrid_list}
	hash_list, cached_hashes = [], []

	@classmethod
	def set_cached_hashes(cls, hash_list):
		cls.hash_list = hash_list
		cls.cached_hashes = DebridCache().get_many(hash_list) or []

	def __init__(self, meta, name):
		self.cached_list = []
		self.name, self.debrid, self.function = self._debrid_dict[name]
		self.imdb, self.season, self.episode = meta.get('imdb_id'), meta.get('season'), meta.get('episode')

	def cache_write(self, hashes):
		DebridCache().set_many(hashes, self.debrid)

	def cache_check(self):
		try:
			self.cached_list.extend(i[0] for i in self.cached_hashes if i[1] == self.debrid and i[2] == 'True')
			unchecked_filter = {h[0] for h in self.cached_hashes if h[1] == self.debrid}
			unchecked_hashes = [i for i in self.hash_list if i not in unchecked_filter]
			if not unchecked_hashes: return self.cached_list
			if self.debrid in ('rd', 'ad'): checked_hashes = self.external_check_cache(unchecked_hashes)
			else: checked_hashes = self.function().check_cache(unchecked_hashes)
			if not checked_hashes: return self.cached_list
			checked_hashes = set(checked_hashes)
			hashes_to_cache = []
			process_append = hashes_to_cache.append
			cached_append = self.cached_list.append
			for h in unchecked_hashes:
				if h in checked_hashes:
					cached_append(h)
					process_append((h, 'True'))
				else: process_append((h, 'False'))
			if hashes_to_cache: Thread(target=self.cache_write, args=(hashes_to_cache,)).start()
		except: pass
		return self.cached_list

	def external_check_cache(self, unchecked_hashes):
		checked_hashes = []
		if self.debrid == 'ad': threads = (
			Thread(target=aio_check_cache, args=(self.imdb, self.season, self.episode, checked_hashes)),
		)
		else: threads = (
			Thread(target=tio_check_cache, args=(self.imdb, self.season, self.episode, checked_hashes)),
			Thread(target=dmm_check_cache, args=(unchecked_hashes, self.imdb, checked_hashes))
		)
		for i in threads: i.start()
		for i in threads: i.join()
		return checked_hashes

import re, random, requests
from fenom.client import randomagent

session = requests.session()
session.headers.update({'User-Agent': randomagent(), 'Accept': 'application/json'})

def aio_check_cache(imdb, season, episode, collector):
	if str(season).isdigit(): params = {'type': 'series', 'id': '%s:%s:%s' % (imdb, season, episode)}
	else: params = {'type': 'movie', 'id': '%s' % imdb}
	headers, url = {'x-aiostreams-user-data': (
		'ewogICJzZXJ2aWNlcyI6IFsKICAgIHsKICAgICAgImlkIjogImFsbGRlYnJpZCIsCiAgICAgICJlbmFi'
		'bGVkIjogdHJ1ZSwKICAgICAgImNyZWRlbnRpYWxzIjogeyJhcGlLZXkiOiAic3RhdGljRGVtb0FwaWtl'
		'eVByZW0ifQogICAgfQogIF0sCiAgInByZXNldHMiOiBbCiAgICB7CiAgICAgICJ0eXBlIjogIm1lZGlh'
		'ZnVzaW9uIiwKICAgICAgImluc3RhbmNlSWQiOiAiNWI4IiwKICAgICAgImVuYWJsZWQiOiB0cnVlLAog'
		'ICAgICAib3B0aW9ucyI6IHsKICAgICAgICAibmFtZSI6ICJNZWRpYUZ1c2lvbiIsCiAgICAgICAgInRp'
		'bWVvdXQiOiA2NTAwLAogICAgICAgICJyZXNvdXJjZXMiOiBbInN0cmVhbSJdLAogICAgICAgICJ1c2VD'
		'YWNoZWRSZXN1bHRzT25seSI6IHRydWUsCiAgICAgICAgImVuYWJsZVdhdGNobGlzdENhdGFsb2dzIjog'
		'ZmFsc2UsCiAgICAgICAgImRvd25sb2FkVmlhQnJvd3NlciI6IGZhbHNlLAogICAgICAgICJjb250cmli'
		'dXRvclN0cmVhbXMiOiBmYWxzZSwKICAgICAgICAiY2VydGlmaWNhdGlvbkxldmVsc0ZpbHRlciI6IFtd'
		'LAogICAgICAgICJudWRpdHlGaWx0ZXIiOiBbXSwKICAgICAgICAibWVkaWFUeXBlcyI6IFtdCiAgICAg'
		'IH0KICAgIH0sCiAgICB7CiAgICAgICJ0eXBlIjogInN0cmVtdGhydVRvcnoiLAogICAgICAiaW5zdGFu'
		'Y2VJZCI6ICI1NDgiLAogICAgICAiZW5hYmxlZCI6IHRydWUsCiAgICAgICJvcHRpb25zIjogewogICAg'
		'ICAgICJuYW1lIjogIlN0cmVtVGhydSBUb3J6IiwKICAgICAgICAidGltZW91dCI6IDY1MDAsCiAgICAg'
		'ICAgInJlc291cmNlcyI6IFsic3RyZWFtIl0sCiAgICAgICAgIm1lZGlhVHlwZXMiOiBbXSwKICAgICAg'
		'ICAiaW5jbHVkZVAyUCI6IGZhbHNlLAogICAgICAgICJ1c2VNdWx0aXBsZUluc3RhbmNlcyI6IGZhbHNl'
		'CiAgICAgIH0KICAgIH0KICBdLAogICJmb3JtYXR0ZXIiOiB7CiAgICAiaWQiOiAidG9ycmVudGlvIiwK'
		'ICAgICJkZWZpbml0aW9uIjogewogICAgICAibmFtZSI6ICIiLAogICAgICAiZGVzY3JpcHRpb24iOiAi'
		'IgogICAgfQogIH0sCiAgInNvcnRDcml0ZXJpYSI6IHsKICAgICJnbG9iYWwiOiBbXQogIH0sCiAgImRl'
		'ZHVwbGljYXRvciI6IHsKICAgICJlbmFibGVkIjogZmFsc2UsCiAgICAia2V5cyI6IFsiaW5mb0hhc2gi'
		'XSwKICAgICJtdWx0aUdyb3VwQmVoYXZpb3VyIjogImFnZ3Jlc3NpdmUiLAogICAgImNhY2hlZCI6ICJz'
		'aW5nbGVfcmVzdWx0IiwKICAgICJ1bmNhY2hlZCI6ICJwZXJfc2VydmljZSIsCiAgICAicDJwIjogInNp'
		'bmdsZV9yZXN1bHQiLAogICAgImV4Y2x1ZGVBZGRvbnMiOiBbXQogIH0sCiAgImV4Y2x1ZGVVbmNhY2hl'
		'ZCI6IHRydWUKfQ=='
	)}, 'https://aiostreams.fortheweak.cloud/api/v1/search'
	try:
		results = requests.get(url, params=params, headers=headers, timeout=7.05)
		files = results.json()['data']['results']
		collector.extend(file['infoHash'] for file in files if file['cached'] and file.get('infoHash'))
	except Exception as e: kodi_utils.logger('aio error', str(e))

def tio_check_cache(imdb, season, episode, collector):
	if str(season).isdigit(): url = 'series/%s:%s:%s.json' % (imdb, season, episode)
	else: url = 'movie/%s.json' % (imdb)
	params = 'realdebrid=T2iZoymNCCD1T5c2sX5u8tIZVcgcFWlCsCJ72rCmrU2mDdmvgieM'
	url = 'https://torrentio.strem.fun/debridoptions=nodownloadlinks,nocatalog|%s/stream/%s' % (params, url)
	pattern = re.compile(r'\b\w{40}\b')
	try:
		results = session.get(url, timeout=7.05)
		files = results.json()['streams']
		collector.extend(pattern.findall(file['url'])[-1] for file in files if '+' in file['name'] and 'url' in file)
	except Exception as e: kodi_utils.logger('tio error', str(e))

def dmm_check_cache(unchecked_hashes_chunk, imdb, collector): # DMM API Allows max 100 hashes per request.
	""" do not thread multiple calls, abusing the api will get it turned off
		100 sample size should be enough """
	from magneto.dmm import get_secret
	unchecked_hashes_chunk = [i for i in unchecked_hashes_chunk if len(i) == 40]
	if len(unchecked_hashes_chunk) > 100: unchecked_hashes_chunk = random.sample(unchecked_hashes_chunk, 100)
	url = 'https://debridmediamanager.com/api/availability/check'
	dmmProblemKey, solution = get_secret()
	data = {'dmmProblemKey': dmmProblemKey, 'solution': solution, 'imdbId': imdb, 'hashes': unchecked_hashes_chunk}
	try:
		results = session.post(url, json=data, timeout=7.05)
		files = results.json()['available']
		collector.extend(file['hash'] for file in files if 'hash' in file)
	except Exception as e: kodi_utils.logger('dmm error', str(e))

