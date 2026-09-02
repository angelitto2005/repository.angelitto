# -*- coding: utf-8 -*-
"""
Simkl sync engine — mirror local complet (paritate cu mdblist_sync.py) + sync
conform regulilor API Simkl (directive user):

  - Phase 1 (initial): /sync/shows, /sync/movies, /sync/anime — apelate
    INDIVIDUAL si SECVENTIAL, FARA date_from (evita CPU spikes pe watchlist mari).
  - Phase 2 (continuu): intai /sync/activities -> se compara timestamp-urile cu
    cele salvate local; daca coincid -> skip; daca difera ->
    /sync/all-items/?date_from=<timestamp salvat> (doar delta).
    Fara timestamp salvat -> fallback Phase 1.
  - Fara polling neconditionat de fundal; sync doar la pornire, sfarsit playback,
    override manual; throttle verificari 15-30 min (aici: 15 min).
  - Intotdeauna date_from la sync-urile ulterioare.
  - Rate limits: 10 GET/s + 1 POST/s (handled in simkl_api.py throttle).
"""

import os
import re
import json
import time
import datetime
import threading
import xbmc
import xbmcgui

from resources.lib.config import ADDON, ADDON_DATA_DIR, ADDON_PATH, IMG_BASE, BACKDROP_BASE
from resources.lib.simkl_api import SIMKLAPI, SIMKL_ICON, SIMKL_CLIENT_ID

DB_PATH = os.path.join(ADDON_DATA_DIR, 'simkl_sync.db')

_MONITOR = None

def _abort_requested():
    global _MONITOR
    if _MONITOR is None:
        _MONITOR = xbmc.Monitor()
    return _MONITOR.abortRequested()

# ------------------------------------------------------------------
# DB
# ------------------------------------------------------------------
def get_connection():
    try:
        conn = __import__('sqlite3', fromlist=['sqlite3']).connect(DB_PATH, timeout=15)
        conn.row_factory = __import__('sqlite3', fromlist=['sqlite3']).Row
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=OFF')
        return conn
    except Exception as e:
        xbmc.log(f'[SIMKL] get_connection error: {e}', xbmc.LOGERROR)
        import sqlite3
        conn = sqlite3.connect(DB_PATH, timeout=15)
        conn.row_factory = sqlite3.Row
        return conn

def _ensure_db():
    """Creeaza tabelele daca lipsesc (DB poate exista fara tabele daca
    sync-ul nu a rulat inca pe acest Kodi)."""
    try:
        init_database()
    except:
        pass

