from modules.kodi_utils import trakt_db, database_connect
from modules.utils import chunks
# from modules.kodi_utils import logger

timeout = 20
SELECT = 'SELECT id FROM trakt_data'
DELETE = 'DELETE FROM trakt_data WHERE id = ?'
DELETE_LIKE = 'DELETE FROM trakt_data WHERE id LIKE "%s"'
WATCHED_INSERT = 'INSERT OR IGNORE INTO watched_status VALUES (?, ?, ?, ?, ?, ?)'
WATCHED_DELETE = 'DELETE FROM watched_status WHERE db_type = ?'
PROGRESS_INSERT = 'INSERT OR IGNORE INTO progress VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)'
PROGRESS_DELETE = 'DELETE FROM progress WHERE db_type = ?'
BASE_DELETE = 'DELETE FROM %s'
TC_BASE_GET = 'SELECT data FROM trakt_data WHERE id = ?'
TC_BASE_SET = 'INSERT OR REPLACE INTO trakt_data (id, data) VALUES (?, ?)'
TC_BASE_DELETE = 'DELETE FROM trakt_data WHERE id = ?'

class TraktCache:
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
		self.dbcon = database_connect(trakt_db, timeout=timeout, isolation_level=None)

	def _set_PRAGMAS(self):
		self.dbcur = self.dbcon.cursor()
		self.dbcur.execute("""PRAGMA synchronous = OFF""")
		self.dbcur.execute("""PRAGMA journal_mode = OFF""")
		self.dbcur.execute("""PRAGMA mmap_size = 268435456""")

def cache_trakt_object(function, string, url):
	dbcur = TraktCache().dbcur
	dbcur.execute(TC_BASE_GET, (string,))
	cached_data = dbcur.fetchone()
	if cached_data: return eval(cached_data[0])
	result = function(url)
	dbcur.execute(TC_BASE_SET, (string, repr(result)))
	return result

def reset_activity(latest_activities):
	string = 'trakt_get_activity'
	cached_data = None
	try:
		dbcur = TraktCache().dbcur
		dbcur.execute(TC_BASE_GET, (string,))
		cached_data = dbcur.fetchone()
		if cached_data: cached_data = eval(cached_data[0])
		else: cached_data = default_activities()
		dbcur.execute(TC_BASE_SET, (string, repr(latest_activities)))
	except: pass
	return cached_data

def clear_trakt_hidden_data(list_type):
	string = 'trakt_hidden_items_%s' % list_type
	try:
		dbcur = TraktCache().dbcur
		dbcur.execute(DELETE, (string,))
	except: pass

def clear_trakt_collection_watchlist_data(list_type, mediatype):
	if mediatype == 'movies': mediatype = 'movie'
	if mediatype in ('tvshows', 'shows'): mediatype = 'tvshow'
	string = 'trakt_%s_%s' % (list_type, mediatype)
	try:
		dbcur = TraktCache().dbcur
		dbcur.execute(DELETE, (string,))
	except: pass

def clear_trakt_list_contents_data(list_type):
	string = 'trakt_list_contents_' + list_type + '_%'
	try:
		dbcur = TraktCache().dbcur
		dbcur.execute(DELETE_LIKE % string)
	except: pass

def clear_trakt_list_data(list_type):
	string = 'trakt_%s' % list_type
	try:
		dbcur = TraktCache().dbcur
		dbcur.execute(DELETE, (string,))
	except: pass

def clear_trakt_calendar():
	try:
		dbcur = TraktCache().dbcur
		dbcur.execute(DELETE_LIKE % 'trakt_get_my_calendar_%')
	except: return

def clear_trakt_recommendations(mediatype):
	string = 'trakt_recommendations_%s' % (mediatype)
	try:
		dbcur = TraktCache().dbcur
		dbcur.execute(DELETE, (string,))
	except: pass

def clear_all_trakt_cache_data(refresh=True):
	try:
		dbcur = TraktCache().dbcur
		for table in ('trakt_data', 'progress', 'watched_status'):
			dbcur.execute(BASE_DELETE % table)
		dbcur.execute("""VACUUM""")
		if not refresh: return True
		from indexers.trakt_api import trakt_sync_activities_thread
		trakt_sync_activities_thread()
		return True
	except: return False

def default_activities():
	return {
			'all': '2020-01-01T00:00:01.000Z',
			'movies':
				{
				'watched_at': '2020-01-01T00:00:01.000Z',
				'collected_at': '2020-01-01T00:00:01.000Z',
				'rated_at': '2020-01-01T00:00:01.000Z',
				'watchlisted_at': '2020-01-01T00:00:01.000Z',
				'favorited_at': '2020-01-01T00:00:01.000Z',
				'recommendations_at': '2020-01-01T00:00:01.000Z',
				'commented_at': '2020-01-01T00:00:01.000Z',
				'paused_at': '2020-01-01T00:00:01.000Z',
				'hidden_at': '2020-01-01T00:00:01.000Z'
				},
			'episodes':
				{
				'watched_at': '2020-01-01T00:00:01.000Z',
				'collected_at': '2020-01-01T00:00:01.000Z',
				'rated_at': '2020-01-01T00:00:01.000Z',
				'watchlisted_at': '2020-01-01T00:00:01.000Z',
				'commented_at': '2020-01-01T00:00:01.000Z',
				'paused_at': '2020-01-01T00:00:01.000Z'
				},
			'shows':
				{
				'rated_at': '2020-01-01T00:00:01.000Z',
				'watchlisted_at': '2020-01-01T00:00:01.000Z',
				'favorited_at': '2020-01-01T00:00:01.000Z',
				'recommendations_at': '2020-01-01T00:00:01.000Z',
				'commented_at': '2020-01-01T00:00:01.000Z',
				'hidden_at': '2020-01-01T00:00:01.000Z',
				'dropped_at': '2020-01-01T00:00:01.000Z'
				},
			'seasons':
				{
				'rated_at': '2020-01-01T00:00:01.000Z',
				'watchlisted_at': '2020-01-01T00:00:01.000Z',
				'commented_at': '2020-01-01T00:00:01.000Z',
				'hidden_at': '2020-01-01T00:00:01.000Z'
				},
			'comments':
				{
				'liked_at': '2020-01-01T00:00:01.000Z'
				},
			'lists':
				{
				'liked_at': '2020-01-01T00:00:01.000Z',
				'updated_at': '2020-01-01T00:00:01.000Z',
				'commented_at': '2020-01-01T00:00:01.000Z'
				},
			'watchlist':
				{
				'updated_at': '2020-01-01T00:00:01.000Z'
				},
			'favorites':
				{
				'updated_at': '2020-01-01T00:00:01.000Z'
				},
			'recommendations':
				{
				'updated_at': '2020-01-01T00:00:01.000Z'
				},
			'account':
				{
				'settings_at': '2020-01-01T00:00:01.000Z',
				'followed_at': '2020-01-01T00:00:01.000Z',
				'following_at': '2020-01-01T00:00:01.000Z',
				'pending_at': '2020-01-01T00:00:01.000Z'
				}
			}

