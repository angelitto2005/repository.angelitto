from threading import Thread
from operator import itemgetter
from types import MappingProxyType
from datetime import datetime, timezone
from caches.favorites_cache import get_hidden_items
from caches.mdbl_cache import clear_mdbl_collection_watchlist_data
from caches.trakt_cache import clear_trakt_collection_watchlist_data
from indexers import metadata
from indexers.mdblist_api import mdbl_watched_unwatched, mdbl_progress, mdbl_get_hidden_items
from indexers.trakt_api import trakt_watched_unwatched, trakt_progress, trakt_get_hidden_items, trakt_official_status
from modules import kodi_utils, settings
from modules.utils import adjust_premiered_date, get_datetime, make_thread_list, paginate_list, sort_for_article, TaskPool
# logger = kodi_utils.logger

timeout = 20
GET_MOVIE_SHOW = 'SELECT %s FROM watched_status WHERE db_type = ? ORDER BY last_played DESC'
GET_BM = 'SELECT * FROM progress WHERE db_type = ? ORDER BY last_played DESC'
SET_MOVIE_SHOW = 'INSERT OR IGNORE INTO watched_status VALUES (?, ?, ?, ?, ?, ?)'
SET_BM = 'INSERT OR REPLACE INTO progress VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)'
DELETE_MOVIE_SHOW = 'DELETE FROM watched_status WHERE db_type = ? AND media_id = ? AND season = ? AND episode = ?'
DELETE_BM = 'DELETE FROM progress WHERE db_type = ? AND media_id = ? AND season = ? AND episode = ?'
WATCHED_DB, TRAKT_DB, MDBL_DB = kodi_utils.indicators_dict.values()
wait_str = kodi_utils.local_string(32577)

def _database_connect(database_file):
	return kodi_utils.database_connect(database_file, timeout=timeout, isolation_level=None)

def set_PRAGMAS(dbcon):
	dbcur = dbcon.cursor()
	dbcur.execute("""PRAGMA synchronous = OFF""")
	dbcur.execute("""PRAGMA journal_mode = OFF""")
	dbcur.execute("""PRAGMA mmap_size = 268435456""")
	return dbcur

def get_database(watched_indicators):
	return kodi_utils.indicators_dict[watched_indicators]

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
	data = bookmarks[f"{tmdb_id}_{season}_{episode}"]
	return data[4], data[5], data[7]

def get_bookmarks(watched_indicators, mediatype):
	try:
		dbcon = _database_connect(get_database(watched_indicators))
		dbcur = set_PRAGMAS(dbcon)
		data = dbcur.execute(GET_BM, (mediatype,))
		return MappingProxyType({f"{i[1]}_{i[2]}_{i[3]}": i for i in data})
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
		else:
			erase_bookmark(mediatype, tmdb_id, season, episode)
			data_base = get_database(watched_indicators)
			last_played = get_last_played_value(data_base)
			dbcon = _database_connect(data_base)
			dbcur = set_PRAGMAS(dbcon)
			dbcur.execute(SET_BM, (mediatype, tmdb_id, season, episode, str(resume_point), str(curr_time), last_played, 0, title))
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
		dbcon = _database_connect(get_database(watched_indicators))
		dbcur = set_PRAGMAS(dbcon)
		dbcur.execute(DELETE_BM, (mediatype, tmdb_id, season, episode))
		if refresh == 'true': kodi_utils.container_refresh()
	except: pass

