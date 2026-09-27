# -*- coding: utf-8 -*-
"""
Watched Status Provider abstraction layer.
Dispatching intre Trakt si MDBList in functie de setarea watched_status_provider.
"""

import os
import threading
import xbmc
import xbmcvfs

from resources.lib.config import ADDON, ADDON_PATH, MDBLIST_API_URL, kodi_abort_requested

# =============================================================================
# REMAPARE ONE-TIME A INDEXULUI DE PROVIDER (v1 -> v2)
# =============================================================================
# Kodi salveaza un enum ca INDEX in lista de values. Ordinea veche (v1) era
# trakt=0, mdblist=1, simkl=2, punchplay=3, local=4; ordinea noua (v2) e
# local=0, trakt=1, mdblist=2, simkl=3, punchplay=4 (Local primul + default).
# Fara remapare, reordonarea ar schimba silenios providerul fiecarui user
# existent (0 = Trakt ar deveni Local). Remapul e DOAR o renumerotare: nu
# comuta pe nimeni, nu porneste sync-uri, nu da notificari.
# ATENTIE (downgrade): daca revii vreodata la fisierele vechi (v1), sterge manual
# provider_index_v2 din setarile addonului, altfel indicii ramin renumarati.
_PROVIDERS_V1 = ('trakt', 'mdblist', 'simkl', 'punchplay', 'local')
_provider_index_migrated = False          # memo de proces (hot path: o citire de atribut)
_provider_index_lock = threading.Lock()
_PROVIDER_INDEX_STAMP = 'provider_index_v2'
_PROVIDER_INDEX_CLAIM = 'tmdbmovies_provider_v2'   # claim cross-proces (Window 10000)
_PROVIDER_INDEX_CLAIM_STALE = 30.0                 # secunde: sub asta, alt proces chiar lucreaza


def _provider_setting_was_saved():
    """True doar daca profilul are EXPLICIT id-ul in settings.xml (alegere anterioara).

    Pe o instalare noua getSetting cade pe default-ul din resources/settings.xml ('0'),
    imposibil de distins de un user v1 cu Trakt (tot 0) -> fara testul asta am muta
    TOATE instalariile noi pe Trakt. Fail-safe: daca nu pot dovedi o alegere
    anterioara, NU renumar (default-ul nou e oricum Kodi (Local))."""
    try:
        from resources.lib.config import _get_settings_dict
        return 'watched_status_provider' in _get_settings_dict()
    except Exception:
        return False


def _provider_claim_state(_win):
    """'' (liber) | 'done' | timestamp (secunde) al claim-ului in curs."""
    if _win is None:
        return ''
    try:
        return _win.getProperty(_PROVIDER_INDEX_CLAIM) or ''
    except Exception:
        return ''


def _provider_claim_age(_claim):
    """Varsta claim-ului in secunde; None daca valoarea nu e un timestamp."""
    try:
        import time as _t
        return _t.time() - float(_claim)
    except Exception:
        return None


def _provider_index_remap_once():
    """Un singur pas de remapare v1 -> v2 (vezi contractul de mai sus)."""
    # 1. Stampila persistenta (supravietuieste restartului) sau claim-ul 'done' din
    #    sesiunea curenta (RAM, Window 10000) -> deja remapat.
    if (ADDON.getSetting(_PROVIDER_INDEX_STAMP) or '') == 'true':
        return
    _win = None
    try:
        import xbmcgui
        _win = xbmcgui.Window(10000)
    except Exception:
        _win = None
    _claim = _provider_claim_state(_win)
    if _claim == 'done':
        return
    # 2. Alt proces remapeaza chiar acum (claim proaspat): astept max 10 x 150ms ca
    #    sa prind valoarea finala, apoi il las pe el (nu dublez remapul).
    if _claim:
        _age = _provider_claim_age(_claim)
        if _age is not None and _age < _PROVIDER_INDEX_CLAIM_STALE:
            for _ in range(10):
                try:
                    xbmc.sleep(150)
                except Exception:
                    pass
                if _provider_claim_state(_win) == 'done':
                    return
                if (ADDON.getSetting(_PROVIDER_INDEX_STAMP) or '') == 'true':
                    return
            return
    # 3. Fara alegere anterioara salvata (instalare noua / setting nefolosit): valoarea
    #    vine din default-ul XML, care e deja Kodi (Local) -> doar stampila.
    if not _provider_setting_was_saved():
        _provider_index_stamp(_win)
        _provider_index_claim_done(_win)
        return
    # 4. Renumar. Stampila se scrie PRIMA: un crash intre cele doua setSetting-uri
    #    lasa valoarea veche interpretata in schema noua (o fereastra de doua scrieri,
    #    acceptata deliberat) - ordinea inversa ar DUBLA remaparea (0 -> 2: Trakt ar
    #    ajunge Simkl). Claim-ul se pune inainte, ca alt proces sa astepte, nu sa citeasca
    #    o valoare pe jumatate mutata.
    if _win is not None:
        try:
            import time as _t
            _win.setProperty(_PROVIDER_INDEX_CLAIM, str(_t.time()))
        except Exception:
            pass
    try:
        _provider_index_stamp(_win)
        _provider_index_renumber()
    finally:
        # 'done' abia ACUM: un alt proces care astepta trebuie sa vada valoarea deja
        # renumarata, nu stampila scrisa peste valoarea veche.
        _provider_index_claim_done(_win)


def _provider_index_renumber():
    """Traducerea propriu-zisa a numarului: v1 -> v2 (Local pentru gunoi)."""
    try:
        _raw = ADDON.getSetting('watched_status_provider') or ''
    except Exception:
        _raw = ''
    try:
        _old = int(_raw)
    except Exception:
        _old = None
    if _old is not None and 0 <= _old <= 4:
        _name = _PROVIDERS_V1[_old]
    else:
        _name = 'local'
        # Diagnostic pentru suport: valoare corupta (non-numerica) SAU in afara
        # intervalului -> Kodi (Local). Se scrie o singura data (remapul ruleaza o
        # data). Valoarea goala e "niciodata ales" (cazul normal pe profilele noi,
        # unde guardul N1 a sarit oricum peste remapare) -> fara zgomot in log.
        if _old is not None or str(_raw).strip() != '':
            try:
                xbmc.log('[TMDb Movies] Provider index %s: %r -> Kodi (Local).'
                         % ('out of range' if _old is not None else 'corrupt', _raw),
                         xbmc.LOGWARNING)
            except Exception:
                pass
    try:
        _new = PROVIDERS_ALL.index(_name)
    except Exception:
        _new = 0
    if _old == _new:
        return
    try:
        ADDON.setSetting('watched_status_provider', str(_new))
    except Exception as _e:
        try:
            xbmc.log('[TMDb Movies] Provider index remap write failed: %s' % _e, xbmc.LOGWARNING)
        except Exception:
            pass
        return
    try:
        xbmc.log('[TMDb Movies] Provider index remap: %s -> %s (Kodi (Local)=0).' % (_old, _new),
                 xbmc.LOGINFO)
    except Exception:
        pass


def _provider_index_stamp(_win):
    """Stampila persistenta (supravietuieste restartului lui Kodi) - se scrie PRIMA."""
    try:
        ADDON.setSetting(_PROVIDER_INDEX_STAMP, 'true')
    except Exception:
        pass


def _provider_index_claim_done(_win):
    """Marcheaza claim-ul din sesiunea curenta ca terminat."""
    if _win is not None:
        try:
            _win.setProperty(_PROVIDER_INDEX_CLAIM, 'done')
        except Exception:
            pass


def _migrate_provider_index():
    """Remapul lazy, o singura data per proces (si per profil).

    NU se apeleaza explicit nicaieri: _get_provider_raw() e singurul cititor al
    setarii si e folosit de monitor la boot (inainte de orice click al userului)
    plus de orice plugin/context script -> acoperire totala, cost zero dupa prima
    citire (un boolean de modul). Lock-ul se ia doar pe miss, niciodata pe hot path."""
    global _provider_index_migrated
    if _provider_index_migrated:
        return
    with _provider_index_lock:
        if _provider_index_migrated:
            return
        try:
            _provider_index_remap_once()
        except Exception as _e:
            try:
                xbmc.log('[TMDb Movies] Provider index remap failed: %s' % _e, xbmc.LOGWARNING)
            except Exception:
                pass
        _provider_index_migrated = True


