from datetime import datetime, timedelta
from caches import BaseCache, maincache_db, get_property, set_property, clear_property
# from modules.kodi_utils import logger

BASE_GET = 'SELECT data, expires FROM maincache WHERE id = ? AND expires > ?'
BASE_SET = 'INSERT OR REPLACE INTO maincache (id, data, expires) VALUES (?, ?, ?)'
BASE_DELETE = 'DELETE FROM maincache WHERE id = ?'
LIKE_SELECT, LIKE_SELECT_ADD = 'SELECT id FROM maincache WHERE %s', 'id LIKE ?'

class MainCache(BaseCache):
	db_file = maincache_db

	def get(self, string):
		result = None
		try:
			current_time = self._get_timestamp(datetime.now())
			result = self.get_memory_cache(string, current_time)
			if result: raise Exception('memory cache true')
			self.dbcur.execute(BASE_GET, (string, current_time))
			cache_data = self.dbcur.fetchone()
			if not cache_data: raise Exception('disk cache false')
			result, expiry = eval(cache_data[0]), cache_data[1]
			self.set_memory_cache(result, string, expiry)
		except: pass
		return result

	def set(self, string, data, expiration):
		try:
			expires = self._get_timestamp(datetime.now() + expiration)
			self.dbcur.execute(BASE_SET, (string, repr(data), int(expires)))
			self.set_memory_cache(data, string, int(expires))
		except: pass

	def get_memory_cache(self, string, current_time):
		result = None
		try:
			cachedata = get_property(string)
			if cachedata:
				cachedata = eval(cachedata)
				if cachedata[0] > current_time: result = cachedata[1]
		except: pass
		return result

	def set_memory_cache(self, data, string, expires):
		try:
			cachedata = (expires, data)
			cachedata = repr(cachedata)
			set_property(string, cachedata)
		except: pass

	def delete(self, string, dbcon=None):
		try:
			self.dbcur.execute(BASE_DELETE, (string,))
			self.delete_memory_cache(string)
		except: pass

	def delete_memory_cache(self, string):
		clear_property(string)

	def delete_all_lists(self):
		from modules.meta_lists import media_lists
		items = ' OR '.join(LIKE_SELECT_ADD for i in media_lists)
		self.dbcur.execute(LIKE_SELECT % items, media_lists)
		results = self.dbcur.fetchall()
		try:
			for item in results:
				try:
					self.dbcur.execute(BASE_DELETE, (str(item[0]),))
					self.delete_memory_cache(str(item[0]))
				except: pass
			self.dbcur.execute("""VACUUM""")
		except: pass

def cache_object(function, string, url, expiration=24, json=False):
	maincache = MainCache()
	cache = maincache.get(string)
	if cache: return cache
	if not isinstance(url, list): url = (url,)
	if json: result = function(*url).json()
	else: result = function(*url)
	if isinstance(expiration, int): expiration = timedelta(hours=expiration)
	maincache.set(string, result, expiration)
	return result

