import json
import time
import zlib
import sqlite3
import os
import xbmcgui
from resources.lib.core.database import connect
from resources.lib.core.config import ADDON, ADDON_DATA_DIR

class MainCache:
    def __init__(self):
        self.dbcon = connect()
        self.dbcur = self.dbcon.cursor()
        self._create_tables()

    def _create_tables(self):
        try:
            self.dbcur.execute("""CREATE TABLE IF NOT EXISTS maincache 
                           (id text unique, data blob, expires integer)""")
            
            # Modify table structure: add 'scanned_providers'
            # If the table already exists without this column, the insert might error,
            # so we try to add the column (simple migration)
            self.dbcur.execute("""CREATE TABLE IF NOT EXISTS sources_cache 
                           (id text unique, streams blob, failed_providers text, scanned_providers text, sort_opt text, expires integer)""")
            
            # Migration for existing users (try/except ignores if already exists)
            try:
                self.dbcur.execute("ALTER TABLE sources_cache ADD COLUMN scanned_providers text")
            except: pass
            try:
                self.dbcur.execute("ALTER TABLE sources_cache ADD COLUMN sort_opt text")
            except: pass
            
            self.dbcon.commit()
        except: pass

    def get(self, string):
        try:
            current_time = int(time.time())
            self.dbcur.execute("SELECT expires, data FROM maincache WHERE id = ?", (string,))
            result = self.dbcur.fetchone()
            if result:
                expires, data_blob = result
                if expires > current_time:
                    if isinstance(data_blob, bytes):
                        return json.loads(zlib.decompress(data_blob))
                    return json.loads(data_blob)
                else:
                    self.delete(string)
        except: pass
        return None

    def set(self, string, data, expiration=48):
        try:
            expires = int(time.time() + (expiration * 3600))
            json_data = json.dumps(data)
            compressed = zlib.compress(json_data.encode('utf-8'))
            self.dbcur.execute("INSERT OR REPLACE INTO maincache (id, data, expires) VALUES (?, ?, ?)", 
                               (string, compressed, expires))
            self.dbcon.commit()
        except: pass

    def delete(self, string):
        try:
            self.dbcur.execute("DELETE FROM maincache WHERE id = ?", (string,))
            self.dbcon.commit()
        except: pass

    def delete_prefix(self, prefix):
        try:
            self.dbcur.execute("DELETE FROM maincache WHERE id GLOB ?", (prefix + '*',))
            self.dbcon.commit()
        except: pass
            
    def delete_all(self):
        try:
            self.dbcur.execute("DELETE FROM maincache")
            self.dbcur.execute("DELETE FROM sources_cache") # Also clear sources
            self.dbcon.execute("VACUUM")
            self.dbcon.commit()
        except: pass

