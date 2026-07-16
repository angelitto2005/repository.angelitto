from threading import Thread
from debrids.torbox_api import TorBoxAPI as Debrid
from modules import source_utils
from modules.settings import enabled_debrids_check, filter_by_name
# from modules.kodi_utils import logger

internal_results, check_title = source_utils.internal_results, source_utils.check_title
clean_file_name, clean_title = source_utils.clean_file_name, source_utils.clean_title
get_file_info, seas_ep_filter = source_utils.get_file_info, source_utils.seas_ep_filter
extensions, extras_filter = source_utils.supported_video_extensions(), source_utils.extras_filter()

class source(Debrid):
	scrape_provider = 'tb_cloud'
	def results(self, info):
		try:
			self.sources = []
			sources_append = self.sources.append
			if not enabled_debrids_check('tb'): return internal_results(self.scrape_provider, self.sources)
			self.scrape_results = []
			title, season, episode = info.get('title'), info.get('season'), info.get('episode')
			if not filter_by_name(self.scrape_provider): self.aliases = None
			else: self.aliases = source_utils.get_aliases_titles(info.get('aliases', []))
			self._scrape_cloud()
			if not self.scrape_results: return internal_results(self.scrape_provider, self.sources)
			extras_filtering_list = tuple(i for i in extras_filter if i not in title.lower())
			for item in self.scrape_results:
				try:
					normalized = clean_title(item['filename'])
					if not normalized.endswith(tuple(extensions)): continue
					for i in ('filename', 'folder_name'):
						if check_title(title, item[i], self.aliases): break
					else: continue
					if season:
						if not (
							seas_ep_filter(season, episode, item['filename'])
							or # usenet obfuscation
							seas_ep_filter(season, episode, item['folder_name'])
						): continue
					elif any(x in normalized for x in extras_filtering_list): continue

					URLName = clean_file_name(item['filename']).replace('html', ' ')
					file_dl, size = item['link'], round(float(item['size'])/1073741824, 2)
					video_quality, details = get_file_info(name_info=normalized)
					sources_append({
						'direct': True,
						'source': self.scrape_provider, 'scrape_provider': self.scrape_provider,
						'id': file_dl, 'url_dl': file_dl,
						'name': URLName, 'URLName': URLName,
						'extraInfo': details, 'quality': video_quality,
						'size': size, 'size_label': '%.2f GB' % size
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
				Thread(target=self._scrape_folders, args=(self._get, 'torrents')),
				Thread(target=self._scrape_folders, args=(self._get, 'usenet')),
				Thread(target=self._scrape_folders, args=(self._get, 'webdl'))
			)): i.start()
			[i.join() for i in threads]
		except: pass

	def _scrape_folders(self, function, mediatype):
		try:
			results_append = self.scrape_results.append
			folder = function('%s/mylist?bypass_cache=true' % mediatype)
			for file in folder:
				if not file['download_finished']: continue
				for item in file['files']:
					try: item.update({
						'filename': item['short_name'], 'folder_name': file['name'],
						'link': '%s,%s,%s' % (file['id'], item['id'], mediatype)
					})
					except: pass
					else: results_append(item)
		except: pass

