from debrids.easynews_api import EasyNewsAPI as Debrid
from modules import source_utils
from modules.utils import clean_file_name, normalize
from modules.settings import filter_by_name, easynews_language_filter
# from modules.kodi_utils import logger

internal_results, check_title = source_utils.internal_results, source_utils.check_title
get_file_info, release_info_format = source_utils.get_file_info, source_utils.release_info_format

class source(Debrid):
	scrape_provider = 'easynews'
	def results(self, info):
		try:
			self.sources = []
			sources_append = self.sources.append
			filter_lang, lang_filters = easynews_language_filter()
			title_filter = filter_by_name('easynews')
			self.mediatype, title, self.year = info.get('mediatype'), info.get('title'), int(info.get('year'))
			self.season, self.episode = info.get('season'), info.get('episode')
			self.search_title = clean_file_name(title).replace('&', 'and')
			if self.mediatype == 'movie': query = '%s %d' % (self.search_title, self.year)
			else: query = '%s S%02dE%02d' % (self.search_title, self.season, self.episode)
			self.scrape_results = self.search(query, info.get('expiry_times')[0])
			if not self.scrape_results: return internal_results(self.scrape_provider, self.sources)
			self.aliases = source_utils.get_aliases_titles(info.get('aliases', []))
			for item in self.scrape_results:
				try:
					if filter_lang and not any(i in lang_filters for i in item['language']) : continue
					normalized = normalize(item['name'])

					if title_filter and not check_title(title, normalized, self.aliases, self.year, self.season, self.episode): continue
					URLName = clean_file_name(normalized).replace('html', ' ').replace('+', ' ').replace('-', ' ')
					url_dl, size = item['url_dl'], round(float(int(item['rawSize']))/1073741824, 2)
					video_quality, details = get_file_info(name_info=release_info_format(normalized))
					sources_append({
						'source': self.scrape_provider, 'direct': True,
						'scrape_provider': self.scrape_provider, 'id': url_dl, 'url_dl': url_dl, 'name': normalized, 'title': normalized,
						'URLName': URLName, 'extraInfo': details, 'quality': video_quality, 'size': size, 'size_label': '%.2f GB' % size
					})
				except: pass
		except Exception as e:
			from modules.kodi_utils import logger
			logger(f"POV {self.scrape_provider} Exception", e)
		internal_results(self.scrape_provider, self.sources)
		return self.sources

