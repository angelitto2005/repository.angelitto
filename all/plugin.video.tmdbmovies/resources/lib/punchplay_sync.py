# -*- coding: utf-8 -*-
import os
import json
import time
import datetime
import threading
import xbmc
import xbmcgui

from resources.lib.config import ADDON, ADDON_DATA_DIR, ADDON_PATH, PUNCHPLAY_COLOR, provider_title
from resources.lib.punchplay_api import PunchplayAPI, PUNCHPLAY_ICON, PUNCHPLAY_CLIENT_ID

DB_PATH = os.path.join(ADDON_DATA_DIR, 'punchplay_sync.db')

_MONITOR = None

def _abort_requested():
    global _MONITOR
    if _MONITOR is None:
        _MONITOR = xbmc.Monitor()
    return _MONITOR.abortRequested()

def get_connection():
    import sqlite3
    try:
        conn = sqlite3.connect(DB_PATH, timeout=60)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=OFF')
        conn.execute('PRAGMA busy_timeout=15000')
        return conn
    except Exception as e:
        xbmc.log(f'[PUNCHPLAY] get_connection error: {e}', xbmc.LOGERROR)
        conn = sqlite3.connect(DB_PATH, timeout=60)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('PRAGMA busy_timeout=15000')
        except:
            pass
        return conn

def _db_exec_retry(c, sql, params=None, tries=20):
    import time as _t
    for _a in range(tries):
        try:
            if params is None:
                c.execute(sql)
            else:
                c.execute(sql, params)
            return True
        except Exception as _e:
            if 'database is locked' in str(_e) and _a < tries - 1:
                _t.sleep(0.4 + 0.15 * _a)
                continue
            raise
    return False

def _db_commit_retry(conn, tries=20):
    import time as _t
    for _a in range(tries):
        try:
            conn.commit()
            return True
        except Exception as _e:
            if 'database is locked' in str(_e) and _a < tries - 1:
                _t.sleep(0.4 + 0.15 * _a)
                continue
            xbmc.log(f'[PUNCHPLAY] commit retry failed: {_e}', xbmc.LOGERROR)
            return False
    return False

def _ensure_db():
    try:
        init_database()
    except:
        pass

