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
from resources.lib.config import ADDON, API_KEY, BASE_URL, LANG, TMDB_SESSION_FILE, IMG_BASE
from resources.lib.utils import log, read_json, write_json
from concurrent.futures import ThreadPoolExecutor

PROFILE_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
DB_PATH = os.path.join(PROFILE_PATH, 'trakt_sync.db')
LAST_SYNC_FILE = os.path.join(PROFILE_PATH, 'last_sync.json')


# =============================================================================
# DATABASE HELPERS
# =============================================================================

def get_connection():
    if not os.path.exists(PROFILE_PATH):
        try: os.makedirs(PROFILE_PATH)
        except: pass
    
    # --- PROTECȚIE DIMENSIUNE ---
    if os.path.exists(DB_PATH):
        try:
            size_mb = os.path.getsize(DB_PATH) / (1024 * 1024)
            if size_mb > 50: # Limita 50MB
                log(f"[DB-PROTECT] trakt_sync.db are {size_mb:.2f}MB. RESETARE AUTOMATĂ!", xbmc.LOGWARNING)
                xbmcvfs.delete(DB_PATH)
                # Notificare discretă
                xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]", "Cache Reset (Size Limit)", os.path.join(ADDON.getAddonInfo('path'), 'icon.png'))
                # Re-inițializare tabele
                init_database()
        except: pass
    # -----------------------------

    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    conn = get_connection()
    c = conn.cursor()
    
    # Tabele existente (nu le modificam definitia de baza pentru a pastra compatibilitatea)
    c.execute('''CREATE TABLE IF NOT EXISTS trakt_watched_movies (tmdb_id TEXT PRIMARY KEY, title TEXT, year TEXT, last_watched_at TEXT, poster TEXT, backdrop TEXT, overview TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS trakt_watched_episodes (tmdb_id TEXT, season INTEGER, episode INTEGER, title TEXT, last_watched_at TEXT, UNIQUE(tmdb_id, season, episode))''')
    c.execute('''CREATE TABLE IF NOT EXISTS trakt_lists (list_type TEXT, media_type TEXT, tmdb_id TEXT, title TEXT, year TEXT, added_at TEXT, poster TEXT, backdrop TEXT, overview TEXT, UNIQUE(list_type, media_type, tmdb_id))''')
    
    # AICI AM ADAUGAT 'updated_at' IN DEFINITIE
    c.execute('''CREATE TABLE IF NOT EXISTS user_lists (trakt_id TEXT PRIMARY KEY, name TEXT, slug TEXT, item_count INTEGER, sort_by TEXT, sort_how TEXT, description TEXT, updated_at TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS user_list_items (list_slug TEXT, media_type TEXT, tmdb_id TEXT, title TEXT, year TEXT, added_at TEXT, poster TEXT, backdrop TEXT, overview TEXT, UNIQUE(list_slug, media_type, tmdb_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS discovery_cache (list_type TEXT, media_type TEXT, tmdb_id TEXT, title TEXT, year TEXT, poster TEXT, backdrop TEXT, overview TEXT, rank INTEGER, UNIQUE(list_type, media_type, tmdb_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS tmdb_discovery (action TEXT, page INTEGER, tmdb_id TEXT, title TEXT, year TEXT, poster TEXT, overview TEXT, rank INTEGER, UNIQUE(action, page, tmdb_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS playback_progress (tmdb_id TEXT, media_type TEXT, season INTEGER, episode INTEGER, progress FLOAT, paused_at TEXT, title TEXT, year TEXT, poster TEXT, UNIQUE(tmdb_id, media_type, season, episode))''')
    c.execute('''CREATE TABLE IF NOT EXISTS tv_meta (tmdb_id TEXT PRIMARY KEY, total_episodes INTEGER, poster TEXT, backdrop TEXT, overview TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS tmdb_custom_lists (list_id TEXT PRIMARY KEY, name TEXT, item_count INTEGER, poster TEXT, backdrop TEXT, description TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS tmdb_custom_list_items 
                 (list_id TEXT, tmdb_id TEXT, media_type TEXT, title TEXT, year TEXT, 
                  poster TEXT, overview TEXT, sort_index INTEGER, UNIQUE(list_id, tmdb_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS tmdb_account_lists (list_type TEXT, media_type TEXT, tmdb_id TEXT, title TEXT, year TEXT, poster TEXT, added_at TEXT, overview TEXT, UNIQUE(list_type, media_type, tmdb_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS tmdb_recommendations (media_type TEXT, tmdb_id TEXT, title TEXT, year TEXT, poster TEXT, overview TEXT, UNIQUE(media_type, tmdb_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS meta_cache_items (tmdb_id TEXT, media_type TEXT, data TEXT, expires INTEGER, UNIQUE(tmdb_id, media_type))''')
    c.execute('''CREATE TABLE IF NOT EXISTS meta_cache_seasons (tmdb_id TEXT, season_num INTEGER, data TEXT, expires INTEGER, UNIQUE(tmdb_id, season_num))''')
    
    # --- TABELE NOI PENTRU UP NEXT SI FAVORITES ---
    c.execute('''CREATE TABLE IF NOT EXISTS trakt_next_episodes 
                 (tmdb_id TEXT PRIMARY KEY, show_title TEXT, season INTEGER, episode INTEGER, 
                  ep_title TEXT, overview TEXT, last_watched_at TEXT, poster TEXT, air_date TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS trakt_hidden_shows (tmdb_id TEXT PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS trakt_favorites 
                 (media_type TEXT, tmdb_id TEXT, title TEXT, year TEXT, poster TEXT, overview TEXT, rank INTEGER, UNIQUE(media_type, tmdb_id))''')
    
    # --- MIGRARI PENTRU DATELE EXISTENTE ---
    # Adaugam coloana updated_at daca nu exista
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
    
    try: c.execute("ALTER TABLE tmdb_custom_lists ADD COLUMN backdrop TEXT")
    except: pass
    
    try: c.execute("ALTER TABLE tmdb_custom_lists ADD COLUMN description TEXT")
    except: pass

    # ADĂUGĂM ACESTE LINII PENTRU A REPARA TRAKT_LISTS
    try: c.execute("ALTER TABLE trakt_lists ADD COLUMN added_at TEXT")
    except: pass
    
    try: c.execute("ALTER TABLE trakt_lists ADD COLUMN poster TEXT")
    except: pass

    try: c.execute("ALTER TABLE trakt_lists ADD COLUMN backdrop TEXT")
    except: pass
    
    try: c.execute("ALTER TABLE trakt_lists ADD COLUMN overview TEXT")
    except: pass

# --- MIGRARI ---
    try: c.execute("ALTER TABLE tmdb_custom_list_items ADD COLUMN sort_index INTEGER")
    except: pass

    conn.commit()
    conn.close()


def is_table_empty(c, table):
    """Verifică dacă un tabel SQL este gol într-un mod robust."""
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
    """Citește timestamp-urile locale cu logging."""
    data = read_json(LAST_SYNC_FILE)
    
    # DEBUG: Afișăm ce am citit
    if data:
        log(f"[SYNC] Loaded local timestamps: {list(data.keys())}")
    else:
        log(f"[SYNC] ⚠️ No local timestamps found (file missing or empty)")
        
    return data or {}


def save_local_last_sync(data):
    """Salvează timestamp-urile cu verificare."""
    write_json(LAST_SYNC_FILE, data)
    
    # Verificăm că s-a salvat corect
    verify = read_json(LAST_SYNC_FILE)
    if verify and len(verify) >= len(data):
        log(f"[SYNC] ✓ Saved timestamps: {list(data.keys())}")
    else:
        log(f"[SYNC] ⚠️ WARNING: Save verification failed! Expected {len(data)}, got {len(verify) if verify else 0}", xbmc.LOGWARNING)

def parse_trakt_date(date_str):
    """
    Parsează data Trakt. Robust la formate cu/fără milisecunde.
    Fără strptime pentru a evita bug-ul Kodi.
    """
    if not date_str: return datetime.datetime.min
    try:
        # Eliminăm 'Z' de la final și decupăm milisecundele
        d = str(date_str).replace('Z', '')
        if '.' in d:
            d = d.split('.')[0]
            
        date_part, time_part = d.split('T')
        y, m, day = map(int, date_part.split('-'))
        H, M, S = map(int, time_part.split(':'))
        
        return datetime.datetime(y, m, day, H, M, S)
    except:
        return datetime.datetime.min