def batch_erase_bookmark(watched_indicators, insert_list, action):
	try:
		if action == 'mark_as_watched': modified_list = [(i[0], i[1], i[2], i[3]) for i in insert_list]
		else: modified_list = insert_list
		if watched_indicators in (1, 2):
			def _process(arg):
				try: function(*arg)
				except: pass
			process_list = []
			process_list_append = process_list.append
			mediatype, tmdb_id = insert_list[0][0], insert_list[0][1]
			bookmarks = get_bookmarks(watched_indicators, mediatype)
			function = (None, trakt_progress, mdbl_progress)[watched_indicators]
			for i in insert_list:
				try: resume_id = detect_bookmark(bookmarks, tmdb_id, i[2], i[3])[2]
				except: continue
				process_list_append(('clear_progress', i[0], i[1], 0, i[2], i[3], resume_id))
			if process_list: threads = list(make_thread_list(_process, process_list, Thread))
		dbcon = _database_connect(get_database(watched_indicators))
		dbcur = set_PRAGMAS(dbcon)
		dbcur.executemany(DELETE_BM, modified_list)
	except: pass

def get_next_episodes(watched_indicators):
	dropped_info = get_dropped_info_tv(watched_indicators)
	dbcon = _database_connect(get_database(watched_indicators))
	dbcur = set_PRAGMAS(dbcon)
	data = dbcur.execute("""
		SELECT media_id, title, last_played, season, episode
		FROM (
			SELECT *, ROW_NUMBER() OVER (
				PARTITION BY media_id ORDER BY season DESC, episode DESC
			) AS r
			FROM watched_status
			WHERE db_type = ?
		) AS t
		WHERE r = 1
	""", ('episode',))
	return [
		{'media_ids': {'tmdb': i[0]}, 'last_played': i[2], 'season': i[3], 'episode': i[4]}
		for i in data if int(i[0]) not in dropped_info
	]

def get_watched_info_movie(watched_indicators):
	info = {}
	try:
		command = GET_MOVIE_SHOW % ('media_id, title, last_played')
		dbcon = _database_connect(get_database(watched_indicators))
		dbcur = set_PRAGMAS(dbcon)
		for i in dbcur.execute(command, ('movie',)): info[i[0]] = i
	except: pass
	return MappingProxyType(info)

def get_watched_info_tv(watched_indicators):
	info = {}
	try:
		command = GET_MOVIE_SHOW % ('media_id, title, last_played, season, episode')
		dbcon = _database_connect(get_database(watched_indicators))
		dbcur = set_PRAGMAS(dbcon)
		for i in dbcur.execute(command, ('episode',)):
			if i[0] in info: info[i[0]] += (i,)
			else: info[i[0]] = (i,)
	except: pass
	return MappingProxyType(info)

def get_dropped_info_tv(watched_indicators):
	hidden_data = set()
	try:
		if   watched_indicators == 1: hidden_data.update(trakt_get_hidden_items('dropped'))
		elif watched_indicators == 2: hidden_data.update(mdbl_get_hidden_items('dropped'))
		else: hidden_data.update(get_hidden_items('dropped'))
	except: pass
	return hidden_data

def get_in_progress_items(watched_info, mediatype, *args):
	data = [
		{'media_ids': {'tmdb': i[1]}, 'media_id': i[1], 'title':i[8], 'season': i[2], 'episode': i[3]}
		for i in watched_info.values() if i[0] == mediatype
	]
	if settings.lists_sort_order('progress') == 0:
		original_list = sort_for_article(data, 'title', settings.ignore_articles())
	else: original_list = data
	if mediatype == 'movie': return original_list, 1
	return original_list

def get_in_progress_tvshows(watched_info, mediatype, page_no):
	def _process(item):
		tmdb_id = item['media_id']
		meta = metadata.tvshow_meta('tmdb_id', tmdb_id, meta_user_info, current_date)
		watched_status = get_watched_status_tvshow(watched_info, tmdb_id, meta.get('total_aired_eps'))
		if watched_status[0] == 0: data_append(item)
	watched_indicators = settings.watched_indicators()
	paginate = settings.paginate()
	limit = settings.page_limit()
	meta_user_info = settings.metadata_user_info()
	current_date = get_datetime()
	data = []
	data_append = data.append
	dropped_info = get_dropped_info_tv(watched_indicators)
	prelim_data = [
		({'media_id': v[0][0], 'title': v[0][1], 'last_played': v[0][2]},)
		for k, v in watched_info.items() if int(k) not in dropped_info
	]
	for i in TaskPool().tasks(_process, prelim_data, Thread): i.join()
