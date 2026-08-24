import requests
from urllib.parse import urlencode, parse_qsl
from modules.kodi_utils import get_setting, show_text
from modules import source_utils
# from modules.kodi_utils import logger

internal_results, get_file_info = source_utils.internal_results, source_utils.get_file_info
clean_file_name, clean_title = source_utils.clean_file_name, source_utils.clean_title

class source:
	timeout = 30
	scrape_provider = 'aiostreams'
	def results(self, info):
		try:
			sources = []
			sources_append = sources.append
			if not all(self.auth): return internal_results(self.scrape_provider, sources)
			title, season, episode = info.get('title'), info.get('season'), info.get('episode')
			if 'timeout' in info: self.timeout = info['timeout'] - 1
			scrape_results = self.search(info['imdb_id'], season, episode)
			from modules.kodi_utils import logger
			if self.errors: logger(self.scrape_provider, f"{self.errors}")
			logger(self.scrape_provider, f"{title} : {self.elapsed}s, {len(scrape_results)}")
			if not scrape_results: return internal_results(self.scrape_provider, sources)
			for item in scrape_results:
				if 'p2p' in item['type']: continue
				item_get = item.get
				url = item_get('url')
				headers = item['requestHeaders'] if item['type'] == 'http' else None
				if headers: url = '|'.join((url, urlencode(headers)))
				nzb_url = item_get('nzbUrl') or ''
				pack = 'season' if item['parsedFile'].get('seasonPack') else 'false'
				addon = item_get('addon') or ''
				indexer = item_get('indexer') or ''
				service = item_get('service') or 'direct'
				hash = item_get('infoHash') or ''
				name = clean_file_name(item_get('folderName') or item_get('filename'))
				seeders = item_get('seeders') or 0
				size = round((item_get('size') or 0)/1073741824, 2)
				name_info = self._make_name_info(item['parsedFile'].get)
				quality, details = get_file_info(name_info=name_info)
				sources_append({
					'direct': True,
					'source': item_get('type'),
					'scrape_provider': self.scrape_provider,
					'hash': hash.lower(),
					'id': url,
					'url_dl': url,
					'nzb_dl': nzb_url,
					'name': name,
					'display_name': name,
					'name_info': name_info,
					'extraInfo': details,
					'quality': quality,
					'size': size,
					'size_label': f"{size:.2f} GB",
					'seeders': seeders,
					'package': pack,
					'library': bool(item_get('library')),
					'cached': bool(item_get('cached')),
					'debrid': service.lower(),
					'provider': addon.lower(),
					'tracker': indexer.lower()
				})
		except Exception as e:
			from traceback import format_exc
			from modules.kodi_utils import logger
			logger(f"POV {self.scrape_provider} Exception", f"{e}\n{format_exc()}")
		internal_results(self.scrape_provider, sources)
		return sources

	def search(self, imdb, season, episode):
		scrape_results = []
		if episode: params = {'type': 'series', 'id': '%s:%s:%s' % (imdb, season, episode)}
		else: params = {'type': 'movie', 'id': '%s' % imdb}
		try:
			base_url = self.resolve_aio_instance()
			search_link = '%s/api/v1/search' % base_url.strip().rstrip('/')
			response = requests.get(search_link, params=params, auth=self.auth, timeout=self.timeout)
			if not response.ok: response.raise_for_status()
			results = response.json()['data']
			self.elapsed = round(response.elapsed.total_seconds(), 3)
			self.errors = [': '.join(i.values()) for i in results['errors']]
			scrape_results.extend(results['results'])
		except requests.exceptions.RequestException as e:
			from modules.kodi_utils import logger
			logger(self.scrape_provider, f"{type(e)}: {e}")
		return scrape_results

	def __init__(self):
		self.elapsed = None
		self.errors = []
		self.auth = get_setting('aio.username'), get_setting('aio.password')

	def _make_name_info(self, data_get):
		quality = (data_get('quality') or '').replace(' ', '.')
		file_info = (
			data_get('resolution'),
			data_get('network'),
			quality,
			data_get('encode'),
			*data_get('visualTags'),
			*data_get('subtitles'),
			*data_get('audioTags'),
			*data_get('audioChannels'),
			*data_get('languages'),
		)
		return '.'.join(dict.fromkeys(i for i in file_info if i)).lower()

	def resolve_aio_instance(self):
		setting_id = (
			'aio.ku_url', 'aio.custom_url', 'aio.viren_url', 'aio.yeb_url', 'aio.midnight_url'
		)[int(get_setting('aio.instance', '0'))]
		return get_setting(setting_id)

def unrestrict_link(url):
	url, *headers = url.rsplit('|', 1)
	try: headers = dict(parse_qsl(*headers))
	except: headers = dict()
	try: # some servers do not accept HEAD requests, must use GET + stream
		with requests.get(url, headers=headers, stream=True, timeout=30) as response:
			response.raise_for_status() # 3xx passes, 4xx/5xx raises
		if headers: return '|'.join((response.url, urlencode(headers)))
		return response.url
	except requests.exceptions.RequestException as e:
		from modules.kodi_utils import logger
		logger('unrestrict_link error', f"{type(e)}: {e}")

def aio_help():
	return show_text('AIOStreams', text=(
"""
AIOStreams consolidates multiple sources and debrid services into a single,
highly customizable provider.  When enabled AIOStreams supersedes
Cloud/External Scrapers, no concurrency.  Results are displayed in the order
received, no local filtering/sorting.

There are four supported public instances:

https://aiostreams.stremio.ru
https://aiostreams.viren070.me (devs nightly instance)
https://aiostreams.fortheweak.cloud
https://aiostreamsfortheweebsstable.midnightignite.me

A custom url may be entered, but is not "supported" (YMMV).

Any result that contains the type 'p2p' are skipped.

Ensure Settings/Sources/Scraper Timeout is as long as longest AIOStreams timeout.

Create an account and copy/paste your UUID/password into the
Username/Password settings.  Be sure to select the correct provider,
UUID's are specific to each provider.

Reporting issues to Github:

+ disable all other addons, too much noise is created by other addons.
+ provide a kodi.log file from after the scrape.

"""
))

