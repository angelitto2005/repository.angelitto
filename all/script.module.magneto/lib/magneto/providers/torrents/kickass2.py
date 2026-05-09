# modified by Venom for Fenomscrapers
"""
	Fenomscrapers Project
"""

import re
from urllib.parse import quote_plus, unquote_plus
from magneto.modules import cache
from magneto.modules import client
from magneto.modules import source_utils
from magneto.modules import workers


class source:
	priority = 4
	pack_capable = True
	hasMovies = True
	hasEpisodes = True
	def __init__(self):
		self.language = ['en']
		self.domains = ['kick4ss.com', 'thekat.info', 'kickass.cm', 'kickass.ws', 'kickasst.net',
								'kickasshydra.dev', 'kickasshydra.net', 'kathydra.com', 'kickass.onl',
								'kickasstorrents.id', 'thekat.cc', 'kkat.net', 'kickasstorrents.bz']
		self._base_link = None
		self.moviesearch = '/usearch/{0}%20category:movies/?field=size&sorder=desc'
		self.tvsearch = '/usearch/{0}%20category:tv/?field=size&sorder=desc'
		self.min_seeders = 0

	@property
	def base_link(self):
		if not self._base_link:
			self._base_link = cache.get(self.__get_base_url, 120, 'https://%s' % self.domains[0])
		return self._base_link

	def __get_base_url(self, fallback):
		for domain in self.domains:
			try:
				url = 'https://%s' % domain
				result = client.request(url, limit=1, timeout=5)
				try: result = re.search('r<title>(.+?)</title>', result, re.I).group(1)
				except: result = None
				if result and 'Kickass' in result: return url
			except:
				source_utils.scraper_error('KICKASS2')
		return fallback

	def sources(self, data, hostDict):
		self.sources = []
		if not data: return self.sources
		self.sources_append = self.sources.append
		try:
			self.aliases = data['aliases']
			self.year = data['year']
			if 'tvshowtitle' in data:
				self.title = data['tvshowtitle'].replace('&', 'and').replace('Special Victims Unit', 'SVU').replace('/', ' ').replace('$', 's')
				self.episode_title = data['title']
				self.hdlr = 'S%02dE%02d' % (int(data['season']), int(data['episode']))
				search_link = self.tvsearch
			else:
				self.title = data['title'].replace('&', 'and').replace('/', ' ').replace('$', 's')
				self.episode_title = None
				self.hdlr = self.year
				search_link = self.moviesearch
			self.undesirables = source_utils.get_undesirables()
			self.check_foreign_audio = source_utils.check_foreign_audio()

			query = '%s %s' % (re.sub(r'[^A-Za-z0-9\s\.-]+', '', self.title), self.hdlr)
			urls = []
			url = '%s%s' % (self.base_link, search_link.format(quote_plus(query)))
			urls.append(url)

			if url.endswith('field=size&sorder=desc'):
				urls.append(url.rsplit("/", 1)[0] + '/2/')
			else:
				urls.append(url + '/2/')
			threads = []
			append = threads.append
			for url in urls:
				append(workers.Thread(self.get_sources, url))
			[i.start() for i in threads]
			[i.join() for i in threads]
			return self.sources
		except:
			source_utils.scraper_error('KICKASS2')
			return self.sources

	def get_sources(self, url):
		# log_utils.log('url = %s' % url)
		try:
			results = client.request(url, timeout=7)
			if not results: return
			rows = client.parseDOM(results, 'tr', attrs={'id': 'torrent_latest_torrents'})
		except:
			source_utils.scraper_error('KICKASS2')
			return
		for row in rows:
			try:
				columns = re.findall(r'<td.*?>(.+?)</td>', row, re.DOTALL)

				url = unquote_plus(columns[0]).replace('&amp;', '&')
				url = re.search(r'(magnet:.+?)&tr=', url, re.I).group(1).replace(' ', '.')
				hash = re.search(r'btih:(.*?)&', url, re.I).group(1)
				name = source_utils.clean_name(unquote_plus(url.split('&dn=')[1])) # some links on kickass dbl encoded

				if not source_utils.check_title(self.title, self.aliases, name, self.hdlr, self.year): continue
				name_info = source_utils.info_from_name(name, self.title, self.year, self.hdlr, self.episode_title)
				if source_utils.remove_lang(name_info, self.check_foreign_audio): continue
				if self.undesirables and source_utils.remove_undesirables(name_info, self.undesirables): continue

				if not self.episode_title: #filter for eps returned in movie query (rare but movie and show exists for Run in 2020)
					ep_strings = [r'[.-]s\d{2}e\d{2}([.-]?)', r'[.-]s\d{2}([.-]?)', r'[.-]season[.-]?\d{1,2}[.-]?']
					name_lower = name.lower()
					if any(re.search(item, name_lower) for item in ep_strings): continue

				try:
					seeders = int(columns[3].replace(',', ''))
					if self.min_seeders > seeders: continue
				except: seeders = 0

				quality, info = source_utils.get_release_quality(name_info, url)
				try:
					dsize, isize = source_utils._size(columns[1].split('<')[0])
					info.insert(0, isize)
				except: dsize = 0
				info = ' | '.join(info)
				self.sources_append({'provider': 'kickass2', 'source': 'torrent', 'seeders': seeders, 'hash': hash, 'name': name, 'name_info': name_info,
												'quality': quality, 'language': 'en', 'url': url, 'info': info, 'direct': False, 'debridonly': True, 'size': dsize})
			except:
				source_utils.scraper_error('KICKASS2')

	def sources_packs(self, data, hostDict, search_series=False, total_seasons=None, bypass_filter=False):
		self.sources = []
		if not data: return self.sources
		self.sources_append = self.sources.append
		try:
			self.search_series = search_series
			self.total_seasons = total_seasons
			self.bypass_filter = bypass_filter

			self.title = data['tvshowtitle'].replace('&', 'and').replace('Special Victims Unit', 'SVU').replace('/', ' ').replace('$', 's')
			self.aliases = data['aliases']
			self.imdb = data['imdb']
			self.year = data['year']
			self.season_x = data['season']
			self.season_xx = self.season_x.zfill(2)
			self.undesirables = source_utils.get_undesirables()
			self.check_foreign_audio = source_utils.check_foreign_audio()

			query = re.sub(r'[^A-Za-z0-9\s\.-]+', '', self.title)
			if search_series:
				queries = [
						self.tvsearch.format(quote_plus(query + ' Season')),
						self.tvsearch.format(quote_plus(query + ' Complete'))]
			else:
				queries = [
							self.tvsearch.format(quote_plus(query + ' S%s' % self.season_xx)),
							self.tvsearch.format(quote_plus(query + ' Season %s' % self.season_x))]
			threads = []
			append = threads.append
			for url in queries:
				link = '%s%s' % (self.base_link, url)
				append(workers.Thread(self.get_sources_packs, link))
			[i.start() for i in threads]
			[i.join() for i in threads]
			return self.sources
		except:
			source_utils.scraper_error('KICKASS2')
			return self.sources

	def get_sources_packs(self, link):
		try:
			results = client.request(link, timeout=7)
			if not results: return
			rows = client.parseDOM(results, 'tr', attrs={'id': 'torrent_latest_torrents'})
		except:
			source_utils.scraper_error('KICKASS2')
			return
		for row in rows:
			try:
				columns = re.findall(r'<td.*?>(.+?)</td>', row, re.DOTALL)

				url = unquote_plus(columns[0]).replace('&amp;', '&')
				url = re.search(r'(magnet:.+?)&tr=', url, re.I).group(1).replace(' ', '.')
				hash = re.search(r'btih:(.*?)&', url, re.I).group(1)
				name = source_utils.clean_name(unquote_plus(url.split('&dn=')[1])) # some links on kickass dbl encoded

				episode_start, episode_end = 0, 0
				if not self.search_series:
					if not self.bypass_filter:
						valid, episode_start, episode_end = source_utils.filter_season_pack(self.title, self.aliases, self.year, self.season_x, name)
						if not valid: continue
					package = 'season'

				elif self.search_series:
					if not self.bypass_filter:
						valid, last_season = source_utils.filter_show_pack(self.title, self.aliases, self.imdb, self.year, self.season_x, name, self.total_seasons)
						if not valid: continue
					else: last_season = self.total_seasons
					package = 'show'

				name_info = source_utils.info_from_name(name, self.title, self.year, season=self.season_x, pack=package)
				if source_utils.remove_lang(name_info, self.check_foreign_audio): continue
				if self.undesirables and source_utils.remove_undesirables(name_info, self.undesirables): continue
				try:
					seeders = int(columns[3].replace(',', ''))
					if self.min_seeders > seeders: continue
				except: seeders = 0

				quality, info = source_utils.get_release_quality(name_info, url)
				try:
					dsize, isize = source_utils._size(columns[1].split('<')[0])
					info.insert(0, isize)
				except: dsize = 0
				info = ' | '.join(info)
				item = {'provider': 'kickass2', 'source': 'torrent', 'seeders': seeders, 'hash': hash, 'name': name, 'name_info': name_info, 'quality': quality,
							'language': 'en', 'url': url, 'info': info, 'direct': False, 'debridonly': True, 'size': dsize, 'package': package}
				if self.search_series: item.update({'last_season': last_season})
				elif episode_start: item.update({'episode_start': episode_start, 'episode_end': episode_end}) # for partial season packs
				self.sources_append(item)
			except:
				source_utils.scraper_error('KICKASS2')
