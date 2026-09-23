import xbmc
import xbmcvfs
import xbmcgui
import xbmcplugin  # NOU (necesar pentru meniuri)
import sys         # NOU (necesar pentru handle si argv)
import json
import re
import os
import math
import time
import glob
from urllib.parse import quote, unquote, urlencode # NOU

# Import WITHOUT HEADERS (which is now a function)
from resources.lib.config import ADDON, ADDON_DATA_DIR, GENRE_MAP

ADDON_PATH = ADDON.getAddonInfo('path')
TMDbmovies_ICON = os.path.join(ADDON_PATH, 'icon.png')

# At the beginning of utils.py, after imports
_debug_cache = None

def _is_debug_enabled():
    """Check if debug is enabled (with cache for performance)."""
    global _debug_cache
    if _debug_cache is None:
        try:
            from resources.lib.config import ADDON
            _debug_cache = ADDON.getSetting('debug_enabled') == 'true'
        except:
            _debug_cache = True
    return _debug_cache

def reset_debug_cache():
    """Reset debug cache (called when settings change)."""
    global _debug_cache
    _debug_cache = None


_WARM_IMPORT_MODULES = (
    'resources.lib.menus',
    'resources.lib.cache',
    'resources.lib.watched_provider',
    'resources.lib.tmdb_api',
    'resources.lib.trakt_api',
    'resources.lib.trakt_sync',
    'resources.lib.scraper',
    'resources.lib.player',
    'resources.lib.detonate',
    'resources.lib.mdblist',
    'resources.lib.mdblist_api',
    'resources.lib.mdblist_sync',
    'resources.lib.simkl',
    'resources.lib.simkl_api',
    'resources.lib.simkl_sync',
    'resources.lib.local_sync',
    'resources.lib.local_library',
    'resources.lib.library',
    'resources.lib.downloader',
    'resources.lib.history_import',
)


def warm_import_modules():
    import importlib
    t0 = time.time()
    done = 0
    for mod_name in _WARM_IMPORT_MODULES:
        try:
            if mod_name in sys.modules:
                done += 1
                continue
            importlib.import_module(mod_name)
            done += 1
        except Exception as e:
            try:
                xbmc.log("[WARM IMPORT] fail {}: {!r}".format(mod_name, e),
                         xbmc.LOGWARNING)
            except Exception:
                pass
    try:
        xbmc.log("[WARM IMPORT] {}/{} modules in {:.2f}s".format(
            done, len(_WARM_IMPORT_MODULES), time.time() - t0), xbmc.LOGINFO)
    except Exception:
        pass


def log(msg, level=xbmc.LOGINFO):
    if level in (xbmc.LOGERROR, xbmc.LOGWARNING):
        xbmc.log(f"[TMDb Movies] {msg}", level)
        return
    
    if _is_debug_enabled():
        xbmc.log(f"[TMDb Movies] {msg}", level)

def get_language():
    return 'en-US'

def ensure_addon_dir():
    if not xbmcvfs.exists(ADDON_DATA_DIR):
        xbmcvfs.mkdirs(ADDON_DATA_DIR)

def read_json(filepath):
    """Read JSON file with logging."""
    try:
        if not xbmcvfs.exists(filepath):
            # No log warning for files that normally don't exist yet
            return None
            
        f = xbmcvfs.File(filepath, 'r')
        content = f.read()
        f.close()
        
        if not content or content.strip() == '':
            log(f"[UTILS] ⚠️ Empty file: {filepath}", xbmc.LOGWARNING)
            return None
            
        data = json.loads(content)
        return data
    except json.JSONDecodeError as e:
        log(f"[UTILS] ❌ JSON decode error in {filepath}: {e}", xbmc.LOGERROR)
        return None
    except Exception as e:
        log(f"[UTILS] ❌ Error reading {filepath}: {e}", xbmc.LOGERROR)
        return None


def write_json(filepath, data):
    """Save JSON file."""
    ensure_addon_dir()
    try:
        content = json.dumps(data, indent=2)
        f = xbmcvfs.File(filepath, 'w')
        success = f.write(content)
        f.close()
        
        if not success:
            log(f"[UTILS] ⚠️ Write returned False for {filepath}", xbmc.LOGWARNING)
        return success
    except Exception as e:
        log(f"[UTILS] ❌ Error writing {filepath}: {e}", xbmc.LOGERROR)
        return False


def clean_text(text):
    if not text:
        return ""
    
    # 1. Ensure decoding
    if isinstance(text, bytes):
        try: text = text.decode('utf-8', errors='ignore')
        except: pass

    # 2. Remove ALL non-ASCII (0-127)
    # This instantly destroys flags and any emoji
    text = re.sub(r'[^\x00-\x7F]+', '', text)
    
    # 3. Remove remaining weird ASCII chars (e.g. |, ~, `)
    # Keep only alphanumeric and safe signs
    text = re.sub(r'[^a-zA-Z0-9\s\.\-\_\[\]\(\)\+]', '', text)

    # 4. Clean multiple spaces
    text = ' '.join(text.split())
    
    return text.strip()

def get_json(url):
    try:
        from resources.lib.config import SESSION, get_headers
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        r = SESSION.get(url, headers=get_headers(), timeout=5, verify=False)
        r.raise_for_status()
        return r.json()
    except:
        return {}

def paginate_list(item_list, page, limit=20):
    if not item_list:
        return [], 0
    count = len(item_list)
    total_pages = math.ceil(count / limit)
    
    start = (page - 1) * limit
    end = start + limit
    
    current_items = item_list[start:end]
    
    return current_items, total_pages

def personal_lists_sort_az():
    try:
        return ADDON.getSetting('personal_lists_sort') == '1'
    except:
        return False

def sort_personal_list(items):
    if not items:
        return items
    try:
        az = ADDON.getSetting('personal_lists_sort') == '1'
    except:
        return items
    if not az:
        return items
    def _title(it):
        if not isinstance(it, dict):
            return ''
        t = it.get('title') or it.get('name') or ''
        if not t:
            for k in ('movie', 'show', 'anime'):
                sub = it.get(k)
                if isinstance(sub, dict):
                    t = sub.get('title') or sub.get('name') or ''
                    if t:
                        break
        return str(t).casefold()
    try:
        return sorted(items, key=_title)
    except:
        return items

def is_season_fully_watched(tmdb_id, season, count_fn):
    try:
        s_num = int(season)
    except:
        return False
    try:
        from resources.lib.tmdb_api import get_tmdb_item_details
        details = get_tmdb_item_details(str(tmdb_id), 'tv', lightweight=True) or {}
        ep_count = 0
        for s in details.get('seasons', []) or []:
            try:
                if int(s.get('season_number', -1)) == s_num:
                    ep_count = int(s.get('episode_count', 0) or 0)
                    break
            except:
                continue
        if ep_count <= 0:
            return False
        return int(count_fn(str(tmdb_id), s_num) or 0) >= ep_count
    except:
        return False

_AIR_TIME_TTL = 7 * 24 * 3600          # ora cunoscuta: valabila 7 zile
_AIR_TIME_NEG_TTL = 6 * 3600           # "nu exista (inca) ora": reincercam dupa 6h
_AIR_TIME_FALLBACK_MAX = 10            # cereri per-episod (Trakt, secvential) per deschidere

# Tokenul care tine locul orei de difuzare in label-urile salvate in fast cache.
# Lista se salveaza MEREU in fast cache (deschiderile urmatoare ramin instant), iar
# ora reala e pusa la randare (live si din cache) din cache-ul sqlite. Asa o lista
# nu mai rămâne "degradata" fara ore dupa ce cache-ul de ore se umple (Sweetpea),
# fara sa fie nevoie de re-prefetch la fiecare deschidere.
AIR_TIME_TOKEN = '[[AT]]'


def _air_time_cache_table():
    try:
        from resources.lib import trakt_sync as _ts
        import sqlite3
        conn = sqlite3.connect(_ts.DB_PATH, timeout=10)
        conn.execute("CREATE TABLE IF NOT EXISTS trakt_airtime_cache "
                     "(tmdb_id TEXT, season INTEGER, episode INTEGER, first_aired TEXT, saved_at REAL, "
                     "UNIQUE(tmdb_id, season, episode))")
        conn.commit()
        return conn
    except:
        return None

