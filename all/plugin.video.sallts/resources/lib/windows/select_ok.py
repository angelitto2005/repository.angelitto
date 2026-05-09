import json
from windows import BaseDialog
from modules.kodi_utils import local_string as ls
# from modules.kodi_utils import logger

class Select(BaseDialog):
	def __init__(self, *args, **kwargs):
		BaseDialog.__init__(self, args)
		self.window_id = 2025
		self.kwargs = kwargs
		self.enumerate = self.kwargs.get('enumerate', 'false')
		self.multi_choice = self.kwargs.get('multi_choice', 'false')
		self.preselect = self.kwargs.get('preselect', [])
		self.multi_line = self.kwargs.get('multi_line', 'false')
		self.highlight = self.kwargs.get('highlight', 'orange')
		self.items = json.loads(self.kwargs['items'])
		self.heading = self.kwargs.get('heading', '')
		self.context_active_action = self.kwargs.get('context_active_action', '')
		self.item_list = []
		self.chosen_indexes = []
		self.append = self.chosen_indexes.append
		self.selected = None
		self.set_properties()
		self.make_menu()

	def onInit(self):
		self.win = self.getControl(self.window_id)
		self.win.addItems(self.item_list)
		if self.preselect:
			for index in self.preselect:
				self.item_list[index].setProperty('tikiskins.check_status', 'checked')
				self.append(index)
		self.setFocusId(self.window_id)

	def run(self):
		self.doModal()
		self.clearProperties()
		return self.selected

	def onClick(self, controlID):
		if controlID == 10:
			self.selected = sorted(self.chosen_indexes)
			self.close()
		elif controlID == 11:
			self.close()

	def onAction(self, action):
		chosen_listitem = self.get_listitem(self.window_id)
		if action in self.selection_actions:
			position = self.get_position(self.window_id)
			if self.multi_choice == 'true':
				if chosen_listitem.getProperty('tikiskins.check_status') == 'checked':
					chosen_listitem.setProperty('tikiskins.check_status', '')
					self.chosen_indexes.remove(position)
				else:
					chosen_listitem.setProperty('tikiskins.check_status', 'checked')
					self.append(position)
			else:
				self.selected = position
				return self.close()
		elif action in self.context_actions and self.context_active_action:
			return# not yet used
		elif action in self.closing_actions:
			return self.close()

	def make_menu(self):
		def builder():
			for count, item in enumerate(self.items, 1):
				listitem = self.make_listitem()
				if enum: line1 = '%02d. %s' % (count, item['line1'])
				else: line1 = item['line1']
				if 'line2' in item: line2 = item['line2']
				else: line2 = ''
				if 'icon' in item: icon = item['icon']
				else: icon = BaseDialog.icon
				listitem.setProperty('tikiskins.dialog.icon', icon)
				listitem.setProperty('tikiskins.dialog.line1', line1)
				listitem.setProperty('tikiskins.dialog.line2', line2)
				listitem.setProperty('tikiskins.dialog.item', json.dumps(item))
				yield listitem
		enum = self.enumerate == 'true'
		self.item_list = list(builder())

	def set_properties(self):
		self.setProperty('tikiskins.dialog.multi_choice', self.multi_choice)
		self.setProperty('tikiskins.dialog.multi_line', self.multi_line)
		self.setProperty('tikiskins.dialog.highlight', self.highlight)
		self.setProperty('tikiskins.dialog.heading', self.heading)

class YesNo(BaseDialog):
	def __init__(self, *args, **kwargs):
		BaseDialog.__init__(self, args)
		self.ok_label = kwargs['ok_label']
		self.cancel_label = kwargs['cancel_label']
		self.text = kwargs['text']
		self.highlight = kwargs['highlight']
		self.heading = kwargs['heading']
		self.default_control = kwargs['default_control']

	def onInit(self):
		self.set_properties()
		self.setFocusId(self.default_control)

	def run(self):
		self.doModal()
		return self.selected

	def onClick(self, controlID):
		if controlID == 10:
			self.selected = True
		elif controlID == 11:
			self.selected = False
		self.close()

	def onAction(self, action):
		if action in self.closing_actions:
			self.selected = None
			self.close()

	def set_properties(self):
		self.setProperty('tikiskins.dialog.ok_label', self.ok_label)
		self.setProperty('tikiskins.dialog.cancel_label', self.cancel_label)
		self.setProperty('tikiskins.dialog.text', self.text)
		self.setProperty('tikiskins.dialog.highlight', self.highlight)
		self.setProperty('tikiskins.dialog.heading', self.heading)

class OK(BaseDialog):
	def __init__(self, *args, **kwargs):
		BaseDialog.__init__(self, args)
		self.ok_label = kwargs.get('ok_label')
		self.text = kwargs['text']
		self.highlight = kwargs['highlight']
		self.heading = kwargs['heading']

	def onInit(self):
		self.set_properties()

	def run(self):
		self.doModal()

	def onClick(self, controlID):
		self.selected = True
		self.close()

	def onAction(self, action):
		if action in self.closing_actions:
			self.close()

	def set_properties(self):
		self.setProperty('tikiskins.dialog.ok_label', self.ok_label)
		self.setProperty('tikiskins.dialog.text', self.text)
		self.setProperty('tikiskins.dialog.highlight', self.highlight)
		self.setProperty('tikiskins.dialog.heading', self.heading)

class SelectContextMenu(BaseDialog):
	def __init__(self, *args, **kwargs):
		BaseDialog.__init__(self, args)
		self.window_id = 2020
		self.kwargs = kwargs
		self.item = self.kwargs['item']
		self.context_active_action = self.kwargs['context_active_action']
		self.highlight = 'royalblue'
		self.item_list = []
		self.selected = None
		self.make_menu()
		self.set_properties()

	def onInit(self):
		win = self.getControl(self.window_id)
		win.addItems(self.item_list)
		self.setFocusId(self.window_id)

	def run(self):
		self.doModal()
		return self.selected

	def onAction(self, action):
		if action in self.selection_actions:
			chosen_listitem = self.get_listitem(self.window_id)
			self.selected = chosen_listitem.getProperty('tikiskins.context.action')
			return self.close()
		elif action in self.context_actions:
			return self.close()
		elif action in self.closing_actions:
			return self.close()

	def make_menu(self):
		pass# nothing used yet

	def set_properties(self):
		self.setProperty('tikiskins.context.highlight', self.highlight)

