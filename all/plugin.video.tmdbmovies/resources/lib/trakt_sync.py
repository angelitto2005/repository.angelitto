import sqlite3
import os
import requests
import xbmc
import xbmcgui
import xbmcvfs
import datetime
import time
import json
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
                xbmcgui.Dialog().notification("[B][COLOR FFFDBD01]TMDb Movies[/COLOR][/B]", "Cache Reset (Size Limit)", os.path.join(ADDON.getAddonInfo('path'), 'icon.png'))
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
    """
    if not date_str: return datetime.datetime.min
    try:
        # Eliminăm 'Z' de la final
        d = date_str.replace('Z', '')
        
        # Dacă avem punct, tăiem milisecundele pentru comparație (păstrăm doar secunde)
        if '.' in d:
            d = d.split('.')[0]
            
        return datetime.datetime.strptime(d, "%Y-%m-%dT%H:%M:%S")
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
            xbmcgui.Dialog().notification("[B][COLOR FFFDBD01]TMDb Movies[/COLOR][/B]", "Sincronizare deja în curs...", os.path.join(ADDON.getAddonInfo('path'), 'icon.png'))
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
            p_dialog.create("[B][COLOR FFFDBD01]TMDb Movies[/COLOR][/B]", "Verificare modificări Trakt...")
        
        try:
            log("[SYNC] === STARTING SMART SYNC ===")
            
            activities = get_trakt_last_activities()
            
            # --- MODIFICARE: Gestionare Eșec API Trakt ---
            if not activities and get_trakt_token():
                log("[SYNC] Nu am putut obține activitățile Trakt (API Error). Forțăm Sincronizare Totală.", xbmc.LOGWARNING)
                force = True # Transformăm automat în Full Sync
            # ---------------------------------------------

            local_sync = get_local_last_sync()
            new_sync = local_sync.copy() if local_sync else {}
            
            conn = get_connection()
            c = conn.cursor()
            
            # --- 1. WATCHED MOVIES ---
            # Forțăm sync dacă timestamp-ul e vechi SAU dacă tabelul este gol
            should_sync_movies = force or needs_sync('movies_watched', activities, local_sync) or is_table_empty(c, 'trakt_watched_movies')
            if should_sync_movies:
                if not silent and p_dialog: p_dialog.update(10, message="Sync: [B][COLOR pink]Filme Vizionate[/COLOR][/B]")
                _sync_watched_movies(c)
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
                _sync_user_lists(c)
                if activities and activities.get('lists', {}).get('updated_at'):
                    new_sync['lists'] = activities['lists']['updated_at']

            # --- SALVĂM ȘI ELIBERĂM DB ÎNAINTE DE THREADING ---
            conn.commit()

            # --- 6. IN PROGRESS & UP NEXT (Threaded) ---
            log("[SYNC] 6. Syncing In Progress & Up Next...")
            if not silent and p_dialog: p_dialog.update(75, message="Sync: [B][COLOR pink]In Progress & Up Next[/COLOR][/B]")
            _sync_playback(c)
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
                if not silent and p_dialog: p_dialog.update(95, message="Sync: [B][COLOR FF00CED1]Cont TMDb[/COLOR][/B]")
                try:
                    _sync_tmdb_data(c)
                except: pass

            conn.commit()
            conn.close()
            
            save_local_last_sync(new_sync)
            cleanup_database()
            
            log("[SYNC] === SYNC COMPLETE ===")
            
            if not silent and p_dialog:
                p_dialog.close()
                xbmcgui.Dialog().notification("[B][COLOR FFFDBD01]TMDb Movies[/COLOR][/B]", "Sincronizare Completă", os.path.join(ADDON.getAddonInfo('path'), 'icon.png'))
                
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
    
    # 1. Mărim limita la 100 pentru a prinde mai multe filme începute
    data = trakt_api.trakt_api_request("/sync/playback", params={'limit': 100, 'extended': 'full'})
    
    if not data or not isinstance(data, list): 
        return
    
    c.execute("DELETE FROM playback_progress")
    rows = []
    
    for item in data:
        # Filtru de siguranță: ignorăm ce e abia început (<1%) sau terminat (>98%)
        progress = item.get('progress', 0)
        if progress <= 1 or progress >= 99: 
            continue
            
        typ = item.get('type')
        meta = item.get('movie') if typ == 'movie' else item.get('show')
        if not meta: continue
        
        # --- FIX: RECUPERARE ID ---
        ids = meta.get('ids') or {}
        tid = str(ids.get('tmdb', ''))
        imdb_id = ids.get('imdb', '')
        
        # Dacă lipsește TMDb ID, încercăm să-l găsim prin IMDb (Convertire)
        if (not tid or tid == 'None') and imdb_id:
            try:
                find_url = f"{BASE_URL}/find/{imdb_id}?api_key={API_KEY}&external_source=imdb_id"
                find_data = get_json(find_url)
                if typ == 'movie' and find_data.get('movie_results'):
                    tid = str(find_data['movie_results'][0]['id'])
                elif typ == 'show' and find_data.get('tv_results'):
                    tid = str(find_data['tv_results'][0]['id'])
            except: pass
            
        # Dacă tot nu avem ID, sărim peste
        if not tid or tid == 'None': 
            continue
        
        s, e = 0, 0
        year = str(meta.get('year', ''))
        
        if typ == 'episode':
            ep = item.get('episode') or {}
            s = ep.get('season', 0)
            e = ep.get('number', 0)
            
            show_title = meta.get('title', 'Unknown Show')
            ep_title = ep.get('title', '')
            title = f"{show_title} - S{s:02d}E{e:02d}"
            if ep_title:
                title += f" - {ep_title}"
        else:
            title = meta.get('title', 'Unknown Movie')
            
        # Adăugăm în lista de inserare
        rows.append((
            tid, typ, s, e, 
            progress, 
            item.get('paused_at'), 
            title, 
            year, 
            '' 
        ))
        
    if rows: 
        c.executemany("INSERT OR REPLACE INTO playback_progress VALUES (?,?,?,?,?,?,?,?,?)", rows)
        log(f"[SYNC] Saved {len(rows)} items in progress (Limit 100 + ID Fix).")


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

    # 1. WATCHLIST & FAVORITES (Direct)
    endpoints = [('watchlist', 'movies', 'movie'), ('watchlist', 'tv', 'tv'), ('favorite', 'movies', 'movie'), ('favorite', 'tv', 'tv')]
    for ltype, endpoint_media, db_media in endpoints:
        try:
            # Forțăm sync dacă tabelul e gol
            if force or is_table_empty(c, 'tmdb_account_lists'):
                c.execute("DELETE FROM tmdb_account_lists WHERE list_type=? AND media_type=?", (ltype, db_media))
                page = 1
                while True:
                    url = f"{BASE_URL}/account/{aid}/{ltype}/{endpoint_media}?api_key={API_KEY}&session_id={sid}&language={lang}&page={page}&sort_by=created_at.desc"
                    r = requests.get(url, timeout=10)
                    if r.status_code != 200: break
                    data = r.json()
                    results = data.get('results', [])
                    if not results: break
                    _sync_tmdb_account_list_single(c, ltype, db_media, results, page)
                    if page >= data.get('total_pages', 1): break
                    page += 1
        except: pass

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
                # Sincronizăm dacă:
                # 1. Este Sincronizare Manuală (_force)
                # 2. Lista este nouă (nu există în _local_map)
                # 3. Numărul de iteme de pe site s-a schimbat
                should_sync = _force or list_id not in _local_map or _local_map.get(list_id) != remote_count
                
                # 4. VERIFICARE EXTRA: Chiar dacă numărul e egal, verificăm dacă tabelul de iteme e gol
                # (Asta repară bug-ul după "Clear Cache")
                if not should_sync:
                    try:
                        # Verificăm dacă avem efectiv iteme salvate pentru această listă
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
                # Transmitem sid, aid, lang etc. ca argumente pentru a evita erorile de scope
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
    
    import time
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
    
    import time
    import zlib # Asigură-te că e importat
    
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
    
    import time
    import zlib
    
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

def cleanup_database():
    if not os.path.exists(DB_PATH): return
    
    import time
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
        # 2. Salvăm DOAR dacă e sub 90% (altfel e watched)
        # ============================================================
        # Backwards compatibility: dacă e marker (>= 1000000), convertim la procent
        if progress >= 1000000:
            # Format vechi - ignorăm, nu mai salvăm așa
            log(f"[SYNC] Ignoring legacy marker format: {progress}")
        elif progress < 90:
            c.execute("""INSERT INTO playback_progress 
                         (tmdb_id, media_type, season, episode, progress, paused_at, title, year, poster) 
                         VALUES (?,?,?,?,?,?,?,?,?)""",
                      (str(tmdb_id), media_type, s_val, e_val, progress, now, title, str(year), ''))
            log(f"[SYNC] ✓ Local progress SAVED: {progress:.2f}% for {title}")
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
    """Worker ultra-rapid: doar retea, fara baza de date."""
    item, token, trakt_client_id, tmdb_api_key = args
    
    show = item.get('show', {})
    trakt_id = show.get('ids', {}).get('trakt')
    tmdb_id = str(show.get('ids', {}).get('tmdb', ''))
    last_watched = item.get('last_watched_at', '')
    
    if not trakt_id or not tmdb_id: return None

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


def _sync_up_next(c, token):
    """Coordoneaza thread-urile si salveaza totul la final intr-o singura operatiune."""
    from resources.lib import trakt_api
    from resources.lib.config import TRAKT_CLIENT_ID, API_KEY
    
    watched = trakt_api.trakt_api_request("/sync/watched/shows")
    if not watched: return
    
    # Sortăm după ultima vizionare
    watched.sort(key=lambda x: x.get('last_watched_at', ''), reverse=True)
    
    # --- MODIFICARE: Mărim limita de la 100 la 500 ---
    # Asta asigură că găsim episoade noi chiar dacă te-ai uitat la 300 de seriale vechi între timp
    top_shows = watched[:500] 
    
    worker_args = [(item, token, TRAKT_CLIENT_ID, API_KEY) for item in top_shows]

    # --- MODIFICARE: 20 Threads pentru a procesa 500 de iteme rapid ---
    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(fetch_up_next_worker, worker_args))
    
    # Ștergem tabelul doar înainte de scriere
    c.execute("DELETE FROM trakt_next_episodes")
    
    clean_rows = [r for r in results if r]
    
    if clean_rows:
        # Salvare bulk
        c.executemany("INSERT OR REPLACE INTO trakt_next_episodes VALUES (?,?,?,?,?,?,?,?,?)", clean_rows)
        
        # Salvare postere bulk
        for row in clean_rows:
            if row[7]: # daca are poster
                update_item_images(c, row[0], 'show', row[7], '')
    
    log(f"[SYNC] Up Next: {len(clean_rows)} seriale actualizate (din {len(top_shows)} verificate).")


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
    if not os.path.exists(DB_PATH): return []
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM trakt_next_episodes ORDER BY last_watched_at DESC")
    items = [dict(row) for row in c.fetchall()]
    conn.close()
    return items

def get_trakt_favorites_from_db(media_type):
    if not os.path.exists(DB_PATH): return []
    conn = get_connection()
    c = conn.cursor()
    db_type = 'movie' if media_type == 'movies' else 'show'
    # MODIFICAT: ORDER BY rank DESC (rank-ul e timestamp-ul adăugării la inserarea manuală)
    c.execute("SELECT * FROM trakt_favorites WHERE media_type=? ORDER BY rank DESC", (db_type,))
    items = [dict(row) for row in c.fetchall()]
    conn.close()
    return items

# ===================== WATCHED STATUS WORKERS =====================

def sync_single_watched_to_trakt(tmdb_id, content_type, season=None, episode=None):
    from resources.lib import trakt_api
    if content_type == 'movie':
        data = {'movies': [{'ids': {'tmdb': int(tmdb_id)}, 'watched_at': datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")}]}
    elif content_type in ['tv', 'show'] and not season:
        # Mark whole show
        data = {'shows': [{'ids': {'tmdb': int(tmdb_id)}, 'watched_at': datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")}]}
    else:
        # Mark episode
        data = {'shows': [{'ids': {'tmdb': int(tmdb_id)}, 'seasons': [{'number': int(season), 'episodes': [{'number': int(episode), 'watched_at': datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")}]}]}]}
    trakt_api.trakt_api_request("/sync/history", method='POST', data=data)

def sync_single_unwatched_to_trakt(tmdb_id, content_type, season=None, episode=None):
    from resources.lib import trakt_api
    if content_type == 'movie':
        data = {'movies': [{'ids': {'tmdb': int(tmdb_id)}}]}
    elif content_type in ['tv', 'show'] and not season:
        data = {'shows': [{'ids': {'tmdb': int(tmdb_id)}}]}
    else:
        data = {'shows': [{'ids': {'tmdb': int(tmdb_id)}, 'seasons': [{'number': int(season), 'episodes': [{'number': int(episode)}]}]}]}
    trakt_api.trakt_api_request("/sync/history/remove", method='POST', data=data)

def mark_as_watched_internal(tmdb_id, content_type, season=None, episode=None, notify=True, sync_trakt=True):
    # Importuri locale
    from resources.lib import tmdb_api
    from resources.lib.config import IMG_BASE, BACKDROP_BASE, ADDON
    import threading

    TRAKT_ICON = os.path.join(ADDON.getAddonInfo('path'), 'resources', 'media', 'trakt.png')
    tid = str(tmdb_id)
    conn = get_connection()
    c = conn.cursor()
    now = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000Z")
    
    # Variabile implicite
    title_val = "Unknown" # Acesta va fi folosit pentru Notificare (galben)
    poster_val = ""
    backdrop_val = ""
    overview_val = ""

    # 1. PRELUARE METADATE
    try:
        if content_type == 'movie':
            details = tmdb_api.get_tmdb_item_details(tid, 'movie') or {}
            title_val = details.get('title', 'Unknown Movie')
            poster_val = f"{IMG_BASE}{details.get('poster_path', '')}" if details.get('poster_path') else ""
            backdrop_val = f"{BACKDROP_BASE}{details.get('backdrop_path', '')}" if details.get('backdrop_path') else ""
            overview_val = details.get('overview', '')
        
        elif content_type in ['tv', 'episode', 'show']:
            show_details = tmdb_api.get_tmdb_item_details(tid, 'tv') or {}
            show_name = show_details.get('name', 'Unknown Show')
            poster_val = f"{IMG_BASE}{show_details.get('poster_path', '')}" if show_details.get('poster_path') else ""
            backdrop_val = f"{BACKDROP_BASE}{show_details.get('backdrop_path', '')}" if show_details.get('backdrop_path') else ""
            overview_val = show_details.get('overview', '')
            
            # Aici facem diferența între ce salvăm și ce afișăm
            if season and episode:
                # Titlul pentru notificare (ex: Wonder Man - S01E02)
                title_val = f"{show_name} - S{int(season):02d}E{int(episode):02d}"
            else:
                title_val = show_name
    except: 
        pass

    try:
        # 2. INSERARE ÎN SQL
        if content_type == 'movie':
            c.execute("INSERT OR REPLACE INTO trakt_watched_movies VALUES (?,?,?,?,?,?,?)", 
                      (tid, title_val, str(now)[:4], now, poster_val, backdrop_val, overview_val))
            c.execute("DELETE FROM playback_progress WHERE tmdb_id=? AND media_type='movie'", (tid,))
        
        elif season and episode:
            # --- FIX BUG ISTORIC: Salvăm doar numele serialului în DB, nu S01E01 ---
            db_show_title = show_name if 'show_name' in locals() else "Unknown Show"
            
            c.execute("INSERT OR REPLACE INTO trakt_watched_episodes VALUES (?,?,?,?,?)", 
                      (tid, int(season), int(episode), db_show_title, now))
            
            # Asigurăm tv_meta
            c.execute("SELECT 1 FROM tv_meta WHERE tmdb_id=?", (tid,))
            if not c.fetchone():
                c.execute("INSERT OR REPLACE INTO tv_meta (tmdb_id, total_episodes, poster, backdrop, overview) VALUES (?,?,?,?,?)", 
                          (tid, 0, poster_val, backdrop_val, overview_val))

            c.execute("DELETE FROM playback_progress WHERE tmdb_id=? AND season=? AND episode=?", (tid, int(season), int(episode)))
        
        elif content_type in ['tv', 'show']:
            # Marcare tot serialul
            show_data = tmdb_api.get_tmdb_item_details(tid, 'tv')
            if show_data:
                rows_to_insert = []
                # Folosim numele curat al serialului pentru DB
                clean_name = show_data.get('name', 'Unknown Show')
                
                for s in show_data.get('seasons', []):
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

    # --- MODIFICARE: CURĂȚARE UP NEXT PENTRU ACTUALIZARE IMEDIATĂ ---
    if season and episode:
        try:
            conn = get_connection()
            # Ștergem vechiul episod
            conn.execute("DELETE FROM trakt_next_episodes WHERE tmdb_id=?", (str(tmdb_id),))
            conn.commit()
            conn.close()
            
            # --- MODIFICARE: ADUCEM EPISODUL NOU IMEDIAT ---
            threading.Thread(target=refresh_next_episode, args=(tmdb_id,)).start()
            # -----------------------------------------------
        except: pass
    # --------------------------------------------------------------

    # 3. NOTIFICARE
    if notify:
        msg = f"[B][COLOR yellow]{title_val}[/COLOR][/B] marcat vizionat"
        xbmcgui.Dialog().notification("Trakt", msg, TRAKT_ICON, 3000, False)
    
    if sync_trakt:
        threading.Thread(target=sync_single_watched_to_trakt, args=(tmdb_id, content_type, season, episode)).start()
    
    from resources.lib.cache import clear_all_fast_cache
    clear_all_fast_cache()
    
    time.sleep(0.2)
    xbmc.executebuiltin("Container.Refresh")


def mark_as_unwatched_internal(tmdb_id, content_type, season=None, episode=None, sync_trakt=True):
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
        elif season and episode:
            c.execute("SELECT title FROM trakt_watched_episodes WHERE tmdb_id=? LIMIT 1", (tid,))
            r = c.fetchone()
            # Dacă titlul în DB e generic sau formatat, îl folosim
            if r: 
                # Uneori titlul din DB e doar numele serialului, alteori e full. 
                # Încercăm să-l facem frumos.
                base_title = r[0].split(' - S')[0] 
                title_display = f"{base_title} - S{int(season):02d}E{int(episode):02d}"
            else:
                title_display = f"S{season}E{episode}"
        elif content_type in ['tv', 'show']:
            c.execute("SELECT title FROM trakt_watched_episodes WHERE tmdb_id=? LIMIT 1", (tid,))
            r = c.fetchone()
            if r: 
                title_display = r[0].split(' - S')[0] # Luăm doar numele serialului
            else:
                title_display = "Serial"

        # 2. ȘTERGERE EFECTIVĂ
        if content_type == 'movie':
            c.execute("DELETE FROM trakt_watched_movies WHERE tmdb_id=?", (tid,))
            c.execute("DELETE FROM playback_progress WHERE tmdb_id=? AND media_type='movie'", (tid,))
        elif season and episode:
            c.execute("DELETE FROM trakt_watched_episodes WHERE tmdb_id=? AND season=? AND episode=?", (tid, int(season), int(episode)))
            c.execute("DELETE FROM playback_progress WHERE tmdb_id=? AND season=? AND episode=?", (tid, int(season), int(episode)))
        elif content_type in ['tv', 'show']:
            c.execute("DELETE FROM trakt_watched_episodes WHERE tmdb_id=?", (tid,))
            c.execute("DELETE FROM playback_progress WHERE tmdb_id=?", (tid,))

        conn.commit()
    except: pass
    finally: conn.close()

    # --- MODIFICARE: CURĂȚARE UP NEXT DACĂ E EPISOD ---
    if season and episode:
        try:
            conn = get_connection()
            conn.execute("DELETE FROM trakt_next_episodes WHERE tmdb_id=?", (str(tmdb_id),))
            conn.commit()
            conn.close()
        except: pass
    # --------------------------------------------------

    # 3. NOTIFICARE ȘI SYNC
    msg = f"[B][COLOR yellow]{title_display}[/COLOR][/B] marcat nevizionat"
    xbmcgui.Dialog().notification("Trakt", msg, TRAKT_ICON, 3000, False)

    from resources.lib.cache import clear_all_fast_cache
    clear_all_fast_cache()

    if sync_trakt:
        threading.Thread(target=sync_single_unwatched_to_trakt, args=(tmdb_id, content_type, season, episode)).start()

    time.sleep(0.2)
    xbmc.executebuiltin("Container.Refresh")


def refresh_next_episode(tmdb_id):
    """Actualizează instantaneu Up Next pentru un singur serial."""
    from resources.lib import trakt_api
    from resources.lib.config import API_KEY
    import requests
    
    # 1. Găsim Trakt ID (necesar pentru API)
    # Încercăm să-l luăm din user_lists sau facem convert
    conn = get_connection()
    c = conn.cursor()
    
    # Obținem datele despre serial din cache-ul TMDb existent
    poster = ''
    show_title = ''
    try:
        # Citim din cache-ul de metadate (dacă există)
        import zlib, json, time
        c.execute("SELECT data FROM meta_cache_items WHERE tmdb_id=? AND media_type='tv'", (str(tmdb_id),))
        row = c.fetchone()
        if row:
            if isinstance(row[0], bytes): data = json.loads(zlib.decompress(row[0]))
            else: data = json.loads(row[0])
            show_title = data.get('name', '')
            poster = data.get('poster_path', '')
            external_ids = data.get('external_ids', {})
            trakt_id = external_ids.get('trakt_id') # TMDb uneori are trakt_id
        else:
            # Fallback rapid la API TMDb doar pentru ID-uri
            url = f"{BASE_URL}/tv/{tmdb_id}/external_ids?api_key={API_KEY}"
            ext_data = requests.get(url, timeout=3).json()
            trakt_id = ext_data.get('trakt_id')
            
        if not trakt_id:
            # Ultimul resort: Căutare Trakt prin API
            res = trakt_api.trakt_api_request(f"/search/tmdb/{tmdb_id}?type=show")
            if res and isinstance(res, list): trakt_id = res[0]['show']['ids']['trakt']

        if trakt_id:
            # 2. Cerem Next Episode de la Trakt
            progress = trakt_api.trakt_api_request(f"/shows/{trakt_id}/progress/watched?extended=full")
            if progress and progress.get('next_episode'):
                nxt = progress['next_episode']
                air_date = nxt.get('first_aired', '').split('T')[0]
                
                # 3. Inserăm în DB
                c.execute("INSERT OR REPLACE INTO trakt_next_episodes VALUES (?,?,?,?,?,?,?,?,?)", 
                          (str(tmdb_id), show_title, nxt['season'], nxt['number'], nxt['title'], nxt['overview'], '', poster, air_date))
                conn.commit()
    except Exception as e:
        log(f"[SYNC] Error refreshing next episode: {e}", xbmc.LOGERROR)
    finally:
        conn.close()

