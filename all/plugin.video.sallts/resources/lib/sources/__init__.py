import magneto
from magneto.aiostreams import source as AIOStreams
from indexers.metadata import movie_meta, tvshow_meta, season_episodes_meta
from indexers.trakt_api import id_lookup
from modules.player import SALTSPlayer
from modules import settings
from modules.utils import get_datetime
#from modules.kodi_utils import logger

main_line, get_setting = magneto.main_line, magneto.get_setting
sleep, notification = magneto.sleep, magneto.notification

class Sources(magneto.MagnetoPlayer):
	def internal_sources(self):
		try:
			return [('internal', AIOS, 'aiostreams')]
		except Exception as e:
			from modules.kodi_utils import logger
			logger('internal_sources', str(e))
		return []

	def _grab_meta(self):
		meta_user_info, current_date = settings.metadata_user_info(), get_datetime()
		if self.mediatype == 'episode':
			self.meta = tvshow_meta('tmdb_id', self.tmdb_id, meta_user_info, current_date)
			self.meta.update({'mediatype': 'episode', 'tvshow_plot': self.meta['plot']})
			try:
				episodes_data = season_episodes_meta(self.season, self.meta, meta_user_info)
				ep_data = next((i for i in episodes_data if i['episode'] == int(self.episode)))
				thumb = ep_data.get('thumb', None) or self.meta.get('fanart') or ''
				self.meta.update({
					'ep_name': ep_data['title'], 'ep_thumb': thumb,
					'season': ep_data['season'], 'episode': ep_data['episode'],
					'premiered': ep_data['premiered'], 'plot': ep_data['plot']
				})
			except: pass
		else: self.meta = movie_meta('tmdb_id', self.tmdb_id, meta_user_info, current_date)
		if self.imdb_id: return
		try:
			imdb_id = next((
				i['movie']['ids']['imdb'] if i['type'] == 'movie' else i['show']['ids']['imdb']
				for i in id_lookup(self.tmdb_id, 'tmdb')
			), None)
			if imdb_id: self.imdb_id = self.meta['imdb_id'] = imdb_id
		except: pass

	def play_file(self, results, source=None):
		if not source: source = results[0]
		src_idx = next((i for i, _ in enumerate(results, 1) if _ == source), 1)
		provider = (i for i in (source.get('service'), source['addon'] or source['scrape_provider']) if i)
		provider = ' | '.join(provider)
		provider_text = provider.upper()
		display_name = source['filename'].upper()
		try: size_label = f"{source['size'] / 1073741824:.2f} GB"
		except: size_label = 'N/A'
		extraInfo = source.get('quality'), source.get('encode'), *source['visualTags'], *source['subtitles']
		extraInfo = ' | '.join(i.upper() for i in extraInfo if i) or 'N/A'
		extra_info = '[B]%s[/B] | [B]%s[/B] | %s' %  (source.get('resolution', 'SD'), size_label, extraInfo)
		resolve_display = '[B]%02d.[/B] [B]%s[/B]' % (src_idx, provider_text)
		resolve_display = main_line % (resolve_display, extra_info, display_name)
		res = self.sources_sd, self.sources_720p, self.sources_1080p, self.sources_4k, self.sources_total
		self.progress_dialog.update_scraper(*res, resolve_display, 0)
		sleep(200) # needed to update window before curl url check pause
		self.url = self.resolve_sources(source) or notification('Invalid playback url')
		if not self.url: return self.play_cancelled()
		return SALTSPlayer().run(self.url, self.meta, self._kill_progress_dialog)

class AIOS(AIOStreams):
	def __init__(self):
		instance_id = int(get_setting('aiostreams_instance', '0'))
		base_url = get_setting('aio_url.%d' % instance_id)
		self.auth = get_setting('username.%d' % instance_id), get_setting('password.%d' % instance_id)
		self.search_link = '%s/api/v1/search' % base_url.strip().rstrip('/')