def _get_provider_raw():
    # Ordinea de pe disc e cea din _PROVIDERS_V1 pana la remapul one-time (lazy, aici).
    _migrate_provider_index()
    # Valoare lipsa / non-numerica / in afara intervalului -> 'local' (indexul 0):
    # singurul provider fara retea, deci nu poate ramane mort (e si default-ul din
    # settings.xml). Golul cade pe ramura de exceptie, nu pe '0' = Trakt + pop-up.
    try:
        idx = int(ADDON.getSetting('watched_status_provider') or '')
    except Exception:
        idx = 0
    return PROVIDERS_ALL[idx] if 0 <= idx <= 4 else 'local'

def clear_cache():
    """No-op pastrat pentru compatibilitate (nu mai exista cache de invalidat)."""
    pass

def _invalidate_fast_cache():
    """Invalideaza listele din fast cache (RAM) dupa o schimbare de watched status.

    Doar LISTELE: metadatele (titluri/ploturi/sezoane) nu se schimba cind marchezi
    un episod vazut, iar pastrarea lor face refresh-ul de Up Next instant in loc
    de re-constructie completa din TMDb (rotita de ~5s la revenirea din player).
    """
    try:
        from resources.lib.cache import clear_list_fast_cache
        clear_list_fast_cache()
    except:
        pass

def _on_home_widget():
    try:
        return 'tmdbmovies' not in xbmc.getInfoLabel('Container.PluginName')
    except:
        return True

def widget_refresh():
    try:
        xbmc.executebuiltin('UpdateLibrary(video,special://skin/foo)')
    except:
        pass

def refresh_ui():
    try:
        if _on_home_widget():
            widget_refresh()
        else:
            xbmc.executebuiltin('Container.Refresh')
    except:
        pass

def browse_command(url):
    try:
        if _on_home_widget():
            return 'ActivateWindow(Videos,%s,return)' % url
    except:
        pass
    return 'Container.Update(%s)' % url

# Ordinea canonica din settings.xml (enum watched_status_provider):
# local=0, trakt=1, mdblist=2, simkl=3, punchplay=4.
# NU se schimba niciodata fara o remapare one-time (vezi _migrate_provider_index):
# .index() scrie inapoi in setarea Kodi, deci ordinea asta E contractul cu discul.
PROVIDERS_ALL = ('local', 'trakt', 'mdblist', 'simkl', 'punchplay')
# Tintele ONLINE (fanout), derivate - fara al doilea tuplu hardcodat.
PROVIDERS_ONLINE = tuple(p for p in PROVIDERS_ALL if p != 'local')

_WATCHED_MARK_PROVIDERS = PROVIDERS_ONLINE  # tintte ONLINE (fanout)
# NOTE fanout: local nu e in _WATCHED_MARK_PROVIDERS (nu e tintta de retea). Cind
# activul e local, scrierea merge pe traseul "active provider" din dispatch_mark_*;
# cind activul e online si userul bifeaza watched_mark_local in Custom selection,
# dispatch_mark_* adauga local explicit (util pt. migrare ulterioara spre Local).

# Culorile providerilor vin din config (sursa unica de adevar); PUNCHPLAY_COLOR
# rămâne în config pentru compatibilitate cu importurile existente.
from resources.lib.config import PROVIDER_COLORS as _CFG_PROVIDER_COLORS, PROVIDER_ICONS as _CFG_PROVIDER_ICONS, provider_title as _cfg_provider_title

_WATCHED_MARK_COLORS = {p: _CFG_PROVIDER_COLORS[p] for p in ('trakt', 'mdblist', 'simkl', 'punchplay', 'local')}

_WATCHED_MARK_LABELS = {
    'trakt': _cfg_provider_title('trakt'),
    'mdblist': _cfg_provider_title('mdblist'),
    'simkl': _cfg_provider_title('simkl'),
    'punchplay': _cfg_provider_title('punchplay'),
    'local': _cfg_provider_title('local'),
}

_WATCHED_MARK_TOGGLES = {
    'trakt': 'watched_mark_trakt',
    'mdblist': 'watched_mark_mdblist',
    'simkl': 'watched_mark_simkl',
    'punchplay': 'watched_mark_punchplay',
    'local': 'watched_mark_local',
}


def _connected_mark_providers():
    connected = ['local']  # local: mereu conectat (nicio retea, zero pop-up)
    try:
        from resources.lib import trakt_api
        if trakt_api.get_trakt_token():
            connected.append('trakt')
    except Exception:
        pass
    try:
        from resources.lib import mdblist
        if mdblist.is_authenticated():
            connected.append('mdblist')
    except Exception:
        pass
    try:
        from resources.lib import simkl
        if simkl.is_authenticated():
            connected.append('simkl')
    except Exception:
        pass
    try:
        from resources.lib import punchplay
        if punchplay.is_authenticated():
            connected.append('punchplay')
    except Exception:
        pass
    return connected


def _mark_targets():
    try:
        mode = ADDON.getSetting('watched_mark_mode') or '0'
    except Exception:
        mode = '0'
    if mode not in ('1', '2'):
        return None
    connected = _connected_mark_providers()
    if mode == '1':
        targets = list(connected)
    else:
        targets = []
        for prov in connected:
            try:
                if ADDON.getSetting(_WATCHED_MARK_TOGGLES[prov]) == 'true':
                    targets.append(prov)
            except Exception:
                pass
    prov = _get_provider_raw()
    if prov in connected and prov not in targets:
        targets.append(prov)
    # Ordine stabila; 'local' poate fi in targets (scris pe traseu separat in dispatch,
    # nu prin fanout-ul online).
    return [p for p in PROVIDERS_ALL if p in targets]


_PROVIDER_LABELS = {'trakt': 'Trakt', 'mdblist': 'MDBList', 'simkl': 'Simkl', 'punchplay': 'PunchPlay', 'local': 'Kodi (Local)'}
_PROVIDER_COLORS = {'trakt': 'pink', 'mdblist': 'lightskyblue', 'simkl': 'mediumpurple', 'punchplay': 'FFFF6600', 'local': 'FFF70D1A'}


def _run_provider_auth(prov):
    try:
        if prov == 'trakt':
            from resources.lib.trakt_api import trakt_auth
            trakt_auth()
        elif prov == 'mdblist':
            from resources.lib.mdblist_api import mdblist_auth
            mdblist_auth()
        elif prov == 'simkl':
            from resources.lib.simkl_api import simkl_auth
            simkl_auth()
        elif prov == 'punchplay':
            from resources.lib.punchplay_api import punchplay_auth
            punchplay_auth()
        else:
            return
    except Exception:
        pass


def _prompt_enabled():
    """Opt-out pentru dialogul de provider deconectat. Default = True (comportament actual)."""
    try:
        return (ADDON.getSetting('watched_provider_prompt') or 'true') != 'false'
    except Exception:
        return True


