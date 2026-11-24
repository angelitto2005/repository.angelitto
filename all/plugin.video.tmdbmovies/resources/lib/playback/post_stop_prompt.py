"""Dialogurile de dupa stop (binge + rating), aratate de service, nu de invocarea de play.

Invocarea de play este singura pe care Kodi o asteapta la finalul scriptului
("CPythonInvoker ... waiting on thread"). Un dialog lasat deschis acolo tinea
invocarea atita cit statea omul in el - si, la inchiderea Kodi cu dialogul pe
ecran, aparea si "script didn't stop in 5 seconds". De aceea invocarea nu mai
deschide niciun dialog: scrie o cerere (fisier JSON + o proprietate ca semnal)
si pleaca. Dialogul il arata service-ul, care traieste oricum cit ruleaza Kodi -
acelasi aranjament ca monitorul din Lucent, doar ca acolo playerul ruleaza chiar
in service, deci nu are nevoie de cerere.

Reguli:
  * un singur prompt o data (`post_stop_prompt_open` e luat inainte de dialog);
  * o cerere mai veche de MAX_AGE secunde e ignorata - daca service-ul a lipsit
    la stop, nu are rost sa sara un dialog peste 10 minute;
  * dialogul asteapta stingerea `stop_refresh_pending`, ca safety pass-ul din
    invocare sa isi faca refreshul de lista primul (altfel il vede ca modal si
    il amina, lasind lista veche);
  * `binge_open` (citit de watched_provider ca garda de randare) e stins de aici
    la final, nu de invocare.
"""
import json
import os
import threading
import time

import xbmc
import xbmcgui

from resources.lib.core.config import ADDON, ADDON_DATA_DIR
from resources.lib.core.log_safe import clean as _log_clean

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

PROMPT_FILE = 'post_stop_prompt.json'
NUDGE_PROP = 'tmdbmovies.post_stop_prompt'       # invocarea -> service
OPEN_PROP = 'tmdbmovies.post_stop_prompt_open'   # un dialog e pe ecran (valoare = momentul)
REFRESH_PROP = 'tmdbmovies.stop_refresh_pending'  # safety pass-ul din invocare
BINGE_PROP = 'tmdbmovies.binge_open'             # garda citita de watched_provider

MAX_AGE = 30.0        # cerere mai veche = ignorata
REFRESH_WAIT = 8.0    # cit asteptam refreshul de lista inainte de dialog
OPEN_STALE = 300.0    # un "dialog deschis" mai vechi de atit e o proprietate ramasa
POLL_SECONDS = 1.0

_monitor = None
_running = {'flag': False}


def _log(message):
    try:
        xbmc.log('[TMDb Movies] [POST-STOP] %s' % _log_clean(str(message)), xbmc.LOGINFO)
    except Exception:
        pass


def _path():
    try:
        if xbmcvfs and not xbmcvfs.exists(ADDON_DATA_DIR):
            xbmcvfs.mkdirs(ADDON_DATA_DIR)
    except Exception:
        pass
    return os.path.join(ADDON_DATA_DIR, PROMPT_FILE)


def submit(binge=None, rating=None):
    """Scrie cererea pentru service. Apelat din invocarea de play, dupa stop."""
    if not binge and not rating:
        return False
    path = _path()
    try:
        payload = {'at': time.time(), 'binge': binge, 'rating': rating}
        temp = path + '.tmp'
        with open(temp, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle)
        os.replace(temp, path)          # atomic: service-ul nu citeste un fisier pe jumatate
        xbmcgui.Window(10000).setProperty(NUDGE_PROP, str(payload['at']))
        _log('cerere scrisa (binge=%s rating=%s)' % (bool(binge), bool(rating)))
        return True
    except Exception as error:
        _log('cerere esuata: %s' % type(error).__name__)
        try:
            os.remove(path)
        except Exception:
            pass
        return False


def _read_and_remove(path):
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            return json.load(handle)
    except Exception:
        return None
    finally:
        try:
            os.remove(path)
        except Exception:
            pass


def start():
    """Porneste bucla de service. Idempotent."""
    global _monitor
    if _monitor is not None:
        return False
    try:
        _monitor = xbmc.Monitor()
        threading.Thread(target=_loop, daemon=True).start()
        _log('bucla pornita in service')
        return True
    except Exception as error:
        _log('bucla nu a pornit: %s' % type(error).__name__)
        return False


def _loop():
    while not _monitor.abortRequested():
        try:
            _tick()
        except Exception as error:
            _log('eroare in bucla: %s' % type(error).__name__)
        if _monitor.waitForAbort(POLL_SECONDS):
            break