def needs_sync(section, remote_activities, local_sync_data):
    """
    Verifică dacă o secțiune necesită sincronizare.
    Returnează True = trebuie sync, False = skip.
    """
    # 1. Verificăm activities
    if not remote_activities or not isinstance(remote_activities, dict): 
        log(f"[SYNC-CHECK] {section}: ⚠️ No valid activities -> SYNC", xbmc.LOGWARNING)
        return True
    
    key_map = {
        'movies_watched': ('movies', 'watched_at'),
        'episodes_watched': ('episodes', 'watched_at'),
        'watchlist': ('watchlist', 'updated_at'),
        'lists': ('lists', 'updated_at'),
        'movies_collected': ('movies', 'collected_at'),
    }
    
    if section not in key_map: 
        log(f"[SYNC-CHECK] {section}: Unknown -> SYNC")
        return True
        
    category, field = key_map[section]
    
    # Extragem timestamps
    cat_data = remote_activities.get(category, {})
    remote_ts = cat_data.get(field) if cat_data else None
    local_ts = local_sync_data.get(section) if local_sync_data else None
    
    # ✅ DEBUG COMPLET
    log(f"[SYNC-CHECK] {section}: Remote='{remote_ts}' | Local='{local_ts}'")
    
    # 2. Fără dată remote = skip
    if not remote_ts: 
        log(f"[SYNC-CHECK] {section}: No remote -> SKIP")
        return False 
    
    # 3. Fără dată locală = sync
    if not local_ts: 
        log(f"[SYNC-CHECK] {section}: No local -> SYNC")
        return True 
    
    # 4. Comparație exactă
    if remote_ts == local_ts:
        log(f"[SYNC-CHECK] {section}: ✓ Match -> SKIP")
        return False
        
    # 5. Comparație datetime
    remote_date = parse_trakt_date(remote_ts)
    local_date = parse_trakt_date(local_ts)
    
    if remote_date > local_date:
        log(f"[SYNC-CHECK] {section}: Remote newer -> SYNC")
        return True
    else:
        log(f"[SYNC-CHECK] {section}: ✓ Local same/newer -> SKIP")
        return False

def sync_full_library(silent=False, force=False):
    from resources.lib import trakt_api
    
    # --- PREVENIRE SINCRONIZARE DUBLĂ ---
    window = xbmcgui.Window(10000)
    if window.getProperty('tmdbmovies_sync_active') == 'true':
        log("[SYNC] Sincronizare deja în curs. Ignorăm cererea nouă.")
        if not silent:
            xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]", "Sincronizare deja în curs...", os.path.join(ADDON.getAddonInfo('path'), 'icon.png'))
        return

    window.setProperty('tmdbmovies_sync_active', 'true')

    try:
        token = trakt_api.get_trakt_token()
        if not token: 
            return

        init_database()
        
        p_dialog = None
        if not silent:
            p_dialog = xbmcgui.DialogProgressBG()
            p_dialog.create("[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]", "Verificare modificări Trakt...")
        
        try:
            log("[SYNC] === STARTING SMART SYNC ===")
            
            activities = get_trakt_last_activities()
            
            # --- MODIFICARE: PROTECTIE TRAKT DOWN ---
            if not activities:
                # Dacă Trakt e picat (API Error), NU forțăm sync-ul.
                # Păstrăm cache-ul vechi ca să nu dispară paginile.
                log("[SYNC] Eșec conectare API Trakt (Activities). ABORT SYNC pentru protejarea datelor locale.", xbmc.LOGWARNING)
                if not silent:
                    xbmcgui.Dialog().notification("[B][COLOR FFFDBD01]Trakt Error[/COLOR][/B]", "Server indisponibil. Date locale păstrate.", os.path.join(ADDON.getAddonInfo('path'), 'icon.png'))
                return 
            # ----------------------------------------

            local_sync = get_local_last_sync()
            new_sync = local_sync.copy() if local_sync else {}
            
            conn = get_connection()
            c = conn.cursor()
            
# --- 1. WATCHED MOVIES ---
            should_sync_movies = force or needs_sync('movies_watched', activities, local_sync) or is_table_empty(c, 'trakt_watched_movies')
            if should_sync_movies:
                if not silent and p_dialog: p_dialog.update(10, message="Sync: [B][COLOR pink]Filme Vizionate[/COLOR][/B]")
                _sync_watched_movies(c)
            
            # Salvăm timestamp-ul de la server chiar dacă am dat skip (pentru că suntem deja la zi)
            if activities and activities.get('movies', {}).get('watched_at'):
                new_sync['movies_watched'] = activities['movies']['watched_at']

            # --- 2. WATCHED EPISODES ---
            should_sync_episodes = force or needs_sync('episodes_watched', activities, local_sync) or is_table_empty(c, 'trakt_watched_episodes')
            if should_sync_episodes:
                if not silent and p_dialog: p_dialog.update(25, message="Sync: [B][COLOR pink]Episoade Vizionate[/COLOR][/B]")
                _sync_watched_episodes(c)
                
            if activities and activities.get('episodes', {}).get('watched_at'):
                new_sync['episodes_watched'] = activities['episodes']['watched_at']

            # --- 3. WATCHLIST ---
            should_sync_watchlist = force or needs_sync('watchlist', activities, local_sync) or is_table_empty(c, 'trakt_lists')
            if should_sync_watchlist:
                if not silent and p_dialog: p_dialog.update(40, message="Sync: [B][COLOR pink]Watchlist[/COLOR][/B]")
                _sync_list_content(c, 'watchlist')
                
            if activities and activities.get('watchlist', {}).get('updated_at'):
                new_sync['watchlist'] = activities['watchlist']['updated_at']

            # --- 4. FAVORITES (Inimioară) ---
            if not silent and p_dialog: p_dialog.update(50, message="Sync: [B][COLOR pink]Trakt Favorites[/COLOR][/B]")
            _sync_trakt_favorites(c)

            # --- 5. USER LISTS ---
            should_sync_lists = force or needs_sync('lists', activities, local_sync) or is_table_empty(c, 'user_lists')
            if should_sync_lists:
                if not silent and p_dialog: p_dialog.update(60, message="Sync: [B][COLOR pink]Liste Personale[/COLOR][/B]")
                _sync_user_lists(c, force=force)
                
            if activities and activities.get('lists', {}).get('updated_at'):
                new_sync['lists'] = activities['lists']['updated_at']

            # --- SALVĂM ȘI ELIBERĂM DB ÎNAINTE DE THREADING ---
            conn.commit()

            # --- 6. IN PROGRESS & UP NEXT (Threaded) ---
            log("[SYNC] 6. Syncing In Progress & Up Next...")
            if not silent and p_dialog: p_dialog.update(75, message="Sync: [B][COLOR pink]In Progress & Up Next[/COLOR][/B]")
            _sync_playback(c)
            _sync_hidden_shows(c)
            _sync_up_next(c, token) 

            conn.commit()

            # --- 7. DISCOVERY ---
            last_disc = local_sync.get('discovery_ts', 0)
            if force or (time.time() - last_disc > 21600):
                if not silent and p_dialog: p_dialog.update(85, message="Sync: [B][COLOR pink]Trending & Popular[/COLOR][/B]")
                _sync_trakt_discovery(c)
                if not silent and p_dialog: p_dialog.update(90, message="Sync: [B][COLOR FF00CED1]Liste TMDb[/COLOR][/B]")
                _sync_tmdb_discovery(c)
                new_sync['discovery_ts'] = time.time()

            # --- 8. TMDB ACCOUNT ---
            session = read_json(TMDB_SESSION_FILE)
            if session and session.get('session_id'):
                # CALCULĂM DACĂ E NEVOIE DE SYNC (Force sau 30 min trecute de la ultimul tmdb_sync_ts)
                tmdb_sync_needed = force or (time.time() - local_sync.get('tmdb_sync_ts', 0) > 1800)

                if tmdb_sync_needed:
                    if not silent and p_dialog: p_dialog.update(95, message="Sync: [B][COLOR FF00CED1]Cont TMDb[/COLOR][/B]")
                    try:
                        # Trimitem tmdb_sync_needed ca parametru force către funcție
                        _sync_tmdb_data(c, force=tmdb_sync_needed)
                        # Salvăm timestamp-ul actual pentru a nu repeta sync-ul timp de 30 min
                        new_sync['tmdb_sync_ts'] = time.time()
                    except: pass

            conn.commit()
            conn.close()
            
            save_local_last_sync(new_sync)
            cleanup_database()
            
            log("[SYNC] === SYNC COMPLETE ===")
            
            if not silent and p_dialog:
                p_dialog.close()
                xbmcgui.Dialog().notification("[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]", "Sincronizare Completă", os.path.join(ADDON.getAddonInfo('path'), 'icon.png'))
                
        except Exception as e:
            log(f"[SYNC] CRITICAL ERROR: {e}", xbmc.LOGERROR)
            if not silent and p_dialog:
                try: p_dialog.close()
                except: pass
    
    finally:
        window.clearProperty('tmdbmovies_sync_active')