def ensure_active_provider(notify=True, interactive=True):
    # Local: mereu conectat -> zero pop-up la boot. Fix-ul pentru userii fara cont.
    if _get_provider_raw() == 'local':
        return False
    try:
        prov = _get_provider_raw()
    except Exception:
        return False
    try:
        connected = _connected_mark_providers()
    except Exception:
        return False
    if prov in connected:
        return False
    # Tinta e MEREU Kodi (Local), pe ambele cai: dialog (alegerea userului) si
    # silentioasa (avertizarea oprita). Regula: addonul nu muta NICIODATA singur
    # marcajele pe alt cont - Local nu are cont si nu poate ramane mort.
    fallback = 'local'
    # True = userul a ales reconectarea, dar ea a picat sau a fost anulata
    # (Back/Esc in fereastra QR). Atunci NU ramane pe providerul deconectat:
    # cade mai jos, pe Local, ca in restul cazurilor.
    _reconnect_failed = False
    _prompt = _prompt_enabled()
    xbmc.log('[TMDb Movies] Provider check: activ=%s conectati=%s prompt=%s'
             % (prov, ','.join(connected) or '-', 'on' if _prompt else 'off'), xbmc.LOGINFO)
    if interactive and _prompt:
        try:
            import xbmcgui
            dead_lbl = _PROVIDER_LABELS.get(prov, prov)
            dead_clr = _PROVIDER_COLORS.get(prov, 'yellow')
            new_lbl = _PROVIDER_LABELS.get(fallback, fallback)
            new_clr = _PROVIDER_COLORS.get(fallback, 'yellow')
            # Dialog nativ cu 2 optiuni: Yes = reconectare (QR), No/Back/Esc = Local.
            # yesno intoarce False si pe Back/Esc, deci Esc ajunge exact pe Local.
            heading = '[B][COLOR %s]%s[/COLOR][/B] [COLOR FFFF4444]is not connected[/COLOR]' % (dead_clr, dead_lbl)
            msg = ('In [B]Settings[/B] > [B]Accounts[/B] the active provider is set to '
                   '[B][COLOR %s]%s[/COLOR][/B], but it is [B][COLOR FFFF4444]not connected[/COLOR][/B].\n'
                   'Watched marks cannot be saved to it.\n'
                   '[COLOR FFCCCCFF]Connect it again, or switch to Kodi (Local)?[/COLOR]') % (dead_clr, dead_lbl)
            yes_lbl = '[COLOR %s]Connect %s now (QR)[/COLOR]' % (dead_clr, dead_lbl)
            no_lbl = '[COLOR %s]Switch to %s[/COLOR]' % (new_clr, new_lbl)
            dlg = xbmcgui.Dialog()
            try:
                _yes = dlg.yesno(heading, msg, nolabel=no_lbl, yeslabel=yes_lbl)
            except TypeError:
                _yes = dlg.yesno(heading, msg)
            if _yes:
                _run_provider_auth(prov)
                try:
                    reconnected = prov in _connected_mark_providers()
                except Exception:
                    reconnected = False
                if reconnected:
                    try:
                        # Indexul CANONIC (PROVIDERS_ALL), nu ordinea online: altfel
                        # 0 ar insemna Kodi (Local) in loc de providerul reconectat.
                        ADDON.setSetting('watched_status_provider', str(PROVIDERS_ALL.index(prov)))
                    except Exception:
                        return False
                    try:
                        _invalidate_fast_cache()
                    except Exception:
                        pass
                    if notify:
                        try:
                            xbmcgui.Dialog().notification('[B][COLOR FFFDBD01]Watched Provider[/COLOR][/B]',
                                                          f'Reconnected [B][COLOR {dead_clr}]{dead_lbl}[/COLOR][/B]',
                                                          os.path.join(ADDON_PATH, 'icon.png'), 5000, False)
                        except Exception:
                            pass
                    return True
                # Reconectarea a picat sau a fost anulata cu Back/Esc in fereastra QR.
                # NU ne oprim aici: providerul e inca deconectat, deci mai jos se
                # comuta pe Local (regula: niciodata raminem pe un provider mort).
                _reconnect_failed = True
        except Exception:
            pass
    try:
        ADDON.setSetting('watched_status_provider', str(PROVIDERS_ALL.index(fallback)))
    except Exception:
        return False
    try:
        _invalidate_fast_cache()
    except Exception:
        pass
    # Semnalizam TOTDEAUNA mutarea pe Local, inclusiv cu avertizarea oprita: comutarea
    # pe Local chiar inseamna "nu mai ai unde sincroniza", iar tacerea ar ascunde exact
    # consecinta (marcajele nu mai ajung in cont). Decizie asumata: bifa "Warn me..."
    # controleaza dialogul de la boot, nu informarea asta de o secunda.
    if notify:
        try:
            import xbmcgui
            dead_lbl = _PROVIDER_LABELS.get(prov, prov)
            dead_clr = _PROVIDER_COLORS.get(prov, 'yellow')
            new_lbl = _PROVIDER_LABELS.get(fallback, fallback)
            new_clr = _PROVIDER_COLORS.get(fallback, 'yellow')
            if _reconnect_failed:
                msg = (f'Reconnecting to [B][COLOR {dead_clr}]{dead_lbl}[/COLOR][/B] failed - '
                       f'active provider switched to [B][COLOR {new_clr}]{new_lbl}[/COLOR][/B].')
            else:
                msg = f'[B][COLOR {dead_clr}]{dead_lbl}[/COLOR][/B] disconnected, active provider switched to [B][COLOR {new_clr}]{new_lbl}[/COLOR][/B].'
            xbmcgui.Dialog().notification('[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]', msg, os.path.join(ADDON_PATH, 'icon.png'), 5000, False)
        except Exception:
            pass
    return True


def _split_colored(word, provs):
    n = len(provs)
    base, extra = divmod(len(word), n)
    out = ''
    pos = 0
    for i, p in enumerate(provs):
        ln = base + (1 if i < extra else 0)
        out += '[COLOR %s]%s[/COLOR]' % (_WATCHED_MARK_COLORS[p], word[pos:pos + ln])
        pos += ln
    return out


def mark_menu_label(is_watched):
    targets = _mark_targets()
    if targets is None:
        return None
    ordered = [p for p in _WATCHED_MARK_PROVIDERS if p in targets]
    if not ordered:
        return None
    if is_watched:
        return '[B][COLOR FFE41B17]Mark [/COLOR]%s[/B]' % _split_colored('Unwatched', ordered)
    return '[B][COLOR FF6AFB92]Mark [/COLOR]%s[/B]' % _split_colored('Watched', ordered)


def _fanout_mark(watched, tmdb_id, content_type, season, episode, providers, notify, sync_provider, do_refresh):
    targets = [p for p in _WATCHED_MARK_PROVIDERS if p in (providers or [])]
    if not targets:
        return []
    done = []
    lock = threading.Lock()

    def _one(prov):
        try:
            if watched:
                if prov == 'trakt':
                    from resources.lib.trakt_sync import mark_as_watched_internal
                    mark_as_watched_internal(tmdb_id, content_type, season, episode, notify=False, sync_trakt=sync_provider, refresh_ui=False)
                elif prov == 'mdblist':
                    from resources.lib.mdblist_sync import mark_as_watched_internal
                    mark_as_watched_internal(tmdb_id, content_type, season, episode, notify=False, sync_mdblist=sync_provider, refresh_ui=False)
                elif prov == 'simkl':
                    from resources.lib.simkl_sync import mark_as_watched_internal
                    mark_as_watched_internal(tmdb_id, content_type, season, episode, notify=False, sync_simkl=sync_provider, refresh_ui=False)
                else:
                    from resources.lib.punchplay_sync import mark_as_watched_internal
                    mark_as_watched_internal(tmdb_id, content_type, season, episode, notify=False, sync_punchplay=sync_provider, refresh_ui=False)
            else:
                if prov == 'trakt':
                    from resources.lib.trakt_sync import mark_as_unwatched_internal
                    mark_as_unwatched_internal(tmdb_id, content_type, season, episode, notify=False, sync_trakt=sync_provider, refresh_ui=False)
                elif prov == 'mdblist':
                    from resources.lib.mdblist_sync import mark_as_unwatched_internal
                    mark_as_unwatched_internal(tmdb_id, content_type, season, episode, notify=False, sync_mdblist=sync_provider, refresh_ui=False)
                elif prov == 'simkl':
                    from resources.lib.simkl_sync import mark_as_unwatched_internal
                    mark_as_unwatched_internal(tmdb_id, content_type, season, episode, notify=False, sync_simkl=sync_provider, refresh_ui=False)
                else:
                    from resources.lib.punchplay_sync import mark_as_unwatched_internal
                    mark_as_unwatched_internal(tmdb_id, content_type, season, episode, notify=False, sync_punchplay=sync_provider, refresh_ui=False)
            with lock:
                done.append(prov)
        except Exception:
            pass

    workers = [threading.Thread(target=_one, args=(p,), daemon=True) for p in targets]
    for t in workers:
        t.start()
    for t in workers:
        t.join(30)
    _refresh_tmdb_up_next(tmdb_id)
    _verify_tmdb_upnext_heal(tmdb_id)
    _invalidate_fast_cache()
    ordered_done = [p for p in _WATCHED_MARK_PROVIDERS if p in done]
    if notify:
        import xbmcgui
        _icon = os.path.join(ADDON_PATH, 'icon.png')
        if ordered_done:
            _names = ' + '.join(_WATCHED_MARK_LABELS[p] for p in ordered_done)
            if watched:
                _lbl = '[B]Mark %s[/B]' % _split_colored('Watched', ordered_done)
            else:
                _lbl = '[B]Mark %s[/B]' % _split_colored('Unwatched', ordered_done)
            xbmcgui.Dialog().notification('[B][COLOR yellow]All Providers[/COLOR][/B]', '%s on %s' % (_lbl, _names), _icon, 5000, False)
        else:
            xbmcgui.Dialog().notification('[B][COLOR yellow]All Providers[/COLOR][/B]', 'No provider updated', _icon, 5000, False)
    if do_refresh:
        refresh_ui()
    return ordered_done


