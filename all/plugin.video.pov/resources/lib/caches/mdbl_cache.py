import json
from modules import kodi_utils
from modules.utils import chunks
# from modules.kodi_utils import logger

SELECT = 'SELECT id FROM mdbl_data'
DELETE = 'DELETE FROM mdbl_data WHERE id = ?'
DELETE_LIKE = 'DELETE FROM mdbl_data WHERE id LIKE ?'
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
		self._database_connect()
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
#		self.dbcur.execute("""VACUUM""")

	def _database_connect(self):
		self.dbcon = kodi_utils.database_connect(kodi_utils.mdbl_db, isolation_level=None)

	def _set_PRAGMAS(self):
		self.dbcur = self.dbcon.cursor()
		self.dbcur.execute("""PRAGMA synchronous = OFF""")
		self.dbcur.execute("""PRAGMA journal_mode = OFF""")
		self.dbcur.execute("""PRAGMA mmap_size = 268435456""")

def integrity_check():
	try:
		db_file = kodi_utils.translate_path(kodi_utils.mdbl_db)
		with kodi_utils.database.connect(db_file) as dbcon:
			dbcur = dbcon.cursor()
			dbcur.execute("""PRAGMA integrity_check""")
			result = dbcur.fetchone()
			if 'ok' in result: status = 'passed'
			else: raise kodi_utils.database.Error(result)
			dbcur.execute("""VACUUM""")
		return status
	except kodi_utils.database.Error as e: status = str(e)
	try:
		with open(db_file, 'w') as _: pass
		from modules.cache import check_databases, clear_cache
		check_databases()
		clear_cache('mdblist', silent=True)
		status = 'repaired'
	except Exception as e:
		kodi_utils.logger('database integrity error', '%s\n%s\n%s' % (status, db_file, e))
	return status

def cache_mdbl_object(function, string, url):
	dbcur = MDBLCache().dbcur
	dbcur.execute(MC_BASE_GET, (string,))
	cached_data = dbcur.fetchone()
	try:
		if cached_data: return json.loads(cached_data[0])
	except: pass
	result = function(url)
	dbcur.execute(MC_BASE_SET, (string, json.dumps(result)))
	return result

def reset_activity(latest_activities):
	string = 'mdbl_get_activity'
	cached_data = None
	try:
		dbcur = MDBLCache().dbcur
		dbcur.execute(MC_BASE_GET, (string,))
		cached_data = dbcur.fetchone()
		if cached_data: cached_data = json.loads(cached_data[0])
		else: cached_data = default_activities()
		dbcur.execute(MC_BASE_SET, (string, json.dumps(latest_activities)))
	except: pass
	return cached_data

def clear_mdbl_hidden_data(list_type):
	string = 'mdbl_hidden_items_%s' % list_type
	try:
		dbcur = MDBLCache().dbcur
		dbcur.execute(DELETE, (string,))
	except: pass

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
		dbcur.execute(DELETE_LIKE, (string,))
	except: pass

def clear_mdbl_list_data(list_type):
	string = 'mdbl_%s' % list_type
	try:
		dbcur = MDBLCache().dbcur
		dbcur.execute(DELETE, (string,))
	except: pass

def clear_mdbl_calendar():
	try:
		dbcur = MDBLCache().dbcur
		dbcur.execute(DELETE_LIKE, ('mdbl_get_my_calendar_%',))
	except: return

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
			'watchlisted_at': '',
			'watched_at': '',
			'season_watched_at': '',
			'episode_watched_at': '',
			'rated_at': '',
			'journal_at': '',
			'collected_at': '',
			'dropped_at': '',
			'paused_at': '',
			'episode_paused_at': '',
			'list_updated_at': '',
			'server_time': ''
			}

