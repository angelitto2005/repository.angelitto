# -*- coding: utf-8 -*-
from caches.base_cache import connect_database, get_timestamp
# from modules.kodi_utils import logger

class PersonalListsCache:
	def make_list(self, list_name, sort_order):
		try:
			dbcon = connect_database('personal_lists_db')
			dbcon.execute('INSERT OR REPLACE INTO personal_lists VALUES (?, ?, ?, ?, ?)', (list_name, repr([]), 0, get_timestamp(), sort_order))
			return True
		except: return False

	def delete_list(self, list_name):
		try:
			dbcon = connect_database('personal_lists_db')
			dbcon.execute('DELETE FROM personal_lists WHERE name=?', (list_name,))
			dbcon.execute('VACUUM')
			return True
		except: return False

	def delete_list_contents(self, list_name):
		try:
			dbcon = connect_database('personal_lists_db')
			dbcon.execute('UPDATE personal_lists SET contents=?, total=? WHERE name=?', (repr([]), '0', list_name))
			return True
		except: return False

	def update_list_details(self, list_name, sort_order, original_name):
		try:
			dbcon = connect_database('personal_lists_db')
			dbcon.execute('UPDATE personal_lists SET name=?, sort_order=? WHERE name=?', (list_name, sort_order, original_name))
			return True
		except: return False

	def get_lists(self):
		try:
			dbcon = connect_database('personal_lists_db')
			all_lists = dbcon.execute('SELECT name, total, created, sort_order FROM personal_lists').fetchall()
			return [{'name': str(i[0]), 'total': i[1], 'created_at': i[2], 'sort_order': i[3]} for i in all_lists]
		except: return []

	def get_list(self, list_name, dbcon=None):
		try:
			if not dbcon: dbcon = connect_database('personal_lists_db')
			return eval(dbcon.execute('SELECT contents FROM personal_lists WHERE name=?', (list_name,)).fetchone()[0])
		except: return []

	def add_remove_list_item(self, action, new_contents, list_name):
		try:
			dbcon = connect_database('personal_lists_db')
			contents = self.get_list(list_name, dbcon=dbcon)
			if action == 'add':
				if [str(i['media_id']) for i in contents if str(new_contents['media_id']) == str(i['media_id'])]: return 'Item Already in [B]%s[/B]' % list_name
				command = 'UPDATE personal_lists SET contents=?, total=total+1 WHERE name=?'
				contents.append(new_contents)
			else:
				if not [str(i['media_id']) for i in contents if str(new_contents) == str(i['media_id'])]: return 'Item Not in [B]%s[/B]' % list_name
				command = 'UPDATE personal_lists SET contents=?, total=total-1 WHERE name=?'
				contents = [i for i in contents if not str(i['media_id']) == str(new_contents)]
			dbcon.execute(command, (repr(contents), list_name))
			return 'Success'
		except: return 'Error'

	def add_many_list_items(self, new_contents, list_name):
		try:
			dbcon = connect_database('personal_lists_db')
			contents = self.get_list(list_name, dbcon=dbcon)
			compare_ids = [str(i['media_id']) for i in contents]
			new_contents = [i for i in new_contents if str(i['media_id']) not in compare_ids]
			contents.extend(new_contents)
			dbcon.execute('UPDATE personal_lists SET contents=?, total=? WHERE name=?', (repr(contents), len(contents), list_name))
			return 'Success'
		except: return 'Error'

personal_lists_cache = PersonalListsCache()
