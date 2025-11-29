# -*- coding: utf-8 -*-
# Thanks to kodifitzwell for allowing me to borrow his code
from threading import Thread
from apis.offcloud_api import Offcloud
from modules import source_utils
from modules.utils import clean_file_name, normalize
from modules.settings import enabled_debrids_check, filter_by_name
# from modules.kodi_utils import logger

class source:
	def __init__(self):
		self.scrape_provider = 'oc_cloud'
		self.sources = []
		self.extensions = source_utils.supported_video_extensions()

	def results(self, info):
		try:
			if not enabled_debrids_check('oc'): return source_utils.internal_results(self.scrape_provider, self.sources)
			self.scrape_results = []
			filter_title = filter_by_name(self.scrape_provider)
			self.media_type, title = info.get('media_type'), info.get('title')
			self.year, self.season, self.episode = int(info.get('year')), info.get('season'), info.get('episode')
			self.folder_query = source_utils.clean_title(normalize(title))
			self._scrape_cloud()
			if not self.scrape_results: return source_utils.internal_results(self.scrape_provider, self.sources)
			self.aliases = source_utils.get_aliases_titles(info.get('aliases', []))
			def _process():
				for item in self.scrape_results:
					try:
						file_name = item['filename']
						if filter_title and not source_utils.check_title(title, file_name, self.aliases, self.year, self.season, self.episode): continue
						display_name = clean_file_name(file_name).replace('html', ' ').replace('+', ' ').replace('-', ' ')
						file_dl, size = Offcloud.requote_uri(item['url']), 0
						video_quality, details = source_utils.get_file_info(name_info=source_utils.release_info_format(file_name))
						source_item = {'name': file_name, 'display_name': display_name, 'quality': video_quality, 'size': size, 'size_label': '%.2f GB' % size, 'debrid': self.scrape_provider,
									'extraInfo': details, 'url_dl': file_dl, 'id': file_dl, 'downloads': False, 'direct': True, 'source': self.scrape_provider,
									'scrape_provider': self.scrape_provider, 'direct_debrid_link': True}
						yield source_item
					except: pass
			self.sources = list(_process())
		except Exception as e:
			from modules.kodi_utils import logger
			logger('offcloud scraper Exception', e)
		source_utils.internal_results(self.scrape_provider, self.sources)
		return self.sources

	def _scrape_cloud(self):
		try:
			threads = []
			append = threads.append
			results_append = self.scrape_results.append
			year_query_list = self._year_query_list()
			try: my_cloud_files = Offcloud.user_cloud()
			except: return self.sources
			for item in my_cloud_files:
				try:
					raw_name = item['fileName']
					normalized = normalize(raw_name)
					if item['status'] != 'downloaded': continue
					file_folder_name = source_utils.clean_title(normalized)
					if item['isDirectory']:
						if not file_folder_name: append(Thread(target=self._scrape_folders, args=(item['requestId'],)))
						elif not self.folder_query in file_folder_name: continue
						else:
							if self.media_type == 'movie' and not any(x in normalized for x in year_query_list): continue
							append(Thread(target=self._scrape_folders, args=(item['requestId'],)))
					else:
						if not raw_name.endswith(tuple(self.extensions)): continue
						if self.media_type == 'movie':
							if not self.folder_query in file_folder_name: continue
							if not any(x in file_folder_name for x in year_query_list): continue
						elif not source_utils.seas_ep_filter(self.season, self.episode, normalized): continue
						results_append({'filename': normalized, 'url': Offcloud.build_url(item['server'], item['requestId'], item['fileName'])})
				except: pass
			[i.start() for i in threads]
			[i.join() for i in threads]
		except: pass

	def _scrape_folders(self, folder_info):
		try:
			results_append = self.scrape_results.append
			torrent_info = Offcloud.torrent_info(folder_info)
			year_query_list = self._year_query_list()
			for item in torrent_info:
				try:
					if not item.endswith(tuple(self.extensions)): continue
					normalized = normalize(item.split('/')[-1])
					file_name = source_utils.clean_title(normalized)
					if self.media_type == 'movie':
						if not self.folder_query in file_name: continue
						if not any(x in file_name for x in year_query_list): continue
					elif not source_utils.seas_ep_filter(self.season, self.episode, normalized): continue
					results_append({'filename': normalized, 'url': item})
				except: continue
		except: return

	def _year_query_list(self):
		return (str(self.year), str(self.year+1), str(self.year-1))

