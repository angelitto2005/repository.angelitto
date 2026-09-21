# -*- coding: utf-8 -*-
import os
import json
import time
import threading
import datetime
import uuid
import xbmc
import xbmcgui
import requests

from resources.lib import config as _pp_config
from resources.lib.config import PUNCHPLAY_API_URL, PUNCHPLAY_CLIENT_ID, PUNCHPLAY_COLOR, ADDON, ADDON_PATH, provider_title, provider_icon

PUNCHPLAY_ICON = provider_icon('punchplay')

APP_VERSION = '1.0'

FULL_SCOPES = ('profile:read profile:write playback:read playback:write events:read '
               'history:read history:write lists:read lists:write ratings:read ratings:write '
               'collection:read collection:write notifications:read notifications:write trophies:read')

_LOCK = threading.Lock()
_REFRESH_LOCK = threading.Lock()
_LAST_REFRESH_FAIL = 0.0
_LAST_REQ = 0.0
_BULK_LOCK = threading.Lock()
_LAST_BULK = 0.0
_BULK_MIN_INTERVAL = 2.2

def _throttle():
    global _LAST_REQ
    with _LOCK:
        delta = time.time() - _LAST_REQ
        if delta < 0.05:
            time.sleep(0.05 - delta)
        _LAST_REQ = time.time()

def _throttle_bulk():
    global _LAST_BULK
    with _BULK_LOCK:
        delta = time.time() - _LAST_BULK
        if delta < _BULK_MIN_INTERVAL:
            time.sleep(_BULK_MIN_INTERVAL - delta)
        _LAST_BULK = time.time()

_SESSION = None

_PP_WORKER_QUEUE = []
_PP_WORKER_LOCK = threading.Lock()
_PP_WORKER_STARTED = False
_PP_WORKER_THREAD = None
_PP_WORKER_STOP = threading.Event()
try:
    _pp_config.register_shutdown_event(_PP_WORKER_STOP)
except Exception:
    pass
_PP_WORKER_MIN_GAP = 2.0
_PP_WORKER_LAST = 0.0
# Repaus maxim cu coada goala: thread-ul se termina SINGUR dupa atit timp.
# Motiv: CPythonInvoker (Kodi) asteapta la shutdown TOATE firele Python ale
# invocarii curente ("waiting on thread ..."), indiferent daca sint daemon.
# Un worker permanent tine invokerul viu toata sesiunea -> la inchidere Kodi
# asteapta 5s, il ucide ("script didn't stop in 5 seconds") si procesul
# ramine agatat (Kodi nu mai porneste pina nu e omorit din Task Manager).
_PP_WORKER_IDLE_EXIT = 2.5
_PP_WORKER_GEN = 0
_PP_SESSIONS = {}
_PP_SESSIONS_LOCK = threading.Lock()

def _pp_session_key(tmdb_id, season, episode):
    try:
        s = int(season or 0)
    except:
        s = 0
    try:
        e = int(episode or 0)
    except:
        e = 0
    return (str(tmdb_id), s, e)

def _pp_worker_stopped(gen):
    global _PP_WORKER_STARTED
    try:
        with _PP_WORKER_LOCK:
            # Doar workerul curent are voie sa dea flagul jos: daca intre timp
            # un _pp_enqueue a pornit deja un worker nou (generatie mai mare),
            # flagul ramine sus si nu apar doi workeri simultan.
            if _PP_WORKER_GEN == gen:
                _PP_WORKER_STARTED = False
    except Exception:
        pass

def _pp_worker_loop(gen):
    global _PP_WORKER_LAST
    idle_since = None
    # Nu folosim bare except in bucla: SystemExit trimis de Kodi la shutdown
    # trebuie sa poata iesi din functie (bare except ar inghiti-o si threadul
    # ar deveni nemuritor).
    try:
        while not _PP_WORKER_STOP.is_set():
            job = None
            expired = False
            with _PP_WORKER_LOCK:
                if _PP_WORKER_QUEUE:
                    job = _PP_WORKER_QUEUE.pop(0)
                    idle_since = None
                else:
                    if idle_since is None:
                        idle_since = time.time()
                    elif (time.time() - idle_since) >= _PP_WORKER_IDLE_EXIT:
                        # Coada goala suficient: iesim. Flagul e dat jos SUB
                        # lock, ca un enqueue simultan sa porneasca worker nou
                        # (si sa nu piarda jobul).
                        _PP_WORKER_STARTED = False
                        expired = True
            if expired:
                return
            if job is None:
                if _pp_config.kodi_abort_requested():
                    break
                try:
                    _PP_WORKER_STOP.wait(0.2)
                except Exception:
                    time.sleep(0.2)
                continue
            if _PP_WORKER_STOP.is_set() or _pp_config.kodi_abort_requested():
                break
            try:
                wait = _PP_WORKER_MIN_GAP - (time.time() - _PP_WORKER_LAST)
            except Exception:
                wait = 0
            if wait > 0:
                try:
                    _PP_WORKER_STOP.wait(wait)
                except Exception:
                    time.sleep(wait)
                if _PP_WORKER_STOP.is_set() or _pp_config.kodi_abort_requested():
                    break
            try:
                job[1]()
            except Exception:
                pass
            try:
                _PP_WORKER_LAST = time.time()
            except Exception:
                pass
    finally:
        _pp_worker_stopped(gen)

