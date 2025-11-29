# -*- coding: utf-8 -*-
from caches.base_cache import BaseCache, get_timestamp
# from modules.kodi_utils import logger

class TMDbListsCache(BaseCache):
	def __init__(self):
		BaseCache.__init__(self, 'tmdb_lists_db', 'tmdb_lists')

	def clear_all_lists(self):
		try:
			dbcon = self.manual_connect('tmdb_lists_db')
			dbcon.execute('DELETE FROM tmdb_lists WHERE id = ?', ('get_user_lists',))
			dbcon.execute('VACUUM')
			return True
		except: return False

	def clear_list(self, list_id):
		try:
			dbcon = self.manual_connect('tmdb_lists_db')
			dbcon.execute('DELETE FROM tmdb_lists WHERE id = ?', ('get_list_details_%s' % list_id,))
			dbcon.execute('VACUUM')
			return True
		except: return False

	def clear_all(self):
		try:
			dbcon = self.manual_connect('tmdb_lists_db')
			dbcon.execute('DELETE FROM tmdb_lists')
			dbcon.execute('VACUUM')
			return True
		except: return False

	def clean_database(self):
		try:
			dbcon = self.manual_connect('tmdb_lists_db')
			dbcon.execute('DELETE FROM tmdb_lists WHERE CAST(expires AS INT) <= ?', (get_timestamp(),))
			dbcon.execute('VACUUM')
			return True
		except: return False

tmdb_lists_cache = TMDbListsCache()

def tmdb_lists_cache_object(function, string, args, json=False, expiration=24):
	cache = tmdb_lists_cache.get(string)
	if cache is not None: return cache
	if isinstance(args, list): args = tuple(args)
	else: args = (args,)
	if json: result = function(*args).json()
	else: result = function(*args)
	tmdb_lists_cache.set(string, result, expiration=expiration)
	return result