import json
from datetime import datetime
from threading import Thread
from indexers import metadata
from indexers.flicklist_api import flicklist_watched_unwatched, flicklist_progress
from indexers.mdblist_api import mdbl_watched_unwatched, mdbl_progress
from indexers.trakt_api import trakt_watched_unwatched, trakt_official_status, trakt_progress
from caches.flicklist_cache import clear_flicklist_collection_watchlist_data
from caches.mdbl_cache import clear_mdbl_collection_watchlist_data
from caches.trakt_cache import clear_trakt_collection_watchlist_data
from modules import kodi_utils, settings, utils
# logger = kodi_utils.logger

timeout = 20
ls, sleep = kodi_utils.local_string, kodi_utils.sleep
progressDialogBG, execJSONRPC = kodi_utils.progressDialogBG, kodi_utils.execJSONRPC
get_datetime, adjust_premiered_date = utils.get_datetime, utils.adjust_premiered_date
sort_for_article, make_thread_list, TaskPool = utils.sort_for_article, utils.make_thread_list, utils.TaskPool
clean_file_name, paginate_list = utils.clean_file_name, utils.paginate_list
WATCHED_DB, TRAKT_DB = kodi_utils.watched_db, kodi_utils.trakt_db
MDBL_DB, FLICKL_DB = kodi_utils.mdbl_db, kodi_utils.flickl_db
indicators_dict = {0: WATCHED_DB, 1: TRAKT_DB, 2: MDBL_DB, 3: FLICKL_DB}

def _database_connect(database_file):
	return kodi_utils.database_connect(database_file, timeout=timeout, isolation_level=None)

def set_PRAGMAS(dbcon):
	dbcur = dbcon.cursor()
	dbcur.execute("""PRAGMA synchronous = OFF""")
	dbcur.execute("""PRAGMA journal_mode = OFF""")
	return dbcur

def get_database(watched_indicators):
	return indicators_dict[watched_indicators]

def get_next_episodes(watched_info):
	seen = set()
	watched_info = [i for i in watched_info if not i[0] is None]
	watched_info.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
	return [
		{'media_ids': {'tmdb': int(i[0])}, 'season': int(i[1]), 'episode': int(i[2]), 'last_played': i[4]}
		for i in watched_info
		if not (i[0] in seen or seen.add(i[0]))
	]

def get_resumetime(bookmarks, tmdb_id, season='', episode=''):
	try: resume_point, curr_time, resume_id = detect_bookmark(bookmarks, tmdb_id, season, episode)
	except: resume_point, curr_time, resume_id = 0, 0, 0
	try: progress = str(int(round(float(resume_point))))
	except: progress = '0'
	try: resumetime = str(int(round(float(curr_time))))
	except: resumetime = '0'
	return resumetime, progress

def set_resumetime(resumetime, progress, duration):
	try: resumetime, progress = float(resumetime), float(progress)
	except: return float(0), duration
	return resumetime or progress * duration / 100, duration

def detect_bookmark(bookmarks, tmdb_id, season='', episode=''):
	return [(i[1], i[2], i[5]) for i in bookmarks if i[0] == str(tmdb_id) and i[3] == season and i[4] == episode][0]

def get_bookmarks(watched_indicators, mediatype):
	try:
		dbcon = _database_connect(get_database(watched_indicators))
		dbcur = set_PRAGMAS(dbcon)
		result = dbcur.execute("""SELECT media_id, resume_point, curr_time, season, episode, resume_id FROM progress WHERE db_type = ?""", (mediatype,))
		return result.fetchall()
	except: pass