def _air_time_rows_fresh(rows, now=None):
    """Randurile inca valide din trakt_airtime_cache: {(tmdb_id, season, episode): first_aired}.

    TTL separat pe tip de rand: ora cunoscuta = 7 zile, 'nu exista (inca) ora' = 6h
    (negative cache, ca sa nu reincercam aceleasi episoade la fiecare deschidere).
    """
    now = time.time() if now is None else now
    fresh = {}
    for r in rows or []:
        try:
            first_aired = str(r[3] or '')
            saved = float(r[4] or 0)
            ttl = _AIR_TIME_TTL if first_aired else _AIR_TIME_NEG_TTL
            if now - saved < ttl:
                fresh[(str(r[0]), int(r[1]), int(r[2]))] = first_aired
        except:
            continue
    return fresh


def get_episode_air_times_map(keys):
    """Orele locale pentru mai multe episoade, dintr-o SINGURA conexiune sqlite.

    keys = iterable de (tmdb_id, season, episode); returneaza
    {(tmdb_id, season, episode): ora_locala} doar pentru orele valide.
    """
    out = {}
    try:
        wanted = set()
        for k in keys or []:
            try:
                wanted.add((str(k[0]), int(k[1]), int(k[2])))
            except:
                continue
        if not wanted:
            return out
        conn = _air_time_cache_table()
        if conn is None:
            return None   # citirea a esuat: apelantul poate cadea pe varianta per episod
        try:
            ids = tuple({t for (t, _s, _e) in wanted})
            marks = ','.join(['?'] * len(ids))
            rows = conn.execute(
                "SELECT tmdb_id, season, episode, first_aired, saved_at FROM trakt_airtime_cache "
                "WHERE tmdb_id IN (%s)" % marks, ids).fetchall()
        finally:
            try:
                conn.close()
            except:
                pass
        now = time.time()
        from resources.lib.config import utc_to_local_time
        for r in rows:
            try:
                key = (str(r[0]), int(r[1]), int(r[2]))
                if key not in wanted or not r[3]:
                    continue
                if now - float(r[4] or 0) >= _AIR_TIME_TTL:
                    continue
                _at = utc_to_local_time(str(r[3])) or ''
                if _at:
                    out[key] = _at
            except:
                continue
    except:
        return None
    return out


def prefetch_air_times(items, days=120):
    """Umple cache-ul sqlite cu orele de difuzare Trakt (bulk + fallback per episod).

    Returneaza True daca toate orele care SE POT afisa sint in cache, False daca mai
    lipsesc si None daca optiunea e oprita / nu exista conexiune Trakt (nimic de facut).
    Esecurile nu mai sint mute: bulk-ul cazut si listele incomplete ajung in kodi.log.
    """
    try:
        if ADDON.getSetting('show_air_time') != 'true':
            return None
    except:
        return None
    try:
        import datetime as _dt
        import time as _tm
        from resources.lib import trakt_api as _ta
        try:
            if not _ta.get_trakt_token():
                return None
        except:
            return None
        today = _dt.date.today()
        want = []
        # need_time: ora se afiseaza doar la episoadele viitoare (sau fara data);
        # pentru episoadele deja difuzate nu facem nicio cerere per episod.
        need_time = {}
        names = {}
        for it in items or []:
            try:
                key = (str(it.get('tmdb_id') or ''), int(it.get('season') or 0), int(it.get('episode') or 0))
            except:
                continue
            if not key[0] or key[0] == 'None' or key[1] <= 0 or key[2] <= 0:
                continue
            want.append(key)
            # Numele serialului doar pentru log (altfel ramine doar tmdb_id).
            try:
                names[key] = str(it.get('show_title') or it.get('name') or it.get('title') or '') or key[0]
            except:
                names[key] = key[0]
            try:
                _p = str(it.get('air_date') or '').split('T')[0].split('-')
                need_time[key] = _dt.date(int(_p[0]), int(_p[1]), int(_p[2])) >= today
            except:
                need_time[key] = True
        want = list(dict.fromkeys(want))
        if not want:
            return None
        try:
            conn = _air_time_cache_table()
            known_times = {}
            missing = list(want)
            if conn is not None:
                try:
                    rows = conn.execute("SELECT tmdb_id, season, episode, first_aired, saved_at FROM trakt_airtime_cache").fetchall()
                    known_times = _air_time_rows_fresh(rows, _tm.time())
                    missing = [w for w in want if w not in known_times]
                except:
                    known_times = {}
            # Ce mai lipseste si ce se poate afisa. Randurile "negative"
            # (first_aired gol, valabile 6h) inseamna doar "verificat recent", nu
            # "avem ora" — deci verdictul le trateaza separat, mai jos.
            _needed = [w for w in want if need_time.get(w)]
            _pn = [w for w in missing if need_time.get(w)]
            have = set(k for k, v in known_times.items() if v)
            found = {}
            bulk_ok = False
            attempted = 0

            if _needed and _pn:
                # 1. BULK: calendarul Trakt "my shows". Un esec aici nu mai e mut:
                #    fara log nu se putea sti de ce lista iese fara ore.
                try:
                    cal = _ta.get_trakt_calendar_shows(start_date=today.strftime('%Y-%m-%d'), days=days) or []
                    bulk_ok = isinstance(cal, list) and len(cal) > 0
                    if not bulk_ok:
                        log("[AIRTIME] bulk calendar returned nothing (calendar 'my shows' gol sau cererea a esuat).", xbmc.LOGWARNING)
                    for entry in cal:
                        if not isinstance(entry, dict):
                            continue
                        show = entry.get('show', {}) or {}
                        ids = show.get('ids', {}) or {}
                        ep = entry.get('episode', {}) or {}
                        fa = entry.get('first_aired', '') or ep.get('first_aired', '') or ''
                        if not fa:
                            continue
                        try:
                            found[(str(ids.get('tmdb', '')), int(ep.get('season') or 0), int(ep.get('number') or 0))] = str(fa)
                        except:
                            continue
                except Exception as _bulk_err:
                    log(f"[AIRTIME] bulk calendar failed: {_bulk_err}", xbmc.LOGWARNING)

                # 2. FALLBACK per episod (secvential, plafonat): doar pentru ce
                #    lipseste si se poate afisa (episod viitor / fara data).
                #    Rezultatul gol se memoreaza si el (negative cache 6h), altfel
                #    aceleasi episoade erau reincercate la fiecare deschidere.
                try:
                    for (t, s, e) in _pn:
                        if attempted >= _AIR_TIME_FALLBACK_MAX:
                            break
                        fa = found.get((t, s, e))
                        if not fa:
                            try:
                                from resources.lib.tmdb_api import get_trakt_id as _get_tid
                                tids = _get_tid(None, t, 'show')
                                epd = _ta.trakt_api_request(f"/shows/{tids}/seasons/{s}/episodes/{e}", params={'extended': 'full'}) if tids else None
                                if isinstance(epd, dict) and epd.get('first_aired'):
                                    fa = str(epd.get('first_aired'))
                            except:
                                fa = ''
                        attempted += 1
                        found[(t, s, e)] = fa or ''
                except:
                    pass

                # 3. Scriem o singura data tot ce am aflat (bulk + fallback,
                #    inclusiv negativele) intr-o singura conexiune.
                try:
                    if conn is not None:
                        for (t, s, e) in _pn:
                            if (t, s, e) not in found:
                                continue
                            conn.execute("INSERT OR REPLACE INTO trakt_airtime_cache (tmdb_id, season, episode, first_aired, saved_at) VALUES (?,?,?,?,?)",
                                         (t, s, e, found[(t, s, e)], _tm.time()))
                        conn.commit()
                except:
                    pass
            try:
                if conn is not None:
                    conn.close()
            except:
                pass

            # 4. Verdict: complete = toate orele care SE POT afisa sint in cache.
            #    Se calculeaza MEREU, chiar si cind nu a fost nimic de cerut
            #    (negative cache activa nu inseamna ca avem orele).
            try:
                have |= set(k for k, v in found.items() if v)
                unresolved = [w for w in _needed if w not in have]
                _worked = bool(_needed and _pn)   # s-a incercat ceva in acest pas?
                _bulk = 'ok' if bulk_ok else ('fail' if _worked else 'n/a')
                if unresolved:
                    _sample = ', '.join(
                        f"{names.get((t, s, e)) or t} S{int(s):02d}E{int(e):02d}" for (t, s, e) in unresolved[:5])
                    _msg = (f"[AIRTIME] incomplete: {len(_needed) - len(unresolved)}/{len(_needed)} ore cunoscute "
                            f"(bulk={_bulk}, fallback={attempted}, lipsa: {_sample})")
                    if _worked:
                        # Diagnostic real: am cerut si tot nu avem ora (Trakt nu are
                        # ora pentru episod / calendar cazut).
                        log(_msg + " - Trakt nu are ora sau calendarul nu a răspuns.", xbmc.LOGWARNING)
                    else:
                        # Nimic de reincercat acum (negative cache): doar informativ.
                        log(_msg + " - nimic de reincercat acum (negative cache).")
                    return False
                log(f"[AIRTIME] complete: {len(_needed)} ore cunoscute (bulk={_bulk}, fallback={attempted})")
                return True
            except:
                pass
        except Exception as _pf_err:
            log(f"[AIRTIME] prefetch failed: {_pf_err}", xbmc.LOGWARNING)
    except:
        pass
    return False