# =============================================================================
# WORKER FUNCTIONS
# =============================================================================

def _sync_watched_movies(c):
    from resources.lib import trakt_api
    data = trakt_api.trakt_api_request("/sync/watched/movies", params={'extended': 'full'})
    if not data or not isinstance(data, list): return
    c.execute("DELETE FROM trakt_watched_movies")
    rows = []
    for item in data:
        if not item: continue
        m = item.get('movie') or {}
        tid = str((m.get('ids') or {}).get('tmdb', ''))
        if tid and tid != 'None':
            rows.append((tid, m.get('title'), str(m.get('year','')), item.get('last_watched_at'), '', '', m.get('overview','')))
    if rows: 
        c.executemany("INSERT OR REPLACE INTO trakt_watched_movies VALUES (?,?,?,?,?,?,?)", rows)
        log(f"[SYNC] Saved {len(rows)} watched movies.")

def _sync_watched_episodes(c):
    from resources.lib import trakt_api
    data = trakt_api.trakt_api_request("/sync/watched/shows", params={'extended': 'full'})
    if not data or not isinstance(data, list): return
    c.execute("DELETE FROM trakt_watched_episodes")
    c.execute("DELETE FROM tv_meta")
    
    ep_rows = []
    meta_rows = []
    
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
        
        meta_rows.append((tid, 0, '', '', overview)) 

    if ep_rows:
        c.executemany("INSERT OR REPLACE INTO trakt_watched_episodes VALUES (?,?,?,?,?)", ep_rows)
        log(f"[SYNC] Saved {len(ep_rows)} watched episodes.")
    if meta_rows:
        c.executemany("INSERT OR REPLACE INTO tv_meta VALUES (?,?,?,?,?)", meta_rows)

def _sync_list_content(c, ltype):
    from resources.lib import trakt_api
    
    for m in ['movies', 'shows']:
        data = trakt_api.trakt_api_request(f"/sync/{ltype}/{m}", params={'extended': 'full'})
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
                rows.append((ltype, db_type, tid, meta.get('title'), str(meta.get('year','')), 
                             item.get('collected_at') or item.get('listed_at'), '', '', meta.get('overview','')))
        
        if rows: 
            c.executemany("INSERT OR REPLACE INTO trakt_lists VALUES (?,?,?,?,?,?,?,?,?)", rows)
            log(f"[SYNC] Saved {len(rows)} items in {ltype} ({m}).")
    
    # ✅ ELIMINAT: sincronizarea detaliilor TV

def _sync_user_lists(c, force=False):
    from resources.lib import trakt_api
    from concurrent.futures import ThreadPoolExecutor # Import necesar aici
    
    user = trakt_api.get_trakt_username()
    if not user: return

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
        
        # Verificăm dacă lista s-a schimbat
        should_sync = force or trakt_id not in local_map or \
                      local_map[trakt_id]['updated_at'] != remote_updated_at or \
                      local_map[trakt_id]['count'] != remote_item_count
        
        items_data = None
        if should_sync:
            log(f"[SYNC] Parallel Fetch Trakt List: {name}")
            items_data = trakt_api.trakt_api_request(f"/users/{user}/lists/{slug}/items", params={'extended': 'full'})
            
        return {
            'header': (trakt_id, name, slug, remote_item_count, lst.get('sort_by'), lst.get('sort_how'), lst.get('description', '') or '', remote_updated_at),
            'items': items_data, 
            'slug': slug, 
            'should_sync': should_sync, 
            'trakt_id': trakt_id
        }

    # Lansăm 5 fire de execuție pentru viteză
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(fetch_trakt_list_worker, remote_lists))

    remote_ids = []
    for res in results:
        if not res: continue
        remote_ids.append(res['trakt_id'])
        
        # 4. Salvăm header-ul listei
        c.execute("INSERT OR REPLACE INTO user_lists VALUES (?,?,?,?,?,?,?,?)", res['header'])
        
        # 5. Salvăm itemele dacă lista a fost descărcată
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
                        # Păstrăm ordinea adăugării (Newest First) folosind it.get('added_at')
                        i_rows.append((res['slug'], typ, tid, meta.get('title'), str(meta.get('year','')), it.get('added_at'), '', '', meta.get('overview','')))
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
    
    # 2. SALVĂM TEMPORAR CE AVEAM LOCAL PENTRU A NU PIERDE SECUNDE EXACTE / DELAY TRAKT
    c.execute("SELECT * FROM playback_progress")
    local_progress = {}
    for row in c.fetchall():
        key = f"{row['tmdb_id']}_{row['media_type']}_{row['season']}_{row['episode']}"
        local_progress[key] = dict(row)
        
    c.execute("DELETE FROM playback_progress")
    rows =[]
    
    # 3. Procesăm datele de la Trakt
    for item in data:
        progress = item.get('progress', 0)
        if progress <= 1 or progress >= 99: 
            continue
            
        typ = item.get('type')
        meta = item.get('movie') if typ == 'movie' else item.get('show')
        if not meta: continue
        
        ids = meta.get('ids') or {}
        tid = str(ids.get('tmdb', ''))
        
        # Fallback dacă lipsește TMDB ID, convertim din IMDb
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
        
        # --- MAGIA MERGE-ULUI: Păstrăm secundele exacte locale dacă există! ---
        key = f"{tid}_{typ}_{s}_{e}"
        if key in local_progress:
            local_val = local_progress[key]['progress']
            local_time = local_progress[key]['paused_at']
            # Dacă local aveam valoarea magică >1.000.000 (secunde exacte), o restaurăm
            if local_val >= 1000000:
                progress = local_val
                paused_at = local_time
        # ----------------------------------------------------------------------
        
        rows.append((tid, typ, s, e, progress, paused_at, title, year, ''))
        
    # 4. SALVĂM ȘI CE ERA LOCAL DAR A FOST OMIS DE TRAKT (Trakt API Cache Delay)
    now = datetime.datetime.utcnow()
    for key, loc in local_progress.items():
        # Verificăm dacă nu cumva a fost deja procesat mai sus
        if not any(r[0] == loc['tmdb_id'] and r[1] == loc['media_type'] and r[2] == loc['season'] and r[3] == loc['episode'] for r in rows):
            try:
                # Parsare manuală fără strptime
                clean_date = str(loc['paused_at']).replace('.000Z', '').replace('Z', '')
                d_part, t_part = clean_date.split('T')
                y, m, d_zi = map(int, d_part.split('-'))
                H, M, S = map(int, t_part.split(':'))
                loc_time = datetime.datetime(y, m, d_zi, H, M, S)
                
                # Dacă l-ai vizionat acum mai puțin de 24h, îl păstrăm local forțat!
                if (now - loc_time).total_seconds() < 86400:
                    rows.append((loc['tmdb_id'], loc['media_type'], loc['season'], loc['episode'], 
                                 loc['progress'], loc['paused_at'], loc['title'], loc['year'], loc['poster']))
            except: pass

    if rows: 
        c.executemany("INSERT OR REPLACE INTO playback_progress VALUES (?,?,?,?,?,?,?,?,?)", rows)
        log(f"[SYNC] Saved {len(rows)} items in progress (Merged with local cache limit 100 + ID Fix).")


