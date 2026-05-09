from windows import BaseDialog
from modules.kodi_utils import media_path
from modules.settings import get_art_provider
# from modules.kodi_utils import logger

poster_empty = media_path('box_office.png')
click_actions = {10: 'close', 11: 'play', 12: 'cancel'}
confirm_actions = {10: False, 11: True}

class NextEpisode(BaseDialog):
	def __init__(self, *args, **kwargs):
		BaseDialog.__init__(self, args)
		self.closed = False
		self.meta = kwargs.get('meta')
		self.function = kwargs.get('function', 'next_ep')# or 'confirm'
		if self.function == 'next_ep':
			self.actions = click_actions
			self.selected = 'close'
		else:
			self.actions = confirm_actions
			self.selected = False
		self.set_properties()

	def onInit(self):
		self.monitor()

	def run(self):
		self.doModal()
		self.clearProperties()
		return self.selected

	def onAction(self, action):
		if action in self.closing_actions:
			self.closed = True
			self.close()

	def onClick(self, controlID):
		self.closed = True
		self.selected = self.actions[controlID]
		self.close()

	def set_properties(self):
		self.poster_main, self.poster_backup, self.fanart_main, self.fanart_backup = get_art_provider()
		self.setProperty('tikiskins.title', self.meta['title'])
		self.setProperty('tikiskins.poster', self.original_poster())
		self.setProperty('tikiskins.fanart', self.original_fanart())
		self.setProperty('tikiskins.nextep_function', self.function)
		if self.function == 'next_ep':
			self.setProperty('tikiskins.next_episode', '[B]%s[/B][CR][B]%02dx%02d[/B] - %s' % (
				self.meta['title'], self.meta['season'], self.meta['episode'], self.meta['ep_name']
			))
		else: self.setProperty('tikiskins.title', '[B]%s[/B]' % self.meta['title'])

	def original_poster(self):
		self.poster = self.meta.get(self.poster_main) or self.meta.get(self.poster_backup) or poster_empty
		return self.poster

	def original_fanart(self):
		self.fanart = self.meta.get(self.fanart_main) or self.meta.get(self.fanart_backup) or ''
		return self.fanart

	def monitor(self):
		progress_bar = self.getControl(5000)
		if self.function == 'next_ep':
			total_time = self.player.getTotalTime()
			total_remaining = total_time - self.player.getTime()
			while self.player.isPlaying():
				try:
					if self.closed: break
					current_time = self.player.getTime()
					remaining = round(total_time - current_time)
					current_point = (remaining / float(total_remaining)) * 100
					progress_bar.setPercent(current_point)
					self.sleep(1000)
				except: pass
		else:
			for current_point in range(100, 0, -5):
				try:
					if self.closed: break
					if current_point == 0: break
					progress_bar.setPercent(current_point)
					self.sleep(1000)
				except: pass
		self.close()

