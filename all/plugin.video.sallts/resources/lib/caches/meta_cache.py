from datetime import datetime, timedelta
from caches import BaseCache, metacache_db, get_property, set_property, clear_property
# from modules.kodi_utils import logger

all_tables = ('metadata', 'season_metadata', 'function_cache')
movie_show = ('movie', 'tvshow')
id_types = ('tmdb_id', 'imdb_id', 'tvdb_id')
GET_MOVIE_SHOW = 'SELECT meta, expires FROM metadata WHERE db_type = ? AND %s = ?'
GET_SEASON = 'SELECT meta, expires FROM season_metadata WHERE tmdb_id = ?'
GET_FUNCTION = 'SELECT string_id, data, expires FROM function_cache WHERE string_id = ?'
GET_ALL = 'SELECT db_type, tmdb_id FROM metadata'
SET_MOVIE_SHOW = 'INSERT OR REPLACE INTO metadata VALUES (?, ?, ?, ?, ?, ?)'
SET_SEASON = 'INSERT INTO season_metadata VALUES (?, ?, ?)'
SET_FUNCTION = 'INSERT INTO function_cache VALUES (?, ?, ?)'
DELETE_MOVIE_SHOW = 'DELETE FROM metadata WHERE db_type = ? AND %s = ?'
DELETE_SEASON = 'DELETE FROM season_metadata WHERE tmdb_id = ?'
DELETE_SEASONS = 'DELETE FROM season_metadata WHERE tmdb_id LIKE ?'
DELETE_FUNCTION = 'DELETE FROM function_cache WHERE string_id = ?'
DELETE_ALL = 'DELETE FROM %s'
string = str

class MetaCache(BaseCache):
	db_file = metacache_db

	def _set_PRAGMAS(self):
		self.dbcur.execute("""PRAGMA synchronous = OFF""")
		self.dbcur.execute("""PRAGMA journal_mode = OFF""")
		self.dbcur.execute("""PRAGMA mmap_size = 268435456""")

	def get(self, mediatype, id_type, media_id):
		meta = None
		try:
			media_id = string(media_id)
			current_time = self._get_timestamp(datetime.now())
			meta = self.get_memory_cache(mediatype, id_type, media_id, current_time)
			if meta is None:
				if mediatype in movie_show:
					self.dbcur.execute(GET_MOVIE_SHOW % id_type, (mediatype, media_id))
				else: self.dbcur.execute(GET_SEASON, (media_id,))
				cache_data = self.dbcur.fetchone()
				if cache_data:
					meta, expiry = eval(cache_data[0]), cache_data[1]
					if expiry < current_time:
						self.delete(mediatype, id_type, media_id, meta=meta, dbcon=None)
						meta = None
					else: self.set_memory_cache(mediatype, id_type, meta, expiry, media_id)
		except: pass
		return meta

	def set(self, mediatype, id_type, meta, expiration=30, tmdb_id=None):
		try:
			expires = self._get_timestamp(datetime.now() + timedelta(days=expiration))
			if mediatype in movie_show:
				media_id, command = string(meta[id_type]), SET_MOVIE_SHOW
				args = mediatype, string(meta['tmdb_id']), meta['imdb_id'], string(meta['tvdb_id']), repr(meta)
			else:
				media_id, command = string(tmdb_id), SET_SEASON
				args = media_id, repr(meta)
			self.dbcur.execute(command, (*args, expires))
		except: return None
		self.set_memory_cache(mediatype, id_type, meta, expires, media_id)

	def delete(self, mediatype, id_type, media_id, meta=None, dbcon=None):
		try:
			media_id = string(media_id)
			if mediatype in movie_show:
				self.dbcur.execute(DELETE_MOVIE_SHOW % id_type, (mediatype, media_id))
				for item in id_types: self.delete_memory_cache(mediatype, item, meta[item])
				if mediatype == 'tvshow': self.dbcur.execute(DELETE_SEASONS, (media_id+'%',))
			else:
				self.dbcur.execute(DELETE_SEASON, (media_id,))
				self.delete_memory_cache(mediatype, id_type, media_id)
		except: return

	def get_memory_cache(self, mediatype, id_type, media_id, current_time):
		result = None
		try:
			if mediatype in movie_show: prop_string = 'salts_%s_%s_%s' % (mediatype, id_type, media_id)
			else: prop_string = 'salts_meta_season_%s' % media_id
			cachedata = get_property(prop_string)
			if cachedata:
				cachedata = eval(cachedata)
				if cachedata[0] > current_time: result = cachedata[1]
		except: pass
		return result

	def set_memory_cache(self, mediatype, id_type, meta, expires, media_id):
		try:
			media_id = string(media_id)
			if mediatype in movie_show: cachedata, prop_string = (expires, meta), 'salts_%s_%s_%s' % (mediatype, id_type, string(media_id))
			else: cachedata, prop_string = (expires, meta), 'salts_meta_season_%s' % string(media_id)
			set_property(prop_string, repr(cachedata))
		except: pass

	def delete_memory_cache(self, mediatype, id_type, media_id):
		try:
			if mediatype in movie_show: clear_property('salts_%s_%s_%s' % (mediatype, id_type, media_id))
			else: clear_property('salts_meta_season_%s' % media_id)
		except: pass

	def get_function(self, prop_string):
		result = None
		try:
			current_time = self._get_timestamp(datetime.now())
			self.dbcur.execute(GET_FUNCTION, (prop_string,))
			cache_data = self.dbcur.fetchone()
			if cache_data and cache_data[2] > current_time: result = eval(cache_data[1])
			else: self.dbcur.execute(DELETE_FUNCTION, (prop_string,))
		except: pass
		return result

	def set_function(self, prop_string, result, expiration=timedelta(days=1)):
		try:
			expires = self._get_timestamp(datetime.now() + expiration)
			self.dbcur.execute(SET_FUNCTION, (prop_string, repr(result), expires))
		except: return

	def delete_all_seasons_memory_cache(self, media_id):
		for item in range(1, 51): clear_property('salts_meta_season_%s_%s' % (string(media_id), string(item)))

	def delete_all(self):
		try:
			self.dbcur.execute(GET_ALL)
			all_entries = self.dbcur.fetchall()
			for i in all_tables: self.dbcur.execute(DELETE_ALL % i)
			self.dbcur.execute("""VACUUM""")
			for i in all_entries:
				try:
					tmdb_id = string(i[1])
					self.delete_memory_cache(str(i[0]), 'tmdb_id', tmdb_id)
					self.delete_all_seasons_memory_cache(tmdb_id)
				except: pass
		except: return

def cache_function(function, prop_string, url, expiration=96, json=False):
	metacache = MetaCache()
	data = metacache.get_function(prop_string)
	if data: return data
	if json: result = function(url).json()
	else: result = function(url)
	metacache.set_function(prop_string, result, expiration=timedelta(hours=expiration))
	return result