#	threads = list(make_thread_list(_process, prelim_data, Thread))
#	[i.join() for i in threads]
	if settings.lists_sort_order('progress') == 0:
		original_list = sort_for_article(data, 'title', settings.ignore_articles())
	else: original_list = sorted(data, key=itemgetter('last_played'), reverse=True)
	if paginate: return paginate_list(original_list, page_no, limit)
	return original_list, 1

def get_watched_movie_tvshow(watched_info, mediatype, page_no):
	def _process(item):
		tmdb_id = item['media_id']
		meta = metadata.tvshow_meta('tmdb_id', tmdb_id, meta_user_info, current_date)
		watched_status = get_watched_status_tvshow(watched_info, tmdb_id, meta.get('total_aired_eps'))
		if watched_status[0] == 1: data_append(item)
	watched_indicators = settings.watched_indicators()
	paginate = settings.paginate()
	limit = settings.page_limit()
	if mediatype == 'tvshow':
		meta_user_info = settings.metadata_user_info()
		current_date = get_datetime()
		data = []
		data_append = data.append
		dropped_info = get_dropped_info_tv(watched_indicators)
		prelim_data = [
			({'media_id': v[0][0], 'title': v[0][1], 'last_played': v[0][2]},)
			for k, v in watched_info.items() if int(k) not in dropped_info
		]
		for i in TaskPool().tasks(_process, prelim_data, Thread): i.join()
#		threads = list(make_thread_list(_process, prelim_data, Thread))
#		[i.join() for i in threads]
		data.sort(key=itemgetter('last_played'), reverse=True)
	else:
		data = [{'media_id': i[0], 'title': i[1]} for i in watched_info.values()]
	if settings.lists_sort_order('watched') == 0:
		original_list = sort_for_article(data, 'title', settings.ignore_articles())
	else: original_list = data
	if paginate: return paginate_list(original_list, page_no, limit)
	return original_list, 1

def get_watched_status_movie(watched_info, tmdb_id):
	try:
		watched_info[tmdb_id]
		return 1, 5
	except: pass
	return 0, 4

def get_watched_status_tvshow(watched_info, tmdb_id, aired_eps):
	playcount, overlay, watched, unwatched = 0, 4, 0, aired_eps
	try:
		watched = sum(True for i in watched_info[tmdb_id] if i[3])
		unwatched = aired_eps - watched
		if watched >= aired_eps and aired_eps != 0: playcount, overlay = 1, 5
	except: pass
	return playcount, overlay, watched, unwatched

def get_watched_status_season(watched_info, tmdb_id, season, aired_eps):
	playcount, overlay, watched, unwatched = 0, 4, 0, aired_eps
	try:
		watched = sum(True for i in watched_info[tmdb_id] if i[3] == season)
		unwatched = aired_eps - watched
		if watched >= aired_eps and aired_eps != 0: playcount, overlay = 1, 5
	except: pass
	return playcount, overlay, watched, unwatched

def get_watched_status_episode(watched_info, tmdb_id, season='', episode=''):
	try:
		next(True for i in watched_info[tmdb_id] if i[3] == season and i[4] == episode)
		return 1, 5
	except: pass
	return 0, 4