def _pp_ensure_worker():
    global _PP_WORKER_STARTED, _PP_WORKER_THREAD, _PP_WORKER_GEN
    with _PP_WORKER_LOCK:
        if _PP_WORKER_STARTED:
            return
        _PP_WORKER_STARTED = True
        _PP_WORKER_GEN += 1
        gen = _PP_WORKER_GEN
    try:
        # daemon=True: la shutdown, Kodi nu mai asteapta threadurile daemon
        # pentru stop-ul invokerului. Workerul iese oricum singur (coada goala
        # / abort Kodi), deci nu ramine viu peste inchidere.
        t = threading.Thread(target=_pp_worker_loop, args=(gen,), daemon=True, name='punchplay-scrobble')
        t.start()
        _PP_WORKER_THREAD = t
    except Exception:
        _pp_worker_stopped(gen)

def _pp_enqueue(label, fn, coalesce_key=None):
    _pp_ensure_worker()
    try:
        with _PP_WORKER_LOCK:
            if coalesce_key is not None and label == 'progress':
                _PP_WORKER_QUEUE[:] = [j for j in _PP_WORKER_QUEUE if j[0] != coalesce_key]
            _PP_WORKER_QUEUE.append((coalesce_key or label, fn))
            # Daca workerul tocmai a expirat cu coada goala, il repornim ca
            # jobul asta sa nu rămîna in coada.
            needs_worker = not _PP_WORKER_STARTED
    except Exception:
        try:
            fn()
        except Exception:
            pass
        return
    if needs_worker:
        _pp_ensure_worker()

def _get_session():
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
    return _SESSION


def _now_utc_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')


