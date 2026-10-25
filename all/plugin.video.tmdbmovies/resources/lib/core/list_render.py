# -*- coding: utf-8 -*-
"""Randarea listelor din fast cache, fara a importa api/tmdb_api sau providerii.

Randarea cache-uita este cea care se declanseaza la intoarcerea din player. Cand
rezolvam aici, evitam ~700ms de importuri (tmdb_api + trakt_sync + providers) pe
calea critica. De aceea modulul sta la baza si nu aduce nimic greu cu el.
"""
import re

import xbmcgui
import xbmcplugin

from resources.lib.core import config as _cfg
from resources.lib.core.utils import apply_air_times_to_cache_items, set_resume_point, log

NEXT_EPISODES_LABEL_VERSION = "13"

_REL_CMD_RE = re.compile(r'(RunPlugin\(|Container\.Update\(|ActivateWindow\([^,]+,\s*)\?')


def _handle():
    # HANDLE se citit dinamic: config.HANDLE e rescris de entry la fiecare
    # invocare (RLI), iar o copie importata la modul ar ingeta.
    try:
        return _cfg.HANDLE
    except Exception:
        return -1


def _set_views_apply(view_type, content=None):
    """Set Views: aplica view-ul salvat DUPA endOfDirectory (content None -> folosim view_type)."""
    try:
        from resources.lib.core import views
        views.apply_view(view_type, view_type if content is None else content)
    except Exception:
        pass


def _safe_set_prop(li, key, value):
    try:
        li.setProperty(str(key), str(value))
        return True
    except Exception as e:
        log(f"[LIST] setProperty esuat ({key}): {e}")
        return False


_WATCHED_GREEN = '[B][COLOR FF6AFB92]'


def _patch_watched_flags(items):
    """Corecteaza bifa de vizionare la randare, din baza de date locala.

    Cache-ul tine starea de vizionare de la momentul constructiei listei. Daca
    intre timp a fost marcat un film/serial, randarea din cache ar arata bifa
    veche. Aici recitim starea curenta (un singur query in batch, baza locala)
    si corectam randurile - fara sa reconstruim lista, deci fara BusyDialog.

    Se aplica doar pe filmele si episodele (randurile care au o bifa proprie).
    Serialele (mediatype tvshow) au bifa de "complet vizionat", care depinde de
    numaratoare - aia raman cum le-a construit cache-ul.
    """
    try:
        import re
        from resources.lib.providers.watched_provider import (
            get_watched_movies_set_batch, get_watched_episodes_set_batch)
    except Exception:
        return
    try:
        movies = []
        episodes = []
        for it in items:
            info = it.get('info') or {}
            mt = info.get('mediatype')
            if mt not in ('movie', 'episode'):
                continue
            u = it.get('url') or ''
            m = re.search(r'tmdb_id=(\d+)', u)
            if not m:
                continue
            tid = m.group(1)
            if mt == 'movie':
                movies.append((it, tid))
            else:
                s_m = re.search(r'season=(\d+)', u)
                e_m = re.search(r'episode=(\d+)', u)
                if s_m and e_m:
                    episodes.append((it, tid, int(s_m.group(1)), int(e_m.group(1))))
        if not movies and not episodes:
            return
        watched_movies = get_watched_movies_set_batch([t for _, t in movies]) if movies else set()
        watched_eps = {}
        if episodes:
            watched_eps = get_watched_episodes_set_batch([t for _, t, _, _ in episodes])
    except Exception:
        return

    def _fix_watch_cm(item, is_watched):
        """Corecteaza optiunea "Mark Watched/Unwatched" din meniul contextual.

        Meniul e construit la momentul listii si pastrat in cache. Daca lista e
        servita "veche" (fallback stale), optiunea ramane cea de la build - deci
        filmul nevedionut ar primi "Mark Unwatched" (si invers). Se corecteaza
        aici, la randare, inainte sa fie aplicat meniul.
        """
        cm = item.get('cm') or []
        idx = -1
        for _i, _e in enumerate(cm):
            if not isinstance(_e, (list, tuple)) or len(_e) < 2:
                continue
            _cmd = str(_e[1] or '')
            if 'mark_watched' in _cmd or 'mark_unwatched' in _cmd:
                idx = _i
                break
        if idx < 0:
            return
        _lbl, _cmd = cm[idx][0], str(cm[idx][1] or '')
        if is_watched:
            _new_cmd = _cmd.replace('mode=mark_watched', 'mode=mark_unwatched')
        else:
            _new_cmd = _cmd.replace('mode=mark_unwatched', 'mode=mark_watched')
        if _new_cmd == _cmd:
            return
        _new_lbl = None
        try:
            from resources.lib.providers.watched_provider import mark_menu_label
            _new_lbl = mark_menu_label(is_watched)
        except Exception:
            _new_lbl = None
        if not _new_lbl:
            if is_watched:
                _new_lbl = str(_lbl).replace('Mark Watched', 'Mark Unwatched')\
                    .replace('FF6AFB92', 'FFE41B17')
            else:
                _new_lbl = str(_lbl).replace('Mark Unwatched', 'Mark Watched')\
                    .replace('FFE41B17', 'FF6AFB92')
        cm[idx] = (_new_lbl, _new_cmd)
        item['cm'] = cm

    def _apply(item, is_watched):
        info = item.get('info') or {}
        try:
            was = int(info.get('playcount') or 0) == 1
        except Exception:
            was = False
        if was == is_watched:
            return
        info['playcount'] = 1 if is_watched else 0
        item['info'] = info
        label = item.get('label') or ''
        if is_watched:
            if '[COLOR' not in label:
                item['label'] = '%s%s[/COLOR][/B]' % (_WATCHED_GREEN, label)
        else:
            if label.startswith(_WATCHED_GREEN) and label.endswith('[/COLOR][/B]'):
                item['label'] = label[len(_WATCHED_GREEN):-len('[/COLOR][/B]')]
        try:
            _fix_watch_cm(item, is_watched)
        except Exception:
            pass

    for it, tid in movies:
        try:
            _apply(it, tid in watched_movies)
        except Exception:
            continue
    for it, tid, se, ep in episodes:
        try:
            st = watched_eps.get(tid) or {}
            _apply(it, (se, ep) in (st.get('set') or set()))
        except Exception:
            continue


