from .kore import ListItem, xbmc_actor

class ListItem(ListItem):
	def toepisode(self, meta, ep_name=''):
		meta_get = meta.get
		info_tag = self.getVideoInfoTag(offscreen=True)
		info_tag.setMediaType('episode')
		info_tag.setSeason(meta_get('season'))
		info_tag.setEpisode(meta_get('episode'))
		info_tag.setTitle(ep_name or meta_get('title'))
		info_tag.setFirstAired(meta_get('premiered'))
		info_tag.setYear(int(meta_get('premiered')[:4] or 0))
		info_tag.setPlot(meta_get('plot'))

	@classmethod
	def from_moviemeta(self, meta):
		meta_get = meta.get
		imdbnumber, tmdbnumber = meta_get('imdb_id', ''), meta_get('tmdb_id', '')
		poster, fanart, logo = meta_get('poster'), meta_get('fanart'), meta_get('clearlogo')
		li = self(offscreen=True)
		li.setArt({'poster': poster, 'fanart': fanart, 'icon': poster, 'clearlogo': logo})
		li.setLabel(meta_get('title') or imdbnumber)
		info_tag = li.getVideoInfoTag(offscreen=True)
		info_tag.setCast([xbmc_actor(name=item) for item in meta_get('cast') or []])
		info_tag.setUniqueIDs({'imdb': imdbnumber, 'tmdb': str(tmdbnumber)})
		info_tag.setMediaType('movie')
		info_tag.setIMDBNumber(imdbnumber)
		info_tag.setTitle(meta_get('title'))
		info_tag.setPlot(meta_get('plot'))
		info_tag.setPremiered(meta_get('premiered'))
		info_tag.setYear(meta_get('year'))
		info_tag.setDuration(meta_get('duration'))
		info_tag.setRating(meta_get('rating')),
		info_tag.setGenres(meta_get('genre'))
		info_tag.setCountries(meta_get('country'))
		info_tag.setDirectors(meta_get('director'))
		info_tag.setWriters(meta_get('writer'))
		return li

	@classmethod
	def from_showmeta(self, meta):
		meta_get = meta.get
		imdbnumber, tmdbnumber = meta_get('imdb_id', ''), meta_get('tmdb_id', '')
		poster, fanart, logo = meta_get('poster'), meta_get('fanart'), meta_get('clearlogo')
		li = self(offscreen=True)
		li.setArt({
			'poster': poster, 'fanart': fanart, 'icon': poster, 'clearlogo': logo,
			'tvshow.poster': poster, 'tvshow.clearlogo': logo
		})
		li.setLabel(meta_get('title') or imdbnumber)
		info_tag = li.getVideoInfoTag(offscreen=True)
		info_tag.setCast([xbmc_actor(name=item) for item in meta_get('cast') or []])
		info_tag.setUniqueIDs({
			'imdb': imdbnumber, 'tmdb': str(tmdbnumber), 'tvdb': str(meta_get('tvdb_id', ''))
		})
		info_tag.setMediaType('tvshow')
		info_tag.setIMDBNumber(imdbnumber)
		info_tag.setTitle(meta_get('title'))
		info_tag.setTvShowTitle(meta_get('title'))
		info_tag.setTvShowStatus(meta_get('status'))
		info_tag.setPlot(meta_get('plot'))
		info_tag.setPremiered(meta_get('premiered'))
		info_tag.setYear(meta_get('year'))
		info_tag.setDuration(meta_get('duration'))
		info_tag.setRating(meta_get('rating')),
		info_tag.setGenres(meta_get('genre'))
		info_tag.setCountries(meta_get('country'))
		info_tag.setDirectors(meta_get('director'))
		info_tag.setWriters(meta_get('writer'))
		return li