def _sync_trakt_discovery(c):
    from resources.lib import trakt_api
    c.execute("DELETE FROM discovery_cache")
    
    # Configurație (API endpoint part, media type, DB type)
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
                data = trakt_api.get_trakt_trending(media, 200)
            elif ltype == 'popular':
                data = trakt_api.get_trakt_popular(media, 200)
            elif ltype == 'anticipated':
                data = trakt_api.get_trakt_anticipated(media, 200)
            else:
                continue

            if not data or not isinstance(data, list): continue
            
            rows = []
            rank = 1
            for item in data:
                if not item: continue
                # Boxoffice returnează item-ul direct, altele au cheie movie/show
                meta = item.get(db_type) if ltype != 'boxoffice' and db_type in item else item
                
                tid = str((meta.get('ids') or {}).get('tmdb', ''))
                if tid and tid != 'None':
                    title = meta.get('title', '')
                    year = str(meta.get('year', ''))
                    overview = meta.get('overview', '')
                    
                    # ✅ REVERT: Nu salvăm postere de la Trakt (nu le are)
                    # Posterele se vor încărca prin self-healing la afișare
                    rows.append((ltype, db_type, tid, title, year, '', '', overview, rank))
                    rank += 1
            
            if rows:
                c.executemany("INSERT OR REPLACE INTO discovery_cache VALUES (?,?,?,?,?,?,?,?,?)", rows)
                total_saved += len(rows)
        except Exception as e:
            pass
            
    log(f"[SYNC] Saved {total_saved} Trakt discovery items.")

def _sync_tmdb_discovery(c):
    """Sincronizează TOATE listele TMDb definite în meniu."""
    import requests
    from resources.lib.tmdb_api import get_tmdb_movies_standard, get_tmdb_tv_standard
    
    # ✅ LISTA COMPLETĂ - Movies (10 liste)
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
    
    # ✅ LISTA COMPLETĂ - TV Shows (8 liste)
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
    
    # Ștergem cache-ul vechi
    c.execute("DELETE FROM tmdb_discovery")
    
    total_saved = 0
    
    # Sincronizăm Movies
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
            log(f"[SYNC] Eroare sync tmdb {action}: {e}", xbmc.LOGERROR)
    
    # Sincronizăm TV Shows
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
            log(f"[SYNC] Eroare sync tmdb {action}: {e}", xbmc.LOGERROR)
    
    log(f"[SYNC] Saved {total_saved} TMDb discovery items (Movies & TV).")


def _sync_tmdb_data(c, force=False):
    from resources.lib.config import TMDB_SESSION_FILE, API_KEY, BASE_URL, LANG
    from resources.lib.utils import read_json, get_language
    import requests
    from concurrent.futures import ThreadPoolExecutor

    session = read_json(TMDB_SESSION_FILE)
    if not session or not session.get('session_id'):
        log("[SYNC] TMDb Account sync skipped: No session found")
        return

    sid = session['session_id']
    aid = session['account_id']
    lang = get_language()

# 1. WATCHLIST & FAVORITES (Oglindire exactă a site-ului)
    endpoints = [('watchlist', 'movies', 'movie'), ('watchlist', 'tv', 'tv'), ('favorite', 'movies', 'movie'), ('favorite', 'tv', 'tv')]
    for ltype, endpoint_media, db_media in endpoints:
        try:
            # Verificăm dacă e cazul de sync
            c.execute("SELECT 1 FROM tmdb_account_lists WHERE list_type=? AND media_type=? LIMIT 1", (ltype, db_media))
            section_is_empty = c.fetchone() is None
            
            # Sincronizăm TMDb dacă: e force, tabelul e gol, sau au trecut 30 min de la ultimul sync TMDb
            if force or section_is_empty:
                # Ștergem local categoria respectivă
                c.execute("DELETE FROM tmdb_account_lists WHERE list_type=? AND media_type=?", (ltype, db_media))
                c.connection.commit() # Salvăm ștergerea înainte de a descărca
                
                # log(f"[SYNC] Fresh Fetch TMDb {ltype} ({db_media})...")
                page = 1
                total_fetched = 0
                while True:
                    # CRITIC: Folosim requests.get DIRECT, NU cache_object!
                    url = f"{BASE_URL}/account/{aid}/{ltype}/{endpoint_media}?api_key={API_KEY}&session_id={sid}&language={lang}&page={page}&sort_by=created_at.desc"
                    r = requests.get(url, timeout=10)
                    if r.status_code != 200: break
                    
                    data = r.json()
                    results = data.get('results', [])
                    if not results: break
                    
                    total_fetched += len(results)
                    _sync_tmdb_account_list_single(c, ltype, db_media, results, page)
                    if page >= data.get('total_pages', 1): break
                    page += 1
                
                log(f"[SYNC] Saved {total_fetched} items in TMDb {ltype} ({db_media}).")
# -------------------------------------------------------------
        except Exception as e:
            log(f"[SYNC] Eroare la categoria TMDb {ltype}: {e}", xbmc.LOGERROR)

# 2. LISTE PERSONALE TMDB (PARALELIZATE)
    try:
        url_lists = f"{BASE_URL}/account/{aid}/lists?api_key={API_KEY}&session_id={sid}&page=1"
        r = requests.get(url_lists, timeout=10)
        
        if r.status_code == 200:
            lists_data = r.json().get('results', [])
            c.execute("SELECT list_id, item_count FROM tmdb_custom_lists")
            local_lists = {str(row['list_id']): int(row['item_count']) for row in c.fetchall()}
            
            # WORKER CU TRANSMITERE EXPLICITĂ DE VARIABILE (VITEZĂ + STABILITATE)
            def fetch_tmdb_list_worker(lst_item, _sid, _aid, _lang, _force, _local_map):
                import requests
                from resources.lib.config import API_KEY, BASE_URL
                
                list_id = str(lst_item.get('id'))
                remote_count = int(lst_item.get('item_count', 0))
                name = lst_item.get('name', '')
                description = lst_item.get('description', '') or ''
                
                # --- LOGICA DE SYNC REPARATĂ ---
                should_sync = _force or list_id not in _local_map or _local_map.get(list_id) != remote_count
                
                # 4. VERIFICARE EXTRA: Chiar dacă numărul e egal, verificăm dacă tabelul de iteme e gol
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
                    log(f"[SYNC] Parallel Sync TMDb List: {name} ({remote_count} items)")
                    try:
                        page = 1
                        while True:
                            # Folosim v4 pentru a suporta seriale
                            list_url = f"{BASE_URL}/list/{list_id}?api_key={API_KEY}&language={_lang}&page={page}"
                            r_raw = requests.get(list_url, timeout=10)
                            if r_raw.status_code != 200: break
                            
                            lr_res = r_raw.json()
                            curr_items = lr_res.get('items', [])
                            if not curr_items: break
                            
                            if page == 1:
                                poster = curr_items[0].get('poster_path', '')
                                backdrop = curr_items[0].get('backdrop_path', '')
                            
                            items.extend(curr_items)
                            
                            if page >= lr_res.get('total_pages', 1): break
                            page += 1
                    except Exception as e:
                        log(f"[SYNC] Error fetching list {name}: {e}")
                
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

            # Lansăm thread-urile (max_workers=5 este ideal pentru TMDb)
            with ThreadPoolExecutor(max_workers=5) as executor:
                results = list(executor.map(lambda l: fetch_tmdb_list_worker(l, sid, aid, lang, force, local_lists), lists_data))

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
                
                # 2. Update Conținut (CRITIC: Păstrăm ordinea originală)
                if res['should_sync']:
                    c.execute("DELETE FROM tmdb_custom_list_items WHERE list_id=?", (res['id'],))
                    if res['items']:
                        i_rows = []
                        for idx, it in enumerate(res['items']):
                            tid = str(it.get('id', ''))
                            m_type = it.get('media_type', 'movie')
                            title = it.get('title') if m_type == 'movie' else it.get('name')
                            year = (it.get('release_date') or it.get('first_air_date') or '0000')[:4]
                            
                            # Adăugăm idx (indexul de pe site) ca a 8-a valoare pentru sort_index
                            i_rows.append((res['id'], tid, m_type, title, year, it.get('poster_path', ''), it.get('overview', ''), idx))
                        
                        if i_rows:
                            # 8 semne de întrebare pentru a se potrivi cu i_rows
                            c.executemany("INSERT OR REPLACE INTO tmdb_custom_list_items VALUES (?,?,?,?,?,?,?,?)", i_rows)

            # Cleanup liste șterse
            for lid in local_lists.keys():
                if lid not in remote_ids:
                    c.execute("DELETE FROM tmdb_custom_lists WHERE list_id=?", (lid,))
                    c.execute("DELETE FROM tmdb_custom_list_items WHERE list_id=?", (lid,))
    except Exception as e:
        log(f"[SYNC] Error parallel tmdb lists: {e}", xbmc.LOGERROR)

    # 3. RECOMMENDATIONS (Raman la fel)
    try:
        c.execute("DELETE FROM tmdb_recommendations")
        for m_type in ['movie', 'tv']:
            endpoint_suffix = 'movies' if m_type == 'movie' else 'tv'
            fav_url = f"{BASE_URL}/account/{aid}/favorite/{endpoint_suffix}?api_key={API_KEY}&session_id={sid}&language={lang}&page=1&sort_by=created_at.desc"
            fav_r = requests.get(fav_url, timeout=10)
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