def _patch_resume_flags(items):
    """Reciteste pozitia de resume din baza locala si o aplica randarii.

    Cache-ul pastreaza resume_time de la construire. O oprire sub 85% nu
    invalideaza lista, deci cercul ar lipsi pana la urmatorul rebuild.
    """
    try:
        import re
        from resources.lib.providers.trakt_sync import get_local_resume_progress_bulk
    except Exception:
        return
    movies = []
    episodes = []
    try:
        for it in items:
            info = it.get('info') or {}
            mt = info.get('mediatype')
            if mt not in ('movie', 'episode'):
                continue
            u = str(it.get('url') or '')
            m = re.search(r'tmdb_id=(\d+)', u)
            if not m:
                continue
            tid = m.group(1)
            if mt == 'movie':
                movies.append((it, tid))
            else:
                s_m = re.search(r'season=(\d+)', u)
                e_m = re.search(r'episode=(\d+)', u)
                if s_m and e_m:
                    episodes.append((it, tid, int(s_m.group(1)), int(e_m.group(1))))
    except Exception:
        return
    if not movies and not episodes:
        return
    data = get_local_resume_progress_bulk([t for _, t in movies],
                                          [(t, s, e) for _, t, s, e in episodes])
    if not isinstance(data, dict):
        return
    mv = data.get('movies') or {}
    eps = data.get('episodes') or {}

    def _total(it):
        try:
            total = float(it.get('total_time') or 0)
        except Exception:
            total = 0.0
        if total <= 0:
            try:
                total = float((it.get('info') or {}).get('duration') or 0)
            except Exception:
                total = 0.0
        return total

    def _apply(it, progress):
        try:
            progress = float(progress or 0)
        except Exception:
            progress = 0.0
        total = _total(it)
        resume = 0
        if progress >= 1000000:
            resume = int(progress - 1000000)
        elif 0 < progress < 90 and total > 0:
            resume = int((progress / 100.0) * total)
        if resume > 0 and total > 0:
            it['resume_time'] = resume
            it['total_time'] = int(total)
        else:
            it['resume_time'] = 0
            if total > 0:
                it['total_time'] = int(total)

    for it, tid in movies:
        _apply(it, mv.get(tid, 0))
    for it, tid, s, e in episodes:
        _apply(it, eps.get((tid, s, e), 0))


def _abs_url(u):
    """Repara URL-urile relative din cache (construite in thread de fundal)."""
    try:
        u = str(u or '')
    except Exception:
        return u
    if not u:
        return u
    if u.startswith('?'):
        from resources.lib.core.config import PLUGIN_URL
        return PLUGIN_URL + u
    return u


