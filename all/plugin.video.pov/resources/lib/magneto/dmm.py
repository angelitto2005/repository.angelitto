# created by kodifitzwell for Fenomscrapers
"""
	Fenomscrapers Project
"""

import ctypes, random, time
from json import loads as jsloads
import queue
from fenom import client
from fenom import source_utils


class source:
	timeout = 7
	priority = 3
	pack_capable = True
	hasMovies = True
	hasEpisodes = True
	_queue = queue.SimpleQueue()
	def __init__(self):
		self.language = ['en']
		self.base_link = "https://debridmediamanager.com"
		self.movieSearch_link = '/api/torrents/movie?imdbId=%s'
		self.tvSearch_link = '/api/torrents/tv?imdbId=%s&seasonNum=%s'
		self.min_seeders = 0

	def sources(self, data, hostDict):
		sources = []
		if not data: return sources
		sources_append = sources.append
		try:
			title = data['tvshowtitle'] if 'tvshowtitle' in data else data['title']
			title = title.replace('&', 'and').replace('Special Victims Unit', 'SVU').replace('/', ' ')
			aliases = source_utils.aliases_to_array(data['aliases'])
			episode_title = data['title'] if 'tvshowtitle' in data else None
			year = data['year']
			imdb = data['imdb']
			if 'tvshowtitle' in data:
				season = data['season']
				episode = data['episode']
				hdlr = 'S%02dE%02d' % (int(season), int(episode))
				url = '%s%s' % (self.base_link, self.tvSearch_link % (imdb, season))
			else:
				hdlr = year
				url = '%s%s' % (self.base_link, self.movieSearch_link % imdb)
			# log_utils.log('url = %s' % url)
			if 'timeout' in data: self.timeout = int(data['timeout'])
			try:
				url += '&dmmProblemKey=%s&solution=%s' % get_secret()
				results = client.request(url, timeout=self.timeout)
				files = jsloads(results)['results']
			except:
				files = []
				raise
			finally:
				self._queue.put_nowait(files) # if seasons
				self._queue.put_nowait(files) # if shows
			undesirables = source_utils.get_undesirables()
			check_foreign_audio = source_utils.check_foreign_audio()
		except:
			source_utils.scraper_error('DMM')
			return sources

		for file in files:
			try:
				hash = file['hash']
				name = file['title']

				name = source_utils.clean_name(name)

				if not source_utils.check_title(title, aliases, name, hdlr, year): continue
				name_info = source_utils.info_from_name(name, title, year, hdlr, episode_title)
				if source_utils.remove_lang(name_info, check_foreign_audio): continue
				if undesirables and source_utils.remove_undesirables(name_info, undesirables): continue

				url = 'magnet:?xt=urn:btih:%s&dn=%s' % (hash, name)

				quality, info = source_utils.get_release_quality(name_info, url)
				try:
					size = float(file['fileSize']) * 1048576
					dsize, isize = source_utils.convert_size(size)
					info.insert(0, isize)
				except: dsize = 0
				info = ' | '.join(info)

				sources_append({
					'source': 'torrent', 'language': 'en', 'direct': False, 'debridonly': True,
					'provider': 'dmm', 'hash': hash, 'url': url, 'name': name, 'name_info': name_info,
					'quality': quality, 'info': info, 'size': dsize, 'seeders': 0
				})
			except:
				source_utils.scraper_error('DMM')
		return sources

	def sources_packs(self, data, hostDict, search_series=False, total_seasons=None, bypass_filter=False):
		sources = []
		if not data: return sources
		sources_append = sources.append
		try:
			title = data['tvshowtitle'].replace('&', 'and').replace('Special Victims Unit', 'SVU').replace('/', ' ')
			aliases = source_utils.aliases_to_array(data['aliases'])
			imdb = data['imdb']
			year = data['year']
			season = data['season']
			url = '%s%s' % (self.base_link, self.tvSearch_link % (imdb, season))
			if 'timeout' in data: self.timeout = int(data['timeout'])
			files = self._queue.get(timeout=self.timeout + 1)
			undesirables = source_utils.get_undesirables()
			check_foreign_audio = source_utils.check_foreign_audio()
		except:
			source_utils.scraper_error('DMM')
			return sources

		for file in files:
			try:
				hash = file['hash']
				name = file['title']

				episode_start, episode_end = 0, 0
				if not search_series:
					if not bypass_filter:
						valid, episode_start, episode_end = source_utils.filter_season_pack(title, aliases, year, season, name.replace('.(Archie.Bunker', ''))
						if not valid: continue
					package = 'season'

				elif search_series:
					if not bypass_filter:
						valid, last_season = source_utils.filter_show_pack(title, aliases, imdb, year, season, name.replace('.(Archie.Bunker', ''), total_seasons)
						if not valid: continue
					else: last_season = total_seasons
					package = 'show'

				name_info = source_utils.info_from_name(name, title, year, season=season, pack=package)
				if source_utils.remove_lang(name_info, check_foreign_audio): continue
				if undesirables and source_utils.remove_undesirables(name_info, undesirables): continue

				url = 'magnet:?xt=urn:btih:%s&dn=%s' % (hash, name)

				quality, info = source_utils.get_release_quality(name_info, url)
				try:
					size = float(file['fileSize']) * 1048576
					dsize, isize = source_utils.convert_size(size)
					info.insert(0, isize)
				except: dsize = 0
				info = ' | '.join(info)

				item = {
					'source': 'torrent', 'language': 'en', 'direct': False, 'debridonly': True,
					'provider': 'dmm', 'hash': hash, 'url': url, 'name': name, 'name_info': name_info,
					'quality': quality, 'info': info, 'size': dsize, 'seeders': 0, 'package': package
				}
				if search_series: item.update({'last_season': last_season})
				elif episode_start: item.update({'episode_start': episode_start, 'episode_end': episode_end}) # for partial season packs
				sources_append(item)
			except:
				source_utils.scraper_error('DMM')
		return sources


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

