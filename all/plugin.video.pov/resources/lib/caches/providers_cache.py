from datetime import datetime, timedelta
from caches import BaseCache, external_db
# from modules.kodi_utils import logger

SELECT_RESULTS = """
	SELECT results, expires
	FROM results_data
	WHERE provider = ?
	AND db_type = ?
	AND tmdb_id = ?
	AND title = ?
	AND year = ?
	AND season = ?
	AND episode = ?
	AND expires > ?
"""
DELETE_RESULTS = """
	DELETE
	FROM results_data
	WHERE provider = ?
	AND db_type = ?
	AND tmdb_id = ?
	AND title = ?
	AND year = ?
	AND season = ?
	AND episode = ?
"""
INSERT_RESULTS = 'INSERT OR REPLACE INTO results_data VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)'
SINGLE_DELETE = 'DELETE FROM results_data WHERE db_type = ? AND tmdb_id = ?'
FULL_DELETE = 'DELETE FROM results_data'

class ExternalProvidersCache(BaseCache):
	db_file = external_db

	def get(self, source, mediatype, tmdb_id, title, year, season, episode):
		result = None
		try:
			current_time = self._get_timestamp(datetime.now())
			self.dbcur.execute(SELECT_RESULTS, (source, mediatype, tmdb_id, title, year, season, episode, current_time))
			cache_data = self.dbcur.fetchone()
			if not cache_data: raise Exception('disk cache false')
			result = eval(cache_data[0])
		except: pass
		return result

	def set(self, source, mediatype, tmdb_id, title, year, season, episode, results, expire_time):
		try:
			expires = self._get_timestamp(datetime.now() + timedelta(hours=expire_time))
			self.dbcur.execute(INSERT_RESULTS, (source, mediatype, tmdb_id, title, year, season, episode, repr(results), int(expires)))
		except: pass

	def delete(self, source, mediatype, tmdb_id, title, season, episode):
		try: self.dbcur.execute(DELETE_RESULTS, (source, mediatype, tmdb_id, title, season, episode))
		except: pass

	def delete_cache(self):
		try:
			self.dbcur.execute(FULL_DELETE)
			self.dbcur.execute("""VACUUM""")
			return 'success'
		except: return 'failure'

	def delete_cache_single(self, mediatype, tmdb_id):
		try:
			self.dbcur.execute(SINGLE_DELETE, (mediatype, tmdb_id))
			self.dbcur.execute("""VACUUM""")
			return True
		except: return False

