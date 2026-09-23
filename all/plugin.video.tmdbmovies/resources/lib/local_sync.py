# -*- coding: utf-8 -*-
"""
Local Sync (provider "Kodi (Local)") — SQLite local database pentru watched
indicators, modelat dupa mdblist_sync.py dar FARA server: toate citirile
runtime vin din local_sync.db, niciodata direct din libraria Kodi (MyVideos.db).

Biblioteca Kodi intervine doar in doua locuri, prin local_library.py:
- write-through la mark/unwatch (playCount in MyVideos.db)
- reverse-import la Library Sync (playcount -> local_watched_*)

Progresul de redare NU se dubleaza: player.py scrie deja in tabela partajata
'playback_progress' (trakt_sync.db), deci In Progress porneste de acolo.
"""

import os
import datetime
import threading
import sqlite3
import xbmc
import xbmcgui

from resources.lib.config import ADDON, ADDON_DATA_DIR, ADDON_PATH, IMG_BASE, BACKDROP_BASE, provider_title, provider_icon

DB_PATH = os.path.join(ADDON_DATA_DIR, 'local_sync.db')
LOCAL_ICON = provider_icon('local') or os.path.join(ADDON_PATH, 'resources', 'media', 'tmdb.png')


def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA busy_timeout=15000")
    conn.row_factory = sqlite3.Row
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
            xbmc.log(f'[LOCAL] commit retry failed: {_e}', xbmc.LOGERROR)
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
    c.execute('''CREATE TABLE IF NOT EXISTS local_watched_movies
                 (tmdb_id TEXT PRIMARY KEY, title TEXT, year TEXT, last_watched_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS local_watched_episodes
                 (tmdb_id TEXT, season INTEGER, episode INTEGER, title TEXT, last_watched_at TEXT,
                  UNIQUE(tmdb_id, season, episode))''')
    c.execute('''CREATE TABLE IF NOT EXISTS local_fully_watched_shows
                 (tmdb_id TEXT PRIMARY KEY, total_episodes INTEGER, last_watched_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS local_next_episodes
                 (tmdb_id TEXT PRIMARY KEY, show_title TEXT, season INTEGER, episode INTEGER,
                  ep_title TEXT, air_date TEXT, watched_count INTEGER DEFAULT 0,
                  total_count INTEGER DEFAULT 0, last_watched_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS local_sync_meta (key TEXT PRIMARY KEY, value TEXT)''')
    conn.commit()
    conn.close()


def get_sync_meta(key, default=''):
    try:
        _ensure_db()
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT value FROM local_sync_meta WHERE key=?", (key,))
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
        _db_exec_retry(c, "INSERT OR REPLACE INTO local_sync_meta (key, value) VALUES (?,?)", (key, str(value)))
        _db_commit_retry(conn)
        conn.close()
    except:
        pass


# ------------------------------------------------------------------
# READERS
# ------------------------------------------------------------------
def is_movie_watched(tmdb_id):
    if not os.path.exists(DB_PATH):
        return False
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT 1 FROM local_watched_movies WHERE tmdb_id=?", (str(tmdb_id),))
    found = c.fetchone() is not None
    conn.close()
    return found


def is_episode_watched(tmdb_id, season, episode):
    if not os.path.exists(DB_PATH):
        return False
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT 1 FROM local_watched_episodes WHERE tmdb_id=? AND season=? AND episode=?",
              (str(tmdb_id), int(season), int(episode)))
    found = c.fetchone() is not None
    conn.close()
    return found


def get_watched_episodes_count(tmdb_id, season=None):
    if not os.path.exists(DB_PATH):
        return 0
    conn = get_connection()
    c = conn.cursor()
    if season is not None:
        c.execute("SELECT COUNT(*) FROM local_watched_episodes WHERE tmdb_id=? AND season=?",
                  (str(tmdb_id), int(season)))
    else:
        c.execute("SELECT COUNT(*) FROM local_watched_episodes WHERE tmdb_id=?", (str(tmdb_id),))
    count = c.fetchone()[0]
    conn.close()
    return count


def get_watched_season_episodes_count(tmdb_id, season):
    return get_watched_episodes_count(tmdb_id, season)


def is_fully_watched_show(tmdb_id):
    if not os.path.exists(DB_PATH):
        return False
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT 1 FROM local_fully_watched_shows WHERE tmdb_id=?", (str(tmdb_id),))
        found = c.fetchone() is not None
    except:
        found = False
    conn.close()
    return found


