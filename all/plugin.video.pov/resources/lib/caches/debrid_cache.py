from datetime import datetime, timedelta
from caches import BaseCache, debridcache_db
# from modules.kodi_utils import logger

GET_MANY = 'SELECT * FROM debrid_data WHERE hash in (%s)'
SET_MANY = 'INSERT INTO debrid_data VALUES (?, ?, ?, ?)'
REMOVE_MANY = 'DELETE FROM debrid_data WHERE hash = ?'
SINGLE_DELETE = 'DELETE FROM debrid_data WHERE debrid = ?'
FULL_DELETE = 'DELETE FROM debrid_data'

class DebridCache(BaseCache):
	db_file = debridcache_db

	def get_many(self, hash_list):
		result = None
		try:
			current_time = self._get_timestamp(datetime.now())
			self.dbcur.execute(GET_MANY % (', '.join('?' for _ in hash_list)), hash_list)
			cache_data = self.dbcur.fetchall()
			if cache_data and cache_data[0][3] > current_time: result = cache_data
			elif cached_data: self.remove_many(cache_data)
		except: pass
		return result

	def set_many(self, hash_list, debrid):
		try:
			expires = self._get_timestamp(datetime.now() + timedelta(hours=24))
			insert_list = [(i[0], debrid, i[1], expires) for i in hash_list]
			self.dbcur.executemany(SET_MANY, insert_list)
		except: pass

	def remove_many(self, cached_data):
		try:
			cached_data = [(str(i[0]),) for i in cached_data]
			self.dbcur.executemany(REMOVE_MANY, cached_data)
		except: pass

	def delete_cache_single(self, debrid):
		try:
			self.dbcur.execute(SINGLE_DELETE, (debrid,))
#			self.dbcur.execute("""VACUUM""")
			return True
		except: return False

	def clear_cache(self):
		try:
			self.dbcur.execute(FULL_DELETE)
			self.dbcur.execute("""VACUUM""")
			return True
		except: return False

