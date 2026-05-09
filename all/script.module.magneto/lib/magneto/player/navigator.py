import sys
from . import kore
from .cinemeta import top_movies, top_series

build_url, make_listitem, add_item, add_items = kore.build_url, kore.make_listitem, kore.add_item, kore.add_items
set_category, set_content, end_directory = kore.set_category, kore.set_content, kore.end_directory
unaired_color = 'dodgerblue'

class Navigator:
	def __init__(self, params):
		self.handle = int(sys.argv[1])
		self.params = params

	def main(self):
		for i in (
		({'action': 'MagnetoSettings', 'name': 'Magneto Settings'}, kore.addon_icon),
		({'action': 'ShowChangelog', 'name': 'Change Log'}, 'DefaultPlaylist.png'),
		({'action': 'ShowReadme', 'name': 'README (AIOSteams)'}, 'DefaultIconInfo.png'),
		({'action': 'InstallJson', 'name': 'Install Playback Json (AIOSteams)'}, 'DefaultAddon.png'),
		({'action': 'Movies', 'name': 'Test Movies (AIOSteams)'}, 'DefaultMovies.png', True),
		({'action': 'Series', 'name': 'Test Series (AIOSteams)'}, 'DefaultTVShows.png', True)
		): add_item(self.handle, *self.build_item(*i))
		set_content(self.handle, '')
		end_directory(self.handle)

	def build_item(self, url_params, icon=None, isFolder=False):
		icon = icon or 'DefaultFolder.png'
		url = build_url(url_params)
		listitem = make_listitem()
		listitem.setLabel(f"{url_params['name']}")
		listitem.setArt({'icon': icon, 'poster': icon})
		return url, listitem, isFolder

class Directory:
	category, content = '', ''
	def run(self, params):
		self.params = params
		self.items = []
		handle = int(sys.argv[1])
		self.worker()
		if self.items: add_items(handle, self.items)
		set_category(handle, self.category)
		set_content(handle, self.content)
		end_directory(handle)

class Movies(Directory):
	content, category = 'movies', 'Movies'
	def worker(self):
		if not hasattr(self, 'items'): self.items = []
		for movie in top_movies():
			imdbnumber = movie.get('imdb_id', '')
			url = build_url({'action': 'MediaPlay', 'mediatype': 'movie', 'imdb_id': imdbnumber})
			try: li = movie.get_listitem() #; li.setProperty('IsPlayable','true')
			except Exception as e: kore.logger(imdbnumber, f"{e}")
			else: self.items.append((url, li, False))

class Series(Directory):
	content, category = 'tvshows', 'TV Shows'
	def worker(self):
		if not hasattr(self, 'items'): self.items = []
		for show in top_series():
			imdbnumber = show.get('imdb_id', '')
			url = build_url({'action': 'Episodes', 'imdb_id': imdbnumber})
			try: li = show.get_listitem()
			except Exception as e: kore.logger(imdbnumber, f"{e}")
			else: self.items.append((url, li, True))

class Episodes(Directory):
	content = 'episodes'
	def worker(self):
		from datetime import datetime
		from .cinemeta import series_meta
		if not hasattr(self, 'items'): self.items = []
		show = series_meta(self.params['imdb_id'])
		meta_get = show.get
		self.category = meta_get('title')
		imdbnumber = meta_get('imdb_id')
		poster, fanart, logo = meta_get('poster'), meta_get('fanart'), meta_get('clearlogo')
		art = {
			'poster': poster, 'fanart': fanart, 'icon': poster, 'clearlogo': logo,
			'tvshow.poster': poster, 'tvshow.clearlogo': logo
		}
		current_date = str(datetime.today().date())
		for ep in meta_get('episodes'):
			ep_get = ep.get
			ep_name, season, episode = ep_get('title'), ep_get('season'), ep_get('episode')
			try: aired = ep_get('premiered') and (current_date > ep['premiered'])
			except: aired = False
			label = f"{season:02d}x{episode:02d}. "
			if aired: label += f"{ep_name}"
			else: label += f"[COLOR {unaired_color}][I]{ep_name}[/I][/COLOR]"
			thumb = ep_get('thumb') or False
			url = build_url({
				'action': 'MediaPlay', 'mediatype': 'episode', 'imdb_id': imdbnumber,
				'season': season, 'episode': episode
			})
			try:
				li = show.get_listitem()
				li.toepisode(ep)
#				li.setProperty('IsPlayable','true')
				if thumb: li.setArt({**art, 'thumb': thumb})
				li.setLabel(label)
			except Exception as e: kore.logger(imdbnumber, f"{e}")
			else: self.items.append((url, li, False))
