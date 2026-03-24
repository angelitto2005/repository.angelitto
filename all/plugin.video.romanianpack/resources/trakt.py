# -*- coding: utf-8 -*-
import json
import re
import time
import datetime
import threading  # ← ADĂUGAT pentru thread safety la refresh
try:
    import urllib
    from urlparse import urljoin
except:
    from urllib.parse import urljoin
    import urllib.parse as urllib
import xbmcaddon
import xbmc
import xbmcgui
from resources.lib import requests
from resources.functions import log, pbar, replaceHTMLCodes, py3

BASE_URL = 'https://api.trakt.tv'
REDIRECT_URI = 'urn:ietf:wg:oauth:2.0:oob'

addon = xbmcaddon.Addon()
CLIENT_ID = addon.getSetting('trakt.clientid')
CLIENT_SECRET = addon.getSetting('trakt.clientsecret')

# ══════════════════════════════════════════════════════════
# ADĂUGAT: Thread lock pentru refresh token (single-use!)
# ══════════════════════════════════════════════════════════
_refresh_lock = threading.Lock()


def __getTrakt(url, post=None, noget=None):
    try:
        if not CLIENT_ID or not CLIENT_SECRET:
            log("### [Trakt]: Client ID sau Client Secret lipsesc din settings.xml!")
            return None, None

        url = urljoin(BASE_URL, url)
        post = json.dumps(post, ensure_ascii=False) if post else None
        
        headers = {
            'Content-Type': 'application/json',
            'trakt-api-key': CLIENT_ID,
            'trakt-api-version': '2',
            'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; rv:5.0) Gecko/20100101 Firefox/5.0',
            'Accept-Language': 'en-US'
        }

        if getTraktCredentialsInfo():
            headers.update({
                'Authorization': 'Bearer %s' % xbmcaddon.Addon().getSetting('trakt.token')
            })
        
        # ══════════════════════════════════════════════════
        # FIX 1: Salvăm metoda originală pentru retry corect
        # (Înainte, retry-ul era MEREU GET — chiar și pentru
        #  POST-uri ca markAsWatched, addToWatchlist, etc.)
        # ══════════════════════════════════════════════════
        is_post_request = bool(post or noget)
        
        if is_post_request:
            askd = requests.post(url, data=post, headers=headers)
        else:
            askd = requests.get(url, headers=headers)

        resp_code = str(askd.status_code)
        
        if resp_code in ['500', '502', '503', '504', '520', '521', '522', '524']:
            log("### [Trakt]: Temporary Trakt Error: %s" % resp_code)
            return None, None
        elif resp_code in ['404']:
            log("### [Trakt]: Object Not Found : %s" % resp_code)
            return None, None
        elif resp_code in ['429']:
            log("### [Trakt]: Trakt Rate Limit Reached: %s" % resp_code)
            return None, None

        if resp_code not in ['401', '405']:
            # ── Succes — procesăm răspunsul normal ──
            resp_header_raw = dict(askd.headers)
            resp_header = {k: v for k, v in resp_header_raw.items()}
            
            if post and not noget:
                result = askd.content
            else:
                try:
                    result = askd.json()
                except:
                    result = askd.text
            return result, resp_header

        # ══════════════════════════════════════════════════
        # 401/405 — Token expirat, încercăm refresh
        # ══════════════════════════════════════════════════
        log("### [Trakt]: Got %s, attempting token refresh..." % resp_code)
        
        # ══════════════════════════════════════════════════
        # FIX 2: Thread lock — refresh_token e SINGLE-USE
        # Fără lock, 2 requesturi simultane cu 401 ar face
        # 2 refresh-uri, al doilea consumând un token deja
        # invalid → ambele eșuează → delogare
        # ══════════════════════════════════════════════════
        with _refresh_lock:
            # Re-citim tokenul DUPĂ lock — alt thread l-ar fi putut reînnoi
            current_token = xbmcaddon.Addon().getSetting('trakt.token')
            token_used = headers.get('Authorization', '').replace('Bearer ', '')
            
            if current_token and current_token != token_used:
                # ── Alt thread a făcut deja refresh — folosim noul token ──
                log("### [Trakt]: Token deja reinnoit de alt thread.")
                new_token = current_token
            else:
                # ── Trebuie să facem noi refresh-ul ──
                oauth = urljoin(BASE_URL, '/oauth/token')
                opost_dict = {
                    'client_id': CLIENT_ID,
                    'client_secret': CLIENT_SECRET,
                    'redirect_uri': REDIRECT_URI,
                    'grant_type': 'refresh_token',
                    'refresh_token': xbmcaddon.Addon().getSetting('trakt.refresh')
                }
                
                # ══════════════════════════════════════
                # FIX 3: Folosim json= în loc de data=
                # (trimite Content-Type: application/json
                #  corect, consistent cu restul API-ului)
                # ══════════════════════════════════════
                try:
                    refresh_result = requests.post(
                        oauth,
                        json=opost_dict,
                        headers={
                            'Content-Type': 'application/json',
                            'User-Agent': headers['User-Agent']
                        },
                        timeout=15
                    )
                except Exception as e:
                    log("### [Trakt]: Refresh request failed: %s" % str(e))
                    return None, None
                
                if refresh_result.status_code != 200:
                    log("### [Trakt]: Eroare la refresh token. Status: %s, Raspuns: %s"
                        % (refresh_result.status_code, refresh_result.text[:300]))
                    # ══════════════════════════════════
                    # FIX 4: Notificare user că trebuie
                    # să se re-autentifice manual
                    # ══════════════════════════════════
                    try:
                        xbmcgui.Dialog().notification(
                            "[B]Trakt[/B]",
                            "Sesiunea a expirat! Re-autentifica-te.",
                            xbmcgui.NOTIFICATION_ERROR, 5000
                        )
                    except:
                        pass
                    return None, None

                r_json = refresh_result.json()
                new_token = r_json['access_token']
                new_refresh = r_json['refresh_token']

                xbmcaddon.Addon().setSetting(id='trakt.token', value=new_token)
                xbmcaddon.Addon().setSetting(id='trakt.refresh', value=new_refresh)
                log("### [Trakt]: Token reinnoit cu succes!")

        # ══════════════════════════════════════════════════
        # Retry requestul original cu noul token
        # ══════════════════════════════════════════════════
        headers['Authorization'] = 'Bearer %s' % new_token

        # ══════════════════════════════════════════════════
        # FIX 5: Retry-ul folosește ACEEAȘI metodă ca originalul
        # (Înainte era MEREU requests.get, chiar și pt POST!)
        # ══════════════════════════════════════════════════
        try:
            if is_post_request:
                retry_result = requests.post(url, data=post, headers=headers)
            else:
                retry_result = requests.get(url, headers=headers)
            
            # ══════════════════════════════════════════
            # FIX 6: Error handling pe retry
            # (Înainte, .json() pe un 401 = crash)
            # ══════════════════════════════════════════
            if str(retry_result.status_code) not in ['200', '201', '204']:
                log("### [Trakt]: Retry dupa refresh esuat: HTTP %s"
                    % retry_result.status_code)
                return None, None
            
            resp_header = dict(retry_result.headers)
            
            if post and not noget:
                result = retry_result.content
            else:
                try:
                    result = retry_result.json()
                except:
                    result = retry_result.text
            
            return result, resp_header
            
        except Exception as e:
            log("### [Trakt]: Retry request failed: %s" % str(e))
            return None, None

    except Exception as e:
        log("### [Trakt]: MRSP getTrakt Unknown Trakt Error: %s" % str(e))
        import traceback
        log(traceback.format_exc())
        return None, None


