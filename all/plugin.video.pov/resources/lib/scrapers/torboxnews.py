import requests
from base64 import b64encode
from modules import kodi_utils, source_utils
from modules.settings import enabled_debrids_check, filter_by_name
# from modules.kodi_utils import logger

internal_results, check_title = source_utils.internal_results, source_utils.check_title
clean_file_name, clean_title = source_utils.clean_file_name, source_utils.clean_title
get_file_info, seas_ep_filter = source_utils.get_file_info, source_utils.seas_ep_filter
extensions, extras_filter = source_utils.supported_video_extensions(), source_utils.extras_filter()

class source:
	timeout = 10
	scrape_provider = 'torboxnews'
	def results(self, info):
		try:
			self.sources = []
			sources_append = self.sources.append
			if not enabled_debrids_check('tb'): return internal_results(self.scrape_provider, self.sources)
			self.scrape_results = []
			title, season, episode = info.get('title'), info.get('season'), info.get('episode')
			self.aliases = source_utils.get_aliases_titles(info.get('aliases', []))
			self.search(self.timeout, info.get('imdb_id'), season, episode)
			if not self.scrape_results: return internal_results(self.scrape_provider, self.sources)
			extras_filtering_list = tuple(i for i in extras_filter if i not in title.lower())
			for item in self.scrape_results:
				try:
					hash = item['infoHash']
					normalized = clean_title(item['filename'])
					url = item['nzbUrl']
					try: seeders = int(item['seeders'])
					except: seeders = 0
					try: size = int(item['size'])
					except: size = 0

					URLName = clean_file_name(item['filename']).replace('html', ' ')
					size = round(float(size)/1073741824, 2)
					size_label = '%.2f GB' % size
					video_quality, details = get_file_info(name_info=normalized)
					if item['cached']: source = {'cache_provider': 'torbox', 'debrid': 'torbox'}
					else: source = {'cache_provider': 'Uncached torbox', 'debrid': 'torbox'}
					source.update({
						# source module definition
						'source': 'usenet', 'language': 'en', 'direct': False, 'debridonly': True,
						'provider': 'torboxnews', 'hash': hash, 'url': url, 'name': URLName, 'name_info': details,
						'quality': video_quality, 'info': size_label, 'size': size, 'seeders': seeders,
						'tracker': item['indexer'] or self.scrape_provider,
						# added by addon in process_sources
						'scrape_provider': 'external', 'external': True,
						'URLName': URLName, 'extraInfo': details, 'size_label': size_label
					})
					sources_append(source)
				except: pass
		except Exception as e:
			from modules.kodi_utils import logger
			logger(f"POV {self.scrape_provider} Exception", e)
		internal_results(self.scrape_provider, self.sources)
		return self.sources

	def search(self, timeout, imdb_id, season, episode):
		try:
			timeout = max(timeout, int(kodi_utils.get_setting('scrapers.timeout.1', '0')))
			user_engines_only = 'true' if kodi_utils.get_setting('tb.user_engines_only') == 'true' else 'false'
			b_str = x_aiostreams_user_data % (timeout * 950, user_engines_only, kodi_utils.get_setting('tb.token'))
			headers = {'x-aiostreams-user-data': b64encode(b_str.encode()).decode()}
			if season: params = {'type': 'series', 'id': '%s:%s:%s' % (imdb_id, season, episode)}
			else: params = {'type': 'movie', 'id': imdb_id}
			url = '%s/api/v1/search' % x_aiostreams_url
			results = requests.get(url, params=params, headers=headers, timeout=timeout).json()
			self.scrape_results.extend(results['data']['results'])
		except requests.RequestException as e:
			kodi_utils.logger(f"{self.scrape_provider} error", str(e))
		except: pass

x_aiostreams_user_data, x_aiostreams_url = (
	'{"sortCriteria":{"global":[]},"deduplicator":{"enabled":false},"formatte'
	'r":{"id":"torrentio"},"presets":[{"type":"torbox-search","instanceId":"v'
	'0p","enabled":true,"options":{"timeout":%d,"name":"TorBoxSearch","source'
	's":["usenet"],"mediaTypes":[],"useMultipleInstances":false,"userSearchEn'
	'gines":true,"onlyShowUserSearchResults":%s}}],"services":[{"id":"torbox"'
	',"enabled":true,"credentials":{"apiKey":"%s"}}]}'
), 'https://aiostreamsfortheweebsstable.midnightignite.me'

