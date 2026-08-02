# -*- coding: utf-8 -*-
"""
MDBList API client — suporta autentificare API Key si OAuth Bearer token.
Toate endpointurile necesare: sync, scrobble, checkin, calendar, lists, upnext.
"""

import os
import json
import time
import datetime
import threading
import xbmc
import xbmcgui
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from resources.lib.config import MDBLIST_API_URL, MDBLIST_CLIENT_ID, ADDON, ADDON_PATH

MDBLIST_ICON = os.path.join(ADDON_PATH, 'resources', 'media', 'mdblist.png')

_API_LOCK = threading.Lock()
_SESSION = None

def _get_session():
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[502, 503, 504])
        _SESSION.mount('https://api.mdblist.com', HTTPAdapter(max_retries=retries))
    return _SESSION

class MDBListAPI:
    def __init__(self):
        self.base_url = MDBLIST_API_URL.rstrip('/')
        self.client_id = MDBLIST_CLIENT_ID
        self._session = _get_session()

    # ------------------------------------------------------------------
    # AUTH
    # ------------------------------------------------------------------
    def _get_token(self):
        return (ADDON.getSetting('mdblist_access_token') or '').strip()

    def _get_refresh_token(self):
        return (ADDON.getSetting('mdblist_refresh_token') or '').strip()

    def _get_api_key(self):
        return (ADDON.getSetting('mdblist_api') or '').strip()

    def _save_token(self, access_token, refresh_token, expires_in):
        created = str(int(time.time()))
        ADDON.setSetting('mdblist_access_token', access_token)
        ADDON.setSetting('mdblist_refresh_token', refresh_token)
        ADDON.setSetting('mdblist_token_created', created)
        ADDON.setSetting('mdblist_token_expires', str(expires_in))

    def _clear_token(self):
        ADDON.setSetting('mdblist_access_token', '')
        ADDON.setSetting('mdblist_refresh_token', '')
        ADDON.setSetting('mdblist_token_created', '')
        ADDON.setSetting('mdblist_token_expires', '')
        ADDON.setSetting('mdblist_username', '')

    def _is_token_expired(self):
        created = ADDON.getSetting('mdblist_token_created') or '0'
        expires = ADDON.getSetting('mdblist_token_expires') or '0'
        try:
            created_ts = int(created)
            expires_in = int(expires)
            return (time.time() - created_ts) >= (expires_in - 300)
        except:
            return True

    def _refresh_token_if_needed(self):
        if not self._get_refresh_token():
            return
        if not self._is_token_expired():
            return
        try:
            data = {
                'grant_type': 'refresh_token',
                'refresh_token': self._get_refresh_token(),
                'client_id': self.client_id,
            }
            r = requests.post(f'{self.base_url}/oauth/token/', data=data, timeout=10)
            if r.status_code == 200:
                j = r.json()
                self._save_token(
                    j.get('access_token', ''),
                    j.get('refresh_token', ''),
                    j.get('expires_in', 2592000)
                )
        except:
            pass

    def is_authenticated(self):
        return bool(self._get_token()) or bool(self._get_api_key())

    # ------------------------------------------------------------------
    # REQUEST
    # ------------------------------------------------------------------
    def _request(self, method, path, params=None, json_data=None, silent_404=False):
        url = f'{self.base_url}/{path.lstrip("/")}'
        headers = {
            'User-Agent': 'TMDbMovies/1.0',
            'Accept': 'application/json',
        }

        token = self._get_token()
        api_key = self._get_api_key()

        # OAuth endpoints don't need authentication
        is_oauth = path.startswith('oauth/')

        if not is_oauth:
            if token:
                self._refresh_token_if_needed()
                headers['Authorization'] = f'Bearer {self._get_token()}'
            elif api_key:
                params = params or {}
                params['apikey'] = api_key
            else:
                return None

        if json_data is not None:
            headers['Content-Type'] = 'application/json'

        try:
            r = self._session.request(method, url, params=params, json=json_data, headers=headers, timeout=15)
            if r.status_code == 429:
                retry_after = int(r.headers.get('Retry-After', 5))
                xbmc.log(f'[MDBList] Rate limited, retrying after {retry_after}s', xbmc.LOGINFO)
                time.sleep(min(retry_after, 10))
                r = self._session.request(method, url, params=params, json=json_data, headers=headers, timeout=15)
            if r.status_code == 401 and token:
                self._refresh_token_if_needed()
                headers['Authorization'] = f'Bearer {self._get_token()}'
                r = self._session.request(method, url, params=params, json=json_data, headers=headers, timeout=15)
            r.raise_for_status()
            if r.status_code == 204:
                return {}
            return r.json()
        except requests.HTTPError as e:
            if silent_404 and e.response.status_code == 404:
                xbmc.log(f'[MDBList] HTTP 404 on {method} /{path}: {e.response.text[:300]}', xbmc.LOGDEBUG)
            else:
                xbmc.log(f'[MDBList] HTTP {e.response.status_code} on {method} /{path}: {e.response.text[:300]}', xbmc.LOGERROR)
            return None
        except Exception as e:
            xbmc.log(f'[MDBList] {method} /{path} error: {e}', xbmc.LOGERROR)
            return None

    def _get(self, path, params=None):
        return self._request('GET', path, params=params)

    def _post(self, path, data=None, silent_404=False):
        return self._request('POST', path, json_data=data, silent_404=silent_404)

    def _post_form(self, path, data=None):
        """POST cu Content-Type: application/x-www-form-urlencoded (necesar de OAuth)."""
        url = f'{self.base_url}/{path.lstrip("/")}'
        headers = {
            'User-Agent': 'TMDbMovies/1.0',
            'Accept': 'application/json',
        }
        if data is None:
            data = {}
        try:
            r = self._session.post(url, data=data, headers=headers, timeout=15)
            if r.status_code == 200:
                return r.json()
            # OAuth device flow: 400 authorization_pending / access_denied / expired_token
            # sunt raspunsuri ASTEPTATE la polling — nu erori. Returnam body-ul
            # ca apelantul sa le poata trata (fara spam in log).
            if path.startswith('oauth/'):
                try:
                    return r.json()
                except:
                    return None
            r.raise_for_status()
            return r.json()
        except requests.HTTPError as e:
            xbmc.log(f'[MDBList] HTTP {e.response.status_code} on POST_FORM /{path}: {e.response.text}', xbmc.LOGERROR)
            return None
        except Exception as e:
            xbmc.log(f'[MDBList] POST_FORM /{path} error: {e}', xbmc.LOGERROR)
            return None

    def _delete(self, path, data=None):
        return self._request('DELETE', path, json_data=data)

    def _patch(self, path, data=None):
        return self._request('PATCH', path, json_data=data)

    # ------------------------------------------------------------------
    # PAGINATION
    # ------------------------------------------------------------------
    def _paginated(self, path, params=None, limit=100):
        params = dict(params or {})
        params.setdefault('limit', limit)
        items = []
        while True:
            data = self._get(path, params)
            if not data:
                break
            pagination = data.get('pagination', {})
            items.extend(data.get('movies', []) + data.get('shows', []) + data.get('episodes', []) + data.get('seasons', []))
            if not pagination.get('has_more'):
                break
            params['cursor'] = pagination.get('next_cursor')
        return items

    # ------------------------------------------------------------------
    # AUTH FLOW
    # ------------------------------------------------------------------
    def auth_get_device_code(self):
        data = {
            'client_id': self.client_id,
            'scope': 'write',
        }
        return self._post_form('oauth/device-authorization/', data=data)

    def auth_poll_token(self, device_code):
        data = {
            'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
            'device_code': device_code,
            'client_id': self.client_id,
        }
        return self._post_form('oauth/token/', data=data)

    def revoke_token(self):
        token = self._get_token()
        if token:
            self._post_form('oauth/revoke_token/', data={'token': token})
        self._clear_token()

    def get_user_info(self):
        return self._get('user/')

    def set_username(self, username):
        ADDON.setSetting('mdblist_username', username)

    # ------------------------------------------------------------------
    # SYNC WATCHED
    # ------------------------------------------------------------------
    def get_last_activities(self):
        return self._get('sync/last_activities/')

    def get_sync_watched(self, cursor=None, limit=100, since=None, mediatype=None):
        params = {'limit': limit}
        if cursor:
            params['cursor'] = cursor
        if since:
            params['since'] = since
        if mediatype:
            params['mediatype'] = mediatype
        return self._get('sync/watched', params=params)

    def _build_show_data(self, key, media_id, season, episode):
        ids = {key: int(media_id)}
        if season is not None and episode is not None:
            return {'shows': [{'ids': ids, 'seasons': [{'number': int(season), 'episodes': [{'number': int(episode)}]}]}]}, 'episodes'
        elif season is not None:
            return {'shows': [{'ids': ids, 'seasons': [{'number': int(season)}]}]}, 'episodes'
        else:
            return {'shows': [{'ids': ids}]}, 'shows'

    def _check_result(self, result, key, success_key):
        return result.get(key, {}).get(success_key, 0) > 0

    def mark_watched(self, media_type, tmdb_id, season=None, episode=None, watched_at=None, tvdb_id=0):
        if watched_at is None:
            watched_at = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z')
        if media_type == 'movie':
            data = {'movies': [{'ids': {'tmdb': int(tmdb_id)}}]}
            result = self._post('sync/watched', data=data)
            if not self._check_result(result, 'updated', 'movies') and tvdb_id:
                data = {'movies': [{'ids': {'tvdb': int(tvdb_id)}}]}
                result = self._post('sync/watched', data=data)
            return result
        data, success_key = self._build_show_data('tmdb', tmdb_id, season, episode)
        result = self._post('sync/watched', data=data)
        if not self._check_result(result, 'updated', success_key) and tvdb_id:
            data, _ = self._build_show_data('tvdb', tvdb_id, season, episode)
            result = self._post('sync/watched', data=data)
        return result

    def mark_unwatched(self, media_type, tmdb_id, season=None, episode=None, tvdb_id=0):
        if media_type == 'movie':
            data = {'movies': [{'ids': {'tmdb': int(tmdb_id)}}]}
            result = self._post('sync/watched/remove', data=data)
            if not self._check_result(result, 'removed', 'movies') and tvdb_id:
                data = {'movies': [{'ids': {'tvdb': int(tvdb_id)}}]}
                result = self._post('sync/watched/remove', data=data)
            return result
        data, success_key = self._build_show_data('tmdb', tmdb_id, season, episode)
        result = self._post('sync/watched/remove', data=data)
        if not self._check_result(result, 'removed', success_key) and tvdb_id:
            data, _ = self._build_show_data('tvdb', tvdb_id, season, episode)
            result = self._post('sync/watched/remove', data=data)
        return result

    # ------------------------------------------------------------------
    # SYNC RATINGS
    # ------------------------------------------------------------------
    def get_sync_ratings(self, cursor=None, limit=100):
        params = {'limit': limit}
        if cursor:
            params['cursor'] = cursor
        return self._get('sync/ratings', params=params)

    def rate_item(self, media_type, tmdb_id, rating, season=None, episode=None, rated_at=None):
        if rated_at is None:
            rated_at = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z')
        ids = {'tmdb': int(tmdb_id)}
        if media_type == 'movie':
            data = {'movies': [{'ids': ids, 'rating': int(rating), 'rated_at': rated_at}]}
        elif season is not None and episode is not None:
            data = {'shows': [{'ids': ids, 'seasons': [{'number': int(season), 'episodes': [{'number': int(episode), 'rating': int(rating), 'rated_at': rated_at}]}]}]}
        elif season is not None:
            data = {'shows': [{'ids': ids, 'seasons': [{'number': int(season), 'rating': int(rating), 'rated_at': rated_at}]}]}
        else:
            data = {'shows': [{'ids': ids, 'rating': int(rating), 'rated_at': rated_at}]}
        return self._post('sync/ratings', data=data)

    def remove_rating(self, media_type, tmdb_id, season=None, episode=None):
        ids = {'tmdb': int(tmdb_id)}
        if media_type == 'movie':
            data = {'movies': [{'ids': ids}]}
        elif season is not None and episode is not None:
            data = {'shows': [{'ids': ids, 'seasons': [{'number': int(season), 'episodes': [{'number': int(episode)}]}]}]}
        elif season is not None:
            data = {'shows': [{'ids': ids, 'seasons': [{'number': int(season)}]}]}
        else:
            data = {'shows': [{'ids': ids}]}
        return self._post('sync/ratings/remove', data=data)

    # ------------------------------------------------------------------
    # SYNC COLLECTION
    # ------------------------------------------------------------------
    def get_collection(self, cursor=None, limit=100, mediatype=None):
        params = {'limit': limit}
        if cursor:
            params['cursor'] = cursor
        if mediatype:
            params['mediatype'] = mediatype
        return self._get('sync/collection', params=params)

    def add_to_collection(self, media_type, tmdb_id):
        ids = {'tmdb': int(tmdb_id)}
        collected_at = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z')
        if media_type == 'movie':
            data = {'movies': [{'ids': ids, 'collected_at': collected_at}]}
        else:
            data = {'shows': [{'ids': ids, 'collected_at': collected_at}]}
        return self._post('sync/collection', data=data)

    def remove_from_collection(self, media_type, tmdb_id):
        ids = {'tmdb': int(tmdb_id)}
        if media_type == 'movie':
            data = {'movies': [{'ids': ids}]}
        else:
            data = {'shows': [{'ids': ids}]}
        return self._post('sync/collection/remove', data=data)

    # ------------------------------------------------------------------
    # SYNC DROPPED
    # ------------------------------------------------------------------
    def get_dropped(self, cursor=None, limit=100):
        params = {'limit': limit}
        if cursor:
            params['cursor'] = cursor
        return self._get('sync/dropped', params=params)

    def mark_dropped(self, tmdb_id):
        dropped_at = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z')
        data = {'shows': [{'ids': {'tmdb': int(tmdb_id)}, 'dropped_at': dropped_at}]}
        return self._post('sync/dropped', data=data)

    def unmark_dropped(self, tmdb_id):
        data = {'shows': [{'ids': {'tmdb': int(tmdb_id)}}]}
        return self._post('sync/dropped/remove', data=data)

    # ------------------------------------------------------------------
    # SCROBBLE
    # ------------------------------------------------------------------
    def _scrobble_body(self, media_type, tmdb_id, progress, season=None, episode=None):
        try:
            p = min(max(float(progress), 0.0), 100.0)
        except:
            p = 0.0
        body = {'progress': round(p, 2)}
        ids = {'tmdb': int(tmdb_id)}
        if media_type == 'movie':
            body['movie'] = {'ids': ids}
        else:
            body['show'] = {'ids': ids}
            if season is not None and episode is not None:
                body['show']['season'] = {'number': int(season), 'episode': {'number': int(episode)}}
        return body

    def scrobble_start(self, media_type, tmdb_id, progress=0, season=None, episode=None):
        return self._post('scrobble/start', data=self._scrobble_body(media_type, tmdb_id, progress, season, episode))

    def scrobble_pause(self, media_type, tmdb_id, progress, season=None, episode=None):
        return self._post('scrobble/pause', data=self._scrobble_body(media_type, tmdb_id, progress, season, episode))

    def scrobble_stop(self, media_type, tmdb_id, progress, season=None, episode=None):
        return self._post('scrobble/stop', data=self._scrobble_body(media_type, tmdb_id, progress, season, episode))

    def scrobble_clear(self, media_type=None, tmdb_id=None, season=None, episode=None, silent_404=False):
        if tmdb_id is None:
            return self._post('scrobble/clear', silent_404=silent_404)
        data = {'movie' if media_type == 'movie' else 'show': {'ids': {'tmdb': int(tmdb_id)}}}
        if media_type != 'movie' and season is not None and episode is not None:
            data['show']['season'] = {'number': int(season), 'episode': {'number': int(episode)}}
        return self._post('scrobble/clear', data=data, silent_404=silent_404)

    # ------------------------------------------------------------------
    # CHECKIN
    # ------------------------------------------------------------------
    def checkin_get(self):
        return self._get('checkin')

    def checkin_start(self, media_type, tmdb_id, season=None, episode=None):
        ids = {'tmdb': int(tmdb_id)}
        if media_type == 'movie':
            data = {'movie': {'ids': ids}}
        else:
            data = {'show': {'ids': ids}}
            if season is not None and episode is not None:
                data['show']['season'] = {'number': int(season), 'episode': {'number': int(episode)}}
        return self._post('checkin', data=data)

    def checkin_update(self, progress, paused=False):
        try:
            p = min(max(float(progress), 0.0), 100.0)
        except:
            p = 0.0
        return self._patch('checkin', data={'progress': round(p, 2), 'paused': paused})

    def checkin_stop(self):
        return self._delete('checkin')

    # ------------------------------------------------------------------
    # PLAYBACK
    # ------------------------------------------------------------------
    def get_playback_sessions(self):
        return self._get('sync/playback')

    def get_now_playing(self):
        return self._get('sync/now-playing/')

    # ------------------------------------------------------------------
    # UP NEXT
    # ------------------------------------------------------------------
    def get_upnext(self, limit=20, offset=0, hide_unreleased=True):
        params = {'limit': limit, 'offset': offset}
        if hide_unreleased:
            params['hide_unreleased'] = 'true'
        return self._get('upnext/', params=params)

    def get_upnext_upcoming(self, limit=20, offset=0, days=14):
        return self._get('upnext/upcoming/', params={'limit': limit, 'offset': offset, 'days': days})

    def get_upnext_watchlist(self, limit=20, offset=0):
        return self._get('upnext/watchlist/', params={'limit': limit, 'offset': offset})

    # ------------------------------------------------------------------
    # CALENDAR
    # ------------------------------------------------------------------
    def calendar_events(self, start=None, end=None, limit=1000):
        params = {'limit': limit}
        if start:
            params['start'] = start
        if end:
            params['end'] = end
        return self._get('calendar/events/', params=params)

    # ------------------------------------------------------------------
    # WATCHLIST
    # ------------------------------------------------------------------
    def get_watchlist(self, mediatype=None, cursor=None, limit=100):
        params = {'limit': limit}
        if mediatype:
            params['mediatype'] = mediatype
        if cursor:
            params['cursor'] = cursor
        return self._get('watchlist/items/', params=params)

    def watchlist_add(self, media_type, tmdb_id, imdb_id=None):
        ids = {'tmdb': int(tmdb_id)}
        if imdb_id:
            ids['imdb'] = str(imdb_id)
        if media_type in ('show', 'tv'):
            data = {'shows': [{'ids': ids}]}
        else:
            data = {'movies': [{'ids': ids}]}
        return self._post('watchlist/items/add/', data=data)

    def watchlist_remove(self, media_type, tmdb_id, imdb_id=None):
        ids = {'tmdb': int(tmdb_id)}
        if imdb_id:
            ids['imdb'] = str(imdb_id)
        if media_type in ('show', 'tv'):
            data = {'shows': [{'ids': ids}]}
        else:
            data = {'movies': [{'ids': ids}]}
        return self._post('watchlist/items/remove/', data=data)

    # ------------------------------------------------------------------
    # LISTS
    # ------------------------------------------------------------------
    def get_user_lists(self):
        return self._get('lists/user/')

    def get_top_lists(self, limit=20, offset=0):
        return self._get('lists/top/', params={'limit': limit, 'offset': offset})

    def get_curated_lists(self, limit=20, offset=0):
        return self._get('lists/curated/', params={'limit': limit, 'offset': offset})

    def get_recommended_lists(self, section='recommended'):
        return self._get(f'lists/recommended/{section}/')

    def get_liked_lists(self, limit=20, offset=0):
        return self._get('lists/liked/', params={'limit': limit, 'offset': offset})

    def search_lists(self, query, limit=20, offset=0):
        return self._get('lists/search/', params={'query': query, 'limit': limit, 'offset': offset})

    def get_list_items(self, list_id, cursor=None, limit=100, mediatype=None):
        params = {'limit': limit}
        if cursor:
            params['cursor'] = cursor
        if mediatype:
            params['mediatype'] = mediatype
        return self._get(f'lists/{list_id}/items/', params=params)

    def list_add_items(self, list_id, media_type, tmdb_id, imdb_id=None):
        ids = {'tmdb': int(tmdb_id)}
        if imdb_id:
            ids['imdb'] = str(imdb_id)
        if media_type in ('show', 'tv'):
            data = {'shows': [{'ids': ids}]}
        else:
            data = {'movies': [{'ids': ids}]}
        return self._post(f'lists/{list_id}/items/add/', data=data)

    def list_remove_items(self, list_id, media_type, tmdb_id, imdb_id=None):
        ids = {'tmdb': int(tmdb_id)}
        if imdb_id:
            ids['imdb'] = str(imdb_id)
        if media_type in ('show', 'tv'):
            data = {'shows': [{'ids': ids}]}
        else:
            data = {'movies': [{'ids': ids}]}
        return self._post(f'lists/{list_id}/items/remove/', data=data)