def set_bookmark(mediatype, tmdb_id, curr_time, total_time, title, season='', episode=''):
	try:
		adjusted_current_time = float(curr_time) - 5
		resume_point = round(adjusted_current_time/float(total_time)*100, 1)
		watched_indicators = settings.watched_indicators()
		if watched_indicators == 1:
			trakt_progress('set_progress', mediatype, tmdb_id, resume_point, season, episode, refresh_trakt=True)
		elif watched_indicators == 2:
			mdbl_progress('set_progress', mediatype, tmdb_id, resume_point, season, episode, refresh_mdb=True)
		elif watched_indicators == 3:
			flicklist_progress('set_progress', mediatype, tmdb_id, resume_point, season, episode, refresh_flicklist=True)
		else:
			erase_bookmark(mediatype, tmdb_id, season, episode)
			data_base = get_database(watched_indicators)
			last_played = get_last_played_value(data_base)
			dbcon = _database_connect(data_base)
			dbcur = set_PRAGMAS(dbcon)
			dbcur.execute("""INSERT OR REPLACE INTO progress VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
						(mediatype, tmdb_id, season, episode, str(resume_point), str(curr_time), last_played, 0, title))
		if settings.sync_kodi_library_watchstatus():
			set_bookmark_kodi_library(mediatype, tmdb_id, curr_time, total_time, season, episode)
		kodi_utils.container_refresh()
	except: pass

def erase_bookmark(mediatype, tmdb_id, season='', episode='', refresh='false'):
	try:
		watched_indicators = settings.watched_indicators()
		bookmarks = get_bookmarks(watched_indicators, mediatype)
		if mediatype == 'episode': season, episode = int(season), int(episode)
		try: resume_id = detect_bookmark(bookmarks, tmdb_id, season, episode)[2]
		except: return
		if watched_indicators == 1:
			trakt_progress('clear_progress', mediatype, tmdb_id, 0, season, episode, resume_id)
		elif watched_indicators == 2:
			mdbl_progress('clear_progress', mediatype, tmdb_id, 0, season, episode, resume_id)
		elif watched_indicators == 3:
			flicklist_progress('clear_progress', mediatype, tmdb_id, 0, season, episode, resume_id)
		dbcon = _database_connect(get_database(watched_indicators))
		dbcur = set_PRAGMAS(dbcon)
		dbcur.execute("""DELETE FROM progress WHERE db_type = ? AND media_id = ? AND season = ? AND episode = ?""", (mediatype, tmdb_id, season, episode))
		if refresh == 'true': kodi_utils.container_refresh()
	except: pass

def batch_erase_bookmark(watched_indicators, insert_list, action):
	try:
		if action == 'mark_as_watched': modified_list = [(i[0], i[1], i[2], i[3]) for i in insert_list]
		else: modified_list = insert_list
		if watched_indicators == 1: function = trakt_progress
		elif watched_indicators == 2: function = mdbl_progress
		elif watched_indicators == 3: function = flicklist_progress
		else: function = None
		if not function is None:
			def _process(arg):
				try: function(*arg)
				except: pass
			process_list = []
			process_list_append = process_list.append
			mediatype = insert_list[0][0]
			tmdb_id = insert_list[0][1]
			bookmarks = get_bookmarks(watched_indicators, mediatype)
			for i in insert_list:
				try: resume_point, curr_time, resume_id = detect_bookmark(bookmarks, tmdb_id, i[2], i[3])
				except: continue
				process_list_append(('clear_progress', i[0], i[1], 0, i[2], i[3], resume_id))
			if process_list: threads = list(make_thread_list(_process, process_list, Thread))
		dbcon = _database_connect(get_database(watched_indicators))
		dbcur = set_PRAGMAS(dbcon)
		dbcur.executemany("""DELETE FROM progress WHERE db_type = ? AND media_id = ? AND season = ? AND episode = ?""", modified_list)
	except: pass

def get_watched_info_movie(watched_indicators):
	info = []
	try:
		dbcon = _database_connect(get_database(watched_indicators))
		dbcur = set_PRAGMAS(dbcon)
		dbcur.execute("""SELECT media_id, title, last_played FROM watched_status WHERE db_type = ?""", ('movie',))
		info = dbcur.fetchall()
	except: pass
	return info

def get_watched_info_tv(watched_indicators):
	info = []
	try:
		dbcon = _database_connect(get_database(watched_indicators))
		dbcur = set_PRAGMAS(dbcon)
		dbcur.execute("""SELECT media_id, season, episode, title, last_played FROM watched_status WHERE db_type = ?""", ('episode',))
		info = dbcur.fetchall()
	except: pass
	return info

def get_in_progress_movies(dummy_arg, page_no, letter):
	watched_indicators = settings.watched_indicators()
	paginate = settings.paginate()
	limit = settings.page_limit()
	dbcon = _database_connect(get_database(watched_indicators))
	dbcur = set_PRAGMAS(dbcon)
	dbcur.execute("""SELECT media_id, title, last_played FROM progress WHERE db_type = ?""", ('movie',))
	data = dbcur.fetchall()
	data = [{'media_id': i[0], 'title': i[1], 'last_played': i[2]} for i in data if not i[0] == '']
	if settings.lists_sort_order('progress') == 0: original_list = sort_for_article(data, 'title', settings.ignore_articles())
	else: original_list = sorted(data, key=lambda x: x['last_played'], reverse=True)
	if paginate: final_list, total_pages = paginate_list(original_list, page_no, letter, limit)
	else: final_list, total_pages = original_list, 1
	return final_list, total_pages

def get_in_progress_tvshows(dummy_arg, page_no, letter, paginate=None):
	def _process(item):
		tmdb_id = item['media_id']
		meta = metadata.tvshow_meta('tmdb_id', tmdb_id, meta_user_info, get_datetime())
		watched_status = get_watched_status_tvshow(watched_info, tmdb_id, meta.get('total_aired_eps'))
		if watched_status[0] == 0: data_append(item)
	duplicates = set()
	duplicates_add = duplicates.add
	data = []
	data_append = data.append
	watched_indicators = settings.watched_indicators()
	paginate = settings.paginate() if paginate is None else paginate
	limit = settings.page_limit()
	meta_user_info = settings.metadata_user_info()
	watched_info = get_watched_info_tv(watched_indicators)
	watched_info.sort(key=lambda x: (x[0], x[4]), reverse=True)
	prelim_data = [({'media_id': i[0], 'title': i[3], 'last_played': i[4]},) for i in watched_info if not (i[0] in duplicates or duplicates_add(i[0]))]
	for i in TaskPool().tasks(_process, prelim_data, Thread): i.join()
#	threads = list(make_thread_list(_process, prelim_data, Thread))
#	[i.join() for i in threads]
	if settings.lists_sort_order('progress') == 0: original_list = sort_for_article(data, 'title', settings.ignore_articles())
	else: original_list = sorted(data, key=lambda x: x['last_played'], reverse=True)
	if paginate: final_list, total_pages = paginate_list(original_list, page_no, letter, limit)
	else: final_list, total_pages = original_list, 1
	return final_list, total_pages

def get_in_progress_episodes():
	watched_indicators = settings.watched_indicators()
	dbcon = _database_connect(get_database(watched_indicators))
	dbcur = set_PRAGMAS(dbcon)
	dbcur.execute("""SELECT media_id, season, episode, resume_point, last_played, title FROM progress WHERE db_type = ?""", ('episode',))
	data = dbcur.fetchall()
	if settings.lists_sort_order('progress') == 0: data = sort_for_article(data, 5, settings.ignore_articles())
	else: data.sort(key=lambda k: k[4], reverse=True)
	episode_list = [{'media_ids': {'tmdb': i[0]}, 'season': int(i[1]), 'episode': int(i[2]), 'resume_point': float(i[3])} for i in data]
	return episode_list

def get_watched_items(mediatype, page_no, letter, paginate=None):
	paginate = settings.paginate() if paginate is None else paginate
	limit = settings.page_limit()
	watched_indicators = settings.watched_indicators()
	if mediatype == 'tvshow':
		def _process(item):
			tmdb_id = item['media_id']
			meta = metadata.tvshow_meta('tmdb_id', tmdb_id, meta_user_info, get_datetime())
			watched_status = get_watched_status_tvshow(watched_info, tmdb_id, meta.get('total_aired_eps'))
			if watched_status[0] == 1: data_append(item)
		watched_info = get_watched_info_tv(watched_indicators)
		meta_user_info = settings.metadata_user_info()
		duplicates = set()
		duplicates_add = duplicates.add
		data = []
		data_append = data.append
		prelim_data = [({'media_id': i[0], 'title': i[3], 'last_played': i[4]},) for i in watched_info if not (i[0] in duplicates or duplicates_add(i[0]))]
		for i in TaskPool().tasks(_process, prelim_data, Thread): i.join()
#		threads = list(make_thread_list(_process, prelim_data, Thread))
#		[i.join() for i in threads]
	else:
		watched_info = get_watched_info_movie(watched_indicators)
		data = [{'media_id': i[0], 'title': i[1], 'last_played': i[2]} for i in watched_info]
	if settings.lists_sort_order('watched') == 0: original_list = sort_for_article(data, 'title', settings.ignore_articles())
	else: original_list = sorted(data, key=lambda x: x['last_played'], reverse=True)
	if paginate: final_list, total_pages = paginate_list(original_list, page_no, letter, limit)
	else: final_list, total_pages = original_list, 1
	return final_list, total_pages

def get_watched_status_movie(watched_info, tmdb_id):
	try:
		watched = [i for i in watched_info if i[0] == tmdb_id]
		if watched: return 1, 5
		return 0, 4
	except: return 0, 4

def get_watched_status_tvshow(watched_info, tmdb_id, aired_eps):
	playcount, overlay, watched, unwatched = 0, 4, 0, aired_eps
	try:
		watched = len([i for i in watched_info if i[0] == tmdb_id])
		unwatched = aired_eps - watched
		if watched >= aired_eps and not aired_eps == 0: playcount, overlay = 1, 5
	except: pass
	return playcount, overlay, watched, unwatched

def get_watched_status_season(watched_info, tmdb_id, season, aired_eps):
	playcount, overlay, watched, unwatched = 0, 4, 0, aired_eps
	try:
		watched = len([i for i in watched_info if i[0] == tmdb_id and i[1] == season])
		unwatched = aired_eps - watched
		if watched >= aired_eps and not aired_eps == 0: playcount, overlay = 1, 5
	except: pass
	return playcount, overlay, watched, unwatched

def get_watched_status_episode(watched_info, tmdb_id, season='', episode=''):
	try:
		watched = [i for i in watched_info if i[0] == tmdb_id and (i[1], i[2]) == (season, episode)]
		if watched: return 1, 5
		else: return 0, 4
	except: return 0, 4

def mark_as_watched_unwatched_movie(params):
	mediatype, action = 'movie', params.get('action')
	tmdb_id, title, year = params.get('tmdb_id'), params.get('title'), params.get('year')
	refresh, from_playback = params.get('refresh', 'true') == 'true', params.get('from_playback', 'false') == 'true'
	watched_indicators = settings.watched_indicators()
	if watched_indicators == 1:
		if from_playback and trakt_official_status(mediatype) is False: kodi_utils.sleep(3000)
		elif not trakt_watched_unwatched(action, 'movies', tmdb_id):
			return kodi_utils.notification(32574)
		clear_trakt_collection_watchlist_data('watchlist', mediatype)
	elif watched_indicators == 2:
		if not mdbl_watched_unwatched(action, 'movies', tmdb_id): return kodi_utils.notification(32574)
		clear_mdbl_collection_watchlist_data('watchlist')
	elif watched_indicators == 3:
		if not flicklist_watched_unwatched(action, 'movies', tmdb_id): return kodi_utils.notification(32574)
		clear_flicklist_collection_watchlist_data('watchlist')
	mark_as_watched_unwatched(watched_indicators, mediatype, tmdb_id, action, title=title)
	if settings.sync_kodi_library_watchstatus():
		mark_as_watched_unwatched_kodi_library(mediatype, action, title, year)
	if refresh: kodi_utils.container_refresh()

def mark_as_watched_unwatched_tvshow(params):
	tmdb_id, action = params.get('tmdb_id'), params.get('action')
	try: tvdb_id = int(params.get('tvdb_id', '0'))
	except: tvdb_id = 0
	watched_indicators = settings.watched_indicators()
	kodi_utils.progressDialogBG.create(ls(32577), '')
	data_base = get_database(watched_indicators)
	title, year = params.get('title', ''), params.get('year', '')
	meta_user_info = settings.metadata_user_info()
	adjust_hours = settings.date_offset()
	current_date = get_datetime()
	insert_list = []
	insert_append = insert_list.append
	meta = metadata.tvshow_meta('tmdb_id', tmdb_id, meta_user_info, get_datetime())
	season_data = meta['season_data']
	season_data = [i for i in season_data if i['season_number'] > 0]
	total = len(season_data)
	last_played = get_last_played_value(data_base)
	for count, item in enumerate(season_data, 1):
		season_number = item['season_number']
		ep_data = metadata.season_episodes_meta(season_number, meta, meta_user_info)
		for ep in ep_data:
			season_number = ep['season']
			ep_number = ep['episode']
			display = 'S%.2dE%.2d' % (int(season_number), int(ep_number))
			kodi_utils.progressDialogBG.update(int(float(count)/float(total)*100), ls(32577), '%s' % display)
			episode_date, premiered = adjust_premiered_date(ep['premiered'], adjust_hours)
			if not episode_date or current_date < episode_date: continue
			insert_append(make_batch_insert(action, 'episode', tmdb_id, season_number, ep_number, last_played, title))
	if watched_indicators == 1:
		if not trakt_watched_unwatched(action, 'shows', tmdb_id, tvdb_id): return kodi_utils.notification(32574)
		clear_trakt_collection_watchlist_data('watchlist', 'tvshow')
	elif watched_indicators == 2:
		if not mdbl_watched_unwatched(action, 'shows', tmdb_id, tvdb_id): return kodi_utils.notification(32574)
		clear_mdbl_collection_watchlist_data('watchlist')
	elif watched_indicators == 3:
		if not flicklist_watched_unwatched(action, 'shows', tmdb_id, tvdb_id): return kodi_utils.notification(32574)
		clear_flicklist_collection_watchlist_data('watchlist')
	batch_mark_as_watched_unwatched(watched_indicators, insert_list, action)
	kodi_utils.progressDialogBG.close()
	if settings.sync_kodi_library_watchstatus(): batch_mark_kodi_library(action, insert_list, title, year)
	kodi_utils.container_refresh()

def mark_as_watched_unwatched_season(params):
	season, action = int(params.get('season')), params.get('action')
	if season == 0: return kodi_utils.notification(32575)
	try: tvdb_id = int(params.get('tvdb_id', '0'))
	except: tvdb_id = 0
	tmdb_id, title, year = params.get('tmdb_id'), params.get('title'), params.get('year')
	watched_indicators = settings.watched_indicators()
	insert_list = []
	insert_append = insert_list.append
	kodi_utils.progressDialogBG.create(ls(32577), '')
	data_base = get_database(watched_indicators)
	meta_user_info = settings.metadata_user_info()
	adjust_hours = settings.date_offset()
	current_date = get_datetime()
	meta = metadata.tvshow_meta('tmdb_id', tmdb_id, meta_user_info, get_datetime())
	ep_data = metadata.season_episodes_meta(season, meta, meta_user_info)
	last_played = get_last_played_value(data_base)
	for count, item in enumerate(ep_data, 1):
		season_number = item['season']
		ep_number = item['episode']
		display = 'S%.2dE%.2d' % (season_number, ep_number)
		episode_date, premiered = adjust_premiered_date(item['premiered'], adjust_hours)
		if not episode_date or current_date < episode_date: continue
		kodi_utils.progressDialogBG.update(int(float(count) / float(len(ep_data)) * 100), ls(32577), '%s' % display)
		insert_append(make_batch_insert(action, 'episode', tmdb_id, season_number, ep_number, last_played, title))
	if watched_indicators == 1:
		if not trakt_watched_unwatched(action, 'season', tmdb_id, tvdb_id, season): return kodi_utils.notification(32574)
		clear_trakt_collection_watchlist_data('watchlist', 'tvshow')
	elif watched_indicators == 2:
		if not mdbl_watched_unwatched(action, 'season', tmdb_id, tvdb_id, season): return kodi_utils.notification(32574)
		clear_mdbl_collection_watchlist_data('watchlist')
	elif watched_indicators == 3:
		if not flicklist_watched_unwatched(action, 'season', tmdb_id, tvdb_id, season): return kodi_utils.notification(32574)
		clear_flicklist_collection_watchlist_data('watchlist')
	batch_mark_as_watched_unwatched(watched_indicators, insert_list, action)
	kodi_utils.progressDialogBG.close()
	if settings.sync_kodi_library_watchstatus(): batch_mark_kodi_library(action, insert_list, title, year)
	kodi_utils.container_refresh()

def mark_as_watched_unwatched_episode(params):
	season, episode = int(params.get('season')), int(params.get('episode'))
	if season == 0: return kodi_utils.notification(32575)
	mediatype, action = 'episode', params.get('action')
	try: tvdb_id = int(params.get('tvdb_id', '0'))
	except: tvdb_id = 0
	tmdb_id, title, year = params.get('tmdb_id'), params.get('title'), params.get('year')
	refresh, from_playback = params.get('refresh', 'true') == 'true', params.get('from_playback', 'false') == 'true'
	watched_indicators = settings.watched_indicators()
	if watched_indicators == 1:
		if from_playback and trakt_official_status(mediatype) is False: kodi_utils.sleep(3000)
		elif not trakt_watched_unwatched(action, mediatype, tmdb_id, tvdb_id, season, episode):
			return kodi_utils.notification(32574)
		clear_trakt_collection_watchlist_data('watchlist', 'tvshow')
	elif watched_indicators == 2:
		if not mdbl_watched_unwatched(action, mediatype, tmdb_id, tvdb_id, season, episode):
			return kodi_utils.notification(32574)
		clear_mdbl_collection_watchlist_data('watchlist')
	elif watched_indicators == 3:
		if not flicklist_watched_unwatched(action, mediatype, tmdb_id, tvdb_id, season, episode):
			return kodi_utils.notification(32574)
		clear_flicklist_collection_watchlist_data('watchlist')
	mark_as_watched_unwatched(watched_indicators, mediatype, tmdb_id, action, season, episode, title)
	if settings.sync_kodi_library_watchstatus():
		mark_as_watched_unwatched_kodi_library(mediatype, action, title, year, season, episode)
	if refresh: kodi_utils.container_refresh()

def mark_as_watched_unwatched(watched_indicators, mediatype='', tmdb_id='', action='', season='', episode='', title=''):
	try:
		data_base = get_database(watched_indicators)
		last_played = get_last_played_value(data_base)
		dbcon = _database_connect(data_base)
		dbcur = set_PRAGMAS(dbcon)
		if action == 'mark_as_watched':
			dbcur.execute("""INSERT OR IGNORE INTO watched_status VALUES (?, ?, ?, ?, ?, ?)""", (mediatype, tmdb_id, season, episode, last_played, title))
		elif action == 'mark_as_unwatched':
			dbcur.execute("""DELETE FROM watched_status WHERE (db_type = ? AND media_id = ? AND season = ? AND episode = ?)""", (mediatype, tmdb_id, season, episode))
		erase_bookmark(mediatype, tmdb_id, season, episode)
	except: kodi_utils.notification(32574)

def batch_mark_as_watched_unwatched(watched_indicators, insert_list, action):
	try:
		dbcon = _database_connect(get_database(watched_indicators))
		dbcur = set_PRAGMAS(dbcon)
		if action == 'mark_as_watched':
			dbcur.executemany("""INSERT OR IGNORE INTO watched_status VALUES (?, ?, ?, ?, ?, ?)""", insert_list)
		elif action == 'mark_as_unwatched':
			dbcur.executemany("""DELETE FROM watched_status WHERE (db_type = ? AND media_id = ? AND season = ? AND episode = ?)""", insert_list)
		batch_erase_bookmark(watched_indicators, insert_list, action)
	except: kodi_utils.notification(32574)

def get_last_played_value(database_type):
	if database_type == WATCHED_DB: return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
	elif database_type == MDBL_DB: return datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
	elif database_type == FLICKL_DB: return datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
	else: return datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z')

def make_batch_insert(action, mediatype, tmdb_id, season, episode, last_played, title):
	if action == 'mark_as_watched': return (mediatype, tmdb_id, season, episode, last_played, title)
	else: return (mediatype, tmdb_id, season, episode)

def batch_mark_kodi_library(action, insert_list, title, year):
	in_library = get_library_video('tvshow', title, year)
	if not in_library: return
	if batch_mark_episodes_as_watched_unwatched_kodi_library(action, in_library, insert_list): kodi_utils.notification(32787)

def clear_local_bookmarks():
	try:
		dbcon = _database_connect(kodi_utils.get_video_database_path())
		dbcur = set_PRAGMAS(dbcon)
		file_ids = dbcur.execute("""SELECT idFile FROM files WHERE strFilename LIKE 'plugin.video.sallts%'""").fetchall()
		for i in ('bookmark', 'streamdetails', 'files'):
			dbcur.executemany("""DELETE FROM %s WHERE idFile = ?""" % i, file_ids)
	except: pass

def get_library_video(mediatype, title, year, season=None, episode=None):
	try:
		years = range(int(year)-1, int(year)+2)
		filters = [{"field": "year", "operator": "is", "value": str(i)} for i in years]
		properties = ["imdbnumber", "title", "originaltitle", "file"] if mediatype == 'movie' else ["title", "year"]
		params = {"filter": {"or": filters}, "properties": properties}
		if mediatype == 'movie':
			r = execJSONRPC(json.dumps({"jsonrpc": "2.0", "method": "VideoLibrary.GetMovies", "params": params, "id": 1}))
			r = json.loads(r)['result']['movies']
			try:
				r = [i for i in r if clean_file_name(title).lower() in clean_file_name(i['title']).lower()][0]
				return r
			except:
				return None
		elif mediatype  == 'tvshow':
			r = execJSONRPC(json.dumps({"jsonrpc": "2.0", "method": "VideoLibrary.GetTVShows", "params": params, "id": 1}))
			r = json.loads(r)['result']['tvshows']
			try:
				r = [
					i for i in r
					if clean_file_name(title).lower()
					in (clean_file_name(i['title']).lower() if not ' (' in i['title'] else clean_file_name(i['title']).lower().split(' (')[0])
				][0]
				return r
			except:
				return None
	except: pass

def set_bookmark_kodi_library(mediatype, tmdb_id, curr_time, total_time, season='', episode=''):
	meta_user_info = settings.metadata_user_info()
	try:
		if mediatype == 'movie': info = metadata.movie_meta('tmdb_id', tmdb_id, meta_user_info, get_datetime())
		else: info = metadata.tvshow_meta('tmdb_id', tmdb_id, meta_user_info, get_datetime())
		title, year = info['title'], info['year']
		years = range(int(year)-1, int(year)+2)
		filters = [{"field": "year", "operator": "is", "value": str(i)} for i in years]
		params = {"filter": {"or": filters}, "properties": ["title"]}
		method = 'VideoLibrary.GetMovies' if mediatype == 'movie' else 'VideoLibrary.GetTVShows'
		r = execJSONRPC(json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}))
		r = json.loads(r)['result']['movies'] if mediatype == 'movie' else json.loads(r)['result']['tvshows']
		if mediatype == 'movie': r = [i for i in r if clean_file_name(title).lower() in clean_file_name(i['title']).lower()][0]
		else:
			r = [
				i for i in r
				if clean_file_name(title).lower()
				in (clean_file_name(i['title']).lower() if not ' (' in i['title'] else clean_file_name(i['title']).lower().split(' (')[0])
			][0]
		if mediatype == 'episode':
			filters = [{"field": "season", "operator": "is", "value": str(season)}, {"field": "episode", "operator": "is", "value": str(episode)}]
			params = {"filter": {"and": filters}, "properties": ["file"], "tvshowid": r['tvshowid']}
			r = execJSONRPC(json.dumps({"jsonrpc": "2.0", "method": "VideoLibrary.GetEpisodes", "params": params, "id": 1}))
			r = json.loads(r)['result']['episodes'][0]
		if mediatype == 'movie': method, id_name, library_id = 'VideoLibrary.SetMovieDetails', 'movieid', r['movieid']
		else: method, id_name, library_id = 'VideoLibrary.SetEpisodeDetails', 'episodeid', r['episodeid']
		query = {"jsonrpc": "2.0", "id": "setResumePoint", "method": method, "params": {id_name: library_id, "resume": {"position": curr_time, "total": total_time}}}
		execJSONRPC(json.dumps(query))
	except: pass

def get_bookmark_kodi_library(mediatype, tmdb_id, season='', episode=''):
	resume = '0'
	meta_user_info = settings.metadata_user_info()
	try:
		if mediatype == 'movie': info = metadata.movie_meta('tmdb_id', tmdb_id, meta_user_info, get_datetime())
		else: info = metadata.tvshow_meta('tmdb_id', tmdb_id, meta_user_info, get_datetime())
		title, year = info['title'], info['year']
		years = range(int(year)-1, int(year)+2)
		filters = [{"field": "year", "operator": "is", "value": str(i)} for i in years]
		properties = ["title", "resume"] if mediatype == 'movie' else ["title"]
		params = {"filter": {"or": filters}, "properties": properties}
		method = 'VideoLibrary.GetMovies' if mediatype == 'movie' else 'VideoLibrary.GetTVShows'
		r = execJSONRPC(json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}))
		r = json.loads(r)['result']['movies'] if mediatype == 'movie' else json.loads(r)['result']['tvshows']
		if mediatype == 'movie': r = [i for i in r if clean_file_name(title).lower() in clean_file_name(i['title']).lower()][0]
		else:
			r = [
				i for i in r
				if clean_file_name(title).lower()
				in (clean_file_name(i['title']).lower() if not ' (' in i['title'] else clean_file_name(i['title']).lower().split(' (')[0])
			][0]
		if mediatype == 'episode':
			filters = [{"field": "season", "operator": "is", "value": str(season)}, {"field": "episode", "operator": "is", "value": str(episode)}]
			params = {"filter": {"and": filters}, "properties": ["file"], "tvshowid": r['tvshowid']}
			r = execJSONRPC(json.dumps({"jsonrpc": "2.0", "method": "VideoLibrary.GetEpisodes", "params": params, "id": 1}))
			r = json.loads(r)['result']['episodes'][0]
		if mediatype == 'movie': method, id_name, library_id, results_key = 'VideoLibrary.GetMovieDetails', 'movieid', r['movieid'], 'moviedetails'
		else: method, id_name, library_id, results_key = 'VideoLibrary.GetEpisodeDetails', 'episodeid', r['episodeid'], 'episodedetails'
		query = {"jsonrpc": "2.0", "id": "getResumePoint", "method": method, "params": {id_name: library_id, "properties": ["title", "resume"]}}
		r = json.loads(execJSONRPC(json.dumps(query)))
		resume = r["result"][results_key]["resume"]["position"]
		return resume
	except: pass

def mark_as_watched_unwatched_kodi_library(mediatype, action, title, year, season=None, episode=None):
	try:
		playcount = 1 if action == 'mark_as_watched' else 0
		years = range(int(year)-1, int(year)+2)
		filters = [{"field": "year", "operator": "is", "value": str(i)} for i in years]
		params = {"filter": {"or": filters}, "properties": ["title"]}
		method = 'VideoLibrary.GetMovies' if mediatype == 'movie' else 'VideoLibrary.GetTVShows'
		r = execJSONRPC(json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}))
		r = json.loads(r)['result']['movies'] if mediatype == 'movie' else json.loads(r)['result']['tvshows']
		if mediatype == 'movie': r = [i for i in r if clean_file_name(title).lower() in clean_file_name(i['title']).lower()][0]
		else:
			r = [
				i for i in r
				if clean_file_name(title).lower()
				in (clean_file_name(i['title']).lower() if not ' (' in i['title'] else clean_file_name(i['title']).lower().split(' (')[0])
			][0]
		if mediatype == 'episode':
			filters = [{"field": "season", "operator": "is", "value": str(season)}, {"field": "episode", "operator": "is", "value": str(episode)}]
			params = {"filter": {"and": filters}, "properties": ["file"], "tvshowid": r['tvshowid']}
			r = execJSONRPC(json.dumps({"jsonrpc": "2.0", "method": "VideoLibrary.GetEpisodes", "params": params, "id": 1}))
			r = json.loads(r)['result']['episodes'][0]
		if mediatype == 'movie': method, id_name, library_id = 'VideoLibrary.SetMovieDetails', 'movieid', r['movieid']
		else: method, id_name, library_id = 'VideoLibrary.SetEpisodeDetails', 'episodeid', r['episodeid']
		query = {"jsonrpc": "2.0", "method": method, "params": {id_name: library_id, "playcount": playcount}, "id": 1}
		execJSONRPC(json.dumps(query))
		query = {"jsonrpc": "2.0", "id": "setResumePoint", "method": method, "params": {id_name: library_id, "resume": {"position": 0,}}}
		execJSONRPC(json.dumps(query))
	except: pass

def batch_mark_episodes_as_watched_unwatched_kodi_library(action, show_info, episode_list):
	playcount = 1 if action == 'mark_as_watched' else 0
	tvshowid = str(show_info['tvshowid'])
	ep_ids, action_list = [], []
	ep_ids_append, action_append = ep_ids.append, action_list.append
	progressDialogBG.create(ls(32577), '')
	try:
		for item in episode_list:
			try:
				season = item[2]
				episode = item[3]
				filters = [{"field": "season", "operator": "is", "value": str(season)}, {"field": "episode", "operator": "is", "value": str(episode)}]
				params = {"filter": {"and": filters}, "properties": ["file", "playcount"], "tvshowid": tvshowid}
				r = execJSONRPC(json.dumps({"jsonrpc": "2.0", "method": "VideoLibrary.GetEpisodes", "params": params, "id": 1}))
				r = json.loads(r)['result']['episodes'][0]
				ep_ids_append((r['episodeid'], r['playcount']))
			except: pass
		for count, item in enumerate(ep_ids, 1):
			try:
				ep_id = item[0]
				current_playcount = item[1]
				if int(current_playcount) != playcount:
					sleep(50)
					display = ls(32856)
					progressDialogBG.update(int(float(count) / float(len(ep_ids)) * 100), ls(32577), display)
					query = {"jsonrpc": "2.0", "method": "VideoLibrary.SetEpisodeDetails", "params": {"episodeid": ep_id, "playcount": playcount}, "id": 1}
					action_append(query)
				else: pass
			except: pass
		r = execJSONRPC(json.dumps(action_list))
		progressDialogBG.close()
		return r
	except: pass