# --- NEW METHODS FOR SOURCES (MODIFIED) ---
    def get_source_cache(self, search_id):
        """Returneaza: (streams, error_providers, empty_providers, scanned_providers, sort_opt)
        sort_opt = optiunea de sortare folosita cand lista a fost salvata (None pt randuri vechi)."""
        try:
            current_time = int(time.time())
            self.dbcur.execute("SELECT expires, streams, failed_providers, scanned_providers, sort_opt FROM sources_cache WHERE id = ?", (search_id,))
            result = self.dbcur.fetchone()
            
            if result:
                expires, streams_blob, failed_json, scanned_json, saved_sort_opt = result
                if expires > current_time:
                    streams = []
                    if streams_blob:
                        try: streams = json.loads(zlib.decompress(streams_blob))
                        except: pass
                    
                    error_list = []
                    empty_list = []
                    if failed_json:
                        try:
                            parsed = json.loads(failed_json)
                            if isinstance(parsed, list):
                                # Old format: all providers are errors (retry)
                                error_list = parsed
                            elif isinstance(parsed, dict):
                                error_list = parsed.get('error', [])
                                empty_list = parsed.get('empty', [])
                        except: pass
                    
                    scanned_list = []
                    if scanned_json:
                        try: scanned_list = json.loads(scanned_json)
                        except: pass
                        
                    try: saved_sort_opt = int(saved_sort_opt)
                    except: saved_sort_opt = None
                    
                    return streams, error_list, empty_list, scanned_list, saved_sort_opt
                else:
                    self.delete_source_cache(search_id)
        except Exception as e:
            pass
        return None, None, None, None, None

    def set_source_cache(self, search_id, streams, error_providers, empty_providers, scanned_providers, expiration_hours, sort_opt=None):
        try:
            expires = int(time.time() + (expiration_hours * 3600))
            
            json_streams = json.dumps(streams)
            compressed_streams = zlib.compress(json_streams.encode('utf-8'))
            
            json_failed = json.dumps({"error": error_providers, "empty": empty_providers})
            json_scanned = json.dumps(scanned_providers)
            
            self.dbcur.execute("INSERT OR REPLACE INTO sources_cache (id, streams, failed_providers, scanned_providers, sort_opt, expires) VALUES (?, ?, ?, ?, ?, ?)", 
                               (search_id, compressed_streams, json_failed, json_scanned, sort_opt, expires))
            self.dbcon.commit()
        except: pass
        
    def delete_source_cache(self, search_id):
        try:
            self.dbcur.execute("DELETE FROM sources_cache WHERE id = ?", (search_id,))
            self.dbcon.commit()
        except: pass

def cache_object(function, string, url, json_output=True, expiration=48):
    cache = MainCache()
    cached_data = cache.get(string)
    if cached_data: return cached_data
    
    if isinstance(url, list): result = function(*url)
    else: result = function(url)
        
    if result:
        if json_output and hasattr(result, 'json'):
            try: data = result.json()
            except: data = result
        else: data = result
        cache.set(string, data, expiration=expiration)
        return data
    return None
    

# --- FAST CACHE (RAM) ---
def get_fast_cache(key, fresh_only=False):
    """Returns data from RAM. Language + page_limit + select action + auto_play are part of the key to react instantly to setting changes.

    fresh_only=True: NU intoarce copia din fereastra stale-while-revalidate.
    Folosit de constructorul de liste (_list_build_wait), unde datele vechi nu
    pot insemna "alt proces a terminat build-ul" - exact confuzia care lasa
    una din variantele Up Next nereconstruita dupa un marcaj.
    """
    try:
        import xbmcgui
        from resources.lib.core.config import get_page_limit_index
        curr_lang = ADDON.getSetting('plot_language')
        curr_limit = get_page_limit_index()
        curr_select = ADDON.getSetting('select_ext_info') or '0'
        curr_autoplay = ADDON.getSetting('auto_play')
        actual_key = f"{key}_{curr_lang}_{curr_limit}_{curr_select}_{curr_autoplay}"

        window = xbmcgui.Window(10000)
        ver = window.getProperty("tmdbmovies_fast_cache_version")
        data = window.getProperty(f"tmdbmovies_fast_{actual_key}")

        if data:
            cache_obj = json.loads(data)
            if cache_obj.get('ver') == ver:
                return cache_obj.get('items')
            if fresh_only:
                return None
            # FALLBACK "stale": daca ultima invalidare a fost un MARCAJ (nu un
            # sync), lista veche e inca utilizabila. Altfel randarea ar trebui
            # sa reconstruiasca lista de la zero (secunde bune de BusyDialog
            # peste lista goala), doar pentru ca un film/serial tocmai a fost
            # marcat. Bifa de vizionare e corectata la randare, din DB-ul
            # local (vezi list_render._patch_watched_flags), deci ce se vedea
            # e corect chiar daca lista e "veche".
            try:
                _ss = float(window.getProperty("tmdbmovies_watched_stale_since") or 0)
                if _ss > 0 and (time.time() - _ss) < UP_NEXT_STALE_MAX_S:
                    return cache_obj.get('items')
            except Exception:
                pass
    except: pass
    return None

