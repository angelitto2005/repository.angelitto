import hashlib
from debrids.torbox_api import TorBoxAPI as Debrid
from modules import kodi_utils, source_utils
from modules.utils import clean_file_name, normalize
from modules.settings import enabled_debrids_check, filter_by_name
# from modules.kodi_utils import logger

internal_results, check_title, clean_title = source_utils.internal_results, source_utils.check_title, source_utils.clean_title
get_file_info, release_info_format, seas_ep_filter = source_utils.get_file_info, source_utils.release_info_format, source_utils.seas_ep_filter
extensions, extras_filter = source_utils.supported_video_extensions(), source_utils.extras_filter()

class source(Debrid):
	scrape_provider = 'torboxnews'
	def results(self, info):
		try:
			self.sources = []
			sources_append = self.sources.append
			if not enabled_debrids_check('tb'): return internal_results(self.scrape_provider, self.sources)
			self.scrape_results = []
			title_filter = True # filter_by_name(self.scrape_provider)
			self.mediatype, title = info.get('mediatype'), info.get('title')
			self.year, self.season, self.episode = int(info.get('year')), info.get('season'), info.get('episode')
			if self.mediatype == 'episode': self.seas_ep_query_list = source_utils.seas_ep_query_list(self.season, self.episode)
			self.folder_query, self.year_query_list = clean_title(normalize(title)), tuple(map(str, range(self.year - 1, self.year + 2)))
			self.search(self.mediatype, info.get('imdb_id'), self.season, self.episode)
			if not self.scrape_results: return internal_results(self.scrape_provider, self.sources)
			self.aliases = source_utils.get_aliases_titles(info.get('aliases', []))
			extras_filtering_list = tuple(i for i in extras_filter if i not in title.lower())
			for item in self.scrape_results:
				try:
					if self.user_engines_only and not item['user_search']: continue
					hash = item['hash'] or hashlib.md5(item['nzb'].encode('utf-8')).hexdigest()
					normalized = normalize(item['raw_title'])
					url = item['nzb']
					try: seeders = int(item['last_known_seeders'])
					except: seeders = 0
					try: size = int(item['size'])
					except: size = 0

					if title_filter and not check_title(title, normalized, self.aliases, self.year, self.season, self.episode): continue
					URLName = clean_file_name(normalized).replace('html', ' ').replace('+', ' ').replace('-', ' ')
					size = round(float(size)/1073741824, 2)
					size_label = '%.2f GB' % size
					video_quality, details = get_file_info(name_info=release_info_format(normalized))
					if item['cached']: source = {'cache_provider': 'torbox', 'debrid': 'torbox'}
					else: source = {'cache_provider': 'Uncached torbox', 'debrid': 'torbox'}
					source.update({
						'source': 'usenet', 'language': 'en', 'direct': False, 'debridonly': True,
						'provider': 'torboxnews', 'hash': hash, 'url': url, 'name': normalized, 'name_info': details,
						'quality': video_quality, 'info': size_label, 'size': size, 'seeders': seeders,
						'tracker': item['tracker'] or self.scrape_provider, 'age': item['age']
					}) # source module definition
					source.update({
						'external': True, 'scrape_provider': 'external', 'URLName': URLName,
						'extraInfo': details, 'size_label': size_label
					}) # added by addon in process_sources
					sources_append(source)
				except: pass
		except Exception as e:
			from modules.kodi_utils import logger
			logger(f"POV {self.scrape_provider} Exception", e)
		internal_results(self.scrape_provider, self.sources)
		return self.sources

	def search(self, mediatype, imdb_id, season, episode):
		try:
			url = 'https://search-api.torbox.app/usenet/imdb:%s' % imdb_id
			params = {'check_cache': 'true', 'check_owned': 'true', 'search_user_engines': 'true'}
			if mediatype == 'episode': params.update({'season': int(season), 'episode': int(episode)})
			results = self._get(url, params=params)
			self.scrape_results.extend(results['nzbs'])
			self.user_engines_only = kodi_utils.get_setting('tb.user_engines_only') == 'true'
		except: pass