def _abs_cm(cm):
    """Repara URL-urile relative din meniurile contextuale ale unui rand."""
    try:
        if not cm:
            return cm
        from resources.lib.core.config import PLUGIN_URL
        out = []
        changed = False
        for e in cm:
            try:
                lbl, cmd = e[0], str(e[1] or '')
            except Exception:
                out.append(e)
                continue
            new = _REL_CMD_RE.sub(lambda m: m.group(1) + PLUGIN_URL + '?', cmd)
            if new == cmd:
                out.append(e)
                continue
            changed = True
            if isinstance(e, (list, tuple)) and len(e) > 2:
                out.append((lbl, new) + tuple(e[2:]))
            else:
                out.append((lbl, new))
        return out if changed else cm
    except Exception:
        return cm


def _notify_links_repaired(n):
    """Notifica o singura data pe sesiune ca linkurile relative au fost reparate."""
    try:
        import os
        from resources.lib.core.config import ADDON_PATH
        if xbmcgui.Window(10000).getProperty('tmdbmovies.links_repaired_notified') == 'true':
            return
        xbmcgui.Window(10000).setProperty('tmdbmovies.links_repaired_notified', 'true')
        try:
            from resources.lib.providers.watched_provider import get_color as _pc
            _color = _pc()
        except Exception:
            _color = 'FF6AFB92'
        xbmcgui.Dialog().notification(
            '[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]',
            'Repaired broken links in [B][COLOR %s]Up Next[/COLOR][/B]' % _color,
            os.path.join(ADDON_PATH, 'icon.png'), 4000, False)
    except Exception:
        pass