def _sync_tmdb_account_list_single(cursor, list_type, media_type, results, page=1):
    """Helper pentru salvarea Watchlist/Favorites în SQL cu sortare corectă."""
    if not results: return

    # Luăm timpul curent
    base_time = time.time()
    
    rows = []
    # Folosim enumerate pentru a păstra ordinea din interiorul paginii
    for index, item in enumerate(results):
        tid = str(item.get('id', ''))
        if not tid: continue
        
        title = item.get('title') if media_type == 'movie' else item.get('name')
        
        date_key = 'release_date' if media_type == 'movie' else 'first_air_date'
        year_raw = str(item.get(date_key, ''))
        year = year_raw[:4] if len(year_raw) >= 4 else ''
        
        poster = item.get('poster_path', '')
        overview = item.get('overview', '')
        
        # --- FORMULA MAGICĂ PENTRU SORTARE CORECTĂ ---
        # 1. API-ul returnează cele mai noi primele (Pagina 1).
        # 2. Vrem ca Pagina 1 să aibă timestamp MAI MARE decât Pagina 2.
        # 3. Scădem (Page * 1000 secunde) din timpul curent.
        # Astfel: Pagina 1 e "Acum - 1000s", Pagina 2 e "Acum - 2000s".
        # La sortare DESC, Pagina 1 va fi sus.
        # Scădem și indexul pentru a păstra ordinea corectă în cadrul paginii (item 1 > item 2).
        
        sort_timestamp = base_time - (page * 1000) - index
        added_at = str(sort_timestamp)
        # ---------------------------------------------
        
        rows.append((list_type, media_type, tid, title, year, poster, added_at, overview))
    
    if rows:
        cursor.executemany("INSERT OR REPLACE INTO tmdb_account_lists VALUES (?,?,?,?,?,?,?,?)", rows)
        

def _sync_single_tmdb_custom_list_items(c, list_id, lang): # Parametru nou: lang
    """Helper pentru conținutul unei liste custom."""
    from resources.lib.config import API_KEY, BASE_URL
    import requests
    
    # Ștergem conținutul vechi al acestei liste înainte de a pune cel nou
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
    """Sincronizează recomandările TMDb."""
    from resources.lib.config import TMDB_SESSION_FILE, API_KEY, BASE_URL, LANG
    from resources.lib.utils import read_json
    import requests
    
    session = read_json(TMDB_SESSION_FILE)
    if not session: 
        log("[SYNC] Recommendations: No TMDb session", xbmc.LOGWARNING)
        return
    
    c.execute("DELETE FROM tmdb_recommendations")
    
    total_saved = 0
    aid = session['account_id']
    sid = session['session_id']
    
    for m_type in ['movie', 'tv']:
        try:
            endpoint_suffix = 'movies' if m_type == 'movie' else 'tv'
            fav_url = f"{BASE_URL}/account/{aid}/favorite/{endpoint_suffix}?api_key={API_KEY}&session_id={sid}&language={LANG}&page=1&sort_by=created_at.desc"
            
            # ✅ ELIMINAT: logging URL cu API key
            fav_r = requests.get(fav_url, timeout=10)
            
            if fav_r.status_code != 200:
                log(f"[SYNC] Recommendations {m_type}: API status {fav_r.status_code}", xbmc.LOGWARNING)
                continue
            
            favorites = fav_r.json().get('results', [])
            if not favorites:
                log(f"[SYNC] Recommendations {m_type}: nu ai favorites", xbmc.LOGWARNING)
                continue
            
            log(f"[SYNC] Recommendations {m_type}: găsite {len(favorites)} favorites")
            
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
                log(f"[SYNC] Recommendations {m_type}: salvate {len(rows)} items")
        except Exception as e:
            log(f"[SYNC] Eroare recommendations {m_type}: {e}", xbmc.LOGERROR)
    
    if total_saved > 0:
        log(f"[SYNC] Total recommendations salvate: {total_saved}")
    else:
        log("[SYNC] ATENȚIE: Nu s-au salvat recommendations!", xbmc.LOGWARNING)


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
    # Sortare descrescătoare după string-ul datei (ISO format sortează corect alfabetic)
    c.execute("SELECT * FROM trakt_lists WHERE list_type=? AND media_type=? ORDER BY added_at DESC", (list_type, media_type))
    items = [dict(row) for row in c.fetchall()]
    conn.close()
    return items

