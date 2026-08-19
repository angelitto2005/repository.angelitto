# -*- coding: utf-8 -*-
"""
Simkl API client — PIN authentication (OAuth device-style) + sync endpoints.
Toate endpointurile necesare: watched, watchlist, ratings, playback, scrobble, calendar.

Reguli API (documentate in docs simkl + respectate aici):
  - Fiecare request: query params obligatorii client_id & app-name & app-version
  - Header User-Agent descriptiv
  - Rate limits: 10 GET/s + 1 POST/s per client (throttle global aici)
  - 429 -> backoff; 412 client_id_failed = throttle block; 409 pe scrobble stop
    = episod deja vizionat (se trateaza ca succes)
"""

import os
import time
import threading
import datetime
import xbmc
import xbmcgui
import requests

from resources.lib.config import SIMKL_API_URL, SIMKL_CLIENT_ID, ADDON, ADDON_PATH

SIMKL_ICON = os.path.join(ADDON_PATH, 'resources', 'media', 'simkl.png')

APP_NAME = 'TMDbMovies'
APP_VERSION = '1.0'

# Throttle global (reguli rate limits Simkl: 10 GET/s + 1 POST/s per client)
_LOCK = threading.Lock()
_LAST_GET = 0.0
_LAST_POST = 0.0

def _throttle_get():
    global _LAST_GET
    with _LOCK:
        delta = time.time() - _LAST_GET
        if delta < 0.1:
            time.sleep(0.1 - delta)
        _LAST_GET = time.time()

def _throttle_post():
    global _LAST_POST
    with _LOCK:
        delta = time.time() - _LAST_POST
        if delta < 1.0:
            time.sleep(1.0 - delta)
        _LAST_POST = time.time()

_SESSION = None

def _get_session():
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
    return _SESSION


