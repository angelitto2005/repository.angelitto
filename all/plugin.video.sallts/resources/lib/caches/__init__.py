import time
from datetime import datetime
from modules import kodi_utils
# logger = kodi_utils.logger

debridcache_db = kodi_utils.debridcache_db
favorites_db = kodi_utils.favorites_db
maincache_db = kodi_utils.maincache_db
metacache_db = kodi_utils.metacache_db
navigator_db = kodi_utils.navigator_db
views_db = kodi_utils.views_db
watched_db = kodi_utils.watched_db
database_connect = kodi_utils.database_connect
container_refresh = kodi_utils.container_refresh
get_property, set_property, clear_property = kodi_utils.get_property, kodi_utils.set_property, kodi_utils.clear_property

class BaseCache:
	db_file = ':memory:'

	def __init__(self):
		self.dbcon = database_connect(self.db_file, isolation_level=None)
		self.dbcur = self.dbcon.cursor()
		self._set_PRAGMAS()

	def _set_PRAGMAS(self):
		self.dbcur.execute("""PRAGMA synchronous = OFF""")
		self.dbcur.execute("""PRAGMA journal_mode = OFF""")

	def _get_timestamp(self, date_time):
		return int(time.mktime(date_time.timetuple()))