def mark_watched_on_providers(tmdb_id, content_type, season=None, episode=None, providers=None, notify=True, sync_provider=True, do_refresh=True):
    return _fanout_mark(True, tmdb_id, content_type, season, episode, providers, notify, sync_provider, do_refresh)


def mark_unwatched_on_providers(tmdb_id, content_type, season=None, episode=None, providers=None, notify=True, sync_provider=True, do_refresh=True):
    return _fanout_mark(False, tmdb_id, content_type, season, episode, providers, notify, sync_provider, do_refresh)

def get_provider():
    return _get_provider_raw()

def is_trakt():
    return _get_provider_raw() == 'trakt'

def is_mdblist():
    return _get_provider_raw() == 'mdblist'

def is_simkl():
    return _get_provider_raw() == 'simkl'

def is_punchplay():
    return _get_provider_raw() == 'punchplay'

def is_local():
    return _get_provider_raw() == 'local'

def get_label():
    return {'trakt': 'Trakt', 'mdblist': 'MDBList', 'simkl': 'Simkl', 'punchplay': 'PunchPlay', 'local': 'Kodi (Local)'}[_get_provider_raw()]

def get_color():
    return _CFG_PROVIDER_COLORS.get(_get_provider_raw(), 'white')

def get_icon():
    return _CFG_PROVIDER_ICONS.get(_get_provider_raw()) or os.path.join(ADDON_PATH, 'resources', 'media', 'tmdb.png')

def get_status_setting():
    # local: id dummy citit cu fallback — afisam mereu "Connected (Local)", nu un setting real.
    return {'trakt': 'trakt_status', 'mdblist': 'mdblist_status', 'simkl': 'simkl_status', 'punchplay': 'punchplay_status', 'local': 'local_status_dummy'}.get(_get_provider_raw(), 'trakt_status')

def get_access_token_setting():
    return {'trakt': 'trakt_access_token', 'mdblist': 'mdblist_access_token', 'simkl': 'simkl_access_token', 'punchplay': 'punchplay_access_token', 'local': 'local_access_token_dummy'}.get(_get_provider_raw(), 'trakt_access_token')

def get_refresh_token_setting():
    return {'trakt': 'trakt_refresh_token', 'mdblist': 'mdblist_refresh_token', 'simkl': 'simkl_access_token', 'punchplay': 'punchplay_refresh_token', 'local': 'local_refresh_token_dummy'}.get(_get_provider_raw(), 'trakt_refresh_token')

def get_source_module():
    prov = _get_provider_raw()
    if prov == 'local':
        return __import__('resources.lib.local_sync', fromlist=['local_sync'])
    if prov == 'punchplay':
        return __import__('resources.lib.punchplay_sync', fromlist=['punchplay_sync'])
    if prov == 'simkl':
        return __import__('resources.lib.simkl_sync', fromlist=['simkl_sync'])
    if prov == 'mdblist':
        return __import__('resources.lib.mdblist_sync', fromlist=['mdblist_sync'])
    return __import__('resources.lib.trakt_sync', fromlist=['trakt_sync'])

def dispatch_mark_watched(tmdb_id, content_type, season=None, episode=None, notify=True, sync_provider=True, do_refresh=True, async_tmdb=False, skip_library_hack=False):
    targets = _mark_targets()
    prov = _get_provider_raw()
    # 'local' nu e target de fanout online: il extragem si il scriem pe un traseu
    # separat (local_sync), ca marcajele locale sa nu se piarda in modurile All/Custom.
    # Providerul ACTIV local se scrie mereu (paritate cu fortarea activului de la _mark_targets).
    local_pending = False
    if targets is not None and 'local' in targets:
        targets = [p for p in targets if p != 'local']
        local_pending = True
    if prov == 'local':
        local_pending = True
    if targets is None or (targets == [prov] and not local_pending):
        if prov == 'local':
            from resources.lib.local_sync import mark_as_watched_internal
            mark_as_watched_internal(tmdb_id, content_type, season, episode, notify=notify, sync_local=sync_provider, refresh_ui=do_refresh, skip_library_hack=skip_library_hack)
        elif prov == 'trakt':
            from resources.lib.trakt_sync import mark_as_watched_internal
            mark_as_watched_internal(tmdb_id, content_type, season, episode, notify=notify, sync_trakt=sync_provider, refresh_ui=do_refresh, skip_library_hack=skip_library_hack)
        elif prov == 'mdblist':
            from resources.lib.mdblist_sync import mark_as_watched_internal
            mark_as_watched_internal(tmdb_id, content_type, season, episode, notify=notify, sync_mdblist=sync_provider, refresh_ui=do_refresh)
        elif prov == 'simkl':
            from resources.lib.simkl_sync import mark_as_watched_internal
            mark_as_watched_internal(tmdb_id, content_type, season, episode, notify=notify, sync_simkl=sync_provider, refresh_ui=do_refresh)
        else:
            from resources.lib.punchplay_sync import mark_as_watched_internal
            mark_as_watched_internal(tmdb_id, content_type, season, episode, notify=notify, sync_punchplay=sync_provider, refresh_ui=do_refresh)
        _refresh_tmdb_up_next(tmdb_id)
        _verify_tmdb_upnext_heal(tmdb_id)
        # Randul TMDB Up Next (sursa listei "TMDb UP Next") trebuie rescris INTOTDEAUNA
        # in acest flux, nu async: async lasa lista TMDB cu episodul vechi daca UI-ul
        # s-a randat inaintea thread-ului (fara refresh ulterior).
        _upnext_ui_sync(preserve_binge=(not do_refresh))
        _invalidate_fast_cache()
        if do_refresh: refresh_ui()
        return
    # Fanout online: scriem si local (daca e pending), apoi providerii online.
    if local_pending:
        try:
            from resources.lib.local_sync import mark_as_watched_internal as _local_mark
            _local_mark(tmdb_id, content_type, season, episode, notify=(notify if not targets else False), sync_local=False, refresh_ui=False)
        except Exception:
            pass
    if not targets:
        _refresh_tmdb_up_next(tmdb_id)
        _verify_tmdb_upnext_heal(tmdb_id)
        _upnext_ui_sync(preserve_binge=(not do_refresh))
        _invalidate_fast_cache()
        if do_refresh: refresh_ui()
        return
    mark_watched_on_providers(tmdb_id, content_type, season, episode, providers=targets, notify=notify, sync_provider=sync_provider, do_refresh=do_refresh)

def dispatch_mark_unwatched(tmdb_id, content_type, season=None, episode=None, sync_provider=True, do_refresh=True):
    targets = _mark_targets()
    prov = _get_provider_raw()
    local_pending = False
    if targets is not None and 'local' in targets:
        targets = [p for p in targets if p != 'local']
        local_pending = True
    if prov == 'local':
        local_pending = True
    if targets is None or (targets == [prov] and not local_pending):
        if prov == 'local':
            from resources.lib.local_sync import mark_as_unwatched_internal
            mark_as_unwatched_internal(tmdb_id, content_type, season, episode, sync_local=sync_provider, refresh_ui=do_refresh)
        elif prov == 'trakt':
            from resources.lib.trakt_sync import mark_as_unwatched_internal
            mark_as_unwatched_internal(tmdb_id, content_type, season, episode, sync_trakt=sync_provider, refresh_ui=do_refresh)
        elif prov == 'mdblist':
            from resources.lib.mdblist_sync import mark_as_unwatched_internal
            mark_as_unwatched_internal(tmdb_id, content_type, season, episode, sync_mdblist=sync_provider, refresh_ui=do_refresh)
        elif prov == 'simkl':
            from resources.lib.simkl_sync import mark_as_unwatched_internal
            mark_as_unwatched_internal(tmdb_id, content_type, season, episode, sync_simkl=sync_provider, refresh_ui=do_refresh)
        else:
            from resources.lib.punchplay_sync import mark_as_unwatched_internal
            mark_as_unwatched_internal(tmdb_id, content_type, season, episode, sync_punchplay=sync_provider, refresh_ui=do_refresh)
        _refresh_tmdb_up_next(tmdb_id)
        _verify_tmdb_upnext_heal(tmdb_id)
        _upnext_ui_sync(preserve_binge=True)
        _invalidate_fast_cache()
        if do_refresh: refresh_ui()
        return
    if local_pending:
        try:
            from resources.lib.local_sync import mark_as_unwatched_internal as _local_unmark
            _local_unmark(tmdb_id, content_type, season, episode, notify=(True if not targets else False), sync_local=False, refresh_ui=False)
        except Exception:
            pass
    if not targets:
        _refresh_tmdb_up_next(tmdb_id)
        _verify_tmdb_upnext_heal(tmdb_id)
        _upnext_ui_sync(preserve_binge=True)
        _invalidate_fast_cache()
        if do_refresh: refresh_ui()
        return
    mark_unwatched_on_providers(tmdb_id, content_type, season, episode, providers=targets, notify=True, sync_provider=sync_provider, do_refresh=do_refresh)