class SIMKLAPI:
    def __init__(self):
        self.base_url = SIMKL_API_URL.rstrip('/')
        self.client_id = SIMKL_CLIENT_ID
        self.session = _get_session()

    # ------------------------------------------------------------------
    # SETTINGS / TOKEN
    # ------------------------------------------------------------------
    def _get_token(self):
        return (ADDON.getSetting('simkl_access_token') or '').strip()

    def _save_token(self, access_token):
        ADDON.setSetting('simkl_access_token', access_token)

    def _clear_token(self):
        ADDON.setSetting('simkl_access_token', '')
        ADDON.setSetting('simkl_username', '')

    def set_username(self, username):
        ADDON.setSetting('simkl_username', username)

    def is_authenticated(self):
        return bool(self._get_token())

    def _base_params(self):
        return {
            'client_id': self.client_id,
            'app-name': APP_NAME,
            'app-version': APP_VERSION,
        }

    # ------------------------------------------------------------------
    # REQUEST
    # ------------------------------------------------------------------
    def _request(self, method, path, params=None, json_data=None, silent_404=False, is_auth=False):
        url = f'{self.base_url}/{path.lstrip("/")}'
        qp = self._base_params()
        if params:
            qp.update(params)
        headers = {
            'User-Agent': f'{APP_NAME}/{APP_VERSION} (Kodi addon)',
            'Accept': 'application/json',
        }
        token = self._get_token()
        if not is_auth and token:
            headers['Authorization'] = f'Bearer {token}'
        elif not is_auth and not token:
            return None

        if json_data is not None:
            headers['Content-Type'] = 'application/json'

        if method == 'POST':
            _throttle_post()
        else:
            _throttle_get()

        try:
            r = self.session.request(method, url, params=qp, json=json_data, headers=headers, timeout=15)
            if r.status_code == 429:
                retry_after = int(r.headers.get('Retry-After', 5))
                xbmc.log(f'[SIMKL] Rate limited (429), retrying after {retry_after}s', xbmc.LOGINFO)
                time.sleep(min(retry_after, 15))
                if method == 'POST':
                    _throttle_post()
                else:
                    _throttle_get()
                r = self.session.request(method, url, params=qp, json=json_data, headers=headers, timeout=15)
            if r.status_code == 401:
                xbmc.log('[SIMKL] HTTP 401 - token invalid/expirat', xbmc.LOGWARNING)
                return None
            if r.status_code == 412:
                xbmc.log('[SIMKL] HTTP 412 client_id_failed - throttled by Simkl. Waiting 60s.', xbmc.LOGWARNING)
                time.sleep(60)
                return None
            if r.status_code == 409 and method == 'POST' and 'scrobble/stop' in path:
                # Episod deja vizionat - nu e eroare, e comportament asteptat
                xbmc.log('[SIMKL] scrobble/stop 409 - deja vizionat, tratat ca succes', xbmc.LOGINFO)
                return {}
            r.raise_for_status()
            if r.status_code == 204:
                return {}
            if r.content:
                # 200 cu body JSON null (ex. remove-from-list, history/remove) —
                # e SUCCES, nu eroare. None e rezervat pentru esec (401/412/429/
                # HTTPError), altfel `if result is not None` rateaza remove-urile.
                try:
                    j = r.json()
                except Exception:
                    j = {}
                return {} if j is None else j
            return {}
        except requests.HTTPError as e:
            if silent_404 and e.response.status_code == 404:
                xbmc.log(f'[SIMKL] HTTP 404 on {method} /{path}', xbmc.LOGDEBUG)
            else:
                xbmc.log(f'[SIMKL] HTTP {e.response.status_code} on {method} /{path}: {e.response.text[:300]}', xbmc.LOGERROR)
            return None
        except Exception as e:
            xbmc.log(f'[SIMKL] {method} /{path} error: {e}', xbmc.LOGERROR)
            return None

    def _get(self, path, params=None, silent_404=False, is_auth=False):
        return self._request('GET', path, params=params, silent_404=silent_404, is_auth=is_auth)

    def _post(self, path, data=None, silent_404=False, params=None):
        return self._request('POST', path, json_data=data, silent_404=silent_404, params=params)

    def _delete(self, path, data=None):
        return self._request('DELETE', path, json_data=data)

    # ------------------------------------------------------------------
    # AUTH (PIN FLOW)
    # ------------------------------------------------------------------
    def auth_get_pin(self):
        return self._get('oauth/pin', is_auth=True)

    def auth_poll_token(self, user_code):
        return self._get(f'oauth/pin/{user_code}', is_auth=True)

    def revoke_token(self):
        self._clear_token()

    def get_user_info(self):
        """Profil + setari cont (POST users/settings — GET users/me intoarce null pe conturi noi).
        Normalizeaza raspunsul: {username, name, join_date, vip}."""
        try:
            data = self._post('users/settings')
            if isinstance(data, dict):
                user = data.get('user') or {}
                account = data.get('account') or {}
                return {
                    'username': user.get('name', ''),
                    'name': user.get('name', ''),
                    'join_date': user.get('joined_at', ''),
                    'vip': account.get('type', ''),
                    'timezone': account.get('timezone', ''),
                    'avatar': user.get('avatar', ''),
                }
        except Exception as e:
            xbmc.log(f'[SIMKL] get_user_info error: {e}', xbmc.LOGERROR)
        return None

    # ------------------------------------------------------------------
    # SYNC WATCHED (Phase 1: fara date_from; Phase 2: all-items cu date_from)
    # NOTA: /sync/shows, /sync/movies, /sync/anime sunt RETRASE (200 null) —
    # totul vine din GET /sync/all-items.
    # ------------------------------------------------------------------
    def get_all_items(self, date_from):
        # extended=full e obligatoriu: fara el, serialele nu au seasons in
        # raspuns si episoadele watched nu pot fi enumerate (Lioness 0 eps).
        return self._get('sync/all-items/', params={'date_from': date_from, 'extended': 'full'})

    def get_activities(self):
        return self._get('sync/activities')

    # ------------------------------------------------------------------
    # WATCHED MUTATIONS
    # ------------------------------------------------------------------
    def _show_ids_body(self, media_type, tmdb_id):
        ids = {'tmdb': int(tmdb_id)}
        key = 'movies' if media_type == 'movie' else 'shows'
        return key, {'ids': ids}

    def mark_watched(self, media_type, tmdb_id, season=None, episode=None, watched_at=None):
        if watched_at is None:
            watched_at = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z')
        if media_type == 'movie':
            data = {'movies': [{'ids': {'tmdb': int(tmdb_id)}, 'watched_at': watched_at}]}
        elif season is not None and episode is not None:
            data = {'shows': [{'ids': {'tmdb': int(tmdb_id)},
                               'seasons': [{'number': int(season),
                                            'episodes': [{'number': int(episode), 'watched_at': watched_at}]}]}]}
        elif season is not None:
            data = {'shows': [{'ids': {'tmdb': int(tmdb_id)},
                               'seasons': [{'number': int(season), 'watched_at': watched_at}]}]}
        else:
            data = {'shows': [{'ids': {'tmdb': int(tmdb_id)}, 'watched_at': watched_at}]}
        return self._post('sync/history', data=data)

    def mark_unwatched(self, media_type, tmdb_id, season=None, episode=None):
        if media_type == 'movie':
            data = {'movies': [{'ids': {'tmdb': int(tmdb_id)}}]}
        elif season is not None and episode is not None:
            data = {'shows': [{'ids': {'tmdb': int(tmdb_id)},
                               'seasons': [{'number': int(season),
                                            'episodes': [{'number': int(episode)}]}]}]}
        elif season is not None:
            data = {'shows': [{'ids': {'tmdb': int(tmdb_id)},
                               'seasons': [{'number': int(season)}]}]}
        else:
            data = {'shows': [{'ids': {'tmdb': int(tmdb_id)}}]}
        return self._post('sync/history/remove', data=data)

    # ------------------------------------------------------------------
    # SYNC RATINGS
    # ------------------------------------------------------------------
    def get_sync_ratings(self, extended='full'):
        return self._get('sync/ratings', params={'extended': extended})

    def rate_item(self, media_type, tmdb_id, rating, season=None, episode=None, rated_at=None):
        if rated_at is None:
            rated_at = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z')
        rating = min(max(int(rating), 1), 10)
        if media_type == 'movie':
            data = {'movies': [{'ids': {'tmdb': int(tmdb_id)}, 'rating': rating, 'rated_at': rated_at}]}
        else:
            # Simkl NU suporta rating de episod/sezon (RatingItem are doar
            # rating/rated_at/ids; nested seasons -> not_found, flat episodes ->
            # ignorat silențios — verificat live + schema OpenAPI). Ratingul pe
            # episod/sezon se aplica SHOW-ului parinte.
            # type='tv' obligatoriu la tmdb pt TV (docs: "tmdb — for TV, specify
            # type") — fara el, id-urile cu coliziune movie/show (ex. 97546 =
            # film german pe Simkl) nu se rezolva ca show.
            data = {'shows': [{'ids': {'tmdb': int(tmdb_id), 'type': 'tv'},
                               'rating': rating, 'rated_at': rated_at}]}
        return self._post('sync/ratings', data=data)

    def remove_rating(self, media_type, tmdb_id, season=None, episode=None):
        if media_type == 'movie':
            data = {'movies': [{'ids': {'tmdb': int(tmdb_id)}}]}
        else:
            # Remove-ul de episod/sezon scoate ratingul show-ului (Simkl nu are
            # rating per episod). type='tv' — paritate cu rate_item.
            data = {'shows': [{'ids': {'tmdb': int(tmdb_id), 'type': 'tv'}}]}
        return self._post('sync/ratings/remove', data=data)

    def add_ratings_bulk(self, movies, shows, episodes):
        """Bulk add ratings (import). Idempotent — re-push nu face dubluri.

        movies:   list[(tmdb_id, rating, rated_at)]
        shows:    list[(tmdb_id, rating, rated_at)]
        episodes: list[(tmdb_id, season, episode, rating, rated_at)] — NU se trimit:
        Simkl nu suporta rating de episod (cheia flat episodes e ignorata silentios,
        nested seasons[].episodes[] -> not_found — verificat live + schema OpenAPI).
        Episoadele raman doar in mirror-ul local (dedupe la re-import).
        """
        data = {}
        if movies:
            data['movies'] = [{'ids': {'tmdb': int(t)}, 'rating': int(r), 'rated_at': d}
                              for t, r, d in movies]
        if shows:
            data['shows'] = [{'ids': {'tmdb': int(t), 'type': 'tv'}, 'rating': int(r), 'rated_at': d}
                             for t, r, d in shows]
        if not data:
            return None
        return self._post('sync/ratings', data=data)

    # ------------------------------------------------------------------
    # WATCHLIST (5 statusuri: plantowatch, watching, hold, dropped, completed)
    # ------------------------------------------------------------------
    def get_watchlist(self, status=None, extended='full'):
        params = {'extended': extended}
        data = self._get('sync/all-items', params=params)
        if not isinstance(data, dict):
            return data
        if not status:
            return data
        out = {}
        for key in ('movies', 'shows', 'anime'):
            items = [it for it in (data.get(key) or [])
                     if isinstance(it, dict) and it.get('status') == status]
            if items:
                out[key] = items
        return out

    def watchlist_add(self, media_type, tmdb_id, status='watching'):
        if media_type in ('show', 'tv', 'episode'):
            data = {'shows': [{'to': status, 'ids': {'tmdb': int(tmdb_id)}}]}
        else:
            data = {'movies': [{'to': status, 'ids': {'tmdb': int(tmdb_id)}}]}
        return self._post('sync/add-to-list', data=data)

    def watchlist_remove(self, media_type, tmdb_id, status='watching'):
        # /sync/remove-from-list e MORT la Simkl (200 null, nu scoate nimic —
        # verificat live). Endpoint-ul corect pt "Remove from List" e
        # /sync/history/remove fara seasons: scoate itemul din library complet
        # (watchlist + history), identic cu butonul de pe site.
        if media_type in ('show', 'tv', 'episode'):
            data = {'shows': [{'ids': {'tmdb': int(tmdb_id)}}]}
        else:
            data = {'movies': [{'ids': {'tmdb': int(tmdb_id)}}]}
        return self._post('sync/history/remove', data=data)

    def watchlist_add_bulk(self, movie_ids, show_ids, status='plantowatch'):
        """Bulk add-to-list (import): movie_ids/show_ids = liste de int tmdb_id."""
        data = {}
        if movie_ids:
            data['movies'] = [{'to': status, 'ids': {'tmdb': int(t)}} for t in movie_ids]
        if show_ids:
            data['shows'] = [{'to': status, 'ids': {'tmdb': int(t)}} for t in show_ids]
        if not data:
            return None
        return self._post('sync/add-to-list', data=data)

    def add_history_bulk(self, movies, episodes):
        """Bulk add to watched history (import).

        movies:   list[(tmdb_id, watched_at)]
        episodes: list[(tmdb_id, season, episode, watched_at)] — grupare pe serial/sezon
        """
        from collections import OrderedDict
        data = {}
        if movies:
            data['movies'] = [{'ids': {'tmdb': int(t)}, 'watched_at': d} for t, d in movies]
        if episodes:
            shows = OrderedDict()
            for t, s, e, d in episodes:
                shows.setdefault(str(t), OrderedDict()).setdefault(s, []).append((e, d))
            shows_list = []
            for t, seasons in shows.items():
                seasons_list = []
                for s_num, eps in seasons.items():
                    seasons_list.append({'number': s_num,
                                         'episodes': [{'number': e, 'watched_at': d} for e, d in eps]})
                shows_list.append({'ids': {'tmdb': int(t)}, 'seasons': seasons_list})
            data['shows'] = shows_list
        if not data:
            return None
        return self._post('sync/history', data=data)

    # ------------------------------------------------------------------
    # PLAYBACK / SCROBBLE
    # ------------------------------------------------------------------
    def get_playback(self):
        return self._get('sync/playback')

    def playback_remove(self, media_type, tmdb_id, season=None, episode=None):
        """Sterge playback-ul (resume) pentru un item.

        Formatul real (verificat live 2026-08-19): DELETE /sync/playback/{id}
        cu id-ul luat din GET /sync/playback — endpoint-ul vechi
        POST /sync/playback/remove nu mai exista (404 url_failed pe orice
        payload). Se potrivește sesiunea dupa show/movie ids.tmdb +
        season/episode din raspuns."""
        try:
            playbacks = self._get('sync/playback')
            if not isinstance(playbacks, list) or not playbacks:
                return None
            tid = str(tmdb_id)
            for p in playbacks:
                if not isinstance(p, dict):
                    continue
                ids = (p.get('show') or p.get('movie') or {}).get('ids') or {}
                if str(ids.get('tmdb', '') or '') != tid:
                    continue
                if media_type == 'movie':
                    return self._delete(f'sync/playback/{p.get("id")}')
                ep = p.get('episode') or {}
                if season is not None and episode is not None:
                    if ep.get('season') == int(season) and ep.get('number') == int(episode):
                        return self._delete(f'sync/playback/{p.get("id")}')
                else:
                    return self._delete(f'sync/playback/{p.get("id")}')
            return None
        except Exception as e:
            xbmc.log(f'[SIMKL] playback_remove error: {e}', xbmc.LOGERROR)
            return None

    def scrobble_start(self, media_type, tmdb_id, progress=0, season=None, episode=None):
        return self._post('scrobble/start', data=self._scrobble_body(media_type, tmdb_id, progress, season, episode))

    def scrobble_pause(self, media_type, tmdb_id, progress, season=None, episode=None):
        return self._post('scrobble/pause', data=self._scrobble_body(media_type, tmdb_id, progress, season, episode))

    def scrobble_stop(self, media_type, tmdb_id, progress, season=None, episode=None):
        return self._post('scrobble/stop', data=self._scrobble_body(media_type, tmdb_id, progress, season, episode))

    def _scrobble_body(self, media_type, tmdb_id, progress, season=None, episode=None):
        try:
            p = min(max(float(progress), 0.0), 100.0)
        except:
            p = 0.0
        body = {'progress': round(p, 2)}
        if media_type == 'movie':
            body['movie'] = {'ids': {'tmdb': int(tmdb_id)}}
        else:
            # FORMATUL REAL al API-ului (verificat live 2026-08-19): episodul
            # se trimite ca seasons[].episodes[] (ca la sync/history), NU ca
            # show.season nested — show.season -> 404 id_err, top-level season
            # -> 201 dar rezolva greșit (S1E4 pentru Reacher S4E4).
            body['show'] = {'ids': {'tmdb': int(tmdb_id)}}
            if season is not None and episode is not None:
                body['show']['seasons'] = [{'number': int(season),
                                            'episodes': [{'number': int(episode)}]}]
        return body

    # ------------------------------------------------------------------
    # CALENDAR (CDN public, fara auth)
    # ------------------------------------------------------------------
    def calendar_events(self):
        """Calendar CDN v2 (tv + anime), combinat intr-un singur payload
        {"calendar": [...], "metadata": {...}} (metadata keyed by str(simkl_id))."""
        merged = {'calendar': [], 'metadata': {}}
        for feed in ('tv', 'anime'):
            try:
                r = self.session.get(f'https://data.simkl.in/calendar/v2/{feed}.json',
                                     headers={'User-Agent': f'{APP_NAME}/{APP_VERSION}'},
                                     timeout=20)
                if r.status_code != 200:
                    continue
                d = r.json()
                if not isinstance(d, dict):
                    continue
                cal = d.get('calendar')
                meta = d.get('metadata')
                if isinstance(cal, list):
                    merged['calendar'].extend(cal)
                if isinstance(meta, dict):
                    merged['metadata'].update(meta)
            except Exception as e:
                xbmc.log(f'[SIMKL] calendar feed {feed} error: {e}', xbmc.LOGERROR)
        return merged if merged['calendar'] else None