def get_history_from_db(media_type):
    if not os.path.exists(DB_PATH): return []
    conn = get_connection()
    c = conn.cursor()
    if media_type == 'movie':
        # ✅ ADĂUGAT: overview la SELECT
        c.execute("SELECT *, last_watched_at as date, overview FROM trakt_watched_movies ORDER BY last_watched_at DESC LIMIT 100")
    else:
        # --- MODIFICARE: JOIN cu tv_meta pentru a lua overview-ul serialului ---
        c.execute("""
            SELECT e.*, m.overview, MAX(e.last_watched_at) as date 
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
    c.execute("SELECT * FROM user_lists ORDER BY name")
    data = [dict(row) for row in c.fetchall()]
    conn.close()
    
    res = []
    for r in data:
        res.append({
            'name': r['name'],
            'ids': {'slug': r['slug'], 'trakt': r['trakt_id']},
            'item_count': r['item_count'],
            'description': r.get('description', '')  # ✅ ADĂUGAT
        })
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
    
    # Am păstrat interogarea ta originală, dar am asigurat ordinea descrescătoare
    # pentru a fi siguri că cele mai recente apar primele.
    c.execute("""
        SELECT e.tmdb_id, 
               MAX(e.title) as show_title, 
               COUNT(*) as watched_count, 
               m.total_episodes,
               MAX(e.last_watched_at) as last_watched
        FROM trakt_watched_episodes e
        LEFT JOIN tv_meta m ON e.tmdb_id = m.tmdb_id
        WHERE e.tmdb_id NOT IN (SELECT tmdb_id FROM trakt_hidden_shows)
        GROUP BY e.tmdb_id
        HAVING (m.total_episodes IS NULL OR m.total_episodes = 0)
               OR (COUNT(*) < m.total_episodes)
        ORDER BY last_watched DESC
        LIMIT 100
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
            'first_air_date': '', # Va fi populat de prefetcher în tmdb_api.py
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
        # ✅ Dacă DB nu există, îl creăm
        init_database()
        return None
    
    conn = get_connection()
    c = conn.cursor()
    
    # ✅ Verificăm dacă tabelul există
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
    """Update imagini folosind cursorul existent (sau conexiune nouă dacă c e None)."""
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
    """Returnează Watchlist sau Favorites din SQL sortate."""
    if not os.path.exists(DB_PATH): return []
    conn = get_connection()
    c = conn.cursor()
    # --- MODIFICARE: Sortare DESC după data adăugării ---
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

def get_tmdb_custom_lists_from_db():
    """Returnează lista listelor personale TMDb."""
    if not os.path.exists(DB_PATH): return []
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM tmdb_custom_lists ORDER BY name")
    items = [dict(row) for row in c.fetchall()]
    conn.close()
    
    # ✅ Returnăm toate câmpurile inclusiv description
    return items

def get_tmdb_custom_list_items_from_db(list_id):
    if not os.path.exists(DB_PATH): return []
    conn = get_connection()
    c = conn.cursor()
    # MODIFICAT: Sortare după sort_index ASC (respectă ordinea de pe site)
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
# METADATA CACHE (JSON STORAGE) - PENTRU NAVIGARE RAPIDĂ ÎN SERIALE
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
    """Citește detaliile sezonului (episoade) din cache cu decompresie zlib."""
    if not os.path.exists(DB_PATH): return None
    
    current_time = int(time.time())
    conn = get_connection()
    c = conn.cursor()
    
    try:
        c.execute("SELECT data, expires FROM meta_cache_seasons WHERE tmdb_id=? AND season_num=?", (str(tmdb_id), int(season_num)))
        row = c.fetchone()
        
        if row:
            data_blob, expires = row
            # Verificăm expirarea
            if current_time > expires:
                return None
            
            try:
                # Încercăm decompresia (pentru date noi comprimate)
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
    """Salvează detaliile sezonului comprimate cu zlib."""
    if not data: return
    
    expires = int(time.time() + (7 * 86400)) # 7 zile
    
    try:
        json_str = json.dumps(data)
        # COMPRIMARE
        compressed_data = zlib.compress(json_str.encode('utf-8'))
        
        should_close = False
        if cursor is None:
            conn = get_connection()
            cursor = conn.cursor()
            should_close = True
            
        cursor.execute("INSERT OR REPLACE INTO meta_cache_seasons VALUES (?,?,?,?)", 
                       (str(tmdb_id), int(season_num), compressed_data, expires))
        
        if should_close:
            cursor.connection.commit()
            cursor.connection.close()
    except Exception as e:
        log(f"[CACHE] Error saving season: {e}", xbmc.LOGERROR)

def update_playback_title(tmdb_id, season, episode, new_title):
    """Actualizează titlul unui episod în progres."""
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
    """Verifică dacă un film e marcat ca vizionat în Trakt."""
    if not os.path.exists(DB_PATH): return False
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT 1 FROM trakt_watched_movies WHERE tmdb_id=?", (str(tmdb_id),))
    found = c.fetchone()
    conn.close()
    return found is not None

def get_movie_watched_count(tmdb_id):
    """Returnează 1 dacă filmul e vizionat, 0 altfel."""
    return 1 if is_movie_watched(tmdb_id) else 0

def get_episode_watched_count(tmdb_id, season=None):
    """Numără episoadele vizionate pentru un serial/sezon."""
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
    """Verifică dacă un episod specific e vizionat."""
    if not os.path.exists(DB_PATH): return False
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT 1 FROM trakt_watched_episodes WHERE tmdb_id=? AND season=? AND episode=?", 
              (str(tmdb_id), int(season), int(episode)))
    found = c.fetchone()
    conn.close()
    return found is not None

# =============================================================================
# WATCHED STATUS CHECKERS (CITIRE DIRECTĂ DIN SQL)
# =============================================================================

def is_movie_watched_sql(tmdb_id):
    """Verifică dacă un film e marcat ca vizionat în SQL."""
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
    """Numără episoadele vizionate pentru un serial/sezon din SQL."""
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
    """Verifică dacă un episod specific e vizionat în SQL."""
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
    """Verifică instant în baza locală dacă serialul este marcat ca dropped/hidden."""
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
        
        # 2. LIMITARE CANTITATIVA (Nou)
        # Pastreaza doar ultimele 200 de intrari accesate (bazat pe expires care e in viitor)
        # Sterge tot ce e in plus fata de cele mai noi 200
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
    Returnează progresul (%) din baza de date locală pentru un singur item.
    Folosită de Player pentru a afișa dialogul de Resume.
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

def update_local_playback_progress(tmdb_id, content_type, season, episode, progress, title, year):
    """
    Salvează sau șterge progresul local.
    progress = Procent (0-100)
    """
    try:
        conn = get_connection()
        c = conn.cursor()
        now = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000Z")
        
        media_type = 'movie' if content_type == 'movie' else 'episode'
        s_val = int(season) if season else 0
        e_val = int(episode) if episode else 0
        
        # 1. Ștergem intrarea veche
        c.execute("DELETE FROM playback_progress WHERE tmdb_id=? AND media_type=? AND season=? AND episode=?", 
                  (str(tmdb_id), media_type, s_val, e_val))
        
        # ============================================================
        # 2. Salvăm DOAR dacă e sub 90% (altfel e watched) SAU dacă e timp exact
        # ============================================================
        if progress >= 1000000:
            # E timp exact! Îl salvăm ca atare
            c.execute("""INSERT INTO playback_progress 
                         (tmdb_id, media_type, season, episode, progress, paused_at, title, year, poster) 
                         VALUES (?,?,?,?,?,?,?,?,?)""",
                      (str(tmdb_id), media_type, s_val, e_val, progress, now, title, str(year), ''))
            log(f"[SYNC] ✓ Local exact-time progress SAVED: {int(progress - 1000000)}s for {title}")
        elif progress < 90:
            # E procentaj standard (ex: descărcat direct de pe Trakt la o sincronizare)
            c.execute("""INSERT INTO playback_progress 
                         (tmdb_id, media_type, season, episode, progress, paused_at, title, year, poster) 
                         VALUES (?,?,?,?,?,?,?,?,?)""",
                      (str(tmdb_id), media_type, s_val, e_val, progress, now, title, str(year), ''))
            log(f"[SYNC] ✓ Local percentage progress SAVED: {progress:.2f}% for {title}")
        else:
            log(f"[SYNC] Progress {progress:.2f}% >= 90%. Removed from In Progress.")
        # ============================================================
        
        conn.commit()
        conn.close()
        
        # --- MODIFICARE: CURĂȚĂM RAM CACHE ---
        # Dacă progresul s-a schimbat, cache-ul RAM nu mai e valabil
        from resources.lib.cache import clear_all_fast_cache
        clear_all_fast_cache()
        # -------------------------------------
        
    except Exception as e:
        log(f"[SYNC] Error saving local progress: {e}", xbmc.LOGERROR)
        
        
def get_plot_in_language(tmdb_id, media_type, lang='ro-RO'):
    """Preia plotul într-o limbă specifică."""
    from resources.lib.config import API_KEY, BASE_URL
    import requests
    
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
    """Worker pentru Up Next: rulează în paralel DOAR apeluri de rețea (fără DB)."""
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

        # Returnăm datele FĂRĂ poster din DB. Posterul va fi rezolvat în firul principal.
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
            
            # Request TMDb (doar pentru poster)
            poster = ''
            tmdb_url = f"https://api.themoviedb.org/3/tv/{tmdb_id}?api_key={tmdb_api_key}"
            r2 = requests.get(tmdb_url, timeout=3)
            if r2.status_code == 200:
                poster = r2.json().get('poster_path', '')

            return (tmdb_id, show.get('title'), nxt['season'], nxt['number'], nxt['title'], nxt['overview'], last_watched, poster, air_date)
    except: pass
    return None

# =============================================================================
# HIDDEN SHOWS HELPERS (NOU)
# =============================================================================