def mark_as_watched_unwatched_movie(params):
	mediatype, action = 'movie', params.get('action')
	tmdb_id, title = params.get('tmdb_id'), params.get('title')
	refresh = params.get('refresh', 'true') == 'true'
	from_playback = params.get('from_playback', 'false') == 'true'
	watched_indicators = settings.watched_indicators()
	if watched_indicators == 1:
		if from_playback and trakt_official_status(mediatype) is False: kodi_utils.sleep(3000)
		elif not trakt_watched_unwatched(action, 'movies', tmdb_id):
			return kodi_utils.notification(32574)
		clear_trakt_collection_watchlist_data('watchlist', mediatype)
	elif watched_indicators == 2:
		if not mdbl_watched_unwatched(action, 'movies', tmdb_id): return kodi_utils.notification(32574)
		clear_mdbl_collection_watchlist_data('watchlist')
	mark_as_watched_unwatched(watched_indicators, mediatype, tmdb_id, action, title=title)
	if refresh: kodi_utils.container_refresh()

def mark_as_watched_unwatched_tvshow(params):
	action = params.get('action')
	try: tvdb_id = int(params.get('tvdb_id', '0'))
	except: tvdb_id = 0
	tmdb_id, title = params.get('tmdb_id'), params.get('title', '')
	watched_indicators = settings.watched_indicators()
	data_base = get_database(watched_indicators)
	meta_user_info = settings.metadata_user_info()
	adjust_hours = settings.date_offset()
	current_date = get_datetime()
	last_played = get_last_played_value(data_base)
	insert_list = []
	insert_append = insert_list.append
	kodi_utils.progressDialogBG.create(wait_str, '')
	try:
		meta = metadata.tvshow_meta('tmdb_id', tmdb_id, meta_user_info, current_date)
		season_data = meta['season_data']
		season_data = [i for i in season_data if i['season_number'] > 0]
		ep_data = []
		for i in season_data: ep_data += metadata.season_episodes_meta(i['season_number'], meta, meta_user_info)
		total = len(ep_data)
		for count, item in enumerate(ep_data, 1):
			season_number = item['season']
			ep_number = item['episode']
			display = 'S%.2dE%.2d' % (int(season_number), int(ep_number))
			kodi_utils.progressDialogBG.update(int(float(count)/float(total)*100), wait_str, display)
			episode_date, premiered = adjust_premiered_date(item['premiered'], adjust_hours)
			if not episode_date or current_date < episode_date: continue
			insert_append(make_batch_insert(action, 'episode', tmdb_id, season_number, ep_number, last_played, title))
		if watched_indicators == 1:
			if not trakt_watched_unwatched(action, 'shows', tmdb_id, tvdb_id):
				return kodi_utils.notification(32574)
			clear_trakt_collection_watchlist_data('watchlist', 'tvshow')
		elif watched_indicators == 2:
			if not mdbl_watched_unwatched(action, 'shows', tmdb_id, tvdb_id):
				return kodi_utils.notification(32574)
			clear_mdbl_collection_watchlist_data('watchlist')
		batch_mark_as_watched_unwatched(watched_indicators, insert_list, action)
	finally: kodi_utils.progressDialogBG.close()
	kodi_utils.container_refresh()

def mark_as_watched_unwatched_season(params):
	season, action = int(params.get('season')), params.get('action')
	if season == 0: return kodi_utils.notification(32575)
	try: tvdb_id = int(params.get('tvdb_id', '0'))
	except: tvdb_id = 0
	tmdb_id, title = params.get('tmdb_id'), params.get('title')
	watched_indicators = settings.watched_indicators()
	data_base = get_database(watched_indicators)
	meta_user_info = settings.metadata_user_info()
	adjust_hours = settings.date_offset()
	current_date = get_datetime()
	last_played = get_last_played_value(data_base)
	insert_list = []
	insert_append = insert_list.append
	kodi_utils.progressDialogBG.create(wait_str, '')
	try:
		meta = metadata.tvshow_meta('tmdb_id', tmdb_id, meta_user_info, current_date)
		ep_data = metadata.season_episodes_meta(season, meta, meta_user_info)
		total = len(ep_data)
		for count, item in enumerate(ep_data, 1):
			season_number = item['season']
			ep_number = item['episode']
			display = 'S%.2dE%.2d' % (int(season_number), int(ep_number))
			kodi_utils.progressDialogBG.update(int(float(count)/float(total)*100), wait_str, display)
			episode_date, premiered = adjust_premiered_date(item['premiered'], adjust_hours)
			if not episode_date or current_date < episode_date: continue
			insert_append(make_batch_insert(action, 'episode', tmdb_id, season_number, ep_number, last_played, title))
		if watched_indicators == 1:
			if not trakt_watched_unwatched(action, 'season', tmdb_id, tvdb_id, season):
				return kodi_utils.notification(32574)
			clear_trakt_collection_watchlist_data('watchlist', 'tvshow')
		elif watched_indicators == 2:
			if not mdbl_watched_unwatched(action, 'season', tmdb_id, tvdb_id, season):
				return kodi_utils.notification(32574)
			clear_mdbl_collection_watchlist_data('watchlist')
		batch_mark_as_watched_unwatched(watched_indicators, insert_list, action)
	finally: kodi_utils.progressDialogBG.close()
	kodi_utils.container_refresh()