class PunchplayAPI:
    def __init__(self):
        self.base_url = PUNCHPLAY_API_URL.rstrip('/')
        self.client_id = PUNCHPLAY_CLIENT_ID
        self.session = _get_session()

    def _get_token(self):
        return (ADDON.getSetting('punchplay_access_token') or '').strip()

    def _get_refresh_token(self):
        return (ADDON.getSetting('punchplay_refresh_token') or '').strip()

    def _get_expiry(self):
        try:
            return float(ADDON.getSetting('punchplay_token_expiry') or '0')
        except:
            return 0.0

    def _save_tokens(self, access_token, refresh_token='', expires_in=3600):
        ADDON.setSetting('punchplay_access_token', access_token or '')
        if refresh_token:
            ADDON.setSetting('punchplay_refresh_token', refresh_token)
        try:
            ADDON.setSetting('punchplay_token_expiry', str(time.time() + int(expires_in or 3600)))
        except:
            pass

    def _clear_token(self):
        ADDON.setSetting('punchplay_access_token', '')
        ADDON.setSetting('punchplay_refresh_token', '')
        ADDON.setSetting('punchplay_token_expiry', '')
        ADDON.setSetting('punchplay_username', '')

    def set_username(self, username):
        ADDON.setSetting('punchplay_username', username or '')

    def is_authenticated(self):
        return bool(self._get_token())

    def _refresh(self, stale_access_token=None):
        global _LAST_REFRESH_FAIL
        with _REFRESH_LOCK:
            try:
                if stale_access_token is not None and self._get_token() != stale_access_token:
                    return bool(self._get_token())
            except:
                pass
            try:
                if time.time() - _LAST_REFRESH_FAIL < 120:
                    return False
            except:
                pass
            refresh_token = self._get_refresh_token()
            if not refresh_token or not self.client_id:
                return False
            try:
                r = None
                for _attempt in range(4):
                    # client_id is REQUIRED: the backend rejects refresh calls
                    # without it with HTTP 401 (public OAuth client flow).
                    r = self.session.post(
                        f'{self.base_url}/auth/refresh',
                        json={'refresh_token': refresh_token, 'client_id': self.client_id},
                        headers={'User-Agent': f'TMDbMovies/{APP_VERSION} (Kodi addon)', 'Accept': 'application/json'},
                        timeout=15)
                    if r.status_code != 429:
                        break
                    try:
                        _retry_after = int(r.headers.get('Retry-After', 5) or 5)
                    except:
                        _retry_after = 5
                    xbmc.log(f'[PUNCHPLAY] refresh throttled (429), waiting {_retry_after}s (attempt {_attempt + 1}/4)', xbmc.LOGINFO)
                    time.sleep(min(max(_retry_after, 1), 60))
                if r is None or r.status_code != 200:
                    try:
                        _eb = r.json() or {}
                    except:
                        _eb = {}
                    _es = json.dumps(_eb).lower() if isinstance(_eb, dict) else str(_eb).lower()
                    if r.status_code in (400, 401) and ('revok' in _es or 'invalid_token' in _es or 'invalid_grant' in _es):
                        self._clear_token()
                        try:
                            ADDON.setSetting('punchplay_status', 'Disconnected')
                        except:
                            pass
                        try:
                            xbmcgui.Dialog().notification(
                                provider_title('punchplay'),
                                'Session expired. Please reconnect.', PUNCHPLAY_ICON, 5000, False)
                        except:
                            pass
                    else:
                        xbmc.log(f'[PUNCHPLAY] refresh failed HTTP {r.status_code}', xbmc.LOGWARNING)
                    try:
                        _LAST_REFRESH_FAIL = time.time()
                    except:
                        pass
                    return False
                data = r.json() or {}
                if not data.get('access_token'):
                    return False
                self._save_tokens(data.get('access_token'), data.get('refresh_token', ''), data.get('expires_in', 3600))
                return True
            except Exception as e:
                xbmc.log(f'[PUNCHPLAY] refresh error: {e}', xbmc.LOGERROR)
                try:
                    _LAST_REFRESH_FAIL = time.time()
                except:
                    pass
                return False

    def _ensure_token(self):
        if not self._get_token():
            return False
        if self._get_expiry() and time.time() > self._get_expiry() - 60:
            return self._refresh()
        return True

    def _request(self, method, path, params=None, json_data=None, idempotency_key=None, silent_404=False, is_auth=False, base_url=None):
        url = f'{(base_url or self.base_url).rstrip("/")}/{path.lstrip("/")}'
        headers = {
            'User-Agent': f'TMDbMovies/{APP_VERSION} (Kodi addon)',
            'Accept': 'application/json',
        }
        if not is_auth:
            if not self._ensure_token():
                return None
            headers['Authorization'] = f'Bearer {self._get_token()}'
        if json_data is not None:
            headers['Content-Type'] = 'application/json'
        if idempotency_key:
            headers['Idempotency-Key'] = idempotency_key
        if _pp_config.kodi_abort_requested():
            # Kodi se inchide: nu mai pornim cereri noi (un request cu retry-uri
            # 429 poate tine thread-ul viu minute intregi si blocheaza
            # shutdown-ul invokerului).
            return None
        _throttle()
        try:
            r = self.session.request(method, url, params=params, json=json_data, headers=headers, timeout=20)
            for _attempt in range(3):
                if r.status_code != 429:
                    break
                try:
                    retry_after = int(r.headers.get('Retry-After', 5) or 5)
                except:
                    retry_after = 5
                xbmc.log(f'[PUNCHPLAY] Rate limited (429), retrying after {retry_after}s (attempt {_attempt + 1}/3)', xbmc.LOGINFO)
                if _pp_config.kodi_abort_requested():
                    return None
                time.sleep(min(max(retry_after, 1), 60))
                _throttle()
                r = self.session.request(method, url, params=params, json=json_data, headers=headers, timeout=20)
            if r.status_code == 429:
                xbmc.log(f'[PUNCHPLAY] HTTP 429 on {method} /{path} after 3 retries: giving up on this batch', xbmc.LOGERROR)
                return None
            if r.status_code == 401 and not is_auth:
                try:
                    _used_token = headers.get('Authorization', '').replace('Bearer ', '')
                except:
                    _used_token = None
                if self._refresh(_used_token):
                    headers['Authorization'] = f'Bearer {self._get_token()}'
                    _throttle()
                    r = self.session.request(method, url, params=params, json=json_data, headers=headers, timeout=20)
                else:
                    xbmc.log('[PUNCHPLAY] HTTP 401 - token invalid/expired', xbmc.LOGWARNING)
                    return None
            if r.status_code == 409 and method == 'POST' and '/playback/stop' in path:
                return {}
            if r.status_code == 400 and 'auth/device/token' in path:
                try:
                    _body = r.json()
                except:
                    _body = {}
                if isinstance(_body, dict) and _body.get('error') == 'authorization_pending':
                    xbmc.log('[PUNCHPLAY] device poll: authorization pending', xbmc.LOGDEBUG)
                    return _body
            r.raise_for_status()
            if r.status_code == 204:
                return {}
            if r.content:
                try:
                    j = r.json()
                except Exception:
                    j = {}
                return {} if j is None else j
            return {}
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else 0
            if silent_404 and code == 404:
                xbmc.log(f'[PUNCHPLAY] HTTP 404 on {method} /{path}', xbmc.LOGDEBUG)
            else:
                body = ''
                try:
                    body = e.response.text[:300]
                except:
                    pass
                xbmc.log(f'[PUNCHPLAY] HTTP {code} on {method} /{path}: {body}', xbmc.LOGERROR)
            return None
        except Exception as e:
            xbmc.log(f'[PUNCHPLAY] {method} /{path} error: {e}', xbmc.LOGERROR)
            return None

    def _get(self, path, params=None, silent_404=False, is_auth=False):
        return self._request('GET', path, params=params, silent_404=silent_404, is_auth=is_auth)

    def _post(self, path, data=None, params=None, idempotency_key=None, silent_404=False):
        return self._request('POST', path, json_data=data, params=params, idempotency_key=idempotency_key, silent_404=silent_404)

    def _patch(self, path, data=None, params=None):
        return self._request('PATCH', path, json_data=data, params=params)

    def _delete(self, path, data=None, params=None, silent_404=False):
        return self._request('DELETE', path, json_data=data, params=params, silent_404=silent_404)

    def device_code(self, scope=None):
        return self._request('POST', 'auth/device/code',
                             json_data={'client_id': self.client_id, 'scope': scope or FULL_SCOPES},
                             is_auth=True)

    def device_token(self, device_code, device_name='Kodi', device_id='tmdbmovies'):
        return self._request('POST', 'auth/device/token',
                             json_data={'client_id': self.client_id, 'device_code': device_code,
                                        'device_name': device_name, 'device_id': device_id},
                             is_auth=True)

    def revoke(self):
        try:
            self._post('oauth/revoke', data={'client_id': self.client_id, 'token': self._get_token()})
        except:
            pass
        self._clear_token()

    def get_me(self):
        return self._get('me')

    def get_user_info(self):
        try:
            data = self.get_me()
            if isinstance(data, dict):
                profile = data.get('profile') or {}
                return {
                    'username': data.get('username') or '',
                    'name': data.get('name') or profile.get('displayName') or '',
                    'join_date': profile.get('memberSince') or '',
                    'stats': profile.get('stats') or {},
                }
        except Exception as e:
            xbmc.log(f'[PUNCHPLAY] get_user_info error: {e}', xbmc.LOGERROR)
        return None

    def get_title(self, media_type, tid):
        kind = 'movie' if str(media_type).lower() == 'movie' else 'show'
        return self._get(f'title/{kind}/{tid}')

    def get_season(self, tmdb_id, season):
        return self._get(f'title/show/{tmdb_id}/season/{season}')

    def get_episode(self, tmdb_id, season, episode):
        return self._get(f'title/show/{tmdb_id}/season/{season}/episode/{episode}')

    def get_history(self, cursor=None, limit=100):
        params = {'limit': limit}
        if cursor:
            params['cursor'] = cursor
        return self._get('me/history', params=params)

    def log_movie(self, tmdb_id, title='', year=0, watched_at=None):
        body = {'title': title or f'tmdb:{tmdb_id}', 'watchedAt': watched_at or _now_utc_iso()}
        if year:
            body['year'] = int(year)
        return self._post(f'title/movie/{tmdb_id}/history', data=body)

    def clear_movie(self, tmdb_id):
        return self._delete(f'title/movie/{tmdb_id}/history')

    def log_episodes(self, tmdb_id, season, episodes, title='', year=0, watched_at=None, allow_rewatches=False):
        body = {'title': title or f'tmdb:{tmdb_id}',
                'watchedAt': watched_at or _now_utc_iso(),
                'episodes': episodes}
        if year:
            body['year'] = int(year)
        if allow_rewatches:
            body['allowRewatches'] = True
        return self._post(f'title/show/{tmdb_id}/season/{season}/watch', data=body)

    def clear_episodes(self, tmdb_id, season):
        return self._delete(f'title/show/{tmdb_id}/season/{season}/watch')

    def delete_history_entry(self, entry_id):
        return self._delete(f'watch-history/{entry_id}')

    def edit_history_entry(self, entry_id, watched_at):
        return self._patch(f'watch-history/{entry_id}', data={'watchedAt': watched_at})

    def get_ratings(self, page=1):
        return self._get('me/ratings', params={'page': page})

    def get_favourites(self, page=1):
        return self._get('me/favourites', params={'page': page})

    def get_watch_status(self, page=1):
        return self._get('me/watch-status', params={'page': page})

    def interact(self, media_type, tmdb_id, scope='title', season=None, episode=None, rating=None,
                 is_favourite=None, want_to_watch=None, show_status=None, watched_at=None):
        kind = 'movie' if str(media_type).lower() == 'movie' else 'show'
        params = {}
        if scope and scope != 'title':
            params['scope'] = scope
        if season is not None:
            params['season'] = int(season)
        if episode is not None:
            params['episode'] = int(episode)
        body = {}
        if rating is not None:
            body['rating'] = min(max(int(rating), 1), 10)
        if is_favourite is not None:
            body['isFavourite'] = bool(is_favourite)
        if want_to_watch is not None:
            body['wantToWatch'] = bool(want_to_watch)
        if show_status is not None:
            body['showStatus'] = show_status
        if watched_at is not None:
            body['watchedAt'] = watched_at
        if not body:
            return None
        return self._patch(f'title/{kind}/{tmdb_id}/interact', data=body, params=params or None)

    def clear_status(self, media_type, tmdb_id, scope='title', season=None, episode=None):
        kind = 'movie' if str(media_type).lower() == 'movie' else 'show'
        params = {}
        if scope and scope != 'title':
            params['scope'] = scope
        if season is not None:
            params['season'] = int(season)
        if episode is not None:
            params['episode'] = int(episode)
        return self._patch(f'title/{kind}/{tmdb_id}/interact', data={'showStatus': None}, params=params or None)

    def rate_item(self, media_type, tmdb_id, rating, season=None, episode=None, rated_at=None):
        mt = str(media_type).lower()
        if mt == 'movie':
            return self.interact('movie', tmdb_id, scope='title', rating=rating)
        if season is not None and episode is not None:
            return self.interact(mt, tmdb_id, scope='episode', season=season, episode=episode, rating=rating)
        if season is not None:
            return self.interact(mt, tmdb_id, scope='season', season=season, rating=rating)
        return self.interact(mt, tmdb_id, scope='series', rating=rating)

    def remove_rating(self, media_type, tmdb_id, season=None, episode=None):
        mt = str(media_type).lower()
        if mt == 'movie':
            return self._clear_rating(mt, tmdb_id, None, None, None)
        if season is not None and episode is not None:
            return self._clear_rating(mt, tmdb_id, 'episode', season, episode)
        if season is not None:
            return self._clear_rating(mt, tmdb_id, 'season', season, None)
        return self._clear_rating(mt, tmdb_id, 'series', None, None)

    def _clear_rating(self, media_type, tmdb_id, scope, season, episode):
        kind = 'movie' if str(media_type).lower() == 'movie' else 'show'
        params = {}
        if scope and scope != 'title':
            params['scope'] = scope
        if season is not None:
            params['season'] = int(season)
        if episode is not None:
            params['episode'] = int(episode)
        return self._patch(f'title/{kind}/{tmdb_id}/interact', data={'rating': None}, params=params or None)

    def get_lists(self, cursor=None, limit=100):
        params = {'limit': limit}
        if cursor:
            params['cursor'] = cursor
        return self._get('me/lists', params=params)

    def get_list(self, list_id):
        return self._get(f'lists/{list_id}')

    def get_list_items(self, list_id, offset=0, limit=200):
        return self._get(f'lists/{list_id}/items', params={'offset': offset, 'limit': limit})

    def create_list(self, name, description='', is_public=False):
        return self._post('lists', data={'name': name[:100], 'description': (description or '')[:500], 'isPublic': bool(is_public)})

    def update_list(self, list_id, name=None, description=None, is_public=None):
        body = {}
        if name is not None:
            body['name'] = name[:100]
        if description is not None:
            body['description'] = (description or '')[:500]
        if is_public is not None:
            body['isPublic'] = bool(is_public)
        if not body:
            return None
        return self._patch(f'lists/{list_id}', data=body)

    def delete_list(self, list_id):
        return self._delete(f'lists/{list_id}')

    def add_list_item(self, list_id, kind, tmdb_id, title=''):
        body = {'kind': kind, 'sourceId': int(tmdb_id), 'title': title or f'tmdb:{tmdb_id}'}
        return self._post(f'lists/{list_id}/items', data=body)

    def remove_list_item(self, list_id, item_id):
        return self._delete(f'lists/{list_id}/items/{item_id}')

    def get_watchlist_id(self):
        try:
            cursor = None
            while True:
                data = self.get_lists(cursor=cursor, limit=100)
                if not isinstance(data, dict):
                    return None
                for lst in data.get('items') or []:
                    if isinstance(lst, dict) and lst.get('isWatchlist'):
                        return lst.get('id')
                cursor = data.get('nextCursor')
                if not cursor:
                    return None
        except Exception:
            return None

    def get_collection(self, cursor=None, limit=200, item_type=None):
        params = {'limit': limit}
        if cursor:
            params['cursor'] = cursor
        if item_type in ('movie', 'show', 'anime'):
            params['type'] = item_type
        return self._get('me/collection', params=params)

    def add_collection(self, kind, tmdb_id, title='', year=0, fmt='digital'):
        body = {'kind': kind, 'sourceId': int(tmdb_id), 'title': title or f'tmdb:{tmdb_id}', 'format': fmt or 'digital'}
        if year:
            body['year'] = int(year)
        return self._post('collection', data=body)

    def remove_collection(self, item_id):
        return self._delete(f'collection/{item_id}')

    def continue_watching(self):
        return self._get('me/continue-watching')

    def continue_watching_detail(self, show_id):
        return self._get(f'me/continue-watching/{show_id}')

    def get_in_progress(self):
        return self._get('playback/in-progress')

    def get_now_playing(self):
        return self._get('playback/now-playing')

    def dismiss_progress(self, progress_id):
        return self._delete(f'playback/in-progress/{progress_id}')

    def playback(self, action, media_type, tmdb_id, title='', year=0, season=None, episode=None,
                 episode_title='', progress=0.0, duration_seconds=0, position_seconds=0,
                 watched=None, watched_threshold=None, session_id='', event_id=''):
        body = {
            'event_id': event_id or f'tmdbmovies-{uuid.uuid4().hex[:12]}',
            'event_created_at': int(time.time() * 1000),
            'media_type': 'movie' if str(media_type).lower() == 'movie' else 'episode',
            'title': title or f'tmdb:{tmdb_id}',
            'tmdb_id': int(tmdb_id),
            'playback_session_id': session_id or f'tmdbmovies-{tmdb_id}',
        }
        if year:
            body['year'] = int(year)
        if season is not None:
            body['season'] = int(season)
        if episode is not None:
            body['episode'] = int(episode)
        if episode_title:
            body['episode_title'] = episode_title
        try:
            body['progress'] = min(max(float(progress), 0.0), 1.0)
        except:
            body['progress'] = 0.0
        if duration_seconds:
            body['duration_seconds'] = int(duration_seconds)
        if position_seconds or action in ('pause', 'progress', 'stop'):
            body['position_seconds'] = int(position_seconds or 0)
        if watched is not None:
            body['watched'] = bool(watched)
        if watched_threshold:
            body['watched_threshold'] = float(watched_threshold)
        return self._post(f'playback/{action}', data=body)

    def scrobble_start(self, media_type, tmdb_id, progress=0, season=None, episode=None, title=''):
        # The session_id sent at start MUST match the one sent by
        # pause/resume/progress/stop, otherwise the server rejects
        # those events with 409 playback_state_conflict.
        _sess = ''
        try:
            with _PP_SESSIONS_LOCK:
                _key = _pp_session_key(tmdb_id, season, episode)
                _sess = _PP_SESSIONS.get(_key, '')
                if not _sess:
                    _sess = uuid.uuid4().hex[:16]
                    _PP_SESSIONS[_key] = _sess
        except:
            pass
        return self.playback('start', media_type, tmdb_id, title=title, season=season, episode=episode,
                             progress=(progress or 0) / 100.0, session_id=_sess)

    def scrobble_pause(self, media_type, tmdb_id, progress, season=None, episode=None, title='',
                       duration_seconds=0, position_seconds=0):
        try:
            with _PP_SESSIONS_LOCK:
                _sess = _PP_SESSIONS.get(_pp_session_key(tmdb_id, season, episode), '')
        except:
            _sess = ''
        return self.playback('pause', media_type, tmdb_id, title=title, season=season, episode=episode,
                             progress=(progress or 0) / 100.0, duration_seconds=duration_seconds,
                             position_seconds=position_seconds, session_id=_sess)

    def scrobble_resume(self, media_type, tmdb_id, progress, season=None, episode=None, title='',
                        duration_seconds=0, position_seconds=0):
        try:
            with _PP_SESSIONS_LOCK:
                _sess = _PP_SESSIONS.get(_pp_session_key(tmdb_id, season, episode), '')
        except:
            _sess = ''
        return self.playback('resume', media_type, tmdb_id, title=title, season=season, episode=episode,
                             progress=(progress or 0) / 100.0, duration_seconds=duration_seconds,
                             position_seconds=position_seconds, session_id=_sess)

    def scrobble_progress(self, media_type, tmdb_id, progress, season=None, episode=None, title='',
                          duration_seconds=0, position_seconds=0):
        try:
            with _PP_SESSIONS_LOCK:
                _sess = _PP_SESSIONS.get(_pp_session_key(tmdb_id, season, episode), '')
        except:
            _sess = ''
        return self.playback('progress', media_type, tmdb_id, title=title, season=season, episode=episode,
                             progress=(progress or 0) / 100.0, duration_seconds=duration_seconds,
                             position_seconds=position_seconds, session_id=_sess)

    def scrobble_stop(self, media_type, tmdb_id, progress, season=None, episode=None, title='',
                      duration_seconds=0, position_seconds=0, watched=None, watched_threshold=None):
        try:
            key = _pp_session_key(tmdb_id, season, episode)
            with _PP_SESSIONS_LOCK:
                session_id = _PP_SESSIONS.pop(key, '')
        except:
            session_id = ''
        return self.playback('stop', media_type, tmdb_id, title=title, season=season, episode=episode,
                             progress=(progress or 0) / 100.0, duration_seconds=duration_seconds,
                             position_seconds=position_seconds, watched=watched,
                             watched_threshold=watched_threshold, session_id=session_id)

    def playback_remove(self, media_type, tmdb_id, season=None, episode=None):
        try:
            items = self.get_in_progress()
            if not isinstance(items, list) or not items:
                return None
            tid = int(tmdb_id)
            for p in items:
                if not isinstance(p, dict):
                    continue
                try:
                    if int(p.get('tmdbId') or p.get('showTmdbId') or 0) != tid and int(p.get('showTmdbId') or 0) != tid:
                        if str(media_type).lower() == 'movie' and int(p.get('tmdbId') or 0) != tid:
                            continue
                        if str(media_type).lower() != 'movie' and int(p.get('showTmdbId') or 0) != tid:
                            continue
                except:
                    continue
                if str(media_type).lower() != 'movie' and season is not None and episode is not None:
                    try:
                        if int(p.get('season') or -1) != int(season) or int(p.get('episode') or -1) != int(episode):
                            continue
                    except:
                        continue
                return self.dismiss_progress(p.get('id'))
            return None
        except Exception as e:
            xbmc.log(f'[PUNCHPLAY] playback_remove error: {e}', xbmc.LOGERROR)
            return None

    def get_calendar(self, month):
        return self._get('calendar', params={'month': month})

    _PUBLIC_BASE = 'https://punchplay.tv/api/public/v1'
    _CATALOG_TYPES = ('movie', 'show', 'anime')
    _DISCOVER_CATEGORIES = ('popular', 'now_playing', 'upcoming', 'top_rated')

    def _get_public(self, path, params=None):
        return self._request('GET', path, params=params, is_auth=True, base_url=self._PUBLIC_BASE)

    def catalog_trending(self, kind='movie'):
        kind = str(kind or 'movie').lower()
        if kind not in self._CATALOG_TYPES:
            kind = 'movie'
        try:
            data = self._get_public('catalog/trending', params={'type': kind}) or {}
            items = data.get('items') or []
            return [it for it in items if isinstance(it, dict)]
        except:
            return []

    def catalog_discover(self, category='popular', kind='movie'):
        category = str(category or 'popular').lower()
        if category not in self._DISCOVER_CATEGORIES:
            category = 'popular'
        kind = str(kind or 'movie').lower()
        if kind not in self._CATALOG_TYPES:
            kind = 'movie'
        try:
            data = self._get_public('catalog/discover', params={'category': category, 'type': kind}) or {}
            items = data.get('items') or []
            return [it for it in items if isinstance(it, dict)]
        except:
            return []

    def sync_changes(self, cursor=None, limit=200):
        params = {'limit': limit}
        if cursor:
            params['cursor'] = cursor
        return self._get('me/sync/changes', params=params)

    def sync_snapshot(self, resource, after=0, limit=500):
        return self._get('me/sync/snapshot', params={'resource': resource, 'after': after, 'limit': limit})

    def bulk_history(self, items, idempotency_key=None):
        _throttle_bulk()
        return self._post('sync/history', data={'items': items},
                          idempotency_key=idempotency_key or f'tmdbmovies-h-{uuid.uuid4().hex}')

    def bulk_ratings(self, items, idempotency_key=None):
        _throttle_bulk()
        return self._post('sync/ratings', data={'items': items},
                          idempotency_key=idempotency_key or f'tmdbmovies-r-{uuid.uuid4().hex}')

    def bulk_watchlist(self, items, idempotency_key=None):
        _throttle_bulk()
        return self._post('sync/watchlist', data={'items': items},
                          idempotency_key=idempotency_key or f'tmdbmovies-w-{uuid.uuid4().hex}')

    def add_history_bulk(self, movies, episodes):
        items = []
        for t, d in movies or []:
            items.append({'client_item_id': f'tmdbmovies-m-{t}-{d}', 'kind': 'movie',
                          'tmdb_id': int(t), 'watched_at': d})
        for t, s, e, d in episodes or []:
            items.append({'client_item_id': f'tmdbmovies-e-{t}-{s}-{e}-{d}', 'kind': 'episode',
                          'tmdb_id': int(t), 'season': int(s), 'episode': int(e), 'watched_at': d})
        if not items:
            return None
        out = {'inserted': 0}
        failed = 0
        for i in range(0, len(items), 100):
            res = self.bulk_history(items[i:i + 100])
            if isinstance(res, dict):
                out['inserted'] += int(res.get('inserted') or 0) + int(res.get('updated') or 0)
            else:
                failed += 1
        if failed and not out['inserted']:
            return None
        return out

    def add_ratings_bulk(self, movies, shows, episodes):
        items = []
        for t, r, d in movies or []:
            items.append({'client_item_id': f'tmdbmovies-rm-{t}', 'kind': 'movie', 'tmdb_id': int(t),
                          'scope': 'title', 'rating': int(r)})
        for t, r, d in shows or []:
            items.append({'client_item_id': f'tmdbmovies-rs-{t}', 'kind': 'show', 'tmdb_id': int(t),
                          'scope': 'series', 'rating': int(r)})
        for t, s, e, r, d in episodes or []:
            try:
                s, e = int(s or 0), int(e or 0)
            except:
                continue
            if e:
                items.append({'client_item_id': f'tmdbmovies-re-{t}-{s}-{e}', 'kind': 'show',
                              'tmdb_id': int(t), 'scope': 'episode', 'season': s, 'episode': e,
                              'rating': int(r)})
            elif s:
                items.append({'client_item_id': f'tmdbmovies-rn-{t}-{s}', 'kind': 'show',
                              'tmdb_id': int(t), 'scope': 'season', 'season': s,
                              'rating': int(r)})
        if not items:
            return None
        out = {'added': 0}
        for i in range(0, len(items), 100):
            res = self.bulk_ratings(items[i:i + 100])
            if isinstance(res, dict):
                out['added'] += int(res.get('inserted') or 0) + int(res.get('updated') or 0)
            else:
                return None
        return out

    def watchlist_add(self, media_type, tmdb_id, title=''):
        kind = 'show' if str(media_type).lower() in ('show', 'tv', 'episode', 'season') else 'movie'
        return self.bulk_watchlist([{'client_item_id': f'tmdbmovies-wa-{kind}-{tmdb_id}',
                                     'kind': kind, 'tmdb_id': int(tmdb_id),
                                     'title': title or f'tmdb:{tmdb_id}'}])

    def watchlist_remove(self, media_type, tmdb_id):
        kind = 'show' if str(media_type).lower() in ('show', 'tv', 'episode', 'season') else 'movie'
        return self.bulk_watchlist([{'client_item_id': f'tmdbmovies-wr-{kind}-{tmdb_id}',
                                     'kind': kind, 'tmdb_id': int(tmdb_id), 'remove': True}])

    def watchlist_add_bulk(self, movie_ids, show_ids, status='plantowatch'):
        items = []
        for t in movie_ids or []:
            items.append({'client_item_id': f'tmdbmovies-wb-m-{t}', 'kind': 'movie', 'tmdb_id': int(t)})
        for t in show_ids or []:
            items.append({'client_item_id': f'tmdbmovies-wb-s-{t}', 'kind': 'show', 'tmdb_id': int(t)})
        if not items:
            return None
        out = {'added': 0}
        for i in range(0, len(items), 100):
            res = self.bulk_watchlist(items[i:i + 100])
            if isinstance(res, dict):
                out['added'] += int(res.get('inserted') or 0) + int(res.get('updated') or 0)
            else:
                return None
        return out

    def mark_watched(self, media_type, tmdb_id, season=None, episode=None, watched_at=None, title='', year=0):
        mt = str(media_type).lower()
        if mt == 'movie':
            return self.log_movie(tmdb_id, title=title, year=year, watched_at=watched_at)
        eps = []
        if season is not None and episode is not None:
            eps = [{'episodeNumber': int(episode)}]
        return self.log_episodes(tmdb_id, int(season or 0), eps, title=title, year=year, watched_at=watched_at)

    def mark_unwatched(self, media_type, tmdb_id, season=None, episode=None):
        mt = str(media_type).lower()
        if mt == 'movie':
            return self.clear_movie(tmdb_id)
        return self.clear_episodes(tmdb_id, int(season or 0))