def dispatch_scrobble(action, tmdb_id, content_type, season, episode, progress, duration_seconds=0, position_seconds=0, watched=None, watched_threshold=None):
    prov = _get_provider_raw()
    if prov == 'local':
        # CAPCANĂ (plan, amendament "else → PunchPlay"): fara acest elif, scrobble-urile
        # cu Local activ ar ajunge tăcut in API-ul PunchPlay. Local: progresul e deja
        # scris local de player.py (tabela partajata playback_progress) — doar listele
        # se invalideaza la stop.
        if action == 'stop':
            _invalidate_fast_cache()
        return
    if prov == 'trakt':
        from resources.lib.trakt_api import send_trakt_scrobble
        send_trakt_scrobble(action, tmdb_id, content_type, season, episode, progress)
    elif prov == 'mdblist':
        from resources.lib.mdblist_api import MDBListAPI
        api = MDBListAPI()
        if action == 'stop' and (progress or 0) <= 0:
            api.scrobble_clear(content_type, tmdb_id, season, episode, silent_404=True)
        elif action == 'start' or action == 'scrobble':
            api.scrobble_start(content_type, tmdb_id, progress, season, episode)
        elif action == 'pause':
            api.scrobble_pause(content_type, tmdb_id, progress, season, episode)
        elif action == 'stop':
            api.scrobble_stop(content_type, tmdb_id, progress, season, episode)
            _invalidate_fast_cache()
    elif prov == 'simkl':
        from resources.lib.simkl_api import SIMKLAPI
        api = SIMKLAPI()
        if action == 'start' or action == 'scrobble':
            api.scrobble_start(content_type, tmdb_id, progress, season, episode)
        elif action == 'pause':
            api.scrobble_pause(content_type, tmdb_id, progress, season, episode)
        elif action == 'stop':
            api.scrobble_stop(content_type, tmdb_id, progress, season, episode)
            _invalidate_fast_cache()
    else:
        from resources.lib.punchplay_api import PunchplayAPI, _pp_enqueue
        api = PunchplayAPI()
        if not api.is_authenticated():
            return
        _key = (str(tmdb_id), season, episode)
        if action == 'start':
            _pp_enqueue('start', lambda: api.scrobble_start(content_type, tmdb_id, progress, season, episode))
        elif action == 'scrobble':
            _pp_enqueue('progress', lambda: api.scrobble_progress(content_type, tmdb_id, progress, season, episode, duration_seconds=duration_seconds, position_seconds=position_seconds), coalesce_key=_key)
        elif action == 'pause':
            _pp_enqueue('pause', lambda: api.scrobble_pause(content_type, tmdb_id, progress, season, episode, duration_seconds=duration_seconds, position_seconds=position_seconds))
        elif action == 'resume':
            _pp_enqueue('resume', lambda: api.scrobble_resume(content_type, tmdb_id, progress, season, episode, duration_seconds=duration_seconds, position_seconds=position_seconds))
        elif action == 'stop':
            _pp_enqueue('stop', lambda: api.scrobble_stop(content_type, tmdb_id, progress, season, episode, duration_seconds=duration_seconds, position_seconds=position_seconds, watched=watched, watched_threshold=watched_threshold))
            _invalidate_fast_cache()

def _kodi_delete_resume_bookmark(tmdb_id, content_type, season=None, episode=None):
    try:
        content_type = 'tv' if content_type in ('tv', 'episode') else 'movie'
        import glob
        import sqlite3
        db_dir = xbmcvfs.translatePath('special://userdata/Database/')
        dbs = glob.glob(os.path.join(db_dir, 'MyVideos*.db'))
        if not dbs:
            return
        db_path = max(dbs, key=os.path.getmtime)
        conn = sqlite3.connect(db_path, timeout=2)
        cur = conn.cursor()
        params = ['%mode=sources%', '%%tmdb_id=%s%%' % tmdb_id, '%%type=%s%%' % content_type]
        query = ("DELETE FROM bookmark WHERE type=1 AND idFile IN (SELECT idFile FROM files "
                 "WHERE strFilename LIKE ? AND strFilename LIKE ? AND strFilename LIKE ?")
        if content_type == 'tv' and season is not None and episode is not None:
            params += ['%%season=%s%%' % season, '%%episode=%s%%' % episode]
            query += " AND strFilename LIKE ? AND strFilename LIKE ?"
        query += ")"
        cur.execute(query, params)
        conn.commit()
        xbmc.log(f"[TMDb Movies] [RESUME] Bookmark Kodi sters: {cur.rowcount} rand(uri)", xbmc.LOGINFO)
        conn.close()
    except Exception as e:
        xbmc.log(f"[TMDb Movies] [RESUME] Bookmark Kodi stergere error: {e}", xbmc.LOGERROR)

def dispatch_remove_progress(tmdb_id, content_type='movie', season=None, episode=None):
    """Elimina resume-ul (toate serverele autorizate + tabela locala) si refresheaza."""
    # 1. Server MDBList (daca e autorizat) - 404 = sesiune inexistenta, nu e eroare
    try:
        from resources.lib.mdblist_api import MDBListAPI
        _api = MDBListAPI()
        if _api.is_authenticated():
            _api.scrobble_clear(content_type, tmdb_id, season, episode, silent_404=True)
    except Exception:
        pass
    # 1b. Server Simkl (daca e autorizat)
    try:
        from resources.lib.simkl_api import SIMKLAPI
        _api = SIMKLAPI()
        if _api.is_authenticated():
            _api.playback_remove(content_type, tmdb_id, season, episode)
    except Exception:
        pass
    # 1c. Server PunchPlay (daca e autorizat)
    try:
        from resources.lib.punchplay_api import PunchplayAPI
        _api = PunchplayAPI()
        if _api.is_authenticated():
            _api.playback_remove(content_type, tmdb_id, season, episode)
    except Exception:
        pass
    # 2. Server Trakt + stergere locala + clear fast cache + Container.Refresh
    from resources.lib.trakt_api import remove_from_progress
    remove_from_progress(tmdb_id, content_type, season, episode)
    # 3. Bookmark Kodi (dialogul nativ de resume nu mai trebuie sa apara la click)
    _kodi_delete_resume_bookmark(tmdb_id, content_type, season, episode)
    # 4. Refresh widget-uri de pe Home (UpdateLibrary) — Container.Refresh din
    #    remove_from_progress doar reimprospateaza containerul activ, nu widget-urile.
    _invalidate_fast_cache()
    refresh_ui()

def get_watched_counts_map(tmdb_ids):
    """Count-uri pe mai multe seriale, dintr-o singura conexiune (per provider activ).

    None = providerul nu are varianta bulk / citirea a esuat -> apelantul foloseste
    numararea per serial (comportamentul de dinainte).
    """
    try:
        prov = _get_provider_raw()
        if prov == 'local':
            from resources.lib.local_sync import get_watched_counts_map as _m
            return _m(tmdb_ids)
        elif prov == 'punchplay':
            from resources.lib.punchplay_sync import get_watched_counts_map as _m
        elif prov == 'mdblist':
            from resources.lib.mdblist_sync import get_watched_counts_map as _m
        elif prov == 'simkl':
            from resources.lib.simkl_sync import get_watched_counts_map as _m
        else:
            return None
        return _m(tmdb_ids)
    except:
        return None


def is_movie_watched(tmdb_id):
    return get_source_module().is_movie_watched(tmdb_id)

