from modules import kodi_utils
# logger = kodi_utils.logger

ls = kodi_utils.local_string
navigator_db = kodi_utils.navigator_db
watched_db = kodi_utils.watched_db
favorites_db = kodi_utils.favorites_db
views_db = kodi_utils.views_db
trakt_db = kodi_utils.trakt_db
mdbl_db = kodi_utils.mdbl_db
flickl_db = kodi_utils.flickl_db
maincache_db = kodi_utils.maincache_db
metacache_db = kodi_utils.metacache_db
debridcache_db = kodi_utils.debridcache_db
current_dbs = kodi_utils.current_dbs
databases_path = kodi_utils.databases_path
packages_path = kodi_utils.packages_path
database_connect = kodi_utils.database_connect

def check_databases():
	if not kodi_utils.path_exists(databases_path): kodi_utils.make_directory(databases_path)
	dbcon = database_connect(navigator_db) # Navigator
	dbcon.execute("""CREATE TABLE IF NOT EXISTS navigator
					(list_name text, list_type text, list_contents text, unique(list_name, list_type))""")
	dbcon.close()
	dbcon = database_connect(watched_db) # Watched Status
	dbcon.execute("""CREATE TABLE IF NOT EXISTS watched_status
					(db_type text, media_id text, season integer, episode integer, last_played text, title text, unique(db_type, media_id, season, episode))""")
	dbcon.execute("""CREATE TABLE IF NOT EXISTS progress
					(db_type text, media_id text, season integer, episode integer, resume_point text, curr_time text,
					last_played text, resume_id integer, title text, unique(db_type, media_id, season, episode))""")
	dbcon.close()
	dbcon = database_connect(favorites_db) # Favorites
	dbcon.execute("""CREATE TABLE IF NOT EXISTS favorites (db_type text, tmdb_id text, title text, unique (db_type, tmdb_id))""")
	dbcon.close()
	dbcon = database_connect(views_db) # Views
	dbcon.execute("""CREATE TABLE IF NOT EXISTS views (view_type text, view_id text, unique (view_type))""")
	dbcon.close()
	dbcon = database_connect(maincache_db) # Main Cache
	dbcon.execute("""CREATE TABLE IF NOT EXISTS maincache (id text unique, data text, expires integer)""")
	dbcon.close()
	dbcon = database_connect(metacache_db) # Meta Cache
	dbcon.execute("""CREATE TABLE IF NOT EXISTS metadata
					(db_type text not null, tmdb_id text not null, imdb_id text, tvdb_id text, meta text, expires integer, unique (db_type, tmdb_id))""")
	dbcon.execute("""CREATE TABLE IF NOT EXISTS season_metadata (tmdb_id text not null unique, meta text, expires integer)""")
	dbcon.execute("""CREATE TABLE IF NOT EXISTS function_cache (string_id text not null, data text, expires integer)""")
	dbcon.execute("""CREATE INDEX IF NOT EXISTS salts_select_id_media ON metadata (tmdb_id, db_type)""")
	dbcon.close()
	dbcon = database_connect(debridcache_db) # Debrid Cache
	dbcon.execute("""CREATE TABLE IF NOT EXISTS debrid_data (hash text not null, debrid text not null, cached text, expires integer, unique (hash, debrid))""")
	dbcon.close()
	dbcon = database_connect(trakt_db) # Trakt
	dbcon.execute("""CREATE TABLE IF NOT EXISTS trakt_data (id text unique, data text)""")
	dbcon.execute("""CREATE TABLE IF NOT EXISTS watched_status
					(db_type text, media_id text, season integer, episode integer, last_played text, title text, unique(db_type, media_id, season, episode))""")
	dbcon.execute("""CREATE TABLE IF NOT EXISTS progress
					(db_type text, media_id text, season integer, episode integer, resume_point text, curr_time text,
					last_played text, resume_id integer, title text, unique(db_type, media_id, season, episode))""")
	dbcon.close()
	dbcon = database_connect(mdbl_db) # MDBList
	dbcon.execute("""CREATE TABLE IF NOT EXISTS mdbl_data (id text unique, data text)""")
	dbcon.execute("""CREATE TABLE IF NOT EXISTS watched_status
					(db_type text, media_id text, season integer, episode integer, last_played text, title text, unique(db_type, media_id, season, episode))""")
	dbcon.execute("""CREATE TABLE IF NOT EXISTS progress
					(db_type text, media_id text, season integer, episode integer, resume_point text, curr_time text,
					last_played text, resume_id integer, title text, unique(db_type, media_id, season, episode))""")
	dbcon.close()
	dbcon = database_connect(flickl_db) # FlickList
	dbcon.execute("""CREATE TABLE IF NOT EXISTS flickl_data (id text unique, data text)""")
	dbcon.execute("""CREATE TABLE IF NOT EXISTS watched_status
					(db_type text, media_id text, season integer, episode integer, last_played text, title text, unique(db_type, media_id, season, episode))""")
	dbcon.execute("""CREATE TABLE IF NOT EXISTS progress
					(db_type text, media_id text, season integer, episode integer, resume_point text, curr_time text,
					last_played text, resume_id integer, title text, unique(db_type, media_id, season, episode))""")
	dbcon.close()

def remove_old_databases():
	files = kodi_utils.list_dirs(databases_path)[1]
	for item in files:
		if item not in current_dbs:
			try: kodi_utils.delete_file(databases_path + item)
			except: pass

