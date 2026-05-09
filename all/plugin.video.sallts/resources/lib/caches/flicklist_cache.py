from modules.kodi_utils import flickl_db, database_connect
from modules.utils import chunks
# from modules.kodi_utils import logger

timeout = 20
SELECT = 'SELECT id FROM flickl_data'
DELETE = 'DELETE FROM flickl_data WHERE id = ?'
DELETE_LIKE = 'DELETE FROM flickl_data WHERE id LIKE "%s"'
WATCHED_INSERT = 'INSERT OR IGNORE INTO watched_status VALUES (?, ?, ?, ?, ?, ?)'
WATCHED_DELETE = 'DELETE FROM watched_status WHERE db_type = ?'
PROGRESS_INSERT = 'INSERT OR IGNORE INTO progress VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)'
PROGRESS_DELETE = 'DELETE FROM progress WHERE db_type = ?'
BASE_DELETE = 'DELETE FROM %s'
FL_BASE_GET = 'SELECT data FROM flickl_data WHERE id = ?'
FL_BASE_SET = 'INSERT OR REPLACE INTO flickl_data (id, data) VALUES (?, ?)'
FL_BASE_DELETE = 'DELETE FROM flickl_data WHERE id = ?'

class FlickListCache:
	batch_size = 1000
	def __init__(self):
		self._connect_database()
		self._set_PRAGMAS()

	def set_bulk_movie_watched(self, insert_list):
		self._delete(WATCHED_DELETE, ('movie',))
		for i in chunks(insert_list, self.batch_size):
			self._executemany(WATCHED_INSERT, i)

	def set_bulk_tvshow_watched(self, insert_list):
		self._delete(WATCHED_DELETE, ('episode',))
		for i in chunks(insert_list, self.batch_size):
			self._executemany(WATCHED_INSERT, i)

	def set_bulk_movie_progress(self, insert_list):
		self._delete(PROGRESS_DELETE, ('movie',))
		self._executemany(PROGRESS_INSERT, insert_list)

	def set_bulk_tvshow_progress(self, insert_list):
		self._delete(PROGRESS_DELETE, ('episode',))
		self._executemany(PROGRESS_INSERT, insert_list)

	def _executemany(self, command, insert_list):
		self.dbcur.executemany(command, insert_list)

	def _delete(self, command, args):
		self.dbcur.execute(command, args)
		self.dbcur.execute("""VACUUM""")

	def _connect_database(self):
		self.dbcon = database_connect(flickl_db, timeout=timeout, isolation_level=None)

	def _set_PRAGMAS(self):
		self.dbcur = self.dbcon.cursor()
		self.dbcur.execute("""PRAGMA synchronous = OFF""")
		self.dbcur.execute("""PRAGMA journal_mode = OFF""")
		self.dbcur.execute("""PRAGMA mmap_size = 268435456""")

def cache_flicklist_object(function, string, url):
	dbcur = FlickListCache().dbcur
	dbcur.execute(FL_BASE_GET, (string,))
	cached_data = dbcur.fetchone()
	if cached_data: return eval(cached_data[0])
	result = function(url)
	dbcur.execute(FL_BASE_SET, (string, repr(result)))
	return result

def reset_activity(latest_activities):
	string = 'flicklist_get_activity'
	cached_data = None
	try:
		dbcur = FlickListCache().dbcur
		dbcur.execute(FL_BASE_GET, (string,))
		cached_data = dbcur.fetchone()
		if cached_data: cached_data = eval(cached_data[0])
		else: cached_data = default_activities()
		dbcur.execute(FL_BASE_SET, (string, repr(latest_activities)))
	except: pass
	return cached_data

def clear_flicklist_collection_watchlist_data(list_type):
	string = 'flicklist_%s' % list_type
	try:
		dbcur = FlickListCache().dbcur
		dbcur.execute(DELETE, (string,))
	except: pass

def clear_flicklist_list_contents_data(list_type):
	string = 'flicklist_list_contents_' + list_type + '_%'
	try:
		dbcur = FlickListCache().dbcur
		dbcur.execute(DELETE_LIKE % string)
	except: pass

def clear_flicklist_list_data(list_type):
	string = 'flicklist_%s' % list_type
	try:
		dbcur = FlickListCache().dbcur
		dbcur.execute(DELETE, (string,))
	except: pass

def clear_all_flicklist_cache_data(refresh=True):
	try:
		dbcur = FlickListCache().dbcur
		for table in ('flickl_data', 'progress', 'watched_status'):
			dbcur.execute(BASE_DELETE % table)
		dbcur.execute("""VACUUM""")
		if not refresh: return True
		from indexers.flicklist_api import flicklist_sync_activities_thread
		flicklist_sync_activities_thread()
		return True
	except: return False

def default_activities():
	return {
			'all': '1970-01-01T00:00:00.000Z',
			'movies':
				{
				'watched_at': '1970-01-01T00:00:00.000Z',
				'paused_at': '1970-01-01T00:00:00.000Z',
				'watchlisted_at': '1970-01-01T00:00:00.000Z'
				},
			'episodes':
				{
				'watched_at': '1970-01-01T00:00:00.000Z',
				'paused_at': '1970-01-01T00:00:00.000Z'
				},
			'shows':
				{
				'watchlisted_at': '1970-01-01T00:00:00.000Z'
				},
			'lists':
				{
				'updated_at': '1970-01-01T00:00:00.000Z'
				},
			'favorites': '1970-01-01T00:00:00.000Z'
			}