def render_from_fast_cache(items, view_type=None):
    """Deseneaza lista instantaneu din datele cached folosind Batch Add.

    view_type: override Set Views pentru aceasta listare (ex. 'episode_lists').
    """
    # Orele de difuzare nu sint "coapte" in label: tokenul din cache e inlocuit aici
    # cu ora reala din sqlite (o singura conexiune pentru toata lista). Asa lista
    # cache-uita se auto-vindeca fara re-prefetch la fiecare deschidere.
    items = apply_air_times_to_cache_items(items)
    try:
        _patch_watched_flags(items)
    except Exception:
        pass
    try:
        _patch_resume_flags(items)
    except Exception:
        pass
    handle = _handle()
    items_to_add = []
    _repaired = 0

    for item in items:
        _u = _abs_url(item.get('url'))
        if _u != item.get('url'):
            item['url'] = _u
            _repaired += 1
        _cm = _abs_cm(item.get('cm'))
        if _cm is not item.get('cm'):
            item['cm'] = _cm
            _repaired += 1
        # Reconstructie ListItem daca vine din JSON (warmup)
        if 'li' in item and isinstance(item['li'], xbmcgui.ListItem):
            li = item['li']
        else:
            li = xbmcgui.ListItem(item['label'])
            li.setArt(item['art'])

            tag = li.getVideoInfoTag()
            info = item['info']

            tag.setMediaType(info.get('mediatype', 'video'))
            tag.setTitle(info.get('title', ''))
            tag.setPlot(info.get('plot', ''))
            _safe_set_prop(li, 'dbtype', info.get('mediatype', 'video'))

            # --- FIX BUG AN (None) ---
            if info.get('year'):
                try:
                    # Convertim in string apoi verificam daca e cifra
                    year_str = str(info['year'])
                    if year_str.isdigit():
                        tag.setYear(int(year_str))
                except:
                    pass # Daca e "None" sau gol, pur si simplu nu setam anul
            # -------------------------

            if info.get('rating'): tag.setRating(float(info['rating']))
            if info.get('votes'): tag.setVotes(int(info['votes']))
            if info.get('duration'): tag.setDuration(int(info['duration']))
            if info.get('premiered'): tag.setPremiered(info['premiered'])
            if info.get('studio'):
                st_val = info['studio']
                # Verificam daca e deja o lista, daca nu, o punem noi intr-una
                if isinstance(st_val, list):
                    tag.setStudios(st_val)
                else:
                    tag.setStudios([str(st_val)])
            if info.get('genre'):
                if isinstance(info['genre'], list):
                    tag.setGenres(info['genre'])
                elif isinstance(info['genre'], str):
                    tag.setGenres(info['genre'].split(', '))
            if info.get('mpaa'): tag.setMpaa(str(info['mpaa']))
            if info.get('season'):
                try:
                    tag.setSeason(int(info['season']))
                except:
                    pass
            if info.get('episode'):
                try:
                    tag.setEpisode(int(info['episode']))
                except:
                    pass
            if info.get('tvshowtitle'):
                tag.setTvShowTitle(str(info['tvshowtitle']))
            # Metadata pe care randarea live (set_metadata) o aplica si care se
            # pierdeau pe calea din cache: motto (VideoInfoPlotVar = Tagline+Plot),
            # titlu original, regizori/scriitori si unique IDs.
            if info.get('tagline'):
                tag.setTagLine(str(info['tagline']))
            if info.get('originaltitle'):
                tag.setOriginalTitle(str(info['originaltitle']))
            if info.get('director'):
                tag.setDirectors(info['director'] if isinstance(info['director'], list) else [str(info['director'])])
            if info.get('writer'):
                tag.setWriters(info['writer'] if isinstance(info['writer'], list) else [str(info['writer'])])
            _uid = item.get('unique_ids')
            if _uid:
                try:
                    _default = 'imdb' if 'imdb' in _uid else 'tmdb'
                    tag.setUniqueIDs(_uid, _default)
                except:
                    pass

            # APLICAM BIFA DOAR DACA NU E FOLDER (Butonul Next nu are bifa)
            if not item['is_folder']:
                if info.get('playcount') == 1:
                    tag.setPlaycount(1)
                else:
                    tag.setPlaycount(0)

                # Intotdeauna verificam daca exista resume_time (chiar daca e watched, poate utilizatorul l-a reinceput)
                if item.get('resume_time') and item.get('total_time'):
                    set_resume_point(li, item['resume_time'], item['total_time'])
                elif info.get('playcount') == 1:
                    tag.setResumePoint(0.0, 0.0)
            else:
                if info.get('playcount') == 1:
                    tag.setPlaycount(1)
                else:
                    tag.setPlaycount(0)

            if item.get('cm'):
                li.addContextMenuItems(item['cm'])

            # Restaurare proprietati (badge episode_type + watched counts AF3)
            # Fara ele, randarea din fast cache pierde badge-urile si cercul cu episoade ramase
            _props = item.get('properties') or {}
            for _k, _v in _props.items():
                if _v:
                    _safe_set_prop(li, _k, str(_v))

        items_to_add.append((item['url'], li, item['is_folder']))

    if _repaired:
        log(f"[LIST] Reparate {_repaired} linkuri relative din cache")
        _notify_links_repaired(_repaired)

    xbmcplugin.addDirectoryItems(handle, items_to_add, len(items_to_add))

    _content = ''
    if items:
        try:
            _content = (items[0]['info'].get('mediatype', 'movies') or 'movies') + 's'
        except Exception:
            _content = 'movies'
        xbmcplugin.setContent(handle, _content)
    xbmcplugin.endOfDirectory(handle, cacheToDisc=True)
    # Set Views: DOAR override explicit de la apelant. Derivarea din content a fost
    # eliminata intentionat: 'episodes' si 'episode_lists' au EXACT acelasi content,
    # deci nicio derivare nu le poate distinge. Fara override -> nu aplicam nimic
    # (fallback sigur) si logam, ca sa depistam call site-ul care uita view_type.
    if view_type:
        _set_views_apply(view_type, _content or None)
    else:
        log('[SET VIEWS] render_from_fast_cache apelat fara view_type (content=%r) - nu se aplica nimic' % (_content,))


def next_episodes_cache_key(params=None, use_tmdb=None, use_mdblist=None,
                            use_simkl=None, use_punchplay=None, use_local=None):
    """Cheia de fast cache pentru listele Up Next (identica cu cea din tmdb_api).

    Functia e aici, nu in tmdb_api, tocmai ca entry.py sa poata verifica hit-ul
    in cache SAU sa construiasca lista NOUA fara sa importe modulul greu.
    Providerul vine din providerul ACTIV de watched status (nu din params) -
    altfel am putea servi lista altui provider.
    """
    params = params or {}
    if use_tmdb is None:
        use_tmdb = str(params.get('use_tmdb') or '') == 'true'
    if use_mdblist is None and use_simkl is None and use_punchplay is None and use_local is None:
        # apelul din entry.py: providerul trebuie citit din setare
        if use_tmdb:
            prov = 'tmdb'
        else:
            try:
                from resources.lib.providers.watched_provider import _get_provider_raw
                prov = _get_provider_raw()
            except Exception:
                prov = 'trakt'
    else:
        prov = ('tmdb' if use_tmdb else ('local' if use_local else ('simkl' if use_simkl else
               ('mdblist' if use_mdblist else ('punchplay' if use_punchplay else 'trakt')))))
    try:
        from resources.lib.core.config import ADDON
        show_future = ADDON.getSetting('upnext_show_future') == 'true'
    except Exception:
        show_future = False
    try:
        unstarted = 1 if ADDON.getSetting('tmdb_upnext_show_unstarted') == 'true' else 0
    except Exception:
        unstarted = 1
    try:
        air_time_on = 1 if ADDON.getSetting('show_air_time') == 'true' else 0
    except Exception:
        air_time_on = 0
    return "next_episodes_all_future_%s_%s_%d_%s_%d" % (
        prov, str(show_future), unstarted, NEXT_EPISODES_LABEL_VERSION, air_time_on)


