# -*- coding: utf-8 -*-
"""
MDBList Sync DB layer — SQLite local database pentru watched indicators,
playback progress, ratings, collection, dropped.
Modelat dupa trakt_sync.py.
"""

import os
import sys
import json
import time
import datetime
import sqlite3
import threading
import xbmc
import xbmcgui
import xbmc

from resources.lib.config import ADDON, ADDON_DATA_DIR, ADDON_PATH, IMG_BASE, BACKDROP_BASE

DB_PATH = os.path.join(ADDON_DATA_DIR, 'mdblist_sync.db')
MDBLIST_ICON = os.path.join(ADDON_PATH, 'resources', 'media', 'mdblist.png')

_MONITOR = None
def _abort_requested():
    global _MONITOR
    if _MONITOR is None:
        _MONITOR = xbmc.Monitor()
    return _MONITOR.abortRequested()

def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS mdblist_watched_movies (
            tmdb_id TEXT PRIMARY KEY,
            title TEXT,
            year TEXT,
            last_watched_at TEXT,
            poster TEXT,
            backdrop TEXT,
            overview TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS mdblist_watched_episodes (
            tmdb_id TEXT,
            season INTEGER,
            episode INTEGER,
            title TEXT,
            last_watched_at TEXT,
            UNIQUE(tmdb_id, season, episode)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS mdblist_playback_progress (
            tmdb_id TEXT,
            media_type TEXT,
            season INTEGER DEFAULT 0,
            episode INTEGER DEFAULT 0,
            resume_id TEXT,
            progress REAL DEFAULT 0,
            updated_at TEXT,
            UNIQUE(tmdb_id, media_type, season, episode)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS mdblist_ratings (
            tmdb_id TEXT,
            media_type TEXT,
            season INTEGER DEFAULT 0,
            episode INTEGER DEFAULT 0,
            rating INTEGER DEFAULT 0,
            rated_at TEXT,
            UNIQUE(tmdb_id, media_type, season, episode)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS mdblist_collection (
            tmdb_id TEXT PRIMARY KEY,
            media_type TEXT,
            collected_at TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS mdblist_dropped (
            tmdb_id TEXT PRIMARY KEY,
            dropped_at TEXT,
            title TEXT DEFAULT ''
        )
    ''')
    try:
        c.execute("ALTER TABLE mdblist_dropped ADD COLUMN title TEXT DEFAULT ''")
    except:
        pass
    c.execute('''
        CREATE TABLE IF NOT EXISTS mdblist_fully_watched_shows (
            tmdb_id TEXT PRIMARY KEY,
            total_episodes INTEGER DEFAULT 0,
            last_watched_at TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS mdblist_next_episodes (
            tmdb_id TEXT PRIMARY KEY,
            show_title TEXT,
            season INTEGER,
            episode INTEGER,
            ep_title TEXT,
            air_date TEXT,
            watched_count INTEGER DEFAULT 0,
            total_count INTEGER DEFAULT 0,
            last_watched_at TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS mdblist_sync_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS mdblist_cache (
            key TEXT PRIMARY KEY,
            data TEXT,
            saved_at TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS mdblist_watchlist (
            tmdb_id TEXT PRIMARY KEY,
            media_type TEXT,
            added_at TEXT,
            title TEXT,
            year TEXT
        )
    ''')
    conn.commit()
    conn.close()

# ------------------------------------------------------------------
# SYNC META HELPERS
# ------------------------------------------------------------------
def get_sync_meta(key, default=''):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT value FROM mdblist_sync_meta WHERE key=?", (key,))
    r = c.fetchone()
    conn.close()
    return r[0] if r else default

def set_sync_meta(key, value):
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO mdblist_sync_meta VALUES (?,?)", (key, str(value)))
    conn.commit()
    conn.close()

# ------------------------------------------------------------------
# LIST CACHE HELPERS (POV-style: fara TTL, invalidat de activitati)
# ------------------------------------------------------------------
def get_cached(key, ttl=0):
    """Returneaza data cache-uita sau None. ttl>0 = expirare in secunde."""
    if not os.path.exists(DB_PATH):
        return None
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT data, saved_at FROM mdblist_cache WHERE key=?", (key,))
        r = c.fetchone()
        conn.close()
        if not r:
            return None
        if ttl > 0:
            try:
                saved = float(r[1])
                if (time.time() - saved) > ttl:
                    return None
            except:
                pass
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
        c.execute("INSERT OR REPLACE INTO mdblist_cache (key, data, saved_at) VALUES (?,?,?)",
                  (key, json.dumps(data), str(time.time())))
        conn.commit()
        conn.close()
    except:
        pass

def clear_cached(key):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM mdblist_cache WHERE key=?", (key,))
        conn.commit()
        conn.close()
    except:
        pass

def clear_cache_prefix(prefix):
    """Sterge toate cheile care incep cu prefix (ex: 'list_items_')."""
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM mdblist_cache WHERE key LIKE ?", (prefix + '%',))
        conn.commit()
        conn.close()
    except:
        pass

# ------------------------------------------------------------------
# WATCHLIST MIRROR (stare instant pentru context menu)
# ------------------------------------------------------------------
def is_in_watchlist(tmdb_id):
    if not os.path.exists(DB_PATH):
        return False
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT 1 FROM mdblist_watchlist WHERE tmdb_id=?", (str(tmdb_id),))
    found = c.fetchone()
    conn.close()
    return found is not None

def watchlist_add_local(tmdb_id, media_type, title='', year=''):
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO mdblist_watchlist (tmdb_id, media_type, added_at, title, year) VALUES (?,?,?,?,?)",
              (str(tmdb_id), media_type, datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z'), title, str(year)))
    conn.commit()
    conn.close()

def watchlist_remove_local(tmdb_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM mdblist_watchlist WHERE tmdb_id=?", (str(tmdb_id),))
    conn.commit()
    conn.close()

def get_watchlist_local():
    if not os.path.exists(DB_PATH):
        return []
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT tmdb_id, media_type, added_at, title, year FROM mdblist_watchlist ORDER BY added_at DESC")
    rows = c.fetchall()
    conn.close()
    return [
        {'tmdb_id': r[0], 'media_type': r[1], 'added_at': r[2], 'title': r[3], 'year': r[4]}
        for r in rows
    ]

def sync_watchlist_local(items):
    """Wholesale replace a mirrorului local din raspunsul watchlist/items."""
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("DELETE FROM mdblist_watchlist")
        rows = []
        for item in items:
            if not isinstance(item, dict):
                continue
            inner = item.get('show', item.get('movie', item))
            ids = inner.get('ids', {}) or {}
            tmdb_id = str(ids.get('tmdb', '') or item.get('tmdb_id') or '')
            if not tmdb_id:
                continue
            mt = str(item.get('mediatype') or '').lower()
            media_type = 'tv' if mt in ('show', 'tv', 'series', 'tvshow') else 'movie'
            title = inner.get('title') or inner.get('name') or 'Unknown'
            year = str(inner.get('year', '') or inner.get('release_year', ''))
            added_at = item.get('added_at', '') or ''
            rows.append((tmdb_id, media_type, added_at, title, year))
        c.executemany("INSERT OR REPLACE INTO mdblist_watchlist (tmdb_id, media_type, added_at, title, year) VALUES (?,?,?,?,?)", rows)
        conn.commit()
    except Exception as e:
        xbmc.log(f'[MDBList] sync_watchlist_local error: {e}', xbmc.LOGERROR)
    finally:
        conn.close()

# ------------------------------------------------------------------
# WATCHED STATUS
# ------------------------------------------------------------------
def is_movie_watched(tmdb_id):
    if not os.path.exists(DB_PATH):
        return False
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT 1 FROM mdblist_watched_movies WHERE tmdb_id=?", (str(tmdb_id),))
    found = c.fetchone()
    conn.close()
    return found is not None

def is_episode_watched(tmdb_id, season, episode):
    if not os.path.exists(DB_PATH):
        return False
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT 1 FROM mdblist_watched_episodes WHERE tmdb_id=? AND season=? AND episode=?",
              (str(tmdb_id), int(season), int(episode)))
    found = c.fetchone()
    conn.close()
    return found is not None

def get_watched_episodes_count(tmdb_id):
    """Numara doar episoadele individual marcate (fara fallback)."""
    if not os.path.exists(DB_PATH):
        return 0
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM mdblist_watched_episodes WHERE tmdb_id=?", (str(tmdb_id),))
    count = c.fetchone()[0]
    conn.close()
    return count

def count_watched_episodes_raw(tmdb_id):
    """Numara episoadele individual marcate (fara fallback)."""
    if not os.path.exists(DB_PATH):
        return 0
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM mdblist_watched_episodes WHERE tmdb_id=?", (str(tmdb_id),))
    count = c.fetchone()[0]
    conn.close()
    return count

def get_watched_season_episodes_count(tmdb_id, season):
    """Returneaza numarul de episoade vizionate dintr-un sezon."""
    if not os.path.exists(DB_PATH):
        return 0
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM mdblist_watched_episodes WHERE tmdb_id=? AND season=?",
              (str(tmdb_id), int(season)))
    count = c.fetchone()[0]
    conn.close()
    return count

def is_fully_watched_show(tmdb_id):
    """Verifica daca serialul e marcat complet vizionat."""
    if not os.path.exists(DB_PATH):
        return False
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT 1 FROM mdblist_fully_watched_shows WHERE tmdb_id=?", (str(tmdb_id),))
        found = c.fetchone() is not None
    except:
        found = False
    conn.close()
    return found

# ------------------------------------------------------------------
# MARK WATCHED
# ------------------------------------------------------------------
def mark_as_watched_internal(tmdb_id, content_type, season=None, episode=None, notify=True, sync_mdblist=True, refresh_ui=True):
    from resources.lib import tmdb_api
    import threading

    tid = str(tmdb_id)
    conn = get_connection()
    c = conn.cursor()
    now = datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S.000Z')

    title_val = 'Unknown'
    poster_val = ''
    backdrop_val = ''
    overview_val = ''

    try:
        if content_type == 'movie':
            details = tmdb_api.get_tmdb_item_details(tid, 'movie') or {}
            title_val = details.get('title', 'Unknown Movie')
            poster_val = f'{IMG_BASE}{details.get("poster_path", "")}' if details.get('poster_path') else ''
            backdrop_val = f'{BACKDROP_BASE}{details.get("backdrop_path", "")}' if details.get('backdrop_path') else ''
            overview_val = details.get('overview', '')
        elif content_type in ('tv', 'episode', 'show', 'season'):
            show_details = tmdb_api.get_tmdb_item_details(tid, 'tv') or {}
            show_name = show_details.get('name', 'Unknown Show')
            poster_val = f'{IMG_BASE}{show_details.get("poster_path", "")}' if show_details.get('poster_path') else ''
            backdrop_val = f'{BACKDROP_BASE}{show_details.get("backdrop_path", "")}' if show_details.get('backdrop_path') else ''
            overview_val = show_details.get('overview', '')
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
            c.execute("INSERT OR REPLACE INTO mdblist_watched_movies VALUES (?,?,?,?,?,?,?)",
                      (tid, title_val, str(now)[:4], now, poster_val, backdrop_val, overview_val))
            c.execute("DELETE FROM mdblist_playback_progress WHERE tmdb_id=? AND media_type='movie'", (tid,))
        elif season is not None and episode is not None:
            db_show_title = show_name if 'show_name' in locals() else 'Unknown Show'
            c.execute("INSERT OR REPLACE INTO mdblist_watched_episodes VALUES (?,?,?,?,?)",
                      (tid, int(season), int(episode), db_show_title, now))
            c.execute("DELETE FROM mdblist_playback_progress WHERE tmdb_id=? AND season=? AND episode=?",
                      (tid, int(season), int(episode)))
        elif season is not None and episode is None:
            db_show_title = show_name if 'show_name' in locals() else 'Unknown Show'
            show_data = tmdb_api.get_tmdb_item_details(tid, 'tv')
            if show_data:
                rows = []
                for s in show_data.get('seasons', []):
                    if str(s.get('season_number')) == str(season):
                        ep_count = s.get('episode_count', 0)
                        if ep_count > 0:
                            for ep_num in range(1, ep_count + 1):
                                rows.append((tid, int(season), ep_num, db_show_title, now))
                        break
                if rows:
                    c.executemany("INSERT OR REPLACE INTO mdblist_watched_episodes VALUES (?,?,?,?,?)", rows)
                c.execute("DELETE FROM mdblist_playback_progress WHERE tmdb_id=? AND season=?", (tid, int(season)))
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
                    c.executemany("INSERT OR REPLACE INTO mdblist_watched_episodes VALUES (?,?,?,?,?)", rows)
                c.execute("INSERT OR REPLACE INTO mdblist_fully_watched_shows (tmdb_id, total_episodes, last_watched_at) VALUES (?,?,?)",
                          (tid, total_eps, now))
                c.execute("DELETE FROM mdblist_playback_progress WHERE tmdb_id=?", (tid,))
        conn.commit()
    except:
        pass
    finally:
        conn.close()

    # Curatam si tabela locala de resume (paritate cu Trakt) — cerculetul dispare instant
    try:
        from resources.lib import trakt_sync as _ts
        _ts.remove_local_progress(tid, content_type, season, episode)
    except:
        pass

    if notify:
        msg = f'[B][COLOR yellow]{title_val}[/COLOR][/B] marked watched on [B][COLOR lightskyblue]MDBList[/COLOR][/B]'
        xbmcgui.Dialog().notification('[B][COLOR lightskyblue]MDBList[/COLOR][/B]', msg, MDBLIST_ICON, 3000, False)

    if sync_mdblist:
        threading.Thread(target=_sync_single_watched, args=(tmdb_id, content_type, season, episode), daemon=True).start()

    if content_type in ('tv', 'show', 'season', 'episode') or season is not None:
        try:
            threading.Thread(target=refresh_next_episode_mdblist, args=(tmdb_id,), daemon=True).start()
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
    from resources.lib.mdblist_api import MDBListAPI
    try:
        api = MDBListAPI()
        result = api.mark_watched(content_type, tmdb_id, season, episode)
        xbmc.log(f'[MDBList] Push watched {content_type} tmdb={tmdb_id} S{season}E{episode}: {result}', xbmc.LOGINFO)
    except Exception as e:
        xbmc.log(f'[MDBList] Push watched error tmdb={tmdb_id} S{season}E{episode}: {e}', xbmc.LOGERROR)

# ------------------------------------------------------------------
# MARK UNWATCHED
# ------------------------------------------------------------------
def mark_as_unwatched_internal(tmdb_id, content_type, season=None, episode=None, sync_mdblist=True, refresh_ui=True):
    import threading

    tid = str(tmdb_id)
    conn = get_connection()
    c = conn.cursor()

    title_display = 'Element'
    try:
        if content_type == 'movie':
            c.execute("SELECT title FROM mdblist_watched_movies WHERE tmdb_id=?", (tid,))
            r = c.fetchone()
            if r:
                title_display = r[0]
        elif season is not None and episode is not None:
            c.execute("SELECT title FROM mdblist_watched_episodes WHERE tmdb_id=? LIMIT 1", (tid,))
            r = c.fetchone()
            if r:
                base_title = r[0].split(' - S')[0]
                title_display = f'{base_title} - S{int(season):02d}E{int(episode):02d}'
            else:
                title_display = f'S{season}E{episode}'
        elif season is not None:
            c.execute("SELECT title FROM mdblist_watched_episodes WHERE tmdb_id=? LIMIT 1", (tid,))
            r = c.fetchone()
            if r:
                base_title = r[0].split(' - S')[0]
                title_display = f'{base_title} - Sezonul {season}'
            else:
                from resources.lib import tmdb_api
                show_details = tmdb_api.get_tmdb_item_details(tid, 'tv') or {}
                show_name = show_details.get('name', 'Serial')
                title_display = f'{show_name} - Sezonul {season}'
        elif content_type in ('tv', 'show'):
            c.execute("SELECT title FROM mdblist_watched_episodes WHERE tmdb_id=? LIMIT 1", (tid,))
            r = c.fetchone()
            if r:
                title_display = r[0].split(' - S')[0]
            else:
                title_display = 'Serial'
    except:
        pass

    try:
        if content_type == 'movie':
            c.execute("DELETE FROM mdblist_watched_movies WHERE tmdb_id=?", (tid,))
            c.execute("DELETE FROM mdblist_playback_progress WHERE tmdb_id=? AND media_type='movie'", (tid,))
        elif season is not None and episode is not None:
            c.execute("DELETE FROM mdblist_watched_episodes WHERE tmdb_id=? AND season=? AND episode=?",
                      (tid, int(season), int(episode)))
            c.execute("DELETE FROM mdblist_playback_progress WHERE tmdb_id=? AND season=? AND episode=?",
                      (tid, int(season), int(episode)))
        elif season is not None:
            c.execute("DELETE FROM mdblist_watched_episodes WHERE tmdb_id=? AND season=?", (tid, int(season)))
            c.execute("DELETE FROM mdblist_playback_progress WHERE tmdb_id=? AND season=?", (tid, int(season)))
        elif content_type in ('tv', 'show'):
            c.execute("DELETE FROM mdblist_watched_episodes WHERE tmdb_id=?", (tid,))
            c.execute("DELETE FROM mdblist_fully_watched_shows WHERE tmdb_id=?", (tid,))
            c.execute("DELETE FROM mdblist_playback_progress WHERE tmdb_id=?", (tid,))
        conn.commit()
    except:
        pass
    finally:
        conn.close()

    # Curatam si tabela locala de resume (paritate cu Trakt) — cerculetul dispare instant
    try:
        from resources.lib import trakt_sync as _ts
        _ts.remove_local_progress(tid, content_type, season, episode)
    except:
        pass

    msg = f'[B][COLOR yellow]{title_display}[/COLOR][/B] marked unwatched on [B][COLOR lightskyblue]MDBList[/COLOR][/B]'
    xbmcgui.Dialog().notification('[B][COLOR lightskyblue]MDBList[/COLOR][/B]', msg, MDBLIST_ICON, 3000, False)

    if sync_mdblist:
        threading.Thread(target=_sync_single_unwatched, args=(tmdb_id, content_type, season, episode), daemon=True).start()

    if content_type in ('tv', 'show', 'season', 'episode') or season is not None:
        try:
            threading.Thread(target=refresh_next_episode_mdblist, args=(tmdb_id,), daemon=True).start()
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
    from resources.lib.mdblist_api import MDBListAPI
    try:
        api = MDBListAPI()
        api.mark_unwatched(content_type, tmdb_id, season, episode)
    except:
        pass

# ------------------------------------------------------------------
# UP NEXT RECOMPUTE (paritate cu Trakt refresh_next_episode)
# ------------------------------------------------------------------
def refresh_next_episode_mdblist(tmdb_id, ignore_hidden=False):
    """Recalculeaza episodul Up Next local dupa mark watched/unwatched.

    Rescrie randul din mdblist_next_episodes (fara server snapshot) si da
    auto-refresh la container daca suntem in plugin.
    """
    from resources.lib import tmdb_api

    def _trigger_ui_refresh():
        try:
            import xbmc
            container_path = xbmc.getInfoLabel('Container.FolderPath')
            if not container_path or 'plugin.video.tmdbmovies' in container_path.lower():
                xbmc.executebuiltin("Container.Refresh")
        except:
            pass

    try:
        show_details = tmdb_api.get_tmdb_item_details(tmdb_id, 'tv')
        if not show_details:
            return
        show_title = show_details.get('name', 'Unknown Show')

        if not os.path.exists(DB_PATH):
            return
        conn = get_connection()
        c = conn.cursor()

        # Dropped → scoatem din Up Next
        if not ignore_hidden:
            c.execute("SELECT 1 FROM mdblist_dropped WHERE tmdb_id=?", (tmdb_id,))
            if c.fetchone():
                conn.execute("DELETE FROM mdblist_next_episodes WHERE tmdb_id=?", (tmdb_id,))
                conn.commit()
                conn.close()
                _trigger_ui_refresh()
                return

        # Istoricul exact vizionat local + ultimul episod vizionat cronologic
        c.execute("SELECT season, episode FROM mdblist_watched_episodes WHERE tmdb_id=?", (tmdb_id,))
        watched_eps = set((r[0], r[1]) for r in c.fetchall())
        c.execute("SELECT season, episode FROM mdblist_watched_episodes WHERE tmdb_id=? ORDER BY last_watched_at DESC LIMIT 1", (tmdb_id,))
        last_row = c.fetchone()

        # Fara episoade vizionate (ex: unwatch la tot) → iese din Up Next
        if not watched_eps:
            conn.execute("DELETE FROM mdblist_next_episodes WHERE tmdb_id=?", (tmdb_id,))
            conn.commit()
            conn.close()
            _trigger_ui_refresh()
            return

        # Urmatorul episod nevizionat dupa ultimul vizionat cronologic
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

        # Fallback: scanare de la inceput (gap-uri de episoade demarcaate)
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

        # Serial terminat → iese din Up Next
        if not next_ep:
            conn.execute("DELETE FROM mdblist_next_episodes WHERE tmdb_id=?", (tmdb_id,))
            conn.commit()
            conn.close()
            _trigger_ui_refresh()
            return

        # Metadatele noului episod (cache TMDb)
        season_data = tmdb_api.get_smart_season_details(tmdb_id, next_ep['season'])
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

        # Episoadele viitoare raman in lista (paritate Trakt + hide_unreleased=False):
        # filtrarea pe upnext_show_future se face la afisare, nu la stocare.
        now_str = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
        c.execute(
            "INSERT OR REPLACE INTO mdblist_next_episodes "
            "(tmdb_id, show_title, season, episode, ep_title, air_date, watched_count, total_count, last_watched_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (tmdb_id, show_title, next_ep['season'], next_ep['number'],
             ep_title, air_date, len(watched_eps),
             show_details.get('number_of_episodes', 0), now_str)
        )
        conn.commit()
        conn.close()
        _trigger_ui_refresh()
    except Exception as e:
        xbmc.log(f'[MDBList] refresh_next_episode_mdblist error: {e}', xbmc.LOGERROR)

# ------------------------------------------------------------------
# SYNC FULL LIBRARY
# ------------------------------------------------------------------
SYNC_LOCK_KEY = 'mdblist_sync_active'

def sync_full_library(silent=False, force=False):
    window = xbmcgui.Window(10000)
    sync_lock = window.getProperty(SYNC_LOCK_KEY)
    if sync_lock == 'true':
        if not silent:
            xbmcgui.Dialog().notification('[B][COLOR lightskyblue]MDBList[/COLOR][/B]', 'Sync already in progress', MDBLIST_ICON, 2000, False)
        return

    window.setProperty(SYNC_LOCK_KEY, 'true')

    try:
        init_database()
        from resources.lib.mdblist_api import MDBListAPI
        api = MDBListAPI()

        if not api.is_authenticated():
            return

        p_dialog = None
        if not silent:
            p_dialog = xbmcgui.DialogProgressBG()
            p_dialog.create('[B][COLOR lightskyblue]MDBList Sync[/COLOR][/B]', '[B][COLOR lightskyblue]Checking for changes...[/COLOR][/B]')

        try:
            xbmc.log(f'[MDBList SYNC] === STARTING {"FORCE" if force else "SMART"} SYNC ===', xbmc.LOGINFO)
            # --- SMART SYNC: compara activitatile remote cu ultimele cunoscute (ca POV) ---
            need_watched = need_ratings = need_collection = need_dropped = need_playback = need_upnext = force
            if force:
                # Force = refresh complet: golim cache-urile de liste ca sa se refaca
                clear_cached('watchlist')
                clear_cached('collection')
                clear_cached('dropped')
                clear_cached('lists_user')
                clear_cached('lists_liked')
                clear_cached('external_user')
                clear_cache_prefix('list_items_')
            if not force:
                activities = api.get_last_activities()
                if activities and isinstance(activities, dict):
                    cached = {}
                    try:
                        cached = json.loads(get_sync_meta('last_activities', '{}'))
                    except:
                        cached = {}
                    def _changed(key):
                        return (activities.get(key) or '') > (cached.get(key) or '')
                    need_watched   = _changed('watched_at') or _changed('episode_watched_at')
                    need_upnext    = need_watched or _changed('list_updated_at')
                    need_playback  = _changed('paused_at') or _changed('episode_paused_at')
                    need_ratings   = _changed('rated_at')
                    need_collection = _changed('collected_at')
                    need_dropped   = _changed('dropped_at')
                    # invalidare cache liste POV-style (only daca activitatea s-a schimbat)
                    if _changed('watchlisted_at'):
                        clear_cached('watchlist')
                    if _changed('collected_at'):
                        clear_cached('collection')
                    if _changed('list_updated_at'):
                        clear_cached('lists_user')
                        clear_cached('lists_liked')
                        clear_cached('external_user')
                        clear_cache_prefix('list_items_')
                    if _changed('dropped_at'):
                        clear_cached('dropped')
                    set_sync_meta('last_activities', json.dumps(activities))
                else:
                    xbmc.log('[MDBList] Activity check failed, skipping sync', xbmc.LOGINFO)
                    return

            # --- GATING PE PROVIDER: datele interferente (watched, playback, up next,
            # ratings) se sincronizeaza doar daca MDBList e providerul de watched status.
            # Dropped ramane mereu activ (curatare manuala, tabele separate de
            # trakt_hidden_shows — fara interferenta). Collection, liste si calendar
            # raman mereu active (non-interferente). ---
            try:
                from resources.lib.watched_provider import is_mdblist as _is_mdblist_provider
                if not _is_mdblist_provider():
                    need_watched = need_ratings = need_playback = need_upnext = False
                xbmc.log(f'[MDBList SYNC] Flags: watched={need_watched} ratings={need_ratings} collection={need_collection} dropped={need_dropped} playback={need_playback} upnext={need_upnext} (provider={"mdblist" if _is_mdblist_provider() else "trakt"})', xbmc.LOGINFO)
            except Exception as e:
                xbmc.log(f'[MDBList] Provider gate error: {e}', xbmc.LOGERROR)

            if need_watched or need_upnext:
                if p_dialog:
                    p_dialog.update(25, '[B][COLOR lightskyblue]MDBList Sync[/COLOR][/B]', 'Sync: [B][COLOR lightskyblue]Watched[/COLOR][/B]')
                _sync_watched_all(api)
            if need_upnext:
                if p_dialog:
                    p_dialog.update(55, '[B][COLOR lightskyblue]MDBList Sync[/COLOR][/B]', 'Sync: [B][COLOR lightskyblue]Up Next[/COLOR][/B]')
                _sync_up_next(api)
                # Invalideaza fast cache-ul RAM al listei Up Next — altfel randarea
                # get_next_episodes() se opreste la get_fast_cache() si intoarce lista
                # veche (episoade pre-sync), fara sa citeasca DB-ul actualizat.
                from resources.lib.cache import clear_all_fast_cache
                clear_all_fast_cache()
                # Pre-cache detalii (show + season) pentru intrare instanta in Up Next (paritate Trakt)
                try:
                    threading.Thread(target=_precache_up_next, daemon=True).start()
                except Exception as e:
                    xbmc.log(f'[MDBList] Up Next pre-cache start error: {e}', xbmc.LOGERROR)
            if need_ratings:
                if p_dialog:
                    p_dialog.update(75, '[B][COLOR lightskyblue]MDBList Sync[/COLOR][/B]', 'Sync: [B][COLOR lightskyblue]Ratings[/COLOR][/B]')
                _sync_ratings(api)
            if need_collection:
                if p_dialog:
                    p_dialog.update(85, '[B][COLOR lightskyblue]MDBList Sync[/COLOR][/B]', 'Sync: [B][COLOR lightskyblue]Collection[/COLOR][/B]')
                _sync_collection(api)
            if need_dropped:
                _sync_dropped(api)
            if need_playback:
                _sync_playback(api)

            # --- CALENDAR: 24h TTL, 1 call per sync ---
            if force or get_cached('calendar', ttl=86400) is None:
                if p_dialog:
                    p_dialog.update(88, '[B][COLOR lightskyblue]MDBList Sync[/COLOR][/B]', 'Sync: [B][COLOR lightskyblue]Calendar[/COLOR][/B]')
                _sync_calendar(api)

            # --- SINCRONIZARE CONT TMDB (mdblist + tmdb, paritate cu trakt + tmdb) ---
            try:
                from resources.lib import trakt_sync as _ts
                # Force nu re-sincronizeaza TMDb daca tocmai a fost sincronizat (<60s):
                # in lantul dublu (provider activ + al doilea serviciu) TMDb nu se duplica.
                _last_tmdb = _ts.get_local_last_sync().get('tmdb_sync_ts', 0)
                tmdb_needed = (time.time() - _last_tmdb > 1800) or (force and (time.time() - _last_tmdb > 60))
                if tmdb_needed:
                    if p_dialog:
                        p_dialog.update(92, '[B][COLOR lightskyblue]MDBList Sync[/COLOR][/B]', 'Sync: [B][COLOR FF00CED1]TMDb account[/COLOR][/B]')
                    _ts.sync_tmdb_only(silent=silent, force=tmdb_needed)
            except Exception as e:
                xbmc.log(f'[MDBList] TMDb sync error: {e}', xbmc.LOGERROR)

            set_sync_meta('last_sync', str(time.time()))
            xbmc.log('[MDBList SYNC] ✓ Saved sync meta + timestamps', xbmc.LOGINFO)

            try:
                from resources.lib.utils import perform_mdblist_backup
                perform_mdblist_backup(manual=False)
            except: pass

            if not silent:
                xbmcgui.Dialog().notification('[B][COLOR lightskyblue]MDBList[/COLOR][/B]', 'Sync complete!', MDBLIST_ICON, 3000, False)
            xbmc.log('[MDBList SYNC] === SYNC COMPLETE ===', xbmc.LOGINFO)
        except Exception as e:
            xbmc.log(f'[MDBList] Sync error: {e}', xbmc.LOGERROR)
        finally:
            if p_dialog:
                p_dialog.close()
    finally:
        window.clearProperty(SYNC_LOCK_KEY)

def _sync_watched_all(api):
    conn = get_connection()
    c = conn.cursor()
    try:
        # Mirror complet (paritate Trakt): randurile locale care lipsesc de pe site
        # se sterg — altfel un mark ramas doar local (push esuat) ramane pe vecie.
        c.execute("DELETE FROM mdblist_watched_movies")
        c.execute("DELETE FROM mdblist_watched_episodes")
        c.execute("DELETE FROM mdblist_fully_watched_shows")
        conn.commit()
        cursor = None
        for _ in range(50):
            if _abort_requested():
                break
            data = api.get_sync_watched(cursor=cursor, limit=1000)
            if not data or not isinstance(data, dict):
                break
            for movie in data.get('movies', []):
                inner = movie.get('movie', movie)
                ids = inner.get('ids', {})
                tmdb_id = str(ids.get('tmdb', ''))
                if not tmdb_id:
                    continue
                title = inner.get('title', 'Unknown')
                watched_at = movie.get('watched_at', '')
                year = str(inner.get('year', '')) if inner.get('year') else str(inner.get('release_year', ''))
                c.execute("INSERT OR REPLACE INTO mdblist_watched_movies (tmdb_id, title, year, last_watched_at) VALUES (?,?,?,?)",
                          (tmdb_id, title, year, watched_at))
            for ep in data.get('episodes', []):
                inner = ep.get('episode', ep)
                show = inner.get('show', {}) if inner else {}
                ids = show.get('ids', {})
                tmdb_id = str(ids.get('tmdb', ''))
                if not tmdb_id:
                    continue
                season = inner.get('season', 1)
                episode = inner.get('number', inner.get('episode', 1))
                title = show.get('title', inner.get('name', 'Unknown Show'))
                watched_at = ep.get('last_watched_at', '')
                c.execute("INSERT OR REPLACE INTO mdblist_watched_episodes (tmdb_id, season, episode, title, last_watched_at) VALUES (?,?,?,?,?)",
                          (tmdb_id, int(season), int(episode), title, watched_at))
            for s in data.get('shows', []):
                show_inner = s.get('show', {})
                ids = show_inner.get('ids', {})
                tmdb_id = str(ids.get('tmdb', ''))
                if not tmdb_id:
                    continue
                total = show_inner.get('total_aired_episodes', 0)
                watched_at = s.get('last_watched_at', '')
                c.execute("INSERT OR REPLACE INTO mdblist_fully_watched_shows (tmdb_id, total_episodes, last_watched_at) VALUES (?,?,?)",
                          (tmdb_id, total, watched_at))
            conn.commit()
            pagination = data.get('pagination', {})
            if not pagination.get('has_more'):
                break
            cursor = pagination.get('next_cursor')
    except Exception as e:
        xbmc.log(f'[MDBList] _sync_watched_all error: {e}', xbmc.LOGERROR)
    finally:
        conn.close()

def _sync_up_next(api):
    conn = get_connection()
    c = conn.cursor()
    try:
        all_items = []
        offset = 0
        for _ in range(50):
            if _abort_requested():
                break
            data = api.get_upnext(limit=1000, offset=offset, hide_unreleased=False)
            if not data or not isinstance(data, dict):
                break
            items = data.get('items', [])
            all_items.extend(items)
            if not data.get('has_more') or not items:
                break
            offset += len(items)
        # Episoade viitoare (peste 7 zile): /upnext/upcoming nu le returneaza.
        # NOTA: days=90 e buggy pe server (testat live 2026-08-03: Lioness S3E2 pe
        # 09-aug dispare din raspuns cu days=90/180, dar apare cu days<=60).
        offset = 0
        for _ in range(20):
            if _abort_requested():
                break
            data = api.get_upnext_upcoming(limit=1000, offset=offset, days=60)
            if not data or not isinstance(data, dict):
                break
            items = data.get('items', [])
            all_items.extend(items)
            if not data.get('has_more') or not items:
                break
            offset += len(items)
        if not all_items:
            return
        rows = []
        for item in all_items:
            if not isinstance(item, dict):
                continue
            show = item.get('show', {}) or {}
            next_ep = item.get('next_episode', {}) or {}
            ids = show.get('ids', {}) or {}
            tmdb_id = str(ids.get('tmdb', '') or item.get('tmdb_id') or item.get('id') or '')
            if not tmdb_id:
                continue
            show_title = show.get('title') or item.get('show_title') or item.get('title') or 'Unknown Show'
            season = int(next_ep.get('season') or 1)
            episode = int(next_ep.get('episode') or 1)
            ep_title = next_ep.get('title') or ''
            air_date = next_ep.get('air_date') or ''
            progress = item.get('progress', {}) or {}
            watched_count = int(progress.get('watched_episode_count') or 0)
            total_count = int(progress.get('total_episode_count') or 0)
            last_watched_at = item.get('last_watched_at') or item.get('watched_at') or ''
            rows.append((tmdb_id, show_title, season, episode, ep_title, air_date,
                         watched_count, total_count, last_watched_at))

        # DEDUPE pe tmdb_id: /upnext (episodul curent/difuzat) are prioritate peste
        # /upnext/upcoming (episod viitor) — all_items combina ambele raspunsuri, deci
        # Lioness poate aparea si cu S3E1 (upnext) si cu S3E2 (upcoming). Fara dedupe,
        # INSERT OR REPLACE pe PK tmdb_id lasa sa castige ULTIMUL rand (upcoming),
        # suprascriind episodul difuzat pe care il arata site-ul.
        seen_ids = set()
        deduped_rows = []
        for r in rows:
            if r[0] in seen_ids:
                continue
            seen_ids.add(r[0])
            deduped_rows.append(r)
        rows = deduped_rows

        # MERGE: serverul nu intoarce niciodata episoade viitoare/TBA (doar cele difuzate).
        # Randurile locale cu episodul urmator in viitor sau fara data se pastreaza
        # (ex: Lioness S3E2 pe 09-aug dupa marcarea S3E1 ca vizionat) DOAR DACA serialul
        # nu apare deloc in raspunsul serverului. Daca serverul intoarce serialul cu alt
        # episod (ex. un-watch pe site: S3E2 -> S3E1), serverul e autoritatea — randul
        # local vechi se arunca (altfel INSERT OR REPLACE pe PK tmdb_id l-ar suprascrie).
        try:
            c.execute("SELECT tmdb_id, show_title, season, episode, ep_title, air_date, "
                      "watched_count, total_count, last_watched_at FROM mdblist_next_episodes")
            local_rows = [tuple(r) for r in c.fetchall()]
        except Exception as e:
            local_rows = []
            xbmc.log(f'[MDBList] _sync_up_next merge read error: {e}', xbmc.LOGERROR)
        server_keys = set()
        server_show_ids = set()
        for r in rows:
            server_keys.add((r[0], r[2], r[3]))
            server_show_ids.add(r[0])
        today = datetime.date.today().isoformat()
        preserved = 0
        for lr in local_rows:
            if lr[0] in server_show_ids:
                continue
            if (lr[0], lr[2], lr[3]) in server_keys:
                continue
            lr_ad = (lr[5] or '').split('T')[0]
            if lr_ad and lr_ad <= today:
                continue
            try:
                c.execute("SELECT 1 FROM mdblist_dropped WHERE tmdb_id=?", (lr[0],))
            except Exception:
                continue
            if c.fetchone():
                continue
            rows.append(lr)
            preserved += 1
        if preserved:
            xbmc.log(f'[MDBList] _sync_up_next: preserved {preserved} future/TBA rows missing from server', xbmc.LOGINFO)

        c.execute("DELETE FROM mdblist_next_episodes")
        c.executemany("INSERT OR REPLACE INTO mdblist_next_episodes "
                      "(tmdb_id, show_title, season, episode, ep_title, air_date, watched_count, total_count, last_watched_at) "
                      "VALUES (?,?,?,?,?,?,?,?,?)", rows)
        conn.commit()
    except Exception as e:
        xbmc.log(f'[MDBList] _sync_up_next error: {e}', xbmc.LOGERROR)
    finally:
        conn.close()

def _precache_up_next():
    """Pre-cache detalii show + season pentru intrare instanta in Up Next (paritate Trakt)."""
    try:
        from resources.lib.tmdb_api import get_smart_season_details, prefetch_metadata_parallel
        from concurrent.futures import ThreadPoolExecutor, as_completed
        items = get_next_episodes_from_db()
        if not items:
            return
        prefetch_metadata_parallel([{'id': str(i['tmdb_id']), 'media_type': 'tv'} for i in items], 'tv')
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(get_smart_season_details, str(i['tmdb_id']), i['season']): i for i in items}
            for f in as_completed(futures):
                pass
        xbmc.log(f'[MDBList] Pre-cached {len(items)} show+season details for Up Next', xbmc.LOGINFO)
    except Exception as e:
        xbmc.log(f'[MDBList] Up Next pre-cache error: {e}', xbmc.LOGERROR)

def get_next_episodes_from_db():
    """Toate serialele Up Next din DB local (fara paginare, ca la Trakt)."""
    if not os.path.exists(DB_PATH):
        return []
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT tmdb_id, show_title, season, episode, ep_title, air_date, "
                  "watched_count, total_count, last_watched_at "
                  "FROM mdblist_next_episodes "
                  "WHERE tmdb_id NOT IN (SELECT tmdb_id FROM mdblist_dropped) "
                  "ORDER BY last_watched_at DESC")
        rows = c.fetchall()
    except Exception as e:
        xbmc.log(f'[MDBList] get_next_episodes_from_db error: {e}', xbmc.LOGERROR)
        rows = []
    finally:
        conn.close()
    return [
        {'tmdb_id': r[0], 'show_title': r[1], 'season': r[2], 'episode': r[3],
         'ep_title': r[4], 'air_date': r[5], 'watched_count': r[6],
         'total_count': r[7], 'last_watched_at': r[8]}
        for r in rows
    ]

def get_in_progress_tvshows_from_db():
    """Seriale in progres: watched > 0 si (total necunoscut sau watched < total).

    Sursa e tabela Up Next MDBList (aceeasi sincronizata pentru MDB Up Next).
    Exclude serialele din tabela dropped. Ordoneaza dupa ultima vizionare.
    """
    if not os.path.exists(DB_PATH):
        return []
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT tmdb_id, show_title, season, episode, ep_title, air_date, "
                  "watched_count, total_count, last_watched_at "
                  "FROM mdblist_next_episodes "
                  "WHERE tmdb_id NOT IN (SELECT tmdb_id FROM mdblist_dropped) "
                  "AND watched_count > 0 "
                  "AND (total_count = 0 OR watched_count < total_count) "
                  "ORDER BY last_watched_at DESC")
        rows = c.fetchall()
    except Exception as e:
        xbmc.log(f'[MDBList] get_in_progress_tvshows_from_db error: {e}', xbmc.LOGERROR)
        rows = []
    finally:
        conn.close()
    return [
        {'tmdb_id': r[0], 'show_title': r[1], 'season': r[2], 'episode': r[3],
         'ep_title': r[4], 'air_date': r[5], 'watched_count': r[6],
         'total_count': r[7], 'last_watched_at': r[8]}
        for r in rows
    ]

def _sync_ratings(api):
    conn = get_connection()
    c = conn.cursor()
    try:
        cursor = None
        while True:
            if _abort_requested():
                break
            data = api.get_sync_ratings(cursor=cursor, limit=100)
            if not data:
                break
            for movie in data.get('movies', []):
                inner = movie.get('movie', movie) or movie
                ids = inner.get('ids', {}) or {}
                tmdb_id = str(ids.get('tmdb', ''))
                if tmdb_id:
                    c.execute("INSERT OR REPLACE INTO mdblist_ratings (tmdb_id, media_type, rating, rated_at) VALUES (?,?,?,?)",
                              (tmdb_id, 'movie', movie.get('rating', 0), movie.get('rated_at', '')))
            for show in data.get('shows', []):
                inner = show.get('show', show) or show
                ids = inner.get('ids', {}) or {}
                tmdb_id = str(ids.get('tmdb', ''))
                if tmdb_id:
                    c.execute("INSERT OR REPLACE INTO mdblist_ratings (tmdb_id, media_type, rating, rated_at) VALUES (?,?,?,?)",
                              (tmdb_id, 'show', show.get('rating', 0), show.get('rated_at', '')))
            for s in data.get('seasons', []):
                inner = s.get('season', s) or s
                show = inner.get('show', {}) or {}
                ids = inner.get('ids', {}) or show.get('ids', {}) or {}
                tmdb_id = str(ids.get('tmdb', ''))
                if tmdb_id:
                    c.execute("INSERT OR REPLACE INTO mdblist_ratings (tmdb_id, media_type, season, rating, rated_at) VALUES (?,?,?,?,?)",
                              (tmdb_id, 'season', inner.get('number', 0), s.get('rating', 0), s.get('rated_at', '')))
            for ep in data.get('episodes', []):
                inner = ep.get('episode', ep) or ep
                ids = inner.get('ids', {}) or {}
                tmdb_id = str(ids.get('tmdb', ''))
                if tmdb_id:
                    c.execute("INSERT OR REPLACE INTO mdblist_ratings (tmdb_id, media_type, season, episode, rating, rated_at) VALUES (?,?,?,?,?,?)",
                              (tmdb_id, 'episode', inner.get('season', 0), inner.get('number', 0), ep.get('rating', 0), ep.get('rated_at', '')))
            conn.commit()
            pagination = data.get('pagination', {})
            if not pagination.get('has_more'):
                break
            cursor = pagination.get('next_cursor')
    except Exception as e:
        xbmc.log(f'[MDBList] _sync_ratings error: {e}', xbmc.LOGERROR)
    finally:
        conn.close()

def _sync_collection(api):
    conn = get_connection()
    c = conn.cursor()
    try:
        cursor = None
        while True:
            if _abort_requested():
                break
            data = api.get_collection(cursor=cursor, limit=100)
            if not data:
                break
            for movie in data.get('movies', []):
                inner = movie.get('movie', movie) or movie
                ids = inner.get('ids', {}) or {}
                tmdb_id = str(ids.get('tmdb', ''))
                if tmdb_id:
                    c.execute("INSERT OR REPLACE INTO mdblist_collection VALUES (?,?,?)",
                              (tmdb_id, 'movie', movie.get('collected_at', '')))
            for show in data.get('shows', []):
                inner = show.get('show', show) or show
                ids = inner.get('ids', {}) or {}
                tmdb_id = str(ids.get('tmdb', ''))
                if tmdb_id:
                    c.execute("INSERT OR REPLACE INTO mdblist_collection VALUES (?,?,?)",
                              (tmdb_id, 'show', show.get('collected_at', '')))
            conn.commit()
            pagination = data.get('pagination', {})
            if not pagination.get('has_more'):
                break
            cursor = pagination.get('next_cursor')
    except Exception as e:
        xbmc.log(f'[MDBList] _sync_collection error: {e}', xbmc.LOGERROR)
    finally:
        conn.close()

def _sync_dropped(api):
    conn = get_connection()
    c = conn.cursor()
    try:
        # Mirror complet: randurile locale care nu mai sunt pe site se sterg
        # (altfel un show re-dropped/un-dropped pe site ramane blocat local si
        # chiar exclude serialul din Up Next prin tabela mdblist_dropped).
        c.execute("DELETE FROM mdblist_dropped")
        conn.commit()
        cursor = None
        while True:
            if _abort_requested():
                break
            data = api.get_dropped(cursor=cursor, limit=100)
            if not data:
                break
            for show in data.get('shows', []):
                inner = show.get('show', show) or show
                ids = inner.get('ids', {}) or {}
                tmdb_id = str(ids.get('tmdb', ''))
                if tmdb_id:
                    title = inner.get('title') or show.get('title') or ''
                    c.execute("INSERT OR REPLACE INTO mdblist_dropped (tmdb_id, dropped_at, title) VALUES (?,?,?)",
                              (tmdb_id, show.get('dropped_at', ''), title))
            conn.commit()
            pagination = data.get('pagination', {})
            if not pagination.get('has_more'):
                break
            cursor = pagination.get('next_cursor')
    except Exception as e:
        xbmc.log(f'[MDBList] _sync_dropped error: {e}', xbmc.LOGERROR)
    finally:
        conn.close()

def _sync_playback(api):
    """Importa sesiunile de playback din /sync/playback (format Trakt-compatibil).

    Raspuns tipic: [{'id', 'progress', 'paused_at', 'type': 'movie'|'episode',
                      'movie': {'ids': {'tmdb'}} | 'show': {'ids': {'tmdb'}},
                      'episode': {'season', 'number'}}]
    DELETE-first ca sesiunile expirate server-side sa dispara din tabela locala.
    """
    conn = get_connection()
    c = conn.cursor()
    _sync_ok = False
    try:
        data = api.get_playback_sessions()
        sessions = data if isinstance(data, list) else (data or {}).get('items', [])
        if not sessions:
            c.execute("DELETE FROM mdblist_playback_progress")
            conn.commit()
            return
        rows = []
        for item in sessions:
            if not isinstance(item, dict):
                continue
            type_ = item.get('type', '') or item.get('media_type', 'movie')
            if type_ == 'movie':
                inner = item.get('movie') or {}
                tmdb_id = str(inner.get('ids', {}).get('tmdb', '') or item.get('tmdb', '') or item.get('tmdb_id', ''))
                season, episode = 0, 0
            else:
                show = item.get('show') or {}
                tmdb_id = str(show.get('ids', {}).get('tmdb', '') or item.get('tmdb', '') or item.get('tmdb_id', ''))
                ep_obj = item.get('episode') or {}
                try:
                    season = int(ep_obj.get('season', item.get('season', 0)) or 0)
                except:
                    season = 0
                try:
                    episode = int(ep_obj.get('number', item.get('episode', 0)) or 0)
                except:
                    episode = 0
            if not tmdb_id:
                continue
            try:
                progress = float(item.get('progress', 0) or 0)
            except:
                progress = 0.0
            updated = item.get('paused_at') or item.get('updated_at') or ''
            rows.append((tmdb_id, 'movie' if type_ == 'movie' else 'episode',
                         season, episode, str(item.get('id', '')), progress, updated))
        c.execute("DELETE FROM mdblist_playback_progress")
        c.executemany("INSERT OR REPLACE INTO mdblist_playback_progress VALUES (?,?,?,?,?,?,?)", rows)
        conn.commit()
        _sync_ok = True
    except Exception as e:
        xbmc.log(f'[MDBList] _sync_playback error: {e}', xbmc.LOGERROR)
    finally:
        conn.close()

    if not _sync_ok:
        return

    # --- IMPORT IN TABELA LOCALA DE RESUME (playback_progress din trakt_sync.db) ---
    # Paritate cu trakt_sync._sync_playback: secunde exacte locale pastrate (valoare magica
    # >1.000.000), skip progress <=1 sau >=99, randuri locale recente (<24h) mentinute.
    # Ruleaza doar cand MDBList este providerul de watched status.
    try:
        from resources.lib.watched_provider import is_mdblist as _is_mdblist_provider
        if not _is_mdblist_provider():
            return
        import datetime as _dt
        from resources.lib import trakt_sync as _ts
        lconn = _ts.get_connection()
        lc = lconn.cursor()
        lc.execute("SELECT * FROM playback_progress")
        local_progress = {}
        for row in lc.fetchall():
            key = f"{row['tmdb_id']}_{row['media_type']}_{row['season']}_{row['episode']}"
            local_progress[key] = dict(row)
        lc.execute("DELETE FROM playback_progress")
        lrows = []
        for item in sessions:
            if not isinstance(item, dict):
                continue
            type_ = item.get('type', '') or item.get('media_type', 'movie')
            try:
                progress = float(item.get('progress', 0) or 0)
            except:
                progress = 0.0
            if progress <= 1 or progress >= 99:
                continue
            if type_ == 'movie':
                inner = item.get('movie') or {}
                tid = str(inner.get('ids', {}).get('tmdb', '') or item.get('tmdb', '') or item.get('tmdb_id', ''))
                s, e = 0, 0
                title = inner.get('title', 'Unknown Movie')
                year = str(inner.get('year', ''))
            else:
                show = item.get('show') or {}
                tid = str(show.get('ids', {}).get('tmdb', '') or item.get('tmdb', '') or item.get('tmdb_id', ''))
                ep_obj = item.get('episode') or {}
                try:
                    s = int(ep_obj.get('season', item.get('season', 0)) or 0)
                except:
                    s = 0
                try:
                    e = int(ep_obj.get('number', item.get('episode', 0)) or 0)
                except:
                    e = 0
                show_title = show.get('title', 'Unknown Show')
                ep_title = ep_obj.get('title', '')
                title = f"{show_title} - S{s:02d}E{e:02d}"
                if ep_title:
                    title += f" - {ep_title}"
                year = str(show.get('year', ''))
            if not tid or tid == 'None':
                continue
            paused_at = item.get('paused_at') or item.get('updated_at') or ''
            key = f"{tid}_{type_}_{s}_{e}"
            if key in local_progress:
                local_val = local_progress[key]['progress']
                local_time = local_progress[key]['paused_at']
                if local_val >= 1000000:
                    progress = local_val
                    paused_at = local_time
            lrows.append((tid, type_, s, e, progress, paused_at, title, year, ''))
        now = _dt.datetime.utcnow()
        for key, loc in local_progress.items():
            if not any(r[0] == loc['tmdb_id'] and r[1] == loc['media_type'] and r[2] == loc['season'] and r[3] == loc['episode'] for r in lrows):
                try:
                    clean_date = str(loc['paused_at']).replace('.000Z', '').replace('Z', '')
                    d_part, t_part = clean_date.split('T')
                    y, m, d_zi = map(int, d_part.split('-'))
                    H, M, S = map(int, t_part.split(':'))
                    loc_time = _dt.datetime(y, m, d_zi, H, M, S)
                    if (now - loc_time).total_seconds() < 86400:
                        lrows.append((loc['tmdb_id'], loc['media_type'], loc['season'], loc['episode'],
                                      loc['progress'], loc['paused_at'], loc['title'], loc['year'], loc['poster']))
                except:
                    pass
        if lrows:
            lc.executemany("INSERT OR REPLACE INTO playback_progress VALUES (?,?,?,?,?,?,?,?,?)", lrows)
        lconn.commit()
        lconn.close()
    except Exception as e:
        xbmc.log(f'[MDBList] local playback merge error: {e}', xbmc.LOGERROR)

def _sync_calendar(api):
    """1 call calendar/events (30 zile), salvat in cache — Varianta A (TTL 24h)."""
    try:
        import datetime as _dt
        today = _dt.date.today()
        end = today + _dt.timedelta(days=30)
        data = api.calendar_events(start=today.isoformat(), end=end.isoformat(), limit=1000)
        if data is not None:
            set_cached('calendar', data)
    except Exception as e:
        xbmc.log(f'[MDBList] _sync_calendar error: {e}', xbmc.LOGERROR)

# ------------------------------------------------------------------
# COLLECTION / DROPPED HELPERS
# ------------------------------------------------------------------
def is_in_collection(tmdb_id):
    if not os.path.exists(DB_PATH):
        return False
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT 1 FROM mdblist_collection WHERE tmdb_id=?", (str(tmdb_id),))
    found = c.fetchone()
    conn.close()
    return found is not None

def is_dropped(tmdb_id):
    if not os.path.exists(DB_PATH):
        return False
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT 1 FROM mdblist_dropped WHERE tmdb_id=?", (str(tmdb_id),))
    found = c.fetchone()
    conn.close()
    return found is not None

def drop_add_local(tmdb_id, title=''):
    try:
        init_database()
    except Exception as e:
        xbmc.log(f'[MDBList] drop_add_local init_database error: {e}', xbmc.LOGERROR)
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO mdblist_dropped (tmdb_id, dropped_at, title) VALUES (?,?,?)",
              (str(tmdb_id), datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z'), title or ''))
    conn.commit()
    conn.close()

def drop_remove_local(tmdb_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM mdblist_dropped WHERE tmdb_id=?", (str(tmdb_id),))
    conn.commit()
    conn.close()

def drop_show(tmdb_id, title=''):
    """Drop un serial pe MDBList (API + local). Returneaza True/False."""
    if not tmdb_id:
        return False
    try:
        from resources.lib.mdblist_api import MDBListAPI
        if MDBListAPI().mark_dropped(tmdb_id):
            drop_add_local(tmdb_id, title)
            return True
    except Exception as e:
        xbmc.log(f'[MDBList] drop_show error: {e}', xbmc.LOGERROR)
    return False

def restore_show(tmdb_id):
    """Restore un serial pe MDBList (API + local). Returneaza True/False."""
    if not tmdb_id:
        return False
    try:
        from resources.lib.mdblist_api import MDBListAPI
        if MDBListAPI().unmark_dropped(tmdb_id):
            drop_remove_local(tmdb_id)
            clear_cached('dropped')
            return True
    except Exception as e:
        xbmc.log(f'[MDBList] restore_show error: {e}', xbmc.LOGERROR)
    return False

def get_dropped_local():
    if not os.path.exists(DB_PATH):
        return []
    try:
        init_database()
    except:
        pass
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT tmdb_id, dropped_at, title FROM mdblist_dropped ORDER BY dropped_at DESC")
        rows = c.fetchall()
    except Exception as e:
        xbmc.log(f'[MDBList] get_dropped_local error: {e}', xbmc.LOGERROR)
        rows = []
    finally:
        conn.close()
    return [{'tmdb_id': r[0], 'dropped_at': r[1], 'title': r[2] or ''} for r in rows]

def import_dropped_from_trakt(silent=False):
    """Importa (copy) dropped-urile din Trakt (trakt_hidden_shows) in MDBList.
    Returneaza (imported, skipped)."""
    try:
        init_database()
    except Exception as e:
        xbmc.log(f'[MDBList] import init_database error: {e}', xbmc.LOGERROR)
    try:
        from resources.lib import trakt_sync
        if not os.path.exists(trakt_sync.DB_PATH):
            if not silent:
                xbmcgui.Dialog().notification('[B][COLOR lightskyblue]MDBList[/COLOR][/B]', 'Connect Trakt first (no Trakt sync data found)', MDBLIST_ICON, 3000, False)
            return 0, 0
        tconn = trakt_sync.get_connection()
        try:
            trows = tconn.execute("SELECT tmdb_id FROM trakt_hidden_shows").fetchall()
        finally:
            tconn.close()
        trakt_ids = [str(r[0]) for r in trows if r[0]]
    except Exception as e:
        xbmc.log(f'[MDBList] import_dropped_from_trakt read error: {e}', xbmc.LOGERROR)
        if not silent:
            xbmcgui.Dialog().notification('[B][COLOR lightskyblue]MDBList[/COLOR][/B]', 'Could not read Trakt dropped list', MDBLIST_ICON, 3000, False)
        return 0, 0

    if not trakt_ids:
        if not silent:
            xbmcgui.Dialog().notification('[B][COLOR lightskyblue]MDBList[/COLOR][/B]', 'No dropped shows found on Trakt', MDBLIST_ICON, 3000, False)
        return 0, 0

    existing = set()
    if os.path.exists(DB_PATH):
        conn = get_connection()
        try:
            for r in conn.execute("SELECT tmdb_id FROM mdblist_dropped").fetchall():
                existing.add(str(r[0]))
        finally:
            conn.close()

    pending = [tid for tid in trakt_ids if tid not in existing]

    if not pending:
        if not silent:
            xbmcgui.Dialog().notification('[B][COLOR lightskyblue]MDBList[/COLOR][/B]', 'Nothing to import - all dropped shows already on MDBList', MDBLIST_ICON, 3000, False)
        return 0, len(trakt_ids)

    from resources.lib.mdblist_api import MDBListAPI
    api = MDBListAPI()

    p_dialog = None
    if not silent:
        p_dialog = xbmcgui.DialogProgressBG()
        p_dialog.create('[B][COLOR lightskyblue]MDBList Import[/COLOR][/B]', f'Importing dropped: 0 / {len(pending)}')

    imported = 0
    try:
        for i, tid in enumerate(pending):
            if _abort_requested():
                break
            if p_dialog:
                p_dialog.update(int((i + 1) * 100 / len(pending)),
                                '[B][COLOR lightskyblue]MDBList Import[/COLOR][/B]',
                                f'Importing dropped: {i + 1} / {len(pending)}')
            try:
                if api.mark_dropped(tid):
                    drop_add_local(tid)
                    imported += 1
            except Exception as e:
                xbmc.log(f'[MDBList] import dropped {tid} error: {e}', xbmc.LOGERROR)
            if _abort_requested():
                break
            xbmc.sleep(1000)
    finally:
        if p_dialog:
            p_dialog.close()

    # Re-pull de pe server: umple titlurile reale (importul salveaza doar tmdb_id)
    if imported > 0 and not _abort_requested():
        try:
            _sync_dropped(api)
        except Exception as e:
            xbmc.log(f'[MDBList] import dropped re-pull error: {e}', xbmc.LOGERROR)

    skipped = len(pending) - imported
    if not silent:
        xbmcgui.Dialog().notification('[B][COLOR lightskyblue]MDBList[/COLOR][/B]',
                                      f'Dropped imported: [B][COLOR FF6AFB92]{imported}[/COLOR][/B], failed: {skipped}', MDBLIST_ICON, 4000, False)
    return imported, skipped

def get_watched_movie_count():
    if not os.path.exists(DB_PATH):
        return 0
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM mdblist_watched_movies")
    count = c.fetchone()[0]
    conn.close()
    return count

def get_watched_episode_count():
    if not os.path.exists(DB_PATH):
        return 0
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM mdblist_watched_episodes")
    count = c.fetchone()[0]
    conn.close()
    return count
