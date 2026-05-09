# created by kodifitzwell for Fenomscrapers
"""
	Fenomscrapers Project
"""

import ctypes, random, time
import re, requests
from fenom import client, source_utils


class source:
	timeout = 7
	priority = 3
	pack_capable = False # packs parsed in sources function
	hasMovies = True
	hasEpisodes = True
	def __init__(self):
		self.language = ['en']
		self.base_link = "https://debridmediamanager.com"
		self.movieSearch_link = '/api/torrents/movie?imdbId=%s'
		self.tvSearch_link = '/api/torrents/tv?imdbId=%s&seasonNum=%s'
		self.min_seeders = 0

	def sources(self, data, hostDict):
		self.sources = []
		if not data: return self.sources
		self.sources_append = self.sources.append
		try:
			self.title = data['tvshowtitle'] if 'tvshowtitle' in data else data['title']
			self.title = self.title.replace('&', 'and').replace('Special Victims Unit', 'SVU').replace('/', ' ')
			self.aliases = data['aliases']
			self.episode_title = data['title'] if 'tvshowtitle' in data else None
			self.total_seasons = data['total_seasons'] if 'tvshowtitle' in data else None
			self.year = data['year']
			self.imdb = data['imdb']
			self.season = data['season'] if 'tvshowtitle' in data else None
			self.hdlr = 'S%02dE%02d' % (int(data['season']), int(data['episode'])) if 'tvshowtitle' in data else self.year
			self.season_x = data['season'] if 'tvshowtitle' in data else None
			self.season_xx = data['season'].zfill(2) if 'tvshowtitle' in data else None
			if 'timeout' in data: self.timeout = int(data['timeout'])
			self.undesirables = source_utils.get_undesirables()
			self.check_foreign_audio = source_utils.check_foreign_audio()

			threads = []
			append = threads.append
			for page in range(2):
				if self.season: url = '%s%s&page=%s' % (self.base_link, self.tvSearch_link % (self.imdb, self.season), page)
				else: url = '%s%s&page=%s' % (self.base_link, self.movieSearch_link % self.imdb, page)
				append(i := source_utils.Thread(self.get_sources, url))
				i.start()
			[i.join() for i in threads]
			return self.sources
		except:
			source_utils.scraper_error('DMM')
			return self.sources

	def get_sources(self, url):
		try:
			dmmProblemKey, solution = get_secret()
			headers = {'User-Agent': client.randomagent(), 'Accept-Encoding': 'gzip, deflate, br', 'Accept': '*/*'}
			params = {'dmmProblemKey': dmmProblemKey, 'solution': solution}
			results = requests.get(url, params=params, headers=headers, timeout=self.timeout)
			files = results.json()['results']
		except:
			source_utils.scraper_error('DMM')
			return

		for file in files:
			try:
				package, episode_start = None, 0
				hash = file['hash']
				name = source_utils.clean_name(file['title'])

				if not source_utils.check_title(self.title, self.aliases, name, self.hdlr, self.year):
					if self.total_seasons is None: continue
					valid, last_season = source_utils.filter_show_pack(self.title, self.aliases, self.imdb, self.year, self.season_x, name, self.total_seasons)
					if not valid:
						valid, episode_start, episode_end = source_utils.filter_season_pack(self.title, self.aliases, self.year, self.season_x, name)
						if not valid: continue
						else: package = 'season'
					else: package = 'show'
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

				item = {
					'source': 'torrent', 'language': 'en', 'direct': False, 'debridonly': True,
					'provider': 'dmm', 'hash': hash, 'url': url, 'name': name, 'name_info': name_info,
					'quality': quality, 'info': info, 'size': dsize, 'seeders': 0
				}
				if package: item['package'] = package
				if package == 'show': item.update({'last_season': last_season})
				if episode_start: item.update({'episode_start': episode_start, 'episode_end': episode_end}) # for partial season packs
				self.sources_append(item)
			except:
				source_utils.scraper_error('DMM')


def get_secret():
	def calc_value_alg(t, n, const):
		temp = t ^ n
		t = ctypes.c_long((temp * const)).value
		t4 = ctypes.c_long(t << 5).value
		t5 = ctypes.c_long((t & 0xFFFFFFFF) >> 27).value
		return t4 | t5

	def slice_hash(s, n):
		half = int(len(s) // 2)
		left_s, right_s = s[:half], s[half:]
		left_n, right_n = n[:half], n[half:]
		l = ''.join(ls + ln for ls, ln in zip(left_s, left_n))
		return l + right_n[::-1] + right_s[::-1]

	def generate_hash(e):
		t = ctypes.c_long(0xDEADBEEF ^ len(e)).value
		a = 1103547991 ^ len(e)
		for ch in e:
			n = ord(ch)
			t = calc_value_alg(t, n, 2654435761)
			a = calc_value_alg(a, n, 1597334677)
		t = ctypes.c_long(t + ctypes.c_long(a * 1566083941).value).value
		a = ctypes.c_long(a + ctypes.c_long(t * 2024237689).value).value
		return (ctypes.c_long(t ^ a).value & 0xFFFFFFFF)

	ran = random.randrange(10 ** 80)
	hex_str = f"{ran:064x}"[:8]
	timestamp = int(time.time())
	dmmProblemKey = f"{hex_str}-{timestamp}"

	s = generate_hash(dmmProblemKey)
	s = f"{s:x}"

	n = generate_hash("debridmediamanager.com%%fe7#td00rA3vHz%VmI-" + hex_str)
	n = f"{n:x}"

	solution = slice_hash(s, n)
	return dmmProblemKey, solution

