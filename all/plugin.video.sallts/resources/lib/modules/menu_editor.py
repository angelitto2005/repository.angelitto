import json
from urllib.parse import parse_qsl
from caches.navigator_cache import navigator_cache
from modules import kodi_utils, menu_lists as default_menus
# from modules.kodi_utils import logger

ls, media_path = kodi_utils.local_string, kodi_utils.media_path
main_list_name_dict = {'RootList': ls(32457), 'MovieList': ls(32028), 'TVShowList': ls(32029), 'AnimeList': 'Anime'}
pos_str, top_pos_str, top_str = ls(32707), ls(32708), ls(32709)

class MenuEditor:
	def __init__(self, params):
		self.params = params
		if 'menu_item' in params: self.menu_item = json.loads(params.get('menu_item'))
		else: self.menu_item = dict(parse_qsl(kodi_utils.get_infolabel("ListItem.FileNameAndPath").replace('plugin://plugin.video.sallts/?','')))
		self.params_get, self.menu_item_get = self.params.get, self.menu_item.get
		if not self.menu_item: self._make_menu_item()

	def edit_menu(self):
		active_list, position = self.params_get('active_list'), int(self.params_get('position', '0'))
		menu_name = self.menu_item_get('name')
		menu_name_translated = ls(menu_name)
		menu_name_translated_display = menu_name_translated.replace('[B]', '').replace('[/B]', '')
		external_list_item, shortcut_folder = self.menu_item_get('external_list_item', 'False') == 'True', self.menu_item_get('shortcut_folder', 'False') == 'True'
		list_name =  main_list_name_dict[active_list]
		listing = []
		if len(active_list) != 1:
			listing.append((ls(32716) % menu_name_translated_display, self.move))
			listing.append((ls(32717) % menu_name_translated_display, self.remove))
		if not shortcut_folder:
			listing.append((ls(32718) % menu_name_translated_display, self.add_original_external))
			listing.append((ls(32719) % menu_name_translated_display, self.shortcut_folder_add_item))
		listing.append((ls(32725) % list_name, self.shortcut_folder_add_to_main_menu))
		listing.append((ls(32721) % list_name, self.add_original))
		listing.append((ls(32723) % list_name, self.check_update_list))
		listing.append((ls(32722) % list_name, self.restore))
		if not external_list_item: listing.append((ls(32724) % menu_name_translated_display, self.reload_menu_item))
		list_items = [{'line1': i[0]} for i in listing]
		kwargs = {'items': json.dumps(list_items), 'heading': 'SALTS', 'enumerate': 'false', 'multi_choice': 'false', 'multi_line': 'false'}
		function = kodi_utils.select_dialog([i[1] for i in listing], **kwargs)
		if function is None: return
		self.params = {'active_list': active_list, 'list_name': list_name, 'menu_name': menu_name, 'menu_name_translated': menu_name_translated, 'position': position}
		self.params_get = self.params.get
		return function()

	def edit_menu_shortcut_folder(self):
		listing = [(ls(32712), 'move'), (ls(32713), 'remove'), ('%s %s' % (ls(32671), ls(32129)), 'clear_all')]
		list_items = [{'line1': i[0]} for i in listing]
		kwargs = {'items': json.dumps(list_items), 'heading': 'SALTS', 'enumerate': 'false', 'multi_choice': 'false', 'multi_line': 'false'}
		self.action = kodi_utils.select_dialog([i[1] for i in listing], **kwargs)
		if self.action is None: return
		return self.shortcut_folder_contents_adjust()

	def browse(self):
		active_list = self.params_get('active_list')
		list_name =  main_list_name_dict[active_list]
		try: choice_items = self._get_removed_items(active_list)
		except: return kodi_utils.notification(32760, 1500)
		browse_item = self._menu_select(choice_items, list_name)
		if browse_item is None: return
		browse_item = choice_items[browse_item]
		if browse_item.get('mode') == 'build_popular_people': kodi_utils.execute_builtin('RunPlugin(%s)' % kodi_utils.build_url(browse_item))
		else: kodi_utils.execute_builtin('Container.Update(%s)' % kodi_utils.build_url(browse_item))

	def move(self):
		active_list = self.params_get('active_list')
		list_items = navigator_cache.currently_used_list(active_list)
		if len(list_items) == 1: return kodi_utils.notification(32736, 1500)
		choice_items = [i for i in list_items if str(i['name']) != str(self.params_get('menu_name'))]
		current_position = self.params_get('position')
		new_position = self._menu_select(choice_items, self.params_get('menu_name_translated'), multi_line='true', position_list=True)
		if new_position is None or new_position == current_position: return
		list_items.insert(new_position, list_items.pop(current_position))
		self._db_execute('set', active_list, list_items)

	def remove(self):
		if not kodi_utils.confirm_dialog(): return kodi_utils.notification(32736, 1500)
		active_list = self.params_get('active_list')
		list_items = navigator_cache.currently_used_list(active_list)
		if len(list_items) == 1: return kodi_utils.notification(32736, 1500)
		list_items = [i for i in list_items if str(i['name']) != str(self.params_get('menu_name'))]
		self._db_execute('set', active_list, list_items)

	def add_original(self):
		active_list = self.params_get('active_list')
		try: choice_items = self._get_removed_items(active_list)
		except: return kodi_utils.notification(32760, 1500)
		menu_name_translated = self.params_get('menu_name_translated')
		choice = self._menu_select(choice_items, menu_name_translated)
		if choice is None: return kodi_utils.notification(32736, 1500)
		choice_list = choice_items[choice]
		list_items = navigator_cache.currently_used_list(active_list)
		position = self._menu_select(list_items, menu_name_translated, multi_line='true', position_list=True)
		if position is None: return kodi_utils.notification(32736, 1500)
		list_items.insert(position, choice_list)
		self._db_execute('set', active_list, list_items)

	def add_original_external(self):
		active_list = self.params_get('active_list')
		choice_items = self._get_main_menu_items(active_list)
		choice = self._menu_select([i[1] for i in choice_items], '')
		if choice is None: return kodi_utils.notification(32736, 1500)
		choice_name, choice_list = choice_items[choice]
		list_items = navigator_cache.currently_used_list(choice_list['action'])
		menu_name_translated = self.params_get('menu_name_translated')
		position = self._menu_select(list_items, menu_name_translated, multi_line='true', position_list=True)
		if position is None: return kodi_utils.notification(32736, 1500)
		menu_name = self._get_external_name_input(menu_name_translated)
		list_items.insert(position, self._add_external_info_to_item(self.menu_item, menu_name, False))
		self._db_execute('set', choice_name, list_items, refresh=False)

	def restore(self):
		if not kodi_utils.confirm_dialog(): return kodi_utils.notification(32736, 1500)
		active_list = self.params_get('active_list')
		self._db_execute('delete', active_list, list_type='edited', refresh=False)
		self._db_execute('set', active_list, default_menus.main_menus[active_list], 'default')

	def reload_menu_item(self):
		active_list = self.params_get('active_list')
		default, edited = navigator_cache.get_main_lists(active_list)
		list_type = 'edited' if edited else 'default'
		current_list = edited or default
		menu_name = self.params_get('menu_name')
		try: new_item = [i for i in default if str(i['name']) == str(menu_name)][0]
		except: return kodi_utils.notification(32760, 1500)
		list_items = [i for i in current_list if str(i['name']) != str(menu_name)]
		list_items.insert(self.params_get('position', 0), new_item)
		self._db_execute('set', active_list, list_items, list_type)

	def check_update_list(self):
		active_list = self.params_get('active_list')
		new_contents = default_menus.main_menus[active_list]
		default, edited = navigator_cache.get_main_lists(active_list)
		list_type = 'edited' if edited else'default'
		current_list = edited or default
		if default == new_contents: return kodi_utils.notification(32983, 1500)
		new_entry = [i for i in new_contents if not i in default][0]
		new_entry_translated_name = ls(new_entry.get('name'))
		if not kodi_utils.confirm_dialog(text='%s[CR]%s' % (ls(32727) % new_entry_translated_name, ls(32728))): return kodi_utils.notification(32736, 1500)
		item_position = self._menu_select(current_list, new_entry_translated_name, position_list=True)
		if item_position is None: return kodi_utils.notification(32736, 1500)
		current_list.insert(item_position, new_entry)
		self._db_execute('set', active_list, current_list, list_type)
		if list_type == 'edited': self._db_execute('set', active_list, new_contents, 'default')

	def add_external(self):
		choice_items = self._get_main_menu_items([])
		choice = self._menu_select([i[1] for i in choice_items], '')
		if choice is None: return kodi_utils.notification(32736, 1500)
		choice_name, choice_list = choice_items[choice]
		list_items = navigator_cache.currently_used_list(choice_list['action'])
		menu_name = self.params_get('name')
		position = self._menu_select(list_items, menu_name, multi_line='true', position_list=True)
		if position is None: return kodi_utils.notification(32736, 1500)
		menu_name = self._get_external_name_input(menu_name)
		list_items.insert(position, self._add_external_info_to_item(self.menu_item, menu_name))
		self._db_execute('set', choice_name, list_items, refresh=False)

	def _menu_select(self, choice_items, menu_name, heading='SALTS', multi_line='false', position_list=False):
		def _builder():
			for item in choice_items:
				item_get = item.get
				line1 = ls(item_get('name', '')).replace('[B]', '').replace('[/B]', '')
				line2 = pos_str % (menu_name, line1 or ls(item_get('list_name')) if position_list else '')
				if item_get('iconImage') in ('', 'None', None): icon = 'DefaultFolder.png'
				elif str(item_get('iconImage')).startswith('Default'): icon = item_get('iconImage')
				elif item_get('iconImage') == 'salts.png': icon = kodi_utils.get_addoninfo('icon')
				elif item_get('network_id'): icon = item_get('iconImage', 'discover.png')
				else: icon = '%s%s' % (icon_path, item_get('iconImage', 'discover.png'))
				yield {'line1': line1, 'line2': line2, 'icon': icon}
		menu_name, icon_path = menu_name.replace('[B]', '').replace('[/B]', ''), media_path()
		list_items = list(_builder())
		if position_list: list_items.insert(0, {'line1': top_str, 'line2': top_pos_str % menu_name, 'icon': media_path('top.png')})
		index_list = [list_items.index(i) for i in list_items]
		kwargs = {'items': json.dumps(list_items), 'heading': heading, 'enumerate': 'false', 'multi_choice': 'false', 'multi_line': multi_line}
		return kodi_utils.select_dialog(index_list, **kwargs)

	def _get_removed_items(self, active_list):
		default_list_items, list_items = navigator_cache.get_main_lists(active_list)
		return [i for i in default_list_items if not i in list_items]

	def _get_external_name_input(self, current_name):
		new_name = kodi_utils.dialog.input('SALTS', defaultt=current_name)
		if new_name == current_name: return None
		return new_name

	def _add_external_info_to_item(self, menu_item, menu_name=None, add_all_params=True):
		if add_all_params:
			self.params.pop('mode', None)
			menu_item.update(self.params)
		if menu_name: menu_item['name'] = menu_name
		menu_item['external_list_item'] = 'True'
		return menu_item

	def _get_main_menu_items(self, active_list):
		choice_list = [i for i in default_menus.default_menu_items if i != active_list]
		return [(i, default_menus.main_menu_items[i]) for i in choice_list]

	def _make_menu_item(self):
		pass

	def _remove_active_shortcut_folder(self, main_menu_items_list, folder_name):
		for x in main_menu_items_list:
			try:
				match = [i for i in x[1] if str(i['name']) == str(folder_name)][0]
				new_list = [i for i in x[1] if i != match]
				self._db_execute('set', x[0], new_list, refresh=False)
			except: pass

	def _db_execute(self, db_action, list_name, list_contents=[], list_type='edited', refresh=True):
		if db_action == 'set': navigator_cache.set_list(list_name, list_type, list_contents)
		elif db_action == 'delete': navigator_cache.delete_list(list_name, list_type)
		elif db_action == 'make_new_folder': navigator_cache.set_list(list_name, 'shortcut_folder', list_contents)
		kodi_utils.notification(32576, 1500)
		kodi_utils.sleep(200)
		if refresh: kodi_utils.container_refresh()

	def shortcut_folder_contents_adjust(self):
		active_list = self.params_get('active_list')
		if self.action == 'clear_all':
			if not kodi_utils.confirm_dialog(): return kodi_utils.notification(32736, 1500)
			list_items = []
		else:
			list_name = self.menu_item_get('name')
			list_items = navigator_cache.get_shortcut_folder_contents(active_list)
			if self.action == 'remove':
				if not kodi_utils.confirm_dialog(): return kodi_utils.notification(32736, 1500)
				list_items = [i for i in list_items if str(i['name']) != str(list_name)]
			else:
				if len(list_items) == 1: return kodi_utils.notification(32736, 1500)
				choice_items = [i for i in list_items if str(i['name']) != str(list_name)]
				current_position = int(self.params_get('position', '0'))
				new_position = self._menu_select(choice_items, list_name, multi_line='true', position_list=True)
				if new_position is None or new_position == current_position: return
				list_items.insert(new_position, list_items.pop(current_position))
		self._db_execute('set', active_list, list_items, 'shortcut_folder', True)

	def shortcut_folder_make(self):
		list_name = kodi_utils.dialog.input('SALTS')
		if not list_name: return
		self._db_execute('make_new_folder', list_name, list_type='shortcut_folder')

	def shortcut_folder_add_item(self):
		shortcut_folders = navigator_cache.get_shortcut_folders()
		if len(shortcut_folders) == 1: choice_name, choice_list = shortcut_folders[0]
		elif shortcut_folders:
			choice = self._menu_select([{'name': i[0], 'iconImage': 'folder.png'} for i in shortcut_folders], '')
			if choice is None: return kodi_utils.notification(32736, 1500)
			shortcut_folders[choice]
			choice_name, choice_list = shortcut_folders[choice]
		else:
			if not kodi_utils.confirm_dialog(text=32702, top_space=True, default_control=10): return kodi_utils.notification(32736, 1500)
			self.shortcut_folder_make()
			try: choice_name, choice_list = navigator_cache.get_shortcut_folders()[0]
			except: return kodi_utils.notification(32736, 1500)
		list_items = eval(choice_list)
		name = self.params_get('name') or self.params_get('menu_name_translated')
		menu_name = self._get_external_name_input(name) or name
		self.menu_item.update({'name': menu_name, 'iconImage': self.params_get('iconImage') or self.menu_item_get('iconImage')})
		position = self._menu_select(list_items, menu_name, multi_line='true', position_list=True) if list_items else 0
		if position is None: return kodi_utils.notification(32736, 1500)
		list_items.insert(position, self.menu_item)
		self._db_execute('set', choice_name, list_items, 'shortcut_folder', False)

	def shortcut_folder_add_to_main_menu(self):
		shortcut_folders = navigator_cache.get_shortcut_folders()
		if len(shortcut_folders) == 1: name = shortcut_folders[0][0]
		elif shortcut_folders:
			choice = self._menu_select([{'name': i[0], 'iconImage': 'folder.png'} for i in shortcut_folders], '')
			if choice is None: return kodi_utils.notification(32736, 1500)
			shortcut_folders[choice]
			name = shortcut_folders[choice][0]
		else:
			if not kodi_utils.confirm_dialog(text=32702, top_space=True, default_control=10): return kodi_utils.notification(32736, 1500)
			self.shortcut_folder_make()
			try: name = navigator_cache.get_shortcut_folders()[0][0]
			except: return kodi_utils.notification(32736, 1500)
		chosen_folder = {'mode': 'navigator.build_shortcut_folder_list', 'name': name, 'iconImage': 'folder.png', 'shortcut_folder': 'True', 'external_list_item': 'True'}
		active_list = self.params_get('active_list')
		list_items = navigator_cache.currently_used_list(active_list)
		position = self._menu_select(list_items, name, multi_line='true', position_list=True)
		if position is None: return kodi_utils.notification(32736, 1500)
		list_items.insert(position, chosen_folder)
		self._db_execute('set', active_list, list_items)

	def shortcut_folder_delete(self):
		if not kodi_utils.confirm_dialog(): return kodi_utils.notification(32736, 1500)
		main_menu_items_list = [(i, navigator_cache.currently_used_list(i)) for i in default_menus.default_menu_items]
		folder_name = self.menu_item_get('name')
		self._db_execute('delete', folder_name, list_type='shortcut_folder')
		self._remove_active_shortcut_folder(main_menu_items_list, folder_name)

