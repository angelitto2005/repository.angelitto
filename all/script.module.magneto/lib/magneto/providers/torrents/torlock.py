# created by Venom for Fenomscrapers
"""
	Fenomscrapers Project
"""

import re
from urllib.parse import quote_plus, unquote_plus
from magneto.modules import client
from magneto.modules import source_utils
from magneto.modules import workers
_LINKS = re.compile(r'<a\s*href\s*=\s*(/torrent/.+?)>', re.DOTALL | re.I)


class source:
	priority = 7
	pack_capable = False
	hasMovies = True
	hasEpisodes = True
	def __init__(self):
		self.language = ['en']
		self.base_link = "https://www.torlock2.com"
		self.search_link = '/all/torrents/%s.html?sort=size'
		self.min_seeders = 0

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
			else:
				self.title = data['title'].replace('&', 'and').replace('/', ' ').replace('$', 's')
				self.episode_title = None
				self.hdlr = self.year
			self.undesirables = source_utils.get_undesirables()
			self.check_foreign_audio = source_utils.check_foreign_audio()

			query = '%s %s' % (re.sub(r'[^A-Za-z0-9\s\.-]+', '', self.title), self.hdlr)
			url = '%s%s' % (self.base_link, self.search_link % quote_plus(query))
			# log_utils.log('url = %s' % url)

			results = client.request(url, timeout=5)
			if not results: return self.sources
			#links = _LINKS.findall(results)[:15] # limit because torlock is slow and 2 requests
			links = []
			rows = client.parseDOM(results, 'tr')
			for row in rows:
				columns = re.findall(r'<td.*?>(.+?)</td>', row, re.DOTALL)
				for column in columns:
					try:
						linkpart = re.search(r'href\s*=\s*["\']/(.+?)["\']>', column, re.I).group(1).split('/')
						linkpart1 = linkpart[1]
						linkpart2 = linkpart[2]
						link = '/torrent/'+linkpart1+'/'+linkpart2
					except:
						continue
					if link:
						links.append(link)
			threads = []
			append = threads.append
			for link in links:
				append(workers.Thread(self.get_sources, link))
			[i.start() for i in threads]
			[i.join() for i in threads]
			return self.sources
		except:
			source_utils.scraper_error('TORLOCK')
			return self.sources

	def get_sources(self, link):
		try:
			url = '%s%s' % (self.base_link, link)
			result = client.request(url, timeout=5)
			if not result or 'magnet:' not in result: return

			url = re.search(r'href\s*=\s*["\'](magnet:[^"\']+)["\']', result, re.I).group(1)
			url = unquote_plus(url).replace('&amp;', '&').split('&tr')[0].replace(' ', '.')
			hash = re.search(r'btih:(.*?)&', url, re.I).group(1)
			name = source_utils.clean_name(url.split('&dn=')[1])

			if not source_utils.check_title(self.title, self.aliases, name, self.hdlr, self.year): return
			name_info = source_utils.info_from_name(name, self.title, self.year, self.hdlr, self.episode_title)
			if source_utils.remove_lang(name_info, self.check_foreign_audio): return
			if self.undesirables and source_utils.remove_undesirables(name_info, self.undesirables): return

			if not self.episode_title: #filter for eps returned in movie query (rare but movie and show exists for Run in 2020)
				ep_strings = [r'[.-]s\d{2}e\d{2}([.-]?)', r'[.-]s\d{2}([.-]?)', r'[.-]season[.-]?\d{1,2}[.-]?']
				name_lower = name.lower()
				if any(re.search(item, name_lower) for item in ep_strings): return

			try:
				seeders = int(re.search(r'>SWARM.*?>\s*([0-9]+?)\s*<', result, re.I).group(1).replace(',', ''))
				if self.min_seeders > seeders: return
			except: seeders = 0

			quality, info = source_utils.get_release_quality(name_info, url)
			try:
				size = re.search(r'>\s*SIZE.*?>\s*(\d.*?[a-z]{2})', result, re.I).group(1)
				dsize, isize = source_utils._size(size)
				info.insert(0, isize)
			except: dsize = 0
			info = ' | '.join(info)

			self.sources_append({'provider': 'torlock', 'source': 'torrent', 'seeders': seeders, 'hash': hash, 'name': name, 'name_info': name_info,
											'quality': quality, 'language': 'en', 'url': url, 'info': info, 'direct': False, 'debridonly': True, 'size': dsize})
		except:
			source_utils.scraper_error('TORLOCK')
