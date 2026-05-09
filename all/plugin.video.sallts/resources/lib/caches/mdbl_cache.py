from modules.kodi_utils import mdbl_db, database_connect
from modules.utils import chunks
# from modules.kodi_utils import logger

timeout = 20
SELECT = 'SELECT id FROM mdbl_data'
DELETE = 'DELETE FROM mdbl_data WHERE id = ?'
DELETE_LIKE = 'DELETE FROM mdbl_data WHERE id LIKE "%s"'
WATCHED_INSERT = 'INSERT OR IGNORE INTO watched_status VALUES (?, ?, ?, ?, ?, ?)'
WATCHED_DELETE = 'DELETE FROM watched_status WHERE db_type = ?'
PROGRESS_INSERT = 'INSERT OR IGNORE INTO progress VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)'
PROGRESS_DELETE = 'DELETE FROM progress WHERE db_type = ?'
BASE_DELETE = 'DELETE FROM %s'
MC_BASE_GET = 'SELECT data FROM mdbl_data WHERE id = ?'
MC_BASE_SET = 'INSERT OR REPLACE INTO mdbl_data (id, data) VALUES (?, ?)'
MC_BASE_DELETE = 'DELETE FROM mdbl_data WHERE id = ?'

class MDBLCache:
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
		self.dbcon = database_connect(mdbl_db, timeout=timeout, isolation_level=None)

	def _set_PRAGMAS(self):
		self.dbcur = self.dbcon.cursor()
		self.dbcur.execute("""PRAGMA synchronous = OFF""")
		self.dbcur.execute("""PRAGMA journal_mode = OFF""")
		self.dbcur.execute("""PRAGMA mmap_size = 268435456""")

def cache_mdbl_object(function, string, url):
	dbcur = MDBLCache().dbcur
	dbcur.execute(MC_BASE_GET, (string,))
	cached_data = dbcur.fetchone()
	if cached_data: return eval(cached_data[0])
	result = function(url)
	dbcur.execute(MC_BASE_SET, (string, repr(result)))
	return result

def reset_activity(latest_activities):
	string = 'mdbl_get_activity'
	cached_data = None
	try:
		dbcur = MDBLCache().dbcur
		dbcur.execute(MC_BASE_GET, (string,))
		cached_data = dbcur.fetchone()
		if cached_data: cached_data = eval(cached_data[0])
		else: cached_data = default_activities()
		dbcur.execute(MC_BASE_SET, (string, repr(latest_activities)))
	except: pass
	return cached_data

def clear_mdbl_collection_watchlist_data(list_type):
	string = 'mdbl_%s' % list_type
	try:
		dbcur = MDBLCache().dbcur
		dbcur.execute(DELETE, (string,))
	except: pass

def clear_mdbl_list_contents_data(list_type):
	string = 'mdbl_list_contents_' + list_type + '_%'
	try:
		dbcur = MDBLCache().dbcur
		dbcur.execute(DELETE_LIKE % string)
	except: pass

def clear_mdbl_list_data(list_type):
	string = 'mdbl_%s' % list_type
	try:
		dbcur = MDBLCache().dbcur
		dbcur.execute(DELETE, (string,))
	except: pass

def clear_all_mdbl_cache_data(refresh=True):
	try:
		dbcur = MDBLCache().dbcur
		for table in ('mdbl_data', 'progress', 'watched_status'):
			dbcur.execute(BASE_DELETE % table)
		dbcur.execute("""VACUUM""")
		if not refresh: return True
		from indexers.mdblist_api import mdbl_sync_activities_thread
		mdbl_sync_activities_thread()
		return True
	except: return False

def default_activities():
	return {
			'watchlisted_at': '2022-05-24T02:09:00Z',
			'watched_at': '2022-05-24T02:09:00Z',
			'season_watched_at': '2022-05-24T02:09:00Z',
			'episode_watched_at': '2022-05-24T02:09:00Z',
			'rated_at': '2022-05-24T02:09:00Z',
			'collected_at': '2022-05-24T02:09:00Z',
			'dropped_at': '2022-05-24T02:09:00Z',
			'paused_at': '2022-05-24T02:09:00Z',
			'episode_paused_at': '2022-05-24T02:09:00Z',
			'list_updated_at': '2022-05-24T02:09:00Z'
			}

