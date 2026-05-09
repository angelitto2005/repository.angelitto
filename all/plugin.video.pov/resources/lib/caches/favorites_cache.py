from caches import BaseCache, favorites_db
from modules import settings
from modules.utils import sort_for_article, paginate_list
# from modules.kodi_utils import logger

INSERT_FAV = 'INSERT INTO favorites VALUES (?, ?, ?)'
DELETE_FAV = 'DELETE FROM favorites WHERE db_type = ? and tmdb_id = ?'
SELECT_FAV = 'SELECT tmdb_id, title FROM favorites WHERE db_type = ?'
CLEAR_FAV = 'DELETE FROM favorites WHERE db_type = ?'
INSERT_DROP = 'INSERT INTO dropped VALUES (?, ?, ?)'
DELETE_DROP = 'DELETE FROM dropped WHERE db_type = ? and tmdb_id = ?'
SELECT_DROP = 'SELECT tmdb_id, title FROM dropped WHERE db_type = ?'
CLEAR_DROP = 'DELETE FROM dropped WHERE db_type = ?'

class Favorites(BaseCache):
	db_file = favorites_db

	def get(self, mediatype):
		self.dbcur.execute(SELECT_FAV, (mediatype,))
		result = self.dbcur.fetchall()
		result = [{'tmdb_id': str(i[0]), 'title': str(i[1])} for i in result]
		return result

	def add(self, mediatype, tmdb_id, title):
		try:
			self.dbcur.execute(INSERT_FAV, (mediatype, str(tmdb_id), title))
			return True
		except: return False

	def remove(self, mediatype, tmdb_id, title):
		try:
			self.dbcur.execute(DELETE_FAV, (mediatype, str(tmdb_id)))
			return True
		except: return False

	def clear(self, mediatype):
		try:
			self.dbcur.execute(CLEAR_FAV, (mediatype,))
			self.dbcur.execute("""VACUUM""")
			return True
		except: return False

class Dropped(BaseCache):
	db_file = favorites_db

	def get(self, mediatype):
		self.dbcur.execute(SELECT_DROP, ('tvshow',))
		result = self.dbcur.fetchall()
		result = [{'tmdb_id': str(i[0]), 'title': str(i[1])} for i in result]
		return result

	def add(self, mediatype, tmdb_id, title):
		try:
			self.dbcur.execute(INSERT_DROP, ('tvshow', str(tmdb_id), title))
			return True
		except: return False

	def remove(self, mediatype, tmdb_id, title):
		try:
			self.dbcur.execute(DELETE_DROP, ('tvshow', str(tmdb_id)))
			return True
		except: return False

	def clear(self, mediatype):
		try:
			self.dbcur.execute(CLEAR_DROP, ('tvshow',))
			self.dbcur.execute("""VACUUM""")
			return True
		except: return False

def get_favorites(watched_info, mediatype, page_no, letter):
	paginate = settings.paginate()
	limit = settings.page_limit()
	data = Favorites().get(mediatype)
	data = sort_for_article(data, 'title', settings.ignore_articles())
	original_list = [{'media_id': i['tmdb_id'], 'title': i['title']} for i in data]
	if paginate: return paginate_list(original_list, page_no, letter, limit)
	return original_list, 1

def get_dropped(watched_info, mediatype, page_no, letter):
	paginate = settings.paginate()
	limit = settings.page_limit()
	data = Dropped().get(mediatype)
	data = sort_for_article(data, 'title', settings.ignore_articles())
	original_list = [{'media_id': i['tmdb_id'], 'title': i['title']} for i in data]
	if paginate: return paginate_list(original_list, page_no, letter, limit)
	return original_list, 1

def get_hidden_items(list_type):
	data = Dropped().get(list_type)
	return [int(i['tmdb_id']) for i in data]