def get_episode_air_time(tmdb_id, season, episode):
    try:
        if ADDON.getSetting('show_air_time') != 'true':
            return ''
    except:
        return ''
    try:
        import time as _tm
        conn = _air_time_cache_table()
        if conn is None:
            return ''
        try:
            r = conn.execute("SELECT first_aired, saved_at FROM trakt_airtime_cache WHERE tmdb_id=? AND season=? AND episode=?",
                             (str(tmdb_id), int(season), int(episode))).fetchone()
        finally:
            try:
                conn.close()
            except:
                pass
        if not r or not r[0]:
            return ''
        try:
            if _tm.time() - float(r[1] or 0) >= _AIR_TIME_TTL:
                return ''
        except:
            pass
        from resources.lib.config import utc_to_local_time
        return utc_to_local_time(str(r[0])) or ''
    except:
        return ''


def apply_air_time(label, at):
    """Pune ora reala in locul AIR_TIME_TOKEN (sau scoate tokenul daca nu avem ora)."""
    try:
        if not label or AIR_TIME_TOKEN not in label:
            return label
        return label.replace(AIR_TIME_TOKEN, f' • {at}' if at else '')
    except:
        return label


def apply_air_times_to_cache_items(items):
    """Randare din fast cache: inlocuieste tokenul de ora cu ora reala din sqlite.

    Asa lista cache-uita se auto-vindeca de indata ce cache-ul de ore se umple,
    fara sa fie nevoie de re-prefetch (si fara sa salvam liste cu ore lipsa).
    """
    try:
        keys = []
        for it in items or []:
            ak = it.get('air_key') if isinstance(it, dict) else None
            if ak and AIR_TIME_TOKEN in str(it.get('label') or ''):
                keys.append((ak[0], ak[1], ak[2]))
        if not keys:
            return items
        at_map = get_episode_air_times_map(keys) or {}
        for it in items:
            lab = it.get('label') if isinstance(it, dict) else None
            if not lab or AIR_TIME_TOKEN not in lab:
                continue
            ak = it.get('air_key') or []
            try:
                at = at_map.get((str(ak[0]), int(ak[1]), int(ak[2])), '')
            except:
                at = ''
            it['label'] = apply_air_time(lab, at)
        return items
    except:
        return items

# =============================================================================
# SELECT ACTION (setarea select_ext_info)
# Randul selectat poate deschide Extended InfoMod in loc de play/navigare.
# Valorile setarii (index -> tipuri de rand acoperite):
#   0 None | 1 Movies | 2 TV Shows | 3 Episodes
#   4 Movies + TV Shows | 5 Movies + Episodes | 6 Movies + TV Shows + Episodes
# Pe randul de EPISOD, "Episodes" are prioritate (pagina episodului); daca e
# bifat doar "TV Shows", randul de episod deschide pagina SERIALULUI,
# ambele comportamente din aceeasi setare.
# =============================================================================
_SELECT_EXT_INFO_MAP = {
    '0': (),
    '1': ('movie',),
    '2': ('tv',),
    '3': ('episode',),
    '4': ('movie', 'tv'),
    '5': ('movie', 'episode'),
    '6': ('movie', 'tv', 'episode'),
}

def select_info_actions():
    """Tipurile de rand pentru care selectul deschide Extended Info (set gol = None)."""
    try:
        return _SELECT_EXT_INFO_MAP.get(str(ADDON.getSetting('select_ext_info') or '0'), ())
    except:
        return ()

def skip_ext_info_in_progress():
    """Skip In Progress: la ON, rindurile din In Progress (Movies / TV Shows / Episodes)
    isi pastreaza comportamentul normal (surse / browser serial), ignorind redirectul
    spre Extended Info din setarea select_ext_info (stil Redlight)."""
    try:
        return ADDON.getSetting('select_skip_inprogress') == 'true'
    except:
        return False

def skip_ext_info_upnext():
    """Skip Up Next: la ON, rindurile din Up Next deschid direct sursele,
    ignorind redirectul spre Extended Info."""
    try:
        return ADDON.getSetting('select_skip_upnext') == 'true'
    except:
        return False

def select_ext_info_params(content_type, tmdb_id, season=None, episode=None, tv_name='', title=''):
    """Params pentru mode=extended_info daca setarea cere pentru acest tip de rand,
    altfel None (randul isi pastreaza comportamentul normal).
    content_type: 'movie' | 'tv'/'show' | 'episode'.
    """
    try:
        if not tmdb_id:
            return None
        acts = select_info_actions()
        if not acts:
            return None
        if content_type == 'episode':
            if 'episode' not in acts and 'tv' not in acts:
                return None
            params = {'mode': 'extended_info', 'tmdb_id': str(tmdb_id), 'type': 'tv'}
            show_title = tv_name or title or ''
            if show_title:
                params['tv_name'] = show_title
            if 'episode' in acts and season is not None and episode is not None:
                # Pagina episodului (EpisodeInfo)
                params['season'] = str(season)
                params['episode'] = str(episode)
            # altfel: doar pagina serialului (stil POV)
            return params
        if content_type in ('tv', 'show', 'tvshow'):
            if 'tv' not in acts:
                return None
            return {'mode': 'extended_info', 'tmdb_id': str(tmdb_id), 'type': 'tv'}
        if content_type == 'movie':
            if 'movie' not in acts:
                return None
            return {'mode': 'extended_info', 'tmdb_id': str(tmdb_id), 'type': 'movie'}
        return None
    except:
        return None

# =============================================================================
# CALENDAR ROW CLICK (helper comun TMDb / Trakt / MDBList / Simkl / PunchPlay)
# Regula de click pe un rand din orice calendar, intr-un singur loc:
#   Filme:    azi/lansate (diff <= 0) -> Extended Info daca selectorul acopera
#             Movies, altfel cautarea/surse. Nelansate -> Extended Info pe film.
#   Episoade: azi/lansate -> Extended Info (episod sau serial, dupa selector),
#             altfel surse. Nelansate -> MEREU Extended Info direct (pagina
#             episodului; pagina serialului doar daca selectorul cere doar TV
#             Shows), identic cu filmele nelansate - niciodata lista de sezon.
# Returneaza (params_dict, is_folder).
# =============================================================================
def calendar_row_click_params(content_type, tmdb_id, diff, season=None, episode=None,
                              show_title='', sources_title=''):
    try:
        tmdb_id = str(tmdb_id)
        if content_type == 'movie':
            if diff <= 0:
                params = select_ext_info_params('movie', tmdb_id)
                if not params:
                    params = {'mode': 'sources', 'tmdb_id': tmdb_id, 'type': 'movie',
                              'title': sources_title or show_title}
                return params, False
            return {'mode': 'extended_info', 'tmdb_id': tmdb_id, 'type': 'movie'}, False
        # --- episod ---
        season = int(season or 0)
        episode = int(episode or 0)
        ep_label = 'S%02dE%02d' % (season, episode)
        if diff <= 0:
            params = select_ext_info_params('episode', tmdb_id, season, episode, show_title)
            if not params:
                params = {'mode': 'sources', 'tmdb_id': tmdb_id, 'type': 'tv',
                          'season': str(season), 'episode': str(episode),
                          'title': '%s %s' % (show_title, ep_label),
                          'tv_show_title': show_title}
            return params, False
        params = select_ext_info_params('episode', tmdb_id, season, episode, show_title)
        if not params:
            # Nelansat, selector off: mereu Extended Info direct pe EPISOD (ca la filme nelansate)
            params = {'mode': 'extended_info', 'tmdb_id': tmdb_id, 'type': 'tv',
                      'season': str(season), 'episode': str(episode), 'tv_name': show_title}
        return params, False
    except Exception:
        # Fallback defensiv: surse direct (comportament sigur)
        try:
            if content_type == 'movie':
                return {'mode': 'sources', 'tmdb_id': str(tmdb_id), 'type': 'movie',
                        'title': sources_title or show_title}, False
            return {'mode': 'sources', 'tmdb_id': str(tmdb_id), 'type': 'tv',
                    'season': str(int(season or 0)), 'episode': str(int(episode or 0)),
                    'title': sources_title or show_title,
                    'tv_show_title': show_title}, False
        except Exception:
            return None, False