def _get_hidden_show_ids():
    """
    Preia serialele ascunse din Calendar ȘI Progress pe Trakt.
    Paginează rezultatele corect (limita oficială Trakt e 100).
    """
    from resources.lib import trakt_api
    
    hidden = {'tmdb': set(), 'trakt': set(), 'imdb': set(), 'tvdb': set()}
    
    for section in ('calendar', 'progress_watched', 'dropped'):
        try:
            page = 1
            while True:
                # FIX: Trakt suportă maxim 100 per pagină
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
                            
                # Dacă primim sub 100, înseamnă că asta e ultima pagină
                if len(result) < 100:
                    break
                page += 1
        except Exception as e:
            from resources.lib.utils import log
            import xbmc
            log(f"[SYNC] Eroare preluare hidden/{section}: {e}", xbmc.LOGWARNING)
    
    total = len(hidden['tmdb'])
    if total > 0:
        from resources.lib.utils import log
        log(f"[SYNC] Hidden shows complet: {total} seriale gasite")
    
    return hidden

def _sync_hidden_shows(c):
    """Sincronizează serialele ascunse în DB local pentru filtrare ultra-rapidă."""
    hidden_ids = _get_hidden_show_ids()
    c.execute("DELETE FROM trakt_hidden_shows")
    rows = [(tid,) for tid in hidden_ids['tmdb'] if tid]
    if rows:
        c.executemany("INSERT OR REPLACE INTO trakt_hidden_shows VALUES (?)", rows)
        log(f"[SYNC] Salvate {len(rows)} seriale hidden in baza de date locala.")


def _is_show_hidden(show_ids, hidden):
    """Verifică dacă un serial e în lista hidden. Compară strict per tip de ID."""
    if not hidden:
        return False
    for key in ('tmdb', 'trakt', 'imdb', 'tvdb'):
        val = show_ids.get(key)
        if val and str(val) in hidden.get(key, set()):
            return True
    return False


def _sync_up_next(c, token):
    """Coordoneaza thread-urile si salveaza totul la final. FILTREAZĂ hidden/dropped."""
    from resources.lib import trakt_api
    from resources.lib.config import TRAKT_CLIENT_ID, API_KEY
    
    watched = trakt_api.trakt_api_request("/sync/watched/shows")
    if not watched: return
    
    # ══════════════════════════════════════════════════════════
    # ADĂUGAT: Filtrare seriale hidden/dropped ÎNAINTE de procesare
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
                log(f"[SYNC] Up Next: {removed} seriale hidden/dropped eliminate "
                    f"din {before_count} total.")
    except Exception as e:
        log(f"[SYNC] Up Next: Eroare filtrare hidden: {e}", xbmc.LOGWARNING)
        # Continuăm fără filtrare dacă eșuează
    # ══════════════════════════════════════════════════════════
    
    # Sortăm după ultima vizionare
    watched.sort(key=lambda x: x.get('last_watched_at', ''), reverse=True)
    top_shows = watched[:500]
    
    worker_args = [(item, token, TRAKT_CLIENT_ID, API_KEY) for item in top_shows]

    # --- ÎNCEPUT MODIFICARE: Reducem max_workers pentru a evita eroarea 429 ---
    # 20 de fire simultane este prea mult pentru Trakt și cauzează "Too Many Requests".
    # 5 fire de execuție oferă un echilibru perfect între viteză și stabilitate (cum are SALTS).
    with ThreadPoolExecutor(max_workers=5) as executor:
    # --- SFÂRȘIT MODIFICARE ---
        results = list(executor.map(fetch_up_next_worker, worker_args))
    
    # Ștergem tabelul doar înainte de scriere
    c.execute("DELETE FROM trakt_next_episodes")
    
    clean_rows = [r for r in results if r]
    
    if clean_rows:
        # Salvare bulk
        c.executemany("INSERT OR REPLACE INTO trakt_next_episodes VALUES (?,?,?,?,?,?,?,?,?)", clean_rows)
        
        # Salvare postere bulk
        for row in clean_rows:
            if row[7]:  # daca are poster
                update_item_images(c, row[0], 'show', row[7], '')
    
    log(f"[SYNC] Up Next: {len(clean_rows)} seriale actualizate "
        f"(din {len(top_shows)} verificate, {len(watched)} după filtrare).")

def _sync_trakt_favorites(c):
    """Sincronizează Favoritele Trakt (inimioară)."""
    from resources.lib import trakt_api
    
    data = trakt_api.trakt_api_request("/users/me/favorites", params={'extended': 'full'})
    if not data or not isinstance(data, list): return

    c.execute("DELETE FROM trakt_favorites")
    rows = []
    for i, item in enumerate(data):
        m_type = item.get('type') # 'movie' sau 'show'
        raw = item.get(m_type)
        if not raw: continue
        
        tmdb_id = str(raw.get('ids', {}).get('tmdb', ''))
        if not tmdb_id: continue
        
        rows.append((m_type, tmdb_id, raw.get('title'), str(raw.get('year', '')), '', raw.get('overview', ''), i))
    
    if rows:
        c.executemany("INSERT OR REPLACE INTO trakt_favorites VALUES (?,?,?,?,?,?,?)", rows)
        log(f"[SYNC] Salvate {len(rows)} favorite Trakt.")

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
        log(f"[DB] Eroare citire trakt_next_episodes: {e}. Re-inițializare...", xbmc.LOGERROR)
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
        # MODIFICAT: ORDER BY rank DESC (rank-ul e timestamp-ul adăugării la inserarea manuală)
        c.execute("SELECT * FROM trakt_favorites WHERE media_type=? ORDER BY rank DESC", (db_type,))
        items = [dict(row) for row in c.fetchall()]
        conn.close()
        return items
    except Exception as e:
        from resources.lib.utils import log
        import xbmc
        log(f"[DB] Eroare citire trakt_favorites: {e}. Re-inițializare...", xbmc.LOGERROR)
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
    
    # FORȚĂM TRAKT ID PENTRU SERIALE (Prevenim erorile pe site-ul lor)
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

    # FORȚĂM TRAKT ID PENTRU SERIALE 
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
        # 2. INSERARE ÎN SQL LOCAL
        if content_type == 'movie':
            c.execute("INSERT OR REPLACE INTO trakt_watched_movies VALUES (?,?,?,?,?,?,?)", 
                      (tid, title_val, str(now)[:4], now, poster_val, backdrop_val, overview_val))
            c.execute("DELETE FROM playback_progress WHERE tmdb_id=? AND media_type='movie'", (tid,))
        
        elif season is not None and episode is not None:
            db_show_title = show_name if 'show_name' in locals() else "Unknown Show"
            c.execute("INSERT OR REPLACE INTO trakt_watched_episodes VALUES (?,?,?,?,?)", 
                      (tid, int(season), int(episode), db_show_title, now))
            c.execute("SELECT 1 FROM tv_meta WHERE tmdb_id=?", (tid,))
            if not c.fetchone():
                c.execute("INSERT OR REPLACE INTO tv_meta (tmdb_id, total_episodes, poster, backdrop, overview) VALUES (?,?,?,?,?)", 
                          (tid, 0, poster_val, backdrop_val, overview_val))
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

    # 3. NOTIFICARE ȘI REFRESH UP NEXT
    if notify:
        msg = f"[B][COLOR yellow]{title_val}[/COLOR][/B] marcat vizionat in [B][COLOR pink]Trakt[/COLOR][/B]"
        xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", msg, TRAKT_ICON, 3000, False)
    
    if sync_trakt:
        threading.Thread(target=sync_single_watched_to_trakt, args=(tmdb_id, content_type, season, episode)).start()
    
    if content_type in ['tv', 'show', 'season', 'episode'] or season is not None:
            try:
                conn = get_connection()
                conn.execute("DELETE FROM trakt_next_episodes WHERE tmdb_id=?", (str(tmdb_id),))
                conn.commit()
                conn.close()
                threading.Thread(target=refresh_next_episode, args=(tmdb_id,)).start()
            except: pass
            
    # --- START: JSON-RPC PENTRU KODI LIBRARY (INSTANT & SILENT) ---
    year_val = str(datetime.datetime.now().year)
    threading.Thread(target=update_kodi_library_watchstatus, args=(content_type, 'mark_as_watched', title_val, year_val, season, episode), daemon=True).start()
    # --- END ---

    from resources.lib.cache import clear_all_fast_cache
    clear_all_fast_cache()
    
    # Adaugă IF-ul aici:
    if refresh_ui:
        xbmc.executebuiltin("Container.Refresh")