def init_database():
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS simkl_watched_movies (
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
        CREATE TABLE IF NOT EXISTS simkl_watched_episodes (
            tmdb_id TEXT,
            season INTEGER,
            episode INTEGER,
            title TEXT,
            last_watched_at TEXT,
            UNIQUE(tmdb_id, season, episode)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS simkl_playback_progress (
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
        CREATE TABLE IF NOT EXISTS simkl_ratings (
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
        CREATE TABLE IF NOT EXISTS simkl_dropped (
            tmdb_id TEXT PRIMARY KEY,
            dropped_at TEXT,
            title TEXT DEFAULT ''
        )
    ''')
    try:
        c.execute("ALTER TABLE simkl_dropped ADD COLUMN title TEXT DEFAULT ''")
    except:
        pass
    c.execute('''
        CREATE TABLE IF NOT EXISTS simkl_fully_watched_shows (
            tmdb_id TEXT PRIMARY KEY,
            total_episodes INTEGER DEFAULT 0,
            last_watched_at TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS simkl_next_episodes (
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
        CREATE TABLE IF NOT EXISTS simkl_sync_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS simkl_cache (
            key TEXT PRIMARY KEY,
            data TEXT,
            saved_at TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS simkl_watchlist (
            tmdb_id TEXT PRIMARY KEY,
            media_type TEXT,
            status TEXT DEFAULT 'watching',
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
    try:
        c.execute("SELECT value FROM simkl_sync_meta WHERE key=?", (key,))
        row = c.fetchone()
        return row['value'] if row else default
    except:
        return default
    finally:
        conn.close()

def set_sync_meta(key, value):
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("INSERT OR REPLACE INTO simkl_sync_meta (key, value) VALUES (?,?)", (key, str(value)))
        conn.commit()
    except:
        pass
    finally:
        conn.close()

def get_cached(key, ttl=0):
    if not os.path.exists(DB_PATH):
        return None
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT data, saved_at FROM simkl_cache WHERE key=?", (key,))
        row = c.fetchone()
        if row:
            if ttl > 0:
                try:
                    saved = float(row['saved_at'])
                    if time.time() - saved > ttl:
                        return None
                except:
                    pass
            return json.loads(row['data'])
    except:
        return None
    finally:
        conn.close()
    return None

def set_cached(key, data):
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("INSERT OR REPLACE INTO simkl_cache (key, data, saved_at) VALUES (?,?,?)",
                  (key, json.dumps(data), str(time.time())))
        conn.commit()
    except:
        pass
    finally:
        conn.close()

def clear_cached(key):
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("DELETE FROM simkl_cache WHERE key=?", (key,))
        conn.commit()
    except:
        pass
    finally:
        conn.close()

def clear_cache_prefix(prefix):
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("DELETE FROM simkl_cache WHERE key LIKE ?", (f'{prefix}%',))
        conn.commit()
    except:
        pass
    finally:
        conn.close()

def clear_all_local_data():
    """Sterge TOATE datele locale Simkl (folosit la revoke)."""
    try:
        init_database()
    except:
        pass
    conn = get_connection()
    c = conn.cursor()
    try:
        for tbl in ('simkl_watched_movies', 'simkl_watched_episodes', 'simkl_playback_progress',
                    'simkl_ratings', 'simkl_dropped', 'simkl_fully_watched_shows',
                    'simkl_next_episodes', 'simkl_watchlist', 'simkl_cache'):
            try:
                c.execute(f"DELETE FROM {tbl}")
            except:
                pass
        c.execute("DELETE FROM simkl_sync_meta")
        conn.commit()
    except Exception as e:
        xbmc.log(f'[SIMKL] clear_all_local_data error: {e}', xbmc.LOGERROR)
    finally:
        conn.close()

# ------------------------------------------------------------------
# WATCHLIST LOCAL MIRROR
# ------------------------------------------------------------------
def is_in_watchlist(tmdb_id):
    if not os.path.exists(DB_PATH):
        return False
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT 1 FROM simkl_watchlist WHERE tmdb_id=?", (str(tmdb_id),))
        found = c.fetchone() is not None
    except:
        found = False
    conn.close()
    return found

def watchlist_add_local(tmdb_id, media_type, title='', year='', status='watching'):
    try:
        init_database()
    except:
        pass
    conn = get_connection()
    c = conn.cursor()
    now = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z')
    try:
        c.execute("INSERT OR REPLACE INTO simkl_watchlist (tmdb_id, media_type, status, added_at, title, year) VALUES (?,?,?,?,?,?)",
                  (str(tmdb_id), media_type, status, now, title, year))
        conn.commit()
    except:
        pass
    finally:
        conn.close()

def watchlist_remove_local(tmdb_id):
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("DELETE FROM simkl_watchlist WHERE tmdb_id=?", (str(tmdb_id),))
        conn.commit()
    except:
        pass
    finally:
        conn.close()

def get_watchlist_local(status=None):
    _ensure_db()
    if not os.path.exists(DB_PATH):
        return []
    conn = get_connection()
    c = conn.cursor()
    try:
        if status:
            c.execute("SELECT * FROM simkl_watchlist WHERE status=? ORDER BY added_at DESC", (status,))
        else:
            c.execute("SELECT * FROM simkl_watchlist ORDER BY added_at DESC")
        items = [dict(r) for r in c.fetchall()]
    except:
        items = []
    conn.close()
    return items

def sync_watchlist_local(items):
    """Mirror complet: sterge randurile locale care nu mai exista pe server,
    apoi inserarea noilor itemuri cu statusul lor."""
    try:
        init_database()
    except:
        pass
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("DELETE FROM simkl_watchlist")
        rows = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            mt = item.get('mediatype') or item.get('type') or ''
            if mt == 'anime':
                mt = 'anime'
            elif mt in ('show', 'tv', 'series', 'tvshow'):
                mt = 'tv'
            elif mt == 'movie':
                mt = 'movie'
            else:
                # fallback: detect anime wrapper
                if 'anime' in item:
                    mt = 'anime'
                else:
                    mt = 'tv' if 'show' in item or 'seasons' in item else 'movie'
            inner = item.get('show') or item.get('movie') or item.get('anime') or item
            ids = (inner.get('ids') or {}) if isinstance(inner, dict) else {}
            tmdb_id = str(ids.get('tmdb', '') or inner.get('tmdb_id', '') or item.get('tmdb_id', '') or '')
            if not tmdb_id or tmdb_id == 'None':
                continue
            status = str(item.get('status', '') or 'watching')
            added_at = item.get('last_added') or item.get('added_at') or ''
            title = inner.get('title') or inner.get('name') or 'Unknown'
            year = str(inner.get('year', '') or '')
            rows.append((tmdb_id, mt, status, added_at, title, year))
        if rows:
            c.executemany("INSERT OR REPLACE INTO simkl_watchlist (tmdb_id, media_type, status, added_at, title, year) VALUES (?,?,?,?,?,?)", rows)
        conn.commit()
        xbmc.log(f'[SIMKL] watchlist local mirror: {len(rows)} items', xbmc.LOGINFO)
    except Exception as e:
        xbmc.log(f'[SIMKL] sync_watchlist_local error: {e}', xbmc.LOGERROR)
    finally:
        conn.close()

# ------------------------------------------------------------------
# WATCHED CHECKERS
# ------------------------------------------------------------------
def is_movie_watched(tmdb_id):
    _ensure_db()
    if not os.path.exists(DB_PATH):
        return False
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT 1 FROM simkl_watched_movies WHERE tmdb_id=?", (str(tmdb_id),))
    found = c.fetchone()
    conn.close()
    return found is not None

def is_episode_watched(tmdb_id, season, episode):
    _ensure_db()
    if not os.path.exists(DB_PATH):
        return False
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT 1 FROM simkl_watched_episodes WHERE tmdb_id=? AND season=? AND episode=?",
              (str(tmdb_id), int(season), int(episode)))
    found = c.fetchone()
    conn.close()
    return found is not None

def _tmdb_next_unwatched(tid, fallback_season=0):
    """Urmatorul episod NEVIZIONAT din TMDb pentru un serial (fallback cand
    watchlist-ul Simkl nu are next_to_watch SAU il are stale — episod deja
    vizionat, race dupa push: Simkl intarzie sa actualizeze next_to_watch,
    ex. Ride or Die S1E4 marcat -> Simkl inca dadea S01E04 cateva secunde).

    Parcurge: (1) next_episode_to_air din show details (daca episodul nu e
    watched — cazul normal); (2) sezoanele fallback + cel din next_episode_to_air
    cautand primul episod NEVIZIONAT cu air_date (acopera serialele complet
    difuzate fara next_episode_to_air, ex. Ride or Die S1E5 2026-07-15).

    Returneaza (season, episode, ep_title, air_date) sau None."""
    try:
        from resources.lib.tmdb_api import get_tmdb_item_details, get_smart_season_details
        sd = get_tmdb_item_details(str(tid), 'tv', lightweight=True)
        nxt = (sd or {}).get('next_episode_to_air') or {}
        season = int(nxt.get('season_number') or 0)
        episode = int(nxt.get('episode_number') or 0)
        if season > 0 and episode > 0 and nxt.get('air_date'):
            if not is_episode_watched(str(tid), season, episode):
                return (season, episode, nxt.get('name') or '', str(nxt.get('air_date') or '').split('T')[0])
        else:
            season = 0  # next_episode_to_air lipseste (sezon complet difuzat etc.)
        # next_episode_to_air e watched sau lipseste — cautam primul episod
        # NEVIZIONAT cu air_date in sezonul lui + sezonul fallback (din ntw stale)
        search_seasons = []
        if season > 0:
            search_seasons.append(season)
        if fallback_season and fallback_season not in search_seasons:
            search_seasons.append(fallback_season)
        for s in search_seasons:
            try:
                sd2 = get_smart_season_details(str(tid), s)
            except:
                sd2 = None
            if not sd2:
                continue
            for ep in (sd2.get('episodes') or []):
                en = int(ep.get('episode_number') or 0)
                if en <= 0:
                    continue
                if is_episode_watched(str(tid), s, en):
                    continue
                ad = str(ep.get('air_date') or '').split('T')[0]
                if not ad:
                    continue
                return (s, en, ep.get('name') or '', ad)
        return None
    except:
        return None

def get_watched_episodes_count(tmdb_id):
    """Numara doar episoadele individual marcate (fara fallback).
    Exclude rândurile marker (season=0, episode=0) — ramasite din vechiul
    format care falsificau count-ul (Lioness 17/24 in loc de 16/24)."""
    _ensure_db()
    if not os.path.exists(DB_PATH):
        return 0
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM simkl_watched_episodes WHERE tmdb_id=? AND season > 0 AND episode > 0", (str(tmdb_id),))
    count = c.fetchone()[0]
    conn.close()
    return count

def count_watched_episodes_raw(tmdb_id):
    return get_watched_episodes_count(tmdb_id)

def get_watched_season_episodes_count(tmdb_id, season):
    _ensure_db()
    if not os.path.exists(DB_PATH):
        return 0
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM simkl_watched_episodes WHERE tmdb_id=? AND season=?",
              (str(tmdb_id), int(season)))
    count = c.fetchone()[0]
    conn.close()
    return count

def is_fully_watched_show(tmdb_id):
    _ensure_db()
    if not os.path.exists(DB_PATH):
        return False
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT 1 FROM simkl_fully_watched_shows WHERE tmdb_id=?", (str(tmdb_id),))
        found = c.fetchone() is not None
    except:
        found = False
    conn.close()
    return found

# ------------------------------------------------------------------
# MARK WATCHED
# ------------------------------------------------------------------
def mark_as_watched_internal(tmdb_id, content_type, season=None, episode=None, notify=True, sync_simkl=True, refresh_ui=True):
    from resources.lib import tmdb_api
    import threading

    tid = str(tmdb_id)
    conn = get_connection()
    c = conn.cursor()
    now = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z')

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
            c.execute("INSERT OR REPLACE INTO simkl_watched_movies (tmdb_id, title, year, last_watched_at) VALUES (?,?,?,?)",
                      (tid, title_val, str(now)[:4], now))
            c.execute("DELETE FROM simkl_playback_progress WHERE tmdb_id=? AND media_type='movie'", (tid,))
        elif season is not None and episode is not None:
            db_show_title = title_val
            c.execute("INSERT OR REPLACE INTO simkl_watched_episodes VALUES (?,?,?,?,?)",
                      (tid, int(season), int(episode), db_show_title, now))
            c.execute("DELETE FROM simkl_playback_progress WHERE tmdb_id=? AND season=? AND episode=?",
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
                    c.executemany("INSERT OR REPLACE INTO simkl_watched_episodes VALUES (?,?,?,?,?)", rows)
                c.execute("DELETE FROM simkl_playback_progress WHERE tmdb_id=? AND season=?", (tid, int(season)))
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
                    c.executemany("INSERT OR REPLACE INTO simkl_watched_episodes VALUES (?,?,?,?,?)", rows)
                c.execute("INSERT OR REPLACE INTO simkl_fully_watched_shows (tmdb_id, total_episodes, last_watched_at) VALUES (?,?,?)",
                          (tid, total_eps, now))
                c.execute("DELETE FROM simkl_playback_progress WHERE tmdb_id=?", (tid,))
        conn.commit()
    except:
        pass
    finally:
        conn.close()

    # Curatam si tabela locala de resume (paritate cu Trakt)
    try:
        from resources.lib import trakt_sync as _ts
        _ts.remove_local_progress(tid, content_type, season, episode)
    except:
        pass

    if notify:
        msg = f'[B][COLOR yellow]{title_val}[/COLOR][/B] marked watched on [B][COLOR mediumpurple]Simkl[/COLOR][/B]'
        xbmcgui.Dialog().notification('[B][COLOR mediumpurple]Simkl[/COLOR][/B]', msg, SIMKL_ICON, 3000, False)

    if sync_simkl:
        threading.Thread(target=_sync_single_watched, args=(tmdb_id, content_type, season, episode), daemon=True).start()

    if content_type in ('tv', 'show', 'season', 'episode') or season is not None:
        try:
            threading.Thread(target=refresh_next_episode_simkl, args=(tmdb_id,), daemon=True).start()
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
        api = SIMKLAPI()
        result = api.mark_watched(content_type, tmdb_id, season, episode)
        xbmc.log(f'[SIMKL] Push watched {content_type} tmdb={tmdb_id} S{season}E{episode}: {result}', xbmc.LOGINFO)
    except Exception as e:
        xbmc.log(f'[SIMKL] Push watched error tmdb={tmdb_id} S{season}E{episode}: {e}', xbmc.LOGERROR)

def _mark_activities_seen_local():
    """Marca timestamp-urile watched locale la 'now' dupa un push reusit."""
    try:
        cached = json.loads(get_sync_meta('last_activities', '{}'))
    except Exception:
        cached = {}
    if not isinstance(cached, dict):
        cached = {}
    now = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z')
    for key in ('movies.watched_at', 'shows.watched_at', 'episodes.watched_at'):
        if str(cached.get(key) or '') < now:
            cached[key] = now
    set_sync_meta('last_activities', json.dumps(cached))

# ------------------------------------------------------------------
# MARK UNWATCHED
# ------------------------------------------------------------------
def mark_as_unwatched_internal(tmdb_id, content_type, season=None, episode=None, notify=True, sync_simkl=True, refresh_ui=True):
    import threading

    tid = str(tmdb_id)
    conn = get_connection()
    c = conn.cursor()

    title_display = 'Element'
    try:
        if content_type == 'movie':
            c.execute("SELECT title FROM simkl_watched_movies WHERE tmdb_id=?", (tid,))
            r = c.fetchone()
            if r:
                title_display = r[0]
        elif season is not None and episode is not None:
            c.execute("SELECT title FROM simkl_watched_episodes WHERE tmdb_id=? LIMIT 1", (tid,))
            r = c.fetchone()
            if r:
                base_title = r[0].split(' - S')[0]
                title_display = f'{base_title} - S{int(season):02d}E{int(episode):02d}'
            else:
                title_display = f'S{season}E{episode}'
        elif season is not None:
            c.execute("SELECT title FROM simkl_watched_episodes WHERE tmdb_id=? LIMIT 1", (tid,))
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
            from resources.lib import tmdb_api
            show_details = tmdb_api.get_tmdb_item_details(tid, 'tv') or {}
            show_name = show_details.get('name', 'Serial')
            title_display = show_name
    except:
        pass

    try:
        if content_type == 'movie':
            c.execute("DELETE FROM simkl_watched_movies WHERE tmdb_id=?", (tid,))
        elif season is not None and episode is not None:
            c.execute("DELETE FROM simkl_watched_episodes WHERE tmdb_id=? AND season=? AND episode=?",
                      (tid, int(season), int(episode)))
        elif season is not None:
            c.execute("DELETE FROM simkl_watched_episodes WHERE tmdb_id=? AND season=?", (tid, int(season)))
        elif content_type in ('tv', 'show'):
            c.execute("DELETE FROM simkl_watched_episodes WHERE tmdb_id=?", (tid,))
            c.execute("DELETE FROM simkl_fully_watched_shows WHERE tmdb_id=?", (tid,))
        conn.commit()
    except:
        pass
    finally:
        conn.close()

    # Stergem si progresul local de resume
    try:
        from resources.lib import trakt_sync as _ts
        _ts.remove_local_progress(tid, content_type, season, episode)
    except:
        pass

    if notify:
        msg = f'[B][COLOR yellow]{title_display}[/COLOR][/B] marked unwatched on [B][COLOR mediumpurple]Simkl[/COLOR][/B]'
        xbmcgui.Dialog().notification('[B][COLOR mediumpurple]Simkl[/COLOR][/B]', msg, SIMKL_ICON, 3000, False)

    if sync_simkl:
        threading.Thread(target=_sync_single_unwatched, args=(tmdb_id, content_type, season, episode), daemon=True).start()

    if content_type in ('tv', 'show', 'season', 'episode') or season is not None:
        try:
            threading.Thread(target=refresh_next_episode_simkl, args=(tmdb_id,), daemon=True).start()
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
        api = SIMKLAPI()
        result = api.mark_unwatched(content_type, tmdb_id, season, episode)
        xbmc.log(f'[SIMKL] Push unwatched {content_type} tmdb={tmdb_id} S{season}E{episode}: {result}', xbmc.LOGINFO)
    except Exception as e:
        xbmc.log(f'[SIMKL] Push unwatched error tmdb={tmdb_id} S{season}E{episode}: {e}', xbmc.LOGERROR)

# ------------------------------------------------------------------
# NEXT EPISODE REFRESH (single show)
# ------------------------------------------------------------------
def refresh_next_episode_simkl(tmdb_id, ignore_hidden=False):
    """Recalculeaza episodul Up Next local dupa mark watched/unwatched.

    Paritate completa cu Trakt (trakt_sync.refresh_next_episode) si MDBList
    (mdblist_sync.refresh_next_episode_mdblist): calcul 100% LOCAL din
    simkl_watched_episodes + sezoanele TMDb — FARA next_to_watch de la server.
    Asta elimina race-urile dupa push (Simkl intarzie sa actualizeze
    next_to_watch cateva secunde; baza locala e actualizata IMEDIAT inainte
    de refresh, deci calculul e mereu corect — ex. Ride or Die S1E4 unwatch
    -> S1E4 reapare instant, fara sa ramana S1E5).
    """
    from resources.lib import tmdb_api
    import datetime

    def _trigger_ui_refresh():
        try:
            import xbmc
            container_path = xbmc.getInfoLabel('Container.FolderPath')
            if not container_path or 'plugin.video.tmdbmovies' in container_path.lower():
                xbmc.executebuiltin("Container.Refresh")
        except:
            pass

    try:
        tid = str(tmdb_id)
        show_details = tmdb_api.get_tmdb_item_details(tid, 'tv')
        if not show_details:
            return
        show_title = show_details.get('name', 'Unknown Show')

        if not os.path.exists(DB_PATH):
            return
        conn = get_connection()
        c = conn.cursor()

        # Dropped → scoatem din Up Next
        if not ignore_hidden:
            c.execute("SELECT 1 FROM simkl_dropped WHERE tmdb_id=?", (tid,))
            if c.fetchone():
                conn.execute("DELETE FROM simkl_next_episodes WHERE tmdb_id=?", (tid,))
                conn.commit()
                conn.close()
                _trigger_ui_refresh()
                return

        # Istoricul exact vizionat local + ultimul episod vizionat cronologic
        c.execute("SELECT season, episode FROM simkl_watched_episodes WHERE tmdb_id=?", (tid,))
        watched_eps = set((r[0], r[1]) for r in c.fetchall())
        c.execute("SELECT season, episode FROM simkl_watched_episodes WHERE tmdb_id=? ORDER BY last_watched_at DESC LIMIT 1", (tid,))
        last_row = c.fetchone()

        # Fara episoade vizionate: daca e in plantowatch, apare S1E1 la coada; altfel iese
        if not watched_eps:
            try:
                c.execute("SELECT 1 FROM simkl_watchlist WHERE tmdb_id=? AND status='plantowatch' AND media_type IN ('tv','anime')", (tid,))
                in_wl = bool(c.fetchone())
            except:
                in_wl = False
            if in_wl:
                from resources.lib.trakt_sync import _tmdb_first_episode as _first, _tmdb_ep_meta as _meta
                nxt = _first(show_details)
                if nxt:
                    ep_title, _, air_date = _meta(tid, nxt['season'], nxt['number'])
                    now_str = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
                    c.execute("INSERT OR REPLACE INTO simkl_next_episodes (tmdb_id, show_title, season, episode, ep_title, air_date, watched_count, total_count, last_watched_at) VALUES (?,?,?,?,?,?,?,?,?)",(tid, show_title, nxt['season'], nxt['number'], ep_title, air_date, 0, 0, now_str))
                    conn.commit(); conn.close(); _trigger_ui_refresh(); return
            conn.execute("DELETE FROM simkl_next_episodes WHERE tmdb_id=?", (tid,))
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

        # Fallback: scanare de la inceput (gap-uri de episoade demarcate)
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
            conn.execute("DELETE FROM simkl_next_episodes WHERE tmdb_id=?", (tid,))
            conn.commit()
            conn.close()
            _trigger_ui_refresh()
            return

        # Metadatele noului episod (cache TMDb)
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

        # Episoadele viitoare raman in lista (paritate Trakt + hide_unreleased=False):
        # filtrarea pe upnext_show_future se face la afisare, nu la stocare.
        now_str = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
        c.execute(
            "INSERT OR REPLACE INTO simkl_next_episodes "
            "(tmdb_id, show_title, season, episode, ep_title, air_date, watched_count, total_count, last_watched_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (tid, show_title, next_ep['season'], next_ep['number'],
             ep_title, air_date, len(watched_eps),
             show_details.get('number_of_episodes', 0), now_str)
        )
        conn.commit()
        conn.close()
        _trigger_ui_refresh()
    except Exception as e:
        xbmc.log(f'[SIMKL] refresh_next_episode_simkl error: {e}', xbmc.LOGERROR)

def _trigger_ui_refresh():
    try:
        from resources.lib.watched_provider import refresh_ui
        refresh_ui()
    except:
        pass

# ------------------------------------------------------------------
# FULL SYNC (Phase 1 / Phase 2)
# ------------------------------------------------------------------
SYNC_LOCK_KEY = 'simkl_sync_active'

def sync_full_library(silent=False, force=False):
    """Sync complet conform regulilor API Simkl:
      - Phase 1: /sync/shows + /sync/movies + /sync/anime SECVENTIAL, fara date_from
      - Phase 2: /sync/activities -> comparatie cu salvate; diferit -> /sync/all-items/?date_from=
      - Throttle: fara force, max o verificare la 15 min
      - Fara polling neconditionat — doar la pornire / sfarsit playback / manual
      - Gating intern (paritate MDBList): watched/ratings/playback/upnext DOAR daca
        Simkl e providerul activ; TOATE endpoint-urile user-specific (watchlist/
        dropped inclusiv) ruleaza doar daca /sync/activities arata schimbari
        (sau force manual); calendarul (CDN public) pe TTL 24h.
    """
    from resources.lib.watched_provider import is_simkl as _is_simkl_provider
    is_active = _is_simkl_provider()
    if not SIMKL_CLIENT_ID:
        return

    api = SIMKLAPI()
    if not api.is_authenticated():
        return

    # Gate global de sincronizare (evita sync-uri concurente)
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT value FROM simkl_sync_meta WHERE key=?", (SYNC_LOCK_KEY,))
        row = c.fetchone()
        lock = row and row['value']
        if lock and not force:
            xbmc.log('[SIMKL] Sync already running, skipping', xbmc.LOGINFO)
            conn.close()
            return
        c.execute("INSERT OR REPLACE INTO simkl_sync_meta (key, value) VALUES (?,?)", (SYNC_LOCK_KEY, '1'))
        conn.commit()
        conn.close()
    except:
        pass

    try:
        xbmc.log(f'[SIMKL SYNC] Starting (provider_active={"simkl" if is_active else "other"}, force={force}, silent={silent})', xbmc.LOGINFO)
        # Throttle 15 min (fara force)
        if not force:
            try:
                last = float(get_sync_meta('last_sync_ts', '0') or 0)
                if last and (time.time() - last) < 15 * 60:
                    xbmc.log('[SIMKL] Sync throttled (<15 min since last)', xbmc.LOGINFO)
                    return
            except:
                pass

        # ---- Phase 2 gate: /sync/activities ----
        changed = True
        saved_activities = None
        try:
            saved_activities = get_sync_meta('last_activities', '')
        except:
            saved_activities = ''
        activities = None
        try:
            activities = api.get_activities()
        except Exception as e:
            xbmc.log(f'[SIMKL] get_activities error: {e}', xbmc.LOGERROR)

        if activities and isinstance(activities, dict):
            new_digest = json.dumps(activities, sort_keys=True, default=str)
            if saved_activities and new_digest == saved_activities:
                changed = False
            set_sync_meta('last_activities', new_digest)

        if (changed or force) and is_active:
            last_date = get_sync_meta('last_sync_date', '')
            if last_date and not force:
                # ---- Phase 2 delta ----
                _sync_all_items_delta(api, last_date)
            else:
                # ---- Phase 1 (initial sau force=True: full sync cu DELETE mirror) ----
                # force trebuie sa faca full: delta nu sterge rândurile locale
                # care nu mai sunt pe server (ex. filme un-watched pe site).
                _sync_watched_phase1(api)
            set_sync_meta('last_sync_date', datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z'))

        # Gating pe activities (regula API Simkl): watchlist/upnext/ratings/
        # playback/dropped sunt endpoint-uri user-specific — se apeleaza DOAR
        # daca /sync/activities arata schimbari (sau force manual). Daca activitatile
        # n-au miscat, zero apeluri API. Calendarul (CDN public) ramane pe TTL 24h.
        if changed or force:
            xbmc.log(f'[SIMKL SYNC] Flags: watched={is_active} upnext={is_active} ratings={is_active} playback={is_active} watchlist=True dropped=True calendar=True (provider={"simkl" if is_active else "other"})', xbmc.LOGINFO)
            _sync_watchlist(api)
            if is_active:
                _sync_up_next(api)
                _sync_ratings(api)
            _sync_dropped(api)
            if is_active:
                _sync_playback(api)
            _sync_calendar(api)
        else:
            xbmc.log('[SIMKL SYNC] No activity changes - skipping user endpoints (activities gate)', xbmc.LOGINFO)

        set_sync_meta('last_sync_ts', str(time.time()))
        set_sync_meta('last_sync', datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z'))

        from resources.lib.cache import clear_all_fast_cache
        try:
            clear_all_fast_cache()
        except:
            pass

        if not silent:
            _trigger_ui_refresh()
    except Exception as e:
        xbmc.log(f'[SIMKL] sync_full_library error: {e}', xbmc.LOGERROR)
    finally:
        try:
            conn = get_connection()
            c = conn.cursor()
            c.execute("DELETE FROM simkl_sync_meta WHERE key=?", (SYNC_LOCK_KEY,))
            conn.commit()
            conn.close()
        except:
            pass

def _sync_watched_phase1(api):
    """Phase 1: /sync/all-items FARA date_from (full sync).

    /sync/shows + /sync/movies + /sync/anime sunt RETRASE de Simkl (200 null
    indiferent de parametri, verificat live) — totul vine din all-items acum.
    DELETE mirror la inceput (paritate cu trakt_sync/mdblist_sync): rândurile
    locale care nu mai sunt pe server se sterg — altfel raman watched la infinit
    (bug-ul Lioness 17/24: rândul marker (0,0) vechi ramanea dupa ce serverul
    a inceput sa trimita seasons)."""
    xbmc.log('[SIMKL] Phase 1: full sync (all-items, no date_from)', xbmc.LOGINFO)
    data = api.get_all_items(None)
    if not data or not isinstance(data, dict):
        return
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM simkl_watched_episodes")
        c.execute("DELETE FROM simkl_watched_movies")
        c.execute("DELETE FROM simkl_fully_watched_shows")
        conn.commit()
        conn.close()
    except Exception as e:
        xbmc.log(f'[SIMKL] phase1 delete mirror error: {e}', xbmc.LOGERROR)
    _store_watched_shows(data)
    _store_watched_movies(data)

def _sync_all_items_delta(api, date_from):
    """Phase 2: /sync/all-items/?date_from=... (shows + movies + anime intr-un singur request).
    Fara DELETE mirror — delta intoarce doar itemele schimbate."""
    xbmc.log(f'[SIMKL] Phase 2: delta sync date_from={date_from}', xbmc.LOGINFO)
    data = api.get_all_items(date_from)
    if not data or not isinstance(data, dict):
        return
    _store_watched_shows(data)
    _store_watched_movies(data)

def _store_watched_shows(data):
    """Parsarea raspunsurilor /sync/shows, /sync/anime, /sync/all-items (sectiunea shows/anime).

    Reguli (verificate live pe all-items, cont real):
    - seriale cu seasons enumerate -> episoadele watched marcate individual.
    - seriale FARA seasons + w >= aired (complet vizionate) -> marker in
      simkl_fully_watched_shows (NU rând (0,0) in watched_episodes — rândul
      (0,0) falsifica get_watched_episodes_count, ex. Lioness 17/24 in loc de
      16/24).
    - seriale FARA seasons + w < aired (ex. Vikings 9/89, Quantico 22/57 —
      8 cazuri live) -> serverul nu enumera episoadele -> nu putem marca
      episoade individuale -> skip (fara falsuri).
    - seriale FARA seasons + w=0 (doar in watchlist plantowatch/watching —
      98 cazuri live) -> NU sunt watched -> skip complet (inainte primeau
      rând (0,0) cu last_watched_at=now -> fals pozitiv)."""
    conn = get_connection()
    c = conn.cursor()
    try:
        ep_rows = []
        show_ids = set()
        fully_rows = []
        for key in ('shows', 'anime'):
            for item in data.get(key, []) or []:
                if not isinstance(item, dict):
                    continue
                inner = item.get('show') or item.get('anime') or item
                ids = (inner.get('ids') or {}) if isinstance(inner, dict) else {}
                tmdb_id = str(ids.get('tmdb', '') or inner.get('tmdb_id', '') or item.get('tmdb_id', '') or '')
                if not tmdb_id or tmdb_id == 'None':
                    continue
                show_ids.add(tmdb_id)
                title = inner.get('title') or inner.get('name') or 'Unknown Show'
                year = str(inner.get('year', '') or '')
                show_watched_at = item.get('last_watched_at') or item.get('watched_at') or ''
                w = item.get('watched_episodes_count')
                t = item.get('total_episodes_count')
                na = item.get('not_aired_episodes_count')
                aired = 0
                if isinstance(w, int) and isinstance(t, int) and t > 0:
                    aired = t - (na if isinstance(na, int) else 0)
                seasons = item.get('seasons') or []
                ep_count = 0
                for s in seasons or []:
                    s_num = s.get('number', s.get('season', 0))
                    for ep in s.get('episodes', []) or []:
                        e_num = ep.get('number', ep.get('episode', 0))
                        if not s_num or not e_num:
                            continue
                        ep_watched_at = ep.get('last_watched_at') or ep.get('watched_at') or show_watched_at
                        ep_rows.append((tmdb_id, int(s_num), int(e_num), title, ep_watched_at))
                        ep_count += 1
                if ep_count == 0:
                    if isinstance(w, int) and w > 0 and (aired == 0 or w >= aired):
                        fully_rows.append((tmdb_id, t if isinstance(t, int) else 0,
                                           show_watched_at or datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z')))
        if ep_rows:
            c.executemany("INSERT OR REPLACE INTO simkl_watched_episodes VALUES (?,?,?,?,?)", ep_rows)
        if fully_rows:
            c.executemany("INSERT OR REPLACE INTO simkl_fully_watched_shows VALUES (?,?,?)", fully_rows)
        conn.commit()
        xbmc.log(f'[SIMKL] watched shows stored: {len(ep_rows)} episode rows for {len(show_ids)} shows, {len(fully_rows)} fully watched', xbmc.LOGINFO)
    except Exception as e:
        xbmc.log(f'[SIMKL] _store_watched_shows error: {e}', xbmc.LOGERROR)
    finally:
        conn.close()

def _store_watched_movies(data):
    """Filmele watched din all-items. FARA fallback la now: un film fara
    last_watched_at (status plantowatch in watchlist) NU e watched — fallback-ul
    `or now` marca toate cele 259 de filme plantowatch ca vizionate la fiecare
    sync (bug: The Invite, Disclosure Day, Minions & Monsters false watched)."""
    conn = get_connection()
    c = conn.cursor()
    try:
        rows = []
        for item in data.get('movies', []) or []:
            if not isinstance(item, dict):
                continue
            inner = item.get('movie') or item
            ids = (inner.get('ids') or {}) if isinstance(inner, dict) else {}
            tmdb_id = str(ids.get('tmdb', '') or inner.get('tmdb_id', '') or item.get('tmdb_id', '') or '')
            if not tmdb_id or tmdb_id == 'None':
                continue
            watched_at = item.get('last_watched_at') or item.get('watched_at') or ''
            if not watched_at:
                continue
            title = inner.get('title') or 'Unknown Movie'
            year = str(inner.get('year', '') or '')
            rows.append((tmdb_id, title, year, watched_at))
        if rows:
            c.executemany("INSERT OR REPLACE INTO simkl_watched_movies (tmdb_id, title, year, last_watched_at) VALUES (?,?,?,?)", rows)
        conn.commit()
        xbmc.log(f'[SIMKL] watched movies stored: {len(rows)}', xbmc.LOGINFO)
    except Exception as e:
        xbmc.log(f'[SIMKL] _store_watched_movies error: {e}', xbmc.LOGERROR)
    finally:
        conn.close()

def _sync_watchlist(api):
    """Mirror local al watchlist-ului (toate statusurile)."""
    try:
        data = api.get_watchlist(extended='full')
        if not data or not isinstance(data, dict):
            return
        items = []
        for key, mt in (('shows', 'tv'), ('anime', 'anime'), ('movies', 'movie')):
            for item in data.get(key, []) or []:
                if isinstance(item, dict):
                    it = dict(item)
                    it['mediatype'] = mt
                    items.append(it)
        sync_watchlist_local(items)
    except Exception as e:
        xbmc.log(f'[SIMKL] _sync_watchlist error: {e}', xbmc.LOGERROR)

def _enrich_air_dates(rows):
    """Completeaza air_date + ep_title din TMDb pentru serialele Simkl (watchlist-ul
    trimite doar SXXEYY, fara data/nume episod). Fara asta, filtrele
    upnext_show_future / 7 zile / TBA si numele episoadelor nu pot functiona
    identic cu Trakt/MDBList. get_smart_season_details are cache RAM+SQLite,
    deci dupa prima sincronizare totul e instant."""
    try:
        from concurrent.futures import ThreadPoolExecutor
        from resources.lib.tmdb_api import get_smart_season_details
        enriched = {}
        lock = threading.Lock()
        def _worker(row):
            try:
                if row[5]:
                    return
                tmdb_id = str(row[0])
                season = int(row[2])
                episode = int(row[3])
                sd = get_smart_season_details(tmdb_id, season)
                if not sd:
                    return
                for ep in sd.get('episodes', []) or []:
                    if int(ep.get('episode_number') or 0) == episode:
                        ad = ep.get('air_date') or ''
                        if ad:
                            ad = str(ad).split('T')[0]
                        nm = ep.get('name') or ''
                        if ad or nm:
                            with lock:
                                enriched[tmdb_id] = (ad, nm)
                        return
            except:
                pass
        with ThreadPoolExecutor(max_workers=5) as ex:
            for row in rows:
                ex.submit(_worker, row)
        out = []
        for r in rows:
            ad, nm = enriched.get(str(r[0]), ('', ''))
            out.append((r[0], r[1], r[2], r[3], nm or r[4], ad or r[5], r[6], r[7], r[8]))
        return out
    except:
        return rows


def _sync_up_next(api):
    """Up Next Simkl = seriale din watchlist cu status 'watching' + next_to_watch."""
    conn = get_connection()
    c = conn.cursor()
    try:
        data = api.get_watchlist(status='watching', extended='full')
        if not data or not isinstance(data, dict):
            return
        rows = []
        for key in ('shows', 'anime'):
            for item in data.get(key, []) or []:
                if not isinstance(item, dict):
                    continue
                inner = item.get('show') or item.get('anime') or item
                ids = (inner.get('ids') or {}) if isinstance(inner, dict) else {}
                tmdb_id = str(ids.get('tmdb', '') or inner.get('tmdb_id', '') or item.get('tmdb_id', '') or '')
                if not tmdb_id or tmdb_id == 'None':
                    continue
                ntw = item.get('next_to_watch') or item.get('next_episode') or ''
                # next_to_watch e STRING in formatul real ("S08E09"), nu dict —
                # dict (season/episode) era presupus si crapa cu AttributeError
                # -> _sync_up_next esua silentios -> tabela ramanea cu date vechi
                season = 0
                episode = 0
                if isinstance(ntw, dict):
                    season = int(ntw.get('season') or 0)
                    episode = int(ntw.get('episode') or 0)
                else:
                    m = re.match(r'^S(\d+)E(\d+)', str(ntw).strip().upper())
                    if m:
                        season = int(m.group(1))
                        episode = int(m.group(2))
                show_title = inner.get('title') or inner.get('name') or 'Unknown Show'
                ep_title = ntw.get('title') if isinstance(ntw, dict) else ''
                air_date = (ntw.get('released') or ntw.get('air_date') or '') if isinstance(ntw, dict) else ''
                if air_date:
                    air_date = str(air_date).split('T')[0]
                if season <= 0 or episode <= 0 or is_episode_watched(tmdb_id, season, episode):
                    # Serial la zi cu difuzarea (next_to_watch gol) sau ntw STALE
                    # (episodul deja vizionat — race dupa push: Simkl intarzie sa
                    # actualizeze next_to_watch, ex. Ride or Die S1E4) — cautam
                    # episodul VIITOR anuntat in TMDb (paritate Trakt/MDBList:
                    # Tulsa King S4E1, Chad Powers S2E1 apar doar cu 'show future'
                    # ON; Reacher S4E5 / Ride or Die S1E5 difuzate apar mereu).
                    found_next = _tmdb_next_unwatched(tmdb_id, fallback_season=season)
                    if not found_next:
                        continue
                    season, episode, ep_title, air_date = found_next
                watched_count = get_watched_episodes_count(tmdb_id)
                last_watched_at = item.get('last_watched_at') or item.get('last_added') or ''
                rows.append((tmdb_id, show_title, season, episode, ep_title, air_date,
                             watched_count, 0, last_watched_at))
        # === UNSTARTED: plan to watch tv/anime cu watched==0 la coada (doar Simkl) ===
        try:
            c.execute("SELECT tmdb_id, title FROM simkl_watchlist WHERE status='plantowatch' AND media_type IN ('tv','anime')")
            wl_rows = c.fetchall()
            if wl_rows:
                try:
                    c.execute("SELECT tmdb_id FROM simkl_dropped")
                    hidden_ids = {str(row[0]) for row in c.fetchall()}
                except:
                    hidden_ids = set()
                existing_ids = {str(r[0]) for r in rows}
                cands = []
                for row in wl_rows:
                    tid = str(row[0])
                    if not tid or tid in existing_ids or tid in hidden_ids:
                        continue
                    try:
                        # watched>0 => deja inceput, nu e unstarted
                        if get_watched_episodes_count(tid) > 0:
                            continue
                    except:
                        continue
                    cands.append((tid, row[1] or 'Unknown Show'))
                if cands:
                    from resources.lib import tmdb_api as _tmdb_api
                    from resources.lib.trakt_sync import _tmdb_first_episode as _first, _tmdb_ep_meta as _meta, get_poster_from_db as _poster
                    from concurrent.futures import ThreadPoolExecutor as _TPE, as_completed as _ac
                    def _fetch_unstarted(entry):
                        tid, title = entry
                        try:
                            sd = _tmdb_api.get_tmdb_item_details(tid, 'tv', lightweight=True, skip_localization=True)
                            if not sd:
                                return None
                            nxt = _first(sd)
                            if not nxt:
                                return None
                            ep_title, ep_overview, air_date = _meta(tid, nxt['season'], nxt['number'])
                            return (tid, title or sd.get('name','Unknown Show'), nxt['season'], nxt['number'], ep_title, air_date, 0, 0, '')
                        except:
                            return None
                    with _TPE(max_workers=10) as ex:
                        futs = {ex.submit(_fetch_unstarted, e): e for e in cands}
                        for f in _ac(futs):
                            res = f.result()
                            if res:
                                rows.append(res)
        except Exception as e:
            xbmc.log(f'[SIMKL] up next unstarted plantowatch error: {e}', xbmc.LOGWARNING)

        if rows:
            rows = _enrich_air_dates(rows)
            c.execute("DELETE FROM simkl_next_episodes")
            c.executemany("INSERT OR REPLACE INTO simkl_next_episodes "
                          "(tmdb_id, show_title, season, episode, ep_title, air_date, watched_count, total_count, last_watched_at) "
                          "VALUES (?,?,?,?,?,?,?,?,?)", rows)
        else:
            c.execute("DELETE FROM simkl_next_episodes")
        conn.commit()
        xbmc.log(f'[SIMKL] up next stored: {len(rows)} shows', xbmc.LOGINFO)
    except Exception as e:
        xbmc.log(f'[SIMKL] _sync_up_next error: {e}', xbmc.LOGERROR)
    finally:
        conn.close()

def _precache_up_next():
    """Pre-fetch metadatele pentru serialele Up Next (paritate cu MDBList)."""
    try:
        items = get_next_episodes_from_db()
        if not items:
            return
        from concurrent.futures import ThreadPoolExecutor
        def _worker(it):
            try:
                from resources.lib.tmdb_api import get_smart_season_details
                get_smart_season_details(str(it['tmdb_id']), it['season'])
            except:
                pass
        executor = ThreadPoolExecutor(max_workers=3)
        for it in items[:10]:
            executor.submit(_worker, it)
        executor.shutdown(wait=False)
    except:
        pass

def get_next_episodes_from_db():
    """Toate serialele Up Next din DB local (paritate cu mdblist)."""
    if not os.path.exists(DB_PATH):
        return []
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT tmdb_id, show_title, season, episode, ep_title, air_date, "
                  "watched_count, total_count, last_watched_at "
                  "FROM simkl_next_episodes "
                  "WHERE tmdb_id NOT IN (SELECT tmdb_id FROM simkl_dropped) "
                  "ORDER BY last_watched_at DESC")
        rows = c.fetchall()
    except Exception as e:
        xbmc.log(f'[SIMKL] get_next_episodes_from_db error: {e}', xbmc.LOGERROR)
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
    """Seriale in progres: watched > 0 si (total necunoscut sau watched < total)."""
    if not os.path.exists(DB_PATH):
        return []
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT tmdb_id, show_title, season, episode, ep_title, air_date, "
                  "watched_count, total_count, last_watched_at "
                  "FROM simkl_next_episodes "
                  "WHERE tmdb_id NOT IN (SELECT tmdb_id FROM simkl_dropped) "
                  "AND watched_count > 0 "
                  "AND (total_count = 0 OR watched_count < total_count) "
                  "ORDER BY last_watched_at DESC")
        rows = c.fetchall()
    except Exception as e:
        xbmc.log(f'[SIMKL] get_in_progress_tvshows_from_db error: {e}', xbmc.LOGERROR)
        rows = []
    finally:
        conn.close()
    return [
        {'tmdb_id': r[0], 'show_title': r[1], 'season': r[2], 'episode': r[3],
         'ep_title': r[4], 'air_date': r[5], 'watched_count': r[6],
         'total_count': r[7], 'last_watched_at': r[8]}
        for r in rows
    ]

# ------------------------------------------------------------------
# RATINGS
# ------------------------------------------------------------------
def _sync_ratings(api):
    conn = get_connection()
    c = conn.cursor()
    try:
        data = api.get_sync_ratings(extended='full')
        if not data or not isinstance(data, dict):
            return
        rows = []
        for item in data.get('movies', []) or []:
            if not isinstance(item, dict):
                continue
            inner = item.get('movie') or item
            ids = (inner.get('ids') or {}) if isinstance(inner, dict) else {}
            tmdb_id = str(ids.get('tmdb', '') or inner.get('tmdb_id', '') or item.get('tmdb_id', '') or '')
            rating = item.get('user_rating')
            if rating is None:
                rating = item.get('rating')
            rated_at = item.get('user_rated_at') or item.get('rated_at') or ''
            if tmdb_id and tmdb_id != 'None' and rating is not None:
                rows.append((tmdb_id, 'movie', 0, 0, rating, rated_at))
        for item in data.get('shows', []) or []:
            if not isinstance(item, dict):
                continue
            inner = item.get('show') or item
            ids = (inner.get('ids') or {}) if isinstance(inner, dict) else {}
            tmdb_id = str(ids.get('tmdb', '') or inner.get('tmdb_id', '') or item.get('tmdb_id', '') or '')
            rating = item.get('user_rating')
            if rating is None:
                rating = item.get('rating')
            rated_at = item.get('user_rated_at') or item.get('rated_at') or ''
            if tmdb_id and tmdb_id != 'None' and rating is not None:
                rows.append((tmdb_id, 'show', 0, 0, rating, rated_at))
                for season in item.get('seasons') or []:
                    if not isinstance(season, dict):
                        continue
                    for ep in season.get('episodes') or []:
                        if not isinstance(ep, dict):
                            continue
                        ep_rating = ep.get('user_rating')
                        if ep_rating is None:
                            ep_rating = ep.get('rating')
                        if ep_rating is None:
                            continue
                        ep_rated_at = ep.get('user_rated_at') or ep.get('rated_at') or rated_at
                        rows.append((tmdb_id, 'episode', int(season.get('number') or 0),
                                     int(ep.get('number') or 0), ep_rating, ep_rated_at))
        if rows:
            # Upsert din GET — NU stergem rândurile care lipsesc din raspuns:
            # filmele/serialele inexistente in baza Simkl (POST 201 dar lipsesc
            # din GET — verificat live) raman ca marcaje de import in tabela
            # locala; altfel re-importul le retrimite la fiecare rulare.
            c.executemany("INSERT OR REPLACE INTO simkl_ratings (tmdb_id, media_type, season, episode, rating, rated_at) VALUES (?,?,?,?,?,?)", rows)
            conn.commit()
            xbmc.log(f'[SIMKL] ratings stored: {len(rows)}', xbmc.LOGINFO)
    except Exception as e:
        xbmc.log(f'[SIMKL] _sync_ratings error: {e}', xbmc.LOGERROR)
    finally:
        conn.close()

# ------------------------------------------------------------------
# PLAYBACK
# ------------------------------------------------------------------
def _sync_playback(api):
    """Importa sesiunile de playback din /sync/playback (format Simkl:
    dict cu cheile movies/shows + progress + paused_at)."""
    conn = get_connection()
    c = conn.cursor()
    try:
        data = api.get_playback()
        if not data or not isinstance(data, dict):
            return
        rows = []
        for item in data.get('movies', []) or []:
            if not isinstance(item, dict):
                continue
            inner = item.get('movie') or item
            ids = (inner.get('ids') or {}) if isinstance(inner, dict) else {}
            tmdb_id = str(ids.get('tmdb', '') or inner.get('tmdb_id', '') or item.get('tmdb_id', '') or '')
            if not tmdb_id or tmdb_id == 'None':
                continue
            try:
                progress = float(item.get('progress', 0) or 0)
            except:
                progress = 0.0
            updated = item.get('paused_at') or item.get('last_watched_at') or ''
            rows.append((tmdb_id, 'movie', 0, 0, str(item.get('id', '')), progress, updated))
        for item in data.get('shows', []) or []:
            if not isinstance(item, dict):
                continue
            inner = item.get('show') or item
            ids = (inner.get('ids') or {}) if isinstance(inner, dict) else {}
            tmdb_id = str(ids.get('tmdb', '') or inner.get('tmdb_id', '') or item.get('tmdb_id', '') or '')
            if not tmdb_id or tmdb_id == 'None':
                continue
            ep_obj = item.get('episode') or {}
            try:
                season = int(ep_obj.get('season', item.get('season', 0)) or 0)
            except:
                season = 0
            try:
                episode = int(ep_obj.get('number', item.get('episode', 0)) or 0)
            except:
                episode = 0
            try:
                progress = float(item.get('progress', 0) or 0)
            except:
                progress = 0.0
            updated = item.get('paused_at') or item.get('last_watched_at') or ''
            rows.append((tmdb_id, 'episode', season, episode, str(item.get('id', '')), progress, updated))
        if rows:
            c.execute("DELETE FROM simkl_playback_progress")
            c.executemany("INSERT OR REPLACE INTO simkl_playback_progress VALUES (?,?,?,?,?,?,?)", rows)
            conn.commit()
            xbmc.log(f'[SIMKL] playback stored: {len(rows)} sessions', xbmc.LOGINFO)
    except Exception as e:
        xbmc.log(f'[SIMKL] _sync_playback error: {e}', xbmc.LOGERROR)
    finally:
        conn.close()

    # --- IMPORT IN TABELA LOCALA DE RESUME (playback_progress din trakt_sync.db) ---
    try:
        from resources.lib.watched_provider import is_simkl as _is_simkl_provider
        if not _is_simkl_provider():
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
        for item in (data or {}).get('movies', []) + (data or {}).get('shows', []):
            if not isinstance(item, dict):
                continue
            type_ = 'movie' if item in (data or {}).get('movies', []) else 'episode'
            try:
                progress = float(item.get('progress', 0) or 0)
            except:
                progress = 0.0
            if progress <= 1 or progress >= 99:
                continue
            if type_ == 'movie':
                inner = item.get('movie') or {}
                tid = str(inner.get('ids', {}).get('tmdb', '') or item.get('tmdb_id', ''))
                s, e = 0, 0
                title = inner.get('title', 'Unknown Movie')
                year = str(inner.get('year', ''))
            else:
                inner = item.get('show') or {}
                tid = str(inner.get('ids', {}).get('tmdb', '') or item.get('tmdb_id', ''))
                ep_obj = item.get('episode') or {}
                try:
                    s = int(ep_obj.get('season', item.get('season', 0)) or 0)
                except:
                    s = 0
                try:
                    e = int(ep_obj.get('number', item.get('episode', 0)) or 0)
                except:
                    e = 0
                show_title = inner.get('title', 'Unknown Show')
                ep_title = ep_obj.get('title', '')
                title = f"{show_title} - S{s:02d}E{e:02d}"
                if ep_title:
                    title += f" - {ep_title}"
                year = str(inner.get('year', ''))
            if not tid or tid == 'None':
                continue
            paused_at = item.get('paused_at') or item.get('last_watched_at') or ''
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
        xbmc.log(f'[SIMKL] local playback merge error: {e}', xbmc.LOGERROR)

# ------------------------------------------------------------------
# DROPPED
# ------------------------------------------------------------------
def _sync_dropped(api):
    """Simkl: dropped = status 'dropped' din watchlist."""
    conn = get_connection()
    c = conn.cursor()
    try:
        data = api.get_watchlist(status='dropped', extended='full')
        if not data or not isinstance(data, dict):
            return
        rows = []
        for key in ('shows', 'anime', 'movies'):
            for item in data.get(key, []) or []:
                if not isinstance(item, dict):
                    continue
                inner = item.get('show') or item.get('anime') or item.get('movie') or item
                ids = (inner.get('ids') or {}) if isinstance(inner, dict) else {}
                tmdb_id = str(ids.get('tmdb', '') or inner.get('tmdb_id', '') or item.get('tmdb_id', '') or '')
                if not tmdb_id or tmdb_id == 'None':
                    continue
                title = inner.get('title') or inner.get('name') or ''
                dropped_at = item.get('last_added') or item.get('added_at') or ''
                rows.append((tmdb_id, dropped_at, title))
        if rows:
            c.execute("DELETE FROM simkl_dropped")
            c.executemany("INSERT OR REPLACE INTO simkl_dropped (tmdb_id, dropped_at, title) VALUES (?,?,?)", rows)
            conn.commit()
            xbmc.log(f'[SIMKL] dropped stored: {len(rows)}', xbmc.LOGINFO)
        else:
            c.execute("DELETE FROM simkl_dropped")
            conn.commit()
        try:
            clear_cache_prefix('simkl_wl_dropped')
        except Exception:
            pass
    except Exception as e:
        xbmc.log(f'[SIMKL] _sync_dropped error: {e}', xbmc.LOGERROR)
    finally:
        conn.close()

# ------------------------------------------------------------------
# CALENDAR
# ------------------------------------------------------------------
def _sync_calendar(api):
    """Calendar CDN public (data.simkl.in) - salvat in cache TTL 24h."""
    try:
        if get_cached('calendar', ttl=86400) is not None:
            return
        data = api.calendar_events()
        if data is not None:
            set_cached('calendar', data)
    except Exception as e:
        xbmc.log(f'[SIMKL] _sync_calendar error: {e}', xbmc.LOGERROR)

# ------------------------------------------------------------------
# DROPPED HELPERS (paritate cu mdblist_sync)
# ------------------------------------------------------------------
def is_dropped(tmdb_id):
    _ensure_db()
    if not os.path.exists(DB_PATH):
        return False
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT 1 FROM simkl_dropped WHERE tmdb_id=?", (str(tmdb_id),))
    found = c.fetchone()
    conn.close()
    return found is not None

def drop_add_local(tmdb_id, title=''):
    try:
        init_database()
    except:
        pass
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO simkl_dropped (tmdb_id, dropped_at, title) VALUES (?,?,?)",
              (str(tmdb_id), datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z'), title or ''))
    conn.commit()
    conn.close()

def drop_remove_local(tmdb_id):
    _ensure_db()
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM simkl_dropped WHERE tmdb_id=?", (str(tmdb_id),))
    conn.commit()
    conn.close()

def drop_show(tmdb_id, title='', media_type='show'):
    """Drop pe Simkl (status 'dropped' in watchlist + local)."""
    if not tmdb_id:
        return False
    try:
        api = SIMKLAPI()
        if api.watchlist_add(media_type, tmdb_id, status='dropped'):
            drop_add_local(tmdb_id, title)
            return True
    except Exception as e:
        xbmc.log(f'[SIMKL] drop_show error: {e}', xbmc.LOGERROR)
    return False

def restore_show(tmdb_id, media_type='show'):
    """Restore (scoate din status 'dropped')."""
    if not tmdb_id:
        return False
    try:
        api = SIMKLAPI()
        if api.watchlist_remove(media_type, tmdb_id, status='dropped'):
            drop_remove_local(tmdb_id)
            return True
    except Exception as e:
        xbmc.log(f'[SIMKL] restore_show error: {e}', xbmc.LOGERROR)
    return False

def get_dropped_local():
    _ensure_db()
    if not os.path.exists(DB_PATH):
        return []
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT tmdb_id, title, dropped_at FROM simkl_dropped ORDER BY dropped_at DESC")
        rows = c.fetchall()
    except:
        rows = []
    conn.close()
    return [{'tmdb_id': r[0], 'title': r[1] or 'Unknown Show', 'dropped_at': r[2]} for r in rows]

# ------------------------------------------------------------------
# COUNTS
# ------------------------------------------------------------------
def get_watched_movie_count():
    _ensure_db()
    if not os.path.exists(DB_PATH):
        return 0
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT COUNT(*) FROM simkl_watched_movies")
        count = c.fetchone()[0]
    except:
        count = 0
    conn.close()
    return count

def get_watched_episode_count():
    _ensure_db()
    if not os.path.exists(DB_PATH):
        return 0
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT COUNT(*) FROM simkl_watched_episodes")
        count = c.fetchone()[0]
    except:
        count = 0
    conn.close()
    return count

# ------------------------------------------------------------------
# DROPPED IMPORT (paritate cu mdblist_sync.import_dropped_from_trakt)
# ------------------------------------------------------------------
def import_dropped_from_trakt(silent=False):
    """Importa (copy) dropped-urile din Trakt (trakt_hidden_shows) in Simkl.
    Doar seriale. Returneaza (imported, skipped)."""
    try:
        init_database()
    except Exception as e:
        xbmc.log(f'[SIMKL] import init_database error: {e}', xbmc.LOGERROR)
    try:
        from resources.lib import trakt_sync
        if not os.path.exists(trakt_sync.DB_PATH):
            if not silent:
                xbmcgui.Dialog().notification('[B][COLOR mediumpurple]Simkl[/COLOR][/B]', 'Connect Trakt first (no Trakt sync data found)', SIMKL_ICON, 3000, False)
            return 0, 0
        tconn = trakt_sync.get_connection()
        try:
            trows = tconn.execute("SELECT tmdb_id FROM trakt_hidden_shows").fetchall()
        finally:
            tconn.close()
        trakt_ids = [str(r[0]) for r in trows if r[0]]
    except Exception as e:
        xbmc.log(f'[SIMKL] import_dropped_from_trakt read error: {e}', xbmc.LOGERROR)
        if not silent:
            xbmcgui.Dialog().notification('[B][COLOR mediumpurple]Simkl[/COLOR][/B]', 'Could not read Trakt dropped list', SIMKL_ICON, 3000, False)
        return 0, 0

    if not trakt_ids:
        if not silent:
            xbmcgui.Dialog().notification('[B][COLOR mediumpurple]Simkl[/COLOR][/B]', 'No dropped shows found on Trakt', SIMKL_ICON, 3000, False)
        return 0, 0

    existing = set()
    if os.path.exists(DB_PATH):
        conn = get_connection()
        try:
            for r in conn.execute("SELECT tmdb_id FROM simkl_dropped").fetchall():
                existing.add(str(r[0]))
        finally:
            conn.close()

    pending = [tid for tid in trakt_ids if tid not in existing]

    if not pending:
        if not silent:
            xbmcgui.Dialog().notification('[B][COLOR mediumpurple]Simkl[/COLOR][/B]', 'Nothing to import - all dropped shows already on Simkl', SIMKL_ICON, 3000, False)
        return 0, len(trakt_ids)

    p_dialog = None
    if not silent:
        p_dialog = xbmcgui.DialogProgressBG()
        p_dialog.create('[B][COLOR mediumpurple]Simkl Import[/COLOR][/B]', f'Importing dropped: 0 / {len(pending)}')

    imported = 0
    try:
        api = SIMKLAPI()
        from resources.lib.history_import import _chunks
        total = len(pending)
        done = 0
        for chunk in _chunks(pending, 150):
            if _abort_requested():
                break
            if p_dialog:
                p_dialog.update(int(done * 100 / max(total, 1)),
                                '[B][COLOR mediumpurple]Simkl Import[/COLOR][/B]',
                                f'Importing dropped: {done} / {total}')
            try:
                res = api.watchlist_add_bulk([], [int(t) for t in chunk], status='dropped')
                if res is not None:
                    added_items = (res or {}).get('added') or {}
                    imported += len(added_items.get('shows') or []) + len(added_items.get('anime') or [])
                    for tid in chunk:
                        drop_add_local(tid)
            except Exception as e:
                xbmc.log(f'[SIMKL] import dropped chunk error: {e}', xbmc.LOGERROR)
            done += len(chunk)
            if _abort_requested():
                break
    finally:
        if p_dialog:
            p_dialog.close()

    # Re-pull de pe server: umple titlurile reale (importul salveaza doar tmdb_id)
    if imported > 0 and not _abort_requested():
        try:
            _sync_dropped(api)
        except Exception as e:
            xbmc.log(f'[SIMKL] import dropped re-pull error: {e}', xbmc.LOGERROR)

    skipped = len(pending) - imported
    if not silent:
        xbmcgui.Dialog().notification('[B][COLOR mediumpurple]Simkl[/COLOR][/B]',
                                      f'Dropped imported: [B][COLOR FF6AFB92]{imported}[/COLOR][/B], failed: {skipped}', SIMKL_ICON, 4000, False)
    return imported, skipped


# ------------------------------------------------------------------
# RATINGS IMPORT (paritate cu import_dropped_from_*)
# ------------------------------------------------------------------
def _parse_ratings_items(items):
    """Normalizeaza items de ratings din Trakt (/sync/ratings) sau MDBList
    (get_sync_ratings) la lista uniforma de dicturi:
    {tmdb_id, media_type: movie|show|episode, season, episode, rating, rated_at}
    Returneaza (movies, shows, episodes) ca liste de dicturi."""
    movies, shows, episodes = [], [], []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        rating = item.get('rating') or 0
        rated_at = item.get('rated_at') or ''
        if 'episode' in item and isinstance(item.get('episode'), dict):
            ep_obj = item['episode']
            show_obj = item.get('show') or (ep_obj.get('show') if isinstance(ep_obj, dict) else None) or {}
            ids = (show_obj.get('ids') or {}) if isinstance(show_obj, dict) else {}
            tmdb_id = str(ids.get('tmdb', '') or show_obj.get('tmdb_id', '') or '')
            season = int(ep_obj.get('season') or item.get('season') or 0)
            episode = int(ep_obj.get('number') or ep_obj.get('episode') or item.get('episode') or 0)
            if tmdb_id and tmdb_id != 'None':
                episodes.append({'tmdb_id': tmdb_id, 'media_type': 'episode', 'season': season,
                                 'episode': episode, 'rating': rating, 'rated_at': rated_at})
        elif 'movie' in item and isinstance(item.get('movie'), dict):
            inner = item['movie']
            ids = (inner.get('ids') or {}) if isinstance(inner, dict) else {}
            tmdb_id = str(ids.get('tmdb', '') or inner.get('tmdb_id', '') or '')
            if tmdb_id and tmdb_id != 'None':
                movies.append({'tmdb_id': tmdb_id, 'media_type': 'movie', 'rating': rating, 'rated_at': rated_at})
        elif 'show' in item and isinstance(item.get('show'), dict):
            inner = item['show']
            ids = (inner.get('ids') or {}) if isinstance(inner, dict) else {}
            tmdb_id = str(ids.get('tmdb', '') or inner.get('tmdb_id', '') or '')
            if tmdb_id and tmdb_id != 'None':
                shows.append({'tmdb_id': tmdb_id, 'media_type': 'show', 'rating': rating, 'rated_at': rated_at})
    return movies, shows, episodes


def import_ratings_from_trakt(silent=False):
    """Importa (copy) rating-urile din Trakt (/sync/ratings) in Simkl.
    Filme + seriale + episoade. Returneaza (imported, skipped)."""
    try:
        init_database()
    except Exception as e:
        xbmc.log(f'[SIMKL] import init_database error: {e}', xbmc.LOGERROR)
    try:
        from resources.lib import trakt_api
        if not ADDON.getSetting('trakt_access_token'):
            if not silent:
                xbmcgui.Dialog().notification('[B][COLOR mediumpurple]Simkl[/COLOR][/B]', 'Connect Trakt first (no Trakt access token)', SIMKL_ICON, 3000, False)
            return 0, 0
        data = trakt_api._get_trakt_paginated_list('/sync/ratings', params={'extended': 'full'})
        if not data or not isinstance(data, list):
            if not silent:
                xbmcgui.Dialog().notification('[B][COLOR mediumpurple]Simkl[/COLOR][/B]', 'Could not fetch Trakt ratings', SIMKL_ICON, 3000, False)
            return 0, 0
        movies, shows, episodes = _parse_ratings_items(data)
    except Exception as e:
        xbmc.log(f'[SIMKL] import_ratings_from_trakt fetch error: {e}', xbmc.LOGERROR)
        if not silent:
            xbmcgui.Dialog().notification('[B][COLOR mediumpurple]Simkl[/COLOR][/B]', 'Could not fetch Trakt ratings', SIMKL_ICON, 3000, False)
        return 0, 0

    return _push_ratings(movies, shows, episodes, 'Trakt', silent)


def import_ratings_from_mdblist(silent=False):
    """Importa (copy) rating-urile din MDBList (sync/ratings) in Simkl.
    Filme + seriale + episoade. Returneaza (imported, skipped)."""
    try:
        init_database()
    except Exception as e:
        xbmc.log(f'[SIMKL] import init_database error: {e}', xbmc.LOGERROR)
    try:
        from resources.lib import mdblist_api
        api = mdblist_api.MDBListAPI()
        if not api.is_authenticated():
            if not silent:
                xbmcgui.Dialog().notification('[B][COLOR mediumpurple]Simkl[/COLOR][/B]', 'Connect MDBList first (no MDBList auth)', SIMKL_ICON, 3000, False)
            return 0, 0
        movies, shows, episodes = [], [], []
        cursor = None
        while True:
            if _abort_requested():
                break
            data = api.get_sync_ratings(cursor=cursor, limit=1000)
            if not data:
                break
            m, s, e = _parse_ratings_items(
                (data.get('movies') or []) + (data.get('shows') or []) + (data.get('episodes') or []))
            movies += m
            shows += s
            episodes += e
            pagination = data.get('pagination', {})
            if not pagination.get('has_more'):
                break
            cursor = pagination.get('next_cursor')
    except Exception as e:
        xbmc.log(f'[SIMKL] import_ratings_from_mdblist fetch error: {e}', xbmc.LOGERROR)
        if not silent:
            xbmcgui.Dialog().notification('[B][COLOR mediumpurple]Simkl[/COLOR][/B]', 'Could not fetch MDBList ratings', SIMKL_ICON, 3000, False)
        return 0, 0

    return _push_ratings(movies, shows, episodes, 'MDBList', silent)


def _ratings_add_local(items):
    """Salveaza local itemele de ratings trimise (INSERT OR REPLACE).
    Folosit la import — episoadele NU sunt returnate de GET /sync/ratings,
    deci singura sursa de dedupe pentru ele e tabela locala."""
    if not items:
        return
    try:
        conn = get_connection()
        try:
            rows = [(it['tmdb_id'], it['media_type'], int(it.get('season') or 0), int(it.get('episode') or 0),
                     it.get('rating') or 0, it.get('rated_at') or '') for it in items]
            conn.executemany("INSERT OR REPLACE INTO simkl_ratings (tmdb_id, media_type, season, episode, rating, rated_at) VALUES (?,?,?,?,?,?)", rows)
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        xbmc.log(f'[SIMKL] _ratings_add_local error: {e}', xbmc.LOGERROR)


def _push_ratings(movies, shows, episodes, source_label, silent=False):
    """Dedupe pe simkl_ratings local + push prin add_ratings_bulk (chunk 150).
    Re-pull _sync_ratings la final. Returneaza (imported, skipped)."""
    total = len(movies) + len(shows) + len(episodes)
    if not total:
        if not silent:
            xbmcgui.Dialog().notification('[B][COLOR mediumpurple]Simkl[/COLOR][/B]', f'No ratings found on {source_label}', SIMKL_ICON, 3000, False)
        return 0, 0

    # Dedupe: cheie (tmdb_id, media_type, season, episode)
    existing = set()
    if os.path.exists(DB_PATH):
        conn = get_connection()
        try:
            for r in conn.execute("SELECT tmdb_id, media_type, season, episode FROM simkl_ratings").fetchall():
                existing.add((str(r[0]), r[1], int(r[2] or 0), int(r[3] or 0)))
        finally:
            conn.close()

    def _key(it):
        return (it['tmdb_id'], it['media_type'], int(it.get('season') or 0), int(it.get('episode') or 0))

    p_movies = [it for it in movies if _key(it) not in existing]
    p_shows = [it for it in shows if _key(it) not in existing]
    p_episodes = [it for it in episodes if _key(it) not in existing]
    pending = len(p_movies) + len(p_shows) + len(p_episodes)

    if not pending:
        if not silent:
            xbmcgui.Dialog().notification('[B][COLOR mediumpurple]Simkl[/COLOR][/B]', 'Nothing to import - all ratings already on Simkl', SIMKL_ICON, 3000, False)
        return 0, total

    p_dialog = None
    if not silent:
        p_dialog = xbmcgui.DialogProgressBG()
        p_dialog.create('[B][COLOR mediumpurple]Simkl Import[/COLOR][/B]', f'Importing ratings: 0 / {pending}')

    imported = 0
    try:
        api = SIMKLAPI()
        from resources.lib.history_import import _chunks
        all_pending = p_movies + p_shows + p_episodes
        done = 0
        for chunk in _chunks(all_pending, 150):
            if _abort_requested():
                break
            if p_dialog:
                p_dialog.update(int(done * 100 / max(pending, 1)),
                                '[B][COLOR mediumpurple]Simkl Import[/COLOR][/B]',
                                f'Importing ratings: {done} / {pending}')
            try:
                c_movies = [(it['tmdb_id'], it['rating'], it['rated_at']) for it in chunk if it['media_type'] == 'movie']
                c_shows = [(it['tmdb_id'], it['rating'], it['rated_at']) for it in chunk if it['media_type'] == 'show']
                c_eps = [(it['tmdb_id'], it['season'], it['episode'], it['rating'], it['rated_at'])
                         for it in chunk if it['media_type'] == 'episode']
                res = api.add_ratings_bulk(c_movies, c_shows, c_eps)
                if res is not None:
                    added_items = (res or {}).get('added') or {}
                    if isinstance(added_items, dict):
                        for k in ('movies', 'shows'):
                            v = added_items.get(k)
                            if isinstance(v, list):
                                imported += len(v)
                            elif isinstance(v, int):
                                imported += v
                    elif isinstance(added_items, int):
                        imported += added_items
                    # Salveaza local itemele trimise (episoadele NU sunt returnate de GET —
                    # singura sursa de dedupe pt ele). Movies/shows le re-pull-ul le
                    # suprascrie cu datele reale de pe server.
                    _ratings_add_local(chunk)
            except Exception as e:
                xbmc.log(f'[SIMKL] import ratings chunk error: {e}', xbmc.LOGERROR)
            done += len(chunk)
            if _abort_requested():
                break
    finally:
        if p_dialog:
            p_dialog.close()

    # Re-pull de pe server: umple titlurile/rated_at reale
    if imported > 0 and not _abort_requested():
        try:
            _sync_ratings(api)
            # Itemele trimise care NU apar in GET (Simkl accepta POST-ul 201
            # dar filmul/serialul poate lipsi din baza lor sau are alt tmdb_id —
            # verificat live: /movies/1024127 -> 200 []) trebuie pastrate local
            # ca baza de dedupe, altfel re-importul le retrimite la fiecare rulare.
            _ratings_add_local(all_pending)
        except Exception as e:
            xbmc.log(f'[SIMKL] import ratings re-pull error: {e}', xbmc.LOGERROR)

    skipped = pending - imported
    if not silent:
        xbmcgui.Dialog().notification('[B][COLOR mediumpurple]Simkl[/COLOR][/B]',
                                      f'Ratings imported: [B][COLOR FF6AFB92]{imported}[/COLOR][/B], failed: {skipped}', SIMKL_ICON, 4000, False)
    return imported, skipped


def import_dropped_from_mdblist(silent=False):
    """Importa (copy) dropped-urile din MDBList (mdblist_dropped) in Simkl.
    Doar seriale. Returneaza (imported, skipped)."""
    try:
        init_database()
    except Exception as e:
        xbmc.log(f'[SIMKL] import init_database error: {e}', xbmc.LOGERROR)
    try:
        from resources.lib import mdblist_sync
        if not os.path.exists(mdblist_sync.DB_PATH):
            if not silent:
                xbmcgui.Dialog().notification('[B][COLOR mediumpurple]Simkl[/COLOR][/B]', 'Sync MDBList first (no MDBList sync data found)', SIMKL_ICON, 3000, False)
            return 0, 0
        mconn = mdblist_sync.get_connection()
        try:
            mrows = mconn.execute("SELECT tmdb_id FROM mdblist_dropped").fetchall()
        finally:
            mconn.close()
        mdblist_ids = [str(r[0]) for r in mrows if r[0]]
    except Exception as e:
        xbmc.log(f'[SIMKL] import_dropped_from_mdblist read error: {e}', xbmc.LOGERROR)
        if not silent:
            xbmcgui.Dialog().notification('[B][COLOR mediumpurple]Simkl[/COLOR][/B]', 'Could not read MDBList dropped list', SIMKL_ICON, 3000, False)
        return 0, 0

    if not mdblist_ids:
        if not silent:
            xbmcgui.Dialog().notification('[B][COLOR mediumpurple]Simkl[/COLOR][/B]', 'No dropped shows found on MDBList', SIMKL_ICON, 3000, False)
        return 0, 0

    existing = set()
    if os.path.exists(DB_PATH):
        conn = get_connection()
        try:
            for r in conn.execute("SELECT tmdb_id FROM simkl_dropped").fetchall():
                existing.add(str(r[0]))
        finally:
            conn.close()

    pending = [tid for tid in mdblist_ids if tid not in existing]

    if not pending:
        if not silent:
            xbmcgui.Dialog().notification('[B][COLOR mediumpurple]Simkl[/COLOR][/B]', 'Nothing to import - all dropped shows already on Simkl', SIMKL_ICON, 3000, False)
        return 0, len(mdblist_ids)

    p_dialog = None
    if not silent:
        p_dialog = xbmcgui.DialogProgressBG()
        p_dialog.create('[B][COLOR mediumpurple]Simkl Import[/COLOR][/B]', f'Importing dropped: 0 / {len(pending)}')

    imported = 0
    try:
        api = SIMKLAPI()
        from resources.lib.history_import import _chunks
        total = len(pending)
        done = 0
        for chunk in _chunks(pending, 150):
            if _abort_requested():
                break
            if p_dialog:
                p_dialog.update(int(done * 100 / max(total, 1)),
                                '[B][COLOR mediumpurple]Simkl Import[/COLOR][/B]',
                                f'Importing dropped: {done} / {total}')
            try:
                res = api.watchlist_add_bulk([], [int(t) for t in chunk], status='dropped')
                if res is not None:
                    added_items = (res or {}).get('added') or {}
                    imported += len(added_items.get('shows') or []) + len(added_items.get('anime') or [])
                    for tid in chunk:
                        drop_add_local(tid)
            except Exception as e:
                xbmc.log(f'[SIMKL] import dropped chunk error: {e}', xbmc.LOGERROR)
            done += len(chunk)
            if _abort_requested():
                break
    finally:
        if p_dialog:
            p_dialog.close()

    # Re-pull de pe server: umple titlurile reale (importul salveaza doar tmdb_id)
    if imported > 0 and not _abort_requested():
        try:
            _sync_dropped(api)
        except Exception as e:
            xbmc.log(f'[SIMKL] import dropped re-pull error: {e}', xbmc.LOGERROR)

    skipped = len(pending) - imported
    if not silent:
        xbmcgui.Dialog().notification('[B][COLOR mediumpurple]Simkl[/COLOR][/B]',
                                      f'Dropped imported: [B][COLOR FF6AFB92]{imported}[/COLOR][/B], failed: {skipped}', SIMKL_ICON, 4000, False)
    return imported, skipped