def _cal_diff_int(item):
    try:
        return int(item[1].getProperty('cal_diff') or 999)
    except:
        return 999

def sort_calendar_items(items_to_add, today_top=True, sort_asc=True):
    """Sortare comuna calendarelor (TMDb / Trakt / MDBList / Simkl / PunchPlay):
    azi primele (optional), apoi dupa cal_diff crescator/descrescator.
    items_to_add: lista de tuple (url, li, is_folder). Returneaza lista sortata."""
    try:
        items = list(items_to_add or [])
        if today_top:
            today_items = [x for x in items if (x[1].getProperty('cal_diff') or '') == '0']
            other_items = [x for x in items if (x[1].getProperty('cal_diff') or '') != '0']
            other_items.sort(key=_cal_diff_int, reverse=not sort_asc)
            return today_items + other_items
        items.sort(key=_cal_diff_int, reverse=not sort_asc)
        return items
    except Exception:
        return list(items_to_add or [])

def format_calendar_date(raw_date, today=None):
    """Helper comun de dată pentru calendare (Trakt / MDBList / etc.):
    returnează (label_localizat, culoare, diff_zile).
    - diff <= -1 (trecut): verde FF00FA9A, 0 (azi): alb, viitor: galben;
    - label prin config.calendar_localized_label (RO/EN + format dată);
    - raw_date gol -> ('', 'white', 999); data invalidă -> data brută, alb, 999."""
    try:
        import datetime as _dt
        from resources.lib.config import calendar_localized_label as _cal_label
        if not raw_date:
            return '', 'white', 999
        if today is None:
            today = _dt.date.today()
        parts = str(raw_date).split('T')[0].split('-')
        d = _dt.date(int(parts[0]), int(parts[1]), int(parts[2]))
        diff = (d - today).days
        ds = '%s-%s-%s' % (parts[0], parts[1], parts[2])
        if diff == -1 or diff <= -2:
            color = 'FF00FA9A'
        elif diff == 0:
            color = 'white'
        else:
            color = 'yellow'
        return _cal_label(diff, ds), color, diff
    except Exception:
        try:
            return str(raw_date)[:10], 'white', 999
        except Exception:
            return '', 'white', 999

def process_media_item(item, kind, return_data=True, skip_details=True):
    """Delegatie catre SINGURUL renderer de randuri film/serial (tmdb_api._process_movie_item
    / _process_tv_item), folosit de toti providerii (Trakt / MDBList / Simkl / PunchPlay).
    kind: 'movie'/'movies' (sau True) -> film; 'tv'/'tvshows'/'show'/'' (sau False) -> serial.
    Returneaza dict-ul procesat al renderer-ului (url/li/is_folder/...) sau None."""
    try:
        from resources.lib import tmdb_api
        if isinstance(kind, bool):
            is_movie = kind
        else:
            is_movie = str(kind).strip().lower() in ('movie', 'movies', 'film')
        if is_movie:
            return tmdb_api._process_movie_item(item, return_data=return_data, skip_details=skip_details)
        return tmdb_api._process_tv_item(item, return_data=return_data, skip_details=skip_details)
    except Exception:
        return None

def calendar_context_menu(base_cm, content_type, tmdb_id, show_title, season=None, episode=None,
                          base_url='', browse_cmd=None, urlencode_fn=None, clear_sources=True):
    """Meniul contextual comun al unui rand de calendar: Browse Show / Browse Season
    (+ Clear sources cache) pe randurile de EPISOD. Returneaza o lista noua cu
    cm-ul de baza + intrarile comune. base_url = sys.argv[0] sau _BASE_URL al modulului."""
    try:
        cm = list(base_cm or [])
        if content_type != 'episode':
            return cm
        enc = urlencode_fn or urlencode
        bcmd = browse_cmd or (lambda url: 'Container.Update(%s)' % url)
        season = int(season or 0)
        episode = int(episode or 0)
        tid = str(tmdb_id)
        b_show_params = enc({'mode': 'details', 'tmdb_id': tid, 'type': 'tv', 'title': show_title})
        cm.append(('[B][COLOR cyan]Browse Show[/COLOR][/B]', bcmd(f"{base_url}?{b_show_params}")))
        b_season_params = enc({'mode': 'episodes', 'tmdb_id': tid, 'season': str(season), 'tv_show_title': show_title})
        cm.append(('[B][COLOR cyan]Browse Season[/COLOR][/B]', bcmd(f"{base_url}?{b_season_params}")))
        if clear_sources:
            clear_p_params = enc({'mode': 'clear_sources_context', 'tmdb_id': tid, 'type': 'tv',
                                  'season': str(season), 'episode': str(episode),
                                  'title': f"{show_title} S{season:02d}E{episode:02d}"})
            cm.append(('[B][COLOR orange]Clear sources cache[/COLOR][/B]', f"RunPlugin({base_url}?{clear_p_params})"))
        return cm
    except Exception:
        return list(base_cm or [])

def extract_details(raw_title, raw_name):
    from resources.lib.utils import clean_text
    import re
    clean_t = clean_text(str(raw_title) or "")
    clean_n = clean_text(str(raw_name) or "")
    full_text = (clean_n + " " + clean_t).lower()

    # --- 1. Extract Size ---
    size_match = re.search(r'(\d+(\.\d+)?\s?(gb|gib|mb|mib))', full_text, re.IGNORECASE)
    size = size_match.group(1).upper() if size_match else "N/A"
    
    # --- 2. Determine Provider ---
    provider = "Unknown"
    if 'fsl' in full_text or 'flash' in full_text: provider = "Flash"
    elif 'pix' in full_text or 'pixeldrain' in full_text: provider = "PixelDrain"
    elif 'gdrive' in full_text or 'google' in full_text: provider = "GDrive"
    elif 'fichier' in full_text: provider = "1Fichier"
    elif 'hubcloud' in full_text: provider = "HubCloud"
    elif 'vidzee' in full_text or 'vflix' in full_text: provider = "Vidzee"
    elif 'flixhq' in full_text: provider = "FlixHQ"
    elif 'webstream' in full_text: provider = "WebStream"
    elif 'hdhub' in full_text: provider = "HDHub"
    elif 'sooti' in full_text or 'hs+' in full_text: provider = "Sooti"
    elif 'vega' in full_text: provider = "Vega"
    elif 'streamvix' in full_text: provider = "StreamVix"
    else:
        parts = clean_n.split(' ')
        if parts and parts[0]: provider = parts[0][:15]

    # --- 3. Determine Resolution (Strict) ---
    res = "SD"
    if re.search(r'\b(2160p|4k\s|4k$|uhd)\b', full_text): res = "4K"
    elif re.search(r'\b(1080p|1080i|fhd)\b', full_text): res = "1080p"
    elif re.search(r'\b(720p|720i|hd)\b', full_text): res = "720p"
    elif re.search(r'\b(480p|360p|sd)\b', full_text): res = "SD"
    
    if res == "SD" and "4k" in full_text:
        if "4khdhub" not in full_text and "4kmovies" not in full_text:
             res = "4K"

    return size, provider, res

def get_genres_string(genre_ids):
    """Convert list of genre IDs to string."""
    if not genre_ids:
        return ''
    
    # Use GENRE_MAP from config (imported above)
    names = [GENRE_MAP.get(g_id, '') for g_id in genre_ids]
    return ', '.join(filter(None, names))

def get_color_for_quality(quality):
    quality = str(quality).lower()
    if '4k' in quality or '2160' in quality: return "FFFF00FF"
    elif '1080' in quality: return "FF7CFC00"
    elif '720' in quality: return "FFBA55D3"
    else: return "FF1E90FF"