def punchplay_auth():
    if not PUNCHPLAY_CLIENT_ID:
        xbmcgui.Dialog().ok(
            provider_title('punchplay'),
            'No PunchPlay Client ID configured.',
            'Register an app at [B]punchplay.tv/developers[/B] (public client).',
            'Then paste the Client ID in addon Settings -> Accounts -> PunchPlay.')
        return
    api = PunchplayAPI()
    code_data = api.device_code()
    if not isinstance(code_data, dict) or not code_data.get('device_code'):
        xbmcgui.Dialog().notification(provider_title('punchplay'),
                                      'Failed to get device code. Check log.',
                                      PUNCHPLAY_ICON, 5000, False)
        return
    device_code = code_data.get('device_code', '')
    user_code = code_data.get('user_code', '')
    verification_url = code_data.get('verification_uri_complete') or code_data.get('verification_uri') or 'https://punchplay.tv'
    interval = max(int(code_data.get('interval', 5) or 5), 3)
    expires_in = int(code_data.get('expires_in', 900) or 900)
    try:
        from resources.lib.utils import make_qr
    except:
        make_qr = None
    qr_path = ''
    try:
        if make_qr:
            qr_path = make_qr(verification_url, 'punchplay_qr.png') or ''
    except:
        pass
    msg = (f"1. Open this link in browser:\n"
           f"[B][COLOR {PUNCHPLAY_COLOR}]{verification_url}[/COLOR][/B]\n"
           f"2. Enter code: [B][COLOR yellow]{user_code}[/COLOR][/B]")
    try:
        from resources.lib.auth_dialog import QRProgressDialog, run_modal_main_thread
        dialog = QRProgressDialog(
            'auth_qr.xml', ADDON_PATH, 'Default', '1080i',
            heading=f'[B][COLOR {PUNCHPLAY_COLOR}]PunchPlay Authentication[/COLOR][/B]',
            qr_image=qr_path,
            icon=PUNCHPLAY_ICON,
            addon_icon=os.path.join(ADDON_PATH, 'icon.png'),
            content=msg)
    except Exception:
        dialog = None
    _result = {}
    _mon = xbmc.Monitor()

    def _poll():
        start_time = time.time()
        while (dialog is None or not dialog.iscanceled()) and not _mon.abortRequested():
            elapsed = time.time() - start_time
            if elapsed > expires_in:
                if dialog is not None:
                    dialog.expired = True
                    dialog.close()
                return
            if dialog is not None:
                percent = max(0, int(100 - (elapsed / expires_in * 100)))
                dialog.update(percent, msg)
            time.sleep(interval)
            result = api.device_token(device_code)
            if not isinstance(result, dict):
                continue
            if result.get('error') == 'authorization_pending':
                continue
            if result.get('access_token'):
                _result['token'] = result
                if dialog is not None:
                    dialog.close()
                return
            if result.get('error') in ('expired_token', 'access_denied'):
                _result['denied'] = result.get('error')
                if dialog is not None:
                    dialog.close()
                return

    import threading
    threading.Thread(target=_poll, daemon=True).start()
    if dialog is not None:
        try:
            run_modal_main_thread(dialog)
        except:
            pass
        try:
            dialog.close()
        except:
            pass
    else:
        xbmcgui.Dialog().ok(provider_title('punchplay'), msg)
    token = _result.get('token')
    if isinstance(token, dict) and token.get('access_token'):
        api._save_tokens(token.get('access_token'), token.get('refresh_token', ''), token.get('expires_in', 3600))
        username = token.get('username') or ''
        try:
            info = api.get_user_info()
            if info and info.get('username'):
                username = info.get('username')
        except:
            pass
        api.set_username(username)
        ADDON.setSetting('punchplay_status', f'Connected: {username}' if username else 'Connected')
        xbmcgui.Dialog().notification(provider_title('punchplay'),
                                      f'Connected as [B]{username}[/B]' if username else 'Connected!',
                                      PUNCHPLAY_ICON, 4000, False)
        threading.Thread(target=_sync_full_library_background, daemon=True).start()
        xbmc.executebuiltin('Container.Refresh')
        return
    if _result.get('denied'):
        xbmcgui.Dialog().notification(provider_title('punchplay'),
                                      'Authorization denied or expired. Try again.',
                                      PUNCHPLAY_ICON, 4000, False)
        return
    if dialog is not None and getattr(dialog, 'expired', False):
        xbmcgui.Dialog().notification(provider_title('punchplay'),
                                      'Authorization expired. Try again.',
                                      PUNCHPLAY_ICON, 4000, False)