def mark_as_watched_unwatched_episode(params):
	season, episode = int(params.get('season')), int(params.get('episode'))
	if season == 0: return kodi_utils.notification(32575)
	mediatype, action = 'episode', params.get('action')
	try: tvdb_id = int(params.get('tvdb_id', '0'))
	except: tvdb_id = 0
	tmdb_id, title = params.get('tmdb_id'), params.get('title')
	refresh = params.get('refresh', 'true') == 'true'
	from_playback = params.get('from_playback', 'false') == 'true'
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
	mark_as_watched_unwatched(watched_indicators, mediatype, tmdb_id, action, season, episode, title)
	if refresh: kodi_utils.container_refresh()

def mark_as_watched_unwatched(watched_indicators, mediatype='', tmdb_id='', action='', season='', episode='', title=''):
	try:
		data_base = get_database(watched_indicators)
		last_played = get_last_played_value(data_base)
		dbcon = _database_connect(data_base)
		dbcur = set_PRAGMAS(dbcon)
		if action == 'mark_as_watched':
			dbcur.execute(SET_MOVIE_SHOW, (mediatype, tmdb_id, season, episode, last_played, title))
		elif action == 'mark_as_unwatched':
			dbcur.execute(DELETE_MOVIE_SHOW, (mediatype, tmdb_id, season, episode))
		erase_bookmark(mediatype, tmdb_id, season, episode)
	except: kodi_utils.notification(32574)

def batch_mark_as_watched_unwatched(watched_indicators, insert_list, action):
	try:
		dbcon = _database_connect(get_database(watched_indicators))
		dbcur = set_PRAGMAS(dbcon)
		if action == 'mark_as_watched': dbcur.executemany(SET_MOVIE_SHOW, insert_list)
		elif action == 'mark_as_unwatched': dbcur.executemany(DELETE_MOVIE_SHOW, insert_list)
		batch_erase_bookmark(watched_indicators, insert_list, action)
	except: kodi_utils.notification(32574)

def get_last_played_value(database_type):
	if database_type == TRAKT_DB: return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')
	elif database_type == MDBL_DB: return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
	else: return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def make_batch_insert(action, mediatype, tmdb_id, season, episode, last_played, title):
	if action == 'mark_as_watched': return (mediatype, tmdb_id, season, episode, last_played, title)
	else: return (mediatype, tmdb_id, season, episode)

def clear_local_bookmarks():
	try:
		GET_LBM = 'SELECT idFile FROM files WHERE strFilename LIKE "plugin.video.pov%"'
		DELETE_LBM = 'DELETE FROM %s WHERE idFile = ?'
		dbcon = _database_connect(kodi_utils.get_video_database_path())
		dbcur = set_PRAGMAS(dbcon)
		file_ids = dbcur.execute(GET_LBM).fetchall()
		for i in ('bookmark', 'streamdetails', 'files'): dbcur.executemany(DELETE_LBM % i, file_ids)
	except: pass