def clear_cache():
    from resources.lib.config import ADDON_DATA_DIR
    from resources.lib import trakt_sync
    from resources.lib import database
    import os
    import xbmcvfs
    import sqlite3
    from resources.lib.utils import log
    import xbmcgui

    deleted = False
    try:
        trakt_sync.get_connection().close()
        database.connect().close()
    except: pass

    # <<-- BEGIN MODIFICATION: Don't delete DB files anymore, only cache content -->>
    
    # 1. Define cache tables that can be safely emptied
    CACHE_TABLES_MAIN = ['maincache', 'sources_cache']
    CACHE_TABLES_SYNC = ['meta_cache_items', 'meta_cache_seasons', 'discovery_cache', 'tmdb_discovery', 
                         'trakt_lists', 'user_lists', 'user_list_items', 'tmdb_custom_lists', 
                         'tmdb_custom_list_items', 'tmdb_account_lists', 'tmdb_recommendations']

    def _clear_tables(conn, tables):
        c = conn.cursor()
        wiped = False
        for table in tables:
            for _a in range(20):
                try:
                    c.execute(f"DELETE FROM {table}")
                    if c.rowcount > 0: wiped = True
                    break
                except Exception as _e:
                    if 'database is locked' in str(_e) and _a < 19:
                        time.sleep(0.4 + 0.15 * _a)
                        continue
                    break
        return wiped

    try:
        conn_main = database.connect()
        try:
            if _clear_tables(conn_main, CACHE_TABLES_MAIN):
                deleted = True
            for _a in range(20):
                try:
                    conn_main.commit()
                    break
                except Exception as _e:
                    if 'database is locked' in str(_e) and _a < 19:
                        time.sleep(0.4 + 0.15 * _a)
                        continue
                    raise
            try:
                conn_main.execute("VACUUM")
            except Exception as _e:
                log(f"[CACHE] Main VACUUM skipped: {_e}", xbmc.LOGWARNING)
        finally:
            try: conn_main.close()
            except: pass
        log("[CACHE] Main cache tables cleared.")
    except Exception as e:
        log(f"[CACHE] Error clearing main tables: {e}", xbmc.LOGERROR)

    try:
        conn_sync = trakt_sync.get_connection()
        try:
            if _clear_tables(conn_sync, CACHE_TABLES_SYNC):
                deleted = True
            for _a in range(20):
                try:
                    conn_sync.commit()
                    break
                except Exception as _e:
                    if 'database is locked' in str(_e) and _a < 19:
                        time.sleep(0.4 + 0.15 * _a)
                        continue
                    raise
            try:
                conn_sync.execute("VACUUM")
            except Exception as _e:
                log(f"[CACHE] Sync VACUUM skipped: {_e}", xbmc.LOGWARNING)
        finally:
            try: conn_sync.close()
            except: pass
        log("[CACHE] Sync cache tables cleared.")
    except Exception as e:
        log(f"[CACHE] Error clearing DB tables: {e}", xbmc.LOGERROR)

    # <<-- END MODIFICATION -->>

    # --- Keep your original logic for JSON files and window properties ---
    json_files = ['sources_cache.json', 'tmdb_lists_cache.json', 'trakt_lists_cache.json', 'trakt_history.json', 'last_sync.json']

    for jf in json_files:
        path = os.path.join(ADDON_DATA_DIR, jf)
        if xbmcvfs.exists(path):
            try:
                xbmcvfs.delete(path)
                deleted = True # Set 'deleted' to True to maintain logic
            except: pass

    try:
        trakt_sync.init_database() 
        database.check_database()  
        log("[CACHE] Databases re-initialized (structure only).")
    except Exception as e:
        log(f"[CACHE] Error re-initializing: {e}", xbmc.LOGERROR)

    try:
        window = xbmcgui.Window(10000)
        props = [
            'tmdbmovies.src_id', 'tmdbmovies.src_data', 'tmdbmovies.need_fast_return',
            'tmdb.list.id', 'tmdb.list.data', 'tmdb.list.use_cache',
            'tmdb.seasons.id', 'tmdb.seasons.data', 'tmdb.seasons.use_cache',
            'tmdb.episodes.id', 'tmdb.episodes.data', 'tmdb.episodes.use_cache',
            'tmdbmovies.title', 'tmdbmovies.poster', 'tmdbmovies.plot', 'tmdbmovies.fanart', 'tmdbmovies.clearlogo',
            'tmdbmovies.total_results', 'tmdbmovies.icon', 'tmdbmovies.flag_ro', 'tmdbmovies.torrent.name',
            'tmdbmovies.count_4k', 'tmdbmovies.count_1080p', 'tmdbmovies.count_720p', 'tmdbmovies.count_sd',
            'tmdbmovies.has_ro_sub', 'tmdbmovies.sub_text_label',
            'tmdbmovies_fast_cache_version'
        ]
        for p in props:
            window.clearProperty(p)
        # Clear all RAM fast cache entries
        for prop in window.getPropertyNames():
            if prop.startswith('tmdbmovies_fast_'):
                window.clearProperty(prop)
        # Clear global RAM meta pool
        try:
            from resources.lib.cache import ram_pool_clear
            ram_pool_clear()
        except: pass
    except: pass

    return deleted # Changed from 'True' to 'deleted' to reflect if something was deleted

def clear_all_caches_with_notification():
    success = clear_cache()
    if success:
        xbmcgui.Dialog().notification(
            "[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]", "Cache cleared!",
            TMDbmovies_ICON, 3000, False)
    else:
        xbmcgui.Dialog().notification(
            "[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]",
            "Cache was already empty.",
            TMDbmovies_ICON, 3000, False)
    return success


def set_resume_point(li, resume_seconds, total_seconds):
    """
    Sets the resume point for a ListItem.
    Compatible with Kodi 20+ (no deprecation warnings).
    """
    try:
    # New method (Kodi 20+)
        info_tag = li.getVideoInfoTag()
        if resume_seconds > 0 and total_seconds > 0:
            info_tag.setResumePoint(float(resume_seconds), float(total_seconds))
        else:
            info_tag.setResumePoint(0.0, 0.0)
    except AttributeError:
        # Fallback for Kodi 19 (Leia)
        try:
            if resume_seconds > 0 and total_seconds > 0:
                li.setProperty('resumetime', str(int(resume_seconds)))
                li.setProperty('totaltime', str(int(total_seconds)))
            else:
                li.setProperty('resumetime', '0')
                li.setProperty('totaltime', '0')
        except Exception:
            pass
    except Exception:
        pass


# =============================================================================
# DOWNLOADS BROWSER & MANAGER
# =============================================================================

def build_downloads_list(params):
    try:
        handle = int(sys.argv[1])
    except:
        handle = -1

    addon_id = ADDON.getAddonInfo('id')
    base_path = f"special://profile/addon_data/{addon_id}/Downloads/"
    
    current_folder = params.get('folder')
    path_to_list = unquote(current_folder) if current_folder else base_path

    if not path_to_list.endswith('/'):
        path_to_list += '/'

    if not xbmcvfs.exists(path_to_list):
        xbmcvfs.mkdirs(path_to_list)

    listing = []
    dirs, files = xbmcvfs.listdir(path_to_list)
    dirs.sort()
    files.sort()

    # --- FOLDERS (Keep Rename and Delete from you) ---
    for d in dirs:
        full_path = path_to_list + d + "/"
        li = xbmcgui.ListItem(label=f"[COLOR yellow]{d}[/COLOR]")
        li.setArt({'icon': 'DefaultFolder.png'})
        try:
            li.getVideoInfoTag().setTitle(d)
        except:
            pass
        
        # Meniu contextual personalizat DOAR pentru foldere
        cm = []
        del_url = f"RunPlugin({sys.argv[0]}?mode=delete_download&path={quote(full_path)})"
        cm.append(('Delete Folder', del_url))
        
        ren_url = f"RunPlugin({sys.argv[0]}?mode=rename_download&path={quote(full_path)})"
        cm.append(('Rename Folder', ren_url))
        
        li.addContextMenuItems(cm)
        
        url = f"{sys.argv[0]}?mode=downloads_menu&folder={quote(full_path)}"
        listing.append((url, li, True))

    # --- FILES (Let Kodi handle context menu) ---
    for f in files:
        if f.lower().endswith(('.mkv', '.mp4', '.avi', '.ts', '.strm', '.mov')):
            full_path = path_to_list + f
            
            li = xbmcgui.ListItem(label=f"[COLOR cyan]{f}[/COLOR]")
            # Important: setInfo helps Kodi activate Resume options
            try:
                li.getVideoInfoTag().setTitle(f)
            except:
                pass
            li.setArt({'icon': 'DefaultVideo.png'})
            li.setProperty('IsPlayable', 'true')
            li.setPath(full_path)
            
            # NO longer add li.addContextMenuItems(cm_file) here.
            # Kodi will automatically show its standard menu (Play, Resume, Delete, Rename).
            
            listing.append((full_path, li, False))

    xbmcplugin.addDirectoryItems(handle, listing, len(listing))
    xbmcplugin.setContent(handle, 'files')
    xbmcplugin.endOfDirectory(handle)
    

