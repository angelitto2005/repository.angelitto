# created by kodifitzwell for Fenomscrapers
"""
	Fenomscrapers Project
"""

import re, requests
from fenom import source_utils


class source:
	timeout = 7
	priority = 1
	pack_capable = False # packs parsed in sources function
	hasMovies = True
	hasEpisodes = True
	def __init__(self):
		self.language = ['en']
		self.base_link = "https://mediafusionfortheweebs.midnightignite.me"
		self.movieSearch_link = '/%s/stream/movie/%s.json'
		self.tvSearch_link = '/%s/stream/series/%s:%s:%s.json'
		self.min_seeders = 0

	def sources(self, data, hostDict):
		sources = []
		if not data: return sources
		sources_append = sources.append
		try:
			title = data['tvshowtitle'] if 'tvshowtitle' in data else data['title']
			title = title.replace('&', 'and').replace('Special Victims Unit', 'SVU').replace('/', ' ')
			aliases = data['aliases']
			episode_title = data['title'] if 'tvshowtitle' in data else None
			total_seasons = data['total_seasons'] if 'tvshowtitle' in data else None
			year = data['year']
			imdb = data['imdb']
			if 'tvshowtitle' in data:
				season = data['season']
				episode = data['episode']
				hdlr = 'S%02dE%02d' % (int(season), int(episode))
				url = '%s%s' % (self.base_link, self.tvSearch_link % (self._token(), imdb, season, episode))
			else:
				hdlr = year
				url = '%s%s' % (self.base_link, self.movieSearch_link % (self._token(), imdb))
			# log_utils.log('url = %s' % url)
			if 'timeout' in data: self.timeout = int(data['timeout'])
			results = requests.get(url, timeout=self.timeout)
			files = results.json()['streams']
			_INFO = re.compile(r'💾.*')
			undesirables = source_utils.get_undesirables()
			check_foreign_audio = source_utils.check_foreign_audio()
		except:
			source_utils.scraper_error('MEDIAFUSION')
			return sources

		for file in files:
			try:
				package, episode_start = None, 0
				hash = file['infoHash']
				file_title = file['description'].split('\n')
				file_info = [x for x in file_title if _INFO.search(x)][0]

				name = source_utils.clean_name(file['behaviorHints']['filename'])

				if not source_utils.check_title(title, aliases, name, hdlr, year):
					if total_seasons is None: continue
					valid, last_season = source_utils.filter_show_pack(title, aliases, imdb, year, season, name, total_seasons)
					if not valid:
						valid, episode_start, episode_end = source_utils.filter_season_pack(title, aliases, year, season, name)
						if not valid: continue
						else: package = 'season'
					else: package = 'show'
				name_info = source_utils.info_from_name(name, title, year, hdlr, episode_title)
				if source_utils.remove_lang(name_info, check_foreign_audio): continue
				if undesirables and source_utils.remove_undesirables(name_info, undesirables): continue

				url = 'magnet:?xt=urn:btih:%s&dn=%s' % (hash, name)

				try:
					seeders = int(re.search(r'👤\s*(\d+)', file_info).group(1))
					if self.min_seeders > seeders: continue
				except: seeders = 0

				quality, info = source_utils.get_release_quality(name_info, url)
				try:
					size = re.search(r'((?:\d+\,\d+\.\d+|\d+\.\d+|\d+\,\d+|\d+)\s*(?:GB|GiB|Gb|MB|MiB|Mb))', file_info).group(0)
					dsize, isize = source_utils._size(size)
					info.insert(0, isize)
				except: dsize = 0
				info = ' | '.join(info)

				item = {
					'source': 'torrent', 'language': 'en', 'direct': False, 'debridonly': True,
					'provider': 'mediafusion', 'hash': hash, 'url': url, 'name': name, 'name_info': name_info,
					'quality': quality, 'info': info, 'size': dsize, 'seeders': seeders
				}
				if package: item.update({'package': package, 'true_size': True})
				if package == 'show': item.update({'last_season': last_season})
				if episode_start: item.update({'episode_start': episode_start, 'episode_end': episode_end}) # for partial season packs
				sources_append(item)
			except:
				source_utils.scraper_error('MEDIAFUSION')
		return sources

	def _token(self):
		return (
			'D-BGDTpQROy1Roy9aa15SRYsSgbPEJbdWnJkeiVoGT6LmPJ65Irqe7C5rYgtRWeOZxH8SOO7NFpD'
			'Mh19hsqS4plk1R273gU3uGWg0Qxvyh-D8-ieWTC33P34NccWnZsz-Y_ZpJlBcvr8FItcbfuFttRk'
			'1Irj_-1JGotw-9savyyC2muo6zuLy68klyiV70zr65euA8VgLi7MlAdU5_LF1UHOy6dutbvYvfVI'
			'-7gt3CHhY7DP7IiLb5cfB-mNnmBdP2J3jwMG3x5ac-Rx0Ao-ltMcjZMZum8zVWg6VwkQdqxokEX2'
			'D1nSMPLWsnj-2UwFO6ov-sD1IeFg8G2loXRbcQk7x91YMNr_Rvj2-11_OwbZutjCOdVs2K52NCbu'
			'ENRjEfS8dn_8XZtBEaJL7ZEEkW7wT_XbzPQ-pWqPPAwh_1jN4xkzE0isa1K7tDGfiRWOtqeH3JED'
			'txyS9-849sVncm4i-TozXOpyVsqNHtxUyWChYZB3WXIymlNCmmer1halPECScs9TH1XywdX2m2SR'
			'9u7jra2SKkd6wDacHR639MQag'
		)