def is_episode_watched(tmdb_id, season, episode):
    return get_source_module().is_episode_watched(tmdb_id, season, episode)

def get_episode_watched_count(tmdb_id):
    """Numar de episoade vizionate pentru un serial (provider-aware, int)."""
    prov = _get_provider_raw()
    if prov == 'local':
        from resources.lib.local_sync import get_watched_episodes_count as _chk
        return _chk(tmdb_id)
    elif prov == 'trakt':
        from resources.lib.trakt_sync import get_episode_watched_count as _chk
        return _chk(tmdb_id)
    elif prov == 'mdblist':
        from resources.lib.mdblist_sync import get_watched_episodes_count as _chk
        return _chk(tmdb_id)
    elif prov == 'simkl':
        from resources.lib.simkl_sync import get_watched_episodes_count as _chk
        return _chk(tmdb_id)
    else:
        from resources.lib.punchplay_sync import get_watched_episodes_count as _chk
        return _chk(tmdb_id)

def get_watched_episodes_set(tmdb_id):
    prov = _get_provider_raw()
    tbl = {'trakt': 'trakt_watched_episodes', 'mdblist': 'mdblist_watched_episodes', 'simkl': 'simkl_watched_episodes', 'punchplay': 'punchplay_watched_episodes', 'local': 'local_watched_episodes'}[prov]
    res = {'set': set(), 'last': None, 'last_at': ''}
    try:
        mod = get_source_module()
        conn = mod.get_connection()
        cur = conn.cursor()
        cur.execute(f"SELECT season, episode, last_watched_at FROM {tbl} WHERE tmdb_id=?", (str(tmdb_id),))
        rows = cur.fetchall()
        conn.close()
        max_at = None
        for r in rows:
            s, e, at = r[0], r[1], r[2]
            if not s or not e:
                continue
            res['set'].add((int(s), int(e)))
            if at:
                if max_at is None or at > max_at[1]:
                    max_at = ((int(s), int(e)), at)
        if max_at:
            res['last'] = max_at[0]
            res['last_at'] = max_at[1]
    except Exception:
        pass
    return res

def get_watched_episodes_set_batch(tmdb_ids):
    prov = _get_provider_raw()
    tbl = {'trakt': 'trakt_watched_episodes', 'mdblist': 'mdblist_watched_episodes', 'simkl': 'simkl_watched_episodes', 'punchplay': 'punchplay_watched_episodes', 'local': 'local_watched_episodes'}[prov]
    result = {}
    ids = [str(x) for x in (tmdb_ids or []) if x]
    if not ids:
        return result
    for tid in ids:
        result[tid] = {'set': set(), 'last': None, 'last_at': ''}
    try:
        mod = get_source_module()
        conn = mod.get_connection()
        cur = conn.cursor()
        chunk_size = 400
        for i in range(0, len(ids), chunk_size):
            chunk = ids[i:i + chunk_size]
            placeholders = ','.join(['?'] * len(chunk))
            cur.execute(f"SELECT tmdb_id, season, episode, last_watched_at FROM {tbl} WHERE tmdb_id IN ({placeholders})", chunk)
            for row in cur.fetchall():
                tid, s, e, at = str(row[0]), row[1], row[2], row[3]
                if tid not in result:
                    continue
                if not s or not e:
                    continue
                result[tid]['set'].add((int(s), int(e)))
                if at:
                    cur_last = result[tid]['last_at']
                    if not cur_last or at > cur_last:
                        result[tid]['last'] = (int(s), int(e))
                        result[tid]['last_at'] = at
        conn.close()
    except Exception:
        pass
    return result

def _refresh_tmdb_up_next(tmdb_id):
    """Recalculeaza randul TMDB Up Next dupa mark watched/unwatched (daca TMDb e conectat)."""
    try:
        from resources.lib.config import TMDB_V4_TOKEN_FILE
        if os.path.exists(TMDB_V4_TOKEN_FILE):
            from resources.lib.trakt_sync import refresh_next_episode_tmdb
            refresh_next_episode_tmdb(tmdb_id)
    except Exception:
        pass


def _verify_tmdb_upnext_heal(tmdb_id):
    """Verifica ca rindul TMDB Up Next pentru tmdb_id corespunde deja vizionate
    locale ale providerului activ; daca nu (ex: rescrierea a esuat tranzitoriu in
    urma cu 0.2-3s), re-run refresh_next_episode_tmdb. Rulata sincron, cu 3
    re-verificari la 500ms — rindul TMDb provine dintr-un SQLite separat.
    """
    try:
        from resources.lib.config import TMDB_V4_TOKEN_FILE
        if not os.path.exists(TMDB_V4_TOKEN_FILE):
            return
        import time as _t
        for _i in range(3):
            _t.sleep(0.5)
            try:
                from resources.lib import trakt_sync as _ts
                pconn = _ts.get_connection()
                pcur = pconn.cursor()
                pcur.execute("SELECT season, episode FROM tmdb_next_episodes WHERE tmdb_id=?", (str(tmdb_id),))
                row = pcur.fetchone()
                pconn.close()
            except Exception:
                return
            if row is None or row[0] is None or row[1] is None:
                return
            try:
                pseason, pep = int(row[0]), int(row[1])
            except Exception:
                return
            # Referinta = rindul providerului activ (aceeasi sursa ca listele
            # Up Next dinamice). Daca exista si difera de rindul TMDB, oferim
            # prilejul de heal (TMDB scris de alt thread poate ramine in urma).
            ref = None
            try:
                mod = get_source_module()
                prov = _get_provider_raw()
                p_tbl = {'trakt': 'trakt_next_episodes', 'mdblist': 'mdblist_next_episodes',
                         'simkl': 'simkl_next_episodes', 'punchplay': 'punchplay_next_episodes',
                         'local': 'local_next_episodes'}[prov]
                mconn = mod.get_connection()
                mcur = mconn.cursor()
                mcur.execute("SELECT season, episode FROM %s WHERE tmdb_id=?" % p_tbl, (str(tmdb_id),))
                mrow = mcur.fetchone()
                mconn.close()
                if mrow and mrow[0] is not None and mrow[1] is not None:
                    ref = (int(mrow[0]), int(mrow[1]))
            except Exception:
                ref = None
            w = get_watched_episodes_set(tmdb_id)
            wset = w.get('set') or set()
            tmdb_pair = (pseason, pep)
            tmdb_is_ok = tmdb_pair not in wset
            ref_is_ok = (ref is None) or (ref not in wset)
            same = (ref is None) or (ref == tmdb_pair)
            if tmdb_is_ok and ref_is_ok and same:
                return  # totul consistent
            # Rindul TMDB e in urma (expus un episod vazut sau diferit de provider).
            try:
                from resources.lib.trakt_sync import refresh_next_episode_tmdb
                refresh_next_episode_tmdb(tmdb_id)
            except Exception:
                pass
            return
    except Exception:
        pass


def _upnext_ui_sync(preserve_binge=True):
    """Dupa rescrierea randurilor Up Next (provider + TMDB): invalideaza listele din
    fast cache si da Container.Refresh, ca AMBELE liste Up Next (colorata dinamica
    si TMDB) sa arate noul episod la urmatoarea randare.

    preserve_binge=True pastreaza comportamentul din player: nu suprascriem un
    dialog binge/autoplay deschis si nu dam refresh daca listele s-au reimprospatat
    chiar acum (evitam randarile in paralel care lasau pagina goala).
    """
    import time as _time
    try:
        from resources.lib.cache import clear_list_fast_cache
        clear_list_fast_cache()
    except Exception:
        pass
    try:
        import xbmcgui
        try:
            _binge_since = float(xbmcgui.Window(10000).getProperty('tmdbmovies.binge_open') or 0)
        except Exception:
            _binge_since = 0.0
        if preserve_binge and _binge_since > 0 and (_time.time() - _binge_since) < 120:
            return
        try:
            _last = float(xbmcgui.Window(10000).getProperty('tmdbmovies.last_upnext_refresh') or 0)
        except Exception:
            _last = 0.0
        if _time.time() - _last < 1.5:
            return
        refresh_ui()
        try:
            if not _on_home_widget():
                widget_refresh()
        except Exception:
            pass
        xbmcgui.Window(10000).setProperty('tmdbmovies.last_upnext_refresh', str(_time.time()))
    except Exception:
        pass