def remove_old_packages():
	files = kodi_utils.list_dirs(packages_path)[1]
	for item in files:
		if '.sallts' in item and item.endswith('zip'):
			try: kodi_utils.delete_file(packages_path + item)
			except: pass

def clean_databases(current_time=None, database_check=True, silent=False):
	remove_old_packages()
	remove_old_databases()
	if database_check: check_databases()
	current_time = current_time or get_current_time()
	command_base = """DELETE from %s WHERE CAST(%s AS INT) <= ?"""
	for db, sql in (
		(debridcache_db, command_base % ('debrid_data', 'expires')),
		(maincache_db, command_base % ('maincache', 'expires')),
		(metacache_db, command_base % ('metadata', 'expires')),
		(metacache_db, command_base % ('function_cache', 'expires')),
		(metacache_db, command_base % ('season_metadata', 'expires'))
	):
		try:
			dbcon = database_connect(db)
			dbcur = dbcon.cursor()
			dbcur.execute("""PRAGMA synchronous = OFF""")
			dbcur.execute("""PRAGMA journal_mode = OFF""")
			dbcur.execute(sql, (current_time,))
			dbcon.commit()
			dbcur.execute("""VACUUM""")
		except: pass
	limit_metacache_database()
	if not silent: kodi_utils.notification(32576, 1500)

def limit_metacache_database(max_size=50):
	with kodi_utils.open_file(metacache_db) as f: fsize = f.size()
	size = round(float(fsize)/1048576, 1)
	if size < max_size: return
	dbcon = database_connect(metacache_db)
	dbcur = dbcon.cursor()
	dbcur.execute("""PRAGMA synchronous = OFF""")
	dbcur.execute("""PRAGMA journal_mode = OFF""")
	dbcur.execute("""DELETE FROM metadata WHERE ROWID IN (SELECT ROWID FROM metadata ORDER BY ROWID DESC LIMIT -1 OFFSET 4000)""")
	dbcur.execute("""DELETE FROM function_cache WHERE ROWID IN (SELECT ROWID FROM function_cache ORDER BY ROWID DESC LIMIT -1 OFFSET 100)""")
	dbcur.execute("""DELETE FROM season_metadata WHERE ROWID IN (SELECT ROWID FROM season_metadata ORDER BY ROWID DESC LIMIT -1 OFFSET 100)""")
	dbcon.commit()
	dbcur.execute("""VACUUM""")

def get_current_time():
	import time, datetime
	return int(time.mktime(datetime.datetime.now().timetuple()))

def clear_cache(cache_type, silent=False):
	def _confirm():
		return silent or kodi_utils.confirm_dialog()
	success = True
	if cache_type == 'meta':
		if not _confirm(): return
		from caches.meta_cache import MetaCache
		MetaCache().delete_all()
	elif cache_type == 'internal_scrapers':
		if not _confirm(): return
		items = 'pm_cloud', 'rd_cloud', 'tb_cloud'
		for item in items: clear_cache(item, silent=True)
	elif cache_type == 'trakt':
		if not _confirm(): return
		from caches.trakt_cache import clear_all_trakt_cache_data
		success = clear_all_trakt_cache_data()
	elif cache_type == 'mdblist':
		if not _confirm(): return
		from caches.mdbl_cache import clear_all_mdbl_cache_data
		success = clear_all_mdbl_cache_data()
	elif cache_type == 'flicklist':
		if not _confirm(): return
		from caches.flicklist_cache import clear_all_flicklist_cache_data
		success = clear_all_flicklist_cache_data()
	elif cache_type == 'imdb':
		if not _confirm(): return
		from indexers.imdb_api import clear_imdb_cache
		success = clear_imdb_cache()
	elif cache_type == 'pm_cloud':
		if not _confirm(): return
		from debrids.premiumize_api import PremiumizeAPI
		success = PremiumizeAPI().clear_cache()
	elif cache_type == 'rd_cloud':
		if not _confirm(): return
		from debrids.realdebrid_api import RealDebridAPI
		success = RealDebridAPI().clear_cache()
	elif cache_type == 'tb_cloud':
		if not _confirm(): return
		from debrids.torbox_api import TorBoxAPI
		success = TorBoxAPI().clear_cache()
	else: # 'list'
		if not _confirm(): return
		from caches.main_cache import MainCache
		MainCache().delete_all_lists()
	if not silent and success: kodi_utils.notification(32576, 1500)

def clear_all_cache():
	if not kodi_utils.confirm_dialog(): return
	line = '[CR]%s: [B]%s[/B]'
	caches = (
		('meta', '%s %s' % (ls(32527), ls(32524))),
		('list', '%s %s' % (ls(32815), ls(32524))),
		('trakt', ls(32087)),
		('mdblist', 'MDBList'),
		('flicklist', 'FlickList'),
		('imdb', '%s %s' % (ls(32064), ls(32524))),
		('internal_scrapers', '%s %s' % (ls(32096), ls(32524)))
	)
	len_caches = len(caches)
	kodi_utils.progressDialog.create('SALTS', '')
	for count, (cache_type, cache_label) in enumerate(caches, 1):
		try:
			if kodi_utils.progressDialog.iscanceled(): break
			kodi_utils.progressDialog.update(int(count / len_caches * 100), line % (ls(32816), cache_label))
			clear_cache(cache_type, silent=True)
			kodi_utils.sleep(200)
		except: kodi_utils.notification(32574, 1500)
	kodi_utils.progressDialog.close()