class Movie(dict):
	def __init__(self, _dict=None):
		super().__init__()
		if _dict: self.parse(_dict)

	def get_listitem(self):
		return ListItem.from_moviemeta(self)

	def parse(self, meta):
		if not isinstance(meta, dict):
			raise TypeError(f"Expected argument type 'dict', got {type(meta)}")
		meta_get = meta.get
		poster = meta_get('poster', '').replace('small', 'large')
		fanart = meta_get('background', '').replace('medium', 'large')
		logo = meta_get('logo', '').replace('medium', 'large')
		self.update({
			'mediatype': 'movie',
			'imdb_id': meta_get('imdb_id', ''), 'tmdb_id': meta_get('moviedb_id', ''),
			'title': meta_get('name') or meta_get('imdb_id'),
			'premiered': (meta_get('released') or '')[:10], 'year': int(meta_get('year') or 0),
			'poster': poster, 'fanart': fanart, 'clearlogo': logo,
			'plot': meta_get('description') or '',
			'genre': meta_get('genres') or meta_get('genre') or [],
			'country': (meta_get('country') or '').split(', '),
			'cast': meta_get('cast') or [],
			'director': meta_get('director') or [],
			'writer': meta_get('writer') or [],
			'duration': int((meta_get('runtime') or '0').split(' ')[0]) * 60,
			'rating': float(meta_get('imdbRating') or 0)
		})

class Series(dict):
	def __init__(self, _dict=None):
		super().__init__()
		if _dict: self.parse(_dict)

	def get_listitem(self):
		return ListItem.from_showmeta(self)

	def parse(self, meta):
		if not isinstance(meta, dict):
			raise TypeError(f"Expected argument type 'dict', got {type(meta)}")
		meta_get = meta.get
		poster = meta_get('poster', '').replace('small', 'large')
		fanart = meta_get('background', '').replace('medium', 'large')
		logo = meta_get('logo', '').replace('medium', 'large')
		title = meta_get('name') or meta_get('imdb_id')
		premiered = (meta_get('released') or '')[:10]
		if 'releaseInfo' in meta: year = int(meta['releaseInfo'][:4] or 0)
		else: year = int(premiered[:4] or 0)
		self.update({
			'mediatype': 'tvshow', 'tvdb_id': meta_get('tvdb_id', ''),
			'imdb_id': meta_get('imdb_id', ''), 'tmdb_id': meta_get('moviedb_id', ''),
			'tvshowtitle': title, 'title': title, 'premiered': premiered, 'year': year,
			'poster': poster, 'fanart': fanart, 'clearlogo': logo,
			'plot': meta_get('description') or '',
			'genre': meta_get('genres') or meta_get('genre') or [],
			'country': (meta_get('country') or '').split(', '),
			'cast': meta_get('cast') or [],
			'director': meta_get('director') or [],
			'writer': meta_get('writer') or [],
			'status': meta_get('status') or '',
			'duration': int((meta_get('runtime') or '0').split(' ')[0]) * 60,
			'rating': float(meta_get('imdbRating') or 0),
		})
		try: episodes = [
			Episode(ep, title) for ep in (meta_get('videos') or [])
			if not ep['season'] == 0
		]
		except: episodes = []
		total_episodes = sum(True for i in episodes if i['season'])
		self.update({'total_episodes': total_episodes, 'episodes': episodes})

class Episode(dict):
	def __init__(self, _dict=None, show_title=''):
		super().__init__()
		if _dict: self.parse(_dict, show_title)

	def parse(self, ep_data, show_title):
		if not isinstance(ep_data, dict):
			raise TypeError(f"Expected argument type 'dict', got {type(ep_data)}")
		self.update({
			'tvshowtitle': show_title, 'season': ep_data['season'], 'episode': ep_data['episode'],
			'title': ep_data.get('title') or ep_data.get('name') or f"Episode {ep_data['episode']}",
			'premiered': (ep_data.get('firstAired') or ep_data.get('released') or '')[:10],
			'plot': ep_data.get('overview') or ep_data.get('description') or '',
			'thumb': ep_data.get('thumbnail') or ''
		})