def get_season_watched_count(tmdb_id, season):
    """Numar de episoade vizionate dintr-un sezon (provider-aware, int)."""
    prov = _get_provider_raw()
    if prov == 'local':
        from resources.lib.local_sync import get_watched_season_episodes_count as _chk
        return _chk(tmdb_id, season)
    elif prov == 'trakt':
        from resources.lib.trakt_sync import get_episode_watched_count as _chk
        return _chk(tmdb_id, season)
    elif prov == 'mdblist':
        from resources.lib.mdblist_sync import get_watched_season_episodes_count as _chk
        return _chk(tmdb_id, season)
    elif prov == 'simkl':
        from resources.lib.simkl_sync import get_watched_season_episodes_count as _chk
        return _chk(tmdb_id, season)
    else:
        from resources.lib.punchplay_sync import get_watched_season_episodes_count as _chk
        return _chk(tmdb_id, season)

# =============================================================================
# DISPATCHER SYNC SECVENTIAL UNIFICAT (Smart / Force / auto-sync 30 min)
# =============================================================================
_SYNC_LOCK_KEY = 'tmdbmovies_sync_active'
_SYNC_START_STAMP_KEY = 'tmdbmovies_sync_started'
_SYNC_OWNER_KEY = 'tmdbmovies_sync_owner'
_SYNC_ATTEMPT_KEY = 'tmdbmovies_sync_attempt'
_SYNC_FUTURE_SKEW = 300.0
_SYNC_STALE_AFTER = 600.0
_LAST_SYNC_STAMP_KEY = 'tmdbmovies_last_sync'


class _SyncLockGuard:
    def __init__(self, token):
        try:
            self._token = str(token or '')
        except Exception:
            self._token = ''

    def close(self):
        try:
            import xbmcgui as _xg2
            if not self._token:
                return
            _w = _xg2.Window(10000)
            if _w.getProperty(_SYNC_OWNER_KEY) == self._token:
                _w.clearProperty(_SYNC_LOCK_KEY)
                _w.clearProperty(_SYNC_START_STAMP_KEY)
                _w.clearProperty(_SYNC_OWNER_KEY)
        except Exception:
            pass


def _sync_lock_release(token):
    try:
        import xbmcgui as _xg1
        if not token:
            return
        _w = _xg1.Window(10000)
        if _w.getProperty(_SYNC_OWNER_KEY) == str(token):
            _w.clearProperty(_SYNC_LOCK_KEY)
            _w.clearProperty(_SYNC_START_STAMP_KEY)
            _w.clearProperty(_SYNC_OWNER_KEY)
    except Exception:
        pass


def _sync_lock_read():
    try:
        import xbmcgui as _xg0
        _w = _xg0.Window(10000)
        return _w.getProperty(_SYNC_LOCK_KEY), _w.getProperty(_SYNC_START_STAMP_KEY), _w.getProperty(_SYNC_OWNER_KEY)
    except Exception:
        return '', '', ''


def _sync_lock_acquire(post_update=False, update_stamp=None):
    import time as _t
    import uuid as _u
    try:
        _now = _t.time()
    except Exception:
        _now = 0.0
    _lock, _started, _owner = _sync_lock_read()
    if _lock == 'true':
        _ts = None
        try:
            _ts = float(_started) if _started else None
        except Exception:
            _ts = None
        _takeover = False
        if post_update and update_stamp is not None:
            try:
                _uts = float(update_stamp)
            except Exception:
                _uts = None
            if _uts is not None and _ts is not None and _ts < _uts and _ts <= _now + _SYNC_FUTURE_SKEW:
                _takeover = True
            elif _ts is None and not _owner:
                _takeover = True
            if _takeover:
                try:
                    xbmc.log('[SYNC DISPATCH] Post-update takeover: clearing pre-update lock.', xbmc.LOGINFO)
                except Exception:
                    pass
            else:
                return 'locked', ''
        if not _takeover and _ts is not None and (_now - _ts) < _SYNC_STALE_AFTER:
            return 'locked', ''
    try:
        _token = _u.uuid4().hex
    except Exception:
        _token = 't%d' % int(_now)
    try:
        import xbmcgui as _xg0
        _w = _xg0.Window(10000)
        _w.setProperty(_SYNC_START_STAMP_KEY, str(_now))
        _w.setProperty(_SYNC_OWNER_KEY, _token)
        _w.setProperty(_SYNC_LOCK_KEY, 'true')
    except Exception:
        return 'locked', ''
    try:
        from resources.lib.config import register_shutdown_iterator
        register_shutdown_iterator(_SyncLockGuard(_token))
    except Exception:
        pass
    return 'acquired', _token

_PROVIDER_SYNC_COLORS = {
    'local': 'FFF70D1A',
    'tmdb': 'FF00CED1',
    'trakt': 'pink',
    'mdblist': 'lightskyblue',
    'simkl': 'mediumpurple',
    'punchplay': 'FFFF6600',
}

_PROVIDER_SYNC_NAMES = {
    'local': 'Kodi (Local)',
    'tmdb': 'TMDb',
    'trakt': 'Trakt',
    'mdblist': 'MDBList',
    'simkl': 'Simkl',
    'punchplay': 'PunchPlay',
}


def _provider_connected(p):
    """Pre-check LOCAL de token (fara retea) pentru piciorul de sync p."""
    try:
        if p == 'local':
            return True
        if p == 'tmdb':
            from resources.lib.utils import read_json
            from resources.lib.config import TMDB_V4_TOKEN_FILE
            s = read_json(TMDB_V4_TOKEN_FILE)
            return bool(s and isinstance(s, dict) and s.get('access_token'))
        if p == 'trakt':
            from resources.lib import trakt_api
            return bool(trakt_api.get_trakt_token())
        if p == 'mdblist':
            return bool(ADDON.getSetting('mdblist_access_token') or ADDON.getSetting('mdblist_api'))
        if p == 'simkl':
            return bool(ADDON.getSetting('simkl_access_token'))
        if p == 'punchplay':
            return bool(ADDON.getSetting('punchplay_access_token'))
    except Exception:
        return False
    return False


