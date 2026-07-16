import requests
timeout = (3.05, 6.05)

class SegmentScraper:
	def __init__(self, imdb_id, season, episode):
		self.params = {'imdb_id': imdb_id, 'season': season, 'episode': episode}
		self.providers = (self.fetch_introdb, self.fetch_theintrodb)

	def fetch_introdb(self):
		result = {'intro': None, 'credits': None}
		try:
			response = requests.get('https://api.introdb.app/segments', params=self.params, timeout=timeout)
			rjson = response.json()
			intro = rjson.get('intro') or {}
			outro = rjson.get('outro') or {}
			intro_start, intro_end = intro.get('start_sec'), intro.get('end_sec')
			outro_start = outro.get('start_sec')
			if intro_start is not None and intro_end is not None:
				result['intro'] = (int(intro_start), int(intro_end))
			if outro_start is not None:
				result['credits'] = int(outro_start)
		except: pass
		return result

	def fetch_theintrodb(self):
		result = {'intro': None, 'credits': None}
		try:
			response = requests.get('https://api.theintrodb.org/v3/media', params=self.params, timeout=timeout)
			rjson = response.json()
			intro_list = rjson.get('intro') or []
			outro_list = rjson.get('credits') or []
			if intro_list:
				intro = next(iter(intro_list))
				intro_start, intro_end = intro.get('start_ms'), intro.get('end_ms')
				if intro_start is not None and intro_end is not None:
					result['intro'] = (int(intro_start / 1000), int(intro_end / 1000))
			if outro_list:
				outro = next(iter(outro_list))
				outro_start = outro.get('start_ms')
				if outro_start is not None:
					result['credits'] = int(outro_start / 1000)
		except: pass
		return result

	def run(self):
		final_intro, final_credits = None, None
		for fetch_api in self.providers:
			data = fetch_api()
			if final_intro is None and data.get('intro') is not None:
				final_intro = data['intro']
			if final_credits is None and data.get('credits') is not None:
				final_credits = data['credits']
			if final_intro is not None and final_credits is not None:
				break
		return final_intro, final_credits