def delete_download_folder(params):
    path = unquote(params.get('path'))
    
    dialog = xbmcgui.Dialog()
    if not dialog.yesno("Delete Folder", f"Are you sure you want to delete the folder?\n[COLOR yellow]{path}[/COLOR]"):
        return

    try:
        # Empty the folder first (Kodi doesn't delete non-empty folders)
        dirs, files = xbmcvfs.listdir(path)
        for f in files:
            xbmcvfs.delete(path + f)
            
        if dirs:
            xbmcgui.Dialog().notification("Error", "The folder contains other folders.", xbmcgui.NOTIFICATION_ERROR)
            return

        if xbmcvfs.rmdir(path):
            xbmcgui.Dialog().notification("Success", "Folder deleted.", TMDbmovies_ICON, 3000, False)
            xbmc.executebuiltin("Container.Refresh")
        else:
            xbmcgui.Dialog().notification("Error", "Could not delete.", xbmcgui.NOTIFICATION_ERROR)
    except Exception as e:
        log(f"[DOWNLOADS] Delete Error: {e}", xbmc.LOGERROR)


def rename_download_folder(params):
    path = unquote(params.get('path'))
    
    clean_path = path.rstrip('/') 
    old_name = clean_path.split('/')[-1]
    parent_dir = clean_path.rsplit('/', 1)[0] + '/'
    
    dialog = xbmcgui.Dialog()
    new_name = dialog.input("Rename", defaultt=old_name)
    
    if not new_name or new_name == old_name:
        return

    new_path = parent_dir + new_name + "/"
    
    try:
        # Try the rename
        success = False
        if xbmcvfs.rename(clean_path, new_path[:-1]): success = True
        elif xbmcvfs.rename(path, new_path): success = True
        
        if success:
            xbmcgui.Dialog().notification("Success", "Renamed.", TMDbmovies_ICON, 3000, False)
            xbmc.executebuiltin("Container.Refresh")
        else:
            xbmcgui.Dialog().notification("Error", "Could not rename.", xbmcgui.NOTIFICATION_ERROR)
    except Exception as e:
        log(f"[DOWNLOADS] Rename Error: {e}", xbmc.LOGERROR)


# =============================================================================
# AUTO-MAINTENANCE (CLEAN SETTINGS ON UPDATE)
# =============================================================================

def clean_settings():
    import xml.etree.ElementTree as ET
    from resources.lib.config import ADDON, ADDON_DATA_DIR
    
    addon_path = xbmcvfs.translatePath(ADDON.getAddonInfo('path'))
    default_xml = os.path.join(addon_path, 'resources', 'settings.xml')
    profile_xml = os.path.join(ADDON_DATA_DIR, 'settings.xml')
    
    if not os.path.exists(default_xml) or not os.path.exists(profile_xml):
        return False
        
    try:
        # 1. Read current official settings from addon
        tree_default = ET.parse(default_xml)
        root_default = tree_default.getroot()
        # Collect all valid IDs
        active_settings = [item.get('id') for item in root_default.iter('setting') if item.get('id')]
        
        # 2. Read settings from user profile
        tree_profile = ET.parse(profile_xml)
        root_profile = tree_profile.getroot()
        
        _PRESERVE_PREFIXES = ('trakt_', 'torrserver_')
        removed_count = 0
        # 3. Search for orphan/old settings and delete them
        for item in root_profile.findall('setting'):
            _id = item.get('id') or ''
            if _id in active_settings or _id == 'installed_version':
                continue
            if any(_id.startswith(p) for p in _PRESERVE_PREFIXES):
                continue
            root_profile.remove(item)
            removed_count += 1
                
        # 4. If we deleted something, save the clean file
        if removed_count > 0:
            tree_profile.write(profile_xml, encoding='utf-8', xml_declaration=True)
            log(f"[MAINTENANCE] Clean successful! Deleted {removed_count} old/invalid settings.")
            return True
            
    except Exception as e:
        log(f"[MAINTENANCE] Error cleaning settings: {e}", xbmc.LOGERROR)
        
    return False


def check_addon_update():
    """
    Checks if the addon has been updated. If so, runs maintenance.
    Called automatically on Kodi startup (from service.py).
    """
    from resources.lib.config import ADDON
    
    current_version = ADDON.getAddonInfo('version')
    saved_version = ADDON.getSetting('installed_version')
    
    if saved_version != current_version:
        log(f"[MAINTENANCE] Update detected: from v{saved_version} to v{current_version}. Running auto-cleanup...")
        
        # 1. Clean old settings from XML
        clean_settings()
        
        # 2. Clear cache (to prevent conflicts with old data structures)
        # Will NOT delete watch history, only temporary cache!
        from resources.lib.utils import clear_cache
        clear_cache()
        
        # 3. Save new version
        ADDON.setSetting('installed_version', current_version)
        log("[MAINTENANCE] Update and cleanup process completed successfully!")
        return True
    return False


# =============================================================================
# SUPPORT & TROUBLESHOOTING (LOG & DONATIONS)
# =============================================================================

def upload_logfile():
    """Reads kodi.log file and uploads it to paste.kodi.tv"""
    import requests
    dialog = xbmcgui.Dialog()

    log_idx = dialog.select("Select log file", ["[B][COLOR FF6AFB92]kodi.log[/COLOR][/B] - active log", "[B][COLOR FFFF4444]kodi.old.log[/COLOR][/B] - old log"])
    if log_idx is None or log_idx < 0:
        return

    log_filename = 'kodi.log' if log_idx == 0 else 'kodi.old.log'
    log_file = xbmcvfs.translatePath(f'special://logpath/{log_filename}')
    url = 'https://paste.kodi.tv/'

    if not xbmcvfs.exists(log_file):
        dialog.ok("Error", f"File {log_filename} not found.")
        return

    # Redus la 2 randuri
    if not dialog.yesno("Upload Kodi Log", f"Do you want to upload {log_filename} to paste.kodi.tv?\nUseful for error reporting."):
        return

    xbmc.executebuiltin('ActivateWindow(busydialognocancel)')
    try:
        f = xbmcvfs.File(log_file, 'r')
        text = f.read()
        f.close()
        
        if isinstance(text, str):
            text = text.encode('utf-8', errors='ignore')
            
        response = requests.post(f"{url}documents", data=text, timeout=10.0).json()
        xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
        
        if 'key' in response:
            link = f"{url}{response['key']}"
            colored_link = f"[B][COLOR FF6AFB92]{link}[/COLOR][/B]"
            # Redus la 2 randuri
            dialog.ok("Upload Successful", f"The log was uploaded successfully!\n\nLink: {colored_link}")
        else:
            dialog.ok("Error", "Upload failed. Check the Kodi log.")
            
    except Exception as e:
        xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
        log(f"[UTILS] Upload Log Error: {e}", xbmc.LOGERROR)
        dialog.ok("Error", f"Load error: {str(e)}")


_LOG_ERROR_RE = re.compile(r' (ERROR|error)(?: <[^>]*>)?: ')
_LOG_WARNING_RE = re.compile(r' (WARNING|warning)(?: <[^>]*>): ')

def _style_kodi_log(text):
    out = []
    for line in text.splitlines():
        stripped = line.lstrip(' ')
        if stripped is not line and len(stripped) != len(line):
            stripped = '\u00a0' * (len(line) - len(stripped)) + stripped
        if _LOG_ERROR_RE.search(stripped):
            stripped = _LOG_ERROR_RE.sub(lambda m: '[COLOR red]%s[/COLOR]' % m.group(0), stripped)
        elif _LOG_WARNING_RE.search(stripped):
            stripped = _LOG_WARNING_RE.sub(lambda m: '[COLOR gold]%s[/COLOR]' % m.group(0), stripped)
        out.append(stripped)
    return '\n'.join(out)