def sync_full_library(silent=False, force=False, source='manual', post_update=False, update_stamp=None):
    import time as _time
    import xbmcgui as _xg

    window = _xg.Window(10000)
    _acq, _own = _sync_lock_acquire(post_update=post_update, update_stamp=update_stamp)
    if _acq != 'acquired':
        xbmc.log('[SYNC DISPATCH] Sync already in progress. Ignoring new request.', xbmc.LOGINFO)
        if not silent:
            _xg.Dialog().notification("[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]",
                                      "Syncing...",
                                      os.path.join(ADDON_PATH, 'icon.png'))
        return 'locked'
    _t0 = _time.time()
    _kind = 'AUTO' if source == 'auto' else ('FULL' if force else 'SMART')
    xbmc.log('[SYNC DISPATCH] === STARTING %s SYNC ===' % _kind, xbmc.LOGINFO)

    _ICON = os.path.join(ADDON_PATH, 'icon.png')

    # Paritate cu dispatcherul vechi: la sync-uri vizibile validam conexiunea
    # providerului activ (popup doar daca lipseste; early-return pentru local).
    if not silent:
        try:
            ensure_active_provider()
        except Exception:
            pass

    # Un singur DialogProgressBG pe toata durata; heading-ul se coloreaza cu
    # culoarea providerului scanat in acel moment.
    p_dialog = None
    if not silent:
        try:
            p_dialog = _xg.DialogProgressBG()
            p_dialog.create("[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]", "Checking for changes...")
        except Exception:
            p_dialog = None

    def _say(pct, color, name, msg):
        if not p_dialog:
            return
        try:
            p_dialog.update(int(pct), heading="[B][COLOR %s]%s[/COLOR][/B]" % (color, name), message=msg)
        except Exception:
            try: p_dialog.update(int(pct), message=msg)
            except Exception: pass

    try:
        # --- Ordinea fixa: Local -> TMDb -> Trakt -> MDBList -> Simkl -> PunchPlay ---
        legs = ['local', 'tmdb', 'trakt', 'mdblist', 'simkl', 'punchplay']
        prov = _get_provider_raw()
        try:
            mark_mode = ADDON.getSetting('watched_mark_mode') or '0'
        except Exception:
            mark_mode = '0'
        try:
            local_toggled = ADDON.getSetting('watched_mark_local') == 'true'
        except Exception:
            local_toggled = False
        # Local: rebuild Up Next (cost TMDb per serial) doar daca local e ACTIV
        # sau bifat in Custom selection (paritate cu dispatcherul vechi).
        local_rebuild = (prov == 'local') or (mark_mode == '2' and local_toggled)

        connected = 0
        succeeded = 0
        failed = 0
        aborted = False
        n = len(legs)
        for i, p in enumerate(legs):
            base = int(100.0 * i / n)
            span = max(1, int(100 / n))
            color = _PROVIDER_SYNC_COLORS.get(p, 'white')
            name = _PROVIDER_SYNC_NAMES.get(p, p)

            try:
                if kodi_abort_requested():
                    aborted = True
                    break
            except Exception:
                pass

            if not _provider_connected(p):
                xbmc.log('[SYNC DISPATCH] %s leg skipped (not connected).' % p.upper(), xbmc.LOGINFO)
                continue
            connected += 1

            xbmc.log('[SYNC DISPATCH] --- %s leg starting ---' % p.upper(), xbmc.LOGINFO)

            def _leg_cb(pct, msg, _p=p, _color=color, _name=name, _base=base, _span=span):
                try:
                    shown = min(99, _base + int((int(pct or 0)) * _span / 100))
                except Exception:
                    shown = _base
                _say(shown, _color, _name, msg or 'Syncing...')

            _say(base + 1, color, name, 'Syncing...')
            try:
                if p == 'local':
                    from resources.lib.local_sync import sync_full_library as _local_sync
                    _local_sync(silent=True, force=force, rebuild_upnext=local_rebuild, progress_cb=_leg_cb)
                elif p == 'tmdb':
                    from resources.lib import trakt_sync as _ts
                    from resources.lib.utils import read_json
                    from resources.lib.config import TMDB_V4_TOKEN_FILE
                    _sess = read_json(TMDB_V4_TOKEN_FILE)
                    if _sess and isinstance(_sess, dict) and _sess.get('access_token'):
                        # Acelasi gating ca in picioarele Trakt/MDBList:
                        # 30 min smart / 60s dedup la force.
                        _last_tmdb = _ts.get_local_last_sync().get('tmdb_sync_ts', 0)
                        tmdb_needed = (_time.time() - _last_tmdb > 1800) or (force and (_time.time() - _last_tmdb > 60))
                        if tmdb_needed:
                            conn = None
                            _ok = False
                            try:
                                _ts.init_database()
                                conn = _ts.get_connection()
                                c = conn.cursor()
                                _ok = _ts.sync_tmdb_phase(c, force=tmdb_needed, silent=True, progress_cb=_leg_cb)
                                conn.commit()
                            except Exception as _e:
                                xbmc.log('[SYNC DISPATCH] TMDb phase error: %s' % _e, xbmc.LOGERROR)
                                _ok = False
                            finally:
                                try:
                                    if conn: conn.close()
                                except Exception: pass
                            # tmdb_sync_ts DOAR la faza completa (anti-141)
                            if _ok:
                                try:
                                    _ls = _ts.get_local_last_sync()
                                    _ls['tmdb_sync_ts'] = _time.time()
                                    _ts.save_local_last_sync(_ls)
                                except Exception: pass
                        else:
                            _ago_min = int((_time.time() - _last_tmdb) / 60) if _last_tmdb else -1
                            _in_min = max(0, 30 - _ago_min) if _ago_min >= 0 else 0
                            xbmc.log('[SYNC DISPATCH] TMDb leg skipped (last sync %d min ago, next in ~%d min).' % (_ago_min, _in_min), xbmc.LOGINFO)
                elif p == 'trakt':
                    from resources.lib.trakt_sync import _trakt_leg
                    _trakt_leg(silent=True, force=force, progress_cb=_leg_cb, suppress_notifications=True, skip_tmdb_phase=True)
                elif p == 'mdblist':
                    from resources.lib.mdblist_sync import _mdblist_leg
                    _mdblist_leg(silent=True, force=force, progress_cb=_leg_cb, suppress_notifications=True, skip_tmdb_phase=True)
                elif p == 'simkl':
                    from resources.lib.simkl_sync import _simkl_leg
                    from resources.lib.simkl_api import SIMKLAPI
                    _simkl_leg(api=SIMKLAPI(), is_active=(prov == 'simkl'),
                               silent=True, force=force, progress_cb=_leg_cb, suppress_notifications=True)
                else:
                    from resources.lib.punchplay_sync import _punchplay_leg
                    from resources.lib.punchplay_api import PunchplayAPI
                    _punchplay_leg(api=PunchplayAPI(), silent=True, force=force,
                                   progress_cb=_leg_cb, suppress_notifications=True)
            except Exception as e:
                xbmc.log('[SYNC DISPATCH] %s leg error: %s' % (p.upper(), e), xbmc.LOGERROR)
                failed += 1
            else:
                succeeded += 1

        if aborted:
            status = 'aborted'
        elif succeeded >= 1:
            status = 'ok'
        elif connected > 0:
            status = 'error'
        else:
            status = 'noop'

        if status != 'aborted':
            try:
                window.setProperty(_SYNC_ATTEMPT_KEY, str(_t0))
            except Exception:
                pass

        if status == 'ok':
            window.setProperty(_LAST_SYNC_STAMP_KEY, str(_t0))
            _say(100, 'FF00CED1', 'TMDb Movies', 'Sync complete')
            xbmc.log('[SYNC DISPATCH] === SYNC COMPLETE (%d/%d legs ok) ===' % (succeeded, connected), xbmc.LOGINFO)
            if not silent:
                _xg.Dialog().notification("[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]",
                                          "Sync Complete",
                                          _ICON)
        elif status == 'error':
            xbmc.log('[SYNC DISPATCH] === SYNC ERROR (%d/%d legs failed) ===' % (failed, connected), xbmc.LOGERROR)
            if not silent:
                _xg.Dialog().notification("[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]",
                                          "Sync errors - check log",
                                          _ICON)
        elif status == 'noop':
            xbmc.log('[SYNC DISPATCH] === SYNC NOOP (no provider connected) ===', xbmc.LOGINFO)
        else:
            xbmc.log('[SYNC DISPATCH] === SYNC ABORTED ===', xbmc.LOGINFO)
        if p_dialog:
            try: p_dialog.close()
            except Exception: pass
            p_dialog = None
        return status
    finally:
        if p_dialog:
            try: p_dialog.close()
            except Exception: pass
        try:
            _sync_lock_release(_own)
        except Exception:
            pass
        try:
            from resources.lib.cache import clear_all_fast_cache
            clear_all_fast_cache()
        except Exception: pass
        try:
            from resources.lib.mdblist_sync import clear_cache_prefix
            clear_cache_prefix('trakt_calendar')
        except Exception: pass

def get_watched_counts(tmdb_id, content_type, season=None):
    """Provider-aware watched count: {watched: int, total: int}"""
    if content_type == 'movie':
        return 1 if is_movie_watched(tmdb_id) else 0
    prov = _get_provider_raw()
    if prov == 'local':
        from resources.lib.local_sync import get_watched_episodes_count, get_watched_season_episodes_count
        if content_type == 'season' and season is not None:
            return get_watched_season_episodes_count(tmdb_id, season)
        else:
            return get_watched_episodes_count(tmdb_id)
    elif prov == 'trakt':
        from resources.lib import trakt_api
        if content_type == 'season' and season is not None:
            return trakt_api.get_watched_counts(tmdb_id, 'season', season)
        else:
            return trakt_api.get_watched_counts(tmdb_id, 'tv')
    elif prov == 'mdblist':
        from resources.lib.mdblist_sync import get_watched_episodes_count, get_watched_season_episodes_count
        if content_type == 'season' and season is not None:
            return get_watched_season_episodes_count(tmdb_id, season)
        else:
            return get_watched_episodes_count(tmdb_id)
    elif prov == 'simkl':
        from resources.lib.simkl_sync import get_watched_episodes_count, get_watched_season_episodes_count
        if content_type == 'season' and season is not None:
            return get_watched_season_episodes_count(tmdb_id, season)
        else:
            return get_watched_episodes_count(tmdb_id)
    else:
        from resources.lib.punchplay_sync import get_watched_episodes_count, get_watched_season_episodes_count
        if content_type == 'season' and season is not None:
            return get_watched_season_episodes_count(tmdb_id, season)
        else:
            return get_watched_episodes_count(tmdb_id)