def remember_upnext_view(variant):
    """Memoram ce lista Up Next era vizibila ('provider' sau 'tmdb').

    In timpul redarii Container.FolderPath este GOL (de asta conditia veche
    'not container_path'), deci threadul de avansare nu poate afla ce lista va
    re-randa userul. Fara aceasta amintire, pre-randarea nu s-ar declanesa niciodata.

    Se salveaza si intr-un FISIER, ca sa supravietuiasca repornirii: la prima
    pre-randare dupa un restart, proprietatea de window e goala, iar fara
    persistenta se ghicea varianta 'provider' - chiar daca userul foloseste
    'tmdb'. Pre-randarea construia atunci lista gresita, iar deschiderea
    listei reale reconstruia tot de la zero (masurat: 8.7s pe Android).

    FISIER, NU SETARE KODI: ADDON.setSetting() declanseaza evenimentul de
    schimbare a setarilor, iar onSettingsChanged apeleaza clear_all_fast_cache()
    -> cache-ul de liste se gola la fiecare randare Up Next (cu tot cu lista
    tocmai construita). Masurat: intrarea in Up Next era cold de fiecare data.
    """
    try:
        import xbmcgui as _xg
        w = _xg.Window(10000)
        if w.getProperty('tmdbmovies.upnext_view') == (variant or ''):
            return
        w.setProperty('tmdbmovies.upnext_view', variant or '')
    except Exception:
        pass
    try:
        import os
        import xbmcvfs
        from resources.lib.core.config import ADDON_DATA_DIR
        _p = os.path.join(ADDON_DATA_DIR, 'upnext_variant.txt')
        _cur = ''
        try:
            _f = xbmcvfs.File(_p, 'r')
            _cur = _f.read()
            _f.close()
        except Exception:
            _cur = ''
        if _cur != (variant or ''):
            _f = xbmcvfs.File(_p, 'w')
            _f.write(variant or '')
            _f.close()
    except Exception:
        pass


def get_last_upnext_variant():
    """Ultima varianta Up Next folosita de user, din fisier (sau '').

    Fisier, nu setare Kodi: o setare ar declansa onSettingsChanged ->
    clear_all_fast_cache() -> golirea cache-ului de liste la fiecare randare.
    """
    try:
        import os
        import xbmcvfs
        from resources.lib.core.config import ADDON_DATA_DIR
        _p = os.path.join(ADDON_DATA_DIR, 'upnext_variant.txt')
        _f = xbmcvfs.File(_p, 'r')
        _v = _f.read()
        _f.close()
        _v = (_v or '').strip()
        return _v if _v in ('tmdb', 'provider') else ''
    except Exception:
        return ''


def prebuild_busy(wait=0.0):
    """Intreaba daca o pre-randare ruleaza; la wait>0 asteapta upana acolo."""
    import time as _t
    end = _t.time() + max(0.0, wait)
    while True:
        try:
            import xbmcgui as _xg
            busy = _xg.Window(10000).getProperty('tmdbmovies.prebuild_busy') == 'true'
        except Exception:
            return False
        if not busy or _t.time() >= end:
            return busy
        _t.sleep(0.1)