def getTraktAsJson(url, post=None, noget=None):
    try:
        r, res_headers_dict = __getTrakt(url, post, noget)
        
        if r is None:
            return None

        res_headers = json.loads(json.dumps(res_headers_dict)) if res_headers_dict else {}

        if 'X-Sort-By' in res_headers and 'X-Sort-How' in res_headers:
            r = sort_list(res_headers['X-Sort-By'], res_headers['X-Sort-How'], r)
        return r
    except Exception as e:
        log("### [Trakt]: Eroare in getTraktAsJson: %s" % str(e))
        return None


def authTrakt():
    try:
        # ══════════════════════════════════════════════════
        # Dacă e deja autorizat, întrebăm clar ce vrea
        # ══════════════════════════════════════════════════
        if getTraktCredentialsInfo() == True:
            user = xbmcaddon.Addon().getSetting('trakt.user').strip() or "necunoscut"
            
            choice = xbmcgui.Dialog().yesno(
                "Trakt - Cont Activ",
                (
                    "Ești conectat ca: [B][COLOR FFFDBD01]%s[/COLOR][/B]\n\n"
                    "Vrei să deconectezi acest cont și să autorizezi altul?"
                ) % user,
                nolabel="Păstrează",
                yeslabel="Deconectează"
            )
            
            if not choice:
                # Userul a ales "Păstrează" → nu facem nimic
                return
            
            # Userul a ales "Deconectează" → ștergem și continuăm la re-autorizare
            addon.setSetting(id='trakt.user', value='')
            addon.setSetting(id='trakt.token', value='')
            addon.setSetting(id='trakt.refresh', value='')
            xbmcgui.Dialog().notification(
                "Trakt", "Cont deconectat. Se începe re-autorizarea...",
                xbmcgui.NOTIFICATION_INFO, 2000
            )
            # Mică pauză ca userul să vadă notificarea
            time.sleep(1)

        # ══════════════════════════════════════════════════
        # Obținem codul de verificare de la Trakt
        # ══════════════════════════════════════════════════
        result = getTraktAsJson('/oauth/device/code', {'client_id': CLIENT_ID}, '1')
        
        if not result or 'verification_url' not in result:
            log("### [Trakt]: Eroare la obtinerea codului de la Trakt.")
            xbmcgui.Dialog().ok(
                "Eroare Trakt",
                "Nu s-a putut obține codul de verificare de la Trakt."
                "\n[CR]Verificați dacă Client ID-ul este corect în setări."
            )
            return

        verification_url = result['verification_url']
        user_code = result['user_code']
        expires_in = int(result['expires_in'])
        device_code = result['device_code']
        interval = result['interval']

        # ══════════════════════════════════════════════════
        # Dialog cu instrucțiuni clare
        # ══════════════════════════════════════════════════
        progressDialog = xbmcgui.DialogProgress()
        msg = (
            "1) Vizitați: [B][COLOR FFFDBD01]%s[/COLOR][/B]\n"
            "2) Introduceți codul: [B][COLOR FFFDBD01]%s[/COLOR][/B]"
        ) % (verification_url, user_code)
        
        progressDialog.create('Autorizare Trakt', msg)

        token = None
        for i in range(0, expires_in):
            if progressDialog.iscanceled():
                break
            
            # Actualizăm procentul
            percent = max(0, int(100 - (float(i) / expires_in * 100)))
            progressDialog.update(percent, msg)
            
            time.sleep(1)
            if not float(i) % interval == 0:
                continue

            r = getTraktAsJson(
                '/oauth/device/token',
                {'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET, 'code': device_code},
                '1'
            )
            
            if r and 'access_token' in r:
                token = r['access_token']
                refresh = r['refresh_token']
                
                # Obținem username-ul
                try:
                    headers = {
                        'Content-Type': 'application/json',
                        'trakt-api-key': CLIENT_ID,
                        'trakt-api-version': '2',
                        'Authorization': 'Bearer %s' % token
                    }
                    user_info = requests.get(
                        urljoin(BASE_URL, '/users/me'),
                        headers=headers,
                        timeout=10
                    ).json()
                    user = user_info.get('username', 'User')
                except:
                    user = 'User'

                # Salvăm credențialele
                addon.setSetting(id='trakt.user', value=user)
                addon.setSetting(id='trakt.token', value=token)
                addon.setSetting(id='trakt.refresh', value=refresh)
                
                progressDialog.close()
                
                xbmcgui.Dialog().ok(
                    "Trakt - Succes!",
                    (
                        "Contul [B][COLOR FFFDBD01]%s[/COLOR][/B] "
                        "a fost autorizat cu succes!\n\n"
                        "Tokenul se va reînnoi automat."
                    ) % user
                )
                
                log("### [Trakt]: Autentificat ca '%s'. Refresh automat activ." % user)
                break

        try:
            progressDialog.close()
        except:
            pass
        
        if not token:
            xbmcgui.Dialog().ok(
                "Trakt - Eroare",
                "Autorizarea a eșuat sau a expirat.\n\n"
                "Încearcă din nou."
            )

    except Exception as e:
        log("### [MRSP] Eroare in authTrakt: %s" % str(e))
        import traceback
        log(traceback.format_exc())
        try:
            progressDialog.close()
        except:
            pass


def getTraktCredentialsInfo():
    user = xbmcaddon.Addon().getSetting('trakt.user').strip()
    token = xbmcaddon.Addon().getSetting('trakt.token')
    refresh = xbmcaddon.Addon().getSetting('trakt.refresh')
    if (user == '' or token == '' or refresh == ''): return False
    return True

def getTraktIndicatorsInfo():
    indicators = xbmcaddon.Addon().getSetting('indicators') if getTraktCredentialsInfo() == False else xbmcaddon.Addon().getSetting('indicators.alt')
    indicators = True if indicators == '1' else False
    return indicators


def getTraktAddonMovieInfo():
    try: scrobble = xbmcaddon.Addon('script.trakt').getSetting('scrobble_movie')
    except: scrobble = ''
    try: ExcludeHTTP = xbmcaddon.Addon('script.trakt').getSetting('ExcludeHTTP')
    except: ExcludeHTTP = ''
    try: authorization = xbmcaddon.Addon('script.trakt').getSetting('authorization')
    except: authorization = ''
    if scrobble == 'true' and ExcludeHTTP == 'false' and not authorization == '': return True
    else: return False


def getTraktAddonEpisodeInfo():
    try: scrobble = xbmcaddon.Addon('script.trakt').getSetting('scrobble_episode')
    except: scrobble = ''
    try: ExcludeHTTP = xbmcaddon.Addon('script.trakt').getSetting('ExcludeHTTP')
    except: ExcludeHTTP = ''
    try: authorization = xbmcaddon.Addon('script.trakt').getSetting('authorization')
    except: authorization = ''
    if scrobble == 'true' and ExcludeHTTP == 'false' and not authorization == '': return True
    else: return False

def getTraktScrobble(action, data):
    try:
        if getTraktCredentialsInfo() == False: return
        response = getTraktAsJson('/scrobble/%s' % (action), data, '1')
        return response
    except:
        pass

def manager(name, imdb, tvdb, content):
    try:
        post = {"movies": [{"ids": {"imdb": imdb}}]} if content == 'movie' else {"shows": [{"ids": {"tvdb": tvdb}}]}

        items = [("Add to [B]Collection[/B]", '/sync/collection')]
        items += [("Remove from [B]Collection[/B]", '/sync/collection/remove')]
        items += [("Add to [B]Watchlist[/B]", '/sync/watchlist')]
        items += [("Remove from [B]Watchlist[/B]", '/sync/watchlist/remove')]
        items += [("Add to [B]new List[/B]", '/users/me/lists/%s/items')]

        result = getTraktAsJson('/users/me/lists')
        lists = [(i['name'], i['ids']['slug']) for i in result]
        lists = [lists[i//2] for i in range(len(lists)*2)]
        for i in range(0, len(lists), 2):
            lists[i] = (("Add to [B]%s[/B]" % lists[i][0]).encode('utf-8'), '/users/me/lists/%s/items' % lists[i][1])
        for i in range(1, len(lists), 2):
            lists[i] = (("Remove from [B]%s[/B]" % lists[i][0]).encode('utf-8'), '/users/me/lists/%s/items/remove' % lists[i][1])
        items += lists

        select = xbmcgui.Dialog().select("Trakt Manager", [i[0] for i in items])

        if select == -1:
            return
        elif select == 4:
            t = "Add to [B]new List[/B]"
            k = xbmc.Keyboard('', t)
            k.doModal()
            new = k.getText() if k.isConfirmed() else None
            if (new == None or new == ''): return
            result = __getTrakt('/users/me/lists', post={"name": new, "privacy": "private"})[0]

            try: slug = byteify(json.loads(result, object_hook=byteify), ignore_dicts=True)['ids']['slug']
            except: return xbmcgui.Dialog().notification(str(name), "Trakt Manager", xbmcgui.NOTIFICATION_ERROR, 3000, sound=True)
            result = __getTrakt(items[select][1] % slug, post=post)[0]
        else:
            result = __getTrakt(items[select][1], post=post)[0]

        icon = xbmcgui.NOTIFICATION_INFO if not result == None else xbmcgui.NOTIFICATION_ERROR

        xbmcgui.Dialog().notification(str(name), "Trakt Manager", icon, 3000, sound=True)
    except:
        return


def slug(name):
    name = name.strip()
    name = name.lower()
    name = re.sub('[^a-z0-9_]', '-', name)
    name = re.sub('--+', '-', name)
    return name


def sort_list(sort_key, sort_direction, list_data):
    reverse = False if sort_direction == 'asc' else True
    if sort_key == 'rank':
        return sorted(list_data, key=lambda x: x['rank'], reverse=reverse)
    elif sort_key == 'added':
        return sorted(list_data, key=lambda x: x['listed_at'], reverse=reverse)
    elif sort_key == 'title':
        return sorted(list_data, key=lambda x: title_key(x[x['type']].get('title')), reverse=reverse)
    elif sort_key == 'released':
        return sorted(list_data, key=lambda x: _released_key(x[x['type']]), reverse=reverse)
    elif sort_key == 'runtime':
        return sorted(list_data, key=lambda x: x[x['type']].get('runtime', 0), reverse=reverse)
    elif sort_key == 'popularity':
        return sorted(list_data, key=lambda x: x[x['type']].get('votes', 0), reverse=reverse)
    elif sort_key == 'percentage':
        return sorted(list_data, key=lambda x: x[x['type']].get('rating', 0), reverse=reverse)
    elif sort_key == 'votes':
        return sorted(list_data, key=lambda x: x[x['type']].get('votes', 0), reverse=reverse)
    else:
        return list_data

def _released_key(item):
    if 'released' in item:
        return item['released']
    elif 'first_aired' in item:
        return item['first_aired']
    else:
        return 0

def getActivity():
    try:
        i = getTraktAsJson('/sync/last_activities')

        activity = []
        activity.append(i['movies']['collected_at'])
        activity.append(i['episodes']['collected_at'])
        activity.append(i['movies']['watchlisted_at'])
        activity.append(i['shows']['watchlisted_at'])
        activity.append(i['seasons']['watchlisted_at'])
        activity.append(i['episodes']['watchlisted_at'])
        activity.append(i['lists']['updated_at'])
        activity.append(i['lists']['liked_at'])
        activity = [int(iso_2_utc(i)) for i in activity]
        activity = sorted(activity, key=int)[-1]

        return activity
    except:
        pass


def getWatchedActivity():
    try:
        i = getTraktAsJson('/sync/last_activities')
        activity = []
        activity.append(i['movies']['watched_at'])
        activity.append(i['episodes']['watched_at'])
        activity = [int(iso_2_utc(i)) for i in activity]
        activity = sorted(activity, key=int)[-1]

        return activity
    except:
        pass


def syncMovies():
    try:
        if getTraktCredentialsInfo() == False: return
        indicators = getTraktAsJson('/users/me/watched/movies')
        return indicators
    except:
        pass

def watchedShows():
    try:
        if getTraktCredentialsInfo() == False: return
        indicators = getTraktAsJson('/users/hidden/progress_watched?limit=1000&type=show')
        return indicators
    except:
        pass
    
def syncTVShows():
    try:
        if getTraktCredentialsInfo() == False: return
        indicators = getTraktAsJson('/users/me/watched/shows?extended=full')
        return indicators
    except:
        pass


def syncSeason(imdb):
    try:
        if getTraktCredentialsInfo() == False: return
        indicators = getTraktAsJson('/shows/%s/progress/watched?specials=false&hidden=false' % imdb)
        indicators = indicators['seasons']
        indicators = [(i['number'], [x['completed'] for x in i['episodes']]) for i in indicators]
        indicators = ['%01d' % int(i[0]) for i in indicators if not False in i[1]]
        return indicators
    except:
        pass


def markMovieAsWatched(imdb):
    if not imdb.startswith('tt'): imdb = 'tt' + imdb
    return __getTrakt('/sync/history', {"movies": [{"ids": {"imdb": imdb}}]})[0]


def markMovieAsNotWatched(imdb):
    if not imdb.startswith('tt'): imdb = 'tt' + imdb
    return __getTrakt('/sync/history/remove', {"movies": [{"ids": {"imdb": imdb}}]})[0]


def markTVShowAsWatched(tvdb):
    return __getTrakt('/sync/history', {"shows": [{"ids": {"tvdb": tvdb}}]})[0]


def markTVShowAsNotWatched(tvdb):
    return __getTrakt('/sync/history/remove', {"shows": [{"ids": {"tvdb": tvdb}}]})[0]


def markEpisodeAsWatched(tvdb, season, episode):
    season, episode = int('%01d' % int(season)), int('%01d' % int(episode))
    return __getTrakt('/sync/history', {"shows": [{"seasons": [{"episodes": [{"number": episode}], "number": season}], "ids": {"tvdb": tvdb}}]})[0]


def markEpisodeAsNotWatched(tvdb, season, episode):
    season, episode = int('%01d' % int(season)), int('%01d' % int(episode))
    return __getTrakt('/sync/history/remove', {"shows": [{"seasons": [{"episodes": [{"number": episode}], "number": season}], "ids": {"tvdb": tvdb}}]})[0]

def addShowToWtachlist(imdb):
    if not imdb.startswith('tt'): imdb = 'tt' + imdb
    #return __getTrakt('/sync/watchlist', {"shows": [{"ids": {"imdb": imdb}, "seasons": [{"number": 1}]}]})[0]
    return __getTrakt('/sync/watchlist', {"shows": [{"ids": {"imdb": imdb}}]})[0]
    
    
def getMovieTranslation(id, lang, full=False):
    url = '/movies/%s/translations/%s' % (id, lang)
    try:
        item = getTraktAsJson(url)[0]
        return item if full else item.get('title')
    except:
        pass


def getTVShowTranslation(id, lang, season=None, episode=None, full=False):
    if season and episode:
        url = '/shows/%s/seasons/%s/episodes/%s/translations/%s' % (id, season, episode, lang)
    else:
        url = '/shows/%s/translations/%s' % (id, lang)

    try:
        item = getTraktAsJson(url)[0]
        return item if full else item.get('title')
    except:
        pass


def getMovieAliases(id):
    try: return getTraktAsJson('/movies/%s/aliases' % id)
    except: return []


def getTVShowAliases(id):
    try: return getTraktAsJson('/shows/%s/aliases' % id)
    except: return []


def getMovie(id, full=True):
    try:
        url = '/movies/%s' % id
        if full: url += '&extended=full'
        return getTraktAsJson(url)
    except:
        return


def getTVShowSummary(id, full=True):
    try:
        url = '/shows/%s' % id
        if full: url += '?extended=full'
        return getTraktAsJson(url)
    except:
        return


def getPeople(id, content_type, full=True):
    try:
        url = '/%s/%s/people' % (content_type, id)
        if full: url += '?extended=full'
        return getTraktAsJson(url)
    except:
        return

def SearchAll(title, year, full=True):
    try:
        return SearchMovie(title, year, full) + SearchTVShow(title, year, full)
    except:
        return

def SearchMovie(title, year, full=True):
    try:
        url = '/search/movie?query=%s' % urllib.quote_plus(title)

        if year: url += '&year=%s' % year
        if full: url += '&extended=full'
        return getTraktAsJson(url)
    except:
        return

def SearchTVShow(title, year, full=True):
    try:
        url = '/search/show?query=%s' % urllib.quote_plus(title)

        if year: url += '&year=%s' % year
        if full: url += '&extended=full'
        return getTraktAsJson(url)
    except:
        return

def IdLookup(content, type, type_id):
    try:
        r = getTraktAsJson('/search/%s/%s?type=%s' % (type, type_id, content))
        return r[0].get(content, {}).get('ids', [])
    except:
        return {}

def getGenre(content, type, type_id):
    try:
        r = '/search/%s/%s?type=%s&extended=full' % (type, type_id, content)
        r = getTraktAsJson(r)
        r = r[0].get(content, {}).get('genres', [])
        return r
    except:
        return []
        
def iso_2_utc(iso_ts):
    if not iso_ts or iso_ts is None: return 0
    delim = -1
    if not iso_ts.endswith('Z'):
        delim = iso_ts.rfind('+')
        if delim == -1: delim = iso_ts.rfind('-')

    if delim > -1:
        ts = iso_ts[:delim]
        sign = iso_ts[delim]
        tz = iso_ts[delim + 1:]
    else:
        ts = iso_ts
        tz = None

    if ts.find('.') > -1:
        ts = ts[:ts.find('.')]

    try: d = datetime.datetime.strptime(ts, '%Y-%m-%dT%H:%M:%S')
    except TypeError: d = datetime.datetime(*(time.strptime(ts, '%Y-%m-%dT%H:%M:%S')[0:6]))

    dif = datetime.timedelta()
    if tz:
        hours, minutes = tz.split(':')
        hours = int(hours)
        minutes = int(minutes)
        if sign == '-':
            hours = -hours
            minutes = -minutes
        dif = datetime.timedelta(minutes=minutes, hours=hours)
    utc_dt = d - dif
    epoch = datetime.datetime.utcfromtimestamp(0)
    delta = utc_dt - epoch
    try: seconds = delta.total_seconds()  # works only on 2.7
    except: seconds = delta.seconds + delta.days * 24 * 3600  # close enough
    return seconds

def byteify(data, ignore_dicts=False):
    if not py3:
      if isinstance(data, unicode):
          return data.encode('utf-8')
    if isinstance(data, list):
        return [byteify(item, ignore_dicts=True) for item in data]
    if isinstance(data, dict) and not ignore_dicts:
        try: dataiter = data.iteritems()
        except: dataiter = data.items()
        return dict([(byteify(key, ignore_dicts=True), byteify(value, ignore_dicts=True)) for key, value in dataiter])
    return data
    
def title_key(title):
    try:
        if title is None: title = ''
        articles_en = ['the', 'a', 'an']
        articles_de = ['der', 'die', 'das']
        articles = articles_en + articles_de

        match = re.match('^((\w+)\s+)', title.lower())
        if match and match.group(2) in articles:
            offset = len(match.group(1))
        else:
            offset = 0
        return title[offset:]
    except:
        return title

def regex_tvshow(label):
    regexes = [
        # ShowTitle.S01E09; s01e09, s01.e09, s01-e09
        '(.*?)[._ -]s([0-9]+)[._ -]*e([0-9]+)',
        '(.*?)[._ -]([0-9]+)x([0-9]+)',  # Showtitle.1x09
        '(.*?)[._ -]([0-9]+)([0-9][0-9])',  # ShowTitle.109
        # ShowTitle.Season 01 - Episode 02, Season 01 Episode 02
        '(.*?)[._ -]?season[._ -]*([0-9]+)[._ -]*-?[._ -]*episode[._ -]*([0-9]+)',
        # ShowTitle_[s01]_[e01]
        '(.*?)[._ -]\[s([0-9]+)\][._ -]*\[[e]([0-9]+)',
        '(.*?)[._ -]s([0-9]+)[._ -]*ep([0-9]+)']  # ShowTitle - s01ep03, ShowTitle - s1ep03

    for regex in regexes:
        match = re.search(regex, label, re.I)
        if match:
            show_title, season, episode = match.groups()
            if show_title:
                show_title = re.sub('[\[\]_\(\).-]', ' ', show_title)
                show_title = re.sub('\s\s+', ' ', show_title)
                show_title = show_title.strip()
            return show_title, int(season), int(episode)

    return '', -1, -1
        
def getDataforTrakt(params, data=None):
    if not data: data = {}
    if type(params) is dict:
        params=params
    else: 
        try: params = json.loads(params)
        except: params = eval(params)

    # ===== MODIFICARE CHEIE =====
    # Verificăm dacă datele vin în formatul imbricat (cu 'info') sau plat (direct de la serviciu)
    if 'info' in params and isinstance(params.get('info'), dict):
        # Cazul clasic, din interiorul addon-ului
        infos = params.get('info')
    else:
        # Cazul nou, direct de la serviciu (un dicționar plat)
        infos = params
    # ===== SFÂRȘIT MODIFICARE =====
    
    # Verificăm și dacă `infos` este valid înainte de a continua
    if not infos:
        log('###getDataforTrakt error: Nu s-au putut extrage metadate valide.')
        return None # Returnăm explicit None

    season = infos.get('Season') or infos.get('season')
    episode = infos.get('Episode') or infos.get('episode')
    try:
        if season: season = int(season)
    except: pass
    try:
        if episode: episode = int(episode)
    except: pass
    showtitle = infos.get('TVshowtitle') or infos.get('TVShowTitle') or infos.get('showname')
    year = infos.get('Year') or infos.get('year')
    title = infos.get('Title') or infos.get('title')
    try:
        from resources.lib import PTN
        nameorig = re.sub('\[COLOR.+?\].+?\[/COLOR\]|\[.*?\]', '', title)
        nameorig = replaceHTMLCodes(nameorig)
        parsed = PTN.parse(nameorig)
        title = parsed.get('title') or nameorig
        year = year or str(parsed.get('year')) or ''
        season = season or parsed.get('season')
        episode = episode or parsed.get('episode')
        if year == 'None': year = ''
        if year:
            try: year = int(year)
            except: pass
        if season and episode:
            if not showtitle: showtitle = title
            if showtitle:
                data['show'] = {"title": showtitle}
                if year: data['show']['year'] = year
                season = int(season)
                episode = int(episode)
                data['episode'] = {"season": season, "number": episode}
        elif year and not episode and not showtitle:
            data['movie'] = {"title": title}
            if year: data['movie']['year'] = year
        elif showtitle:
            title, season, episode = regex_tvshow(showtitle)
            if season and episode:
                data['show'] = {"title": showtitle}
                if year: data['show']['year'] = year
                data['episode'] = {"season": season, "number": episode}
        elif title and not showtitle and not season and not episode:
            data['movie'] = {"title": title}
            if year: data['movie']['year'] = year
    except BaseException as e:
        log('###getDataforTrakt error: %s' % str(e))
        pass
    
    # Returnam datele doar daca am reusit sa identificam un film sau un serial
    if 'movie' in data or 'show' in data:
        return data
    else:
        log('###getDataforTrakt warning: Nu s-a putut identifica un film sau serial din metadatele: %s' % str(infos))
        return None

def getUserLists(username):
    try:
        if not username: return None
        url = '/users/%s/lists' % username
        return getTraktAsJson(url)
    except:
        log("### [Trakt]: Eroare la preluarea listelor pentru %s" % username)
        return None

def getListItems(username, list_id, page=1, limit=30):
    try:
        if not username or not list_id: return None
        # Am adaugat parametrii page si limit la URL-ul API
        url = '/users/%s/lists/%s/items?extended=full&page=%s&limit=%s' % (username, list_id, page, limit)
        return getTraktAsJson(url)
    except:
        log("### [Trakt]: Eroare la preluarea itemilor pentru lista %s, pagina %s" % (list_id, page))
        return None