def get_watched_counts_map(tmdb_ids):
    """Bulk watched-episode counts (o singura conexiune) — paritate cu celelalte module.

    None = citirea a esuat -> apelantul cade pe numararea per serial."""
    out = {}
    try:
        if not os.path.exists(DB_PATH):
            return out
        ids = tuple({str(t) for t in (tmdb_ids or []) if str(t)})
        if not ids:
            return out
        marks = ','.join(['?'] * len(ids))
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT tmdb_id, COUNT(*) FROM local_watched_episodes "
                  "WHERE tmdb_id IN (%s) GROUP BY tmdb_id" % marks, ids)
        for r in c.fetchall():
            try:
                out[str(r[0])] = int(r[1] or 0)
            except:
                continue
        try: conn.close()
        except: pass
        return out
    except:
        return None


def get_next_episodes_from_db():
    try:
        _ensure_db()
        conn = get_connection()
        c = conn.cursor()
        c.execute("""SELECT tmdb_id, show_title, season, episode, ep_title, air_date, watched_count, total_count, last_watched_at
                     FROM local_next_episodes
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
                     FROM local_next_episodes
                     WHERE watched_count > 0 AND (total_count = 0 OR watched_count < total_count)
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


def get_in_progress_movies_from_db():
    """Filme in curs: din tabela partajata playback_progress (media_type='movie')."""
    try:
        from resources.lib import trakt_sync
        return trakt_sync.get_in_progress_movies_from_db()
    except:
        return []


def get_in_progress_episodes_from_db():
    """Episoade in curs: din tabela partajata playback_progress (media_type='episode')."""
    try:
        from resources.lib import trakt_sync
        return trakt_sync.get_in_progress_episodes_from_db()
    except:
        return []


# ------------------------------------------------------------------
# MARK WATCHED / UNWATCHED
# ------------------------------------------------------------------
def mark_as_watched_internal(tmdb_id, content_type, season=None, episode=None, notify=True, sync_local=True, refresh_ui=True, skip_library_hack=False):
    """Scrie watched in local_sync.db + write-through playCount in MyVideos.db.

    sync_local e pastrat in semnatura pentru paritate cu ceilalti provideri
    (dispatcher-ul il trimite); la local nu exista server, deci e no-op.
    """
    from resources.lib import tmdb_api

    tid = str(tmdb_id)
    conn = get_connection()
    c = conn.cursor()
    now = datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S.000Z')

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
            _db_exec_retry(c, "INSERT OR REPLACE INTO local_watched_movies VALUES (?,?,?,?)",
                           (tid, title_val, str(now)[:4], now))
        elif season is not None and episode is not None:
            _db_exec_retry(c, "INSERT OR REPLACE INTO local_watched_episodes VALUES (?,?,?,?,?)",
                           (tid, int(season), int(episode), title_val.split(' - ')[0] if title_val else 'Unknown Show', now))
        elif season is not None:
            show_data = tmdb_api.get_tmdb_item_details(tid, 'tv')
            db_show_title = title_val.split(' - ')[0] if title_val else 'Unknown Show'
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
                    c.executemany("INSERT OR REPLACE INTO local_watched_episodes VALUES (?,?,?,?,?)", rows)
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
                    c.executemany("INSERT OR REPLACE INTO local_watched_episodes VALUES (?,?,?,?,?)", rows)
                c.execute("INSERT OR REPLACE INTO local_fully_watched_shows (tmdb_id, total_episodes, last_watched_at) VALUES (?,?,?)",
                          (tid, total_eps, now))
        conn.commit()
    except Exception as e:
        xbmc.log(f'[LOCAL] mark watched DB error: {e}', xbmc.LOGERROR)
    finally:
        conn.close()

    # Curatam si tabela partajata de resume (cerculetul dispare instant)
    try:
        from resources.lib import trakt_sync as _ts
        _ts.remove_local_progress(tid, content_type, season, episode)
    except:
        pass

    # WRITE-THROUGH: bifa apare instant si in biblioteca Kodi nativa
    try:
        from resources.lib import local_library
        local_library.set_playcount(tid, content_type, season, episode, 1)
    except Exception as e:
        xbmc.log(f'[LOCAL] write-through watched error: {e}', xbmc.LOGWARNING)

    if notify:
        msg = f'[B][COLOR yellow]{title_val}[/COLOR][/B] marked watched on ' + provider_title('local')
        xbmcgui.Dialog().notification(provider_title('local'), msg, LOCAL_ICON, 3000, False)

    if content_type in ('tv', 'show', 'season', 'episode') or season is not None:
        try:
            threading.Thread(target=refresh_next_episode_local, args=(tmdb_id,), daemon=True).start()
        except:
            pass

    # Doar listele (metadatele serialelor rămân valide dupa un mark watched).
    try:
        from resources.lib.cache import clear_list_fast_cache
        clear_list_fast_cache()
    except:
        pass

    if refresh_ui:
        xbmc.executebuiltin('Container.Refresh')


def mark_as_unwatched_internal(tmdb_id, content_type, season=None, episode=None, notify=True, sync_local=True, refresh_ui=True):
    """Sterge watched din local_sync.db + playCount=0 write-through in MyVideos.db
    (lastPlayed ramane PARSAT, paritate cu unmark-ul nativ Kodi)."""
    tid = str(tmdb_id)
    conn = get_connection()
    c = conn.cursor()

    title_display = 'Element'
    try:
        if content_type == 'movie':
            c.execute("SELECT title FROM local_watched_movies WHERE tmdb_id=?", (tid,))
            r = c.fetchone()
            if r:
                title_display = r[0]
        elif season is not None and episode is not None:
            c.execute("SELECT title FROM local_watched_episodes WHERE tmdb_id=? LIMIT 1", (tid,))
            r = c.fetchone()
            if r:
                base_title = r[0].split(' - S')[0]
                title_display = f'{base_title} - S{int(season):02d}E{int(episode):02d}'
            else:
                title_display = f'S{season}E{episode}'
        elif season is not None:
            c.execute("SELECT title FROM local_watched_episodes WHERE tmdb_id=? LIMIT 1", (tid,))
            r = c.fetchone()
            if r:
                base_title = r[0].split(' - S')[0]
                title_display = f'{base_title} - Sezonul {season}'
            else:
                from resources.lib import tmdb_api
                show_details = tmdb_api.get_tmdb_item_details(tid, 'tv') or {}
                title_display = f"{show_details.get('name', 'Serial')} - Sezonul {season}"
        elif content_type in ('tv', 'show'):
            c.execute("SELECT title FROM local_watched_episodes WHERE tmdb_id=? LIMIT 1", (tid,))
            r = c.fetchone()
            if r:
                title_display = r[0].split(' - S')[0]
            else:
                title_display = 'Serial'
    except:
        pass

    try:
        if content_type == 'movie':
            c.execute("DELETE FROM local_watched_movies WHERE tmdb_id=?", (tid,))
        elif season is not None and episode is not None:
            c.execute("DELETE FROM local_watched_episodes WHERE tmdb_id=? AND season=? AND episode=?",
                      (tid, int(season), int(episode)))
        elif season is not None:
            c.execute("DELETE FROM local_watched_episodes WHERE tmdb_id=? AND season=?", (tid, int(season)))
        elif content_type in ('tv', 'show'):
            c.execute("DELETE FROM local_watched_episodes WHERE tmdb_id=?", (tid,))
            c.execute("DELETE FROM local_fully_watched_shows WHERE tmdb_id=?", (tid,))
        conn.commit()
    except Exception as e:
        xbmc.log(f'[LOCAL] mark unwatched DB error: {e}', xbmc.LOGERROR)
    finally:
        conn.close()

    # Curatam si tabela partajata de resume
    try:
        from resources.lib import trakt_sync as _ts
        _ts.remove_local_progress(tid, content_type, season, episode)
    except:
        pass

    # WRITE-THROUGH invers: bifa dispare instant si din biblioteca Kodi nativa.
    # lastPlayed ramane neatinss (paritate cu nativul Kodi, care pastreaza lastPlayed la unmark).
    try:
        from resources.lib import local_library
        local_library.set_playcount(tid, content_type, season, episode, 0)
    except Exception as e:
        xbmc.log(f'[LOCAL] write-through unwatched error: {e}', xbmc.LOGWARNING)

    msg = f'[B][COLOR yellow]{title_display}[/COLOR][/B] marked unwatched on ' + provider_title('local')
    if notify:
        xbmcgui.Dialog().notification(provider_title('local'), msg, LOCAL_ICON, 3000, False)

    if content_type in ('tv', 'show', 'season', 'episode') or season is not None:
        try:
            threading.Thread(target=refresh_next_episode_local, args=(tmdb_id,), daemon=True).start()
        except:
            pass

    try:
        from resources.lib.cache import clear_list_fast_cache
        clear_list_fast_cache()
    except:
        pass

    if refresh_ui:
        xbmc.executebuiltin('Container.Refresh')


# ------------------------------------------------------------------
# UP NEXT RECOMPUTE (paritate cu refresh_next_episode_mdblist)
# ------------------------------------------------------------------
def refresh_next_episode_local(tmdb_id, ignore_hidden=False, refresh_ui=True):
    """Recalculeaza episodul Up Next local dupa mark watched/unwatched.

    100% local + cache TMDb (get_smart_season_details), ZERO retea sync.
    refresh_ui=False in rebuild-urile batch (altfel fiecare serial da
    Container.Refresh -> flicker continuu pe durata sync-ului).
    """
    from resources.lib import tmdb_api

    def _trigger_ui_refresh():
        try:
            from resources.lib.cache import clear_list_fast_cache
            clear_list_fast_cache()
        except:
            pass
        try:
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
        show_details = tmdb_api.get_tmdb_item_details(tmdb_id, 'tv')
        if not show_details:
            return
        show_title = show_details.get('name', 'Unknown Show')

        if not os.path.exists(DB_PATH):
            return
        conn = get_connection()
        c = conn.cursor()

        c.execute("SELECT season, episode FROM local_watched_episodes WHERE tmdb_id=?", (tmdb_id,))
        watched_eps = set((r[0], r[1]) for r in c.fetchall())
        c.execute("SELECT season, episode FROM local_watched_episodes WHERE tmdb_id=? ORDER BY last_watched_at DESC LIMIT 1", (tmdb_id,))
        last_row = c.fetchone()

        # Fara episoade vizionate: iese din Up Next (localul n-are watchlist "neinceput")
        if not watched_eps:
            _db_exec_retry(conn, "DELETE FROM local_next_episodes WHERE tmdb_id=?", (tmdb_id,))
            _db_commit_retry(conn)
            try: conn.close()
            except: pass
            if refresh_ui:
                _trigger_ui_refresh()
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
                _db_exec_retry(conn, "DELETE FROM local_next_episodes WHERE tmdb_id=?", (tmdb_id,))
                _db_commit_retry(conn)
            except:
                pass
            try: conn.close()
            except: pass
            if refresh_ui:
                _trigger_ui_refresh()
            return

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

        now_str = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
        _db_exec_retry(c,
            "INSERT OR REPLACE INTO local_next_episodes "
            "(tmdb_id, show_title, season, episode, ep_title, air_date, watched_count, total_count, last_watched_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (tmdb_id, show_title, next_ep['season'], next_ep['number'],
             ep_title, air_date, len(watched_eps),
             show_details.get('number_of_episodes', 0), now_str)
        )
        _db_commit_retry(conn)
        try: conn.close()
        except: pass
        if refresh_ui:
            _trigger_ui_refresh()
    except Exception as e:
        xbmc.log(f'[LOCAL] refresh_next_episode_local error: {e}', xbmc.LOGERROR)


# ------------------------------------------------------------------
# SYNC FULL LIBRARY (faza locala: reverse-import + rebuild Up Next)
# ------------------------------------------------------------------
def sync_full_library(silent=False, force=False, rebuild_upnext=True):
    """Faza locala a sync-ului: reverse-import din biblioteca Kodi (playcount ->
    local_watched_*) + import progres partajat + rebuild local_next_episodes.

    rebuild_upnext=False sare rebuild-ul (cost TMDb per serial) — folosit de
    dispatcher cand localul nu e providerul activ (doar reverse-importul ieftin).
    """
    init_database()
    try:
        from resources.lib import local_library
        n = local_library.import_kodi_watchstate()
        if not silent:
            xbmc.log(f'[LOCAL] reverse-import: {n} items updated from Kodi library', xbmc.LOGINFO)
    except Exception as e:
        xbmc.log(f'[LOCAL] reverse-import error: {e}', xbmc.LOGERROR)

    if not rebuild_upnext:
        set_sync_meta('last_sync', datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z'))
        return

    # Rebuild Up Next pentru toate serialele cu episoade vazute
    try:
        from resources.lib import tmdb_api
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT DISTINCT tmdb_id FROM local_watched_episodes")
        tids = [str(r[0]) for r in c.fetchall()]
        conn.close()
        for tid in tids:
            try:
                refresh_next_episode_local(tid, refresh_ui=False)
            except:
                continue
        set_sync_meta('last_sync', datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z'))
        try:
            from resources.lib.cache import clear_list_fast_cache
            clear_list_fast_cache()
        except:
            pass
        if not silent:
            xbmcgui.Dialog().notification(provider_title('local'),
                                          f'Local sync done ({len(tids)} shows)',
                                          LOCAL_ICON, 3000, False)
    except Exception as e:
        xbmc.log(f'[LOCAL] rebuild upnext error: {e}', xbmc.LOGERROR)
