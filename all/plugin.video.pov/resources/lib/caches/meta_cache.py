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
movie_show = ('movie', 'tvshow')

def prop_get(value, *args):
	if value == 'meta_season': return 'pov_meta_season_%s' % args
	if value == 'meta': return 'pov_meta_%s_%s_%s' % args
	return ''.join(args)

class MetaCache(BaseCache):
	db_file = metacache_db

	def _set_PRAGMAS(self):
		self.dbcur.execute("""PRAGMA synchronous = OFF""")
		self.dbcur.execute("""PRAGMA journal_mode = OFF""")
		self.dbcur.execute("""PRAGMA mmap_size = 268435456""")

	def get(self, mediatype, id_type, media_id):
		media_str = str(media_id)
		current_time = self._get_timestamp(datetime.now())
		cache_data = self.get_memory_cache(mediatype, id_type, media_str, current_time)
		if cache_data: return cache_data
		if mediatype in movie_show:
			command, args = GET_MOVIE_SHOW % id_type, (mediatype, media_str, current_time)
		else: command, args = GET_SEASON, (media_str, current_time)
		self.dbcur.execute(command, args)
		data = self.dbcur.fetchone()
		if not data: return None
		meta, expiry = self.jsloads(data[0]), data[1]
		self.set_memory_cache(mediatype, id_type, meta, expiry, media_str)
		return meta

	def set(self, mediatype, id_type, meta, expiration=30, tmdb_id=None):
		expires = datetime.now() + timedelta(days=expiration)
		expires = self._get_timestamp(datetime.combine(expires, datetime.min.time()))
		if mediatype in movie_show:
			media_str, command = str(meta[id_type]), SET_MOVIE_SHOW
			args = mediatype, str(meta['tmdb_id']), meta['imdb_id'], str(meta['tvdb_id']), expires
		else:
			media_str, command = str(tmdb_id), SET_SEASON
			args = media_str, expires
		self.dbcur.execute(command, (*args, self.jsdumps(meta)))
		self.set_memory_cache(mediatype, id_type, meta, expires, media_str)

	def delete(self, mediatype, id_type, media_id, meta=None, dbcon=None):
		media_str = str(media_id)
		if mediatype in movie_show:
			self.dbcur.execute(DELETE_MOVIE_SHOW % id_type, (mediatype, media_str))
			for item in ('tmdb_id', 'imdb_id', 'tvdb_id'):
				self.delete_memory_cache(mediatype, item, meta[item])
			if mediatype == 'tvshow': self.dbcur.execute(DELETE_SEASONS, (media_str + '%',))
		else:
			self.dbcur.execute(DELETE_SEASON, (media_str,))
			self.delete_memory_cache(mediatype, id_type, media_str)

	def get_memory_cache(self, mediatype, id_type, media_id, current_time):
		media_str = str(media_id)
		if mediatype in movie_show: prop_string = prop_get('meta', mediatype, id_type, media_str)
		else: prop_string = prop_get('meta_season', media_str)
		cache_data = get_property(prop_string)
		if not cache_data: return None
		expiry, meta = self.jsloads(cache_data)
		if expiry < current_time: return None
		return meta

	def set_memory_cache(self, mediatype, id_type, meta, expires, media_id):
		media_str = str(media_id)
		if mediatype in movie_show: prop_string = prop_get('meta', mediatype, id_type, media_str)
		else: prop_string = prop_get('meta_season', media_str)
		cache_data = (expires, meta)
		set_property(prop_string, self.jsdumps(cache_data))

	def delete_memory_cache(self, mediatype, id_type, media_id):
		if mediatype in movie_show: clear_property(prop_get('meta', mediatype, id_type, media_id))
		else: clear_property(prop_get('meta_season', media_id))

	def get_function(self, prop_string):
		current_time = self._get_timestamp(datetime.now())
		self.dbcur.execute(GET_FUNCTION, (prop_string, current_time))
		cache_data = self.dbcur.fetchone()
		if not cache_data: return None
		return self.jsloads(cache_data[0])

	def set_function(self, prop_string, result, expiration):
		expires = self._get_timestamp(datetime.now() + expiration)
		self.dbcur.execute(SET_FUNCTION, (prop_string, expires, self.jsdumps(result)))

	def delete_all_seasons_memory_cache(self, media_id, total_seasons=None):
		if isinstance(total_seasons, str): total_seasons = self.jsloads(total_seasons)
		if isinstance(total_seasons, dict): total_seasons = total_seasons.get('total_seasons')
		if not isinstance(total_seasons, int): total_seasons = 100
		prop_string = prop_get('meta_season', str(media_id))
		for item in range(total_seasons + 1): clear_property('%s_%s' % (prop_string, str(item)))

	def delete_all(self):
		self.dbcur.execute(GET_ALL)
		all_entries = self.dbcur.fetchall()
		for i in all_entries:
			try:
				mediatype, tmdb_id = str(i[0]), str(i[1])
				if mediatype == 'tvshow':
					self.delete_all_seasons_memory_cache(tmdb_id, i[2])
				self.delete_memory_cache(mediatype, 'tmdb_id', tmdb_id)
			except: pass
		for table in ('metadata', 'season_metadata', 'function_cache'):
			self.dbcur.execute(DELETE_ALL % table)
		self.dbcur.execute("""VACUUM""")

	def prefetch(self, limit=500):
		command = 'SELECT db_type, tmdb_id, meta, expires FROM metadata ORDER BY expires DESC LIMIT ?'
		for db_type, tmdb_id, meta, expires in self.dbcur.execute(command, (limit,)).fetchall():
			try: self.set_memory_cache(db_type, 'tmdb_id', self.jsloads(meta), expires, tmdb_id)
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