def set_fast_cache(key, items):
    """Saves data in RAM."""
    try:
        import xbmcgui
        from resources.lib.core.config import get_page_limit_index
        curr_lang = ADDON.getSetting('plot_language')
        curr_limit = get_page_limit_index()
        curr_select = ADDON.getSetting('select_ext_info') or '0'
        curr_autoplay = ADDON.getSetting('auto_play')
        actual_key = f"{key}_{curr_lang}_{curr_limit}_{curr_select}_{curr_autoplay}"

        window = xbmcgui.Window(10000)
        ver = window.getProperty("tmdbmovies_fast_cache_version")
        cache_obj = {'ver': ver, 'items': items}
        window.setProperty(f"tmdbmovies_fast_{actual_key}", json.dumps(cache_obj))
    except: pass

# Cat timp e servita lista "veche" dupa un marcaj, inainte de a fi reconstruita
# oricum. Stale-while-revalidate tine containerul plin (fara pagina neagra), dar
# NU poate permite ca episodul tocmai vizionat sa nu dispara niciodata. Dupa acest
# prag: golirile de lista reince, iar randarea ignora cache-ul vechi.
# Locuit in cache.py pentru ca clear_list_fast_cache() sa nu depinda de tmdb_api
# (import circular); tmdb_api il importa pentru carpe-ul de corectitudine.
UP_NEXT_STALE_MAX_S = 30.0


def upnext_stale_since():
    """Timestamp-ul la care s-a deschis fereastra stale-while-revalidate, sau 0.0.

    Defensiv pe citire: o valoare corupta NU trebuie sa blocheze invalidarea
    cache-urilor (float('abc') arunca si, intr-un try comun, ar opri tot blocul).
    """
    try:
        import xbmcgui
        v = xbmcgui.Window(10000).getProperty("tmdbmovies.upnext_stale_since")
        return float(v) if v else 0.0
    except Exception:
        return 0.0


def upnext_stale_active():
    try:
        _ss = upnext_stale_since()
        return _ss > 0 and (time.time() - _ss) < UP_NEXT_STALE_MAX_S
    except Exception:
        return False


def mark_upnext_cache_built(variant='', built_from=0.0):
    """Semnal cross-proces: lista Up Next a fost rescrisa ACUM in fast cache.

    Scris de build-ul real (api/tmdb_api.get_next_episodes) la fiecare scriere.
    Citit de safety pass-ul din player ca sa stie daca refreshul lui ar randa
    date vechi: in fereastra stale-while-revalidate `get_fast_cache` intoarce
    intentionat lista veche, deci "a terminat pre-randarea" nu inseamna "cache-ul
    e proaspat" (pre-randarea poate si sa renunte).

    Varianta conteaza: listele TMDb si provider se construiesc separat, iar un
    build al celeilalte variante nu face lista vizibila proaspata.

    built_from: momentul in care build-ul a CITIT randurile din DB. Stampul
    trebuie sa fie acela, nu momentul scrierii: un build pornit inainte de
    marcaj poate termina dupa el si ar scrie lista veche cu stamp „proaspat"
    (log real: build pornit 22:42:12.8, marcaj 22:42:21.4, scriere 22:42:28.6).
    """
    try:
        import xbmcgui
        w = xbmcgui.Window(10000)
        _now = str(built_from or time.time())
        w.setProperty('tmdbmovies.upnext_cache_built_at', _now)
        if variant in ('tmdb', 'provider'):
            w.setProperty('tmdbmovies.upnext_built_at_' + variant, _now)
        return True
    except Exception:
        return False


