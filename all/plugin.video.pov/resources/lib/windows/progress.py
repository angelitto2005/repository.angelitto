from windows import BaseDialog
from modules.kodi_utils import media_path
from modules.settings import get_art_provider
# from modules.kodi_utils import logger

fanart_empty = BaseDialog.fanart
poster_empty = media_path('box_office.png')

class ProgressMedia(BaseDialog):
	def __init__(self, *args, **kwargs):
		BaseDialog.__init__(self, args)
		self.is_canceled = False
		self.selected = None
		self.meta = kwargs['meta']
		self.text = kwargs.get('text', '')
		self.enable_buttons = kwargs.get('enable_buttons', False)
		self.true_button = kwargs.get('true_button', '')
		self.false_button = kwargs.get('false_button', '')
		self.focus_button = kwargs.get('focus_button', 10)
		self.percent = float(kwargs.get('percent', 0))
		self.make_items()
		self.set_properties()

	def onInit(self):
		if self.enable_buttons: self.allow_buttons()

	def run(self):
		self.doModal()
		self.clearProperties()
		return self.selected

	def iscanceled(self):
		if self.enable_buttons: return self.selected
		else: return self.is_canceled

	def onAction(self, action):
		if action in self.closing_actions:
			self.is_canceled = True
			self.close()

	def onClick(self, controlID):
		self.selected = controlID == 10
		self.close()

	def allow_buttons(self):
		self.setProperty('tikiskins.source_progress.buttons', 'true')
		self.setProperty('tikiskins.source_progress.true_button', self.true_button)
		self.setProperty('tikiskins.source_progress.false_button', self.false_button)
		self.update(self.text, self.percent)
		self.setFocusId(self.focus_button)

	def make_items(self):
		self.poster_main, self.poster_backup, self.fanart_main, self.fanart_backup = get_art_provider()
		self.title = self.meta['title']
		self.year = str(self.meta['year'])
		self.poster = self.meta.get(self.poster_main) or self.meta.get(self.poster_backup) or poster_empty
		self.fanart = self.meta.get(self.fanart_main) or self.meta.get(self.fanart_backup) or fanart_empty
		self.clearlogo = self.meta['clearlogo'] or ''

	def set_properties(self):
		self.setProperty('tikiskins.source_progress.title', self.title)
		self.setProperty('tikiskins.source_progress.year', self.year)
		self.setProperty('tikiskins.source_progress.poster', self.poster)
		self.setProperty('tikiskins.source_progress.fanart', self.fanart)
		self.setProperty('tikiskins.source_progress.clearlogo', self.clearlogo)

	def update(self, content='', percent=0):
		try:
			self.getControl(2000).setText(content)
			self.getControl(5000).setPercent(percent)
		except: pass

