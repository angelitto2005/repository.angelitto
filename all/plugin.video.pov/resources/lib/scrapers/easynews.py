from debrids.easynews_api import EasyNewsAPI as Debrid
from modules import source_utils
from modules.settings import filter_by_name, easynews_language_filter
# from modules.kodi_utils import logger

internal_results, check_title = source_utils.internal_results, source_utils.check_title
clean_file_name, clean_title = source_utils.clean_file_name, source_utils.clean_title
get_file_info = source_utils.get_file_info

class source(Debrid):
	scrape_provider = 'easynews'
	def results(self, info):
		try:
			self.sources = []
			sources_append = self.sources.append
			filter_lang, lang_filters = easynews_language_filter()
			title, season, episode = info.get('title'), info.get('season'), info.get('episode')
			search_title = clean_file_name(title).replace('&', 'and')
			if season: query = '%s S%02dE%02d' % (search_title, season, episode)
			else: query = '%s %d' % (search_title, int(info.get('year')))
			if not filter_by_name(self.scrape_provider): self.aliases = None
			else: self.aliases = source_utils.get_aliases_titles(info.get('aliases', []))
			self.scrape_results = self.search(query, info.get('expiry_times')[0])
			if not self.scrape_results: return internal_results(self.scrape_provider, self.sources)
			for item in self.scrape_results:
				try:
					if filter_lang and not any(i in lang_filters for i in item['language']) : continue
					if not check_title(title, item['name'], self.aliases): continue
					normalized = clean_title(item['name'])

					URLName = clean_file_name(item['name']).replace('html', ' ')
					file_dl, size = item['url_dl'], round(float(int(item['rawSize']))/1073741824, 2)
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