def upnext_cache_built_at(variant=''):
    """Timestamp-ul ultimului build Up Next scris in cache (0.0 = necunoscut).

    Cu `variant` citeste STRICT stampul acelei variante. Fara fallback pe cel
    generic: stampul generic e scris de ORICE build, deci un build al celeilalte
    variante "valida" poarta si refresh-ul randa lista veche (la primul stop
    dupa un restart al Kodi stampul variantei lipseste cu desavarsire).
    0.0 = varianta respectiva nu a fost construita in aceasta sesiune.
    """
    try:
        import xbmcgui
        w = xbmcgui.Window(10000)
        if variant in ('tmdb', 'provider'):
            return float(w.getProperty('tmdbmovies.upnext_built_at_' + variant) or 0)
        return float(w.getProperty('tmdbmovies.upnext_cache_built_at') or 0)
    except Exception:
        return 0.0


def upnext_built_for(variant):
    """Stampul de build relevant pentru lista Up Next de pe ecran.

    Varianta cunoscuta: STRICT stampul ei. Un build al celeilalte liste nu face
    lista vizibila proaspata, iar acceptarea lui duce la re-randare pe cache
    vechi (log 19:34, mansh: pass-ul a validat stampul listei tmdb in timp ce pe
    ecran era lista provider).

    Varianta necunoscuta: stampul generic, deliberat. Daca nu se poate rezolva
    din calea de la stop, nici din cea live (list_render.upnext_variant_from_path)
    si nici din amintirea ultimei randari reale, atunci containerul nu e un
    folder Up Next (orice randare reala a unei liste Up Next scrie amintirea),
    deci nu exista cache Up Next de aparat.

    De ce NU cerem ambele stampuri cand varianta e necunoscuta: cine are lista
    TMDb dezactivata din setari (tmdb_upnext_enabled=false) nu o construieste
    niciodata, deci stampul ei ramine 0 pentru totdeauna - conditia nu s-ar
    implini, safety pass-ul ar expira si lista nu s-ar mai reimprospata deloc.
    """
    try:
        if variant in ('tmdb', 'provider'):
            return upnext_cache_built_at(variant)
        return upnext_cache_built_at('')
    except Exception:
        return 0.0


def _playback_active():
    """True cat timp ruleaza un episod.

    In timpul redarii lista Up Next nu e pe ecran, deci nu are rost sa o
    golim - si nimeni nu se uita la ea pana la urmatorul Container.Refresh.
    Masurat pe debug log: lista era scrisa la 00:30:02 (85%), si la randarea
    de la stop (00:30:24) cache-ul era din nou gol -> light path-ul rata ->
    ~2.8s de import tmdb_api + DialogBusy peste 6s. Nu am urmarit cine o
    goleste (ghost scraper, daemonii de refresh, sync-urile) pentru ca orice
    gard pus la un singur apelator se poate ocoli. Gardul e aici, in punctul
    central, si acopera orice golire, indiferent de origine.
    Plagiu de 6h: daca monitorul ar muri inainte sa stinga flagul, lista ar
    ramane blocata pana la restart. Timestampul face gardul sa se auto-repara.
    """
    try:
        import xbmcgui
        w = xbmcgui.Window(10000)
        if w.getProperty('tmdbmovies.playback_active') != 'true':
            return False
        return (time.time() - float(w.getProperty('tmdbmovies.playback_since') or 0)) < 21600
    except Exception:
        return False


def set_playback_active(active):
    try:
        import xbmcgui
        w = xbmcgui.Window(10000)
        if active:
            w.setProperty('tmdbmovies.playback_active', 'true')
            w.setProperty('tmdbmovies.playback_since', str(time.time()))
        else:
            w.clearProperty('tmdbmovies.playback_active')
            w.clearProperty('tmdbmovies.playback_since')
    except Exception:
        pass