def view_kodi_log():
    
    dialog = xbmcgui.Dialog()
    
    # 1. Alegerea fisierului de log
    log_idx = dialog.select("Select log file", ["[B][COLOR FF6AFB92]kodi.log[/COLOR][/B] - active log", "[B][COLOR FFFF4444]kodi.old.log[/COLOR][/B] - old log"])
    if log_idx is None or log_idx < 0:
        return # Utilizatorul a anulat

    # Stabilim numele fisierului pe baza selectiei
    log_filename = 'kodi.log' if log_idx == 0 else 'kodi.old.log'
    log_file = xbmcvfs.translatePath(f'special://logpath/{log_filename}')
    
    if not xbmcvfs.exists(log_file):
        dialog.ok("Error", f"File {log_filename} not found.")
        return

    # 2. Alegerea ordinii de afisare
    order_idx = dialog.select(f"Display order ({log_filename})", ["[B][COLOR FF87CEEB]Ascending[/COLOR][/B] - oldest first", "[B][COLOR FFFFD700]Descending[/COLOR][/B] - newest first"])
    if order_idx is None or order_idx < 0:
        return # Utilizatorul a anulat

    err_idx = dialog.select("Show errors only?", ["[B][COLOR FFFF4444]Yes[/COLOR][/B] - errors only", "[B][COLOR FF6AFB92]No[/COLOR][/B] - full log"])
    if err_idx is None or err_idx < 0:
        return
    errors_only = (err_idx == 0)
    last_200 = False
    if not errors_only:
        scope_idx = dialog.select("How much of the log to show?", ["[B][COLOR FF87CEEB]Full log[/COLOR][/B] - entire file", "[B][COLOR FFFFD700]Last 200 lines[/COLOR][/B] - newest entries"])
        if scope_idx is None or scope_idx < 0:
            return
        last_200 = (scope_idx == 1)
    try:
        f = xbmcvfs.File(log_file, 'r')
        raw = f.read()
        f.close()
    except Exception as e:
        xbmc.log(f"[UTILS] View Log Error: {e}", xbmc.LOGERROR)
        dialog.ok("Error", f"Could not read {log_filename}.")
        return

    if isinstance(raw, bytes):
        raw = raw.decode('utf-8', errors='ignore')

    lines = raw.splitlines()
    if errors_only:
        lines = [l for l in lines if _LOG_ERROR_RE.search(l)]
        if not lines:
            dialog.ok(log_filename, "No errors found.")
            return
    elif last_200 and len(lines) > 200:
        lines = lines[-200:]
    file_color = 'FF6AFB92' if log_idx == 0 else 'FFFF4444'
    heading = f"[B][COLOR {file_color}]{log_filename}[/COLOR][/B] - {'newest first' if order_idx == 1 else 'oldest first'}"
    if errors_only:
        heading += " - errors only"
    elif last_200:
        heading += " - last 200 lines"
    if order_idx == 1:
        lines.reverse()

    dialog.textviewer(heading, _style_kodi_log('\n'.join(lines)))


INVOKER_SETTING = 'reuse_language_invoker'
INVOKER_ADDONS = ('plugin.video.tmdbmovies', 'tmdbm.trailers')
INVOKER_SHORT = {'plugin.video.tmdbmovies': 'Movies', 'tmdbm.trailers': 'Trailers'}

def _invoker_xml_path(addon_id):
    return xbmcvfs.translatePath('special://home/addons/%s/addon.xml' % addon_id)

def get_invoker_setting():
    try:
        return (ADDON.getSetting(INVOKER_SETTING) or 'true').strip().lower()
    except:
        return 'true'

def read_invoker_xml(addon_id):
    try:
        import xml.etree.ElementTree as ET
        path = _invoker_xml_path(addon_id)
        if not xbmcvfs.exists(path):
            return None
        tree = ET.parse(path)
        item = next(tree.getroot().iter('reuselanguageinvoker'), None)
        if item is not None and item.text:
            return item.text.strip()
        return None
    except Exception as e:
        xbmc.log(f"[UTILS] Invoker XML read error ({addon_id}): {e}", xbmc.LOGERROR)
        return None

def apply_invoker_to_xml(addon_id, value):
    try:
        import xml.etree.ElementTree as ET
        path = _invoker_xml_path(addon_id)
        if not xbmcvfs.exists(path):
            return None
        tree = ET.parse(path)
        item = next(tree.getroot().iter('reuselanguageinvoker'), None)
        if item is None:
            return False
        item.text = value
        tree.write(path, encoding='utf-8', xml_declaration=True)
        return True
    except Exception as e:
        xbmc.log(f"[UTILS] Invoker XML write error ({addon_id}): {e}", xbmc.LOGERROR)
        return False

def _ask_invoker_reload(desired, before):
    try:
        import time
        time.sleep(60)
        _col = lambda v: '[B][COLOR FF6AFB92]TRUE[/COLOR][/B]' if v == 'true' else '[B][COLOR FFF535AA]FALSE[/COLOR][/B]'
        _txt = "The addon update reset addon.xml to " + _col(before) + ", but your setting is " + _col(desired) + ".[CR]Reload the profile now to re-apply your choice?"
        if xbmcgui.Dialog().yesno("Reuse Language Invoker", _txt, nolabel="Later", yeslabel="Reload now"):
            try:
                xbmc.executebuiltin('LoadProfile(%s)' % xbmc.getInfoLabel('System.ProfileName'))
                xbmc.log('[UTILS] Invoker profile reloaded after user confirm.', xbmc.LOGINFO)
            except:
                pass
        else:
            xbmc.log('[UTILS] Invoker reload postponed by user. Restart Kodi to apply.', xbmc.LOGINFO)
    except:
        pass

def check_language_invoker_mismatch():
    try:
        setting = get_invoker_setting()
        fixed = []
        before = setting
        for addon_id in INVOKER_ADDONS:
            current = read_invoker_xml(addon_id)
            if current is None or current == setting:
                continue
            before = current
            if apply_invoker_to_xml(addon_id, setting):
                fixed.append(addon_id)
        if fixed:
            xbmc.log(f"[UTILS] Invoker mismatch fixed ({', '.join(fixed)} -> {setting}). Asking user for profile reload.", xbmc.LOGINFO)
            try:
                import threading
                threading.Thread(target=_ask_invoker_reload, args=(setting, before), daemon=True).start()
            except:
                pass
    except:
        pass

def toggle_language_invoker():
    try:
        xbmc.executebuiltin('Dialog.Close(all,true)')
        xbmc.sleep(500)
    except: pass
    dialog = xbmcgui.Dialog()
    try:
        current = get_invoker_setting()
        new_value = 'false' if current == 'true' else 'true'
        if not dialog.yesno("Reuse Language Invoker", "Current: " + ('[B][COLOR FF6AFB92]TRUE[/COLOR][/B]' if current == 'true' else '[B][COLOR FFF535AA]FALSE[/COLOR][/B]') + ". Switch to " + ('[B][COLOR FF6AFB92]TRUE[/COLOR][/B]' if new_value == 'true' else '[B][COLOR FFF535AA]FALSE[/COLOR][/B]') + "?"):
            return
        ADDON.setSetting(INVOKER_SETTING, new_value)
        applied = []
        missing = []
        for addon_id in INVOKER_ADDONS:
            if not xbmcvfs.exists(_invoker_xml_path(addon_id)):
                if addon_id != 'plugin.video.tmdbmovies':
                    missing.append(INVOKER_SHORT.get(addon_id, addon_id))
                continue
            if apply_invoker_to_xml(addon_id, new_value):
                applied.append(INVOKER_SHORT.get(addon_id, addon_id))
        if 'Movies' not in applied:
            dialog.ok("Error", "Could not write addon.xml.")
            return
        _inv_colored = '[B][COLOR FF6AFB92]TRUE[/COLOR][/B]' if new_value == 'true' else '[B][COLOR FFF535AA]FALSE[/COLOR][/B]'
        _movies_colored = '[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/COLOR][/B]'
        _trailers_colored = '[B][COLOR FF00CED1]TMDbM [COLOR FFF70D1A]Trailers[/COLOR][/COLOR][/B]'
        if 'Trailers' in applied:
            _scope = _movies_colored + ' + ' + _trailers_colored
        else:
            _scope = _movies_colored + ' only'
            if missing:
                _scope += ' (' + ', '.join(missing) + ' not installed)'
        dialog.ok("Reuse Language Invoker", "Set to " + _inv_colored + " (" + _scope + ")" + chr(10) + "Reload profile to apply.")
        try:
            xbmc.executebuiltin('LoadProfile(%s)' % xbmc.getInfoLabel('System.ProfileName'))
        except: pass
    except Exception as e:
        xbmc.log(f"[UTILS] Invoker toggle error: {e}", xbmc.LOGERROR)
    

DONATE_URL = 'https://ko-fi.com/angelitto'


def show_donate_link():
    qr_path = os.path.join(ADDON_PATH, 'resources', 'media', 'donate_qr.png')
    if not xbmcvfs.exists(qr_path):
        # Comprimat la exact 3 randuri - GARANTAT fara scroll!
        text = (
            "Enjoying the addon?\n"
            "Support its development and buy me a coffee!\n"
            f"Link: [B][COLOR FF6AFB92]{DONATE_URL}[/COLOR][/B]\n"
            "Thank you for your support!"
        )
        xbmcgui.Dialog().ok("Support the Project", text)
        return

    from resources.lib.auth_dialog import QRProgressDialog, run_modal_main_thread
    msg = (
        "Enjoying the addon?\n"
        "Support its development\n"
        "and buy me a coffee!\n"
        f"Link: [B][COLOR FF6AFB92]{DONATE_URL}[/COLOR][/B]\n"
        "Thank you for your support!"
    )
    pdialog = QRProgressDialog(
        'auth_qr.xml', ADDON_PATH, 'Default', '1080i',
        heading='[B][COLOR FF6AFB92]Support the Project[/COLOR][/B]',
        qr_image=qr_path,
        icon=os.path.join(ADDON_PATH, 'resources', 'media', 'favorites.png'),
        addon_icon=TMDbmovies_ICON,
        content=msg,
    )
    run_modal_main_thread(pdialog)


