import json
from threading import Thread
from caches.debrid_cache import DebridCache
from indexers import alldebrid_api, offcloud_api, premiumize_api, realdebrid_api, torbox_api
from indexers import metadata
from modules import kodi_utils, settings
# from modules.kodi_utils import logger

ls, get_setting = kodi_utils.local_string, kodi_utils.get_setting
show_busy_dialog, hide_busy_dialog = kodi_utils.show_busy_dialog, kodi_utils.hide_busy_dialog
confirm_dialog, select_dialog = kodi_utils.confirm_dialog, kodi_utils.select_dialog
default_internal_scrapers = settings.default_internal_scrapers()
default_external_scrapers = settings.default_external_scrapers()
plswait_str, checking_debrid_str, remaining_debrid_str, size_str = ls(32577), ls(32578), ls(32579), ls(32584)

debrid_list = (
	('premiumize', 'pm', premiumize_api.PremiumizeAPI),
	('offcloud', 'oc', offcloud_api.OffcloudAPI),
	('torbox', 'tb', torbox_api.TorBoxAPI),
	('realdebrid', 'rd', realdebrid_api.RealDebridAPI),
	('alldebrid', 'ad', alldebrid_api.AllDebridAPI)
)

def import_debrid(debrid_provider):
	cls = next((i[2] for i in debrid_list if i[0] == debrid_provider), None)
	return cls() if cls else cls

def debrid_enabled():
	return [i[0] for i in debrid_list if settings.enabled_debrids_check(i[1])]

def debrid_type_enabled(debrid_type, enabled_debrids):
	return [i[0] for i in debrid_list if i[0] in enabled_debrids and get_setting('%s.%s.enabled' % (i[1], debrid_type)) == 'true']

