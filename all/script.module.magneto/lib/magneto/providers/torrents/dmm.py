# created by kodifitzwell for Fenomscrapers
"""
	Fenomscrapers Project
"""

import ctypes, math, random, time
import requests, queue
from magneto.modules import source_utils
from magneto.modules import workers


class source:
	timeout = 7
	priority = 3
	pack_capable = True
	hasMovies = True
	hasEpisodes = True
	_queue = queue.SimpleQueue()
	def __init__(self):
		dmmProblemKey, solution = get_secret()
		self.params = {'dmmProblemKey': dmmProblemKey, 'solution': solution}
		self.language = ['en']
		self.base_link = "https://debridmediamanager.com"
		self.movieSearch_link = '/api/torrents/movie?imdbId=%s'
		self.tvSearch_link = '/api/torrents/tv?imdbId=%s&seasonNum=%s'
		self.min_seeders = 0

	def sources(self, data, hostDict):
		self.sources, self.files = [], []
		if not data: return self.sources
		self.sources_append = self.sources.append
		try:
			self.title = data['tvshowtitle'] if 'tvshowtitle' in data else data['title']
			self.title = self.title.replace('&', 'and').replace('Special Victims Unit', 'SVU').replace('/', ' ')
			self.aliases = data['aliases']
			self.episode_title = data['title'] if 'tvshowtitle' in data else None
			self.year = data['year']
			self.imdb = data['imdb']
			self.season = data['season'] if 'tvshowtitle' in data else None
			self.hdlr = 'S%02dE%02d' % (int(data['season']), int(data['episode'])) if 'tvshowtitle' in data else self.year
			self.undesirables = source_utils.get_undesirables()
			self.check_foreign_audio = source_utils.check_foreign_audio()

			threads = []
			append = threads.append
			for page in range(2):
				if self.season: url = '%s%s&page=%s' % (self.base_link, self.tvSearch_link % (self.imdb, self.season), page)
				else: url = '%s%s&page=%s' % (self.base_link, self.movieSearch_link % self.imdb, page)
				append(i := workers.Thread(self.get_sources, url))
				i.start()
			[i.join() for i in threads]
			self._queue.put_nowait(self.files)
			self._queue.put_nowait(self.files)
			return self.sources
		except:
			source_utils.scraper_error('DMM')
			return self.sources

	def get_sources(self, url):
		try:
			results = requests.get(url, params=self.params, timeout=self.timeout)
			files = results.json()['results']
			self.files += files
		except:
			source_utils.scraper_error('DMM')
			return

		for file in files:
			try:
				hash = file['hash']
				name = source_utils.clean_name(file['title'])

				if not source_utils.check_title(self.title, self.aliases, name, self.hdlr, self.year): continue
				name_info = source_utils.info_from_name(name, self.title, self.year, self.hdlr, self.episode_title)
				if source_utils.remove_lang(name_info, self.check_foreign_audio): continue
				if self.undesirables and source_utils.remove_undesirables(name_info, self.undesirables): continue

				url = 'magnet:?xt=urn:btih:%s&dn=%s' % (hash, name)

				quality, info = source_utils.get_release_quality(name_info, url)
				try:
					size = f"{float(file['fileSize']) / 1024:.2f} GB"
					dsize, isize = source_utils._size(size)
					info.insert(0, isize)
				except: dsize = 0
				info = ' | '.join(info)

				self.sources_append({
					'source': 'torrent', 'language': 'en', 'direct': False, 'debridonly': True,
					'provider': 'dmm', 'hash': hash, 'url': url, 'name': name, 'name_info': name_info,
					'quality': quality, 'info': info, 'size': dsize, 'seeders': 0
				})
			except:
				source_utils.scraper_error('DMM')

	def sources_packs(self, data, hostDict, search_series=False, total_seasons=None, bypass_filter=False):
		self.sources = []
		if not data: return self.sources
		self.sources_append = self.sources.append
		try:
			self.search_series = search_series
			self.total_seasons = total_seasons
			self.bypass_filter = bypass_filter

			self.title = data['tvshowtitle'].replace('&', 'and').replace('Special Victims Unit', 'SVU').replace('/', ' ')
			self.aliases = data['aliases']
			self.imdb = data['imdb']
			self.year = data['year']
			self.season_x = data['season']
			self.season_xx = self.season_x.zfill(2)
			self.undesirables = source_utils.get_undesirables()
			self.check_foreign_audio = source_utils.check_foreign_audio()

			self.get_sources_packs(None)
			return self.sources
		except:
			source_utils.scraper_error('DMM')
			return self.sources

	def get_sources_packs(self, link):
		try:
			results = self._queue.get(timeout=self.timeout + 1)
			if not results: return
			files = results
		except:
			source_utils.scraper_error('DMM')
			return

		for file in files:
			try:
				hash = file['hash']
				name = source_utils.clean_name(file['title'])

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

				url = 'magnet:?xt=urn:btih:%s&dn=%s' % (hash, name)
				quality, info = source_utils.get_release_quality(name_info, url)
				try:
					size = f"{float(file['fileSize']) / 1024:.2f} GB"
					dsize, isize = source_utils._size(size)
					info.insert(0, isize)
				except: dsize = 0
				info = ' | '.join(info)

				item = {
					'source': 'torrent', 'language': 'en', 'direct': False, 'debridonly': True,
					'provider': 'dmm', 'hash': hash, 'url': url, 'name': name, 'name_info': name_info,
					'quality': quality, 'info': info, 'size': dsize, 'seeders': 0, 'package': package
				}
				if self.search_series: item.update({'last_season': last_season})
				elif episode_start: item.update({'episode_start': episode_start, 'episode_end': episode_end}) # for partial season packs
				self.sources_append(item)
			except:
				source_utils.scraper_error('DMM')


def get_secret():

	def calc_value_alg(t, n, const):
		temp = t ^ n
		t = ctypes.c_long((temp * const)).value
		t4 = ctypes.c_long(t << 5).value
		x32 = t & 0xFFFFFFFF  # convert to 32-bit unsigned value
		t5 = ctypes.c_long(x32 >> 27).value
		t6 = t4 | t5

		return t6

	def slice(e, t):
		a = math.floor(len(e) / 2)
		s = e[0:a]
		n = e[a:]
		i = t[0:a]
		o = t[a:]

		l = ""
		for e in range(0, a):
			l += s[e] + i[e]

		temp = l + (o[::-1] + n[::-1])

		return temp

	def generateHash(e):
		t = int(3735928559) ^ int(len(e))
		t = ctypes.c_long(t).value
		a = 1103547991 ^ len(e)

		for s in range(len(e)):
			n = ord(e[s])
			t = calc_value_alg(t, n, 2654435761)
			# a=(a ^ n*1597334677) << 5 | a >> 27
			a = calc_value_alg(a, n, 1597334677)

		t_o = t
		t = ctypes.c_long(t + ctypes.c_long(a * 1566083941).value | 0).value
		a = ctypes.c_long(a + ctypes.c_long(t * 2024237689).value | 0).value

		return (ctypes.c_long(t ^ a).value & 0xFFFFFFFF) >> 0

	ran = random.randrange(10**80)
	myhex = "%064x" % ran

	# limit string to 64 characters
	e = myhex[:8]
	t = int(time.time())
	a = str(e) + '-' + str(t)

	s = generateHash(a)
	s = hex(s).replace('0x', '')

	n = generateHash("debridmediamanager.com%%fe7#td00rA3vHz%VmI-" + e)
	n = hex(n).replace('0x', '')

	i = slice(s, n)
	dmmProblemKey = a
	solution = i
	return dmmProblemKey, solution