def _sync_full_library_background():
    from resources.lib.punchplay_sync import sync_full_library
    sync_full_library(silent=True, force=True)


def punchplay_revoke():
    if not xbmcgui.Dialog().yesno(f"[B][COLOR {PUNCHPLAY_COLOR}]Disconnect PunchPlay[/COLOR][/B]",
                                  f"Are you sure you want to disconnect from [B][COLOR {PUNCHPLAY_COLOR}]PunchPlay[/COLOR][/B]?\n[COLOR gray]Synced data will be deleted for security.[/COLOR]"):
        return
    from resources.lib import punchplay_sync
    api = PunchplayAPI()
    if api.is_authenticated():
        api.revoke()
    ADDON.setSetting('punchplay_status', 'Disconnected')
    try:
        from resources.lib.watched_provider import ensure_active_provider
        ensure_active_provider()
    except:
        pass
    try:
        punchplay_sync.clear_all_local_data()
    except:
        pass
    try:
        from resources.lib.watched_provider import _invalidate_fast_cache
        _invalidate_fast_cache()
    except:
        pass
    xbmcgui.Dialog().notification(provider_title('punchplay'),
                                  'Disconnected.',
                                  PUNCHPLAY_ICON, 3000, False)
    xbmc.executebuiltin('Container.Refresh')


def prompt_punchplay_rating(tmdb_id, content_type, season, episode, title):
    from resources.lib.trakt_api import _prompt_trakt_rating
    _prompt_trakt_rating(tmdb_id, content_type, season, episode, title, service='punchplay')
