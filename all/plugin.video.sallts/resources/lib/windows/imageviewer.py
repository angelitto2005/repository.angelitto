import json
from windows import BaseDialog
from indexers.tmdb_api import tmdb_popular_people
from menus.people import person_data_dialog
from modules.settings import download_directory
from modules.kodi_utils import media_path, show_busy_dialog, hide_busy_dialog, local_string as ls, get_property, set_property
# from modules.kodi_utils import logger

fanart = BaseDialog.fanart
next_icon = media_path('item_next.png')
nextpage_str, delete_str, down_str = ls(32799), ls(32785), ls(32747)

class ThumbImageViewer(BaseDialog):
	def __init__(self, *args, **kwargs):
		BaseDialog.__init__(self, args)
		self.window_id = 2000
		self.current_page = 1
		self.selected = None
		self.list_items = kwargs.get('list_items')
		self.next_page_params = kwargs.get('next_page_params')
		self.ImagesInstance = kwargs.get('ImagesInstance')

	def onInit(self):
		self.make_page()

	def run(self):
		self.doModal()
		self.clearProperties()

	def onAction(self, action):
		if action in self.closing_actions:
			return self.previous_page()
		try:
			position = self.get_position(self.window_id)
			chosen_listitem = self.get_listitem(self.window_id)
		except: return
		if action in self.selection_actions:
			if chosen_listitem.getProperty('tikiskins.next_page_item') == 'true': self.new_page()
			else:
				thumb_params = chosen_listitem.getProperty('tikiskins.action')
				thumb_params = json.loads(thumb_params)
				if thumb_params['mode'] == 'slideshow_image':
					thumb_params['current_index'] = position
					ending_position = self.ImagesInstance.run(thumb_params)
					self.win.selectItem(ending_position)
				elif thumb_params['mode'] == 'person_data_dialog':
					person_data_dialog({'query': thumb_params['actor_name']})
		elif action in self.context_actions:
			choice = self.open_window(('windows.imageviewer', 'ThumbContextMenu'), 'contextmenu.xml', list_item=chosen_listitem)
			if choice:
				if 'delete_image' in choice: self.reset_after_delete(choice, position)
				else: self.execute_code(choice)

	def make_page(self):
		try:
			self.set_properties()
			if self.next_page_params.get('page_no', 'final_page') != 'final_page': self.make_next_page()
			self.win = self.getControl(self.window_id)
			self.win.addItems(self.list_items)
			self.setFocusId(self.window_id)
		except: pass

	def new_page(self):
		try:
			show_busy_dialog()
			self.win.reset()
			self.current_page += 1
			self.next_page_params['in_progress'] = 'true'
			self.list_items, self.next_page_params = self.ImagesInstance.run(self.next_page_params)
			hide_busy_dialog()
			self.make_page()
		except: self.close()

	def previous_page(self):
		try:
			self.current_page -= 1
			if self.current_page < 1: return self.close()
			self.win.reset()
			self.next_page_params['page_no'] = self.current_page
			self.next_page_params['in_progress'] = 'true'
			self.list_items, self.next_page_params = self.ImagesInstance.run(self.next_page_params)
			self.make_page()
		except: self.close()

	def make_next_page(self):
		try:
			listitem = self.make_listitem()
			listitem.setProperty('tikiskins.name', nextpage_str)
			listitem.setProperty('tikiskins.thumb', next_icon)
			listitem.setProperty('tikiskins.next_page_item', 'true')
			self.list_items.append(listitem)
		except: pass

	def reset_after_delete(self, choice, position):
		set_property('salts_delete_image_finished', 'false')
		self.execute_code(choice)
		while not get_property('salts_delete_image_finished') == 'true': self.sleep(10)
		self.win.reset()
		self.list_items = self.ImagesInstance.browser_image(download_directory('image'), return_items=True)
		self.make_page()
		self.win.selectItem(position)

	def set_properties(self):
		self.setProperty('tikiskins.page_no', str(self.current_page))
		self.setProperty('tikiskins.thumbviewer.fanart', fanart)

class ThumbContextMenu(BaseDialog):
	def __init__(self, *args, **kwargs):
		BaseDialog.__init__(self, args)
		self.window_id = 2020
		self.list_item = kwargs['list_item']
		self.item_list = []
		self.selected = None
		self.make_context_menu()

	def onInit(self):
		self.set_properties()
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
		if action in self.context_actions:
			return self.close()
		if action in self.closing_actions:
			return self.close()

	def set_properties(self):
		self.setProperty('tikiskins.context.highlight', 'orange')

	def make_context_menu(self):
		enable_delete = self.list_item.getProperty('tikiskins.delete') == 'true'
		path = self.list_item.getProperty('tikiskins.path')
		thumb_url = self.list_item.getProperty('tikiskins.thumb')
		if enable_delete:
			self.item_list.append(self.make_contextmenu_item('[B]%s[/B]' % delete_str, 'RunPlugin(%s)', {
				'mode': 'delete_image', 'folder_path': self.list_item.getProperty('tikiskins.folder_path'),
				'thumb_url': thumb_url, 'image_url': path, 'in_progress': 'true'
			}))
		else: self.item_list.append(self.make_contextmenu_item(down_str, 'RunPlugin(%s)', {
			'mode': 'downloader', 'action': 'image', 'mediatype': 'image', 'image': BaseDialog.icon,
			'thumb_url': thumb_url, 'image_url': path, 'name': self.list_item.getProperty('tikiskins.name')
		}))

class SlideShow(BaseDialog):
	def __init__(self, *args, **kwargs):
		BaseDialog.__init__(self, args)
		self.window_id = 5000
		self.all_images = kwargs.get('all_images')
		self.index = kwargs.get('index')
		self.set_properties()
		self.make_items()

	def onInit(self):
		self.win = self.getControl(self.window_id)
		self.win.addItems(self.item_list)
		self.win.selectItem(self.index)
		self.setFocusId(self.window_id)

	def run(self):
		self.doModal()
		return self.position

	def onAction(self, action):
		if action in self.closing_actions:
			self.position = self.get_position(self.window_id)
			self.close()

	def make_items(self):
		def builder():
			for item in self.all_images:
				try:
					listitem = self.make_listitem()
					listitem.setProperty('tikiskins.slideshow.image', item[0])
					listitem.setProperty('tikiskins.slideshow.title', item[1])
					yield listitem
				except: pass
		self.item_list = list(builder())

	def set_properties(self):
		self.setProperty('tikiskins.slideshow.fanart', fanart)

