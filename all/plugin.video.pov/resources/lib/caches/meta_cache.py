from datetime import datetime, timedelta
from caches import BaseCache, metacache_db, get_property, set_property, clear_property
# from modules.kodi_utils import logger

GET_MOVIE_SHOW = 'SELECT meta, expires FROM metadata WHERE db_type = ? AND %s = ? and expires > ?'
GET_SEASON = 'SELECT meta, expires FROM season_metadata WHERE tmdb_id = ? AND expires > ?'
GET_FUNCTION = 'SELECT data, expires FROM function_cache WHERE string_id = ? AND expires > ?'
GET_ALL = 'SELECT db_type, tmdb_id, meta FROM metadata'
SET_MOVIE_SHOW = 'INSERT OR REPLACE INTO metadata VALUES (?, ?, ?, ?, ?, ?)'
SET_SEASON = 'INSERT INTO season_metadata VALUES (?, ?, ?)'
SET_FUNCTION = 'INSERT INTO function_cache VALUES (?, ?, ?)'
DELETE_MOVIE_SHOW = 'DELETE FROM metadata WHERE db_type = ? AND %s = ?'
DELETE_SEASON = 'DELETE FROM season_metadata WHERE tmdb_id = ?'
DELETE_SEASONS = 'DELETE FROM season_metadata WHERE tmdb_id LIKE ?'
DELETE_FUNCTION = 'DELETE FROM function_cache WHERE string_id = ?'
DELETE_ALL = 'DELETE FROM %s'
movie_show, id_types = ('movie', 'tvshow'), ('tmdb_id', 'imdb_id', 'tvdb_id')
prop_dict = {'meta': 'pov_meta_%s_%s_%s', 'meta_season': 'pov_meta_season_%s'}

class MetaCache(BaseCache):
	db_file = metacache_db

	def _set_PRAGMAS(self):
		self.dbcur.executescript("""
			PRAGMA synchronous = OFF;
			PRAGMA journal_mode = OFF;
			PRAGMA mmap_size = 268435456;
		""")

	def get(self, mediatype, id_type, media_id):
		meta = None
		try:
			media_id = str(media_id)
			current_time = self._get_timestamp(datetime.now())
			cache_data = self.get_memory_cache(mediatype, id_type, media_id, current_time)
			if cache_data: return cache_data
			if mediatype in movie_show:
				self.dbcur.execute(GET_MOVIE_SHOW % id_type, (mediatype, media_id, current_time))
			else: self.dbcur.execute(GET_SEASON, (media_id, current_time))
			data = self.dbcur.fetchone()
			if not data: return meta
			meta, expiry = eval(data[0]), data[1]
			self.set_memory_cache(mediatype, id_type, meta, expiry, media_id)
		except: pass
		return meta

	def set(self, mediatype, id_type, meta, expiration=30, tmdb_id=None):
		try:
			if mediatype in movie_show:
				media_id, command = str(meta[id_type]), SET_MOVIE_SHOW
				args = mediatype, str(meta['tmdb_id']), meta['imdb_id'], str(meta['tvdb_id']), repr(meta)
			else:
				media_id, command = str(tmdb_id), SET_SEASON
				args = media_id, repr(meta)
			expires = datetime.now() + timedelta(days=expiration)
			expires = self._get_timestamp(datetime.combine(expires, datetime.min.time()))
			self.dbcur.execute(command, (*args, expires))
		except: return
		self.set_memory_cache(mediatype, id_type, meta, expires, media_id)

	def delete(self, mediatype, id_type, media_id, meta=None, dbcon=None):
		try:
			media_id = str(media_id)
			if mediatype in movie_show:
				self.dbcur.execute(DELETE_MOVIE_SHOW % id_type, (mediatype, media_id))
				for item in id_types: self.delete_memory_cache(mediatype, item, meta[item])
				if mediatype == 'tvshow': self.dbcur.execute(DELETE_SEASONS, (media_id + '%',))
			else:
				self.dbcur.execute(DELETE_SEASON, (media_id,))
				self.delete_memory_cache(mediatype, id_type, media_id)
		except: pass

	def get_memory_cache(self, mediatype, id_type, media_id, current_time):
		result = None
		try:
			media_id = str(media_id)
			if mediatype in movie_show: prop_string = prop_dict.get('meta') % (mediatype, id_type, media_id)
			else: prop_string = prop_dict.get('meta_season') % media_id
			cachedata = get_property(prop_string)
			if cachedata:
				cachedata = eval(cachedata)
				if cachedata[0] > current_time: result = cachedata[1]
		except: pass
		return result

	def set_memory_cache(self, mediatype, id_type, meta, expires, media_id):
		try:
			media_id = str(media_id)
			if mediatype in movie_show:
				cachedata, prop_string = (expires, meta), prop_dict.get('meta') % (mediatype, id_type, media_id)
			else: cachedata, prop_string = (expires, meta), prop_dict.get('meta_season') % media_id
			set_property(prop_string, repr(cachedata))
		except: pass

	def delete_memory_cache(self, mediatype, id_type, media_id):
		try:
			if mediatype in movie_show: clear_property(prop_dict.get('meta') % (mediatype, id_type, media_id))
			else: clear_property(prop_dict.get('meta_season') % media_id)
		except: pass

	def get_function(self, prop_string):
		result = None
		try:
			current_time = self._get_timestamp(datetime.now())
			self.dbcur.execute(GET_FUNCTION, (prop_string, current_time))
			cache_data = self.dbcur.fetchone()
			if cache_data: result = eval(cache_data[0])
		except: pass
		return result

	def set_function(self, prop_string, result, expiration):
		try:
			expires = self._get_timestamp(datetime.now() + expiration)
			self.dbcur.execute(SET_FUNCTION, (prop_string, repr(result), expires))
		except: pass

	def delete_all_seasons_memory_cache(self, media_id, total_seasons=None):
		if not total_seasons: total_seasons = 100
		for item in range(total_seasons + 1):
			clear_property('%s_%s' % (prop_dict.get('meta_season') % str(media_id), str(item)))

	def delete_all(self):
		try:
			self.dbcur.execute(GET_ALL)
			all_entries = self.dbcur.fetchall()
			for i in all_entries:
				try:
					mediatype, tmdb_id = str(i[0]), str(i[1])
					if mediatype == 'tvshow':
						total_seasons = eval(i[2]).get('total_seasons')
						self.delete_all_seasons_memory_cache(tmdb_id, total_seasons)
					self.delete_memory_cache(mediatype, 'tmdb_id', tmdb_id)
				except: pass
			for table in ('metadata', 'season_metadata', 'function_cache'):
				self.dbcur.execute(DELETE_ALL % table)
			self.dbcur.execute("""VACUUM""")
		except: pass

	def prefetch(self, limit=500):
		for db_type, tmdb_id, meta, expires in self.dbcur.execute("""
			SELECT db_type, tmdb_id, meta, expires
			FROM metadata
			WHERE tmdb_id IS NOT NULL
			ORDER BY expires DESC
			LIMIT ?
		""", (limit,)):
			try: self.set_memory_cache(db_type, 'tmdb_id', eval(meta), expires, tmdb_id)
			except: pass
		for i in (self.dbcur, self.dbcon): i.close()

def cache_function(function, prop_string, url, expiration=96, json=False):
	metacache = MetaCache()
	data = metacache.get_function(prop_string)
	if data: return data
	if json: result = function(url).json()
	else: result = function(url)
	if isinstance(expiration, (int, float)): expiration = timedelta(hours=expiration)
	metacache.set_function(prop_string, result, expiration)
	return result

