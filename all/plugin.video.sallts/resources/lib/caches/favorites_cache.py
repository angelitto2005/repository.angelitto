from caches import BaseCache, favorites_db, container_refresh
from modules import settings
from modules.utils import sort_for_article, paginate_list
# from modules.kodi_utils import logger

INSERT_FAV = 'INSERT INTO favorites VALUES (?, ?, ?)'
DELETE_FAV = 'DELETE FROM favorites WHERE db_type = ? and tmdb_id = ?'
SELECT_FAV = 'SELECT tmdb_id, title FROM favorites WHERE db_type = ?'
CLEAR_FAV = 'DELETE FROM favorites WHERE db_type = ?'

class Favorites(BaseCache):
	db_file = favorites_db

	def add_to_favorites(self, mediatype, tmdb_id, title):
		try:
			self.dbcur.execute(INSERT_FAV, (mediatype, str(tmdb_id), title))
			return True
		except: return False

	def remove_from_favorites(self, mediatype, tmdb_id, title):
		try:
			self.dbcur.execute(DELETE_FAV, (mediatype, str(tmdb_id)))
			container_refresh()
			return True
		except: return False

	def get_favorites(self, mediatype):
		self.dbcur.execute(SELECT_FAV, (mediatype,))
		result = self.dbcur.fetchall()
		result = [{'tmdb_id': str(i[0]), 'title': str(i[1])} for i in result]
		return result

	def clear_favorites(self, mediatype):
		try:
			self.dbcur.execute(CLEAR_FAV, (mediatype,))
			self.dbcur.execute("""VACUUM""")
			return True
		except: return False

favorites_cache = Favorites()

def get_favorites(mediatype, page_no, letter):
	paginate = settings.paginate()
	limit = settings.page_limit()
	data = favorites_cache.get_favorites(mediatype)
	data = sort_for_article(data, 'title', settings.ignore_articles())
	original_list = [{'media_id': i['tmdb_id'], 'title': i['title']} for i in data]
	if paginate: final_list, total_pages = paginate_list(original_list, page_no, letter, limit)
	else: final_list, total_pages = original_list, 1
	return final_list, total_pages