def clear_list_fast_cache(force=False, stale_ok=False):
    """Invalideaza DOAR listele (fast cache), pastrind cache-ul RAM de metadate.

    Watched status nu schimba metadatele (titluri/ploturi/sezoane/imagini), dar
    clear_all_fast_cache() bumpa si versiunea de metadate -> dupa FIECARE episod
    vazut, listele se re-construiau cu toate cererile TMDb de la zero (secunde
    bune de spinner la revenirea in Up Next). Aici listele se re-build din DB,
    iar metadatele raman instant din cache.

    FEREASTA STALE-WHILE-REVALIDATE: dupa un marcaj, lista se pastreaza intentionat
    ca "veche" (max UP_NEXT_STALE_MAX_S), ca sa nu ramana containerul negru cu
    BusyDialog in timp ce pre-randarea rescrie lista in fundal. Orice golire in
    acest interval - inclusiv cea din daemonii de refresh ai providerului
    (trakt/mdblist/simkl/punchplay/local) - ar reface lista de la zero si ar
    reintroduce exact problema pe care o rezolvam. Deci golirea e amanata.
    Corectitudinea nu depinde de asta: carpe-ul din tmdb_api ignora cache-ul
    dupa prag, iar pre-randarea il rescrie imediat ce termina.
    """
    # force=True: invalidam ORICE, chiar si in fereastra stale sau in timpul
    # redarii. Folosit la oprirea din player, unde listele trebuie sa se
    # reconstruiasca (bifa de vizionat sa apara imediat) - iar Up Next e
    # pastrat separat, peste invalidare, ca sa nu produca pagina neagra.
    if not force:
        if upnext_stale_active():
            return
        if _playback_active():
            return
    try:
        import xbmcgui
        window = xbmcgui.Window(10000)
        window.setProperty("tmdbmovies_fast_cache_version", str(time.time()))
        if stale_ok:
            # Invalidare de la un marcaj: lista veche ramane utilizabila ca
            # fallback (vezi get_fast_cache), ca randarea sa nu devina o
            # reconstructie completa.
            window.setProperty("tmdbmovies_watched_stale_since", str(time.time()))
        else:
            # Invalidare normala (sync, setari): lista veche NU mai poate fi
            # servita, continutul s-a schimbat real.
            window.clearProperty("tmdbmovies_watched_stale_since")
    except: pass


def clear_all_fast_cache(force=False):
    try:
        import xbmcgui
        window = xbmcgui.Window(10000)
        # Fereastra stale-while-revalidate (vezi clear_list_fast_cache): versiunea
        # de LISTE se pastreaza, ca lista veche sa poata fi randata imediat dupa
        # un marcaj. Metadatele (RAM) se invalideaza oricum - nu produc pagina
        # neagra, doar re-fetch. Fara asta, cele ~22 de apeluri din toate modulele
        # (sync, ghost scraper, warm-up) goleau lista pe la gardul din
        # clear_list_fast_cache, iar randarea de la intoarcerea din playercadea din
        # cache la build complet - BusyDialog peste lista.
        _stale = (not force) and (upnext_stale_active() or _playback_active())
        if not _stale:
            window.setProperty("tmdbmovies_fast_cache_version", str(time.time()))
            try:
                window.clearProperty("tmdbmovies_watched_stale_since")
            except Exception:
                pass
        window.setProperty("tmdbmovies_ram_cache_version", str(time.time()))
    except: pass


# Ensure ram cache version is initialized on first access
def _ensure_ram_cache_ver():
    try:
        w = _get_ram_window()
        if not w.getProperty("tmdbmovies_ram_cache_version"):
            w.setProperty("tmdbmovies_ram_cache_version", str(time.time()))
    except:
        pass


# =============================================================================
# RAM META CACHE (Window Properties) — instant between plugin calls
# =============================================================================
_RAM_WINDOW = None

def _get_ram_window():
    global _RAM_WINDOW
    if _RAM_WINDOW is None:
        import xbmcgui
        _RAM_WINDOW = xbmcgui.Window(10000)
    return _RAM_WINDOW

_RAM_TTL = 168 * 3600  # 7 days in seconds

