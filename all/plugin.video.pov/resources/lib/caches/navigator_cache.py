from caches import BaseCache, navigator_db, get_property, set_property, clear_property
from modules import menu_lists as default_menus
# from modules.kodi_utils import logger

GET_LIST = 'SELECT list_contents FROM navigator WHERE list_name = ? AND list_type = ?'
SET_LIST = 'INSERT OR REPLACE INTO navigator VALUES (?, ?, ?)'
DELETE_LIST = 'DELETE FROM navigator WHERE list_name = ? and list_type = ?'
GET_FOLDERS = 'SELECT list_name, list_contents FROM navigator WHERE list_type = ?'
GET_FOLDER_CONTENTS = 'SELECT list_contents FROM navigator WHERE list_name = ? AND list_type = ?'

def prop_get(value, *args):
	if value == 'shortcut_folder': return 'pov_%s_shortcut_folder' % args
	if value == 'default': return 'pov_%s_default' % args
	if value == 'edited': return 'pov_%s_edited' % args
	return ''.join(args)

class NavigatorCache(BaseCache):
	db_file = navigator_db

	def get_main_lists(self, list_name):
		default_contents = self.get_memory_cache(list_name, 'default')
		if not default_contents:
			default_contents = self.get_list(list_name, 'default')
			if default_contents is None:
				self.rebuild_database()
				default_contents = self.get_list(list_name, 'default')
				if default_contents is None: return None, None
			try:
				edited_contents = self.get_list(list_name, 'edited')
				self.set_memory_cache(list_name, 'edited', edited_contents)
				self.set_memory_cache(list_name, 'default', default_contents)
			except: edited_contents = None
		else: edited_contents = self.get_memory_cache(list_name, 'edited')
		return default_contents, edited_contents

	def get_list(self, list_name, list_type):
		try: return self.jsloads(self.dbcur.execute(GET_LIST, (list_name, list_type)).fetchone()[0])
		except: return None

	def set_list(self, list_name, list_type, list_contents):
		self.dbcur.execute(SET_LIST, (list_name, list_type, self.jsdumps(list_contents)))
		self.set_memory_cache(list_name, list_type, list_contents)

	def delete_list(self, list_name, list_type):
		self.dbcur.execute(DELETE_LIST, (list_name, list_type))
		self.delete_memory_cache(list_name, list_type)
		self.dbcur.execute("""VACUUM""")

	def get_memory_cache(self, list_name, list_type):
		try: return self.jsloads(get_property(prop_get(list_type, list_name)))
		except: return None

	def set_memory_cache(self, list_name, list_type, list_contents):
		set_property(prop_get(list_type, list_name), self.jsdumps(list_contents))

	def delete_memory_cache(self, list_name, list_type):
		clear_property(prop_get(list_type, list_name))

	def get_shortcut_folders(self):
		try:
			folders = self.dbcur.execute(GET_FOLDERS, ('shortcut_folder',)).fetchall()
			return sorted([(str(i[0]), i[1]) for i in folders], key=lambda s: s[0].lower())
		except: return []

	def get_shortcut_folder_contents(self, list_name):
		try:
			contents = self.dbcur.execute(GET_FOLDER_CONTENTS, (list_name, 'shortcut_folder')).fetchone()[0]
			return self.jsloads(contents)
		except: return []

	def currently_used_list(self, list_name):
		default_contents, edited_contents = self.get_main_lists(list_name)
		list_items = edited_contents or default_contents
		return list_items

	def rebuild_database(self):
		for list_name in default_menus.default_menu_items:
			self.set_list(list_name, 'default', default_menus.main_menus[list_name])

navigator_cache = NavigatorCache()

