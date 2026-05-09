from modules import kodi_utils
# logger = kodi_utils.logger

ls = kodi_utils.local_string
navigator_db = kodi_utils.navigator_db
watched_db = kodi_utils.watched_db
favorites_db = kodi_utils.favorites_db
views_db = kodi_utils.views_db
trakt_db = kodi_utils.trakt_db
mdbl_db = kodi_utils.mdbl_db
maincache_db = kodi_utils.maincache_db
metacache_db = kodi_utils.metacache_db
debridcache_db = kodi_utils.debridcache_db
external_db = kodi_utils.external_db
current_dbs = kodi_utils.current_dbs
databases_path = kodi_utils.databases_path
packages_path = kodi_utils.packages_path
database_connect = kodi_utils.database_connect

def check_databases():
	if not kodi_utils.path_exists(databases_path): kodi_utils.make_directory(databases_path)
	dbcon = database_connect(maincache_db) # Main Cache
	dbcon.execute("""CREATE TABLE IF NOT EXISTS maincache (id text unique, data text, expires integer)""")
	dbcon.close()
	dbcon = database_connect(navigator_db) # Navigator
	dbcon.execute("""CREATE TABLE IF NOT EXISTS navigator
					(list_name text, list_type text, list_contents text, unique (list_name, list_type))""")
	dbcon.close()
	dbcon = database_connect(metacache_db) # Meta Cache
	dbcon.execute("""CREATE TABLE IF NOT EXISTS metadata
					(db_type text not null, tmdb_id text not null, imdb_id text, tvdb_id text, meta text, expires integer, unique (db_type, tmdb_id))""")
	dbcon.execute("""CREATE TABLE IF NOT EXISTS season_metadata (tmdb_id text not null unique, meta text, expires integer)""")
	dbcon.execute("""CREATE TABLE IF NOT EXISTS function_cache (string_id text not null, data text, expires integer)""")
	dbcon.execute("""CREATE INDEX IF NOT EXISTS pov_select_id_media ON metadata (tmdb_id, db_type)""")
	dbcon.close()
	dbcon = database_connect(watched_db) # Watched Status
	dbcon.execute("""CREATE TABLE IF NOT EXISTS watched_status
					(db_type text, media_id text, season integer, episode integer, last_played text, title text, unique (db_type, media_id, season, episode))""")
	dbcon.execute("""CREATE TABLE IF NOT EXISTS progress
					(db_type text, media_id text, season integer, episode integer, resume_point text, curr_time text,
					last_played text, resume_id integer, title text, unique (db_type, media_id, season, episode))""")
	dbcon.execute("""CREATE INDEX IF NOT EXISTS pov_ws_in_progress_episodes ON watched_status (db_type, media_id, season DESC, episode DESC)""")
	dbcon.close()
	dbcon = database_connect(favorites_db) # Favorites
	dbcon.execute("""CREATE TABLE IF NOT EXISTS favorites (db_type text, tmdb_id text, title text, unique (db_type, tmdb_id))""")
	dbcon.execute("""CREATE TABLE IF NOT EXISTS dropped (db_type text, tmdb_id text, title text, unique (db_type, tmdb_id))""")
	dbcon.close()
	dbcon = database_connect(views_db) # Views
	dbcon.execute("""CREATE TABLE IF NOT EXISTS views (view_type text, view_id text, unique (view_type))""")
	dbcon.close()
	dbcon = database_connect(debridcache_db) # Debrid Cache
	dbcon.execute("""CREATE TABLE IF NOT EXISTS debrid_data (hash text not null, debrid text not null, cached text, expires integer, unique (hash, debrid))""")
	dbcon.close()
	dbcon = database_connect(external_db) # External Providers Cache
	dbcon.execute("""CREATE TABLE IF NOT EXISTS results_data
					(provider text, db_type text, tmdb_id text, title text, year integer, season text, episode text, results text,
					expires integer, unique (provider, db_type, tmdb_id, title, year, season, episode))""")
	dbcon.close()
	dbcon = database_connect(trakt_db) # Trakt
	dbcon.execute("""CREATE TABLE IF NOT EXISTS trakt_data (id text unique, data text)""")
	dbcon.execute("""CREATE TABLE IF NOT EXISTS watched_status
					(db_type text, media_id text, season integer, episode integer, last_played text, title text, unique (db_type, media_id, season, episode))""")
	dbcon.execute("""CREATE TABLE IF NOT EXISTS progress
					(db_type text, media_id text, season integer, episode integer, resume_point text, curr_time text,
					last_played text, resume_id integer, title text, unique (db_type, media_id, season, episode))""")
	dbcon.execute("""CREATE INDEX IF NOT EXISTS pov_ws_in_progress_episodes ON watched_status (db_type, media_id, season DESC, episode DESC)""")
	dbcon.close()
	dbcon = database_connect(mdbl_db) # MDBList
	dbcon.execute("""CREATE TABLE IF NOT EXISTS mdbl_data (id text unique, data text)""")
	dbcon.execute("""CREATE TABLE IF NOT EXISTS watched_status
					(db_type text, media_id text, season integer, episode integer, last_played text, title text, unique (db_type, media_id, season, episode))""")
	dbcon.execute("""CREATE TABLE IF NOT EXISTS progress
					(db_type text, media_id text, season integer, episode integer, resume_point text, curr_time text,
					last_played text, resume_id integer, title text, unique (db_type, media_id, season, episode))""")
	dbcon.execute("""CREATE INDEX IF NOT EXISTS pov_ws_in_progress_episodes ON watched_status (db_type, media_id, season DESC, episode DESC)""")
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
		if '.pov' in item and item.endswith('zip'):
			try: kodi_utils.delete_file(packages_path + item)
			except: pass

