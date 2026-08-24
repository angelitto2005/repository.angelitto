import sqlite3
from modules.kodi_utils import favorites_db, translate_path
from modules.settings import ignore_articles
from modules.utils import sort_for_article
# from modules.kodi_utils import logger

def call_local(path, values=None, executemany=False, db_path=None):
	if values is None: values = ()
	if db_path is None: db_path = favorites_db
	if db_path.startswith('special://'):
		db_path = translate_path(db_path)
	with sqlite3.connect(db_path) as dbcon:
		dbcon.row_factory = sqlite3.Row
		dbcur = dbcon.cursor()
		try:
			dbcur.execute("""PRAGMA synchronous = OFF""")
			dbcur.execute("""PRAGMA journal_mode = OFF""")
			if executemany: dbcur.executemany(path, values)
			else: dbcur.execute(path, values)
			if path.strip().upper().startswith('SELECT'):
				rows = [dict(row) for row in dbcur.fetchall()]
				return rows
			else:
				dbcon.commit()
				return None
		finally: dbcur.close()

def local_favorites(watched_info, mediatype, page_no):
	path = 'SELECT tmdb_id, title FROM favorites WHERE db_type = ?'
	data = call_local(path, (mediatype,))
	if page_no == 'all': return data
	data = [{'media_id': str(i['tmdb_id']), 'title': i['title']} for i in data]
	original_list = sort_for_article(data, 'title', ignore_articles())
	return original_list, 1

def local_droplist(watched_info, mediatype, page_no):
	path = 'SELECT tmdb_id, title FROM dropped WHERE db_type = ?'
	data = call_local(path, (mediatype,))
	if page_no == 'all': return data
	data = [{'media_id': str(i['tmdb_id']), 'title': i['title']} for i in data]
	original_list = sort_for_article(data, 'title', ignore_articles())
	return original_list, 1

def add_to_sync(list_id, mediatype, tmdb_id, title):
	path = 'INSERT INTO %s VALUES (?, ?, ?)' % list_id
	try: call_local(path, (mediatype, str(tmdb_id), title))
	except: return False
	return True

def remove_from_sync(list_id, mediatype, tmdb_id, title):
	path = 'DELETE FROM %s WHERE db_type = ? and tmdb_id = ?' % list_id
	try: call_local(path, (mediatype, str(tmdb_id)))
	except: return False
	return True

def local_get_hidden_items(list_type):
	data = call_local('SELECT tmdb_id FROM dropped')
	return [int(i['tmdb_id']) for i in data]