def play_from_cloud(params):
	source = Source.fromcloud(params)
	url = source.resolve_internal_sources(source.direct_debrid_link)
	return kodi_utils.execute_builtin('PlayMedia(%s)' % url)

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
			extensions = tuple(supported_video_extensions())
			extras_filtering_list = tuple(i for i in extras_filter() if i not in title.lower())
			if self.url.startswith('magnet'):
				store_to_cloud = settings.store_resolved_torrent_to_cloud(self.debrid)
			else: store_to_cloud = settings.store_resolved_usenet_to_cloud(self.debrid)
			if self.debrid in ('realdebrid', 'alldebrid'): args = self.url, self.hash, True
			else: args = self.url, self.hash
			api = import_debrid(self.debrid)
			files = api.parse_magnet_pack(*args)
			selected_files = []
			selected_files_append = selected_files.append
			for i in files or []:
				torrent_id, filename = i.get('torrent_id'), i['filename'].lower()
				if filename.endswith('.m2ts'): raise Exception('_m2ts_check failed')
				if not filename.endswith(extensions): continue
				if season:
					if not seas_ep_filter(season, episode, filename): continue
				elif any(x in filename for x in extras_filtering_list): continue
				selected_files_append(i)
			if not selected_files: raise Exception('selected_files failed')
			selected_files.sort(key=lambda k: k['size'], reverse=True)
			file_key = next((i['link'] for i in selected_files), None)
			file_url = api.unrestrict_link(file_key)
			if not api.defaults_to_cloud:
				if store_to_cloud: Thread(target=api.create_transfer, args=(self.url,)).start()
			if api.defaults_to_cloud:
				if not store_to_cloud: self._delete(api, torrent_id)
			return file_url
		except Exception as e:
			kodi_utils.logger('resolve_external_sources exception', f"{e}\n{self.dumps()}")
			if files and torrent_id: self._delete(api, torrent_id)

	def _delete(self, api, torrent_id):
		Thread(target=api.delete_torrent, args=(torrent_id,)).start()

	def resolve_internal_sources(self, direct_debrid_link=False):
		try:
			if self.scrape_provider == 'tb_cloud':
				url = torbox_api.TorBoxAPI().unrestrict_link(self.id)
			elif self.scrape_provider == 'rd_cloud':
				if direct_debrid_link: url = self.url_dl
				else: url = realdebrid_api.RealDebridAPI().unrestrict_link(self.id)
			elif self.scrape_provider == 'ad_cloud':
				if direct_debrid_link: url = self.url_dl
				else: url = alldebrid_api.AllDebridAPI().unrestrict_link(self.id)
			elif self.scrape_provider == 'easynews':
				from indexers.easynews_api import EasyNewsAPI
				url = EasyNewsAPI().unrestrict_link(self.url_dl)
				if not direct_debrid_link: url += '|seekable=0'
			elif self.scrape_provider == 'aiostreams':
				from debrids.aiostreams import unrestrict_link
				url = unrestrict_link(self.url_dl)
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
		if not pack_choices: return None if download else kodi_utils.no_results()
		pack_choices.sort(key=lambda k: k['filename'].lower())
		for item in pack_choices: item.update({
			'icon': self.meta.get('poster') or api.icon,
			'line1': clean_file_name(item['filename']),
			'line2': '%s: %.2f GB' % (size_str, float(item['size'])/1073741824)
		})
		if download: return pack_choices
		kwargs = {'items': json.dumps(pack_choices), 'heading': self.name, 'highlight': highlight}
		chosen_result = select_dialog(pack_choices, **kwargs)
		if chosen_result is None: return 'cancel'
		url_dl = chosen_result['link']
		return api.unrestrict_link(url_dl)

	def manual_add_magnet_to_cloud(self):
		if not confirm_dialog(text=ls(32687) % self.debrid.upper()): return
		show_busy_dialog()
		api = import_debrid(self.debrid)
		api.clear_cache()
		result = api.create_transfer(self.url)
		hide_busy_dialog()
		if result: kodi_utils.notify_success()
		else: kodi_utils.notify_failed()

	def manual_airlock_to_cloud(self):
		if not confirm_dialog(text=ls(32687) % self.debrid.upper()): return
		show_busy_dialog()
		api = import_debrid(self.debrid)
		api.clear_cache()
		request_id = api.create_transfer(self.url)
		if not request_id: return kodi_utils.notify_error()
		mediatype = 'torrents' if self.url.startswith('magnet') else 'usenet'
		result = api.toggle_airlock(mediatype, request_id, True)
		hide_busy_dialog()
		if result: kodi_utils.notify_success()
		else: kodi_utils.notify_failed()

	def aio_add_to_cloud(self):
		if not confirm_dialog(text=ls(32687) % self.debrid.upper()): return
		if not getattr(self, 'url_dl', False): return kodi_utils.notify_error()
		url, *headers = self.url_dl.rsplit('|', 1)
		try: headers = dict(kodi_utils.parse_qsl(*headers))
		except: headers = dict()
		import requests
		response = requests.get(url, headers=headers, stream=True, timeout=10)
		if not response.ok: return kodi_utils.notify_error()
		chunk = next(response.iter_content(chunk_size=1048576), b'')
		if len(chunk): kodi_utils.notify_success()
		else: kodi_utils.notify_failed()

	def unchecked_magnet_status(self):
		show_busy_dialog()
		api = import_debrid(self.debrid)
		result = api.parse_magnet_pack(self.url, self.hash)
		hide_busy_dialog()
		if not result: return kodi_utils.ok_dialog(text='Not Cached at [B]%s[/B]' % self.debrid.upper())
		torrent_id = next((i['torrent_id'] for i in result if 'torrent_id' in i), None)
		if torrent_id: Thread(target=api.delete_torrent, args=(torrent_id,)).start()
		kodi_utils.ok_dialog(text='Cached at [B]%s[/B]' % self.debrid.upper())

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
			if self.debrid in ('rd', 'realdebrid'):
				# removed dmm_check_cache, 403 Forbidden
				checked_hashes = realdebrid_api.tio_check_cache(self.imdb, self.season, self.episode)
			elif self.debrid in ('ad', 'alldebrid'):
				checked_hashes = alldebrid_api.aio_check_cache(self.imdb, self.season, self.episode)
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

