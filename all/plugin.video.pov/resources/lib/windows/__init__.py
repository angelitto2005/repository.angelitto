import xbmcgui
from modules import kodi_utils
from modules.utils import manual_function_import
# from modules.kodi_utils import logger

window_xml_info_action = xbmcgui.ACTION_SHOW_INFO
window_xml_closing_actions = (xbmcgui.ACTION_STOP, xbmcgui.ACTION_PARENT_DIR, xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK)
window_xml_selection_actions = (xbmcgui.ACTION_SELECT_ITEM, xbmcgui.ACTION_MOUSE_START)
window_xml_context_actions = (xbmcgui.ACTION_CONTEXT_MENU, xbmcgui.ACTION_MOUSE_RIGHT_CLICK, xbmcgui.ACTION_MOUSE_LONG_CLICK)
window_xml_left_action, window_xml_right_action = xbmcgui.ACTION_MOVE_LEFT, xbmcgui.ACTION_MOVE_RIGHT
window_xml_up_action, window_xml_down_action = xbmcgui.ACTION_MOVE_UP, xbmcgui.ACTION_MOVE_DOWN
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

class BaseDialog(xbmcgui.WindowXMLDialog):
	fanart = kodi_utils.get_addoninfo('fanart')
	icon = kodi_utils.get_addoninfo('icon')
	def __init__(self, *args):
		xbmcgui.WindowXMLDialog.__init__(self, args)
		self.info_actions = window_xml_info_action
		self.closing_actions = window_xml_closing_actions
		self.selection_actions = window_xml_selection_actions
		self.context_actions = window_xml_context_actions
		self.left_actions = window_xml_left_action
		self.right_actions = window_xml_right_action
		self.up_actions = window_xml_up_action
		self.down_actions = window_xml_down_action
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

