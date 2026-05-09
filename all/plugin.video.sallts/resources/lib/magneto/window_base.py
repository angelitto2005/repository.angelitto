from . import kore
from .settings import skin_location

window_xml_dialog, logger, manual_function_import = kore.window_xml_dialog, kore.logger, kore.manual_function_import

def open_window(import_info, skin_xml, **kwargs):
	'''
	import_info: ('module', 'function')
	'''
	try:
		xml_window = create_window(import_info, skin_xml, **kwargs)
		choice = xml_window.run()
		del xml_window
		return choice
	except Exception as e:
		logger('error in open_window', str(e))

def create_window(import_info, skin_xml, **kwargs):
	'''
	import_info: ('module', 'function')
	'''
	try:
		function = manual_function_import(*import_info)
		args = (skin_xml, skin_location(skin_xml))
		xml_window = function(*args, **kwargs)
		return xml_window
	except Exception as e:
		logger('error in create_window', str(e))
		return kore.notification('Error')

class BaseDialog(window_xml_dialog):
	def __init__(self, *args):
		window_xml_dialog.__init__(self, args)
		self.player = kore.player
		self.closing_actions = kore.window_xml_closing_actions
		self.selection_actions = kore.window_xml_selection_actions
		self.context_actions = kore.window_xml_context_actions
		self.info_action = kore.window_xml_info_action
		self.left_action = kore.window_xml_left_action
		self.right_action = kore.window_xml_right_action
		self.up_action = kore.window_xml_up_action
		self.down_action = kore.window_xml_down_action

	def make_listitem(self):
		return kore.make_listitem()

	def build_url(self, params):
		return kore.build_url(params)

	def execute_code(self, command, block=False):
		return kore.execute_builtin(command, block)

	def get_position(self, window_id):
		return self.get_control(window_id).getSelectedPosition()

	def get_listitem(self, window_id):
		return self.get_control(window_id).getSelectedItem()

	def add_items(self, _control, _items):
		self.get_control(_control).addItems(_items)

	def select_item(self, _control, _item):
		self.get_control(_control).selectItem(_item)

	def set_image(self, _control, _image):
		self.get_control(_control).setImage(_image)

	def set_label(self, _control, _label):
		self.get_control(_control).setLabel(_label)

	def set_text(self, _control, _text):
		self.get_control(_control).setText(_text)

	def set_percent(self, _control, _percent):
		self.get_control(_control).setPercent(_percent)

	def reset_window(self, _control):
		self.get_control(_control).reset()

	def get_control(self, control_id):
		return self.getControl(control_id)

	def make_contextmenu_item(self, label, action, params):
		cm_item = self.make_listitem()
		cm_item.set_properties({'label': label, 'action': action % self.build_url(params)})
		return cm_item

	def get_visibility(self, command):
		return kore.get_visibility(command)

	def open_window(self, import_info, skin_xml, **kwargs):
		return open_window(import_info, skin_xml, **kwargs)

	def sleep(self, time):
		kore.sleep(time)

	def clear_modals(self):
		try: del self.player
		except: pass