def ram_cache_get(tag, key):
    """Generic RAM cache get. Checks version + TTL."""
    try:
        w = _get_ram_window()
        ver = w.getProperty("tmdbmovies_ram_cache_version")
        raw = w.getProperty(f'tmdb_ram_{tag}_{key}')
        if not raw:
            return None
        import json
        data = json.loads(raw)
        if data.get('_ver') != ver:
            w.clearProperty(f'tmdb_ram_{tag}_{key}')
            return None
        expires = data.get('_expires', 0)
        if time.time() > expires:
            w.clearProperty(f'tmdb_ram_{tag}_{key}')
            return None
        return data.get('meta')
    except:
        return None

def ram_cache_set(tag, key, data, ttl=_RAM_TTL):
    """Generic RAM cache set."""
    try:
        import json
        w = _get_ram_window()
        ver = w.getProperty("tmdbmovies_ram_cache_version")
        cache_obj = {'meta': data, '_expires': time.time() + ttl, '_ver': ver}
        w.setProperty(f'tmdb_ram_{tag}_{key}', json.dumps(cache_obj))
    except:
        pass

def ram_cache_get_tvshow(tmdb_id):
    return ram_cache_get('tv', tmdb_id)

def ram_cache_set_tvshow(tmdb_id, data, ttl=_RAM_TTL):
    ram_cache_set('tv', tmdb_id, data, ttl)

def ram_cache_get_season(tmdb_id, season_num):
    return ram_cache_get('season', f'{tmdb_id}_{season_num}')

def ram_cache_set_season(tmdb_id, season_num, data, ttl=_RAM_TTL):
    ram_cache_set('season', f'{tmdb_id}_{season_num}', data, ttl)

def ram_cache_clear_all():
    """Clear all RAM cache by bumping version. All entries with old ver become stale."""
    try:
        w = _get_ram_window()
        w.setProperty("tmdbmovies_ram_cache_version", str(time.time()))
    except:
        pass

# =============================================================================
# GLOBAL RAM META POOL (Python dict — no Window Property size limits)
# =============================================================================
_RAM_META_POOL = {}
_RAM_META_POOL_MAX = 500

def ram_pool_get(tmdb_id):
    """O(1) dict lookup — instant, no serialization."""
    return _RAM_META_POOL.get(str(tmdb_id))

def ram_pool_set(tmdb_id, data):
    """Store metadata in global pool. Silently skips if pool is full."""
    if len(_RAM_META_POOL) >= _RAM_META_POOL_MAX:
        return
    _RAM_META_POOL[str(tmdb_id)] = data

def ram_pool_clear():
    _RAM_META_POOL.clear()

def warm_ram_pool_from_db():
    """Load most recent non‑expired metadata entries into the global RAM pool.
    Called once at service startup — makes trending lists load instantly
    for shows the user has already browsed."""
    try:
        conn = sqlite3.connect(os.path.join(ADDON_DATA_DIR, 'trakt_sync.db'), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=OFF")
        c = conn.cursor()
        now = int(time.time())
        c.execute("SELECT tmdb_id, media_type, data FROM meta_cache_items WHERE expires > ? ORDER BY rowid DESC LIMIT ?", (now, _RAM_META_POOL_MAX))
        rows = c.fetchall()
        conn.close()
        count = 0
        for tmdb_id, media_type, data_blob in rows:
            try:
                if isinstance(data_blob, bytes):
                    data = json.loads(zlib.decompress(data_blob))
                else:
                    data = json.loads(data_blob)
                _RAM_META_POOL[str(tmdb_id)] = data
                count += 1
            except:
                pass
        if count:
            from resources.lib.core.utils import log
            log(f"[CACHE] RAM meta pool warmed with {count} entries")
    except Exception as e:
        from resources.lib.core.utils import log
        log(f"[CACHE] RAM meta pool warmup skipped: {e}")