def clean_databases(current_time=None, database_check=True, silent=False):
	if database_check: check_databases()
	if not current_time: from datetime import datetime
	current_time = current_time or int(datetime.now().timestamp())
	for db, table in (
		(maincache_db, 'maincache'),
		(external_db, 'results_data'),
		(debridcache_db, 'debrid_data'),
		(metacache_db, 'function_cache'),
		(metacache_db, 'season_metadata'),
		(metacache_db, 'metadata')
	): purge_database(db, table, current_time)
	dbcon = database_connect(watched_db, isolation_level=None)
	dbcon.execute("""VACUUM""")
	dbcon.close()
	limit_metacache_database()
	remove_old_databases()
	remove_old_packages()
	if not silent: kodi_utils.notification(32576, 1500)

def purge_database(db, table, expiry):
	dbcon = database_connect(db)
	dbcur = dbcon.cursor()
	dbcur.execute("""PRAGMA synchronous = OFF""")
	dbcur.execute("""PRAGMA journal_mode = OFF""")
	dbcur.execute("""DELETE FROM %s WHERE expires <= ?""" % table, (expiry,))
	dbcon.commit()
	dbcur.execute("""VACUUM""")

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
		from debrids.easynews_api import clear_media_results_database
		clear_media_results_database()
		items = 'ad_cloud', 'pm_cloud', 'rd_cloud', 'tb_cloud', 'oc_cloud'
		for item in items: clear_cache(item, silent=True)
	elif cache_type == 'external_scrapers':
		if not _confirm(): return
		from caches.providers_cache import ExternalProvidersCache
		from caches.debrid_cache import DebridCache
		data = ExternalProvidersCache().delete_cache()
		debrid_cache = DebridCache().clear_database()
		success = (data, debrid_cache) == ('success', 'success')
	elif cache_type == 'trakt':
		if not _confirm(): return
		from caches.trakt_cache import clear_all_trakt_cache_data
		success = clear_all_trakt_cache_data()
	elif cache_type == 'mdblist':
		if not _confirm(): return
		from caches.mdbl_cache import clear_all_mdbl_cache_data
		success = clear_all_mdbl_cache_data()
	elif cache_type == 'tmdblist':
		if not _confirm(): return
		from indexers.tmdb_api import clear_tmdbl_cache
		success = clear_tmdbl_cache()
	elif cache_type == 'imdb':
		if not _confirm(): return
		from indexers.imdb_api import clear_imdb_cache
		success = clear_imdb_cache()
	elif cache_type == 'ad_cloud':
		if not _confirm(): return
		from debrids.alldebrid_api import AllDebridAPI
		success = AllDebridAPI().clear_cache()
	elif cache_type == 'pm_cloud':
		if not _confirm(): return
		from debrids.premiumize_api import PremiumizeAPI
		success = PremiumizeAPI().clear_cache()
	elif cache_type == 'rd_cloud':
		if not _confirm(): return
		from debrids.real_debrid_api import RealDebridAPI
		success = RealDebridAPI().clear_cache()
	elif cache_type == 'tb_cloud':
		if not _confirm(): return
		from debrids.torbox_api import TorBoxAPI
		success = TorBoxAPI().clear_cache()
	elif cache_type == 'oc_cloud':
		if not _confirm(): return
		from debrids.offcloud_api import OffcloudAPI
		success = OffcloudAPI().clear_cache()
	else: # 'list'
		if not _confirm(): return
		from caches.main_cache import MainCache
		MainCache().delete_all_lists()
	if not silent and success: kodi_utils.notification(32576, 1500)

def clear_all_cache():
	if not kodi_utils.confirm_dialog(): return
	line = '[CR]%s: [B]%s %s[/B]'
	caches = (
		('external_scrapers', ls(32118)), ('internal_scrapers', ls(32096)),
		('trakt', ls(32037)), ('mdblist', 'MDBList'), ('tmdblist', 'TMDBList'),
		('imdb', ls(32064)), ('list', ls(32815)), ('meta', ls(32527))
	)
	len_caches = len(caches)
	kodi_utils.progressDialog.create('POV', '')
	for count, (cache_type, cache_label) in enumerate(caches, 1):
		try:
			if kodi_utils.progressDialog.iscanceled(): break
			args = int(count / len_caches * 100), line % (ls(32816), cache_label, ls(32524))
			kodi_utils.progressDialog.update(*args)
			clear_cache(cache_type, silent=True)
			kodi_utils.sleep(200)
		except: kodi_utils.notification(32574, 1500)
	kodi_utils.progressDialog.close()

