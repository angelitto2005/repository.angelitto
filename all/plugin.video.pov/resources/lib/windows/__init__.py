from modules import kodi_utils
from modules.utils import manual_function_import
# from modules.kodi_utils import logger

location = kodi_utils.skin_location()

def open_window(import_info, skin_xml, **kwargs):
	'''
	import_info: tuple with ('module', 'function')
	'''
	try:
		xml_window = create_window(import_info, skin_xml, **kwargs)
		choice = xml_window.run()
		del xml_window
		return choice
	except: pass

def create_window(import_info, skin_xml, **kwargs):
	'''
	import_info: tuple with ('module', 'function')
	'''
	try:
		function = manual_function_import(*import_info)
		xml_window = function(skin_xml, location, **kwargs)
		return xml_window
	except Exception as e:
		kodi_utils.logger('error in open_window', str(e))
		return kodi_utils.notification(32574)

def videoplayer(url, close_action=None, callback=None):
	def onAVStarted(self):
		self.playback_event = True
	Player = type('Player', (kodi_utils.xbmc_player,), {'onAVStarted': onAVStarted})
	player = Player()
	player.playback_event = False
	player.play(url)
	for i in range(50):
		kodi_utils.sleep(200)
		if player.playback_event: break
	if callable(close_action): close_action()
	while player.isPlayingVideo(): kodi_utils.sleep(200)
	if player.playback_event and callable(callback): callback()

class BaseDialog(kodi_utils.window_xml_dialog):
	fanart = kodi_utils.get_addoninfo('fanart')
	icon = kodi_utils.get_addoninfo('icon')
	def __init__(self, *args):
		kodi_utils.window_xml_dialog.__init__(self, args)
		self.closing_actions = kodi_utils.window_xml_closing_actions
		self.selection_actions = kodi_utils.window_xml_selection_actions
		self.context_actions = kodi_utils.window_xml_context_actions
		self.info_actions = kodi_utils.window_xml_info_action
		self.left_actions = kodi_utils.window_xml_left_action
		self.right_actions = kodi_utils.window_xml_right_action
		self.up_actions = kodi_utils.window_xml_up_action
		self.down_actions = kodi_utils.window_xml_down_action
		self.player = kodi_utils.player
		self.setProperty('tikiskins.pov.icon', self.icon)

	def make_listitem(self):
		return kodi_utils.make_listitem()

	def build_url(self, params):
		return kodi_utils.build_url(params)

	def execute_code(self, command):
		return kodi_utils.execute_builtin(command)

	def get_position(self, window_id):
		return self.getControl(window_id).getSelectedPosition()

	def get_listitem(self, window_id):
		return self.getControl(window_id).getSelectedItem()

	def make_contextmenu_item(self, label, action, params):
		cm_item = self.make_listitem()
		cm_item.setProperty('tikiskins.context.label', label)
		cm_item.setProperty('tikiskins.context.action', action % self.build_url(params))
		return cm_item

	def get_infolabel(self, label):
		return kodi_utils.get_infolabel(label)

	def open_window(self, import_info, skin_xml, **kwargs):
		return open_window(import_info, skin_xml, **kwargs)

	def sleep(self, time):
		kodi_utils.sleep(time)