# ------------------------------------------------------------------
# AUTH UI FLOW (PIN + QR deep-link)
# ------------------------------------------------------------------
def simkl_auth():
    client_id = SIMKL_CLIENT_ID
    if not client_id:
        xbmcgui.Dialog().ok(
            '[B][COLOR mediumpurple]Simkl[/COLOR][/B]',
            'No Simkl Client ID configured.',
            'Go to [B]simkl.com/settings/developer/[/B] and register an app.',
            'Then set [B]SIMKL_CLIENT_ID[/B] in [B]config.py[/B].'
        )
        return

    api = SIMKLAPI()
    pin_data = api.auth_get_pin()
    if not pin_data or pin_data.get('result') != 'OK':
        xbmcgui.Dialog().notification('[B][COLOR mediumpurple]Simkl[/COLOR][/B]',
                                       'Failed to get PIN. Check log.',
                                       SIMKL_ICON, 5000, False)
        return

    user_code = pin_data.get('user_code', '')
    verification_url = pin_data.get('verification_url', 'https://simkl.com/pin')
    device_code = pin_data.get('device_code', '')
    interval = max(int(pin_data.get('interval', 5) or 5), 3)
    expires_in = int(pin_data.get('expires_in', 900) or 900)

    # QR deep-link: pre-completeaza codul in pagina de PIN
    try:
        from urllib.parse import quote
        auth_url = f"{verification_url.rstrip('/')}/{quote(user_code)}"
    except:
        auth_url = verification_url

    from resources.lib.utils import make_qr
    from resources.lib.auth_dialog import QRProgressDialog, run_modal_main_thread
    qr_path = make_qr(auth_url, 'simkl_qr.png')
    msg = (f"1. Open this link in browser:\n"
           f"[B][COLOR mediumpurple]{verification_url}[/COLOR][/B]\n"
           f"2. Enter code: [B][COLOR yellow]{user_code}[/COLOR][/B]")
    dialog = QRProgressDialog(
        'auth_qr.xml', ADDON_PATH, 'Default', '1080i',
        heading='[B][COLOR mediumpurple]Simkl Authentication[/COLOR][/B]',
        qr_image=qr_path or '',
        icon=SIMKL_ICON,
        addon_icon=os.path.join(ADDON_PATH, 'icon.png'),
        content=msg,
    )

    _result = {}
    _mon = xbmc.Monitor()

    def _poll():
        start_time = time.time()
        while not dialog.iscanceled() and not _mon.abortRequested():
            elapsed = time.time() - start_time
            if elapsed > expires_in:
                dialog.expired = True
                dialog.close()
                return
            percent = max(0, int(100 - (elapsed / expires_in * 100)))
            dialog.update(percent, msg)
            time.sleep(interval)

            result = api.auth_poll_token(user_code)
            if result is None:
                continue
            if result.get('result') == 'OK' and result.get('access_token'):
                _result['token'] = result.get('access_token')
                dialog.close()
                return
            if result.get('error') == 'expired':
                _result['denied'] = 'expired'
                dialog.close()
                return

    import threading
    threading.Thread(target=_poll, daemon=True).start()
    run_modal_main_thread(dialog)
    dialog.close()

    token = _result.get('token')
    if token:
        api._save_token(token)
        username = ''
        try:
            info = api.get_user_info()
            if info:
                username = info.get('username', info.get('name', ''))
                api.set_username(username)
        except:
            pass
        status = f'Connected: {username}' if username else 'Connected'
        ADDON.setSetting('simkl_status', status)
        xbmcgui.Dialog().notification('[B][COLOR mediumpurple]Simkl[/COLOR][/B]',
                                       f'Connected as [B][COLOR red]{username}[/COLOR][/B]' if username else 'Connected!',
                                       SIMKL_ICON, 4000, False)
        threading.Thread(target=_sync_full_library_background, daemon=True).start()
        xbmc.executebuiltin('Container.Refresh')
        return

    if _result.get('denied'):
        xbmcgui.Dialog().notification('[B][COLOR mediumpurple]Simkl[/COLOR][/B]',
                                       'Authorization expired. Try again.',
                                       SIMKL_ICON, 4000, False)
        return

    if dialog.expired:
        xbmcgui.Dialog().notification('[B][COLOR mediumpurple]Simkl[/COLOR][/B]',
                                       'Authorization expired. Try again.',
                                       SIMKL_ICON, 4000, False)


def _sync_full_library_background():
    from resources.lib.simkl_sync import sync_full_library
    sync_full_library(silent=True, force=True)


def simkl_revoke():
    from resources.lib import simkl_sync
    api = SIMKLAPI()
    if api.is_authenticated():
        api.revoke_token()
    ADDON.setSetting('simkl_status', '')
    try:
        simkl_sync.clear_all_local_data()
    except:
        pass
    from resources.lib.watched_provider import _invalidate_fast_cache
    _invalidate_fast_cache()
    xbmcgui.Dialog().notification('[B][COLOR mediumpurple]Simkl[/COLOR][/B]',
                                   'Disconnected.',
                                   SIMKL_ICON, 3000, False)
    xbmc.executebuiltin('Container.Refresh')


def prompt_simkl_rating(tmdb_id, content_type, season, episode, title):
    """Deschide TraktRating.xml cu service='simkl' pentru rating pe Simkl."""
    from resources.lib.trakt_api import _prompt_trakt_rating
    _prompt_trakt_rating(tmdb_id, content_type, season, episode, title, service='simkl')