def init_database():
    conn = get_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS punchplay_watched_movies
                 (tmdb_id TEXT PRIMARY KEY, title TEXT, year TEXT, last_watched_at TEXT,
                  poster TEXT, backdrop TEXT, overview TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS punchplay_watched_episodes
                 (tmdb_id TEXT, season INTEGER, episode INTEGER, title TEXT, last_watched_at TEXT,
                  UNIQUE(tmdb_id, season, episode))''')
    c.execute('''CREATE TABLE IF NOT EXISTS punchplay_fully_watched_shows
                 (tmdb_id TEXT PRIMARY KEY, total_episodes INTEGER, last_watched_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS punchplay_watchlist
                 (tmdb_id TEXT PRIMARY KEY, media_type TEXT, status TEXT DEFAULT 'watching',
                  added_at TEXT, title TEXT, year TEXT, is_anime INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS punchplay_ratings
                 (tmdb_id TEXT, media_type TEXT, season INTEGER DEFAULT 0, episode INTEGER DEFAULT 0,
                  rating INTEGER, rated_at TEXT, is_anime INTEGER DEFAULT 0, title TEXT DEFAULT '',
                  UNIQUE(tmdb_id, media_type, season, episode))''')
    c.execute('''CREATE TABLE IF NOT EXISTS punchplay_dropped
                 (tmdb_id TEXT PRIMARY KEY, dropped_at TEXT, title TEXT DEFAULT '')''')
    c.execute('''CREATE TABLE IF NOT EXISTS punchplay_playback
                 (tmdb_id TEXT, media_type TEXT, season INTEGER DEFAULT 0, episode INTEGER DEFAULT 0,
                  progress REAL, updated_at TEXT,
                  UNIQUE(tmdb_id, media_type, season, episode))''')
    c.execute('''CREATE TABLE IF NOT EXISTS punchplay_next_episodes
                 (tmdb_id TEXT PRIMARY KEY, show_title TEXT, season INTEGER, episode INTEGER,
                  ep_title TEXT, air_date TEXT, watched_count INTEGER DEFAULT 0,
                  total_count INTEGER DEFAULT 0, last_watched_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS punchplay_favourites
                 (tmdb_id TEXT PRIMARY KEY, media_type TEXT, title TEXT DEFAULT '')''')
    c.execute('''CREATE TABLE IF NOT EXISTS punchplay_sync_meta (key TEXT PRIMARY KEY, value TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS punchplay_cache (key TEXT PRIMARY KEY, data TEXT, saved_at REAL)''')
    try:
        c.execute("ALTER TABLE punchplay_dropped ADD COLUMN title TEXT DEFAULT ''")
    except:
        pass
    try:
        c.execute("ALTER TABLE punchplay_watchlist ADD COLUMN is_anime INTEGER DEFAULT 0")
    except:
        pass
    try:
        c.execute("ALTER TABLE punchplay_ratings ADD COLUMN title TEXT DEFAULT ''")
    except:
        pass
    try:
        c.execute("ALTER TABLE punchplay_ratings ADD COLUMN is_anime INTEGER DEFAULT 0")
    except:
        pass
    conn.commit()
    conn.close()

def clear_all_local_data():
    try:
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
    except:
        pass
    try:
        init_database()
    except:
        pass

def get_sync_meta(key, default=''):
    try:
        _ensure_db()
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT value FROM punchplay_sync_meta WHERE key=?", (key,))
        r = c.fetchone()
        conn.close()
        return r[0] if r else default
    except:
        return default

def set_sync_meta(key, value):
    try:
        _ensure_db()
        conn = get_connection()
        c = conn.cursor()
        _db_exec_retry(c, "INSERT OR REPLACE INTO punchplay_sync_meta (key, value) VALUES (?,?)", (key, str(value)))
        _db_commit_retry(conn)
        conn.close()
    except:
        pass

def get_cached(key, ttl=3600):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT data, saved_at FROM punchplay_cache WHERE key=?", (key,))
        r = c.fetchone()
        conn.close()
        if not r:
            return None
        if time.time() - float(r[1] or 0) > ttl:
            return None
        try:
            return json.loads(r[0])
        except:
            return None
    except:
        return None

def set_cached(key, data):
    try:
        conn = get_connection()
        c = conn.cursor()
        _db_exec_retry(c, "INSERT OR REPLACE INTO punchplay_cache (key, data, saved_at) VALUES (?,?,?)",
                       (key, json.dumps(data), time.time()))
        _db_commit_retry(conn)
        conn.close()
    except:
        pass

def _is_punchplay_provider():
    try:
        return (ADDON.getSetting('watched_status_provider') or '0') == '3'
    except:
        return False

def get_history_counts():
    try:
        if not os.path.exists(DB_PATH):
            return (0, 0)
    except:
        return (0, 0)
    conn = None
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM punchplay_watched_movies")
        movies = c.fetchone()[0] or 0
        c.execute("SELECT COUNT(DISTINCT tmdb_id) FROM punchplay_watched_episodes")
        partial = c.fetchone()[0] or 0
        try:
            c.execute("SELECT COUNT(*) FROM punchplay_fully_watched_shows WHERE tmdb_id NOT IN (SELECT DISTINCT tmdb_id FROM punchplay_watched_episodes)")
            fully = c.fetchone()[0] or 0
        except:
            fully = 0
        return (movies, partial + fully)
    except:
        return (0, 0)
    finally:
        try:
            if conn is not None:
                conn.close()
        except:
            pass

def is_movie_watched(tmdb_id):
    try:
        _ensure_db()
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT 1 FROM punchplay_watched_movies WHERE tmdb_id=?", (str(tmdb_id),))
        r = c.fetchone()
        conn.close()
        return bool(r)
    except:
        return False

def is_episode_watched(tmdb_id, season, episode):
    try:
        _ensure_db()
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT 1 FROM punchplay_watched_episodes WHERE tmdb_id=? AND season=? AND episode=?",
                  (str(tmdb_id), int(season), int(episode)))
        r = c.fetchone()
        if not r:
            c.execute("SELECT 1 FROM punchplay_fully_watched_shows WHERE tmdb_id=?", (str(tmdb_id),))
            r = c.fetchone()
        conn.close()
        return bool(r)
    except:
        return False

def get_watched_episodes_count(tmdb_id, season=None):
    try:
        _ensure_db()
        conn = get_connection()
        c = conn.cursor()
        if season is not None:
            c.execute("SELECT COUNT(*) FROM punchplay_watched_episodes WHERE tmdb_id=? AND season=? AND episode > 0",
                      (str(tmdb_id), int(season)))
        else:
            c.execute("SELECT COUNT(*) FROM punchplay_watched_episodes WHERE tmdb_id=? AND season > 0 AND episode > 0",
                      (str(tmdb_id),))
        r = c.fetchone()
        conn.close()
        return int(r[0] or 0)
    except:
        return 0

def get_watched_season_episodes_count(tmdb_id, season):
    return get_watched_episodes_count(tmdb_id, season)

def get_watched_movie_count():
    try:
        _ensure_db()
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM punchplay_watched_movies")
        r = c.fetchone()
        conn.close()
        return int(r[0] or 0)
    except:
        return 0

def get_watched_episode_count():
    try:
        _ensure_db()
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM punchplay_watched_episodes WHERE season > 0 AND episode > 0")
        r = c.fetchone()
        conn.close()
        return int(r[0] or 0)
    except:
        return 0

def is_fully_watched_show(tmdb_id):
    try:
        _ensure_db()
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT 1 FROM punchplay_fully_watched_shows WHERE tmdb_id=?", (str(tmdb_id),))
        r = c.fetchone()
        conn.close()
        return bool(r)
    except:
        return False

def is_dropped(tmdb_id):
    try:
        _ensure_db()
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT 1 FROM punchplay_dropped WHERE tmdb_id=?", (str(tmdb_id),))
        r = c.fetchone()
        conn.close()
        return bool(r)
    except:
        return False

def get_dropped_local():
    try:
        _ensure_db()
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT tmdb_id, dropped_at, title FROM punchplay_dropped")
        rows = [{'tmdb_id': str(r[0]), 'dropped_at': r[1], 'title': r[2] or ''} for r in c.fetchall()]
        conn.close()
        return rows
    except:
        return []

def drop_add_local(tmdb_id, title=''):
    try:
        _ensure_db()
        conn = get_connection()
        c = conn.cursor()
        now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')
        _db_exec_retry(c, "INSERT OR REPLACE INTO punchplay_dropped (tmdb_id, dropped_at, title) VALUES (?,?,?)",
                       (str(tmdb_id), now, title or ''))
        _db_commit_retry(conn)
        conn.close()
    except:
        pass

def drop_remove_local(tmdb_id):
    try:
        _ensure_db()
        conn = get_connection()
        c = conn.cursor()
        _db_exec_retry(c, "DELETE FROM punchplay_dropped WHERE tmdb_id=?", (str(tmdb_id),))
        _db_commit_retry(conn)
        conn.close()
    except:
        pass

def is_favourite(tmdb_id):
    try:
        _ensure_db()
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT 1 FROM punchplay_favourites WHERE tmdb_id=?", (str(tmdb_id),))
        r = c.fetchone()
        conn.close()
        return bool(r)
    except:
        return False

def favourite_add_local(tmdb_id, media_type='show', title=''):
    try:
        _ensure_db()
        conn = get_connection()
        c = conn.cursor()
        _db_exec_retry(c, "INSERT OR REPLACE INTO punchplay_favourites (tmdb_id, media_type, title) VALUES (?,?,?)",
                       (str(tmdb_id), media_type, title or ''))
        _db_commit_retry(conn)
        conn.close()
    except:
        pass

def favourite_remove_local(tmdb_id):
    try:
        _ensure_db()
        conn = get_connection()
        c = conn.cursor()
        _db_exec_retry(c, "DELETE FROM punchplay_favourites WHERE tmdb_id=?", (str(tmdb_id),))
        _db_commit_retry(conn)
        conn.close()
    except:
        pass

def is_in_collection(tmdb_id):
    try:
        _ensure_db()
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT 1 FROM punchplay_collection WHERE tmdb_id=?", (str(tmdb_id),))
        r = c.fetchone()
        conn.close()
        return bool(r)
    except:
        return False

def collection_add_local(tmdb_id, media_type='movie', title='', year=''):
    try:
        _ensure_db()
        conn = get_connection()
        c = conn.cursor()
        _db_exec_retry(c, "INSERT OR REPLACE INTO punchplay_collection (tmdb_id, media_type, title, year, added_at) VALUES (?,?,?,?,?)",
                       (str(tmdb_id), media_type, title or '', str(year or ''), ''))
        _db_commit_retry(conn)
        conn.close()
    except:
        pass

def collection_remove_local(tmdb_id):
    try:
        _ensure_db()
        conn = get_connection()
        c = conn.cursor()
        _db_exec_retry(c, "DELETE FROM punchplay_collection WHERE tmdb_id=?", (str(tmdb_id),))
        _db_commit_retry(conn)
        conn.close()
    except:
        pass

def drop_show(tmdb_id, title='', media_type='show'):
    try:
        api = PunchplayAPI()
        mt = 'movie' if str(media_type).lower() == 'movie' else 'show'
        res = api.interact(mt, tmdb_id, scope='title', show_status='DROPPED')
        xbmc.log(f'[PUNCHPLAY] Drop {mt} tmdb={tmdb_id}: {res}', xbmc.LOGINFO)
        drop_add_local(tmdb_id, title)
        try:
            conn = get_connection()
            c = conn.cursor()
            _db_exec_retry(c, "DELETE FROM punchplay_next_episodes WHERE tmdb_id=?", (str(tmdb_id),))
            _db_commit_retry(conn)
            conn.close()
        except:
            pass
        try:
            from resources.lib.cache import clear_all_fast_cache
            clear_all_fast_cache()
        except:
            pass
        return res is not None
    except Exception as e:
        xbmc.log(f'[PUNCHPLAY] drop_show error: {e}', xbmc.LOGERROR)
        return False

def restore_show(tmdb_id, media_type='show'):
    try:
        api = PunchplayAPI()
        mt = 'movie' if str(media_type).lower() == 'movie' else 'show'
        # interact(show_status=None) OMITS the field server-side (no-op), so we
        # must send {"showStatus": null} explicitly via clear_status.
        res = api.clear_status(mt, tmdb_id, scope='title')
        xbmc.log(f'[PUNCHPLAY] Restore {mt} tmdb={tmdb_id}: {res}', xbmc.LOGINFO)
        if res is None:
            return False
        drop_remove_local(tmdb_id)
        try:
            threading.Thread(target=refresh_next_episode_punchplay, args=(str(tmdb_id),), daemon=True).start()
        except:
            pass
        return res is not None
    except Exception as e:
        xbmc.log(f'[PUNCHPLAY] restore_show error: {e}', xbmc.LOGERROR)
        return False

def is_in_watchlist(tmdb_id, media_type=None):
    try:
        _ensure_db()
        conn = get_connection()
        c = conn.cursor()
        if media_type:
            c.execute("SELECT status FROM punchplay_watchlist WHERE tmdb_id=? AND media_type=?", (str(tmdb_id), media_type))
        else:
            c.execute("SELECT status FROM punchplay_watchlist WHERE tmdb_id=?", (str(tmdb_id),))
        r = c.fetchone()
        conn.close()
        return r[0] if r else None
    except:
        return None

def watchlist_add_local(tmdb_id, media_type, status='watching', title='', year='', added_at=''):
    try:
        _ensure_db()
        conn = get_connection()
        c = conn.cursor()
        _db_exec_retry(c, "INSERT OR REPLACE INTO punchplay_watchlist (tmdb_id, media_type, status, added_at, title, year) VALUES (?,?,?,?,?,?)",
                       (str(tmdb_id), media_type, status, added_at or '', title or '', str(year or '')))
        _db_commit_retry(conn)
        conn.close()
    except:
        pass

def watchlist_remove_local(tmdb_id):
    try:
        _ensure_db()
        conn = get_connection()
        c = conn.cursor()
        _db_exec_retry(c, "DELETE FROM punchplay_watchlist WHERE tmdb_id=?", (str(tmdb_id),))
        _db_commit_retry(conn)
        conn.close()
    except:
        pass

def get_watchlist_local(status=None):
    try:
        _ensure_db()
        conn = get_connection()
        c = conn.cursor()
        if status:
            c.execute("SELECT tmdb_id, media_type, status, added_at, title, year, is_anime FROM punchplay_watchlist WHERE status=?", (status,))
        else:
            c.execute("SELECT tmdb_id, media_type, status, added_at, title, year, is_anime FROM punchplay_watchlist")
        rows = [{'tmdb_id': str(r[0]), 'media_type': r[1], 'status': r[2], 'added_at': r[3], 'title': r[4], 'year': r[5],
                 'is_anime': int(r[6] or 0)} for r in c.fetchall()]
        conn.close()
        return rows
    except:
        return []

def mark_as_watched_internal(tmdb_id, content_type, season=None, episode=None, notify=True, sync_punchplay=True, refresh_ui=True):
    from resources.lib import tmdb_api
    import threading
    tid = str(tmdb_id)
    conn = get_connection()
    c = conn.cursor()
    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')
    title_val = 'Unknown'
    try:
        if content_type == 'movie':
            details = tmdb_api.get_tmdb_item_details(tid, 'movie') or {}
            title_val = details.get('title', 'Unknown Movie')
        elif content_type in ('tv', 'episode', 'show', 'season'):
            show_details = tmdb_api.get_tmdb_item_details(tid, 'tv') or {}
            show_name = show_details.get('name', 'Unknown Show')
            if season is not None and episode is not None:
                title_val = f'{show_name} - S{int(season):02d}E{int(episode):02d}'
            elif season is not None:
                title_val = f'{show_name} - Sezonul {season}'
            else:
                title_val = show_name
    except:
        pass
    try:
        if content_type == 'movie':
            c.execute("INSERT OR REPLACE INTO punchplay_watched_movies (tmdb_id, title, year, last_watched_at) VALUES (?,?,?,?)",
                      (tid, title_val, str(now)[:4], now))
            c.execute("DELETE FROM punchplay_playback WHERE tmdb_id=? AND media_type='movie'", (tid,))
        elif season is not None and episode is not None:
            c.execute("INSERT OR REPLACE INTO punchplay_watched_episodes VALUES (?,?,?,?,?)",
                      (tid, int(season), int(episode), title_val, now))
            c.execute("DELETE FROM punchplay_playback WHERE tmdb_id=? AND season=? AND episode=?",
                      (tid, int(season), int(episode)))
        elif season is not None and episode is None:
            show_data = tmdb_api.get_tmdb_item_details(tid, 'tv')
            if show_data:
                rows = []
                for s in show_data.get('seasons', []):
                    if str(s.get('season_number')) == str(season):
                        ep_count = s.get('episode_count', 0)
                        if ep_count > 0:
                            for ep_num in range(1, ep_count + 1):
                                rows.append((tid, int(season), ep_num, title_val, now))
                        break
                if rows:
                    c.executemany("INSERT OR REPLACE INTO punchplay_watched_episodes VALUES (?,?,?,?,?)", rows)
                c.execute("DELETE FROM punchplay_playback WHERE tmdb_id=? AND season=?", (tid, int(season)))
        elif content_type in ('tv', 'show'):
            show_data = tmdb_api.get_tmdb_item_details(tid, 'tv')
            if show_data:
                rows = []
                clean_name = show_data.get('name', 'Unknown Show')
                total_eps = show_data.get('number_of_episodes', 0)
                for s in show_data.get('seasons', []):
                    s_num = s.get('season_number')
                    ep_count = s.get('episode_count', 0)
                    if s_num is None or ep_count == 0:
                        continue
                    for ep_num in range(1, ep_count + 1):
                        rows.append((tid, s_num, ep_num, clean_name, now))
                if rows:
                    c.executemany("INSERT OR REPLACE INTO punchplay_watched_episodes VALUES (?,?,?,?,?)", rows)
                c.execute("INSERT OR REPLACE INTO punchplay_fully_watched_shows (tmdb_id, total_episodes, last_watched_at) VALUES (?,?,?)",
                          (tid, total_eps, now))
                c.execute("DELETE FROM punchplay_playback WHERE tmdb_id=?", (tid,))
        conn.commit()
    except:
        pass
    finally:
        conn.close()
    try:
        from resources.lib import trakt_sync as _ts
        _ts.remove_local_progress(tid, content_type, season, episode)
    except:
        pass
    if notify:
        msg = f'[B][COLOR yellow]{title_val}[/COLOR][/B] marked watched on ' + provider_title('punchplay')
        xbmcgui.Dialog().notification(provider_title('punchplay'), msg, PUNCHPLAY_ICON, 3000, False)
    if sync_punchplay:
        threading.Thread(target=_sync_single_watched, args=(tmdb_id, content_type, season, episode), daemon=True).start()
    if content_type in ('tv', 'show', 'season', 'episode') or season is not None:
        try:
            threading.Thread(target=refresh_next_episode_punchplay, args=(tmdb_id,), daemon=True).start()
        except:
            pass
    from resources.lib.cache import clear_all_fast_cache
    try:
        clear_all_fast_cache()
    except:
        pass
    if refresh_ui:
        xbmc.executebuiltin('Container.Refresh')

def _sync_single_watched(tmdb_id, content_type, season=None, episode=None):
    try:
        api = PunchplayAPI()
        result = api.mark_watched(content_type, tmdb_id, season, episode)
        xbmc.log(f'[PUNCHPLAY] Push watched {content_type} tmdb={tmdb_id} S{season}E{episode}: {result}', xbmc.LOGINFO)
    except Exception as e:
        xbmc.log(f'[PUNCHPLAY] Push watched error tmdb={tmdb_id} S{season}E{episode}: {e}', xbmc.LOGERROR)

def mark_as_unwatched_internal(tmdb_id, content_type, season=None, episode=None, notify=True, sync_punchplay=True, refresh_ui=True):
    import threading
    tid = str(tmdb_id)
    conn = get_connection()
    c = conn.cursor()
    title_display = 'Element'
    try:
        if content_type == 'movie':
            c.execute("SELECT title FROM punchplay_watched_movies WHERE tmdb_id=?", (tid,))
            r = c.fetchone()
            if r:
                title_display = r[0]
        elif season is not None and episode is not None:
            c.execute("SELECT title FROM punchplay_watched_episodes WHERE tmdb_id=? LIMIT 1", (tid,))
            r = c.fetchone()
            if r:
                base_title = r[0].split(' - S')[0]
                title_display = f'{base_title} - S{int(season):02d}E{int(episode):02d}'
            else:
                title_display = f'S{season}E{episode}'
        elif season is not None:
            c.execute("SELECT title FROM punchplay_watched_episodes WHERE tmdb_id=? LIMIT 1", (tid,))
            r = c.fetchone()
            if r:
                base_title = r[0].split(' - S')[0]
                title_display = f'{base_title} - Sezonul {season}'
            else:
                from resources.lib import tmdb_api
                show_details = tmdb_api.get_tmdb_item_details(tid, 'tv') or {}
                title_display = f"{show_details.get('name', 'Serial')} - Sezonul {season}"
        elif content_type in ('tv', 'show'):
            from resources.lib import tmdb_api
            show_details = tmdb_api.get_tmdb_item_details(tid, 'tv') or {}
            title_display = show_details.get('name', 'Serial')
    except:
        pass
    try:
        if content_type == 'movie':
            c.execute("DELETE FROM punchplay_watched_movies WHERE tmdb_id=?", (tid,))
        elif season is not None and episode is not None:
            c.execute("DELETE FROM punchplay_watched_episodes WHERE tmdb_id=? AND season=? AND episode=?",
                      (tid, int(season), int(episode)))
        elif season is not None:
            c.execute("DELETE FROM punchplay_watched_episodes WHERE tmdb_id=? AND season=?", (tid, int(season)))
        elif content_type in ('tv', 'show'):
            c.execute("DELETE FROM punchplay_watched_episodes WHERE tmdb_id=?", (tid,))
            c.execute("DELETE FROM punchplay_fully_watched_shows WHERE tmdb_id=?", (tid,))
        conn.commit()
    except:
        pass
    finally:
        conn.close()
    try:
        from resources.lib import trakt_sync as _ts
        _ts.remove_local_progress(tid, content_type, season, episode)
    except:
        pass
    if notify:
        msg = f'[B][COLOR yellow]{title_display}[/COLOR][/B] marked unwatched on ' + provider_title('punchplay')
        xbmcgui.Dialog().notification(provider_title('punchplay'), msg, PUNCHPLAY_ICON, 3000, False)
    if sync_punchplay:
        threading.Thread(target=_sync_single_unwatched, args=(tmdb_id, content_type, season, episode), daemon=True).start()
    if content_type in ('tv', 'show', 'season', 'episode') or season is not None:
        try:
            threading.Thread(target=refresh_next_episode_punchplay, args=(tmdb_id,), daemon=True).start()
        except:
            pass
    from resources.lib.cache import clear_all_fast_cache
    try:
        clear_all_fast_cache()
    except:
        pass
    if refresh_ui:
        xbmc.executebuiltin('Container.Refresh')

def _sync_single_unwatched(tmdb_id, content_type, season=None, episode=None):
    try:
        api = PunchplayAPI()
        result = api.mark_unwatched(content_type, tmdb_id, season, episode)
        xbmc.log(f'[PUNCHPLAY] Push unwatched {content_type} tmdb={tmdb_id} S{season}E{episode}: {result}', xbmc.LOGINFO)
    except Exception as e:
        xbmc.log(f'[PUNCHPLAY] Push unwatched error tmdb={tmdb_id} S{season}E{episode}: {e}', xbmc.LOGERROR)

def _trigger_ui_refresh():
    try:
        from resources.lib.watched_provider import refresh_ui
        refresh_ui()
    except:
        pass

def refresh_next_episode_punchplay(tmdb_id, ignore_hidden=False):
    from resources.lib import tmdb_api
    import datetime

    def _local_trigger():
        try:
            try:
                from resources.lib.cache import clear_all_fast_cache
                clear_all_fast_cache()
            except:
                pass
            import xbmc
            import xbmcgui
            import time
            try:
                _binge_since = float(xbmcgui.Window(10000).getProperty('tmdbmovies.binge_open') or 0)
            except:
                _binge_since = 0.0
            if _binge_since > 0 and time.time() - _binge_since < 120:
                return
            container_path = xbmc.getInfoLabel('Container.FolderPath')
            if not container_path or 'plugin.video.tmdbmovies' in container_path.lower():
                xbmc.executebuiltin("Container.Refresh")
                xbmcgui.Window(10000).setProperty('tmdbmovies.last_upnext_refresh', str(time.time()))
        except:
            pass

    try:
        tid = str(tmdb_id)
        show_details = tmdb_api.get_tmdb_item_details(tid, 'tv', lightweight=True, skip_localization=True)
        if not show_details:
            show_details = tmdb_api.get_tmdb_item_details(tid, 'tv')
        if not show_details:
            return
        show_title = show_details.get('name', 'Unknown Show')
        if not os.path.exists(DB_PATH):
            return
        conn = get_connection()
        c = conn.cursor()
        if not ignore_hidden:
            c.execute("SELECT 1 FROM punchplay_dropped WHERE tmdb_id=?", (tid,))
            if c.fetchone():
                try:
                    _db_exec_retry(conn, "DELETE FROM punchplay_next_episodes WHERE tmdb_id=?", (tid,))
                    _db_commit_retry(conn)
                except:
                    pass
                try: conn.close()
                except: pass
                _local_trigger()
                return
        c.execute("SELECT season, episode FROM punchplay_watched_episodes WHERE tmdb_id=?", (tid,))
        watched_eps = set((r[0], r[1]) for r in c.fetchall())
        c.execute("SELECT season, episode FROM punchplay_watched_episodes WHERE tmdb_id=? ORDER BY last_watched_at DESC LIMIT 1", (tid,))
        last_row = c.fetchone()
        if not watched_eps:
            try:
                c.execute("SELECT 1 FROM punchplay_watchlist WHERE tmdb_id=?", (tid,))
                in_wl = bool(c.fetchone())
            except:
                in_wl = False
            if in_wl:
                from resources.lib.trakt_sync import _tmdb_first_episode as _first, _tmdb_ep_meta as _meta
                nxt = _first(show_details)
                if nxt:
                    ep_title, _, air_date = _meta(tid, nxt['season'], nxt['number'])
                    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
                    _db_exec_retry(c, "INSERT OR REPLACE INTO punchplay_next_episodes (tmdb_id, show_title, season, episode, ep_title, air_date, watched_count, total_count, last_watched_at) VALUES (?,?,?,?,?,?,?,?,?)", (tid, show_title, nxt['season'], nxt['number'], ep_title, air_date, 0, 0, now_str))
                    _db_commit_retry(conn)
                    try: conn.close()
                    except: pass
                    _local_trigger(); return
            try:
                _db_exec_retry(conn, "DELETE FROM punchplay_next_episodes WHERE tmdb_id=?", (tid,))
                _db_commit_retry(conn)
            except:
                pass
            try: conn.close()
            except: pass
            _local_trigger()
            return
        next_ep = None
        if last_row:
            last_s, last_e = last_row[0], last_row[1]
            for s in show_details.get('seasons', []):
                s_num = s.get('season_number')
                if s_num == 0 or s_num < last_s:
                    continue
                ep_count = s.get('episode_count', 0)
                start_ep = (last_e + 1) if s_num == last_s else 1
                for e_num in range(start_ep, ep_count + 1):
                    if (s_num, e_num) not in watched_eps:
                        next_ep = {'season': s_num, 'number': e_num}
                        break
                if next_ep:
                    break
        if not next_ep:
            for s in show_details.get('seasons', []):
                s_num = s.get('season_number')
                if s_num == 0:
                    continue
                ep_count = s.get('episode_count', 0)
                for e_num in range(1, ep_count + 1):
                    if (s_num, e_num) not in watched_eps:
                        next_ep = {'season': s_num, 'number': e_num}
                        break
                if next_ep:
                    break
        if not next_ep:
            try:
                _db_exec_retry(conn, "DELETE FROM punchplay_next_episodes WHERE tmdb_id=?", (tid,))
                _db_commit_retry(conn)
            except:
                pass
            try: conn.close()
            except: pass
            _local_trigger()
            return
        season_data = tmdb_api.get_smart_season_details(tid, next_ep['season'])
        ep_title = ''
        air_date = ''
        if season_data:
            for ep in season_data.get('episodes', []):
                if ep.get('episode_number') == next_ep['number']:
                    ep_title = ep.get('name', '')
                    air_date_raw = ep.get('air_date', '')
                    if air_date_raw:
                        air_date = air_date_raw.split('T')[0]
                    break
        now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        _db_exec_retry(c,
            "INSERT OR REPLACE INTO punchplay_next_episodes "
            "(tmdb_id, show_title, season, episode, ep_title, air_date, watched_count, total_count, last_watched_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (tid, show_title, next_ep['season'], next_ep['number'],
             ep_title, air_date, len(watched_eps),
             show_details.get('number_of_episodes', 0), now_str))
        _db_commit_retry(conn)
        try: conn.close()
        except: pass
        _local_trigger()
    except Exception as e:
        xbmc.log(f'[PUNCHPLAY] refresh_next_episode_punchplay error: {e}', xbmc.LOGERROR)

def _is_anime_entry(it):
    try:
        for k in ('isAnime', 'is_anime', 'anime'):
            v = it.get(k)
            if v is True or str(v).lower() in ('1', 'true'):
                return 1
    except:
        pass
    return 0

def _pick(d, *keys, default=''):
    for k in keys:
        try:
            v = d.get(k)
        except:
            v = None
        if v is not None and v != '':
            return v
    return default

def _store_history_snapshot(items, c):
    movies = []
    episodes = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        tmdb_id = _pick(it, 'tmdbId', 'tmdb_id', default=0)
        try:
            tmdb_id = int(tmdb_id or 0)
        except:
            continue
        if not tmdb_id:
            continue
        itype = str(_pick(it, 'type', default='')).lower()
        watched_at = _pick(it, 'watchedAt', 'watched_at', default='')
        title = _pick(it, 'title', default='')
        year = _pick(it, 'year', default='')
        if itype == 'movie':
            movies.append((str(tmdb_id), str(title), str(year), str(watched_at), '', '', ''))
        elif itype == 'episode':
            s = _pick(it, 'season', default=0)
            e = _pick(it, 'episode', default=0)
            try:
                s, e = int(s or 0), int(e or 0)
            except:
                continue
            if not s or not e:
                continue
            episodes.append((str(tmdb_id), s, e, str(title), str(watched_at)))
    if not movies and not episodes:
        try:
            _lm = c.execute("SELECT (SELECT COUNT(*) FROM punchplay_watched_movies) + (SELECT COUNT(*) FROM punchplay_watched_episodes)").fetchone()[0] or 0
        except:
            _lm = 0
        if _lm > 0:
            xbmc.log('[PUNCHPLAY SYNC] History: empty server response with non-empty local mirror, keeping local data', xbmc.LOGWARNING)
            return 0, 0
    c.execute("DELETE FROM punchplay_watched_movies")
    if movies:
        c.executemany("INSERT OR REPLACE INTO punchplay_watched_movies (tmdb_id, title, year, last_watched_at, poster, backdrop, overview) VALUES (?,?,?,?,?,?,?)", movies)
    c.execute("DELETE FROM punchplay_watched_episodes")
    if episodes:
        c.executemany("INSERT OR REPLACE INTO punchplay_watched_episodes (tmdb_id, season, episode, title, last_watched_at) VALUES (?,?,?,?,?)", episodes)
    return len(movies), len(episodes)

def _store_interaction_snapshot(items, c):
    ratings = []
    dropped = []
    favourites = []
    try:
        from collections import Counter as _Counter
        _statuses = _Counter()
        for _it in items or []:
            if isinstance(_it, dict):
                _statuses[str(_it.get('showStatus') or _it.get('show_status') or '-')] += 1
        xbmc.log(f'[PUNCHPLAY DBG] interaction items={len(items or [])} statuses={dict(_statuses)} '
                 f'sample_keys={list((items or [{}])[0].keys()) if items else []}', xbmc.LOGINFO)
        try:
            import json as _js
            xbmc.log(f'[PUNCHPLAY DBG] first_item={_js.dumps((items or [{}])[0])[:1500]}', xbmc.LOGINFO)
        except:
            pass
    except:
        pass
    for it in items or []:
        if not isinstance(it, dict):
            continue
        tmdb_id = _pick(it, 'tmdbId', 'tmdb_id', 'sourceId', 'source_id', default=0)
        try:
            tmdb_id = int(tmdb_id or 0)
        except:
            continue
        if not tmdb_id:
            continue
        kind = str(_pick(it, 'kind', default='show')).lower()
        media_type = 'movie' if kind == 'movie' else 'show'
        scope = str(_pick(it, 'scope', default='title')).lower()
        s = _pick(it, 'season', default=0) or 0
        e = _pick(it, 'episode', default=0) or 0
        try:
            s, e = int(s), int(e)
        except:
            s, e = 0, 0
        rating = _pick(it, 'rating', default=None)
        try:
            rating = int(rating) if rating is not None else None
        except:
            rating = None
        rated_at = _pick(it, 'ratedAt', 'rated_at', 'updatedAt', 'updated_at', default='')
        status = _pick(it, 'showStatus', 'show_status', default=None)
        if rating:
            ratings.append((str(tmdb_id), media_type, s, e, rating, str(rated_at), _is_anime_entry(it),
                            str(_pick(it, 'title', 'name', default='') or '')))
        if status == 'DROPPED' and scope in ('title', 'series'):
            dropped.append((str(tmdb_id), str(rated_at)))
        try:
            fav = bool(it.get('isFavourite'))
        except:
            fav = False
        if fav and scope in ('title', 'series'):
            favourites.append((str(tmdb_id), media_type))
    if not ratings and not dropped and not favourites:
        try:
            _lm = c.execute("SELECT (SELECT COUNT(*) FROM punchplay_ratings) + (SELECT COUNT(*) FROM punchplay_dropped) + (SELECT COUNT(*) FROM punchplay_favourites)").fetchone()[0] or 0
        except:
            _lm = 0
        if _lm > 0:
            xbmc.log('[PUNCHPLAY SYNC] Interaction: empty server response with non-empty local mirror, keeping local data', xbmc.LOGWARNING)
            return 0, 0
    c.execute("DELETE FROM punchplay_ratings")
    if ratings:
        c.executemany("INSERT OR REPLACE INTO punchplay_ratings (tmdb_id, media_type, season, episode, rating, rated_at, is_anime, title) VALUES (?,?,?,?,?,?,?,?)", ratings)
    try:
        kept = {str(r[0]): (r[1] or '') for r in
                c.execute("SELECT tmdb_id, title FROM punchplay_dropped").fetchall()}
    except:
        kept = {}
    c.execute("DELETE FROM punchplay_dropped")
    if dropped:
        c.executemany("INSERT OR REPLACE INTO punchplay_dropped (tmdb_id, dropped_at, title) VALUES (?,?,?)",
                      [(t, d, kept.get(str(t), '')) for t, d in dropped])
    try:
        c.execute("DELETE FROM punchplay_favourites")
        if favourites:
            c.executemany("INSERT OR REPLACE INTO punchplay_favourites (tmdb_id, media_type) VALUES (?,?)", favourites)
    except Exception as e:
        xbmc.log(f'[PUNCHPLAY] favourites store error: {e}', xbmc.LOGERROR)
    return len(ratings), len(dropped)

def _sync_watchlist_list(api, c, lists):
    watch_id = None
    for lst in lists or []:
        if isinstance(lst, dict) and lst.get('isWatchlist'):
            watch_id = lst.get('id')
            break
    if watch_id is None:
        try:
            watch_id = api.get_watchlist_id()
        except:
            watch_id = None
    wl_rows = []
    if watch_id is not None:
        detail_items = None
        try:
            detail = api.get_list(watch_id)
            try:
                _di = (detail or {}).get('items') or []
                xbmc.log(f'[PUNCHPLAY DBG] watchlist detail keys={list(detail.keys()) if isinstance(detail, dict) else type(detail)} '
                         f'itemCount={detail.get("itemCount") if isinstance(detail, dict) else "?"} '
                         f'items_type={type((detail or {}).get("items")).__name__} '
                         f'items_len={len(_di)} '
                         f'first_keys={list(_di[0].keys()) if _di and isinstance(_di[0], dict) else "-"}', xbmc.LOGINFO)
            except:
                pass
            if isinstance(detail, dict) and isinstance(detail.get('items'), list):
                detail_items = detail.get('items')
        except:
            detail_items = None
        if detail_items:
            for it in detail_items:
                if not isinstance(it, dict):
                    continue
                try:
                    tmdb_id = int(it.get('tmdbId') or 0)
                except:
                    continue
                if not tmdb_id:
                    continue
                kind = str(it.get('type') or '').lower()
                media_type = 'movie' if kind == 'movie' else 'tv'
                wl_rows.append((str(tmdb_id), media_type, 'watching',
                                str(it.get('addedAt') or ''), str(it.get('title') or ''), '',
                                _is_anime_entry(it)))
        else:
            offset = 0
            for _ in range(100):
                try:
                    data = api.get_list_items(watch_id, offset=offset, limit=200)
                except:
                    data = None
                if not isinstance(data, dict):
                    break
                for it in data.get('items') or []:
                    if not isinstance(it, dict):
                        continue
                    try:
                        tmdb_id = int(it.get('tmdbId') or 0)
                    except:
                        continue
                    if not tmdb_id:
                        continue
                    kind = str(it.get('type') or '').lower()
                    media_type = 'movie' if kind == 'movie' else 'tv'
                    wl_rows.append((str(tmdb_id), media_type, 'watching',
                                    str(it.get('addedAt') or ''), str(it.get('title') or ''), '',
                                    _is_anime_entry(it)))
                try:
                    total = int(data.get('total') or 0)
                except:
                    total = 0
                offset += 200
                nxt = data.get('nextOffset')
                if nxt is None or (total and offset >= total):
                    break
                try:
                    offset = int(nxt)
                except:
                    pass
    if not wl_rows and watch_id is not None:
        try:
            _lm = c.execute("SELECT COUNT(*) FROM punchplay_watchlist").fetchone()[0] or 0
        except:
            _lm = 0
        if _lm > 0:
            xbmc.log('[PUNCHPLAY SYNC] Watchlist: empty server response with non-empty local mirror, keeping local data', xbmc.LOGWARNING)
            return watch_id, 0
    c.execute("DELETE FROM punchplay_watchlist")
    if wl_rows:
        c.executemany("INSERT OR REPLACE INTO punchplay_watchlist (tmdb_id, media_type, status, added_at, title, year, is_anime) VALUES (?,?,?,?,?,?,?)", wl_rows)
    try:
        todo = [(t, m) for t, m, _s, _a, _ti, _y, _an in wl_rows if not _ti]
        if todo:
            from resources.lib import tmdb_api as _tapi
            import concurrent.futures as _cf

            def _one(pair):
                t, m = pair
                try:
                    d = _tapi.get_tmdb_item_details(str(t), 'movie' if m == 'movie' else 'tv', lightweight=True, skip_localization=True) or {}
                    title = d.get('title') or d.get('name') or ''
                    if not title:
                        return None
                    year = str(d.get('release_date') or d.get('first_air_date') or '')[:4]
                    return (title, year, str(t))
                except:
                    return None

            with _cf.ThreadPoolExecutor(max_workers=10) as _ex:
                for _r in _ex.map(_one, todo[:500]):
                    try:
                        if _r:
                            _db_exec_retry(c, "UPDATE punchplay_watchlist SET title=?, year=? WHERE tmdb_id=?", _r)
                    except:
                        pass
    except:
        pass
    return watch_id, len(wl_rows)

def _store_collection_snapshot(items, c):
    try:
        conn = c.connection
    except:
        conn = None
    try:
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='punchplay_collection'")
        has_tbl = bool(c.fetchone())
    except:
        has_tbl = False
    _fresh_tbl = not has_tbl
    if not has_tbl:
        try:
            c.execute('''CREATE TABLE IF NOT EXISTS punchplay_collection
                         (tmdb_id TEXT, media_type TEXT, title TEXT, year TEXT, added_at TEXT,
                          UNIQUE(tmdb_id, media_type))''')
        except:
            pass
    rows = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        tmdb_id = _pick(it, 'tmdbId', 'tmdb_id', default=0)
        try:
            tmdb_id = int(tmdb_id or 0)
        except:
            continue
        if not tmdb_id:
            continue
        kind = str(_pick(it, 'kind', 'type', default='show')).lower()
        media_type = 'movie' if kind == 'movie' else 'tv'
        rows.append((str(tmdb_id), media_type, str(_pick(it, 'title', default='')),
                     str(_pick(it, 'year', default='')), str(_pick(it, 'addedAt', 'added_at', default=''))))
    if not rows:
        try:
            _lm = c.execute("SELECT COUNT(*) FROM punchplay_collection").fetchone()[0] or 0
        except:
            _lm = 0
        if _lm > 0:
            xbmc.log('[PUNCHPLAY SYNC] Collection: empty server response with non-empty local mirror, keeping local data', xbmc.LOGWARNING)
            return 0
    try:
        if not _fresh_tbl:
            c.execute("DELETE FROM punchplay_collection")
        if rows:
            c.executemany("INSERT OR REPLACE INTO punchplay_collection (tmdb_id, media_type, title, year, added_at) VALUES (?,?,?,?,?)", rows)
    except:
        pass
    return len(rows)

def _store_playback_snapshot(items, c):
    # FIX "()" in In Progress: nu mai suprascriem metadatele locale (title/year/poster)
    # cu randuri goale de pe server. Completam din itemul serverului sau din TMDb,
    # pastram titlul/anul/posterul locale non-vida si resume-ul local in secunde exacte.
    # 0. Snapshot local (playback_progress traieste in trakt_sync.db, nu in DB-ul PunchPlay)
    local_meta = {}
    try:
        from resources.lib import trakt_sync as _ts0
        _conn0 = _ts0.get_connection()
        _c0 = _conn0.cursor()
        for r in _c0.execute("SELECT tmdb_id, media_type, season, episode, progress, title, year, poster FROM playback_progress").fetchall():
            try:
                local_meta[(str(r[0]), str(r[1]), int(r[2] or 0), int(r[3] or 0))] = (
                    float(r[4] or 0), r[5] or '', r[6] or '', r[7] or '')
            except:
                continue
        try:
            _conn0.close()
        except:
            pass
    except:
        local_meta = {}

    rows = []
    missing_title = []  # (index, tmdb_id, media_type) pentru completare TMDb
    for it in items or []:
        if not isinstance(it, dict):
            continue
        itype = str(_pick(it, 'type', default='')).lower()
        if itype == 'movie':
            tmdb_id = _pick(it, 'tmdbId', 'tmdb_id', default=0)
            try:
                tmdb_id = int(tmdb_id or 0)
            except:
                continue
            if not tmdb_id:
                continue
            rows.append([str(tmdb_id), 'movie', 0, 0,
                         float(_pick(it, 'progressPercent', 'progress_percent', default=0) or 0),
                         str(_pick(it, 'updatedAt', 'updated_at', default='')),
                         str(_pick(it, 'title', 'movieTitle', default='') or ''),
                         str(_pick(it, 'year', 'releaseYear', default='') or '')])
            if not rows[-1][6]:
                missing_title.append((len(rows) - 1, str(tmdb_id), 'movie'))
        elif itype == 'episode':
            tmdb_id = _pick(it, 'showTmdbId', 'show_tmdb_id', 'tmdbId', 'tmdb_id', default=0)
            try:
                tmdb_id = int(tmdb_id or 0)
            except:
                continue
            if not tmdb_id:
                continue
            s = _pick(it, 'season', default=0) or 0
            e = _pick(it, 'episode', default=0) or 0
            try:
                s, e = int(s), int(e)
            except:
                continue
            rows.append([str(tmdb_id), 'episode', s, e,
                         float(_pick(it, 'progressPercent', 'progress_percent', default=0) or 0),
                         str(_pick(it, 'updatedAt', 'updated_at', default='')),
                         str(_pick(it, 'title', 'showTitle', default='') or ''),
                         str(_pick(it, 'year', 'firstAirYear', default='') or '')])
            if not rows[-1][6]:
                missing_title.append((len(rows) - 1, str(tmdb_id), 'tv'))

    # 1. Completare titlu/an lipsa din TMDb (thread pool mic, lightweight)
    if missing_title:
        try:
            from resources.lib.tmdb_api import get_tmdb_item_details as _pp_details
            import concurrent.futures as _pp_cf

            def _pp_fill(_mt_):
                _idx, _tid, _mt = _mt_
                try:
                    d = _pp_details(_tid, _mt, lightweight=True, skip_localization=True) or {}
                    if _mt == 'movie':
                        rows[_idx][6] = d.get('title') or rows[_idx][6]
                        if not rows[_idx][7]:
                            rows[_idx][7] = str(d.get('release_date') or '')[:4]
                    else:
                        rows[_idx][6] = d.get('name') or rows[_idx][6]
                        if not rows[_idx][7]:
                            rows[_idx][7] = str(d.get('first_air_date') or '')[:4]
                except:
                    pass

            with _pp_cf.ThreadPoolExecutor(max_workers=5) as _pp_ex:
                list(_pp_ex.map(_pp_fill, missing_title))
        except:
            pass

    # 2. Merge cu meta locala: titlu/an/poster locale non-vida + secunde exacte locale
    merged = []
    for r in rows:
        tid, mt, s, e, prog, upd, title, year = r
        loc = local_meta.get((tid, mt, s, e))
        if loc:
            lprog, ltitle, lyear, lposter = loc
            if lprog >= 1000000:
                prog = lprog  # pastram resume-ul local in secunde exacte (nu-l coboram la % server)
            if not title:
                title = ltitle
            if not year:
                year = lyear
        merged.append((tid, mt, s, e, prog, upd, title, year, loc[3] if loc else ''))

    c.execute("DELETE FROM punchplay_playback")
    if merged:
        c.executemany("INSERT OR REPLACE INTO punchplay_playback (tmdb_id, media_type, season, episode, progress, updated_at) VALUES (?,?,?,?,?,?)",
                      [(m[0], m[1], m[2], m[3], m[4], m[5]) for m in merged])
    try:
        from resources.lib import trakt_sync as _ts
        tconn = _ts.get_connection()
        tc = tconn.cursor()
        for tid, mt, s, e, prog, upd, title, year, poster in merged:
            try:
                if 1 < float(prog or 0) < 99:
                    tc.execute("INSERT OR REPLACE INTO playback_progress (tmdb_id, media_type, season, episode, progress, paused_at, title, year, poster) VALUES (?,?,?,?,?,?,?,?,?)",
                               (tid, mt, s, e, float(prog), upd, title, year, poster or ''))
            except:
                pass
        tconn.commit()
        tconn.close()
    except:
        pass
    return len(merged)

def _enrich_air_dates(rows):
    from resources.lib import tmdb_api
    import concurrent.futures

    def _one(row):
        try:
            tid, show_title, season, episode, ep_title, air_date, wc, tc, last_at = row
            if air_date and ep_title:
                return row
            data = tmdb_api.get_smart_season_details(str(tid), int(season))
            if not data:
                return row
            for ep in data.get('episodes', []):
                if ep.get('episode_number') == int(episode):
                    if not ep_title:
                        ep_title = ep.get('name', '') or ep_title
                    raw = ep.get('air_date', '') or ''
                    if not air_date and raw:
                        air_date = raw.split('T')[0]
                    break
            return (tid, show_title, season, episode, ep_title, air_date, wc, tc, last_at)
        except:
            return row

    out = []
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
            futs = [ex.submit(_one, r) for r in rows]
            for f in concurrent.futures.as_completed(futs, timeout=30):
                try:
                    out.append(f.result())
                except:
                    pass
    except:
        out = rows
    return out if out else rows

def _sync_up_next(api, c):
    try:
        data = api.continue_watching()
    except:
        data = None
    if not isinstance(data, list):
        return 0
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    rows = []
    for it in data:
        if not isinstance(it, dict):
            continue
        try:
            tmdb_id = int(it.get('showTmdbId') or it.get('sourceId') or 0)
        except:
            continue
        if not tmdb_id:
            continue
        watched = int(it.get('totalEpisodesWatched') or 0)
        avail = int(it.get('totalEpisodesAvailable') or 0)
        if avail > 0 and watched >= avail:
            continue
        ns = it.get('nextSeason')
        ne = it.get('nextEpisode')
        ep_title = it.get('nextEpisodeTitle') or ''
        air_date = ''
        if ns is None or ne is None:
            nta = it.get('nextEpisodeToAir') or {}
            try:
                ns = int(nta.get('season')) if nta.get('season') is not None else None
                ne = int(nta.get('episode')) if nta.get('episode') is not None else None
            except:
                ns, ne = None, None
            if not ep_title:
                ep_title = nta.get('name') or ''
            raw = nta.get('airDate') or nta.get('air_date') or ''
            if raw:
                air_date = str(raw).split('T')[0]
        if ns is None or ne is None:
            continue
        try:
            ns, ne = int(ns), int(ne)
        except:
            continue
        rows.append((str(tmdb_id), str(it.get('title') or ''), ns, ne, str(ep_title or ''),
                     str(air_date or ''), watched, avail, str(it.get('lastWatchedAt') or now_str)))
    try:
        have = {r[0] for r in rows}
        for w in get_watchlist_local() or []:
            try:
                if str(w.get('media_type') or '') != 'tv':
                    continue
                if str(w.get('status') or '') not in ('watching', 'plantowatch'):
                    continue
                tid = str(w.get('tmdb_id') or '')
                if not tid or tid in have:
                    continue
                if is_fully_watched_show(tid):
                    continue
                if get_watched_episodes_count(tid) > 0:
                    continue
                rows.append((tid, str(w.get('title') or ''), 1, 1, '', '',
                             0, 0, str(w.get('added_at') or now_str)))
                have.add(tid)
            except:
                pass
    except:
        pass
    rows = _enrich_air_dates(rows)
    c.execute("DELETE FROM punchplay_next_episodes")
    if rows:
        c.executemany("INSERT OR REPLACE INTO punchplay_next_episodes (tmdb_id, show_title, season, episode, ep_title, air_date, watched_count, total_count, last_watched_at) VALUES (?,?,?,?,?,?,?,?,?)", rows)
    return len(rows)

def get_next_episodes_from_db():
    try:
        _ensure_db()
        conn = get_connection()
        c = conn.cursor()
        c.execute("""SELECT tmdb_id, show_title, season, episode, ep_title, air_date, watched_count, total_count, last_watched_at
                     FROM punchplay_next_episodes
                     WHERE tmdb_id NOT IN (SELECT tmdb_id FROM punchplay_dropped)
                     ORDER BY last_watched_at DESC""")
        rows = []
        for r in c.fetchall():
            rows.append({'tmdb_id': str(r[0]), 'show_title': r[1] or '', 'season': r[2] or 0, 'episode': r[3] or 0,
                         'ep_title': r[4] or '', 'air_date': r[5] or '', 'watched_count': r[6] or 0,
                         'total_count': r[7] or 0, 'last_watched_at': r[8] or ''})
        conn.close()
        return rows
    except:
        return []

def get_in_progress_tvshows_from_db():
    try:
        _ensure_db()
        conn = get_connection()
        c = conn.cursor()
        c.execute("""SELECT tmdb_id, show_title, season, episode, ep_title, air_date, watched_count, total_count, last_watched_at
                     FROM punchplay_next_episodes
                     WHERE tmdb_id NOT IN (SELECT tmdb_id FROM punchplay_dropped)
                     AND watched_count > 0 AND (total_count = 0 OR watched_count < total_count)
                     ORDER BY last_watched_at DESC""")
        rows = []
        for r in c.fetchall():
            rows.append({'tmdb_id': str(r[0]), 'show_title': r[1] or '', 'season': r[2] or 0, 'episode': r[3] or 0,
                         'ep_title': r[4] or '', 'air_date': r[5] or '', 'watched_count': r[6] or 0,
                         'total_count': r[7] or 0, 'last_watched_at': r[8] or ''})
        conn.close()
        return rows
    except:
        return []

def _precache_up_next(items):
    try:
        from resources.lib import tmdb_api
        import concurrent.futures
        ids = []
        for it in items or []:
            tid = str(it.get('tmdb_id') or '')
            if tid and tid not in ids:
                ids.append(tid)
        if not ids:
            return
        def _fetch(tid):
            try:
                tmdb_api.get_tmdb_item_details(tid, 'tv')
            except:
                pass
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
            futs = [ex.submit(_fetch, t) for t in ids[:50]]
            for f in concurrent.futures.as_completed(futs, timeout=20):
                try:
                    f.result()
                except:
                    pass
    except:
        pass

_CAL_PREV = [0, 1, 3, 7, 14, 30]
_CAL_FUT = [7, 14, 21, 30, 60, 90]

def _calendar_months():
    try:
        prev_idx = int(ADDON.getSetting('mdblist_cal_previous_days') or '3')
        fut_idx = int(ADDON.getSetting('mdblist_cal_future_days') or '0')
    except:
        prev_idx, fut_idx = 3, 0
    try:
        prev_days = _CAL_PREV[prev_idx] if 0 <= prev_idx < len(_CAL_PREV) else 7
    except:
        prev_days = 7
    try:
        fut_days = _CAL_FUT[fut_idx] if 0 <= fut_idx < len(_CAL_FUT) else 7
    except:
        fut_days = 7
    today = datetime.date.today()
    start = today - datetime.timedelta(days=prev_days)
    end = today + datetime.timedelta(days=fut_days)
    months = []
    d = datetime.date(start.year, start.month, 1)
    while d <= end:
        months.append(d.strftime('%Y-%m'))
        if d.month == 12:
            d = datetime.date(d.year + 1, 1, 1)
        else:
            d = datetime.date(d.year, d.month + 1, 1)
    return months

def _sync_calendar(api):
    try:
        if get_cached('calendar', ttl=86400) is not None:
            return True
    except:
        pass
    merged = {'days': []}
    try:
        for month in _calendar_months():
            try:
                data = api.get_calendar(month)
            except:
                data = None
            if not isinstance(data, dict):
                continue
            for day in data.get('days') or []:
                if isinstance(day, dict):
                    merged['days'].append(day)
    except:
        pass
    set_cached('calendar', merged)
    return True

def get_calendar_local():
    data = get_cached('calendar', ttl=86400)
    if isinstance(data, dict):
        return data
    return {'days': []}

SYNC_LOCK_KEY = 'punchplay_sync_active'

def _acquire_lock():
    try:
        v = get_sync_meta(SYNC_LOCK_KEY, '')
        if v:
            try:
                locked = (time.time() - float(v)) < 600
            except:
                locked = (v == '1')
            if locked:
                return False
            xbmc.log('[PUNCHPLAY SYNC] Stale lock detected. Clearing and proceeding.', xbmc.LOGWARNING)
        set_sync_meta(SYNC_LOCK_KEY, str(time.time()))
        return True
    except:
        return True

def _release_lock():
    try:
        set_sync_meta(SYNC_LOCK_KEY, '')
    except:
        pass

def _snapshot_all(api, resource, limit=500):
    items = []
    after = 0
    while True:
        try:
            data = api.sync_snapshot(resource, after=after, limit=limit)
        except:
            data = None
        if not isinstance(data, dict):
            break
        batch = data.get('items') or []
        items.extend([b for b in batch if isinstance(b, dict)])
        if not data.get('hasMore'):
            break
        try:
            after = int(data.get('nextAfter') or 0)
        except:
            break
        if after <= 0:
            break
    return items

def _full_rebuild(api, c, is_active, p_dialog=None):
    def _upd(pct, section):
        try:
            if p_dialog:
                p_dialog.update(pct, provider_title('punchplay', name='PunchPlay Sync'),
                                'Sync: [B][COLOR %s]%s[/COLOR][/B]' % (PUNCHPLAY_COLOR, section))
        except:
            pass
    try:
        hist = _snapshot_all(api, 'history')
        m, e = _store_history_snapshot(hist, c)
        xbmc.log(f'[PUNCHPLAY SYNC] History: {m} movies, {e} episodes.', xbmc.LOGINFO)
        _upd(25, 'History')
    except Exception as ex:
        xbmc.log(f'[PUNCHPLAY SYNC] History error: {ex}', xbmc.LOGERROR)
    try:
        lists = _snapshot_all(api, 'list')
        wid, wn = _sync_watchlist_list(api, c, lists)
        xbmc.log(f'[PUNCHPLAY SYNC] Watchlist id={wid}: {wn} items.', xbmc.LOGINFO)
        _upd(45, 'Watchlist')
    except Exception as ex:
        xbmc.log(f'[PUNCHPLAY SYNC] Lists error: {ex}', xbmc.LOGERROR)
    try:
        inter = _snapshot_all(api, 'interaction')
        r, d = _store_interaction_snapshot(inter, c)
        xbmc.log(f'[PUNCHPLAY SYNC] Ratings: {r}, dropped: {d}.', xbmc.LOGINFO)
        _backfill_ratings_titles_en()
        _upd(60, 'Ratings')
    except Exception as ex:
        xbmc.log(f'[PUNCHPLAY SYNC] Interaction error: {ex}', xbmc.LOGERROR)
    try:
        coll = _snapshot_all(api, 'collection')
        cn = _store_collection_snapshot(coll, c)
        xbmc.log(f'[PUNCHPLAY SYNC] Collection: {cn} items.', xbmc.LOGINFO)
        _upd(70, 'Collection')
    except Exception as ex:
        xbmc.log(f'[PUNCHPLAY SYNC] Collection error: {ex}', xbmc.LOGERROR)
    try:
        _db_commit_retry(c.connection)
    except:
        pass
    if is_active:
        try:
            pb = _snapshot_all(api, 'playback')
            pn = _store_playback_snapshot(pb, c)
            xbmc.log(f'[PUNCHPLAY SYNC] Playback: {pn} items.', xbmc.LOGINFO)
            _upd(78, 'Playback')
        except Exception as ex:
            xbmc.log(f'[PUNCHPLAY SYNC] Playback error: {ex}', xbmc.LOGERROR)
        try:
            un = _sync_up_next(api, c)
            xbmc.log(f'[PUNCHPLAY SYNC] Up Next: {un} shows.', xbmc.LOGINFO)
            _upd(88, 'Up Next')
            try:
                _precache_up_next(get_next_episodes_from_db())
            except:
                pass
        except Exception as ex:
            xbmc.log(f'[PUNCHPLAY SYNC] Up Next error: {ex}', xbmc.LOGERROR)
        try:
            _db_commit_retry(c.connection)
        except:
            pass
    try:
        _sync_calendar(api)
        _upd(95, 'Calendar')
    except Exception as ex:
        xbmc.log(f'[PUNCHPLAY SYNC] Calendar error: {ex}', xbmc.LOGERROR)

def sync_full_library(silent=False, force=False):
    if not PUNCHPLAY_CLIENT_ID:
        return
    api = PunchplayAPI()
    if not api.is_authenticated():
        return
    if not _acquire_lock():
        if not silent:
            xbmcgui.Dialog().notification(provider_title('punchplay'),
                                          'Sync already in progress.', PUNCHPLAY_ICON, 3000, False)
        return
    p_dialog = None
    try:
        is_active = _is_punchplay_provider()
        try:
            from resources.lib.watched_provider import _get_provider_raw as _get_prov_raw
            _prov_name = _get_prov_raw()
        except:
            _prov_name = 'punchplay' if is_active else 'other'
        xbmc.log(f'[PUNCHPLAY SYNC] Starting (provider_active={is_active}, provider={_prov_name}, force={force}, silent={silent}).', xbmc.LOGINFO)
        if not silent:
            xbmcgui.Dialog().notification(provider_title('punchplay'),
                                           'Syncing...', PUNCHPLAY_ICON, 2000, False)
            try:
                p_dialog = xbmcgui.DialogProgressBG()
                p_dialog.create(provider_title('punchplay', name='PunchPlay Sync'),
                                'Checking for changes...')
            except:
                p_dialog = None
        if not force:
            try:
                last_ts = float(get_sync_meta('last_sync_ts', '0') or 0)
            except:
                last_ts = 0
            if time.time() - last_ts < 300:
                xbmc.log('[PUNCHPLAY SYNC] Throttled (synced < 5 min ago). Skipping.', xbmc.LOGINFO)
                try:
                    if p_dialog:
                        p_dialog.close()
                except:
                    pass
                return
        _ensure_db()
        conn = get_connection()
        c = conn.cursor()
        need_full = force
        new_cursor = None
        if not need_full:
            try:
                cursor = get_sync_meta('sync_cursor', '')
                data = api.sync_changes(cursor=cursor or None, limit=100)
            except:
                data = None
            if not isinstance(data, dict):
                need_full = True
            elif data.get('resetRequired'):
                try:
                    new_cursor = data.get('nextCursor') or ''
                except:
                    new_cursor = ''
                need_full = True
            else:
                changes = data.get('changes') or []
                try:
                    new_cursor = data.get('nextCursor') or cursor
                except:
                    new_cursor = cursor
                if changes:
                    need_full = True
                else:
                    xbmc.log('[PUNCHPLAY SYNC] No changes. Skipping.', xbmc.LOGINFO)
        if need_full:
            _full_rebuild(api, c, is_active, p_dialog)
            try:
                data = api.sync_changes(limit=1)
                if isinstance(data, dict) and data.get('nextCursor'):
                    new_cursor = data.get('nextCursor')
            except:
                pass
        try:
            _db_commit_retry(conn)
        except:
            pass
        try:
            conn.close()
        except:
            pass
        if new_cursor:
            set_sync_meta('sync_cursor', new_cursor)
        set_sync_meta('last_sync_ts', str(time.time()))
        set_sync_meta('last_sync', datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z'))
        try:
            from resources.lib.cache import clear_all_fast_cache
            clear_all_fast_cache()
        except:
            pass
        xbmc.log('[PUNCHPLAY SYNC] Complete.', xbmc.LOGINFO)
        if not silent:
            try:
                if p_dialog:
                    p_dialog.close()
            except:
                pass
            xbmcgui.Dialog().notification(provider_title('punchplay'),
                                           'Sync complete!', PUNCHPLAY_ICON, 3000, False)
            _trigger_ui_refresh()
    except Exception as e:
        xbmc.log(f'[PUNCHPLAY SYNC] Error: {e}', xbmc.LOGERROR)
        if not silent:
            try:
                if p_dialog:
                    p_dialog.close()
            except:
                pass
            try:
                xbmcgui.Dialog().notification(provider_title('punchplay'),
                                               'Sync failed: %s' % e, PUNCHPLAY_ICON, 5000, False)
            except:
                pass
    finally:
        _release_lock()

def mirror_history(movies, episodes):
    try:
        _ensure_db()
        conn = get_connection()
        c = conn.cursor()
        if movies:
            c.executemany("INSERT OR REPLACE INTO punchplay_watched_movies (tmdb_id, title, year, last_watched_at) VALUES (?,?,?,?)",
                          [(str(t), '', '', str(d)) for t, d in movies])
        if episodes:
            c.executemany("INSERT OR REPLACE INTO punchplay_watched_episodes (tmdb_id, season, episode, title, last_watched_at) VALUES (?,?,?,?,?)",
                          [(str(t), int(s), int(e), '', str(d)) for t, s, e, d in episodes])
        _db_commit_retry(conn)
        conn.close()
        return True
    except:
        return False

def mirror_watchlist(movie_ids, show_ids, status='watching'):
    try:
        _ensure_db()
        conn = get_connection()
        c = conn.cursor()
        for t in movie_ids or []:
            _db_exec_retry(c, "INSERT OR REPLACE INTO punchplay_watchlist (tmdb_id, media_type, status) VALUES (?,?,?)",
                           (str(t), 'movie', status))
        for t in show_ids or []:
            _db_exec_retry(c, "INSERT OR REPLACE INTO punchplay_watchlist (tmdb_id, media_type, status) VALUES (?,?,?)",
                           (str(t), 'tv', status))
        _db_commit_retry(conn)
        conn.close()
        return True
    except:
        return False

def mirror_ratings(movies, shows, episodes):
    try:
        _ensure_db()
        conn = get_connection()
        c = conn.cursor()
        for t, r, d in movies or []:
            _db_exec_retry(c, "INSERT OR REPLACE INTO punchplay_ratings (tmdb_id, media_type, season, episode, rating, rated_at, title) VALUES (?,?,?,?,?,?,?)",
                           (str(t), 'movie', 0, 0, int(r), str(d), ''))
        for t, r, d in shows or []:
            _db_exec_retry(c, "INSERT OR REPLACE INTO punchplay_ratings (tmdb_id, media_type, season, episode, rating, rated_at, title) VALUES (?,?,?,?,?,?,?)",
                           (str(t), 'show', 0, 0, int(r), str(d), ''))
        for t, s, e, r, d in episodes or []:
            _db_exec_retry(c, "INSERT OR REPLACE INTO punchplay_ratings (tmdb_id, media_type, season, episode, rating, rated_at, title) VALUES (?,?,?,?,?,?,?)",
                           (str(t), 'show', int(s), int(e), int(r), str(d), ''))
        _db_commit_retry(conn)
        conn.close()
        return True
    except:
        return False

def mirror_dropped(items):
    try:
        n = len(items or [])
        xbmc.log(f'[PUNCHPLAY] mirror_dropped start: {n} items', xbmc.LOGINFO)
        _ensure_db()
        conn = get_connection()
        c = conn.cursor()
        for it in items or []:
            if isinstance(it, (list, tuple)):
                t = str(it[0])
                title = str(it[1] or '') if len(it) > 1 else ''
                d = str(it[2] or '') if len(it) > 2 else ''
            else:
                t, title, d = str(it), '', ''
            _db_exec_retry(c, "INSERT OR REPLACE INTO punchplay_dropped (tmdb_id, dropped_at, title) VALUES (?,?,?)", (t, d, title))
        _db_commit_retry(conn)
        conn.close()
        xbmc.log(f'[PUNCHPLAY] mirror_dropped done', xbmc.LOGINFO)
        return True
    except:
        return False

def _backfill_ratings_titles_en():
    try:
        _ensure_db()
        conn = get_connection()
        c = conn.cursor()
        try:
            c.execute("""UPDATE punchplay_ratings SET title=COALESCE(
                (SELECT title FROM punchplay_watchlist w WHERE w.tmdb_id=punchplay_ratings.tmdb_id AND w.title<>'' LIMIT 1),
                (SELECT title FROM punchplay_watched_movies m WHERE m.tmdb_id=punchplay_ratings.tmdb_id AND m.title<>'' LIMIT 1),
                (SELECT MAX(title) FROM punchplay_watched_episodes e WHERE e.tmdb_id=punchplay_ratings.tmdb_id AND e.title<>'' LIMIT 1),
                (SELECT title FROM punchplay_favourites f WHERE f.tmdb_id=punchplay_ratings.tmdb_id AND f.title<>'' LIMIT 1),
                (SELECT title FROM punchplay_dropped d WHERE d.tmdb_id=punchplay_ratings.tmdb_id AND d.title<>'' LIMIT 1),
                (SELECT title FROM punchplay_collection cc WHERE cc.tmdb_id=punchplay_ratings.tmdb_id AND cc.title<>'' LIMIT 1)
            ) WHERE title IS NULL OR title=''""")
            conn.commit()
        except:
            pass
        try:
            rows = c.execute("SELECT tmdb_id, media_type FROM punchplay_ratings WHERE title IS NULL OR title=''").fetchall()
        except:
            try:
                conn.close()
            except:
                pass
            return
        pending = [(str(r[0]), r[1]) for r in rows if r[0]]
        if not pending:
            try:
                conn.close()
            except:
                pass
            return
        try:
            conn.close()
        except:
            pass
        import threading as _th
        _th.Thread(target=_backfill_ratings_titles_en_bg, args=(pending[:200],), daemon=True).start()
    except:
        pass

def _backfill_ratings_titles_en_bg(pending):
    try:
        from resources.lib import tmdb_api as _tapi
        import concurrent.futures as _cf

        def _one(pair):
            t, m = pair
            try:
                d = _tapi.get_tmdb_item_details(str(t), 'movie' if m == 'movie' else 'tv', lightweight=True, skip_localization=True) or {}
                title = d.get('title') or d.get('name') or ''
                if not title:
                    return None
                return (title, str(t))
            except:
                return None

        conn = get_connection()
        c = conn.cursor()
        try:
            with _cf.ThreadPoolExecutor(max_workers=5) as _ex:
                for _r in _ex.map(_one, pending):
                    if _r:
                        try:
                            c.execute("UPDATE punchplay_ratings SET title=? WHERE tmdb_id=? AND (title IS NULL OR title='')", _r)
                        except:
                            pass
            conn.commit()
        except:
            pass
        try:
            conn.close()
        except:
            pass
    except:
        pass

def get_ratings_local(media_type=None):
    try:
        _ensure_db()
        conn = get_connection()
        c = conn.cursor()
        if media_type:
            c.execute("SELECT tmdb_id, media_type, season, episode, rating, rated_at, is_anime, title FROM punchplay_ratings WHERE media_type=?", (media_type,))
        else:
            c.execute("SELECT tmdb_id, media_type, season, episode, rating, rated_at, is_anime, title FROM punchplay_ratings")
        rows = [{'tmdb_id': str(r[0]), 'media_type': r[1], 'season': r[2] or 0, 'episode': r[3] or 0,
                 'rating': r[4], 'rated_at': r[5], 'is_anime': int(r[6] or 0), 'title': r[7] or ''} for r in c.fetchall()]
        conn.close()
        return rows
    except:
        return []

def get_collection_local():
    try:
        _ensure_db()
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='punchplay_collection'")
        if not c.fetchone():
            conn.close()
            return []
        c.execute("SELECT tmdb_id, media_type, title, year, added_at FROM punchplay_collection")
        rows = [{'tmdb_id': str(r[0]), 'media_type': r[1], 'title': r[2] or '', 'year': r[3] or '', 'added_at': r[4] or ''} for r in c.fetchall()]
        conn.close()
        return rows
    except:
        return []