def mark_as_unwatched_internal(tmdb_id, content_type, season=None, episode=None, sync_trakt=True, refresh_ui=True):
    import threading
    from resources.lib.config import ADDON
    
    TRAKT_ICON = os.path.join(ADDON.getAddonInfo('path'), 'resources', 'media', 'trakt.png')
    tid = str(tmdb_id)
    conn = get_connection()
    c = conn.cursor()
    
    title_display = "Element"

    try:
        # 1. EXTRAGERE TITLU (Pentru notificare, înainte de ștergere)
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

        # 2. ȘTERGERE EFECTIVĂ SQL
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

    # 3. CURĂȚARE UP NEXT
    if content_type in['tv', 'show', 'season', 'episode'] or season is not None:
        try:
            conn = get_connection()
            conn.execute("DELETE FROM trakt_next_episodes WHERE tmdb_id=?", (str(tmdb_id),))
            conn.commit()
            conn.close()
            # --- ÎNCEPUT MODIFICARE: Eliminăm refresh_next_episode aici! ---
            # Dacă am dat unwatch la primul episod, s-ar putea ca tot serialul să devină un-watched.
            # Dacă re-cerem imediat de la Trakt, serverul lor ne va da date vechi din cache-ul LOR.
            # E mai sigur să ștergem doar local. Dacă user-ul se uită din nou, "Smart Sync" 
            # va reface lista corect la următoarea pornire sau la următoarea vizionare.
            # 
            # AM ȘTERS LINIA: threading.Thread(target=refresh_next_episode, args=(tmdb_id,)).start()
            # --- SFÂRȘIT MODIFICARE ---
        except: pass

    # 4. NOTIFICARE ȘI SYNC TRAKT
    msg = f"[B][COLOR yellow]{title_display}[/COLOR][/B] marcat nevizionat in [B][COLOR pink]Trakt[/COLOR][/B]"
    xbmcgui.Dialog().notification("[B][COLOR pink]Trakt[/COLOR][/B]", msg, TRAKT_ICON, 3000, False)

    if sync_trakt:
        threading.Thread(target=sync_single_unwatched_to_trakt, args=(tmdb_id, content_type, season, episode)).start()

    # --- START SALTS: JSON-RPC PENTRU KODI LIBRARY (INSTANT & SILENT) ---
    year_val = str(datetime.datetime.now().year)
    threading.Thread(target=update_kodi_library_watchstatus, args=(content_type, 'mark_as_unwatched', title_display, year_val, season, episode), daemon=True).start()
    # --- END SALTS ---

    from resources.lib.cache import clear_all_fast_cache
    clear_all_fast_cache()

    # Adaugă IF-ul aici:
    if refresh_ui:
        xbmc.executebuiltin("Container.Refresh")


def refresh_next_episode(tmdb_id, ignore_hidden=False):
    from resources.lib import trakt_api
    from resources.lib.config import API_KEY

    
    # --- PAUZĂ CRITICĂ --- 
    # Îi dăm voie serverului Trakt să proceseze ștergerea/adăugarea la istoric
    # altfel ne va returna tot episodul de dinainte.
    time.sleep(1.5) 
    
    tmdb_id = str(tmdb_id)
    trakt_id = None
    show_title = ''
    poster = ''
    
    log(f"[UP NEXT] Refreshing next episode for TMDb {tmdb_id}...")
    
    # ══════════════════════════════════════════════════════════
    # PAS 1: Găsim Trakt ID prin Trakt Search API
    # ══════════════════════════════════════════════════════════
    try:
        res = trakt_api.trakt_api_request(
            f"/search/tmdb/{tmdb_id}",
            params={'type': 'show'}
        )
        if res and isinstance(res, list) and len(res) > 0:
            show_data = res[0].get('show', {})
            trakt_id = show_data.get('ids', {}).get('trakt')
            show_title = show_data.get('title', '')
    except Exception as e:
        log(f"[UP NEXT] Search error: {e}", xbmc.LOGWARNING)
    
    if not trakt_id:
        log(f"[UP NEXT] ✗ Nu am găsit Trakt ID pentru TMDb {tmdb_id}",
            xbmc.LOGWARNING)
        xbmc.executebuiltin("Container.Refresh")
        return
    
    # ══════════════════════════════════════════════════════════
    # PAS 2: Cerem Next Episode de la Trakt
    # ══════════════════════════════════════════════════════════
    try:
        progress = trakt_api.trakt_api_request(
            f"/shows/{trakt_id}/progress/watched"
        )
    except:
        progress = None
    
    if not progress or not progress.get('next_episode'):
        log(f"[UP NEXT] '{show_title}' complet. Fără episod nou.")
        from resources.lib.cache import clear_all_fast_cache
        clear_all_fast_cache()
        xbmc.executebuiltin("Container.Refresh")
        return
    
    nxt = progress['next_episode']
    air_date = nxt.get('first_aired', '')
    if air_date:
        air_date = air_date.split('T')[0]
    
    # ══════════════════════════════════════════════════════════
    # PAS 3: Poster (cache local → TMDb API fallback)
    # ══════════════════════════════════════════════════════════
    try:
        poster = get_poster_from_db(tmdb_id, 'show') or ''
        
        if not poster:
            tmdb_url = f"https://api.themoviedb.org/3/tv/{tmdb_id}?api_key={API_KEY}"
            r = requests.get(tmdb_url, timeout=3)
            if r.status_code == 200:
                poster = r.json().get('poster_path', '')
    except:
        pass
    
    # ══════════════════════════════════════════════════════════
    # PAS 4: Verificare hidden (Evităm fals-pozitivele la Unhide)
    # ══════════════════════════════════════════════════════════
    if not ignore_hidden:
        try:
            hidden = _get_hidden_show_ids()
            show_ids = {'tmdb': tmdb_id, 'trakt': str(trakt_id)}
            if _is_show_hidden(show_ids, hidden):
                log(f"[UP NEXT] '{show_title}' e hidden/dropped. Skip.")
                xbmc.executebuiltin("Container.Refresh")
                return
        except:
            pass
    
    # ══════════════════════════════════════════════════════════
    # PAS 5: Salvare în DB + Refresh UI
    # ══════════════════════════════════════════════════════════
    try:
        # Generăm timestamp-ul CURENT (acum) în format Trakt.
        # Asta rezolvă problema "apare la coadă până la sync", pentru că 
        # îi spunem bazei de date locale că am vizionat acest serial FIX ACUM.
        import datetime
        now_str = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")

        conn = get_connection()
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO trakt_next_episodes VALUES (?,?,?,?,?,?,?,?,?)",
            (tmdb_id, show_title, nxt['season'], nxt['number'],
             nxt.get('title', ''), nxt.get('overview', ''),
             now_str, poster, air_date) # <-- MODIFICARE CHEIE: Am pus now_str în loc de '' la last_watched_at
        )
        conn.commit()
        conn.close()
        
        log(f"[UP NEXT] ✓ {show_title} → "
            f"S{nxt['season']:02d}E{nxt['number']:02d} - {nxt.get('title', '')}")
        
    except Exception as e:
        log(f"[UP NEXT] Eroare salvare: {e}", xbmc.LOGERROR)
    
    # ══════════════════════════════════════════════════════════
    # PAS 6: Refresh UI (Datele noi sunt sigure în DB)
    # ══════════════════════════════════════════════════════════
    # --- START SALTS: ELIMINAT REFRESH-UL DUBLAT DIN BACKGROUND ---
    # Fără Container.Refresh aici! Evităm cercul de încărcare de 40 secunde
    # care îți bloca Kodi-ul și trezea alte addonuri să scaneze.
    # Noul episod "Up Next" este salvat în DB și va fi afișat automat la următoarea navigare.
    pass
    # --- END SALTS ---


# =============================================================================
# SALTS IMPLEMENTATION: NATIVE KODI LIBRARY JSON-RPC SYNC
# =============================================================================
def update_kodi_library_watchstatus(mediatype, action, title, year, season=None, episode=None):
    """
    Sincronizeaza bifa instantaneu cu libraria locala Kodi prin JSON-RPC.
    Această metodă NU declanșează alarme/scanări din partea altor addonuri.
    """
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


