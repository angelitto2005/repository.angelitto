import json
import requests
from .kore import logger, get_setting, set_property, int_window_prop

public_instance = (
	'https://aiostreams.stremio.ru',
	'https://',
	'https://aiostreams.viren070.me',
	'https://aiostreams.fortheweak.cloud',
	'https://aiostreamsfortheweebsstable.midnightignite.me'
)

def internal_results(provider, sources):
	set_property(int_window_prop % provider, json.dumps(sources))

class source:
	timeout = 30
	scrape_provider = 'aiostreams'
	def results(self, info):
		try:
			self.sources, self.errors = [], []
			sources_append = self.sources.append
			if not all(self.auth): return internal_results(self.scrape_provider, self.sources)
			self.mediatype, title = info.get('mediatype'), info.get('title', '')
			self.season, self.episode = info.get('season'), info.get('episode')
			if 'timeout' in info: self.timeout = info['timeout'] - 1
			self.scrape_results = self.search(info['imdb_id'])
			if not self.scrape_results: return internal_results(self.scrape_provider, self.sources)
			for item in self.scrape_results:
				if 'p2p' in item['type']: continue
				item.pop('sources', None)
				file = {'scrape_provider': self.scrape_provider, **item.pop('parsedFile', {})}
				try: file.update(item)
				except: pass
				else: sources_append(file)
		except Exception as e: logger(f"Magneto {self.scrape_provider} Exception", f"{e}")
		if self.errors: logger(self.scrape_provider, f"{self.errors}")
		logger(self.scrape_provider, f"{title} : {self.elapsed}s, {len(self.sources)}, {len(self.scrape_results)}")
		internal_results(self.scrape_provider, self.sources)
		return self.sources

	def search(self, imdb):
		if self.mediatype == 'movie': params = {'type': 'movie', 'id': '%s' % imdb}
		else: params = {'type': 'series', 'id': '%s:%s:%s' % (imdb, self.season, self.episode)}
		try:
			response = requests.get(self.search_link, params=params, auth=self.auth, timeout=self.timeout)
			if not response.ok: response.raise_for_status()
			results = response.json()['data']
			self.elapsed = round(response.elapsed.total_seconds(), 3)
			self.errors = [': '.join(i.values()) for i in results['errors']]
			return results['results']
		except requests.exceptions.RequestException as e:
			logger(self.scrape_provider, f"{e}\n{e.request.url}")

	def __init__(self):
		instance_id = int(get_setting('aiostreams_instance', '0'))
		if instance_id == 1: base_url = get_setting('aio.custom_url')
		else: base_url = public_instance[instance_id]
		self.auth = get_setting('aio.username'), get_setting('aio.password')
		self.search_link = '%s/api/v1/search' % base_url.strip().rstrip('/')
