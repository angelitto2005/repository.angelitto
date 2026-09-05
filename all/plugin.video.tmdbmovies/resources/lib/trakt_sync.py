import sqlite3
import os
import requests
import xbmc
import xbmcgui
import xbmcvfs
import datetime
import json
import time
import zlib
from resources.lib.config import ADDON, API_KEY, BASE_URL, LANG, TMDB_V4_TOKEN_FILE, IMG_BASE
from resources.lib.utils import log, read_json, write_json
from concurrent.futures import ThreadPoolExecutor, as_completed

PROFILE_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
DB_PATH = os.path.join(PROFILE_PATH, 'trakt_sync.db')
LAST_SYNC_FILE = os.path.join(PROFILE_PATH, 'last_sync.json')


# =============================================================================
# DATABASE HELPERS
# =============================================================================

def _initialize_tables_on_connection(conn):
    """Creeaza si actualizeaza structura tabelelor pe conexiunea furnizata."""
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS trakt_watched_movies (tmdb_id TEXT PRIMARY KEY, title TEXT, year TEXT, last_watched_at TEXT, poster TEXT, backdrop TEXT, overview TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS trakt_watched_episodes (tmdb_id TEXT, season INTEGER, episode INTEGER, title TEXT, last_watched_at TEXT, UNIQUE(tmdb_id, season, episode))''')
    c.execute('''CREATE TABLE IF NOT EXISTS trakt_lists (list_type TEXT, media_type TEXT, tmdb_id TEXT, title TEXT, year TEXT, added_at TEXT, poster TEXT, backdrop TEXT, overview TEXT, UNIQUE(list_type, media_type, tmdb_id))''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS user_lists (trakt_id TEXT PRIMARY KEY, name TEXT, slug TEXT, item_count INTEGER, sort_by TEXT, sort_how TEXT, description TEXT, updated_at TEXT, poster TEXT, backdrop TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS user_list_items (list_slug TEXT, media_type TEXT, tmdb_id TEXT, title TEXT, year TEXT, added_at TEXT, poster TEXT, backdrop TEXT, overview TEXT, UNIQUE(list_slug, media_type, tmdb_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS discovery_cache (list_type TEXT, media_type TEXT, tmdb_id TEXT, title TEXT, year TEXT, poster TEXT, backdrop TEXT, overview TEXT, rank INTEGER, UNIQUE(list_type, media_type, tmdb_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS tmdb_discovery (action TEXT, page INTEGER, tmdb_id TEXT, title TEXT, year TEXT, poster TEXT, overview TEXT, rank INTEGER, UNIQUE(action, page, tmdb_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS playback_progress (tmdb_id TEXT, media_type TEXT, season INTEGER, episode INTEGER, progress FLOAT, paused_at TEXT, title TEXT, year TEXT, poster TEXT, UNIQUE(tmdb_id, media_type, season, episode))''')
    c.execute('''CREATE TABLE IF NOT EXISTS tv_meta (tmdb_id TEXT PRIMARY KEY, total_episodes INTEGER, poster TEXT, backdrop TEXT, overview TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS tmdb_custom_lists (list_id TEXT PRIMARY KEY, name TEXT, item_count INTEGER, poster TEXT, backdrop TEXT, description TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS tmdb_custom_list_items 
                 (list_id TEXT, tmdb_id TEXT, media_type TEXT, title TEXT, year TEXT, 
                  poster TEXT, overview TEXT, sort_index INTEGER, UNIQUE(list_id, tmdb_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS tmdb_account_lists (list_type TEXT, media_type TEXT, tmdb_id TEXT, title TEXT, year TEXT, poster TEXT, added_at TEXT, overview TEXT, release_date TEXT, first_air_date TEXT, UNIQUE(list_type, media_type, tmdb_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS tmdb_recommendations (media_type TEXT, tmdb_id TEXT, title TEXT, year TEXT, poster TEXT, overview TEXT, UNIQUE(media_type, tmdb_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS meta_cache_items (tmdb_id TEXT, media_type TEXT, data TEXT, expires INTEGER, UNIQUE(tmdb_id, media_type))''')
    c.execute('''CREATE TABLE IF NOT EXISTS meta_cache_seasons (tmdb_id TEXT, season_num INTEGER, data TEXT, expires INTEGER, UNIQUE(tmdb_id, season_num))''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS trakt_next_episodes 
                 (tmdb_id TEXT PRIMARY KEY, show_title TEXT, season INTEGER, episode INTEGER, 
                  ep_title TEXT, overview TEXT, last_watched_at TEXT, poster TEXT, air_date TEXT, watched_count INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS tmdb_next_episodes 
                 (tmdb_id TEXT PRIMARY KEY, show_title TEXT, season INTEGER, episode INTEGER, 
                  ep_title TEXT, overview TEXT, last_watched_at TEXT, poster TEXT, air_date TEXT, 
                  watched_count INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS trakt_hidden_shows (tmdb_id TEXT PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS trakt_favorites 
                 (media_type TEXT, tmdb_id TEXT, title TEXT, year TEXT, poster TEXT, overview TEXT, rank INTEGER, UNIQUE(media_type, tmdb_id))''')
    
    # Migrari automate on-the-fly
    try: c.execute("ALTER TABLE user_lists ADD COLUMN updated_at TEXT")
    except: pass
    try: c.execute("ALTER TABLE user_lists ADD COLUMN description TEXT")
    except: pass
    try: c.execute("ALTER TABLE tmdb_account_lists ADD COLUMN overview TEXT")
    except: pass
    try: c.execute("ALTER TABLE tv_meta ADD COLUMN overview TEXT")
    except: pass
    try: c.execute("ALTER TABLE trakt_watched_movies ADD COLUMN poster TEXT")
    except: pass
    try: c.execute("ALTER TABLE tmdb_custom_lists ADD COLUMN description TEXT")
    except: pass
    try: c.execute("ALTER TABLE user_lists ADD COLUMN poster TEXT")
    except: pass
    try: c.execute("ALTER TABLE user_lists ADD COLUMN backdrop TEXT")
    except: pass
    try: c.execute("ALTER TABLE trakt_lists ADD COLUMN added_at TEXT")
    except: pass
    try: c.execute("ALTER TABLE trakt_lists ADD COLUMN poster TEXT")
    except: pass
    try: c.execute("ALTER TABLE trakt_lists ADD COLUMN backdrop TEXT")
    except: pass
    try: c.execute("ALTER TABLE trakt_lists ADD COLUMN overview TEXT")
    except: pass
    try: c.execute("ALTER TABLE tmdb_custom_list_items ADD COLUMN sort_index INTEGER")
    except: pass
    try: c.execute("ALTER TABLE tmdb_account_lists ADD COLUMN release_date TEXT")
    except: pass
    try: c.execute("ALTER TABLE tmdb_account_lists ADD COLUMN first_air_date TEXT")
    except: pass
    try: c.execute("ALTER TABLE trakt_next_episodes ADD COLUMN watched_count INTEGER DEFAULT 0")
    except: pass
    try: c.execute("UPDATE trakt_next_episodes SET watched_count=(SELECT COUNT(*) FROM trakt_watched_episodes WHERE trakt_watched_episodes.tmdb_id=trakt_next_episodes.tmdb_id) WHERE watched_count IS NULL OR watched_count=0")
    except: pass

    conn.commit()


_db_initialized = False  # Flag global pentru optimizare

def get_connection():
    global _db_initialized
    if not os.path.exists(PROFILE_PATH):
        try: os.makedirs(PROFILE_PATH)
        except: pass
    
    # --- PROTECTIE DIMENSIUNE ---
    if os.path.exists(DB_PATH):
        try:
            size_mb = os.path.getsize(DB_PATH) / (1024 * 1024)
            if size_mb > 50: # Limita 50MB
                log(f"[DB-PROTECT] trakt_sync.db is {size_mb:.2f}MB. AUTO RESET!", xbmc.LOGWARNING)
                try: xbmcvfs.delete(DB_PATH)
                except:
                    try: os.remove(DB_PATH)
                    except: pass
                # Notificare discreta
                try:
                    xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]", "Cache Reset (Size Limit)", os.path.join(ADDON.getAddonInfo('path'), 'icon.png'))
                except: pass
        except: pass
    # -----------------------------

    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA mmap_size=268435456")
    conn.execute("PRAGMA busy_timeout=15000")
    
    if not _db_initialized:
        try:
            # CRITIC: init-ul ruleaza intotdeauna (CREATE TABLE IF NOT EXISTS e idempotent).
            # Gate-ul vechi verifica doar meta_cache_items (cea mai veche tabela) - daca DB-ul
            # exista dintr-o versiune mai veche, tabelele adaugate ulterior (meta_cache_seasons,
            # playback_progress, tmdb_account_lists, tmdb_custom_lists, discovery_cache etc.)
            # nu mai erau create NICIODATA -> "no such table" la fiecare sync.
            _initialize_tables_on_connection(conn)
            _db_initialized = True
        except Exception as e:
            log(f"[DB] Error checking or creating tables: {e}", xbmc.LOGERROR)

    return conn


def init_database():
    # Initializarea se realizeaza acum automat in interiorul get_connection()
    conn = get_connection()
    conn.close()


_TRAKT_NEXT_COLS_10 = "(tmdb_id, show_title, season, episode, ep_title, overview, last_watched_at, poster, air_date, watched_count)"
_TRAKT_NEXT_COLS_9 = "(tmdb_id, show_title, season, episode, ep_title, overview, last_watched_at, poster, air_date)"
_TMDB_NEXT_COLS = "(tmdb_id, show_title, season, episode, ep_title, overview, last_watched_at, poster, air_date, watched_count)"


def _has_watched_count_col(c, table):
    try:
        c.execute("SELECT watched_count FROM %s LIMIT 1" % table)
        return True
    except:
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
            log(f"[DB] commit retry failed: {_e}", xbmc.LOGERROR)
            return False
    return False


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


def _insert_trakt_next_batch(c, rows):
    has_wc = _has_watched_count_col(c, 'trakt_next_episodes')
    if has_wc:
        fixed = []
        for r in rows:
            if len(r) == 9:
                fixed.append(tuple(list(r) + [1]))
            else:
                fixed.append(tuple(r[:10]))
        import time as _t
        for _a in range(20):
            try:
                c.executemany("INSERT OR REPLACE INTO trakt_next_episodes %s VALUES (?,?,?,?,?,?,?,?,?,?)" % _TRAKT_NEXT_COLS_10, fixed)
                return
            except Exception as _e:
                if 'database is locked' in str(_e) and _a < 19:
                    _t.sleep(0.4 + 0.15 * _a)
                    continue
                raise
    else:
        fixed = [tuple(r[:9]) for r in rows]
        c.executemany("INSERT OR REPLACE INTO trakt_next_episodes %s VALUES (?,?,?,?,?,?,?,?,?)" % _TRAKT_NEXT_COLS_9, fixed)


def _insert_trakt_next_one(c, row):
    has_wc = _has_watched_count_col(c, 'trakt_next_episodes')
    if has_wc:
        if len(row) == 9:
            row = tuple(list(row) + [1])
        _db_exec_retry(c, "INSERT OR REPLACE INTO trakt_next_episodes %s VALUES (?,?,?,?,?,?,?,?,?,?)" % _TRAKT_NEXT_COLS_10, tuple(row[:10]))
    else:
        _db_exec_retry(c, "INSERT OR REPLACE INTO trakt_next_episodes %s VALUES (?,?,?,?,?,?,?,?,?)" % _TRAKT_NEXT_COLS_9, tuple(row[:9]))


def is_table_empty(c, table):
    """Verifica daca un tabel SQL este gol intr-un mod robust."""
    try:
        c.execute(f"SELECT COUNT(*) FROM {table}")
        row = c.fetchone()
        return row[0] == 0 if row else True
    except:
        return True
    

# =============================================================================
# SMART SYNC ENGINE
# =============================================================================

def get_trakt_last_activities():
    from resources.lib import trakt_api
    return trakt_api.trakt_api_request("/sync/last_activities")

def get_local_last_sync():
    """Citeste timestamp-urile locale cu logging."""
    data = read_json(LAST_SYNC_FILE)
    
    # DEBUG: Afisam ce am citit
    if data:
        log(f"[TRAKT SYNC] Loaded local timestamps: {list(data.keys())}")
    else:
        log(f"[TRAKT SYNC] ⚠️ No local timestamps found (file missing or empty)")
        
    return data or {}


def save_local_last_sync(data):
    """Salveaza timestamp-urile cu verificare."""
    write_json(LAST_SYNC_FILE, data)
    
    # Verificam ca s-a salvat corect
    verify = read_json(LAST_SYNC_FILE)
    if verify and len(verify) >= len(data):
        log(f"[TRAKT SYNC] ✓ Saved timestamps: {list(data.keys())}")
    else:
        log(f"[TRAKT SYNC] ⚠️ WARNING: Save verification failed! Expected {len(data)}, got {len(verify) if verify else 0}", xbmc.LOGWARNING)

_RO_SYNC_FMT = '%d-%m-%Y %H:%M'

def _fmt_ro(val):
    """Convert any timestamp (ISO string, float, or None) to Romanian format string."""
    if not val:
        return None
    if isinstance(val, (int, float)):
        return time.strftime(_RO_SYNC_FMT, time.localtime(val))
    s = str(val).strip()
    try:
        s2 = s.replace('Z', '')
        if '.' in s2:
            s2 = s2.split('.')[0]
        dp, tp = s2.split('T')
        y, m, d = map(int, dp.split('-'))
        H, M, Sec = map(int, tp.split(':'))
        return time.strftime(_RO_SYNC_FMT, time.localtime(time.mktime((y, m, d, H, M, Sec, 0, 0, -1))))
    except Exception:
        pass
    return s

def _parse_to_ts(val):
    """Parse any value to a float timestamp for numeric comparisons."""
    if isinstance(val, (int, float)):
        return float(val)
    if not val:
        return 0.0
    s = str(val).strip()
    try:
        return time.mktime(time.strptime(s, _RO_SYNC_FMT))
    except Exception:
        pass
    try:
        s2 = s.replace('Z', '')
        if '.' in s2:
            s2 = s2.split('.')[0]
        dp, tp = s2.split('T')
        y, m, d = map(int, dp.split('-'))
        H, M, Sec = map(int, tp.split(':'))
        return time.mktime((y, m, d, H, M, Sec, 0, 0, -1))
    except Exception:
        pass
    return 0.0

def parse_trakt_date(date_str):
    """
    Parseaza data Trakt. Robust la formate cu/fara milisecunde.
    Fara strptime pentru a evita bug-ul Kodi.
    """
    if not date_str: return datetime.datetime.min
    try:
        # Eliminam 'Z' de la final si decupam milisecundele
        d = str(date_str).replace('Z', '')
        if '.' in d:
            d = d.split('.')[0]
            
        date_part, time_part = d.split('T')
        y, m, day = map(int, date_part.split('-'))
        H, M, S = map(int, time_part.split(':'))
        
        return datetime.datetime(y, m, day, H, M, S)
    except:
        return datetime.datetime.min

def needs_sync(section, remote_activities, local_sync_data, provider=''):
    pfx = f'[{provider} ' if provider else '['
    # 1. Verificam activities
    if not remote_activities or not isinstance(remote_activities, dict): 
        log(f"{pfx}SYNC-CHECK] {section}: ⚠️ No valid activities -> SYNC", xbmc.LOGWARNING)
        return True
    
    key_map = {
        'movies_watched': ('movies', 'watched_at'),
        'episodes_watched': ('episodes', 'watched_at'),
        'watchlist': ('watchlist', 'updated_at'),
        'lists': ('lists', 'updated_at'),
        'movies_collected': ('movies', 'collected_at'),
    }
    
    if section not in key_map: 
        log(f"{pfx}SYNC-CHECK] {section}: Unknown -> SYNC")
        return True
        
    category, field = key_map[section]
    
    # Extragem timestamps
    cat_data = remote_activities.get(category, {})
    remote_ts = cat_data.get(field) if cat_data else None
    local_ts = local_sync_data.get(section) if local_sync_data else None
    
    # ✅ DEBUG COMPLET
    log(f"{pfx}SYNC-CHECK] {section}: Remote='{remote_ts}' | Local='{local_ts}'")
    
    # 2. Fara data remote = skip
    if not remote_ts: 
        log(f"{pfx}SYNC-CHECK] {section}: No remote -> SKIP")
        return False 
    
    # 3. Fara data locala = sync
    if not local_ts: 
        log(f"{pfx}SYNC-CHECK] {section}: No local -> SYNC")
        return True 
    
    # 4. Comparatie exacta
    if remote_ts == local_ts:
        log(f"{pfx}SYNC-CHECK] {section}: ✓ Match -> SKIP")
        return False
        
    # 5. Comparatie datetime
    remote_date = parse_trakt_date(remote_ts)
    local_date = parse_trakt_date(local_ts)
    
    if remote_date > local_date:
        log(f"{pfx}SYNC-CHECK] {section}: Remote newer -> SYNC")
        return True
    else:
        log(f"{pfx}SYNC-CHECK] {section}: ✓ Local same/newer -> SKIP")
        return False

def sync_full_library(silent=False, force=False):
    from resources.lib import trakt_api

    try:
        from resources.lib.utils import warm_import_modules
        warm_import_modules()
    except Exception:
        pass

    # --- PREVENIRE SINCRONIZARE DUBLA ---
    window = xbmcgui.Window(10000)
    _sync_lock = window.getProperty('tmdbmovies_sync_active')
    if _sync_lock == 'true':
        _sync_start = window.getProperty('tmdbmovies_sync_started')
        if _sync_start and (time.time() - float(_sync_start)) < 600:
            log("[TRAKT SYNC] Sync already in progress. Ignoring new request.")
            if not silent:
                xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]", "Syncing...", os.path.join(ADDON.getAddonInfo('path'), 'icon.png'))
            return
        # Stale lock (>10 min) — previous process was killed during sync
        log("[TRAKT SYNC] Stale lock detected (>10min). Clearing and proceeding.")

    window.setProperty('tmdbmovies_sync_active', 'true')
    window.setProperty('tmdbmovies_sync_started', str(time.time()))

    try:
        # Verificam starea ambelor servicii
        trakt_token = trakt_api.get_trakt_token()
        tmdb_session = read_json(TMDB_V4_TOKEN_FILE)
        has_tmdb = tmdb_session and isinstance(tmdb_session, dict) and tmdb_session.get('access_token')

        # Daca nu este conectat niciun cont, oprim sincronizarea
        if not trakt_token and not has_tmdb:
            return

        init_database()
        
        p_dialog = None
        if not silent:
            p_dialog = xbmcgui.DialogProgressBG()
            p_dialog.create("[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]", "Checking for changes...")
        
        try:
            log("[TRAKT SYNC] === STARTING SMART SYNC ===")
            conn = get_connection()
            c = conn.cursor()
            
            local_sync = get_local_last_sync()
            new_sync = local_sync.copy() if local_sync else {}
            
            # --- SINCRONIZARE CONT TRAKT (Rulata doar daca Trakt este activ) ---
            if trakt_token:
                activities = get_trakt_last_activities()
                if activities:
                    # Datele interferente (watched, playback, hidden, up next) se sincronizeaza
                    # doar daca Trakt este providerul de watched status (paritate cu MDBList).
                    from resources.lib.watched_provider import is_trakt as _is_trakt_provider
                    provider_trakt = _is_trakt_provider()

                    # 1. WATCHED MOVIES
                    if provider_trakt:
                        should_sync_movies = force or needs_sync('movies_watched', activities, local_sync, provider='TRAKT') or is_table_empty(c, 'trakt_watched_movies')
                        if should_sync_movies:
                            if not silent and p_dialog: p_dialog.update(10, message="Sync: [B][COLOR pink]Watched Movies[/COLOR][/B]")
                            _sync_watched_movies(c)
                        new_sync['movies_watched'] = activities.get('movies', {}).get('watched_at')
                        conn.commit()

                        # 2. WATCHED EPISODES
                        should_sync_episodes = force or needs_sync('episodes_watched', activities, local_sync, provider='TRAKT') or is_table_empty(c, 'trakt_watched_episodes')
                        if should_sync_episodes:
                            if not silent and p_dialog: p_dialog.update(25, message="Sync: [B][COLOR pink]Watched Episodes[/COLOR][/B]")
                            _sync_watched_episodes(c)
                        new_sync['episodes_watched'] = activities.get('episodes', {}).get('watched_at')
                        conn.commit()

                    # 3. WATCHLIST
                    should_sync_watchlist = force or needs_sync('watchlist', activities, local_sync, provider='TRAKT') or is_table_empty(c, 'trakt_lists')
                    if should_sync_watchlist:
                        if not silent and p_dialog: p_dialog.update(40, message="Sync: [B][COLOR pink]Watchlist[/COLOR][/B]")
                        _sync_list_content(c, 'watchlist')
                    new_sync['watchlist'] = activities.get('watchlist', {}).get('updated_at')
                    conn.commit()

                    # 4. FAVORITES
                    if not silent and p_dialog: p_dialog.update(50, message="Sync: [B][COLOR pink]Trakt Favorites[/COLOR][/B]")
                    _sync_trakt_favorites(c)
                    conn.commit()

                    # 5. USER LISTS
                    should_sync_lists = force or needs_sync('lists', activities, local_sync, provider='TRAKT') or is_table_empty(c, 'user_lists')
                    if should_sync_lists:
                        if not silent and p_dialog: p_dialog.update(60, message="Sync: [B][COLOR pink]Liste Personale[/COLOR][/B]")
                        _sync_user_lists(c, force=force)
                    new_sync['lists'] = activities.get('lists', {}).get('updated_at')
                    conn.commit()

                    # 6. PLAYBACK, UP NEXT (doar daca Trakt e providerul de watched status)
                    if provider_trakt:
                        if not silent and p_dialog: p_dialog.update(70, message="Sync: [B][COLOR pink]Playback Progress[/COLOR][/B]")
                        _sync_playback(c); conn.commit()
                        if not silent and p_dialog: p_dialog.update(75, message="Sync: [B][COLOR pink]Up Next[/COLOR][/B]")
                        _sync_up_next(c, trakt_token); conn.commit()

                    # 7. HIDDEN SHOWS (Dropped) — intotdeauna cand Trakt e autorizat,
                    # indiferent de provider (date de curatare manuala, tabele separate
                    # de mdblist_dropped — fara interferenta).
                    _sync_hidden_shows(c); conn.commit()

            # --- SINCRONIZARE DISCOVERY (Independenta) ---
            last_disc = local_sync.get('discovery_ts', 0)
            disc_empty = is_table_empty(c, 'discovery_cache') or is_table_empty(c, 'tmdb_discovery')
            if force or disc_empty or (time.time() - last_disc > 21600):
                if not silent and p_dialog: p_dialog.update(85, message="Sync: [B][COLOR pink]Trending & Popular[/COLOR][/B]")
                _sync_trakt_discovery(c)
                if not silent and p_dialog: p_dialog.update(90, message="Sync: [B][COLOR FF00CED1]Liste TMDb[/COLOR][/B]")
                _sync_tmdb_discovery(c)
                new_sync['discovery_ts'] = time.time()
                conn.commit()

            # --- SINCRONIZARE CONT TMDB (Rulata doar daca TMDb este activ) ---
            if has_tmdb:
                # Force nu re-sincronizeaza TMDb daca tocmai a fost sincronizat (<60s):
                # in lantul dublu (provider activ + al doilea serviciu) TMDb nu se duplica.
                _last_tmdb = local_sync.get('tmdb_sync_ts', 0)
                tmdb_sync_needed = (time.time() - _last_tmdb > 1800) or (force and (time.time() - _last_tmdb > 60))
                if tmdb_sync_needed:
                    if not silent and p_dialog: p_dialog.update(95, message="Sync: [B][COLOR FF00CED1]Cont TMDb[/COLOR][/B]")
                    try:
                        _sync_tmdb_data(c, force=tmdb_sync_needed)
                        new_sync['tmdb_sync_ts'] = time.time()
                    except: pass
                    conn.commit()
            conn.close()
            
            save_local_last_sync(new_sync)
            cleanup_database()
            
            try:
                from resources.lib.utils import perform_trakt_backup
                perform_trakt_backup(manual=False)
            except: pass
            
            log("[TRAKT SYNC] === SYNC COMPLETE ===")
            if not silent and p_dialog:
                p_dialog.close()
                xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]", "Sync Complete", os.path.join(ADDON.getAddonInfo('path'), 'icon.png'))
                
        except Exception as e:
            log(f"[TRAKT SYNC] CRITICAL ERROR: {e}", xbmc.LOGERROR)
            if not silent and p_dialog:
                try: p_dialog.close()
                except: pass
            try:
                conn.rollback()
            except: pass
            try:
                conn.close()
            except: pass
    
    finally:
        window.clearProperty('tmdbmovies_sync_active')
        window.clearProperty('tmdbmovies_sync_started')
        try:
            from resources.lib.cache import clear_all_fast_cache
            clear_all_fast_cache()
        except: pass
        try:
            from resources.lib.mdblist_sync import clear_cache_prefix
            clear_cache_prefix('trakt_calendar')
        except: pass


def sync_tmdb_only(silent=True, force=True):
    """Sincronizeaza exclusiv datele contului TMDb, fara a atinge Trakt."""
    window = xbmcgui.Window(10000)
    if window.getProperty('tmdbmovies_sync_active') == 'true':
        log("[TMDB SYNC] A full sync is already in progress. Ignoring dedicated TMDb sync.")
        return

    session = read_json(TMDB_V4_TOKEN_FILE)
    if not session or not session.get('access_token'):
        return

    try:
        init_database()
        conn = get_connection()
        c = conn.cursor()
        
        # Sincronizam doar sectiunea de TMDb
        _sync_tmdb_data(c, force=force)
        
        conn.commit()
        conn.close()
        
        # Actualizam doar timestamp-ul local pentru TMDb
        local_sync = get_local_last_sync()
        local_sync['tmdb_sync_ts'] = time.time()
        save_local_last_sync(local_sync)
        
        log("[TMDB SYNC] TMDb sync completed separately.")
    except Exception as e:
        log(f"[TMDB SYNC] Error in dedicated TMDb sync: {e}", xbmc.LOGERROR)
        try:
            conn.rollback()
        except: pass
        try:
            conn.close()
        except: pass


# =============================================================================
# WORKER FUNCTIONS
# =============================================================================

def _sync_watched_movies(c):
    from resources.lib import trakt_api
    data = trakt_api._get_trakt_paginated_list("/sync/watched/movies", params={'extended': 'full,images'})
    if not data or not isinstance(data, list): return
    c.execute("DELETE FROM trakt_watched_movies")
    rows = []
    for item in data:
        if not item: continue
        m = item.get('movie') or {}
        tid = str((m.get('ids') or {}).get('tmdb', ''))
        if tid and tid != 'None':
            poster_path = ''
            backdrop_path = ''
            try:
                imgs = (m.get('images') or {})
                p_urls = imgs.get('poster') or []
                b_urls = imgs.get('fanart') or imgs.get('backdrop') or []
                if p_urls and isinstance(p_urls, list) and p_urls[0] and 'image.tmdb.org' in str(p_urls[0]):
                    poster_path = '/' + str(p_urls[0]).split('/')[-1].split('?')[0]
                if b_urls and isinstance(b_urls, list) and b_urls[0] and 'image.tmdb.org' in str(b_urls[0]):
                    backdrop_path = '/' + str(b_urls[0]).split('/')[-1].split('?')[0]
            except:
                pass
            rows.append((tid, m.get('title'), str(m.get('year','')), item.get('last_watched_at'), poster_path, backdrop_path, m.get('overview','')))
    if rows: 
        c.executemany("INSERT OR REPLACE INTO trakt_watched_movies VALUES (?,?,?,?,?,?,?)", rows)
        log(f"[TRAKT SYNC] Saved {len(rows)} watched movies.")

def _sync_watched_episodes(c):
    from resources.lib import trakt_api
    data = trakt_api._get_trakt_paginated_list("/sync/watched/shows", params={'extended': 'progress'})
    if not data or not isinstance(data, list): return
    c.execute("DELETE FROM trakt_watched_episodes")

    ep_rows = []

    for item in data:
        if not item: continue
        s = item.get('show') or {}
        tid = str((s.get('ids') or {}).get('tmdb', ''))
        if not tid or tid == 'None': continue

        title = s.get('title', '')
        overview = s.get('overview', '')
        for season in item.get('seasons', []):
            s_num = season.get('number')
            for ep in season.get('episodes', []):
                rows_data = (tid, s_num, ep.get('number'), title, ep.get('last_watched_at'))
                ep_rows.append(rows_data)

        c.execute("INSERT OR IGNORE INTO tv_meta (tmdb_id, total_episodes, poster, backdrop, overview) VALUES (?,?,?,?,?)",
                  (tid, 0, '', '', overview))

    if ep_rows:
        c.executemany("INSERT OR REPLACE INTO trakt_watched_episodes VALUES (?,?,?,?,?)", ep_rows)
        log(f"[TRAKT SYNC] Saved {len(ep_rows)} watched episodes.")

def _sync_list_content(c, ltype):
    from resources.lib import trakt_api
    
    for m in ['movies', 'shows']:
        data = trakt_api.trakt_api_request(f"/sync/{ltype}/{m}", params={'extended': 'full,images'})
        if not data or not isinstance(data, list): continue
        db_type = 'movie' if m == 'movies' else 'show'
        c.execute("DELETE FROM trakt_lists WHERE list_type=? AND media_type=?", (ltype, db_type))
        rows = []
        for item in data:
            if not item: continue
            meta = item.get('movie') if m == 'movies' else item.get('show')
            if not meta: continue
            
            tid = str((meta.get('ids') or {}).get('tmdb', ''))
            if tid and tid != 'None':
                # Poster/backdrop din Trakt images (URL-uri full, extragem doar calea)
                poster_path = ''
                backdrop_path = ''
                try:
                    imgs = (meta.get('images') or {})
                    p_urls = imgs.get('poster') or []
                    b_urls = imgs.get('fanart') or imgs.get('backdrop') or []
                    if p_urls and isinstance(p_urls, list) and p_urls[0] and 'image.tmdb.org' in str(p_urls[0]):
                        poster_path = '/' + str(p_urls[0]).split('/')[-1].split('?')[0]
                    if b_urls and isinstance(b_urls, list) and b_urls[0] and 'image.tmdb.org' in str(b_urls[0]):
                        backdrop_path = '/' + str(b_urls[0]).split('/')[-1].split('?')[0]
                except:
                    pass
                rows.append((ltype, db_type, tid, meta.get('title'), str(meta.get('year','')), 
                             item.get('collected_at') or item.get('listed_at'), poster_path, backdrop_path, meta.get('overview','')))
        
        if rows: 
            c.executemany("INSERT OR REPLACE INTO trakt_lists VALUES (?,?,?,?,?,?,?,?,?)", rows)
            log(f"[TRAKT SYNC] Saved {len(rows)} items in {ltype} ({m}).")
    
    # ✅ ELIMINAT: sincronizarea detaliilor TV

def _sync_user_lists(c, force=False):
    from resources.lib import trakt_api
    from concurrent.futures import ThreadPoolExecutor # Import necesar aici
    
    user = trakt_api.get_trakt_username()
    if not user: return

    # Migrare coloane
    try:
        c.execute("SELECT poster_tmdb_id FROM user_lists LIMIT 1")
    except:
        try: c.execute("ALTER TABLE user_lists ADD COLUMN poster_tmdb_id TEXT")
        except: pass

    remote_lists = trakt_api.trakt_api_request(f"/users/{user}/lists")
    if not remote_lists or not isinstance(remote_lists, list): return
    
    try:
        c.execute("SELECT trakt_id, updated_at, item_count FROM user_lists")
        local_map = {str(row['trakt_id']): {'updated_at': str(row['updated_at'] or ''), 'count': int(row['item_count'] or 0)} for row in c.fetchall()}
    except: local_map = {}

    # --- FUNCTIE WORKER PENTRU PARALELIZARE ---
    def fetch_trakt_list_worker(lst):
        trakt_id = str((lst.get('ids') or {}).get('trakt', ''))
        slug = (lst.get('ids') or {}).get('slug')
        name = lst.get('name', 'Unknown')
        remote_updated_at = str(lst.get('updated_at', ''))
        remote_item_count = int(lst.get('item_count', 0))
        
        if not slug or not trakt_id: return None
        
        # Verificam daca lista s-a schimbat
        should_sync = force or trakt_id not in local_map or \
                      local_map[trakt_id]['updated_at'] != remote_updated_at or \
                      local_map[trakt_id]['count'] != remote_item_count
        
        items_data = None
        if should_sync:
            log(f"[TRAKT SYNC] Parallel Fetch Trakt List: {name}")
            items_data = trakt_api.trakt_api_request(f"/users/{user}/lists/{slug}/items", params={'extended': 'full,images'})
            
        return {
            'header': (trakt_id, name, slug, remote_item_count, lst.get('sort_by'), lst.get('sort_how'), lst.get('description', '') or '', remote_updated_at),
            'items': items_data, 
            'slug': slug, 
            'should_sync': should_sync, 
            'trakt_id': trakt_id
        }

    # Lansam 5 fire de executie pentru viteza
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(fetch_trakt_list_worker, remote_lists))

    remote_ids = []
    for res in results:
        if not res: continue
        remote_ids.append(res['trakt_id'])
        
        # 4. Salvam header-ul listei
        # IMPORTANT: Pastram poster-ul si backdrop-ul daca existau deja local (Trakt API nu le trimite)
        c.execute("SELECT poster, backdrop, poster_tmdb_id FROM user_lists WHERE trakt_id=?", (res['trakt_id'],))
        existing = c.fetchone()
        p = existing['poster'] if existing else ''
        b = existing['backdrop'] if existing else ''
        pt = existing['poster_tmdb_id'] if existing else ''
        
        full_header = res['header'] + (p, b, pt)
        cols = "(trakt_id, name, slug, item_count, sort_by, sort_how, description, updated_at, poster, backdrop, poster_tmdb_id)"
        c.execute(f"INSERT OR REPLACE INTO user_lists {cols} VALUES (?,?,?,?,?,?,?,?,?,?,?)", full_header)
        
        # 5. Salvam itemele daca lista a fost descarcata
        if res['should_sync'] and res['items'] and isinstance(res['items'], list):
            c.execute("DELETE FROM user_list_items WHERE list_slug=?", (res['slug'],))
            i_rows = []
            for it in res['items']:
                if not it: continue
                typ = it.get('type')
                if typ in ['movie', 'show']:
                    meta = it.get(typ) or {}
                    tid = str((meta.get('ids') or {}).get('tmdb', ''))
                    if tid and tid != 'None':
                        poster_path = ''
                        backdrop_path = ''
                        try:
                            imgs = (meta.get('images') or {})
                            p_urls = imgs.get('poster') or []
                            b_urls = imgs.get('fanart') or imgs.get('backdrop') or []
                            if p_urls and isinstance(p_urls, list) and p_urls[0] and 'image.tmdb.org' in str(p_urls[0]):
                                poster_path = '/' + str(p_urls[0]).split('/')[-1].split('?')[0]
                            if b_urls and isinstance(b_urls, list) and b_urls[0] and 'image.tmdb.org' in str(b_urls[0]):
                                backdrop_path = '/' + str(b_urls[0]).split('/')[-1].split('?')[0]
                        except:
                            pass
                        # Pastram ordinea adaugarii (Newest First) folosind listed_at
                        i_rows.append((res['slug'], typ, tid, meta.get('title'), str(meta.get('year','')), it.get('listed_at'), poster_path, backdrop_path, meta.get('overview','')))
            if i_rows:
                c.executemany("INSERT OR REPLACE INTO user_list_items VALUES (?,?,?,?,?,?,?,?,?)", i_rows)

    # 6. Stergere liste orfane
    for local_id in local_map.keys():
        if local_id not in remote_ids:
            c.execute("SELECT slug FROM user_lists WHERE trakt_id=?", (local_id,))
            row = c.fetchone()
            if row: c.execute("DELETE FROM user_list_items WHERE list_slug=?", (row['slug'],))
            c.execute("DELETE FROM user_lists WHERE trakt_id=?", (local_id,))


def _sync_playback(c):
    from resources.lib import trakt_api
    from resources.lib.utils import get_json
    from resources.lib.config import API_KEY, BASE_URL
    import datetime
    
    # 1. Cerem datele de la Trakt
    data = trakt_api.trakt_api_request("/sync/playback", params={'limit': 100, 'extended': 'full'})
    if not data or not isinstance(data, list): 
        return
    
    # 2. SALVAM TEMPORAR CE AVEAM LOCAL PENTRU A NU PIERDE SECUNDE EXACTE / DELAY TRAKT
    c.execute("SELECT * FROM playback_progress")
    local_progress = {}
    for row in c.fetchall():
        key = f"{row['tmdb_id']}_{row['media_type']}_{row['season']}_{row['episode']}"
        local_progress[key] = dict(row)
        
    c.execute("DELETE FROM playback_progress")
    rows =[]
    
    # 3. Procesam datele de la Trakt
    for item in data:
        progress = item.get('progress', 0)
        if progress <= 1 or progress >= 99: 
            continue
            
        typ = item.get('type')
        meta = item.get('movie') if typ == 'movie' else item.get('show')
        if not meta: continue
        
        ids = meta.get('ids') or {}
        tid = str(ids.get('tmdb', ''))
        
        # Fallback daca lipseste TMDB ID, convertim din IMDb
        imdb_id = ids.get('imdb', '')
        if (not tid or tid == 'None') and imdb_id:
            try:
                find_url = f"{BASE_URL}/find/{imdb_id}?api_key={API_KEY}&external_source=imdb_id"
                find_data = get_json(find_url)
                if typ == 'movie' and find_data.get('movie_results'):
                    tid = str(find_data['movie_results'][0]['id'])
                elif typ == 'show' and find_data.get('tv_results'):
                    tid = str(find_data['tv_results'][0]['id'])
            except: pass
            
        if not tid or tid == 'None': continue
        
        s, e = 0, 0
        year = str(meta.get('year', ''))
        
        if typ == 'episode':
            ep = item.get('episode') or {}
            s = ep.get('season', 0)
            e = ep.get('number', 0)
            show_title = meta.get('title', 'Unknown Show')
            ep_title = ep.get('title', '')
            title = f"{show_title} - S{s:02d}E{e:02d}"
            if ep_title: title += f" - {ep_title}"
        else:
            title = meta.get('title', 'Unknown Movie')
            
        paused_at = item.get('paused_at', '')
        
        # --- MAGIA MERGE-ULUI: Pastram secundele exacte locale daca exista! ---
        key = f"{tid}_{typ}_{s}_{e}"
        if key in local_progress:
            local_val = local_progress[key]['progress']
            local_time = local_progress[key]['paused_at']
            # Daca local aveam valoarea magica >1.000.000 (secunde exacte), o restauram
            if local_val >= 1000000:
                progress = local_val
                paused_at = local_time
        # ----------------------------------------------------------------------
        
        rows.append((tid, typ, s, e, progress, paused_at, title, year, ''))
        
    # 4. SALVAM SI CE ERA LOCAL DAR A FOST OMIS DE TRAKT (Trakt API Cache Delay)
    now = datetime.datetime.utcnow()
    for key, loc in local_progress.items():
        # Verificam daca nu cumva a fost deja procesat mai sus
        if not any(r[0] == loc['tmdb_id'] and r[1] == loc['media_type'] and r[2] == loc['season'] and r[3] == loc['episode'] for r in rows):
            try:
                # Parsare manuala fara strptime
                clean_date = str(loc['paused_at']).replace('.000Z', '').replace('Z', '')
                d_part, t_part = clean_date.split('T')
                y, m, d_zi = map(int, d_part.split('-'))
                H, M, S = map(int, t_part.split(':'))
                loc_time = datetime.datetime(y, m, d_zi, H, M, S)
                
                # Daca l-ai vizionat acum mai putin de 24h, il pastram local fortat!
                if (now - loc_time).total_seconds() < 86400:
                    rows.append((loc['tmdb_id'], loc['media_type'], loc['season'], loc['episode'], 
                                 loc['progress'], loc['paused_at'], loc['title'], loc['year'], loc['poster']))
            except: pass

    if rows: 
        c.executemany("INSERT OR REPLACE INTO playback_progress VALUES (?,?,?,?,?,?,?,?,?)", rows)
        log(f"[TRAKT SYNC] Saved {len(rows)} items in progress (Merged with local cache limit 100 + ID Fix).")


def _sync_trakt_discovery(c):
    from resources.lib import trakt_api
    c.execute("DELETE FROM discovery_cache")
    
    # Configuratie (API endpoint part, media type, DB type)
    endpoints = [
        ('trending', 'movies', 'movie'), 
        ('trending', 'shows', 'show'),
        ('popular', 'movies', 'movie'), 
        ('popular', 'shows', 'show'),
        ('anticipated', 'movies', 'movie'), 
        ('anticipated', 'shows', 'show'),
        ('boxoffice', 'movies', 'movie')
    ]
    
    total_saved = 0
    for ltype, media, db_type in endpoints:
        try:
            # Boxoffice e special
            if ltype == 'boxoffice':
                data = trakt_api.get_trakt_box_office()
            elif ltype == 'trending':
                data = trakt_api._fetch_trakt_paginated(trakt_api.get_trakt_trending, media, 500)
            elif ltype == 'popular':
                data = trakt_api._fetch_trakt_paginated(trakt_api.get_trakt_popular, media, 500)
            elif ltype == 'anticipated':
                data = trakt_api._fetch_trakt_paginated(trakt_api.get_trakt_anticipated, media, 500)
            else:
                continue

            if not data or not isinstance(data, list): continue
            
            rows = []
            rank = 1
            for item in data:
                if not item: continue
                # Boxoffice returneaza item-ul direct, altele au cheie movie/show
                meta = item.get(db_type) if ltype != 'boxoffice' and db_type in item else item
                
                tid = str((meta.get('ids') or {}).get('tmdb', ''))
                if tid and tid != 'None':
                    title = meta.get('title', '')
                    year = str(meta.get('year', ''))
                    overview = meta.get('overview', '')
                    
                    # ✅ REVERT: Nu salvam postere de la Trakt (nu le are)
                    # Posterele se vor incarca prin self-healing la afisare
                    rows.append((ltype, db_type, tid, title, year, '', '', overview, rank))
                    rank += 1
            
            if rows:
                c.executemany("INSERT OR REPLACE INTO discovery_cache VALUES (?,?,?,?,?,?,?,?,?)", rows)
                total_saved += len(rows)
        except Exception as e:
            pass
            
    log(f"[TRAKT SYNC] Saved {total_saved} Trakt discovery items.")

def _sync_tmdb_discovery(c):
    """Sincronizeaza TOATE listele TMDb definite in meniu."""
    import requests
    from resources.lib.tmdb_api import get_tmdb_movies_standard, get_tmdb_tv_standard
    
    # ✅ LISTA COMPLETA - Movies (10 liste)
    movie_actions = [
        'tmdb_movies_trending_day', 
        'tmdb_movies_trending_week', 
        'tmdb_movies_popular', 
        'tmdb_movies_top_rated',
        'tmdb_movies_premieres', 
        'tmdb_movies_latest_releases', 
        'tmdb_movies_netflix',
        'tmdb_movies_amazon',
        'tmdb_movies_disney',
        'tmdb_movies_apple',
        'tmdb_movies_box_office', 
        'tmdb_movies_now_playing',
        'tmdb_movies_upcoming', 
        'tmdb_movies_anticipated', 
        'tmdb_movies_blockbusters',
        'hindi_movies_trending',
        'hindi_movies_popular',
        'hindi_movies_premieres',
        'hindi_movies_in_theaters',
        'hindi_movies_upcoming',
        'hindi_movies_anticipated'
    ]
    
    # ✅ LISTA COMPLETA - TV Shows (8 liste)
    tv_actions = [
        'tmdb_tv_trending_day', 
        'tmdb_tv_trending_week', 
        'tmdb_tv_popular', 
        'tmdb_tv_top_rated',
        'tmdb_tv_premieres', 
        'tmdb_tv_latest_releases',
        'tmdb_tv_netflix',
        'tmdb_tv_amazon',
        'tmdb_tv_disney',
        'tmdb_tv_apple',
        'tmdb_tv_airing_today', 
        'tmdb_tv_on_the_air', 
        'tmdb_tv_upcoming'
    ]
    
    # Stergem cache-ul vechi
    c.execute("DELETE FROM tmdb_discovery")
    
    total_saved = 0
    
    # Sincronizam Movies
    for action in movie_actions:
        try:
            r = get_tmdb_movies_standard(action, 1)
            if r and r.status_code == 200:
                data = r.json().get('results', [])
                rows = []
                rank = 1
                for item in data:
                    if not item: continue
                    tid = str(item.get('id', ''))
                    if not tid: continue
                    
                    title = item.get('title', '')
                    date_val = str(item.get('release_date', ''))
                    year = date_val[:4] if len(date_val) >= 4 else ''
                    poster = item.get('poster_path', '')
                    overview = item.get('overview', '')
                    
                    rows.append((action, 1, tid, title, year, poster, overview, rank))
                    rank += 1
                
                if rows:
                    c.executemany("INSERT OR REPLACE INTO tmdb_discovery VALUES (?,?,?,?,?,?,?,?)", rows)
                    total_saved += len(rows)
        except Exception as e:
            log(f"[TMDB SYNC] Error sync tmdb {action}: {e}", xbmc.LOGERROR)
    
    # Sincronizam TV Shows
    for action in tv_actions:
        try:
            r = get_tmdb_tv_standard(action, 1)
            if r and r.status_code == 200:
                data = r.json().get('results', [])
                rows = []
                rank = 1
                for item in data:
                    if not item: continue
                    tid = str(item.get('id', ''))
                    if not tid: continue
                    
                    title = item.get('name', '')
                    date_val = str(item.get('first_air_date', ''))
                    year = date_val[:4] if len(date_val) >= 4 else ''
                    poster = item.get('poster_path', '')
                    overview = item.get('overview', '')
                    
                    rows.append((action, 1, tid, title, year, poster, overview, rank))
                    rank += 1
                
                if rows:
                    c.executemany("INSERT OR REPLACE INTO tmdb_discovery VALUES (?,?,?,?,?,?,?,?)", rows)
                    total_saved += len(rows)
        except Exception as e:
            log(f"[TMDB SYNC] Error sync tmdb {action}: {e}", xbmc.LOGERROR)
    
    log(f"[TMDB SYNC] Saved {total_saved} TMDb discovery items (Movies & TV).")


def _sync_tmdb_data(c, force=False):
    from resources.lib.config import TMDB_V4_TOKEN_FILE, TMDB_V4_BASE_URL, LANG
    from resources.lib.utils import read_json, get_language
    import requests
    from concurrent.futures import ThreadPoolExecutor

    session = read_json(TMDB_V4_TOKEN_FILE)
    if not session or not session.get('access_token'):
        log("[TMDB SYNC] TMDb Account sync skipped: No v4 token found")
        return

    token = session['access_token']
    aid = session['account_id']
    lang = get_language()
    headers = {'Authorization': f'Bearer {token}'}

# 1. WATCHLIST & FAVORITES (Oglindire exacta a site-ului)
    endpoints = [('watchlist', 'movie', 'movie'), ('watchlist', 'tv', 'tv'), ('favorite', 'movie', 'movie'), ('favorite', 'tv', 'tv')]
    for ltype, endpoint_media, db_media in endpoints:
        try:
            # Verificam daca e cazul de sync
            c.execute("SELECT 1 FROM tmdb_account_lists WHERE list_type=? AND media_type=? LIMIT 1", (ltype, db_media))
            section_is_empty = c.fetchone() is None
            
            # Sincronizam TMDb daca: e force, tabelul e gol, sau au trecut 30 min de la ultimul sync TMDb
            if force or section_is_empty:
                # Stergem local categoria respectiva
                c.execute("DELETE FROM tmdb_account_lists WHERE list_type=? AND media_type=?", (ltype, db_media))
                c.connection.commit() # Salvam stergerea inainte de a descarca
                
                # log(f"[SYNC] Fresh Fetch TMDb {ltype} ({db_media})...")
                page = 1
                total_fetched = 0
                while True:
                    # CRITIC: Folosim requests.get DIRECT, NU cache_object!
                    # v4: media type (singular) vine INAINTE: /account/{aid}/movie/watchlist
                    resource = 'watchlist' if ltype == 'watchlist' else 'favorites'
                    url = f"{TMDB_V4_BASE_URL}/account/{aid}/{endpoint_media}/{resource}"
                    r = requests.get(url, headers=headers, params={'language': lang, 'page': page, 'sort_by': 'created_at.desc'}, timeout=10)
                    if r.status_code != 200: break
                    
                    data = r.json()
                    results = data.get('results', [])
                    if not results: break
                    
                    total_fetched += len(results)
                    _sync_tmdb_account_list_single(c, ltype, db_media, results, page)
                    if page >= data.get('total_pages', 1): break
                    page += 1
                
                log(f"[TMDB SYNC] Saved {total_fetched} items in TMDb {ltype} ({db_media}).")
                c.connection.commit()
# -------------------------------------------------------------
        except Exception as e:
            log(f"[TMDB SYNC] Error in TMDb category {ltype}: {e}", xbmc.LOGERROR)

# 2. LISTE PERSONALE TMDB (PARALELIZATE)
    try:
        url_lists = f"{TMDB_V4_BASE_URL}/account/{aid}/lists"
        r = requests.get(url_lists, headers=headers, params={'page': 1}, timeout=10)
        
        if r.status_code == 200:
            lists_data = r.json().get('results', [])
            c.execute("SELECT list_id, item_count FROM tmdb_custom_lists")
            local_lists = {str(row['list_id']): int(row['item_count']) for row in c.fetchall()}
            
            # WORKER CU TRANSMITERE EXPLICITA DE VARIABILE (VITEZA + STABILITATE)
            def fetch_tmdb_list_worker(lst_item, _sid, _aid, _lang, _force, _local_map, _headers):
                import requests
                from resources.lib.config import TMDB_V4_BASE_URL
                
                list_id = str(lst_item.get('id'))
                # v4 returneaza number_of_items (NU item_count — v3). Fara asta, toate listele apar cu (0).
                remote_count = int(lst_item.get('number_of_items', lst_item.get('item_count', 0)))
                name = lst_item.get('name', '')
                description = lst_item.get('description', '') or ''
                
                # --- LOGICA DE SYNC REPARATA ---
                should_sync = _force or list_id not in _local_map or _local_map.get(list_id) != remote_count
                
                # 4. VERIFICARE EXTRA: Chiar daca numarul e egal, verificam daca tabelul de iteme e gol
                if not should_sync:
                    try:
                        c_check = get_connection().cursor()
                        c_check.execute("SELECT COUNT(*) FROM tmdb_custom_list_items WHERE list_id=?", (list_id,))
                        count_local_items = c_check.fetchone()[0]
                        if count_local_items == 0 and remote_count > 0:
                            should_sync = True
                    except: pass

                poster, backdrop, items = '', '', []
                
                if should_sync:
                    log(f"[TMDB SYNC] Parallel Sync TMDb List: {name} ({remote_count} items)")
                    try:
                        page = 1
                        while True:
                            # Folosim v4 pentru a suporta seriale
                            list_url = f"{TMDB_V4_BASE_URL}/list/{list_id}"
                            r_raw = requests.get(list_url, headers=_headers, params={'language': _lang, 'page': page}, timeout=10)
                            if r_raw.status_code != 200: break
                            
                            lr_res = r_raw.json()
                            curr_items = lr_res.get('results', [])  # v4 returneaza 'results', nu 'items'
                            if not curr_items: break
                            
                            if page == 1:
                                poster = curr_items[0].get('poster_path', '')
                                backdrop = curr_items[0].get('backdrop_path', '')
                            
                            items.extend(curr_items)
                            
                            if page >= lr_res.get('total_pages', 1): break
                            page += 1
                    except Exception as e:
                        log(f"[TRAKT SYNC] Error fetching list {name}: {e}")
                
                return {
                    'id': list_id, 
                    'name': name, 
                    'count': remote_count, 
                    'desc': description, 
                    'poster': poster, 
                    'backdrop': backdrop, 
                    'items': items, 
                    'should_sync': should_sync
                }

            # Lansam thread-urile (max_workers=5 este ideal pentru TMDb)
            with ThreadPoolExecutor(max_workers=5) as executor:
                results = list(executor.map(lambda l: fetch_tmdb_list_worker(l, token, aid, lang, force, local_lists, headers), lists_data))

            remote_ids = []
            for res in results:
                if not res: continue
                remote_ids.append(res['id'])
                
                if not res['should_sync']:
                    c.execute("SELECT poster, backdrop FROM tmdb_custom_lists WHERE list_id=?", (res['id'],))
                    old = c.fetchone()
                    if old: res['poster'], res['backdrop'] = old['poster'], old['backdrop']

                c.execute("INSERT OR REPLACE INTO tmdb_custom_lists VALUES (?,?,?,?,?,?)", 
                          (res['id'], res['name'], res['count'], res['poster'], res['backdrop'], res['desc']))
                
                # 2. Update Continut (CRITIC: Pastram ordinea originala)
                if res['should_sync']:
                    c.execute("DELETE FROM tmdb_custom_list_items WHERE list_id=?", (res['id'],))
                    if res['items']:
                        i_rows = []
                        for idx, it in enumerate(res['items']):
                            tid = str(it.get('id', ''))
                            m_type = it.get('media_type', 'movie')
                            title = it.get('title') if m_type == 'movie' else it.get('name')
                            year = (it.get('release_date') or it.get('first_air_date') or '0000')[:4]
                            
                            # Adaugam idx (indexul de pe site) ca a 8-a valoare pentru sort_index
                            i_rows.append((res['id'], tid, m_type, title, year, it.get('poster_path', ''), it.get('overview', ''), idx))
                        
                        if i_rows:
                            # 8 semne de intrebare pentru a se potrivi cu i_rows
                            c.executemany("INSERT OR REPLACE INTO tmdb_custom_list_items VALUES (?,?,?,?,?,?,?,?)", i_rows)

            # Cleanup liste sterse
            for lid in local_lists.keys():
                if lid not in remote_ids:
                    c.execute("DELETE FROM tmdb_custom_lists WHERE list_id=?", (lid,))
                    c.execute("DELETE FROM tmdb_custom_list_items WHERE list_id=?", (lid,))
        c.connection.commit()
    except Exception as e:
        log(f"[TMDB SYNC] Error parallel tmdb lists: {e}", xbmc.LOGERROR)
    try: c.connection.commit()
    except: pass

    # 3. RECOMMENDATIONS (Raman la fel)
    try:
        c.execute("DELETE FROM tmdb_recommendations")
        for m_type in ['movie', 'tv']:
            # v4: media type (singular) inainte: /account/{aid}/movie/favorites
            fav_url = f"{TMDB_V4_BASE_URL}/account/{aid}/{m_type}/favorites"
            fav_r = requests.get(fav_url, headers=headers, params={'language': lang, 'page': 1, 'sort_by': 'created_at.desc'}, timeout=10)
            if fav_r.status_code == 200:
                favorites = fav_r.json().get('results', [])
                seen_ids = set()
                rows = []
                for fav_item in favorites[:5]:
                    fav_id = fav_item.get('id')
                    if not fav_id: continue
                    rec_url = f"{BASE_URL}/{m_type}/{fav_id}/recommendations?api_key={API_KEY}&language={lang}&page=1"
                    rec_r = requests.get(rec_url, timeout=10)
                    if rec_r.status_code == 200:
                        recs = rec_r.json().get('results', [])
                        for item in recs:
                            tid = str(item.get('id', ''))
                            if not tid or tid in seen_ids: continue
                            seen_ids.add(tid)
                            title = item.get('title') if m_type == 'movie' else item.get('name')
                            date_key = 'release_date' if m_type == 'movie' else 'first_air_date'
                            year_raw = str(item.get(date_key, ''))
                            year = year_raw[:4] if len(year_raw) >= 4 else ''
                            rows.append((m_type, tid, title, year, item.get('poster_path', ''), item.get('overview', '')))
                            if len(rows) >= 40: break
                    if len(rows) >= 40: break
                if rows: c.executemany("INSERT OR REPLACE INTO tmdb_recommendations VALUES (?,?,?,?,?,?)", rows)
    except: pass
    try: c.connection.commit()
    except: pass

    # 4. TMDB UP NEXT (watchlist TV + progresul providerului activ)
    try:
        sync_tmdb_up_next(c)
    except Exception as e:
        log(f"[TMDB SYNC] sync_tmdb_up_next hook error: {e}", xbmc.LOGERROR)
    try: c.connection.commit()
    except: pass


def _sync_tmdb_account_list_single(cursor, list_type, media_type, results, page=1):
    """Helper pentru salvarea Watchlist/Favorites in SQL cu sortare corecta."""
    if not results: return

    # Luam timpul curent
    base_time = time.time()
    
    rows = []
    # Folosim enumerate pentru a pastra ordinea din interiorul paginii
    for index, item in enumerate(results):
        tid = str(item.get('id', ''))
        if not tid: continue
        
        title = item.get('title') if media_type == 'movie' else item.get('name')
        
        date_key = 'release_date' if media_type == 'movie' else 'first_air_date'
        year_raw = str(item.get(date_key, ''))
        year = year_raw[:4] if len(year_raw) >= 4 else ''
        
        poster = item.get('poster_path', '')
        overview = item.get('overview', '')
                
        sort_timestamp = base_time - (page * 1000) - index
        added_at = str(sort_timestamp)
        
        full_date = year_raw if len(year_raw) >= 8 else ''
        if media_type == 'movie':
            release_date = full_date
            first_air_date = ''
        else:
            release_date = ''
            first_air_date = full_date
        
        rows.append((list_type, media_type, tid, title, year, poster, added_at, overview, release_date, first_air_date))
    
    if rows:
        cursor.executemany("INSERT OR REPLACE INTO tmdb_account_lists VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        

def _sync_single_tmdb_custom_list_items(c, list_id, lang): # Parametru nou: lang
    """Helper pentru continutul unei liste custom."""
    from resources.lib.config import API_KEY, BASE_URL
    import requests
    
    # Stergem continutul vechi al acestei liste inainte de a pune cel nou
    c.execute("DELETE FROM tmdb_custom_list_items WHERE list_id=?", (str(list_id),))
    
    page = 1
    total_items = 0
    
    while True:
        # Folosim parametrul lang primit
        url = f"{BASE_URL}/list/{list_id}?api_key={API_KEY}&language={lang}&page={page}"
        try:
            r = requests.get(url, timeout=10)
            if r.status_code != 200: break
            data = r.json()
            items = data.get('items', [])
            if not items: break
            
            rows = []
            for item in items:
                tid = str(item.get('id', ''))
                m_type = item.get('media_type', 'movie')
                title = item.get('title') if m_type == 'movie' else item.get('name')
                
                date_key = 'release_date' if m_type == 'movie' else 'first_air_date'
                year_raw = str(item.get(date_key, ''))
                year = year_raw[:4] if len(year_raw) >= 4 else ''
                
                poster = item.get('poster_path', '')
                overview = item.get('overview', '')
                
                rows.append((str(list_id), tid, m_type, title, year, poster, overview))
            
            if rows:
                c.executemany("INSERT OR REPLACE INTO tmdb_custom_list_items VALUES (?,?,?,?,?,?,?)", rows)
                total_items += len(rows)
                
            if len(items) < 20: break
            page += 1
        except:
            break


def _sync_tmdb_recommendations_fast(c):
    """Sincronizeaza recomandarile TMDb."""
    from resources.lib.config import TMDB_V4_TOKEN_FILE, TMDB_V4_BASE_URL, LANG
    from resources.lib.utils import read_json
    import requests
    
    session = read_json(TMDB_V4_TOKEN_FILE)
    if not session or not session.get('access_token'): 
        log("[TMDB SYNC] Recommendations: No TMDb v4 token", xbmc.LOGWARNING)
        return
    
    c.execute("DELETE FROM tmdb_recommendations")
    
    total_saved = 0
    aid = session['account_id']
    headers = {'Authorization': f"Bearer {session['access_token']}"}
    
    for m_type in ['movie', 'tv']:
        try:
            # v4: media type (singular) inainte: /account/{aid}/movie/favorites
            fav_url = f"{TMDB_V4_BASE_URL}/account/{aid}/{m_type}/favorites"
            
            # ✅ ELIMINAT: logging URL cu API key
            fav_r = requests.get(fav_url, headers=headers, params={'language': LANG, 'page': 1, 'sort_by': 'created_at.desc'}, timeout=10)
            
            if fav_r.status_code != 200:
                log(f"[TMDB SYNC] Recommendations {m_type}: API status {fav_r.status_code}", xbmc.LOGWARNING)
                continue
            
            favorites = fav_r.json().get('results', [])
            if not favorites:
                log(f"[TMDB SYNC] Recommendations {m_type}: no favorites", xbmc.LOGWARNING)
                continue
            
            log(f"[TMDB SYNC] Recommendations {m_type}: found {len(favorites)} favorites")
            
            seen_ids = set()
            rows = []
            
            for fav_item in favorites[:10]:
                fav_id = fav_item.get('id')
                if not fav_id: continue
                
                for page in [1, 2]:
                    rec_url = f"{BASE_URL}/{m_type}/{fav_id}/recommendations?api_key={API_KEY}&language={LANG}&page={page}"
                    rec_r = requests.get(rec_url, timeout=10)
                    
                    if rec_r.status_code == 200:
                        recs = rec_r.json().get('results', [])
                        
                        for item in recs:
                            tid = str(item.get('id', ''))
                            if not tid or tid in seen_ids: continue
                            seen_ids.add(tid)
                            
                            title = item.get('title') if m_type == 'movie' else item.get('name')
                            date_key = 'release_date' if m_type == 'movie' else 'first_air_date'
                            year_raw = str(item.get(date_key, ''))
                            year = year_raw[:4] if len(year_raw) >= 4 else ''
                            poster = item.get('poster_path', '')
                            overview = item.get('overview', '')
                            
                            rows.append((m_type, tid, title, year, poster, overview))
                            
                            if len(rows) >= 100:
                                break
                    
                    if len(rows) >= 100:
                        break
                
                if len(rows) >= 100:
                    break
            
            if rows:
                c.executemany("INSERT OR REPLACE INTO tmdb_recommendations VALUES (?,?,?,?,?,?)", rows)
                total_saved += len(rows)
                log(f"[TMDB SYNC] Recommendations {m_type}: salvate {len(rows)} items")
        except Exception as e:
            log(f"[TMDB SYNC] Error recommendations {m_type}: {e}", xbmc.LOGERROR)
    
    if total_saved > 0:
        log(f"[TMDB SYNC] Total recommendations saved: {total_saved}")
    else:
        log("[TMDB SYNC] WARNING: No recommendations saved!", xbmc.LOGWARNING)


# =============================================================================
# GETTERS
# =============================================================================

def get_trakt_discovery_from_db(list_type, media_type):
    if not os.path.exists(DB_PATH): return []
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM discovery_cache WHERE list_type=? AND media_type=? ORDER BY rank", (list_type, media_type))
    items = [dict(row) for row in c.fetchall()]
    conn.close()
    return items

def get_trakt_list_from_db(list_type, media_type):
    if not os.path.exists(DB_PATH): return []
    conn = get_connection()
    c = conn.cursor()
    # Sortare descrescatoare dupa string-ul datei (ISO format sorteaza corect alfabetic)
    c.execute("SELECT * FROM trakt_lists WHERE list_type=? AND media_type=? ORDER BY added_at DESC", (list_type, media_type))
    items = [dict(row) for row in c.fetchall()]
    conn.close()
    return items

def get_history_from_db(media_type):
    if not os.path.exists(DB_PATH): return []
    conn = get_connection()
    c = conn.cursor()
    if media_type == 'movie':
        # ✅ ADAUGAT: overview la SELECT
        c.execute("SELECT *, last_watched_at as date, overview FROM trakt_watched_movies ORDER BY last_watched_at DESC LIMIT 100")
    else:
        # --- MODIFICARE: JOIN cu tv_meta pentru a lua overview-ul serialului ---
        c.execute("""
            SELECT e.*, m.overview, m.poster as poster, m.backdrop as backdrop, MAX(e.last_watched_at) as date 
            FROM trakt_watched_episodes e 
            LEFT JOIN tv_meta m ON e.tmdb_id = m.tmdb_id 
            GROUP BY e.tmdb_id 
            ORDER BY MAX(e.last_watched_at) DESC LIMIT 100
        """)
        
    items = [dict(row) for row in c.fetchall()]
    conn.close()
    return items

def get_lists_from_db():
    if not os.path.exists(DB_PATH): return []
    conn = get_connection()
    c = conn.cursor()
    
    # --- ASIGURARE COLOANE (MIGRARE ON-THE-FLY) ---
    try:
        c.execute("SELECT poster, backdrop FROM user_lists LIMIT 1")
    except:
        try: c.execute("ALTER TABLE user_lists ADD COLUMN poster TEXT")
        except: pass
        try: c.execute("ALTER TABLE user_lists ADD COLUMN backdrop TEXT")
        except: pass
        conn.commit()
    try:
        c.execute("SELECT poster_tmdb_id FROM user_lists LIMIT 1")
    except:
        try: c.execute("ALTER TABLE user_lists ADD COLUMN poster_tmdb_id TEXT")
        except: pass
        conn.commit()

    c.execute("SELECT * FROM user_lists ORDER BY name")
    data = [dict(row) for row in c.fetchall()]
    
    # --- IDENTIFICARE LISTE CARE AU NEVOIE DE FETCH ---
    fetch_tasks = []  # (slug, current_first_id, m_type)
    list_map = {}     # slug -> row dict
    
    res = []
    for r in data:
        slug = r['slug']
        list_map[slug] = r
        poster = r.get('poster')
        backdrop = r.get('backdrop')
        poster_tmdb_id = r.get('poster_tmdb_id', '')
        
        c.execute("SELECT media_type, tmdb_id FROM user_list_items WHERE list_slug=? ORDER BY added_at DESC LIMIT 1", (slug,))
        item = c.fetchone()
        needs_api = False
        if item:
            current_first_id = item[1]
            r['_first_id'] = current_first_id
            r['_first_type'] = 'movie' if item[0] == 'movie' else 'tv'
            r['_needs_update'] = not poster or not backdrop or current_first_id != poster_tmdb_id
            if r['_needs_update']:
                meta = get_tmdb_item_details_from_db(current_first_id, r['_first_type'])
                if not meta:
                    needs_api = True
                    fetch_tasks.append((slug, current_first_id, r['_first_type']))
                else:
                    r['_cached_meta'] = meta
        else:
            r['_first_id'] = None
            r['_needs_update'] = False
    
    # --- FETCH PARALEL PENTRU METADATELE LIPSA ---
    if fetch_tasks:
        def fetch_worker(slug, tid, mtype):
            from resources.lib.utils import get_json
            url = f"{BASE_URL}/{mtype}/{tid}?api_key={API_KEY}&language={LANG}"
            meta = get_json(url)
            if meta:
                conn2 = get_connection()
                set_tmdb_item_details_to_db(conn2.cursor(), tid, mtype, meta)
                conn2.commit()
                conn2.close()
            return slug, meta
        
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(fetch_worker, slug, tid, mtype): slug for slug, tid, mtype in fetch_tasks}
            for future in as_completed(futures):
                slug, meta = future.result()
                if meta:
                    list_map[slug]['_cached_meta'] = meta
    
    # --- CONSTRUIRE REZULTATE ---
    updates = []
    for r in data:
        slug = r['slug']
        poster = r.get('poster')
        backdrop = r.get('backdrop')
        poster_tmdb_id = r.get('poster_tmdb_id', '')
        
        if r.get('_needs_update') and r.get('_first_id'):
            meta = r.get('_cached_meta')
            if meta:
                if meta.get('poster_path'):
                    poster = meta['poster_path']
                if meta.get('backdrop_path'):
                    backdrop = meta['backdrop_path']
                if poster or backdrop:
                    updates.append((poster, backdrop, r['_first_id'], slug))
        
        icon = 'trakt.png'
        fanart = ''
        
        if poster:
            if poster.startswith('http'): icon = poster
            else: icon = f"https://image.tmdb.org/t/p/w300{poster}"
            
        if backdrop:
            if backdrop.startswith('http'): fanart = backdrop
            else: fanart = f"https://image.tmdb.org/t/p/w1280{backdrop}"

        res.append({
            'name': r['name'],
            'ids': {'slug': slug, 'trakt': r['trakt_id']},
            'item_count': r['item_count'],
            'description': r.get('description', ''),
            'icon': icon,
            'fanart': fanart
        })
        
    if updates:
        for p, b, tid, s in updates:
            c.execute("UPDATE user_lists SET poster=?, backdrop=?, poster_tmdb_id=? WHERE slug=?", (p, b, tid, s))
        conn.commit()
        
    conn.close()
    return res

def get_trakt_user_list_items_from_db(slug):
    if not os.path.exists(DB_PATH): return []
    conn = get_connection()
    c = conn.cursor()
    # MODIFICAT: ORDER BY added_at DESC
    c.execute("SELECT * FROM user_list_items WHERE list_slug=? ORDER BY added_at DESC", (slug,))
    items = [dict(row) for row in c.fetchall()]
    conn.close()
    return items

def get_in_progress_movies_from_db():
    if not os.path.exists(DB_PATH): return []
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM playback_progress WHERE media_type='movie' ORDER BY paused_at DESC")
    items = [dict(row) for row in c.fetchall()]
    conn.close()
    return items

def get_in_progress_tvshows_from_db():
    if not os.path.exists(DB_PATH): return []
    conn = get_connection()
    c = conn.cursor()
    
    # 1. Am marit LIMIT la 500 pentru ca niciun serial sa nu fie taiat prematur.
    # 2. Am modificat COUNT(*) in SUM(CASE WHEN e.season > 0) pentru a ignora 
    #    episoadele speciale (Season 0) care dadeau matematica peste cap.
    c.execute("""
        SELECT e.tmdb_id, 
               MAX(e.title) as show_title, 
               SUM(CASE WHEN e.season > 0 THEN 1 ELSE 0 END) as watched_count, 
               m.total_episodes,
               MAX(e.last_watched_at) as last_watched
        FROM trakt_watched_episodes e
        LEFT JOIN tv_meta m ON e.tmdb_id = m.tmdb_id
        WHERE e.tmdb_id NOT IN (SELECT tmdb_id FROM trakt_hidden_shows)
        GROUP BY e.tmdb_id
        HAVING (m.total_episodes IS NULL OR m.total_episodes = 0)
               OR (SUM(CASE WHEN e.season > 0 THEN 1 ELSE 0 END) < m.total_episodes)
        ORDER BY last_watched DESC
        LIMIT 500
    """)
    
    result = []
    for r in c.fetchall():
        title = r['show_title'] or 'Unknown Show'
        poster = get_poster_from_db(r['tmdb_id'], 'tv')
        
        watched = r['watched_count'] if r['watched_count'] else 0
        total = r['total_episodes'] if r['total_episodes'] else 0
        
        result.append({
            'id': str(r['tmdb_id']),
            'tmdb_id': str(r['tmdb_id']),
            'name': title,
            'title': title, 
            'watched_eps': int(watched),
            'total_eps': int(total),
            'first_air_date': '', 
            'poster_path': poster
        })
    conn.close()
    return result

def get_in_progress_episodes_from_db():
    if not os.path.exists(DB_PATH): return []
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM playback_progress WHERE media_type='episode' ORDER BY paused_at DESC")
    items = [dict(row) for row in c.fetchall()]
    conn.close()
    return items

def get_tmdb_from_db(action, page):
    if not os.path.exists(DB_PATH): 
        # ✅ Daca DB nu exista, il cream
        init_database()
        return None
    
    conn = get_connection()
    c = conn.cursor()
    
    # ✅ Verificam daca tabelul exista
    try:
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tmdb_discovery'")
        if not c.fetchone():
            conn.close()
            init_database()
            return None
    except:
        conn.close()
        init_database()
        return None
    
    c.execute("SELECT * FROM tmdb_discovery WHERE action=? AND page=? ORDER BY rank", (action, page))
    items = [dict(row) for row in c.fetchall()]
    conn.close()
    
    res = []
    for r in items:
        res.append({
            'id': r['tmdb_id'],
            'title': r['title'],
            'name': r['title'],
            'poster_path': r['poster'],
            'overview': r['overview'],
            'release_date': r['year'] + '-01-01',
            'first_air_date': r['year'] + '-01-01'
        })
    return res if res else None



# --- IMAGE CACHE & META HELPERS ---

def get_tv_meta_from_db(tmdb_id):
    if not os.path.exists(DB_PATH): return 0
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT total_episodes FROM tv_meta WHERE tmdb_id=?", (str(tmdb_id),))
    row = c.fetchone()
    conn.close()
    return row['total_episodes'] if row else 0

def set_tv_meta_to_db(tmdb_id, total_episodes):
    conn = get_connection()
    c = conn.cursor()
    try:
        # --- MODIFICARE: Folosim UPDATE pentru a nu sterge overview/poster daca exista deja ---
        c.execute("UPDATE tv_meta SET total_episodes=? WHERE tmdb_id=?", (int(total_episodes), str(tmdb_id)))
        
        # Daca randul nu exista (rowcount e 0), abia atunci facem INSERT
        if c.rowcount == 0:
             c.execute("INSERT INTO tv_meta (tmdb_id, total_episodes) VALUES (?, ?)", 
                       (str(tmdb_id), int(total_episodes)))
        
        conn.commit()
    except: pass
    conn.close()

def warm_tv_meta_cache_from_db():
    """Pre-populeaza TV_META_CACHE dict cu toate intrarile din tv_meta.
    Cheama o data la startup pentru a evita SQLite reads in get_watched_status_tvshow."""
    try:
        from resources.lib.tmdb_api import TV_META_CACHE
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT tmdb_id, total_episodes FROM tv_meta")
        for row in c.fetchall():
            TV_META_CACHE[str(row[0])] = row[1]
        conn.close()
    except:
        pass

def get_poster_from_db(tmdb_id, media_type):
    conn = get_connection()
    c = conn.cursor()
    tables = ['discovery_cache', 'trakt_lists', 'trakt_watched_movies', 'tmdb_discovery']
    
    for tbl in tables:
        try:
            if tbl == 'trakt_watched_movies':
                if media_type == 'movie':
                    c.execute(f"SELECT poster FROM {tbl} WHERE tmdb_id=? AND poster IS NOT NULL AND poster != ''", (str(tmdb_id),))
                else: continue
            elif tbl == 'tmdb_discovery':
                c.execute(f"SELECT poster FROM {tbl} WHERE tmdb_id=? AND poster IS NOT NULL AND poster != ''", (str(tmdb_id),))
            else:
                c.execute(f"SELECT poster FROM {tbl} WHERE tmdb_id=? AND media_type=? AND poster IS NOT NULL AND poster != ''", (str(tmdb_id), media_type))
            
            row = c.fetchone()
            if row and row['poster']:
                conn.close()
                return row['poster']
        except: pass
    conn.close()
    return None

def set_poster_to_db(tmdb_id, media_type, poster_url):
    pass 

def update_item_images(c, tmdb_id, media_type, poster, backdrop):
    """Update imagini folosind cursorul existent (sau conexiune noua daca c e None)."""
    if not tmdb_id: return
    
    conn_local = None
    if c is None:
        try:
            conn_local = sqlite3.connect(DB_PATH, timeout=20)
            c = conn_local.cursor()
        except: return

    try:
        # Mapare tip media pt tabelele Trakt
        m_type = 'movie' if media_type in ['movie', 'movies'] else 'show'
        
        if m_type == 'movie':
            c.execute("UPDATE trakt_watched_movies SET poster=?, backdrop=? WHERE tmdb_id=?", (poster, backdrop, tmdb_id))
        
        c.execute("UPDATE trakt_lists SET poster=?, backdrop=? WHERE tmdb_id=? AND media_type=?", (poster, backdrop, tmdb_id, m_type))
        c.execute("UPDATE user_list_items SET poster=?, backdrop=? WHERE tmdb_id=? AND media_type=?", (poster, backdrop, tmdb_id, m_type))
        c.execute("UPDATE discovery_cache SET poster=?, backdrop=? WHERE tmdb_id=? AND media_type=?", (poster, backdrop, tmdb_id, m_type))
        c.execute("UPDATE tmdb_discovery SET poster=? WHERE tmdb_id=?", (poster, tmdb_id))
        
        if conn_local: conn_local.commit()
    except: pass
    finally:
        if conn_local: conn_local.close()

def get_tmdb_account_list_from_db(list_type, media_type):
    """Returneaza Watchlist sau Favorites din SQL sortate."""
    if not os.path.exists(DB_PATH): return []
    conn = get_connection()
    c = conn.cursor()
    # --- MODIFICARE: Sortare DESC dupa data adaugarii ---
    c.execute("SELECT * FROM tmdb_account_lists WHERE list_type=? AND media_type=? ORDER BY added_at DESC", (list_type, media_type))
    items = [dict(row) for row in c.fetchall()]
    conn.close()
    
    res = []
    for r in items:
        res.append({
            'id': r['tmdb_id'],
            'title': r['title'],
            'name': r['title'],
            'year': r['year'],
            'poster_path': r['poster'],
            # --- MODIFICARE: Returnam si overview ---
            'overview': r.get('overview', ''),
            'release_date': r['year'] + '-01-01',
            'first_air_date': r['year'] + '-01-01'
        })
    return res

def get_tmdb_watchlist_for_calendar():
    """Returneaza filme+serialele din watchlist TMDb cu datele reale pentru My Calendar."""
    if not os.path.exists(DB_PATH): return []
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT * FROM tmdb_account_lists WHERE list_type='watchlist' ORDER BY added_at DESC")
        items = [dict(row) for row in c.fetchall()]
    except:
        items = []
    conn.close()
    
    res = []
    for r in items:
        if r.get('media_type') not in ('movie', 'tv'): continue
        date_str = r.get('release_date') or r.get('first_air_date') or ''
        res.append({
            'media_type': r.get('media_type'),
            'tmdb_id': str(r['tmdb_id']),
            'title': r.get('title', ''),
            'year': r.get('year', ''),
            'poster': r.get('poster', ''),
            'overview': r.get('overview', ''),
            'date': date_str
        })
    return res

def get_tmdb_custom_lists_from_db():
    """Returneaza lista listelor personale TMDb."""
    if not os.path.exists(DB_PATH): return []
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM tmdb_custom_lists ORDER BY name")
    items = [dict(row) for row in c.fetchall()]
    conn.close()
    
    # ✅ Returnam toate campurile inclusiv description
    return items

def get_tmdb_custom_list_items_from_db(list_id):
    if not os.path.exists(DB_PATH): return []
    conn = get_connection()
    c = conn.cursor()
    # MODIFICAT: Sortare dupa sort_index ASC (respecta ordinea de pe site)
    c.execute("SELECT * FROM tmdb_custom_list_items WHERE list_id=? ORDER BY sort_index ASC", (str(list_id),))
    items = [dict(row) for row in c.fetchall()]
    conn.close()
    
    res = []
    for r in items:
        res.append({
            'id': r['tmdb_id'],
            'media_type': r['media_type'],
            'title': r['title'],
            'name': r['title'],
            'year': r['year'],
            'poster_path': r['poster'],
            'overview': r['overview'],
            'release_date': r['year'] + '-01-01',
            'first_air_date': r['year'] + '-01-01'
        })
    return res

def get_recommendations_from_db(media_type):
    if not os.path.exists(DB_PATH): return []
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM tmdb_recommendations WHERE media_type=?", (media_type,))
    items = [dict(row) for row in c.fetchall()]
    conn.close()
    
    res = []
    for r in items:
        res.append({
            'id': r['tmdb_id'],
            'title': r['title'],
            'name': r['title'],
            'poster_path': r['poster'],
            'overview': r['overview']
        })
    return res

def is_in_tmdb_account_list(list_type, media_type, tmdb_id):
    if not os.path.exists(DB_PATH): return False
    # Normalizam: 'episode'/'season'/'show'/'tvshow' → 'tv' (randurile in DB sunt 'tv'/'movie')
    media_type = 'tv' if media_type in ('tv', 'tvshow', 'episode', 'season', 'show') else 'movie'
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT 1 FROM tmdb_account_lists WHERE list_type=? AND media_type=? AND tmdb_id=?", (list_type, media_type, str(tmdb_id)))
    found = c.fetchone()
    conn.close()
    return found is not None

def is_in_tmdb_custom_list(list_id, tmdb_id):
    if not os.path.exists(DB_PATH): return False
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT 1 FROM tmdb_custom_list_items WHERE list_id=? AND tmdb_id=?", (str(list_id), str(tmdb_id)))
    found = c.fetchone()
    conn.close()
    return found is not None

# =============================================================================
# METADATA CACHE (JSON STORAGE) - PENTRU NAVIGARE RAPIDA IN SERIALE
# =============================================================================

def get_tmdb_item_details_from_db(tmdb_id, media_type):
    if not os.path.exists(DB_PATH): return None
    
    current_time = int(time.time())
    conn = get_connection()
    c = conn.cursor()
    
    # Selectam datele (care acum pot fi BLOB comprimat)
    c.execute("SELECT data, expires FROM meta_cache_items WHERE tmdb_id=? AND media_type=?", (str(tmdb_id), media_type))
    row = c.fetchone()
    conn.close()
    
    if row:
        data_blob, expires = row
        if current_time > expires:
            return None
        try:
            # Incercam decompresia. Daca e text vechi, va da eroare si trecem la except
            if isinstance(data_blob, bytes):
                decompressed = zlib.decompress(data_blob)
                return json.loads(decompressed)
            else:
                return json.loads(data_blob) # Compatibilitate veche
        except:
            return None
    return None

def set_tmdb_item_details_to_db(cursor, tmdb_id, media_type, data):
    if not data: return
    expires = int(time.time() + (7 * 86400)) # 7 zile
    
    try:
        json_str = json.dumps(data)
        # COMPRIMARE AICI
        compressed_data = zlib.compress(json_str.encode('utf-8'))
        
        should_close = False
        if cursor is None:
            conn = get_connection()
            cursor = conn.cursor()
            should_close = True
            
        cursor.execute("INSERT OR REPLACE INTO meta_cache_items VALUES (?,?,?,?)", 
                       (str(tmdb_id), media_type, compressed_data, expires))
        
        if should_close:
            cursor.connection.commit()
            cursor.connection.close()
    except: pass

def get_tmdb_season_details_from_db(tmdb_id, season_num):
    """Citeste detaliile sezonului (episoade) din cache cu decompresie zlib."""
    if not os.path.exists(DB_PATH): return None
    
    current_time = int(time.time())
    conn = get_connection()
    c = conn.cursor()
    
    try:
        c.execute("SELECT data, expires FROM meta_cache_seasons WHERE tmdb_id=? AND season_num=?", (str(tmdb_id), int(season_num)))
        row = c.fetchone()
        
        if row:
            data_blob, expires = row
            # Verificam expirarea
            if current_time > expires:
                return None
            
            try:
                # Incercam decompresia (pentru date noi comprimate)
                if isinstance(data_blob, bytes):
                    return json.loads(zlib.decompress(data_blob))
                # Fallback pentru date vechi (string)
                return json.loads(data_blob)
            except:
                return None
    except:
        pass
    finally:
        conn.close()
        
    return None

def set_tmdb_season_details_to_db(cursor, tmdb_id, season_num, data):
    """Salveaza detaliile sezonului comprimate cu zlib."""
    if not data: return
    
    expires = int(time.time() + (7 * 86400)) # 7 zile
    
    json_str = json.dumps(data)
    compressed_data = zlib.compress(json_str.encode('utf-8'))
    
    should_close = False
    if cursor is None:
        conn = get_connection()
        cursor = conn.cursor()
        should_close = True
    
    for attempt in range(12):
        try:
            cursor.execute("INSERT OR REPLACE INTO meta_cache_seasons VALUES (?,?,?,?)", 
                           (str(tmdb_id), int(season_num), compressed_data, expires))
            if should_close:
                cursor.connection.commit()
                cursor.connection.close()
            return
        except Exception as e:
            if 'database is locked' in str(e) and attempt < 11:
                time.sleep(0.5 * (attempt + 1) + 0.2)
                if should_close:
                    try: cursor.connection.close()
                    except: pass
                    conn = get_connection()
                    cursor = conn.cursor()
            else:
                log(f"[CACHE] Error saving season: {e}", xbmc.LOGERROR)
                if should_close:
                    try: cursor.connection.close()
                    except: pass
                return

def update_playback_title(tmdb_id, season, episode, new_title):
    """Actualizeaza titlul unui episod in progres."""
    if not tmdb_id: return
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("UPDATE playback_progress SET title=? WHERE tmdb_id=? AND season=? AND episode=?", 
                  (new_title, str(tmdb_id), int(season), int(episode)))
        conn.commit()
    except: pass
    conn.close()

# =============================================================================
# WATCHED STATUS CHECKERS (CITIRE DIN SQL)
# =============================================================================

def is_movie_watched(tmdb_id):
    """Verifica daca un film e marcat ca vizionat in Trakt."""
    if not os.path.exists(DB_PATH): return False
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT 1 FROM trakt_watched_movies WHERE tmdb_id=?", (str(tmdb_id),))
    found = c.fetchone()
    conn.close()
    return found is not None

def get_movie_watched_count(tmdb_id):
    """Returneaza 1 daca filmul e vizionat, 0 altfel."""
    return 1 if is_movie_watched(tmdb_id) else 0

def get_episode_watched_count(tmdb_id, season=None):
    """Numara episoadele vizionate pentru un serial/sezon."""
    if not os.path.exists(DB_PATH): return 0
    conn = get_connection()
    c = conn.cursor()
    
    if season is not None:
        c.execute("SELECT COUNT(*) FROM trakt_watched_episodes WHERE tmdb_id=? AND season=?", 
                  (str(tmdb_id), int(season)))
    else:
        c.execute("SELECT COUNT(*) FROM trakt_watched_episodes WHERE tmdb_id=?", (str(tmdb_id),))
    
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def is_episode_watched(tmdb_id, season, episode):
    """Verifica daca un episod specific e vizionat."""
    if not os.path.exists(DB_PATH): return False
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT 1 FROM trakt_watched_episodes WHERE tmdb_id=? AND season=? AND episode=?", 
              (str(tmdb_id), int(season), int(episode)))
    found = c.fetchone()
    conn.close()
    return found is not None

# =============================================================================
# WATCHED STATUS CHECKERS (CITIRE DIRECTA DIN SQL)
# =============================================================================

def is_movie_watched_sql(tmdb_id):
    """Verifica daca un film e marcat ca vizionat in SQL."""
    if not os.path.exists(DB_PATH): 
        return False
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT 1 FROM trakt_watched_movies WHERE tmdb_id=?", (str(tmdb_id),))
        found = c.fetchone()
        conn.close()
        return found is not None
    except:
        return False

def get_watched_episode_count_sql(tmdb_id, season=None):
    """Numara episoadele vizionate pentru un serial/sezon din SQL."""
    if not os.path.exists(DB_PATH): 
        return 0
    try:
        conn = get_connection()
        c = conn.cursor()
        
        if season is not None:
            c.execute("SELECT COUNT(*) FROM trakt_watched_episodes WHERE tmdb_id=? AND season=?", 
                      (str(tmdb_id), int(season)))
        else:
            c.execute("SELECT COUNT(*) FROM trakt_watched_episodes WHERE tmdb_id=?", (str(tmdb_id),))
        
        row = c.fetchone()
        conn.close()
        return row[0] if row else 0
    except:
        return 0

def is_episode_watched_sql(tmdb_id, season, episode):
    """Verifica daca un episod specific e vizionat in SQL."""
    if not os.path.exists(DB_PATH): 
        return False
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT 1 FROM trakt_watched_episodes WHERE tmdb_id=? AND season=? AND episode=?", 
                  (str(tmdb_id), int(season), int(episode)))
        found = c.fetchone()
        conn.close()
        return found is not None
    except:
        return False

def is_show_hidden(tmdb_id):
    """Verifica instant in baza locala daca serialul este marcat ca dropped/hidden."""
    if not os.path.exists(DB_PATH): 
        return False
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT 1 FROM trakt_hidden_shows WHERE tmdb_id=?", (str(tmdb_id),))
        found = c.fetchone()
        conn.close()
        return found is not None
    except:
        return False

def cleanup_database():
    if not os.path.exists(DB_PATH): return

    current_time = int(time.time())
    
    try:
        conn = get_connection()
        c = conn.cursor()
        
        # 1. Sterge expiirate
        c.execute("DELETE FROM meta_cache_items WHERE expires < ?", (current_time,))
        c.execute("DELETE FROM meta_cache_seasons WHERE expires < ?", (current_time,))
        
        c.execute("""DELETE FROM meta_cache_items WHERE tmdb_id NOT IN (
            SELECT tmdb_id FROM meta_cache_items ORDER BY expires DESC LIMIT 200
        )""")
        
        c.execute("""DELETE FROM meta_cache_seasons WHERE tmdb_id NOT IN (
            SELECT tmdb_id FROM meta_cache_seasons ORDER BY expires DESC LIMIT 300
        )""")

        conn.commit()
        
        # 3. VACUUM OBLIGATORIU
        # SQLite nu micsoreaza fisierul fizic fara VACUUM
        conn.execute("VACUUM")
        
        conn.close()
    except Exception as e:
        log(f"[CLEANUP] Error: {e}", xbmc.LOGERROR)


# =============================================================================
# PLAYBACK PROGRESS (LOCAL & SYNC) - ADAUGAT PENTRU RESUME FIX
# =============================================================================
def get_local_playback_progress(tmdb_id, content_type, season=None, episode=None):
    """
    Returneaza progresul (%) din baza de date locala pentru un singur item.
    Folosita de Player pentru a afisa dialogul de Resume.
    """
    if not os.path.exists(DB_PATH): return 0
    
    try:
        conn = get_connection()
        c = conn.cursor()
        
        if content_type == 'movie':
            c.execute("SELECT progress FROM playback_progress WHERE tmdb_id=? AND media_type='movie'", (str(tmdb_id),))
        else:
            c.execute("SELECT progress FROM playback_progress WHERE tmdb_id=? AND season=? AND episode=?", 
                      (str(tmdb_id), int(season), int(episode)))
            
        row = c.fetchone()
        conn.close()
        
        if row and row['progress']:
            return float(row['progress'])
    except: pass
    return 0

def remove_local_progress(tmdb_id, content_type='movie', season=None, episode=None):
    """Sterge randurile de resume din tabela locala playback_progress (provider-independent)."""
    try:
        conn = get_connection()
        c = conn.cursor()
        if content_type == 'movie':
            c.execute("DELETE FROM playback_progress WHERE tmdb_id=? AND media_type='movie'", (str(tmdb_id),))
        else:
            if season is not None and episode is not None:
                c.execute("DELETE FROM playback_progress WHERE tmdb_id=? AND media_type='episode' AND season=? AND episode=?",
                          (str(tmdb_id), int(season), int(episode)))
            elif season is not None:
                c.execute("DELETE FROM playback_progress WHERE tmdb_id=? AND media_type='episode' AND season=?",
                          (str(tmdb_id), int(season)))
            else:
                c.execute("DELETE FROM playback_progress WHERE tmdb_id=?", (str(tmdb_id),))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        log(f"[TRAKT SYNC] remove_local_progress error: {e}", xbmc.LOGERROR)
        return False

def get_local_playback_progress_batch(tmdb_id, content_type, season):
    """Fetch ALL episode progress for a season in one query. Returns dict {ep_num: progress}."""
    result = {}
    if not os.path.exists(DB_PATH):
        return result
    try:
        conn = get_connection()
        c = conn.cursor()
        if content_type == 'movie':
            c.execute("SELECT episode, progress FROM playback_progress WHERE tmdb_id=? AND media_type='movie'", (str(tmdb_id),))
        else:
            c.execute("SELECT episode, progress FROM playback_progress WHERE tmdb_id=? AND season=? AND media_type='episode'",
                      (str(tmdb_id), int(season)))
        for row in c.fetchall():
            result[int(row['episode'])] = float(row['progress'])
        conn.close()
    except:
        pass
    return result

def update_local_playback_progress(tmdb_id, content_type, season, episode, progress, title, year):
    """
    Salveaza sau sterge progresul local.
    progress = Procent (0-100)
    """
    try:
        conn = get_connection()
        c = conn.cursor()
        now = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000Z")
        
        media_type = 'movie' if content_type == 'movie' else 'episode'
        s_val = int(season) if season else 0
        e_val = int(episode) if episode else 0
        
        # 1. Stergem intrarea veche
        _db_exec_retry(c, "DELETE FROM playback_progress WHERE tmdb_id=? AND media_type=? AND season=? AND episode=?",
                  (str(tmdb_id), media_type, s_val, e_val))
        
        # ============================================================
        # 2. Salvam DOAR daca e sub 90% (altfel e watched) SAU daca e timp exact
        # ============================================================
        if progress >= 1000000:
            # E timp exact! Il salvam ca atare
            _db_exec_retry(c, """INSERT INTO playback_progress
                         (tmdb_id, media_type, season, episode, progress, paused_at, title, year, poster)
                         VALUES (?,?,?,?,?,?,?,?,?)""",
                      (str(tmdb_id), media_type, s_val, e_val, progress, now, title, str(year), ''))
            log(f"[TRAKT SYNC] ✓ Local exact-time progress SAVED: {int(progress - 1000000)}s for {title}")
        elif progress < 90:
            # E procentaj standard (ex: descarcat direct de pe Trakt la o sincronizare)
            _db_exec_retry(c, """INSERT INTO playback_progress
                         (tmdb_id, media_type, season, episode, progress, paused_at, title, year, poster)
                         VALUES (?,?,?,?,?,?,?,?,?)""",
                      (str(tmdb_id), media_type, s_val, e_val, progress, now, title, str(year), ''))
            log(f"[TRAKT SYNC] ✓ Local percentage progress SAVED: {progress:.2f}% for {title}")
        else:
            log(f"[TRAKT SYNC] Progress {progress:.2f}% >= 90%. Removed from In Progress.")
        # ============================================================
        
        _db_commit_retry(conn)
        try: conn.close()
        except: pass
        
        # --- MODIFICARE: CURATAM RAM CACHE ---
        # Daca progresul s-a schimbat, cache-ul RAM nu mai e valabil
        from resources.lib.cache import clear_all_fast_cache
        clear_all_fast_cache()
        # -------------------------------------
        
    except Exception as e:
        log(f"[TRAKT SYNC] Error saving local progress: {e}", xbmc.LOGERROR)
        
        
def get_plot_in_language(tmdb_id, media_type, lang=None):
    """Preia plotul intr-o limba specifica."""
    from resources.lib.config import API_KEY, BASE_URL, get_plot_language
    if lang is None:
        lang = get_plot_language()
    endpoint = 'movie' if media_type == 'movie' else 'tv'
    url = f"{BASE_URL}/{endpoint}/{tmdb_id}?api_key={API_KEY}&language={lang}"
    
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            return r.json().get('overview', '')
    except:
        pass
    return ''


# ===================== NEW WORKERS (THREADED) =====================

def fetch_single_show_progress(item):
    """Worker pentru Up Next: ruleaza in paralel DOAR apeluri de retea (fara DB)."""
    from resources.lib import trakt_api
    import requests
    
    show = item.get('show', {})
    trakt_id = show.get('ids', {}).get('trakt')
    tmdb_id = str(show.get('ids', {}).get('tmdb', ''))
    last_watched = item.get('last_watched_at', '')
    
    if not trakt_id or not tmdb_id or tmdb_id == 'None':
        return None

    # Cerem progresul de la Trakt (API Call)
    try:
        progress = trakt_api.trakt_api_request(f"/shows/{trakt_id}/progress/watched")
    except:
        return None
    
    if progress and progress.get('next_episode'):
        next_ep = progress['next_episode']
        air_date = next_ep.get('first_aired', '')
        if air_date: air_date = air_date.split('T')[0]

        # Returnam datele FARA poster din DB. Posterul va fi rezolvat in firul principal.
        return {
            'tmdb_id': tmdb_id,
            'show_title': show.get('title'),
            'season': next_ep.get('season'),
            'episode': next_ep.get('number'),
            'ep_title': next_ep.get('title'),
            'overview': next_ep.get('overview'),
            'last_watched': last_watched,
            'air_date': air_date
        }
    return None


def fetch_up_next_worker(args):
    item, token, trakt_client_id, tmdb_api_key = args
    
    show = item.get('show', {})
    trakt_id = show.get('ids', {}).get('trakt')
    tmdb_id = str(show.get('ids', {}).get('tmdb', ''))
    last_watched = item.get('last_watched_at', '')
    
    # FIX: Excludem clonele de pe Trakt care nu au TMDb ID valid
    if not trakt_id or not tmdb_id or tmdb_id == 'None': 
        return None

    headers = {'Content-Type': 'application/json', 'trakt-api-version': '2', 'trakt-api-key': trakt_client_id, 'Authorization': f'Bearer {token}'}
    
    try:
        # Request Trakt
        url = f"https://api.trakt.tv/shows/{trakt_id}/progress/watched"
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code != 200: return None
        prog = r.json()
        
        if prog and prog.get('next_episode'):
            nxt = prog['next_episode']
            
            # Fix-ul pentru split (sa nu moara sync-ul)
            air_date = nxt.get('first_aired', '')
            if air_date: air_date = air_date.split('T')[0]
            
            # Request TMDb (poster + validare an)
            poster = ''
            tmdb_url = f"https://api.themoviedb.org/3/tv/{tmdb_id}?api_key={tmdb_api_key}"
            r2 = requests.get(tmdb_url, timeout=3)
            if r2.status_code == 200:
                tmdb_data = r2.json()
                poster = tmdb_data.get('poster_path', '')
                
                # --- VALIDARE: verificam daca anul show-ului TMDB corespunde cu episodul ---
                tmdb_first_air = tmdb_data.get('first_air_date', '')
                if tmdb_first_air and air_date:
                    tmdb_year_s = tmdb_first_air[:4]
                    ep_year_s = air_date[:4]
                    if tmdb_year_s.isdigit() and ep_year_s.isdigit():
                        tmdb_year = int(tmdb_year_s)
                        ep_year = int(ep_year_s)
                        if abs(tmdb_year - ep_year) > 3:
                            show_title = show.get('title', '')
                            if show_title:
                                try:
                                    search_url = "https://api.themoviedb.org/3/search/tv"
                                    r3 = requests.get(search_url, params={'api_key': tmdb_api_key, 'query': show_title}, timeout=5)
                                    if r3.status_code == 200:
                                        def _norm_name(s):
                                            return ''.join(ch.lower() for ch in str(s) if ch.isalnum())
                                        search_norm = _norm_name(show_title)
                                        for result in r3.json().get('results', []):
                                            result_first_air = result.get('first_air_date', '')
                                            if result_first_air and result_first_air[:4] == ep_year_s:
                                                result_norm = _norm_name(result.get('name', ''))
                                                if not (result_norm == search_norm or result_norm in search_norm or search_norm in result_norm):
                                                    continue
                                                new_id = str(result['id'])
                                                try:
                                                    check_url = f"https://api.themoviedb.org/3/tv/{new_id}/season/{nxt['season']}/episode/{nxt['number']}?api_key={tmdb_api_key}"
                                                    rc = requests.get(check_url, timeout=5)
                                                    if rc.status_code != 200:
                                                        continue
                                                except:
                                                    continue
                                                log(f"[UP NEXT] Corectat tmdb_id {tmdb_id} -> {new_id} pentru '{show_title}' (first_air {tmdb_year} != ep {ep_year})")
                                                tmdb_id = new_id
                                                poster = result.get('poster_path', '') or poster
                                                break
                                except:
                                    pass

            return (tmdb_id, show.get('title'), nxt['season'], nxt['number'], nxt['title'], nxt['overview'], last_watched, poster, air_date)
    except: pass
    return None

# =============================================================================
# HIDDEN SHOWS HELPERS (NOU)
# =============================================================================

def _get_hidden_show_ids():
    """
    Preia serialele ascunse din Calendar SI Progress pe Trakt.
    Pagineaza rezultatele corect (limita oficiala Trakt e 100).
    """
    from resources.lib import trakt_api
    
    hidden = {'tmdb': set(), 'trakt': set(), 'imdb': set(), 'tvdb': set()}
    
    for section in ('calendar', 'progress_watched', 'dropped'):
        try:
            page = 1
            while True:
                # FIX: Trakt suporta maxim 100 per pagina
                result = trakt_api.trakt_api_request(
                    f'/users/hidden/{section}',
                    params={'type': 'show', 'limit': 100, 'page': page}
                )
                if not result or not isinstance(result, list):
                    break
                    
                for item in result:
                    ids = item.get('show', {}).get('ids', {})
                    for key in hidden:
                        val = ids.get(key)
                        if val:
                            hidden[key].add(str(val))
                            
                # Daca primim sub 100, inseamna ca asta e ultima pagina
                if len(result) < 100:
                    break
                page += 1
        except Exception as e:
            from resources.lib.utils import log
            import xbmc
            log(f"[TRAKT SYNC] Error fetching hidden/{section}: {e}", xbmc.LOGWARNING)
    
    total = len(hidden['tmdb'])
    if total > 0:
        from resources.lib.utils import log
        log(f"[TRAKT SYNC] Hidden shows complete: {total} shows found")
    
    return hidden

def _sync_hidden_shows(c):
    """Sincronizeaza serialele ascunse in DB local pentru filtrare ultra-rapida."""
    hidden_ids = _get_hidden_show_ids()
    c.execute("DELETE FROM trakt_hidden_shows")
    rows = [(tid,) for tid in hidden_ids['tmdb'] if tid]
    if rows:
        c.executemany("INSERT OR REPLACE INTO trakt_hidden_shows VALUES (?)", rows)
        log(f"[TRAKT SYNC] Saved {len(rows)} hidden shows in local database.")


def _is_show_hidden(show_ids, hidden):
    """Verifica daca un serial e in lista hidden. Compara strict per tip de ID."""
    if not hidden:
        return False
    for key in ('tmdb', 'trakt', 'imdb', 'tvdb'):
        val = show_ids.get(key)
        if val and str(val) in hidden.get(key, set()):
            return True
    return False


def _sync_up_next(c, token):
    """Coordoneaza thread-urile si salveaza totul la final. FILTREAZA hidden/dropped."""
    from resources.lib import trakt_api
    from resources.lib.config import TRAKT_CLIENT_ID, API_KEY

    sync_start = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000Z")

    watched = trakt_api._get_trakt_paginated_list("/sync/watched/shows", params={'extended': 'progress'})
    if not watched:
        watched = []
    
    # ══════════════════════════════════════════════════════════
    # ADAUGAT: Filtrare seriale hidden/dropped INAINTE de procesare
    # Preia din /users/hidden/calendar + /users/hidden/progress_watched
    # ══════════════════════════════════════════════════════════
    try:
        hidden = _get_hidden_show_ids()
        if any(s for s in hidden.values()):
            before_count = len(watched)
            watched = [
                item for item in watched
                if not _is_show_hidden(item.get('show', {}).get('ids', {}), hidden)
            ]
            removed = before_count - len(watched)
            if removed > 0:
                log(f"[TRAKT SYNC] Up Next: {removed} hidden/dropped shows removed "
                    f"from {before_count} total.")
    except Exception as e:
        log(f"[TRAKT SYNC] Up Next: Error filtering hidden: {e}", xbmc.LOGWARNING)
        # Continuam fara filtrare daca esueaza
    # ══════════════════════════════════════════════════════════
    
    # Sortam dupa ultima vizionare
    watched.sort(key=lambda x: x.get('last_watched_at', ''), reverse=True)
    top_shows = watched[:500]
    
    worker_args = [(item, token, TRAKT_CLIENT_ID, API_KEY) for item in top_shows]

    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(fetch_up_next_worker, worker_args))

    clean_rows = [r for r in results if r]
    # Normalizam la 10 coloane (watched_count) - fetch_up_next_worker are 9
    # Folosim conexiune separata pentru COUNT ca sa nu tinem write-lock pe c in timpul fetch-urilor
    norm_rows = []
    try:
        _cnt_conn = get_connection()
        _cnt_cur = _cnt_conn.cursor()
        for r in clean_rows:
            if len(r) == 9:
                try:
                    _cnt_cur.execute("SELECT COUNT(*) FROM trakt_watched_episodes WHERE tmdb_id=?", (str(r[0]),))
                    wc = _cnt_cur.fetchone()[0] or 1
                except:
                    wc = 1
                norm_rows.append(tuple(list(r) + [int(wc)]))
            elif len(r) == 10:
                norm_rows.append(r)
        _cnt_conn.close()
    except:
        try: _cnt_conn.close()
        except: pass
        norm_rows = [tuple(list(r) + [1]) if len(r) == 9 else tuple(r[:10]) for r in clean_rows]
    clean_rows = norm_rows
    
    # === UNSTARTED WATCHLIST (trakt_lists watchlist/show cu watched_count==0) la coada Up Next ===
    # Colectam candidatii cu conexiune separata (read-only) ca sa nu blocam write-lock-ul lui c
    wl_rows = []
    _wl_cands = []
    try:
        _wl_conn = get_connection()
        _wl_cur = _wl_conn.cursor()
        _wl_cur.execute("SELECT tmdb_id, title FROM trakt_lists WHERE list_type='watchlist' AND media_type='show'")
        wl_rows = _wl_cur.fetchall() or []
        if wl_rows:
            try:
                _wl_cur.execute("SELECT tmdb_id FROM trakt_hidden_shows")
                hidden_ids = {str(row[0]) for row in _wl_cur.fetchall()}
            except:
                hidden_ids = set()
            existing_ids = {str(r[0]) for r in clean_rows}
            for row in wl_rows:
                tid = str(row[0])
                if not tid or tid in existing_ids or tid in hidden_ids:
                    continue
                try:
                    _wl_cur.execute("SELECT COUNT(*) FROM trakt_watched_episodes WHERE tmdb_id=?", (tid,))
                    if (_wl_cur.fetchone()[0] or 0) > 0:
                        continue
                except:
                    continue
                _wl_cands.append((tid, row[1] or 'Unknown Show'))
        _wl_conn.close()
        cands = list(_wl_cands)
        if cands:
            from resources.lib import tmdb_api as _tmdb_api
            from concurrent.futures import ThreadPoolExecutor as _TPE, as_completed as _ac
            def _fetch_unstarted(entry):
                tid, title = entry
                try:
                    sd = _tmdb_api.get_tmdb_item_details(tid, 'tv', lightweight=True, skip_localization=True)
                    if not sd:
                        return None
                    nxt = _tmdb_first_episode(sd)
                    if not nxt:
                        return None
                    ep_title, ep_overview, air_date = _tmdb_ep_meta(tid, nxt['season'], nxt['number'])
                    poster = get_poster_from_db(tid, 'show') or sd.get('poster_path', '')
                    return (tid, title or sd.get('name','Unknown Show'), nxt['season'], nxt['number'], ep_title, ep_overview, '', poster, air_date, 0)
                except:
                    return None
            with _TPE(max_workers=5) as ex:
                futs = {ex.submit(_fetch_unstarted, e): e for e in cands}
                for f in _ac(futs):
                    res = f.result()
                    if res:
                        clean_rows.append(res)
    except Exception as e:
        log(f"[TRAKT SYNC] Up Next unstarted watchlist error: {e}", xbmc.LOGWARNING)
    
    # --- Scriere atomica scurta (eliberam lock-ul cat mai repede) ---
    try:
        _db_exec_retry(c, "DELETE FROM trakt_next_episodes WHERE tmdb_id NOT IN "
                  "(SELECT tmdb_id FROM trakt_watched_episodes WHERE last_watched_at >= ?)",
                  (sync_start,))
    except Exception as e:
        log(f"[TRAKT SYNC] Up Next delete error: {e}", xbmc.LOGWARNING)
    # Curatam si intrarile neincepute vechi care nu mai sunt in watchlist (sterse de pe site)
    try:
        if wl_rows is not None:
            _wl_ids = {str(r[0]) for r in (wl_rows or [])}
            # stergem doar randurile cu watched_count==0 care nu mai sunt in watchlist
            try:
                c.execute("SELECT tmdb_id, watched_count FROM trakt_next_episodes")
                _old_rows = c.fetchall()
            except:
                # DB vechi fara watched_count
                c.execute("SELECT tmdb_id FROM trakt_next_episodes")
                _old_rows = [(r[0], 1) for r in c.fetchall()]
            for row in _old_rows:
                try:
                    if int(row[1] or 0) == 0 and str(row[0]) not in _wl_ids:
                        _db_exec_retry(c, "DELETE FROM trakt_next_episodes WHERE tmdb_id=?", (str(row[0]),))
                except:
                    pass
    except:
        pass
    if clean_rows:
        try:
            _insert_trakt_next_batch(c, clean_rows)
        except Exception as e:
            log(f"[TRAKT SYNC] Up Next insert error: {e}", xbmc.LOGERROR)
        
        # Salvare postere bulk
        for row in clean_rows:
            if row[7]:  # daca are poster
                update_item_images(c, row[0], 'show', row[7], '')
    
        _db_commit_retry(c.connection)
        log(f"[TRAKT SYNC] Up Next: {len(clean_rows)} seriale actualizate "
        f"(din {len(top_shows)} verificate, {len(watched)} dupa filtrare).")
    else:
        _db_commit_retry(c.connection)
        log(f"[TRAKT SYNC] Up Next: 0 seriale (toate filtrate/dropped).")
    
    # Pre-cache season details for instant Next Episodes display
    if clean_rows:
        def _precache_next_episodes():
            try:
                from resources.lib.tmdb_api import get_smart_season_details
                from concurrent.futures import ThreadPoolExecutor, as_completed
                tmdb_ids = [(row[0], row[2]) for row in clean_rows]
                with ThreadPoolExecutor(max_workers=5) as executor:
                    futures = {executor.submit(get_smart_season_details, tid, sn): (tid, sn) for tid, sn in tmdb_ids}
                    for f in as_completed(futures):
                        pass
                log(f"[TRAKT SYNC] Pre-cached {len(tmdb_ids)} season details for Next Episodes")
            except Exception as e:
                log(f"[TRAKT SYNC] Pre-cache error: {e}")
        import threading
        threading.Thread(target=_precache_next_episodes, daemon=True).start()

def _sync_trakt_favorites(c):
    """Sincronizeaza Favoritele Trakt (inimioara)."""
    from resources.lib import trakt_api
    
    data = trakt_api.trakt_api_request("/users/me/favorites", params={'extended': 'full,images'})
    if not data or not isinstance(data, list): return

    c.execute("DELETE FROM trakt_favorites")
    rows = []
    for i, item in enumerate(data):
        m_type = item.get('type') # 'movie' sau 'show'
        raw = item.get(m_type)
        if not raw: continue
        
        tmdb_id = str(raw.get('ids', {}).get('tmdb', ''))
        if not tmdb_id: continue
        
        poster_path = ''
        try:
            imgs = (raw.get('images') or {})
            p_urls = imgs.get('poster') or []
            if p_urls and isinstance(p_urls, list) and p_urls[0] and 'image.tmdb.org' in str(p_urls[0]):
                poster_path = '/' + str(p_urls[0]).split('/')[-1].split('?')[0]
        except:
            pass
        rows.append((m_type, tmdb_id, raw.get('title'), str(raw.get('year', '')), poster_path, raw.get('overview', ''), i))
    
    if rows:
        c.executemany("INSERT OR REPLACE INTO trakt_favorites VALUES (?,?,?,?,?,?,?)", rows)
        log(f"[TRAKT SYNC] Saved {len(rows)} Trakt favorites.")

def get_next_episodes_from_db():
    if not os.path.exists(DB_PATH): 
        init_database()
        return []
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM trakt_next_episodes ORDER BY last_watched_at DESC")
        items = [dict(row) for row in c.fetchall()]
        conn.close()
        return items
    except Exception as e:
        from resources.lib.utils import log
        import xbmc
        log(f"[DB] Error reading trakt_next_episodes: {e}. Re-initializing...", xbmc.LOGERROR)
        init_database()
        return []

def get_tmdb_next_episodes_from_db():
    """Toate serialele Up Next TMDB din DB local (watchlist TMDb + progres provider activ)."""
    if not os.path.exists(DB_PATH): 
        init_database()
        return []
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM tmdb_next_episodes ORDER BY last_watched_at DESC")
        items = [dict(row) for row in c.fetchall()]
        conn.close()
        return items
    except Exception as e:
        from resources.lib.utils import log
        import xbmc
        log(f"[DB] Error reading tmdb_next_episodes: {e}. Re-initializing...", xbmc.LOGERROR)
        init_database()
        return []

def get_trakt_favorites_from_db(media_type):
    if not os.path.exists(DB_PATH): 
        init_database()
        return []
    try:
        conn = get_connection()
        c = conn.cursor()
        db_type = 'movie' if media_type == 'movies' else 'show'
        # MODIFICAT: ORDER BY rank DESC (rank-ul e timestamp-ul adaugarii la inserarea manuala)
        c.execute("SELECT * FROM trakt_favorites WHERE media_type=? ORDER BY rank DESC", (db_type,))
        items = [dict(row) for row in c.fetchall()]
        conn.close()
        return items
    except Exception as e:
        from resources.lib.utils import log
        import xbmc
        log(f"[DB] Error reading trakt_favorites: {e}. Re-initializing...", xbmc.LOGERROR)
        init_database()
        return []

# ===================== WATCHED STATUS WORKERS =====================

def sync_single_watched_to_trakt(tmdb_id, content_type, season=None, episode=None):
    from resources.lib import trakt_api
    from resources.lib.tmdb_api import get_trakt_id
    import datetime
    
    try: tid_int = int(tmdb_id)
    except: return 

    now_str = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
    
    # FORTAM TRAKT ID PENTRU SERIALE (Prevenim erorile pe site-ul lor)
    ids_dict = {'tmdb': tid_int}
    if content_type != 'movie':
        trakt_id = get_trakt_id(None, tmdb_id, 'show')
        if trakt_id: ids_dict['trakt'] = int(trakt_id)

    if content_type == 'movie':
        data = {'movies':[{'ids': ids_dict, 'watched_at': now_str}]}
    elif content_type in ['tv', 'show'] and season is None:
        data = {'shows':[{'ids': ids_dict, 'watched_at': now_str}]}
    elif season is not None and episode is None: # MARCARE TOT SEZONUL
        try: s_val = int(season)
        except: return
        data = {'shows':[{'ids': ids_dict, 'seasons':[{'number': s_val, 'watched_at': now_str}]}]}
    else: # MARCARE EPISOD
        try:
            s_val = int(season)
            e_val = int(episode)
        except: return
        data = {'shows':[{'ids': ids_dict, 'seasons':[{'number': s_val, 'episodes':[{'number': e_val, 'watched_at': now_str}]}]}]}
        
    trakt_api.trakt_api_request("/sync/history", method='POST', data=data)

def sync_single_unwatched_to_trakt(tmdb_id, content_type, season=None, episode=None):
    from resources.lib import trakt_api
    from resources.lib.tmdb_api import get_trakt_id
    
    try: tid_int = int(tmdb_id)
    except: return

    # FORTAM TRAKT ID PENTRU SERIALE 
    ids_dict = {'tmdb': tid_int}
    if content_type != 'movie':
        trakt_id = get_trakt_id(None, tmdb_id, 'show')
        if trakt_id: ids_dict['trakt'] = int(trakt_id)

    if content_type == 'movie':
        data = {'movies':[{'ids': ids_dict}]}
    elif content_type in['tv', 'show'] and season is None:
        data = {'shows': [{'ids': ids_dict}]}
    elif season is not None and episode is None: # DE-MARCARE TOT SEZONUL
        try: s_val = int(season)
        except: return
        data = {'shows':[{'ids': ids_dict, 'seasons':[{'number': s_val}]}]}
    else: # DE-MARCARE EPISOD
        try:
            s_val = int(season)
            e_val = int(episode)
        except: return
        data = {'shows':[{'ids': ids_dict, 'seasons':[{'number': s_val, 'episodes': [{'number': e_val}]}]}]}
        
    trakt_api.trakt_api_request("/sync/history/remove", method='POST', data=data)

def mark_as_watched_internal(tmdb_id, content_type, season=None, episode=None, notify=True, sync_trakt=True, refresh_ui=True):
    from resources.lib import tmdb_api
    from resources.lib.config import IMG_BASE, BACKDROP_BASE, ADDON
    import threading

    TRAKT_ICON = os.path.join(ADDON.getAddonInfo('path'), 'resources', 'media', 'trakt.png')
    tid = str(tmdb_id)
    conn = get_connection()
    c = conn.cursor()
    now = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000Z")
    
    title_val = "Unknown" 
    poster_val = ""
    backdrop_val = ""
    overview_val = ""

    # 1. PRELUARE METADATE (FIX 'season' ADDED)
    try:
        if content_type == 'movie':
            details = tmdb_api.get_tmdb_item_details(tid, 'movie') or {}
            title_val = details.get('title', 'Unknown Movie')
            poster_val = f"{IMG_BASE}{details.get('poster_path', '')}" if details.get('poster_path') else ""
            backdrop_val = f"{BACKDROP_BASE}{details.get('backdrop_path', '')}" if details.get('backdrop_path') else ""
            overview_val = details.get('overview', '')
        
        elif content_type in['tv', 'episode', 'show', 'season']:
            show_details = tmdb_api.get_tmdb_item_details(tid, 'tv') or {}
            show_name = show_details.get('name', 'Unknown Show')
            poster_val = f"{IMG_BASE}{show_details.get('poster_path', '')}" if show_details.get('poster_path') else ""
            backdrop_val = f"{BACKDROP_BASE}{show_details.get('backdrop_path', '')}" if show_details.get('backdrop_path') else ""
            overview_val = show_details.get('overview', '')
            
            if season is not None and episode is not None:
                title_val = f"{show_name} - S{int(season):02d}E{int(episode):02d}"
            elif season is not None and episode is None:
                title_val = f"{show_name} - Sezonul {season}"
            else:
                title_val = show_name
    except: 
        pass

    try:
        # 2. INSERARE IN SQL LOCAL
        if content_type == 'movie':
            c.execute("INSERT OR REPLACE INTO trakt_watched_movies VALUES (?,?,?,?,?,?,?)", 
                      (tid, title_val, str(now)[:4], now, poster_val, backdrop_val, overview_val))
            c.execute("DELETE FROM playback_progress WHERE tmdb_id=? AND media_type='movie'", (tid,))
        
        elif season is not None and episode is not None:
            db_show_title = show_name if 'show_name' in locals() else "Unknown Show"
            c.execute("INSERT OR REPLACE INTO trakt_watched_episodes VALUES (?,?,?,?,?)",
                      (tid, int(season), int(episode), db_show_title, now))
            try:
                _mt = int((show_details or {}).get('number_of_episodes') or 0)
            except:
                _mt = 0
            if _mt > 0:
                c.execute("INSERT OR REPLACE INTO tv_meta (tmdb_id, total_episodes, poster, backdrop, overview) VALUES (?,?,?,?,?)",
                          (tid, _mt, poster_val, backdrop_val, overview_val))
            else:
                c.execute("SELECT 1 FROM tv_meta WHERE tmdb_id=?", (tid,))
                if not c.fetchone():
                    c.execute("INSERT OR REPLACE INTO tv_meta (tmdb_id, total_episodes, poster, backdrop, overview) VALUES (?,?,?,?,?)",
                              (tid, 0, poster_val, backdrop_val, overview_val))
            try:
                from resources.lib.tmdb_api import TV_META_CACHE as _TMC
                if _mt > 0:
                    _TMC[tid] = _mt
                elif tid in _TMC:
                    del _TMC[tid]
            except:
                pass
            c.execute("DELETE FROM playback_progress WHERE tmdb_id=? AND season=? AND episode=?", (tid, int(season), int(episode)))

        elif season is not None and episode is None:
            db_show_title = show_name if 'show_name' in locals() else "Unknown Show"
            show_data = tmdb_api.get_tmdb_item_details(tid, 'tv')
            if show_data:
                rows_to_insert =[]
                for s in show_data.get('seasons',[]):
                    if str(s.get('season_number')) == str(season):
                        ep_count = s.get('episode_count', 0)
                        if ep_count > 0:
                            for ep_num in range(1, ep_count + 1):
                                rows_to_insert.append((tid, int(season), ep_num, db_show_title, now))
                        break
                if rows_to_insert:
                    c.executemany("INSERT OR REPLACE INTO trakt_watched_episodes VALUES (?,?,?,?,?)", rows_to_insert)
                c.execute("SELECT 1 FROM tv_meta WHERE tmdb_id=?", (tid,))
                if not c.fetchone():
                    c.execute("INSERT OR REPLACE INTO tv_meta (tmdb_id, total_episodes, poster, backdrop, overview) VALUES (?,?,?,?,?)", 
                              (tid, show_data.get('number_of_episodes', 0), poster_val, backdrop_val, overview_val))
                c.execute("DELETE FROM playback_progress WHERE tmdb_id=? AND season=?", (tid, int(season)))

        elif content_type in['tv', 'show']:
            show_data = tmdb_api.get_tmdb_item_details(tid, 'tv')
            if show_data:
                rows_to_insert =[]
                clean_name = show_data.get('name', 'Unknown Show')
                for s in show_data.get('seasons',[]):
                    s_num = s.get('season_number')
                    ep_count = s.get('episode_count', 0)
                    if s_num is None or ep_count == 0: continue
                    for ep_num in range(1, ep_count + 1):
                        rows_to_insert.append((tid, s_num, ep_num, clean_name, now))
                if rows_to_insert:
                    c.executemany("INSERT OR REPLACE INTO trakt_watched_episodes VALUES (?,?,?,?,?)", rows_to_insert)
                c.execute("INSERT OR REPLACE INTO tv_meta (tmdb_id, total_episodes, poster, backdrop, overview) VALUES (?,?,?,?,?)", 
                          (tid, show_data.get('number_of_episodes', 0), poster_val, backdrop_val, overview_val))
                c.execute("DELETE FROM playback_progress WHERE tmdb_id=?", (tid,))

        conn.commit()
    except: pass
    finally: conn.close()

    # 2b. STERGERE DIN WATCHLIST LOCAL
    try:
        if content_type == 'movie' or content_type in ['tv', 'show'] and season is None:
            conn = get_connection()
            c = conn.cursor()
            if content_type == 'movie':
                c.execute("DELETE FROM trakt_lists WHERE list_type='watchlist' AND media_type='movie' AND tmdb_id=?", (tid,))
            else:
                c.execute("DELETE FROM trakt_lists WHERE list_type='watchlist' AND media_type='show' AND tmdb_id=?", (tid,))
            conn.commit()
            conn.close()
    except: pass

    # 3. NOTIFICARE SI REFRESH UP NEXT
    if notify:
        msg = f"[B][COLOR yellow]{title_val}[/COLOR][/B] marked watched on [B][COLOR pink]Trakt[/COLOR][/B]"
        xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", msg, TRAKT_ICON, 3000, False)
    
    if sync_trakt:
        threading.Thread(target=sync_single_watched_to_trakt, args=(tmdb_id, content_type, season, episode), daemon=True).start()
    
    if content_type in ['tv', 'show', 'season', 'episode'] or season is not None:
            try:
                # Rulam asincron in fundal. Cand primeste datele TMDB, va rescrie baza si va da auto-refresh.
                threading.Thread(target=refresh_next_episode, args=(tmdb_id,), daemon=True).start()
            except: pass
            
    # --- START KODI LIBRARY HACK (INSTANT) ---
    try:
        # Folosim tmdb_id in loc de year_val pentru o precizie de 100%
        threading.Thread(target=update_kodi_library_watchstatus, args=(content_type, 'mark_as_watched', title_val, tmdb_id, season, episode), daemon=True).start()
    except: pass
    # --- END KODI LIBRARY HACK ---
    
    from resources.lib.cache import clear_all_fast_cache
    clear_all_fast_cache()
    
    if refresh_ui:
        xbmc.executebuiltin("Container.Refresh")


def mark_as_unwatched_internal(tmdb_id, content_type, season=None, episode=None, notify=True, sync_trakt=True, refresh_ui=True):
    import threading
    from resources.lib.config import ADDON
    
    TRAKT_ICON = os.path.join(ADDON.getAddonInfo('path'), 'resources', 'media', 'trakt.png')
    tid = str(tmdb_id)
    conn = get_connection()
    c = conn.cursor()
    
    title_display = "Element"

    try:
        # 1. EXTRAGERE TITLU (Pentru notificare, inainte de stergere)
        if content_type == 'movie':
            c.execute("SELECT title FROM trakt_watched_movies WHERE tmdb_id=?", (tid,))
            r = c.fetchone()
            if r: title_display = r[0]
        elif season is not None and episode is not None:
            c.execute("SELECT title FROM trakt_watched_episodes WHERE tmdb_id=? LIMIT 1", (tid,))
            r = c.fetchone()
            if r: 
                base_title = r[0].split(' - S')[0] 
                title_display = f"{base_title} - S{int(season):02d}E{int(episode):02d}"
            else:
                title_display = f"S{season}E{episode}"
        elif season is not None and episode is None:
            c.execute("SELECT title FROM trakt_watched_episodes WHERE tmdb_id=? LIMIT 1", (tid,))
            r = c.fetchone()
            if r:
                base_title = r[0].split(' - S')[0]
                title_display = f"{base_title} - Sezonul {season}"
            else:
                # FALLBACK LA TMDB API
                from resources.lib import tmdb_api
                show_details = tmdb_api.get_tmdb_item_details(tid, 'tv') or {}
                show_name = show_details.get('name', 'Serial')
                title_display = f"{show_name} - Sezonul {season}"
        elif content_type in ['tv', 'show']:
            c.execute("SELECT title FROM trakt_watched_episodes WHERE tmdb_id=? LIMIT 1", (tid,))
            r = c.fetchone()
            if r: 
                title_display = r[0].split(' - S')[0]
            else:
                title_display = "Serial"

        # 2. STERGERE EFECTIVA SQL
        if content_type == 'movie':
            c.execute("DELETE FROM trakt_watched_movies WHERE tmdb_id=?", (tid,))
            c.execute("DELETE FROM playback_progress WHERE tmdb_id=? AND media_type='movie'", (tid,))
        elif season is not None and episode is not None:
            c.execute("DELETE FROM trakt_watched_episodes WHERE tmdb_id=? AND season=? AND episode=?", (tid, int(season), int(episode)))
            c.execute("DELETE FROM playback_progress WHERE tmdb_id=? AND season=? AND episode=?", (tid, int(season), int(episode)))
        elif season is not None and episode is None:
            c.execute("DELETE FROM trakt_watched_episodes WHERE tmdb_id=? AND season=?", (tid, int(season)))
            c.execute("DELETE FROM playback_progress WHERE tmdb_id=? AND season=?", (tid, int(season)))
        elif content_type in ['tv', 'show']:
            c.execute("DELETE FROM trakt_watched_episodes WHERE tmdb_id=?", (tid,))
            c.execute("DELETE FROM playback_progress WHERE tmdb_id=?", (tid,))

        conn.commit()
    except: pass
    finally: conn.close()

    # 3. RECALCULARE UP NEXT (Fara a sterge orbeste serialul)
    if content_type in ['tv', 'show', 'season', 'episode'] or season is not None:
        try:
            # Rulam asincron in fundal. Cand primeste datele TMDB, va rescrie baza si va da auto-refresh.
            threading.Thread(target=refresh_next_episode, args=(tmdb_id,), daemon=True).start()
        except: pass

    # 4. NOTIFICARE SI SYNC TRAKT
    msg = f"[B][COLOR yellow]{title_display}[/COLOR][/B] marked unwatched on [B][COLOR pink]Trakt[/COLOR][/B]"
    if notify:
        xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", msg, TRAKT_ICON, 3000, False)

    if sync_trakt:
        threading.Thread(target=sync_single_unwatched_to_trakt, args=(tmdb_id, content_type, season, episode), daemon=True).start()

    # --- START KODI LIBRARY HACK (INSTANT) ---
    try:
        # Folosim tmdb_id in loc de year_val pentru o precizie de 100%
        threading.Thread(target=update_kodi_library_watchstatus, args=(content_type, 'mark_as_unwatched', title_display, tmdb_id, season, episode), daemon=True).start()
    except: pass
    # --- END KODI LIBRARY HACK ---

    from resources.lib.cache import clear_all_fast_cache
    clear_all_fast_cache()

    if refresh_ui:
        xbmc.executebuiltin("Container.Refresh")


def refresh_next_episode(tmdb_id, ignore_hidden=False):
    from resources.lib import tmdb_api
    import datetime
    
    tmdb_id = str(tmdb_id)
    log(f"[UP NEXT] Calculating next LOCAL episode for TMDb {tmdb_id}...")
    
    def _trigger_ui_refresh():
        try:
            import xbmc
            container_path = xbmc.getInfoLabel('Container.FolderPath')
            if not container_path or 'plugin.video.tmdbmovies' in container_path.lower():
                xbmc.executebuiltin("Container.Refresh")
        except: pass
        
    try:
        # 1. Luam detaliile serialului (din cache-ul local TMDb, este instant)
        show_details = tmdb_api.get_tmdb_item_details(tmdb_id, 'tv')
        if not show_details:
            return
            
        show_title = show_details.get('name', 'Unknown Show')
        
        # 2. Verificam daca e ascuns/dropped (100% Local, 0 API Calls)
        if not ignore_hidden:
            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT 1 FROM trakt_hidden_shows WHERE tmdb_id=?", (tmdb_id,))
            is_hidden = c.fetchone()
            conn.close()
            
            if is_hidden:
                log(f"[UP NEXT] '{show_title}' is hidden (dropped). Removing from UI.")
                conn = get_connection()
                try:
                    _db_exec_retry(conn, "DELETE FROM trakt_next_episodes WHERE tmdb_id=?", (tmdb_id,))
                    _db_commit_retry(conn)
                except:
                    pass
                try: conn.close()
                except: pass
                from resources.lib.cache import clear_all_fast_cache
                clear_all_fast_cache()
                _trigger_ui_refresh()
                return
        
        # 3. Citim istoricul EXACT vizionat local + ultimul episod vizionat cronologic
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT season, episode FROM trakt_watched_episodes WHERE tmdb_id=?", (tmdb_id,))
        watched_eps = set((r['season'], r['episode']) for r in c.fetchall())
        c.execute("SELECT season, episode FROM trakt_watched_episodes WHERE tmdb_id=? ORDER BY last_watched_at DESC LIMIT 1", (tmdb_id,))
        last_row = c.fetchone()
        conn.close()
        
        # --- Daca nu mai avem niciun episod vizionat: daca e in watchlist neinceput, apare S1E1; altfel iese
        if not watched_eps:
            try:
                c2 = get_connection().cursor()
                c2.execute("SELECT 1 FROM trakt_lists WHERE list_type='watchlist' AND media_type='show' AND tmdb_id=?", (tmdb_id,))
                in_wl = bool(c2.fetchone())
                c2.connection.close()
            except:
                in_wl = False
            if in_wl and not is_hidden:
                next_ep = _tmdb_first_episode(show_details)
                if next_ep:
                    season_data = tmdb_api.get_smart_season_details(tmdb_id, next_ep['season'])
                    ep_title = ''; ep_overview=''; air_date=''
                    if season_data:
                        for ep in season_data.get('episodes',[]) or []:
                            if ep.get('episode_number')==next_ep['number']:
                                ep_title=ep.get('name',''); ep_overview=ep.get('overview',''); air_date=str(ep.get('air_date','')).split('T')[0]; break
                    poster = get_poster_from_db(tmdb_id,'show') or show_details.get('poster_path','')
                    now_str = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
                    conn2 = get_connection(); c2 = conn2.cursor()
                    _insert_trakt_next_one(c2, (tmdb_id,show_title,next_ep['season'],next_ep['number'],ep_title,ep_overview,now_str,poster,air_date,0))
                    _db_commit_retry(conn2); conn2.close()
                    from resources.lib.cache import clear_all_fast_cache
                    clear_all_fast_cache(); _trigger_ui_refresh()
                    return
            log(f"[UP NEXT] '{show_title}' no longer has watched episodes. Removing from UI.")
            conn = get_connection()
            try:
                _db_exec_retry(conn, "DELETE FROM trakt_next_episodes WHERE tmdb_id=?", (tmdb_id,))
                _db_commit_retry(conn)
            except:
                pass
            try: conn.close()
            except: pass
            from resources.lib.cache import clear_all_fast_cache
            clear_all_fast_cache()
            _trigger_ui_refresh()
            return
        # ---
        
        # 4. Cautam urmatorul episod nevizionat DUPA ultimul vizionat cronologic
        next_ep = None
        if last_row:
            last_s, last_e = last_row['season'], last_row['episode']
            for s in show_details.get('seasons', []):
                s_num = s.get('season_number')
                if s_num == 0 or s_num < last_s: continue
                ep_count = s.get('episode_count', 0)
                start_ep = (last_e + 1) if s_num == last_s else 1
                for e_num in range(start_ep, ep_count + 1):
                    if (s_num, e_num) not in watched_eps:
                        next_ep = {'season': s_num, 'number': e_num}
                        break
                if next_ep:
                    break
        
        # 4b. Fallback: daca n-am gasit nimic dupa ultimul vizionat (ex: gap de episoade demarcate),
        #     scanam de la inceput
        if not next_ep:
            for s in show_details.get('seasons', []):
                s_num = s.get('season_number')
                if s_num == 0: continue
                ep_count = s.get('episode_count', 0)
                for e_num in range(1, ep_count + 1):
                    if (s_num, e_num) not in watched_eps:
                        next_ep = {'season': s_num, 'number': e_num}
                        break
                if next_ep:
                    break
                
        # 5. Daca nu am gasit nimic, serialul s-a terminat
        if not next_ep:
            log(f"[UP NEXT] '{show_title}' complete. Removing from UI.")
            conn = get_connection()
            try:
                _db_exec_retry(conn, "DELETE FROM trakt_next_episodes WHERE tmdb_id=?", (tmdb_id,))
                _db_commit_retry(conn)
            except:
                pass
            try: conn.close()
            except: pass
            from resources.lib.cache import clear_all_fast_cache
            clear_all_fast_cache()
            _trigger_ui_refresh()
            return

        # 6. Luam metadatele noului episod (din cache TMDb)
        season_data = tmdb_api.get_smart_season_details(tmdb_id, next_ep['season'])
        ep_title = ''
        ep_overview = ''
        air_date = ''
        
        if season_data:
            for ep in season_data.get('episodes', []):
                if ep.get('episode_number') == next_ep['number']:
                    ep_title = ep.get('name', '')
                    ep_overview = ep.get('overview', '')
                    air_date_raw = ep.get('air_date', '')
                    if air_date_raw:
                        air_date = air_date_raw.split('T')[0]
                    break

        # 7. Poster
        poster = get_poster_from_db(tmdb_id, 'show') or show_details.get('poster_path', '')

        # 8. Salvam noul episod calculat direct in DB-ul local
        now_str = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")

        conn = get_connection()
        c = conn.cursor()
        try:
            c.execute("SELECT COUNT(*) FROM trakt_watched_episodes WHERE tmdb_id=?", (tmdb_id,))
            wc = c.fetchone()[0] or 0
        except:
            wc = len(watched_eps)
        _insert_trakt_next_one(c, (tmdb_id, show_title, next_ep['season'], next_ep['number'],
                 ep_title, ep_overview, now_str, poster, air_date, int(wc)))
        _db_commit_retry(conn)
        conn.close()
        
        log(f"[UP NEXT] ✓ {show_title} updated INSTANT and LOCAL to -> S{next_ep['season']:02d}E{next_ep['number']:02d}")
        
        from resources.lib.cache import clear_all_fast_cache
        clear_all_fast_cache()
        
        _trigger_ui_refresh()

    except Exception as e:
        log(f"[UP NEXT] Error calculating local episode: {e}", xbmc.LOGERROR)


# =============================================================================
# TMDB UP NEXT (watchlist TMDb + progresul providerului activ de watched status)
# =============================================================================
def _tmdb_next_episode_scan(show_details, watched_set, watched_last):
    next_ep = None
    if watched_last:
        last_s, last_e = watched_last
        for s in show_details.get('seasons', []):
            s_num = s.get('season_number')
            if s_num == 0 or s_num < last_s:
                continue
            ep_count = s.get('episode_count', 0)
            start_ep = (last_e + 1) if s_num == last_s else 1
            for e_num in range(start_ep, ep_count + 1):
                if (s_num, e_num) not in watched_set:
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
                if (s_num, e_num) not in watched_set:
                    next_ep = {'season': s_num, 'number': e_num}
                    break
            if next_ep:
                break
    return next_ep


def _tmdb_next_to_air(show_details):
    """Episodul urmator programat pentru serialele neincepute (next_episode_to_air)."""
    try:
        nxt = (show_details or {}).get('next_episode_to_air') or {}
        if not nxt:
            return None
        s = int(nxt.get('season_number') or 0)
        e = int(nxt.get('episode_number') or 0)
        if s <= 0 or e <= 0:
            return None
        return {'season': s, 'number': e}
    except Exception:
        return None


def _tmdb_first_episode(show_details):
    try:
        seasons = (show_details or {}).get('seasons') or []
        for s in seasons:
            if int(s.get('season_number') or 0) == 1 and int(s.get('episode_count') or 0) >= 1:
                return {'season': 1, 'number': 1}
    except Exception:
        pass
    return _tmdb_next_to_air(show_details)


def _tmdb_ep_meta(tmdb_id, season, episode):
    """Metadatele episodului (nume localizat, overview, air_date) din sezoanele TMDb."""
    from resources.lib.tmdb_api import get_smart_season_details
    ep_title, ep_overview, air_date = '', '', ''
    try:
        season_data = get_smart_season_details(tmdb_id, season)
        if season_data:
            for ep in season_data.get('episodes', []):
                if ep.get('episode_number') == episode:
                    ep_title = ep.get('name', '')
                    ep_overview = ep.get('overview', '')
                    air_date_raw = ep.get('air_date', '')
                    if air_date_raw:
                        air_date = air_date_raw.split('T')[0]
                    break
    except Exception:
        pass
    return ep_title, ep_overview, air_date


def sync_tmdb_up_next(c):
    import datetime
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from resources.lib.watched_provider import get_watched_episodes_set_batch, _get_provider_raw, get_source_module
    from resources.lib import tmdb_api

    t0 = time.time()
    try:
        c.execute("SELECT tmdb_id, title, poster, overview FROM tmdb_account_lists "
                  "WHERE list_type='watchlist' AND media_type='tv' ORDER BY added_at DESC")
        wl_rows = c.fetchall()
        wl_ids = {str(r['tmdb_id']) for r in wl_rows}

        pool_ids = []
        try:
            prov = _get_provider_raw()
            prov_tbl = {'trakt': 'trakt_next_episodes',
                        'mdblist': 'mdblist_next_episodes',
                        'simkl': 'simkl_next_episodes'}.get(prov)
            if prov_tbl:
                pconn = get_source_module().get_connection()
                pcur = pconn.cursor()
                pcur.execute("SELECT DISTINCT tmdb_id FROM %s" % prov_tbl)
                raw_pool = [str(r[0]) for r in pcur.fetchall()]
                pconn.close()
                pool_ids = [tid for tid in raw_pool if tid not in wl_ids]
        except Exception as e:
            log(f"[TMDB SYNC] Up Next pool extension error: {e}", xbmc.LOGERROR)
            pool_ids = []

        all_tids = list(wl_ids) + pool_ids
        if not all_tids:
            c.execute("DELETE FROM tmdb_next_episodes")
            log(f"[TMDB SYNC] Up Next: 0 seriale (watchlist TMDb + pool {_get_provider_raw()}).")
            try:
                from resources.lib.cache import clear_all_fast_cache
                clear_all_fast_cache()
            except:
                pass
            return

        watched_map = get_watched_episodes_set_batch(all_tids)

        show_map = {}
        def _fetch_show(tid):
            try:
                skip = tid in wl_ids
                return tid, tmdb_api.get_tmdb_item_details(tid, 'tv', lightweight=True, skip_localization=skip)
            except:
                return tid, None

        t_show_start = time.time()
        with ThreadPoolExecutor(max_workers=10) as ex:
            futures = {ex.submit(_fetch_show, tid): tid for tid in all_tids}
            for f in as_completed(futures):
                tid, data = f.result()
                if data:
                    show_map[tid] = data
        log(f"[TMDB SYNC] Up Next show_details: {len(show_map)}/{len(all_tids)} in {time.time() - t_show_start:.1f}s (10 workers, lightweight, wl EN-only, pool localized)")

        pending = []
        for row in wl_rows:
            tid = str(row['tmdb_id'])
            show_details = show_map.get(tid)
            if not show_details:
                continue
            w = watched_map.get(tid) or {'set': set(), 'last': None, 'last_at': ''}
            if w['set']:
                next_ep = _tmdb_next_episode_scan(show_details, w['set'], w['last'])
            else:
                next_ep = _tmdb_first_episode(show_details)
            if not next_ep:
                continue
            pending.append({
                'tid': tid,
                'show_title': row['title'] or 'Unknown Show',
                'poster': row['poster'] or '',
                'overview': row['overview'] or '',
                'w': w,
                'next_ep': next_ep,
                'is_pool': False,
                'show_details': show_details
            })

        for tid in pool_ids:
            show_details = show_map.get(tid)
            if not show_details:
                continue
            w = watched_map.get(tid) or {'set': set(), 'last': None, 'last_at': ''}
            if not w['set']:
                continue
            next_ep = _tmdb_next_episode_scan(show_details, w['set'], w['last'])
            if not next_ep:
                continue
            pending.append({
                'tid': tid,
                'show_title': show_details.get('name', 'Unknown Show'),
                'poster': get_poster_from_db(tid, 'show') or show_details.get('poster_path', ''),
                'overview': '',
                'w': w,
                'next_ep': next_ep,
                'is_pool': True,
                'show_details': show_details
            })

        t_season_start = time.time()
        def _fetch_meta(entry):
            try:
                tid = entry['tid']
                s = entry['next_ep']['season']
                e = entry['next_ep']['number']
                ep_title, ep_overview, air_date = _tmdb_ep_meta(tid, s, e)
                return entry, ep_title, ep_overview, air_date
            except:
                return entry, '', '', ''

        with ThreadPoolExecutor(max_workers=10) as ex:
            futures = {ex.submit(_fetch_meta, entry): entry for entry in pending}
            season_results = []
            for f in as_completed(futures):
                season_results.append(f.result())

        clean_rows = []
        now_str = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
        for entry, ep_title, ep_overview, air_date in season_results:
            w = entry['w']
            next_ep = entry['next_ep']
            clean_rows.append((entry['tid'], entry['show_title'], next_ep['season'], next_ep['number'],
                               ep_title, ep_overview or entry['overview'], w['last_at'] or now_str,
                               entry['poster'], air_date, len(w['set'])))

        _db_exec_retry(c, "DELETE FROM tmdb_next_episodes")
        try:
            _meta_rows = []
            for entry in pending:
                try:
                    _nt = int((entry.get('show_details') or {}).get('number_of_episodes') or 0)
                except:
                    _nt = 0
                if _nt > 0:
                    _meta_rows.append((str(entry['tid']), _nt))
            if _meta_rows:
                c.executemany("INSERT OR IGNORE INTO tv_meta (tmdb_id, total_episodes) VALUES (?, ?)", _meta_rows)
                c.executemany("UPDATE tv_meta SET total_episodes=? WHERE tmdb_id=?", [(nt, tid) for tid, nt in _meta_rows])
            try:
                for _tid, _nt in _meta_rows:
                    tmdb_api.TV_META_CACHE[_tid] = _nt
            except:
                pass
        except:
            pass
        if clean_rows:
            import time as _t2
            for _a in range(20):
                try:
                    c.executemany("INSERT OR REPLACE INTO tmdb_next_episodes %s VALUES (?,?,?,?,?,?,?,?,?,?)" % _TMDB_NEXT_COLS, clean_rows)
                    break
                except Exception as _e:
                    if 'database is locked' in str(_e) and _a < 19:
                        _t2.sleep(0.4 + 0.15 * _a)
                        continue
                    raise
            _db_commit_retry(c.connection)
        elapsed = time.time() - t0
        log(f"[TMDB SYNC] Up Next: {len(clean_rows)} seriale (watchlist TMDb + pool {_get_provider_raw()}) in {elapsed:.1f}s (show {time.time()-t_season_start:.1f}s season phase).")
        try:
            from resources.lib.cache import clear_all_fast_cache
            clear_all_fast_cache()
        except Exception:
            pass
    except Exception as e:
        log(f"[TMDB SYNC] sync_tmdb_up_next error: {e}", xbmc.LOGERROR)


def refresh_next_episode_tmdb(tmdb_id):
    import datetime
    from resources.lib.watched_provider import get_watched_episodes_set, _get_provider_raw, get_source_module
    from resources.lib import tmdb_api

    try:
        tid = str(tmdb_id)
        show_details = tmdb_api.get_tmdb_item_details(tid, 'tv')
        if not show_details:
            return
        show_title = show_details.get('name', 'Unknown Show')

        if not os.path.exists(DB_PATH):
            return
        conn = get_connection()
        cur = conn.cursor()

        # Apartenenta: watchlist TMDb SAU pool-ul providerului activ
        cur.execute("SELECT 1 FROM tmdb_account_lists WHERE list_type='watchlist' "
                    "AND media_type='tv' AND tmdb_id=?", (tid,))
        in_watchlist = bool(cur.fetchone())

        if in_watchlist:
            in_pool = True
        else:
            in_pool = False
            try:
                prov = _get_provider_raw()
                prov_tbl = {'trakt': 'trakt_next_episodes',
                            'mdblist': 'mdblist_next_episodes',
                            'simkl': 'simkl_next_episodes'}.get(prov)
                if prov_tbl:
                    import time
                    for _ in range(6):
                        pconn = get_source_module().get_connection()
                        pcur = pconn.cursor()
                        pcur.execute("SELECT 1 FROM %s WHERE tmdb_id=?" % prov_tbl, (tid,))
                        in_pool = bool(pcur.fetchone())
                        pconn.close()
                        if in_pool:
                            break
                        time.sleep(0.25)
            except Exception:
                in_pool = False

        if not in_watchlist and not in_pool:
            try:
                _db_exec_retry(conn, "DELETE FROM tmdb_next_episodes WHERE tmdb_id=?", (tid,))
                _db_commit_retry(conn)
            except:
                pass
            try: conn.close()
            except: pass
            return

        w = get_watched_episodes_set(tid)

        if w['set']:
            next_ep = _tmdb_next_episode_scan(show_details, w['set'], w['last'])
        elif in_watchlist:
            next_ep = _tmdb_first_episode(show_details)
        else:
            next_ep = None

        if not next_ep:
            try:
                _db_exec_retry(conn, "DELETE FROM tmdb_next_episodes WHERE tmdb_id=?", (tid,))
                _db_commit_retry(conn)
            except:
                pass
            try: conn.close()
            except: pass
            return

        ep_title, ep_overview, air_date = _tmdb_ep_meta(tid, next_ep['season'], next_ep['number'])
        poster = get_poster_from_db(tid, 'show') or show_details.get('poster_path', '')
        now_str = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
        try:
            _db_exec_retry(conn,
                "INSERT OR REPLACE INTO tmdb_next_episodes %s VALUES (?,?,?,?,?,?,?,?,?,?)" % _TMDB_NEXT_COLS,
                (tid, show_title, next_ep['season'], next_ep['number'], ep_title,
                 ep_overview, w['last_at'] or now_str, poster, air_date, len(w['set'])))
            _db_commit_retry(conn)
        except Exception as _e:
            log(f"[TMDB SYNC] refresh insert retry failed: {_e}", xbmc.LOGERROR)
        try: conn.close()
        except: pass
        log(f"[TMDB SYNC] Up Next refreshed {show_title} -> S{next_ep['season']:02d}E{next_ep['number']:02d}")
        try:
            from resources.lib.cache import clear_all_fast_cache
            clear_all_fast_cache()
        except Exception:
            pass
    except Exception as e:
        log(f"[TMDB SYNC] refresh_next_episode_tmdb error: {e}", xbmc.LOGERROR)


# =============================================================================
# SALTS IMPLEMENTATION: NATIVE KODI LIBRARY JSON-RPC SYNC
# =============================================================================
def update_kodi_library_watchstatus(mediatype, action, title, year, season=None, episode=None):
    try:
        import json
        import xbmc
        from resources.lib.utils import clean_text
        
        playcount = 1 if action == 'mark_as_watched' else 0
        
        # 1. Filtram dupa an pentru o cautare rapida in JSON-RPC
        years = range(int(year)-1, int(year)+2) if year and str(year).isdigit() else []
        filters = [{"field": "year", "operator": "is", "value": str(i)} for i in years]
        
        properties = ["title", "file"]
        params = {"filter": {"or": filters}, "properties": properties} if filters else {"properties": properties}
        
        method = 'VideoLibrary.GetMovies' if mediatype == 'movie' else 'VideoLibrary.GetTVShows'
        req = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
        
        res = json.loads(xbmc.executeJSONRPC(json.dumps(req)))
        items = res.get('result', {}).get('movies' if mediatype == 'movie' else 'tvshows', [])
        
        if not items:
            return 
            
        target_title = clean_text(title).lower()
        found_item = None
        
        # 2. Cautam matching exact in rezultate
        for item in items:
            item_title = clean_text(item.get('title', '')).lower()
            if mediatype != 'movie' and ' (' in item.get('title', ''):
                item_title = clean_text(item.get('title', '').split(' (')[0]).lower()
                
            if target_title in item_title or item_title in target_title:
                found_item = item
                break
                
        if not found_item:
            return
            
        # 3. Setam tipul de identificator
        if mediatype == 'episode' or (season is not None and episode is not None):
            ep_filters = [
                {"field": "season", "operator": "is", "value": str(season)}, 
                {"field": "episode", "operator": "is", "value": str(episode)}
            ]
            ep_params = {"filter": {"and": ep_filters}, "properties": ["file"], "tvshowid": found_item['tvshowid']}
            ep_req = {"jsonrpc": "2.0", "method": "VideoLibrary.GetEpisodes", "params": ep_params, "id": 1}
            ep_res = json.loads(xbmc.executeJSONRPC(json.dumps(ep_req)))
            
            episodes = ep_res.get('result', {}).get('episodes', [])
            if not episodes: return
            
            target_id = episodes[0]['episodeid']
            set_method = 'VideoLibrary.SetEpisodeDetails'
            id_name = 'episodeid'
        elif mediatype == 'movie':
            target_id = found_item['movieid']
            set_method = 'VideoLibrary.SetMovieDetails'
            id_name = 'movieid'
        else:
            return 
            
        # 4. Trimitem comanda de Update Playcount (Instant) - Asta e secretul SALTS
        query_playcount = {"jsonrpc": "2.0", "method": set_method, "params": {id_name: target_id, "playcount": playcount}, "id": 1}
        xbmc.executeJSONRPC(json.dumps(query_playcount))
        
        # 5. Resetam Bara de Progres daca marcam ca vizionat
        query_resume = {"jsonrpc": "2.0", "method": set_method, "params": {id_name: target_id, "resume": {"position": 0}}, "id": 1}
        xbmc.executeJSONRPC(json.dumps(query_resume))
        
    except Exception as e:
        pass # Ignoram silentios


# =============================================================================
# KODI LIBRARY JSON-RPC SYNC (INFALLIBLE TMDB ID MATCH)
# =============================================================================
def update_kodi_library_watchstatus(mediatype, action, title, tmdb_id=None, season=None, episode=None):
    try:
        import json
        import xbmc
        import re
        
        playcount = 1 if action == 'mark_as_watched' else 0
        
        # Extragem doar numele serialului/filmului din titlul compus (ex: "Hacks - S01E03" -> "Hacks")
        search_title = str(title)
        if mediatype in ['episode', 'season', 'tv'] and ' - S' in search_title:
            search_title = search_title.split(' - S')[0].strip()
        elif mediatype in ['episode', 'season', 'tv'] and ' - Sezonul' in search_title:
            search_title = search_title.split(' - Sezonul')[0].strip()
        
        # 1. Cerem toate Filmele sau Serialele din Kodi
        if mediatype == 'movie':
            method = 'VideoLibrary.GetMovies'
            properties = ["title", "uniqueid", "file"]
        else:
            method = 'VideoLibrary.GetTVShows'
            properties = ["title", "uniqueid", "file"]
        
        req = {
            "jsonrpc": "2.0", 
            "method": method, 
            "params": {"properties": properties}, 
            "id": 1
        }
        
        res = json.loads(xbmc.executeJSONRPC(json.dumps(req)))
        items = res.get('result', {}).get('movies' if mediatype == 'movie' else 'tvshows', [])
        
        if not items:
            return 
            
        found_item = None
        
        # 2. Cautare inteligenta: Primordial dupa TMDb ID, fallback dupa Nume
        for item in items:
            uids = item.get('uniqueid', {})
            # Verificam TMDb ID (TMDB Helper il salveaza in 'tmdb' sau 'default')
            if tmdb_id and (str(uids.get('tmdb')) == str(tmdb_id) or str(uids.get('default')) == str(tmdb_id)):
                found_item = item
                break
                
            # Fallback la Titlu
            item_title = str(item.get('title', '')).lower()
            item_title = re.sub(r'\s*\(\d{4}\)$', '', item_title).strip() # Stergem anul daca Kodi l-a adaugat
            
            if search_title.lower() == item_title:
                found_item = item
                break
                
        if not found_item:
            return
            
        # 3. Gasim ID-ul intern Kodi pentru Film sau Episod
        if mediatype == 'episode' or (season is not None and episode is not None):
            tvshowid = found_item['tvshowid']
            ep_req = {
                "jsonrpc": "2.0", 
                "method": "VideoLibrary.GetEpisodes", 
                "params": {
                    "tvshowid": tvshowid,
                    "season": int(season),
                    "properties": ["episode", "file", "playcount"],
                    "filter": {"field": "episode", "operator": "is", "value": str(episode)}
                }, 
                "id": 1
            }
            ep_res = json.loads(xbmc.executeJSONRPC(json.dumps(ep_req)))
            episodes = ep_res.get('result', {}).get('episodes', [])
            
            if not episodes: return
            
            target_id = episodes[0]['episodeid']
            set_method = 'VideoLibrary.SetEpisodeDetails'
            id_name = 'episodeid'
            
        elif mediatype == 'movie':
            target_id = found_item['movieid']
            set_method = 'VideoLibrary.SetMovieDetails'
            id_name = 'movieid'
        else:
            return 
            
        # 4. Trimitem Setarea de Playcount
        xbmc.executeJSONRPC(json.dumps({
            "jsonrpc": "2.0", "method": set_method, 
            "params": {id_name: target_id, "playcount": playcount}, "id": 1
        }))
        
        # 5. Daca a fost marcat ca vizionat, resetam pozitia de Resume
        if playcount == 1:
            xbmc.executeJSONRPC(json.dumps({
                "jsonrpc": "2.0", "method": set_method, 
                "params": {id_name: target_id, "resume": {"position": 0}}, "id": 1
            }))
            
    except Exception as e:
        from resources.lib.utils import log
        log(f"[KODI-SYNC] Error updating library: {e}", 4) # 4 = LOGERROR