def _tick():
    window = xbmcgui.Window(10000)
    if not window.getProperty(NUDGE_PROP):
        return
    # Semnalul se stinge INAINTE de citire: un singur consumator, iar o eroare
    # mai jos nu lasa semnalul aprins pentru totdeauna.
    window.clearProperty(NUDGE_PROP)
    payload = _read_and_remove(_path())
    reason = None
    try:
        open_since = float(window.getProperty(OPEN_PROP) or 0)
    except Exception:
        open_since = 0.0
    if _running['flag'] or (open_since and time.time() - open_since < OPEN_STALE):
        reason = 'un dialog e deja pe ecran'
    elif not payload:
        reason = 'cerere lipsa'
    else:
        try:
            age = time.time() - float(payload.get('at') or 0)
        except Exception:
            age = MAX_AGE + 1
        if age > MAX_AGE:
            reason = 'cerere veche (%.0fs)' % age
        elif not (payload.get('binge') or payload.get('rating')):
            reason = 'cerere goala'
    if reason:
        _log('prompt sarit (%s)' % reason)
        # Invocarea nu mai stinge garda cind a trimis o cerere; daca cererea
        # moare aici, o stingem noi, altfel watched_provider nu mai randeaza
        # nimic 120s.
        try:
            window.clearProperty(BINGE_PROP)
        except Exception:
            pass
        return
    _running['flag'] = True
    try:
        window.setProperty(OPEN_PROP, str(time.time()))
    except Exception:
        pass
    threading.Thread(target=_run, args=(payload,), daemon=True).start()


def _run(payload):
    try:
        if payload.get('binge') and _run_binge(payload['binge']):
            return          # a ales episodul urmator: rating-ul nu se mai pune
        if payload.get('rating'):
            _run_rating(payload['rating'])
    except Exception as error:
        _log('prompt esuat: %s' % type(error).__name__)
    finally:
        _running['flag'] = False
        try:
            window = xbmcgui.Window(10000)
            window.clearProperty(OPEN_PROP)
            window.clearProperty(BINGE_PROP)
        except Exception:
            pass


def _wait_for_refresh():
    """Safety pass-ul din invocare isi face refreshul de lista primul.

    El isi ia singur bugetul POST_STOP de la stop. Cit timp `stop_refresh_pending`
    e sus, un dialog de-al nostru ar fi vazut ca modal si pass-ul ar amina
    refreshul - adica lista ar ramine veche dupa ce se inchide dialogul.
    """
    deadline = time.time() + REFRESH_WAIT
    while time.time() < deadline:
        try:
            if not xbmcgui.Window(10000).getProperty(REFRESH_PROP):
                return
        except Exception:
            return
        if _monitor is None or _monitor.abortRequested():
            return
        xbmc.sleep(200)


def _run_binge(info):
    """Arata dialogul de episod urmator; True daca a pornit ceva."""
    n_info = info.get('n_info') or {}
    if not n_info:
        return False
    # Import stringe modulele grele (player.py) - le are deja service-ul din
    # warm-import, iar daca nu, se platesc o singura data, in threadul asta.
    from resources.lib.playback.player import AutoPlayWindow, _show_modal_abortable
    from resources.lib.core.utils import plugin_url

    _wait_for_refresh()
    # Aceeasi garda ca inainte: nu deschidem peste un GUI care inca isi
    # re-initializeaza fereastra media. Bucla e plafonata (2s) si ruleaza in
    # service, deci nu mai tine nicio invocare.
    for _ in range(20):
        try:
            if not xbmc.getCondVisibility('System.HasModalDialog') \
                    and not xbmc.getCondVisibility('Container.IsUpdating'):
                break
        except Exception:
            break
        if _monitor is None or _monitor.abortRequested():
            return False
        xbmc.sleep(100)

    window = AutoPlayWindow('autoplay_dialog.xml', ADDON.getAddonInfo('path'),
                            'Default', '1080i', n_info=n_info)
    _show_modal_abortable(window)
    result = window.action_result
    try:
        del window
    except Exception:
        pass
    _log('binge: buton %s' % result)
    if result not in (1, 2):
        return False

    params = {
        'mode': 'sources', 'tmdb_id': info.get('tmdb_id'), 'type': 'tv',
        'season': str(n_info.get('season')), 'episode': str(n_info.get('episode')),
        'title': n_info.get('title'), 'tv_show_title': n_info.get('show_title'),
    }
    if result == 1:
        prev = info.get('prev') or {}
        params.update({
            'auto_play_next': 'true',
            'prev_quality': prev.get('quality', ''),
            'prev_group': prev.get('group', ''),
            'prev_is_sdr': 'true' if prev.get('is_sdr', True) else 'false',
            'prev_debrid': prev.get('debrid', ''),
            'prev_provider': prev.get('provider', ''),
            'prev_codec': prev.get('codec', ''),
            'prev_source': prev.get('source', ''),
            'prev_ctx': json.dumps(prev.get('ctx') or {}),
        })
    else:
        # "Choose Source" deschide fereastra surselor: fara no_auto intra
        # oricum pe autoplay si ignora alegerea.
        params['no_auto'] = '1'
    url = plugin_url(params)
    try:
        if xbmc.Player().isPlaying():
            xbmc.Player().stop()
            xbmc.sleep(500)
    except Exception:
        pass
    xbmc.executebuiltin('RunPlugin(%s)' % url)
    _log('binge: pornesc S%sE%s' % (params['season'], params['episode']))
    return True


def _run_rating(info):
    from resources.lib.api import tmdb_api

    _wait_for_refresh()
    tmdb_api.prompt_postwatch_rating(
        info.get('tmdb_id'), info.get('content_type'),
        info.get('season'), info.get('episode'), info.get('title') or '')
