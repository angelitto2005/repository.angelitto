import json
from threading import Thread
from caches import watched_cache as ws
from windows import open_window
from indexers.segments import SegmentScraper
from indexers.metadata import art_infodict, movie_show_infodict, episode_infodict, info_tagger
from modules import kodi_utils, settings
from modules.utils import sec2time, make_title_slug
# from modules.kodi_utils import logger

KODI_VERSION, make_cast_list = kodi_utils.get_kodi_version(), kodi_utils.make_cast_list
ls, get_setting = kodi_utils.local_string, kodi_utils.get_setting
get_art_provider, meta_user_info = settings.get_art_provider, settings.metadata_user_info
fanart_empty = kodi_utils.get_addoninfo('fanart')
poster_empty = kodi_utils.media_path('box_office.png')

class POVPlayer(kodi_utils.xbmc_player):
	def __init__(self):
		kodi_utils.xbmc_player.__init__(self)
		self.set_resume, self.set_watched = 5, 90
		self.playback_event, self.progress_media = None, None
		self.media_marked, self.nextep_info_gathered = False, False
		self.subs_searched, self.stingers_checked = False, False
		self.nextep_started, self.play_random_continual = False, False
		self.autoplay_next_episode = False
		self.autoplay_nextep = settings.autoplay_next_episode()
		self.autoscrape_next_episode = False
		self.autoscrape_nextep = settings.autoscrape_next_episode()
		self.art_provider = (*get_art_provider(), poster_empty, fanart_empty)
		self.stinger_enabled = get_setting('stingers.enable') == 'true'
		self.stinger_check = int(get_setting('stingers.threshold', '30'))
		self.skip_intro_enabled = get_setting('skip_intro.enable') == 'true'
		self.volume_check = get_setting('volumecheck.enabled', 'false') == 'true'

	def onAVStarted(self):
		self.playback_event = True

	def onPlayBackStarted(self):
		try: kodi_utils.hide_busy_dialog()
		except: pass

	def onPlayBackStopped(self):
		self.playback_event = 'stop'

	def run(self, url=None, meta=None, progress_media=None):
		if not url: return
		try:
			self.meta = meta or {}
			self.meta_get = self.meta.get
			self.tmdb_id, self.imdb_id = self.meta_get('tmdb_id'), self.meta_get('imdb_id')
			self.title, self.year = self.meta_get('title'), self.meta_get('year')
			self.mediatype, self.tvdb_id = self.meta_get('mediatype'), self.meta_get('tvdb_id')
			self.season, self.episode = self.meta_get('season', ''), self.meta_get('episode', '')
			if any(i in self.meta for i in ('random', 'random_continual')): bookmark = 0
			else: bookmark = self.bookmarkPOV()
			if bookmark == 'cancel': return
			self.meta.update({'url': url, 'bookmark': bookmark})
			listitem = self.make_listitem()
			listitem.setContentLookup(False)
			listitem.setLabel(self.title)
			listitem.setArt(art_infodict(self.meta, self.art_provider, meta_user_info()))
			listitem.setPath(url)
			listitem.setProperty('StartPercent', str(bookmark))

			self.playback_event = False
			self.play(url, listitem)
			while not self.playback_event: kodi_utils.sleep(100)
			if callable(progress_media): progress_media()
			kodi_utils.close_all_dialog()
			self.exec_task('trakt_ids')
			if self.mediatype == 'episode':
				self.play_random_continual = 'random_continual' in self.meta
				if not self.play_random_continual and self.autoplay_nextep:
					self.autoplay_next_episode = 'random' not in self.meta
				if not self.play_random_continual and self.autoscrape_nextep:
					self.autoscrape_next_episode = 'random' not in self.meta
				if not self.play_random_continual and self.autoplay_nextep and self.autoscrape_nextep:
					self.autoscrape_next_episode = False
				self.exec_task('episode_handler')
			if self.volume_check: kodi_utils.volume_checker()
			kodi_utils.sleep(1000)
			while self.isPlayingVideo(): self.check_playback_events()
			if not self.media_marked: self.media_watched_marker()
			ws.clear_local_bookmarks()
			kodi_utils.clear_property('script.trakt.ids')
		except: pass

	def check_playback_events(self):
		try:
			kodi_utils.sleep(1000)
			self.total_time, self.curr_time = self.getTotalTime(), self.getTime()
			self.current_point = round(float(self.curr_time/self.total_time * 100), 1)
			self.remaining_time = round(self.total_time - self.curr_time)
			if not self.subs_searched:
				self.exec_task('subtitles')
			if not self.stingers_checked and self.mediatype == 'movie':
				if self.stinger_enabled and self.curr_time > self.stinger_check:
					self.exec_task('stingers')
			if not self.media_marked:
				if self.current_point >= self.set_watched:
					self.media_watched_marker()
			if self.nextep_info_gathered and not self.nextep_started:
				if self.play_random_continual and self.remaining_time <= self.start_prep:
					self.exec_task('random_continual')
				elif self.autoplay_next_episode and self.remaining_time <= self.start_prep:
					if self.autoplay_nextep: self.exec_task('next_ep')
				elif self.autoscrape_next_episode and self.remaining_time <= self.autoscrape_next_window_time:
					if self.autoscrape_nextep: self.exec_task('scrape_next_ep')
		except: pass

	def make_listitem(self):
		listitem = kodi_utils.make_listitem()
		try:
			if self.mediatype == 'movie':
				info = movie_show_infodict(self.meta)
				uids = {'imdb': self.imdb_id, 'tmdb': str(self.tmdb_id)}
			else:
				info = {**episode_infodict(self.meta), 'title': self.meta_get('ep_name')}
				uids = {'imdb': self.imdb_id, 'tmdb': str(self.tmdb_id), 'tvdb': str(self.tvdb_id)}
			if KODI_VERSION < 20:
				listitem.setInfo('video', info)
				listitem.setUniqueIDs(uids)
				listitem.setCast(self.meta_get('cast', []))
			else:
				infotag = info_tagger(listitem, info)
				infotag.setUniqueIDs(uids)
				infotag.setCast(make_cast_list(self.meta_get('cast', [])))
		except: pass
		return listitem

	def episode_handler(self):
		for _ in range(150):
			total_time = False
			try: total_time = self.getTotalTime() > 0
			except: pass
			if total_time: break
			kodi_utils.sleep(200)
		else: return
		self.intro, self.credits = SegmentScraper(self.imdb_id, self.season, self.episode).run()
		if self.intro is not None and self.skip_intro_enabled:
			self.exec_task('skip_intro')
		if self.play_random_continual or self.autoplay_next_episode or self.autoscrape_next_episode:
			self.info_next_ep()

	def info_next_ep(self):
		try:
			self.nextep_settings = settings.autoplay_next_settings()
			if self.credits is not None and self.credits <= self.getTotalTime():
				window_time = round(self.getTotalTime() - self.credits + 5)
				self.nextep_settings['window_time'] = window_time
				self.nextep_settings['autoscrape_next_window_time'] = window_time
			elif not self.nextep_settings['run_popup']:
				window_time = round(0.02 * self.getTotalTime())
				self.nextep_settings['window_time'] = window_time
			elif self.nextep_settings['timer_method'] == 'percentage':
				percentage = self.nextep_settings['window_percentage']
				window_time = round((percentage/100) * self.getTotalTime())
				self.nextep_settings['window_time'] = window_time
			else:
				window_time = self.nextep_settings['window_time']
			threshold_check = window_time + 21
			self.start_prep = self.nextep_settings['scraper_time'] + threshold_check
			self.nextep_settings.update({'threshold_check': threshold_check, 'start_prep': self.start_prep})
			self.autoscrape_next_window_time = self.nextep_settings['autoscrape_next_window_time']
		except: pass
		finally: self.nextep_info_gathered = True

	def media_watched_marker(self):
		self.media_marked = True
		try:
			if self.current_point >= self.set_watched:
				if self.mediatype == 'movie': watched_function, watched_params = ws.mark_as_watched_unwatched_movie, {
					'mode': 'mark_as_watched_unwatched_movie', 'action': 'mark_as_watched', 'refresh': 'false', 'from_playback': 'true',
					'tmdb_id': self.tmdb_id, 'title': self.title, 'year': self.year
				}
				else: watched_function, watched_params = ws.mark_as_watched_unwatched_episode, {
					'mode': 'mark_as_watched_unwatched_episode', 'action': 'mark_as_watched', 'refresh': 'false', 'from_playback': 'true',
					'tmdb_id': self.tmdb_id, 'title': self.title, 'year': self.year, 'tvdb_id': self.tvdb_id, 'season': self.season, 'episode': self.episode
				}
				self.exec_task('media_watched', watched_function, watched_params)
			else:
				kodi_utils.clear_property('pov_total_autoplays')
				if not self.current_point >= self.set_resume: return
				ws.set_bookmark(self.mediatype, self.tmdb_id, self.curr_time, self.total_time, self.title, self.season, self.episode)
		except: pass

	def bookmarkPOV(self):
		bookmark = 0
		watched_indicators = settings.watched_indicators()
		try: resume_point, curr_time, resume_id = ws.detect_bookmark(ws.get_bookmarks(watched_indicators, self.mediatype), self.tmdb_id, self.season, self.episode)
		except: resume_point, curr_time = 0, 0
		resume_check = float(resume_point)
		if resume_check > 0:
			percent = str(resume_point)
			raw_time = float(curr_time)
			if watched_indicators in (1, 2): resume_point = '%s%%' % str(percent)
			else: resume_point = sec2time(raw_time, n_msec=0)
			bookmark = self.getResumeStatus(resume_point, percent, bookmark)
			if bookmark == 0: ws.erase_bookmark(self.mediatype, self.tmdb_id, self.season, self.episode)
		return bookmark

	def getResumeStatus(self, resume_point, percent, bookmark):
		if settings.auto_resume(self.mediatype): return percent
		choice = open_window(
			('windows.progress', 'ProgressMedia'),
			'progress_media.xml',
			meta=self.meta,
			text=ls(32790) % resume_point,
			enable_buttons=True,
			true_button=ls(32832),
			false_button=ls(32833),
			focus_button=10,
			percent=percent
		)
		return percent if choice is True else bookmark if choice is False else 'cancel'

	def getStingers(self, tmdb_id, poster):
		if not tmdb_id: return
		from indexers import tmdb_api
		stingers = {'duringcreditsstinger': 'During Credit Scene', 'aftercreditsstinger': 'After Credit Scene'}
		keywords = tmdb_api.movie_keywords(tmdb_id) or []
		keywords = [str(i['name']) for i in keywords]
		if all((i in keywords for i in stingers.keys())): stinger = 'Dual Credit Scenes'
		else: stinger = next((v for k, v in stingers.items() if k in keywords), None)
		return kodi_utils.notification(stinger, time=6000, icon=poster) if stinger else ''

	def exec_task(self, task_name, *args):
		try:
			if task_name == 'media_watched':
				if args: Thread(target=args[0], args=(args[1],)).start()
			elif task_name == 'episode_handler':
				Thread(target=self.episode_handler).start()
			elif task_name == 'skip_intro':
				from modules.episode_tools import execute_skip_intro
				Thread(target=execute_skip_intro, args=(self, self.meta)).start()
			elif task_name == 'scrape_next_ep':
				self.nextep_started = True
				from modules.episode_tools import execute_scrape_nextep
				Thread(target=execute_scrape_nextep, args=(self, self.meta)).start()
			elif task_name in ('next_ep', 'random_continual'):
				self.nextep_started = True
				from modules.episode_tools import execute_nextep
				Thread(target=execute_nextep, args=(self, self.meta, self.nextep_settings)).start()
			elif task_name == 'subtitles':
				self.subs_searched = True
				poster = self.meta.get('poster') or poster_empty
				season = self.season if self.mediatype == 'episode' else None
				episode = self.episode if self.mediatype == 'episode' else None
				from indexers.subtitles import Subtitles
				Thread(target=Subtitles().run, args=(self.title, self.imdb_id, season, episode, poster)).start()
			elif task_name == 'stingers':
				self.stingers_checked = True
				poster = self.meta.get('poster') or poster_empty
				tmdb_id = self.tmdb_id if self.mediatype == 'movie' and self.stinger_enabled else None
				Thread(target=self.getStingers, args=(tmdb_id, poster)).start()
			elif task_name == 'trakt_ids':
				trakt_ids = {'tmdb': self.tmdb_id, 'imdb': self.imdb_id, 'slug': make_title_slug(self.title)}
				if self.mediatype == 'episode': trakt_ids['tvdb'] = self.tvdb_id
				kodi_utils.clear_property('script.trakt.ids')
				kodi_utils.set_property('script.trakt.ids', json.dumps(trakt_ids))
		except: pass

