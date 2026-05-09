from threading import Thread
from debrids.torbox_api import TorBoxAPI as Debrid
from modules import source_utils
from modules.utils import clean_file_name, normalize
from modules.settings import enabled_debrids_check, filter_by_name
# from modules.kodi_utils import logger

internal_results, check_title, clean_title = source_utils.internal_results, source_utils.check_title, source_utils.clean_title
get_file_info, release_info_format, seas_ep_filter = source_utils.get_file_info, source_utils.release_info_format, source_utils.seas_ep_filter
extensions, extras_filter = source_utils.supported_video_extensions(), source_utils.extras_filter()

class source(Debrid):
	scrape_provider = 'tb_cloud'
	def results(self, info):
		try:
			self.sources = []
			sources_append = self.sources.append
			if not enabled_debrids_check('tb'): return internal_results(self.scrape_provider, self.sources)
			self.scrape_results = []
			title_filter = filter_by_name(self.scrape_provider)
			self.mediatype, title = info.get('mediatype'), info.get('title')
			self.year, self.season, self.episode = int(info.get('year')), info.get('season'), info.get('episode')
			if self.mediatype == 'episode': self.seas_ep_query_list = source_utils.seas_ep_query_list(self.season, self.episode)
			self.folder_query, self.year_query_list = clean_title(normalize(title)), tuple(map(str, range(self.year - 1, self.year + 2)))
			self._scrape_cloud()
			if not self.scrape_results: return internal_results(self.scrape_provider, self.sources)
			self.aliases = source_utils.get_aliases_titles(info.get('aliases', []))
			extras_filtering_list = tuple(i for i in extras_filter if i not in title.lower())
			for item in self.scrape_results:
				try:
					if not item['filename'].lower().endswith(tuple(extensions)): continue
					formalized = normalize(item['folder_name'])
					foldername = clean_title(formalized)
					normalized = normalize(item['filename'])
					filename = clean_title(normalized)
					if self.mediatype == 'movie':
						if any(x in filename for x in extras_filtering_list): continue
						if not (
							any(x in filename for x in self.year_query_list)
							or # usenet obfuscation
							any(x in foldername for x in self.year_query_list)
						): continue
					elif not (
						seas_ep_filter(self.season, self.episode, normalized)
						or # usenet obfuscation
						seas_ep_filter(self.season, self.episode, formalized)
					): continue
					if not (self.folder_query in filename or self.folder_query in foldername): continue

					if title_filter and not check_title(title, normalized, self.aliases, self.year, self.season, self.episode): continue
					direct_debrid_link, URLName = item['mediatype'], clean_file_name(normalized).replace('html', ' ').replace('+', ' ').replace('-', ' ')
					file_dl, size = item['link'], round(float(item['size'])/1073741824, 2)
					video_quality, details = get_file_info(name_info=release_info_format(normalized))
					sources_append({
						'source': self.scrape_provider, 'direct': True, 'direct_debrid_link': direct_debrid_link,
						'scrape_provider': self.scrape_provider, 'id': file_dl, 'url_dl': file_dl, 'name': normalized, 'title': normalized,
						'URLName': URLName, 'extraInfo': details, 'quality': video_quality, 'size': size, 'size_label': '%.2f GB' % size
					})
				except: pass
		except Exception as e:
			from modules.kodi_utils import logger
			logger(f"POV {self.scrape_provider} Exception", e)
		internal_results(self.scrape_provider, self.sources)
		return self.sources

	def _scrape_cloud(self):
		try:
			results_append = self.scrape_results.append
			for i in (threads := (
				Thread(target=self._scrape_folders, args=(self.user_cloud, 'torent')),
				Thread(target=self._scrape_folders, args=(self.user_cloud_usenet, 'usenet')),
				Thread(target=self._scrape_folders, args=(self.user_cloud_webdl, 'webdl'))
			)): i.start()
			[i.join() for i in threads]
		except: pass

	def _scrape_folders(self, function, mediatype):
		try:
			results_append = self.scrape_results.append
			folder = function(check_cache=False)
			for file in folder:
				for item in file['files']:
					try: item.update({
						'filename': item['short_name'], 'folder_name': file['name'],
						'mediatype': mediatype, 'link': '%d,%d' % (file['id'], item['id'])
					})
					except: pass
					else: results_append(item)
		except: pass