def snapshot_upnext_cache():
    """Salveaza listele Up Next din cache, inainte de invalidare.

    Versiunea cache-ului de liste e UN SINGUR property global
    (tmdbmovies_fast_cache_version), deci nu putem invalida "tot exceptand
    Up Next" - dar putem pastra datele peste bump si sa le scriem inapoi.

    De ce conteaza: la oprirea din player, invalidarea completa face ca
    listele sa se reconstruiasca, iar bifa de vizionat sa apara imediat
    (corect). Dar Up Next poate avea 160 de randuri, iar reconstructia dura
    secunde -> container negru cu BusyDialog. Pastrand doar Up Next, el
    ramane instant, iar restul listelor se reconstruiesc corect.
    """
    out = {}
    try:
        from resources.lib.core.cache import get_fast_cache
        for params in ({'use_tmdb': 'true'}, {}):
            try:
                key = next_episodes_cache_key(params)
                items = get_fast_cache(key)
                if items:
                    out[key] = items
            except Exception:
                continue
    except Exception:
        return {}
    return out


def _prebuild_both_variants(min_ts=0.0):
    """Incalzeste ambele liste Up Next (TMDb + provider) in cache.

    Ruleaza dupa sync: listele trebuie sa fie gata la prima accesare dupa un
    restart, fara sa reconstruiasca tot de la zero.

    min_ts: asteapta ca randul nou sa fie scris (min_ts = momentul marcajului),
    ca pre-randarea sa nu construiasca lista cu randul vechi.
    """
    _variants = ['provider']
    try:
        from resources.lib.core.config import ADDON
        if (ADDON.getSetting('tmdb_upnext_enabled') or 'true') != 'false':
            _variants.append('tmdb')
    except Exception:
        _variants.append('tmdb')
    # Varianta VIZIBILA se construieste PRIMA. Fiecare build costa 10-13s pe
    # un box Android; daca lista de pe ecran era a doua, safety pass-ul din
    # player astepta degeaba ~10s si apoi randa cache-ul vechi (log 09:50).
    _visible = ''
    try:
        import xbmcgui as _xgv
        _visible = (_xgv.Window(10000).getProperty('tmdbmovies.upnext_view') or '').strip()
    except Exception:
        _visible = ''
    if _visible not in ('tmdb', 'provider'):
        try:
            _visible = get_last_upnext_variant()
        except Exception:
            _visible = ''
    if _visible in _variants:
        _variants = [_visible] + [v for v in _variants if v != _visible]
    _done = {}
    for _v in _variants:
        try:
            from resources.lib.providers.watched_provider import _prebuild_upnext_cache
            _done[_v] = bool(_prebuild_upnext_cache('', min_ts, False, _v))
        except Exception:
            _done[_v] = False
    try:
        from resources.lib.core.utils import log
        # Log pe fiecare varianta, cu rezultatul real. Inainte se scria
        # "ambele variante incalzite in cache" neconditionat, chiar si cind
        # una (sau amindoua) iesise imediat pe usa din busy/lock - de aici
        # logurile care contraziceau realitatea (log 09:50: 35.414 "ambele
        # variante", desi build-ul real a terminat la 42.421).
        log("[UP NEXT] pre-randare variante: " + ', '.join(
            f"{_v}={'ok' if _ok else 'nu'}" for _v, _ok in _done.items()))
    except Exception:
        pass


def restore_upnext_cache(snap):
    """Scrie inapoi listele Up Next pastrate de snapshot_upnext_cache()."""
    if not snap:
        return 0
    n = 0
    try:
        from resources.lib.core.cache import set_fast_cache
        for key, items in snap.items():
            try:
                set_fast_cache(key, items)
                n += 1
            except Exception:
                continue
    except Exception:
        return 0
    return n


def try_render_cached_next_episodes(params=None, view_type='episode_lists'):
    """Randare immediate daca lista Up Next e deja in fast cache.

    Cheia de cache e construita aici, deci nu e nevoie de tmdb_api/provideri:
    la intoarcerea din player asta scade ~700ms de importuri. False = nu era
    cache, apelantul continua pe calea normala (import greu + constructie).
    Daca o pre-randare ruleaza chiar acum (threadul de avansare), o asteptam
    scurt: asa randarea prinde lista noua in loc sa o construiasca din nou.
    """
    try:
        from resources.lib.core.cache import get_fast_cache
        key = next_episodes_cache_key(params)
        cached = get_fast_cache(key)
        if not cached and prebuild_busy(wait=3.0):
            cached = get_fast_cache(key)
        if not cached:
            return False
        remember_upnext_view('tmdb' if str((params or {}).get('use_tmdb') or '') == 'true' else 'provider')
        render_from_fast_cache(cached, view_type=view_type)
        return True
    except Exception as e:
        log(f"[LIST] cache-hit Up Next esuat: {e}")
        return False