def prompt_mdblist_rating(tmdb_id, content_type, season, episode, title):
    """Deschide TraktRating.xml cu service='mdblist' pentru rating pe MDBList."""
    from resources.lib.trakt_api import _prompt_trakt_rating
    _prompt_trakt_rating(tmdb_id, content_type, season, episode, title, service='mdblist')


# ------------------------------------------------------------------
# AUTH UI FLOW (Device Code)
# ------------------------------------------------------------------
def mdblist_auth():
    """OAuth Device Code authentication flow with DialogProgress."""
    client_id = MDBLIST_CLIENT_ID
    if not client_id:
        xbmcgui.Dialog().ok(
            '[B][COLOR lightskyblue]MDBList[/COLOR][/B]',
            'No MDBList Client ID configured.',
            'Go to [B]mdblist.com/developer/[/B] and register an app.',
            'Then set [B]MDBLIST_CLIENT_ID[/B] in [B]config.py[/B].'
        )
        return

    api = MDBListAPI()
    device_data = api.auth_get_device_code()
    if not device_data:
        xbmcgui.Dialog().notification('[B][COLOR lightskyblue]MDBList[/COLOR][/B]',
                                       'Failed to get device code. Check log.',
                                       MDBLIST_ICON, 5000, False)
        return

    user_code = device_data.get('user_code', 'XXXX-XXXX')
    verification_url = device_data.get('verification_url', 'https://mdblist.com/oauth/device/')
    device_code = device_data.get('device_code', '')
    interval = int(device_data.get('interval', 5))
    expires_in = int(device_data.get('expires_in', 600))

    # ══════════════════════════════════════════════════════════
    # QR CODE AUTH (stil Umbrella) — dialog custom cu QR + cod
    # doModal() pe MAIN THREAD (input garantat); polling in background
    # ══════════════════════════════════════════════════════════
    from resources.lib.utils import make_qr
    from resources.lib.auth_dialog import QRProgressDialog, run_modal_main_thread
    qr_path = make_qr(verification_url, 'mdblist_qr.png')
    msg = (f"1. Open this link in browser:\n"
           f"[B][COLOR lightskyblue]https://mdblist.com/oauth/device[/COLOR][/B]\n"
           f"2. Enter code: [B][COLOR yellow]{user_code}[/COLOR][/B]")
    dialog = QRProgressDialog(
        'auth_qr.xml', ADDON_PATH, 'Default', '1080i',
        heading='[B][COLOR lightskyblue]MDBList Authentication[/COLOR][/B]',
        qr_image=qr_path or '',
        icon=MDBLIST_ICON,
        addon_icon=os.path.join(ADDON_PATH, 'icon.png'),
        content=msg,
    )

    _result = {}
    _mon = xbmc.Monitor()

    def _poll():
        start_time = time.time()
        interval_cur = interval
        while not dialog.iscanceled() and not _mon.abortRequested():
            elapsed = time.time() - start_time
            if elapsed > expires_in:
                dialog.expired = True
                dialog.close()
                return
            percent = max(0, int(100 - (elapsed / expires_in * 100)))
            dialog.update(percent, msg)
            time.sleep(interval_cur)

            result = api.auth_poll_token(device_code)
            if result is None:
                continue

            if 'access_token' in result:
                _result['token'] = result
                dialog.close()
                return

            error = result.get('error', '')
            if error in ('access_denied', 'expired_token'):
                _result['denied'] = error
                dialog.close()
                return

    threading.Thread(target=_poll, daemon=True).start()
    run_modal_main_thread(dialog)
    dialog.close()

    token_data = _result.get('token')
    if token_data:
        api._save_token(
            token_data.get('access_token', ''),
            token_data.get('refresh_token', ''),
            token_data.get('expires_in', 2592000)
        )
        user_info = api.get_user_info()
        username = ''
        if user_info:
            username = user_info.get('username', user_info.get('name', ''))
            api.set_username(username)

        status = f'Connected: {username}' if username else 'Connected'
        ADDON.setSetting('mdblist_status', status)

        xbmcgui.Dialog().notification('[B][COLOR lightskyblue]MDBList[/COLOR][/B]',
                                       f'Connected as [B][COLOR red]{username}[/COLOR][/B]' if username else 'Connected!',
                                       MDBLIST_ICON, 4000, False)

        threading.Thread(target=sync_full_library_background, daemon=True).start()
        xbmc.executebuiltin('Container.Refresh')
        return

    if _result.get('denied'):
        xbmcgui.Dialog().notification('[B][COLOR lightskyblue]MDBList[/COLOR][/B]',
                                       f'Authorization {_result["denied"].replace("_", " ")}.',
                                       MDBLIST_ICON, 4000, False)
        return

    if dialog.expired:
        xbmcgui.Dialog().notification('[B][COLOR lightskyblue]MDBList[/COLOR][/B]',
                                       'Authorization expired. Try again.',
                                       MDBLIST_ICON, 4000, False)


def sync_full_library_background():
    from resources.lib.mdblist_sync import sync_full_library
    sync_full_library(silent=True, force=True)


def mdblist_revoke():
    # --- START PROTECTIE DECONECTARE ACCIDENTALA ---
    if not xbmcgui.Dialog().yesno("[B][COLOR lightskyblue]Disconnect MDBList[/COLOR][/B]", "Are you sure you want to disconnect from MDBList?\n[COLOR gray]Synced data will be deleted for security.[/COLOR]"):
        return
    # --- END PROTECTIE ---

    api = MDBListAPI()
    api.revoke_token()
    ADDON.setSetting('mdblist_status', 'Disconnected')
    ADDON.setSetting('mdblist_username', '')
    ADDON.setSetting('mdblist_api', '')
    xbmcgui.Dialog().notification('[B][COLOR lightskyblue]MDBList[/COLOR][/B]',
                                   'Disconnected.',
                                   MDBLIST_ICON, 3000, False)
    xbmc.executebuiltin('Container.Refresh')