def perform_trakt_backup(manual=False):
    """Saves Trakt history (Movies + Episodes) from SQL to a local JSON file."""
    import time
    import datetime
    from resources.lib.utils import write_json, read_json, log
    from resources.lib import trakt_sync

    try:
        # Check settings if running in automatic mode (background)
        if not manual:
            try: auto_enabled = ADDON.getSetting('trakt_auto_backup') == 'true'
            except: auto_enabled = False
            
            if not auto_enabled:
                return

            try: freq = ADDON.getSetting('trakt_backup_frequency') # 0=Weekly, 1=Monthly
            except: freq = '0'
            
            last_backup_file = os.path.join(ADDON_DATA_DIR, 'last_backup_time.json')
            last_time_data = read_json(last_backup_file) or {}
            last_run_raw = last_time_data.get('last_run', 0)
            # Parse string (DD-MM-YYYY HH:MM) or float (old format) to timestamp
            if isinstance(last_run_raw, str):
                try:
                    last_backup = time.mktime(time.strptime(last_run_raw, '%d-%m-%Y %H:%M'))
                except Exception:
                    last_backup = 0
            else:
                last_backup = float(last_run_raw)
            
            days_passed = (time.time() - last_backup) / 86400
            
            if freq == '0' and days_passed < 7:
                return # Hasn't been a week
            elif freq == '1' and days_passed < 30:
                return # Hasn't been a month

        # 1. Create folder if it doesn't exist
        backup_dir = os.path.join(ADDON_DATA_DIR, 'Trakt_History')
        if not xbmcvfs.exists(backup_dir):
            xbmcvfs.mkdirs(backup_dir)

        # 2. Extract data from local SQLite database
        backup_data = {'movies': [], 'episodes': []}
        conn = trakt_sync.get_connection()
        c = conn.cursor()

        try:
            c.execute("SELECT tmdb_id, title, year, last_watched_at FROM trakt_watched_movies")
            for row in c.fetchall():
                backup_data['movies'].append(dict(row))
        except: pass

        try:
            c.execute("SELECT tmdb_id, title, season, episode, last_watched_at FROM trakt_watched_episodes")
            for row in c.fetchall():
                backup_data['episodes'].append(dict(row))
        except: pass
        
        conn.close()

        if not backup_data['movies'] and not backup_data['episodes']:
            if manual:
                xbmcgui.Dialog().notification("[B][COLOR pink]Backup[/COLOR][/B]", "No history to save!", xbmcgui.NOTIFICATION_WARNING)
            return

        # 3. Generate file name based on current date
        date_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
        filename = f"Trakt_History_{date_str}.json"
        filepath = os.path.join(backup_dir, filename)

        # 4. Save file
        if write_json(filepath, backup_data):
            log(f"[BACKUP] Complete save in: {filepath}")
            
            # Update last backup time
            if not manual:
                last_backup_file = os.path.join(ADDON_DATA_DIR, 'last_backup_time.json')
                write_json(last_backup_file, {'last_run': time.strftime('%d-%m-%Y %H:%M')})

            if manual:
                msg = f"History saved successfully!\nSaved [B][COLOR FF00FA9A]{len(backup_data['movies'])} movies[/COLOR][/B] and [B][COLOR FF00FA9A]{len(backup_data['episodes'])} episodes[/COLOR][/B] at:\n[B][COLOR yellow]Trakt_History/{filename}[/COLOR][/B]"
                xbmcgui.Dialog().ok("Backup Trakt Complet", msg)

    except Exception as e:
        log(f"[BACKUP] Error saving history: {e}", xbmc.LOGERROR)
        if manual:
            xbmcgui.Dialog().notification("Error", "Error creating backup.", xbmcgui.NOTIFICATION_ERROR)


def perform_mdblist_backup(manual=False):
    """Saves MDBList history (Movies + Episodes) from SQL to a local JSON file."""
    import time
    import datetime
    from resources.lib.utils import write_json, read_json, log
    from resources.lib import mdblist_sync

    try:
        # Check settings if running in automatic mode (background)
        if not manual:
            try: auto_enabled = ADDON.getSetting('mdblist_auto_backup') == 'true'
            except: auto_enabled = False
            
            if not auto_enabled:
                return

            try: freq = ADDON.getSetting('mdblist_backup_frequency') # 0=Weekly, 1=Monthly
            except: freq = '0'
            
            last_backup_file = os.path.join(ADDON_DATA_DIR, 'last_mdblist_backup_time.json')
            last_time_data = read_json(last_backup_file) or {}
            last_run_raw = last_time_data.get('last_run', 0)
            # Parse string (DD-MM-YYYY HH:MM) or float (old format) to timestamp
            if isinstance(last_run_raw, str):
                try:
                    last_backup = time.mktime(time.strptime(last_run_raw, '%d-%m-%Y %H:%M'))
                except Exception:
                    last_backup = 0
            else:
                last_backup = float(last_run_raw)
            
            days_passed = (time.time() - last_backup) / 86400
            
            if freq == '0' and days_passed < 7:
                return # Hasn't been a week
            elif freq == '1' and days_passed < 30:
                return # Hasn't been a month

        # 1. Create folder if it doesn't exist
        backup_dir = os.path.join(ADDON_DATA_DIR, 'MDBList_History')
        if not xbmcvfs.exists(backup_dir):
            xbmcvfs.mkdirs(backup_dir)

        # 2. Extract data from local SQLite database
        backup_data = {'movies': [], 'episodes': []}
        conn = mdblist_sync.get_connection()
        c = conn.cursor()

        try:
            c.execute("SELECT tmdb_id, title, year, last_watched_at FROM mdblist_watched_movies")
            for row in c.fetchall():
                backup_data['movies'].append(dict(row))
        except: pass

        try:
            c.execute("SELECT tmdb_id, title, season, episode, last_watched_at FROM mdblist_watched_episodes")
            for row in c.fetchall():
                backup_data['episodes'].append(dict(row))
        except: pass
        
        conn.close()

        if not backup_data['movies'] and not backup_data['episodes']:
            if manual:
                xbmcgui.Dialog().notification("[B][COLOR lightskyblue]Backup[/COLOR][/B]", "No history to save!", xbmcgui.NOTIFICATION_WARNING)
            return

        # 3. Generate file name based on current date
        date_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
        filename = f"MDBList_History_{date_str}.json"
        filepath = os.path.join(backup_dir, filename)

        # 4. Save file
        if write_json(filepath, backup_data):
            log(f"[BACKUP] Complete save in: {filepath}")
            
            # Update last backup time
            if not manual:
                last_backup_file = os.path.join(ADDON_DATA_DIR, 'last_mdblist_backup_time.json')
                write_json(last_backup_file, {'last_run': time.strftime('%d-%m-%Y %H:%M')})

            if manual:
                msg = f"History saved successfully!\nSaved [B][COLOR FF00FA9A]{len(backup_data['movies'])} movies[/COLOR][/B] and [B][COLOR FF00FA9A]{len(backup_data['episodes'])} episodes[/COLOR][/B] at:\n[B][COLOR yellow]MDBList_History/{filename}[/COLOR][/B]"
                xbmcgui.Dialog().ok("Backup MDBList Complet", msg)

    except Exception as e:
        log(f"[BACKUP] Error saving MDBList history: {e}", xbmc.LOGERROR)
        if manual:
            xbmcgui.Dialog().notification("Error", "Error creating backup.", xbmcgui.NOTIFICATION_ERROR)


def make_qr(url, filename='auth_qr.png'):
    if not url:
        return None
    try:
        from resources.lib.externals import segno
        ensure_addon_dir()
        base, dot, ext = filename.rpartition('.')
        if not dot:
            ext, base = 'png', filename
        unique = f'{base}_{int(time.time() * 1000)}.{ext}'
        dest = os.path.join(ADDON_DATA_DIR, unique)
        # Curatam fisierele QR vechi (acelasi base) ca sa nu se acumuleze
        for old in glob.glob(os.path.join(ADDON_DATA_DIR, f'{base}_[0-9]*.{ext}')):
            try: xbmcvfs.delete(old)
            except: pass
        qrcode = segno.make(url, micro=False)
        qrcode.save(dest, scale=20)
        return dest
    except Exception as e:
        log(f"[UTILS] make_qr error: {e}", xbmc.LOGERROR)
        return None


