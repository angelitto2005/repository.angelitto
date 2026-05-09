"""
	Cocoscrapers Project
"""

import re
from urllib.parse import quote_plus, unquote_plus
from magneto.modules import client
from magneto.modules import source_utils
from magneto.modules import workers

class source:
	priority = 3
	pack_capable = True
	hasMovies = True
	hasEpisodes = False
	def __init__(self):
		self.language = ['en']
		self.base_link = 'https://rutor.info'
# 1st param = 
# 2nd param = Category
# 3rd param = 
# 4th param = sort by. Date Added: increasing=1, Date Added: decreasing=0, Distributing: increasing=3, Distributing: decreasing=2, 
# Rocking: increasing=5, Rocking: decreasing=4, Name: increasing=7, Name: decreasing=6, Size: increasing=9, Size: decreasing=8, Relevance: increasing=11, Relevance: decreasing=10
# Foreign Movie = 0/1/110/8
# Foreign TV = 0/4/110/8
		self.search_link = '/search/%s/%s'
		self.movie_params = '0/0/0/8'
		self.tvshow_params = '0/0/0/8'
		self.min_seeders = 0

	def sources(self, data, hostDict):
		sources = []
		if not data: return sources
		append = sources.append
		try:
			aliases = data['aliases']
			year = data['year']
			if 'tvshowtitle' in data:
				return sources
				# title = data['tvshowtitle'].replace('&', 'and').replace('Special Victims Unit', 'SVU').replace('/', ' ').replace('$', 's')
				# episode_title = data['title']
				# hdlr = 'S%02dE%02d' % (int(data['season']), int(data['episode']))
				# search_link = self.search_link % (self.tvshow_params, '%s')
			else:
				title = data['title'].replace('&', 'and').replace('/', ' ').replace('$', 's')
				episode_title = None
				hdlr = year
				search_link = self.search_link % (self.movie_params, '%s')
			query = '%s %s' % (re.sub(r'[^A-Za-z0-9\s\.-]+', '', title), hdlr)
			url = '%s%s' % (self.base_link, search_link % (quote_plus(query)))
			# log_utils.log('url = %s' % url)
			html = client.request(url, timeout=7)

			# if not html or '<tbody' not in html: return sources
			if not html or '<div id="index">' not in html: return sources

			# table = client.parseDOM(html, 'tbody')
			table = client.parseDOM(html, 'div', attrs={'id': 'index'})

			rows = client.parseDOM(table, 'tr')
			undesirables = source_utils.get_undesirables()
			check_foreign_audio = source_utils.check_foreign_audio()
		except:
			source_utils.scraper_error('RUTOR')
			return sources

		for row in rows:
			try:
				if 'magnet:' not in row: continue
				columns = re.findall(r'<td.*?>(.*?)</td>', row, re.DOTALL)

				url = re.search(r'href\s*=\s*["\'](magnet:.+?)["\']', columns[1], re.I).group(1)
				url = unquote_plus(url).replace('&amp;', '&').replace('&#x3D;', '=').split('&tr')[0]
				url = url.replace('&dn=rutor.info', '&dn=[rutor.info]')
				# url = unquote_plus(client.replaceHTMLCodes(link[0])).split('&tr')[0]
				# url = re.sub(r'(&tr=.+)&dn=', '&dn=', url).replace(' ', '.') # some links on bitsearch &tr= before &dn=
				hash = re.search(r'btih:(.*?)&', url, re.I).group(1)

				name = re.search(r'/torrent/.+?["\']>(.+?)<', columns[1], re.I).group(1)
				name = source_utils.clean_name(name).replace('2./.', '').replace('./.', '').replace('|.', '').replace('...', '.').replace('..', '.').replace(',.', '.').replace(':.', '.')
				url = '%s%s' % (url, name)

				if not source_utils.check_title(title, aliases, name, hdlr, year):
					continue
				name_info = source_utils.info_from_name(name, title, year, hdlr, episode_title)
				if source_utils.remove_lang(name_info, check_foreign_audio):
					continue
				if undesirables and source_utils.remove_undesirables(name_info, undesirables):
					continue

				if not episode_title: # filter for eps returned in movie query (rare but movie and show exists for Run in 2020)
					ep_strings = [r'[.-]s\d{2}e\d{2}([.-]?)', r'[.-]s\d{2}([.-]?)', r'[.-]season[.-]?\d{1,2}[.-]?']
					name_lower = name.lower()
					if any(re.search(item, name_lower) for item in ep_strings): continue

				try:
					seeders = client.parseDOM(columns[-1], 'span', attrs={'class': 'green'}) # some results have comments so seeders is always last col from end
					seeders = re.search(r'/>(.+)', seeders[0], re.I).group(1).replace('&nbsp;', ' ')
					if 'K' in seeders: seeders = float(seeders.rstrip('K')) * 1000
					seeders = int(seeders)
					if self.min_seeders > seeders: continue
				except:
					seeders = 0

				quality, info = source_utils.get_release_quality(name_info, url)
				try:
					size = columns[-2].replace('&nbsp;', ' ') # some results have comments so size is always 2nd col from end
					dsize, isize = source_utils._size(size)
					info.insert(0, isize)
				except: dsize = 0
				info = ' | '.join(info)

				append({'provider': 'rutor', 'source': 'torrent', 'seeders': seeders, 'hash': hash, 'name': name, 'name_info': name_info,
										'quality': quality, 'language': 'en', 'url': url, 'info': info, 'direct': False, 'debridonly': True, 'size': dsize})
			except:
				source_utils.scraper_error('RUTOR')
		return sources

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
						self.search_link % (self.tvshow_params, quote_plus(query + ' Season')),
						self.search_link % (self.tvshow_params, quote_plus(query + ' Complete'))]
			else:
				queries = [
						self.search_link % (self.tvshow_params, quote_plus(query + ' S%s' % self.season_xx)),
						self.search_link % (self.tvshow_params, quote_plus(query + ' Season %s' % self.season_x))]

			threads = []
			append = threads.append
			for url in queries:
				link = '%s%s' % (self.base_link, url)
				append(workers.Thread(self.get_sources_packs, link))
			[i.start() for i in threads]
			[i.join() for i in threads]
			return self.sources
		except:
			source_utils.scraper_error('RUTOR')
			return self.sources

	def get_sources_packs(self, link):
		try:
			results = client.request(link, timeout=7)
			# if not html or '<tbody' not in html: return sources
			if not results or '<div id="index">' not in results: return sources
			# table = client.parseDOM(html, 'tbody')
			table = client.parseDOM(results, 'div', attrs={'id': 'index'})
			rows = client.parseDOM(table, 'tr')
		except:
			source_utils.scraper_error('RUTOR')
		for row in rows:
			try:
				if 'magnet:' not in row: continue
				columns = re.findall(r'<td.*?>(.*?)</td>', row, re.DOTALL)

				url = re.search(r'href\s*=\s*["\'](magnet:.+?)["\']', columns[1], re.I).group(1)
				url = unquote_plus(url).replace('&amp;', '&').replace('&#x3D;', '=').split('&tr')[0]
				url = url.replace('&dn=rutor.info', '&dn=[rutor.info]')
				# url = unquote_plus(client.replaceHTMLCodes(link[0])).split('&tr')[0]
				# url = re.sub(r'(&tr=.+)&dn=', '&dn=', url).replace(' ', '.') # some links on bitsearch &tr= before &dn=
				hash = re.search(r'btih:(.*?)&', url, re.I).group(1)

				name = re.search(r'/torrent/.+?["\']>(.+?)<', columns[1], re.I).group(1)
				name = source_utils.clean_name(name).replace('2./.', '').replace('./.', '').replace('|.', '').replace('...', '.').replace('..', '.').replace(',.', '.').replace(':.', '.')
				url = '%s%s' % (url, name)

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
					seeders = client.parseDOM(columns[-1], 'span', attrs={'class': 'green'}) # some results have comments so seeders is always last col from end
					seeders = re.search(r'/>(.+)', seeders[0], re.I).group(1).replace('&nbsp;', ' ')
					if 'K' in seeders: seeders = float(seeders.rstrip('K')) * 1000
					seeders = int(seeders)
					if self.min_seeders > seeders: continue
				except: seeders = 0

				quality, info = source_utils.get_release_quality(name_info, url)
				try:
					size = columns[-2].replace('&nbsp;', ' ') # some results have comments so size is always 2nd col from end
					dsize, isize = source_utils._size(size)
					info.insert(0, isize)
				except: dsize = 0
				info = ' | '.join(info)

				item = {'provider': 'rutor', 'source': 'torrent', 'seeders': seeders, 'hash': hash, 'name': name, 'name_info': name_info, 'quality': quality,
							'language': 'en', 'url': url, 'info': info, 'direct': False, 'debridonly': True, 'size': dsize, 'package': package}
				if self.search_series: item.update({'last_season': last_season})
				elif episode_start: item.update({'episode_start': episode_start, 'episode_end': episode_end}) # for partial season packs
				self.sources_append(item)
			except:
				source_utils.scraper_error('RUTOR')
