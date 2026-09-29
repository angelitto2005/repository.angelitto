# -*- coding: utf-8 -*-
"""
Set Views - view-uri memorate per categorie (skin + view_type), pattern POV.

- Salvare: FocusId-ul containerului curent (din folderul "Click here to save current view").
- Aplicare: dupa endOfDirectory -> asteapta Container.Content (max ~2s) si executa
  Container.SetViewMode(view_id). Listarile care nu seteaza content (ex. cloud/debrid)
  primesc content=None -> asteptare scurta fixa (fara poll, ca sa nu pierdem 2s degeaba).
- Reset: sterge tabela proprie + randurile pluginului din ViewModes6.db (memoria Kodi
  per folder), cu confirmare.
- Fara fallback hardcodat: daca nu exista view salvat, comportamentul Kodi ramane neschimbat.
"""
import os
import time

import xbmc
import xbmcgui
import xbmcvfs

PLUGIN_ID = 'plugin.video.tmdbmovies'
TITLE = '[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]'

VIEW_TYPES = ('main', 'movies', 'tvshows', 'seasons', 'episodes', 'episode_lists', 'cloud')

VIEW_LABELS = {
    'main': 'Main (Root menus)',
    'movies': 'Movies',
    'tvshows': 'TV Shows',
    'seasons': 'Seasons',
    'episodes': 'Episodes',
    'episode_lists': 'Episode Lists',
    'cloud': 'Cloud / Files',
}

# Content-ul folosit la randarea folderelor de salvare si la poll-ul din apply_view.
CONTENT = {
    'main': '',
    'movies': 'movies',
    'tvshows': 'tvshows',
    'seasons': 'seasons',
    'episodes': 'episodes',
    'episode_lists': 'episodes',
    'cloud': 'files',
}

# Meniurile pot raporta '' / 'files' / 'videos' in functie de skin/Kodi -> acceptam toate.
ACCEPT = {'main': ('', 'files', 'videos')}

_POLL_TIMEOUT = 2.0   # secunde, cu iesire imediata la match (POV foloseste 3s)
_POLL_STEP = 0.05
_UNKNOWN_WAIT = 0.30  # secunde, pentru listarile fara content cunoscut (debrid/cloud)


def _log(msg, level=xbmc.LOGDEBUG):
    try:
        xbmc.log('[TMDb Movies][views] ' + str(msg), level)
    except Exception:
        pass


def _icon():
    try:
        from resources.lib.config import ADDON_PATH
        return os.path.join(ADDON_PATH, 'resources', 'media', 'settings.png')
    except Exception:
        return xbmcgui.NOTIFICATION_INFO


def _db_path():
    base = ''
    try:
        from resources.lib.config import ADDON_DATA_DIR
        base = ADDON_DATA_DIR or ''
    except Exception:
        base = ''
    if not base:
        try:
            base = xbmcvfs.translatePath('special://profile/addon_data/' + PLUGIN_ID + '/')
        except Exception:
            base = ''
    return os.path.join(base, 'views.db') if base else 'views.db'


def _ensure_dir():
    """Creeaza folderul de profil daca lipseste (ca makeFile din Umbrella)."""
    try:
        base = os.path.dirname(_db_path())
        if base and not os.path.isdir(base):
            os.makedirs(base, exist_ok=True)
    except Exception:
        pass


def _skin():
    try:
        return xbmc.getSkinDir() or ''
    except Exception:
        return ''


def view_for_content(content):
    """Mapare content -> categorie (o singura regula, folosita peste tot)."""
    content = (content or '').strip().lower()
    if content in ('movies', 'tvshows', 'seasons', 'episodes', 'episode_lists'):
        return content
    return 'main'


def _read_saved(view_type):
    """Citire directa din views.db (fara creare de fisier/tabela). '' daca nu exista."""
    skin = _skin()
    if not skin or not view_type:
        return ''
    try:
        import sqlite3
        path = _db_path()
        if not os.path.exists(path):
            return ''
        con = sqlite3.connect(path, timeout=10)
        try:
            row = con.execute("SELECT view_id FROM views WHERE skin=? AND view_type=?",
                              (skin, view_type)).fetchone()
            return str(row[0]) if row and row[0] else ''
        finally:
            con.close()
    except Exception as e:
        _log('read error: %r' % (e,))
        return ''


def get_saved_view(view_type):
    """View id-ul salvat pentru skinul curent ('' daca nu exista)."""
    return _read_saved(view_type)


def save_view(view_type):
    """Salveaza view-ul curent (FocusId) pentru categoria data + skinul curent."""
    if view_type not in VIEW_TYPES:
        return
    skin = _skin()
    if not skin:
        return
    try:
        vid = int(xbmcgui.Window(xbmcgui.getCurrentWindowId()).getFocusId())
    except Exception:
        vid = -1
    if vid <= 0:
        _log('save aborted: FocusId invalid (%s) pentru %s' % (vid, view_type), xbmc.LOGWARNING)
        return
    try:
        import sqlite3
        _ensure_dir()
        con = sqlite3.connect(_db_path(), timeout=10)
        try:
            cur = con.cursor()
            cur.execute("CREATE TABLE IF NOT EXISTS views (skin TEXT, view_type TEXT, view_id TEXT, UNIQUE(skin, view_type));")
            cur.execute("DELETE FROM views WHERE (skin=? AND view_type=?)", (skin, view_type))
            cur.execute("INSERT INTO views VALUES (?, ?, ?)", (skin, view_type, str(vid)))
            con.commit()
        finally:
            con.close()
    except Exception as e:
        _log('save error: %r' % (e,), xbmc.LOGWARNING)
        try:
            xbmcgui.Dialog().notification(TITLE, 'Could not save the view', xbmcgui.NOTIFICATION_WARNING, 3000, False)
        except Exception:
            pass
        return
    try:
        view_name = xbmc.getInfoLabel('Container.Viewmode') or str(vid)
    except Exception:
        view_name = str(vid)
    _log('saved %s=%s [skin=%s]' % (view_type, vid, skin))
    try:
        xbmcgui.Dialog().notification(TITLE, '%s: %s' % (VIEW_LABELS.get(view_type, view_type), view_name),
                                      _icon(), 3000, False)
    except Exception:
        pass


def apply_view(view_type, content=None):
    """Aplica DUPA endOfDirectory view-ul salvat pentru categoria data.

    content: Container.Content asteptat (str sau tuple) sau None = listarea nu seteaza
    content (nedeterminist, ex. debrid) -> asteptare scurta fixa, fara poll.
    Sar peste widgeturi/Home (Container.PluginName nu e pluginul nostru), ca la POV.
    """
    if view_type not in VIEW_TYPES:
        return
    try:
        if PLUGIN_ID not in (xbmc.getInfoLabel('Container.PluginName') or ''):
            return
    except Exception:
        return
    view_id = _read_saved(view_type)
    if not view_id or not str(view_id).isdigit():
        return
    if content is None:
        xbmc.sleep(int(_UNKNOWN_WAIT * 1000))
    else:
        accepted = ACCEPT.get(view_type)
        if accepted is None:
            accepted = (content,) if isinstance(content, str) else tuple(content)
        else:
            accepted = tuple(accepted)
            if isinstance(content, str) and content not in accepted:
                accepted = accepted + (content,)
        deadline = time.time() + _POLL_TIMEOUT
        matched = False
        current = ''
        while time.time() < deadline:
            try:
                current = xbmc.getInfoLabel('Container.Content') or ''
            except Exception:
                current = ''
            if current in accepted:
                matched = True
                break
            xbmc.sleep(int(_POLL_STEP * 1000))
        if not matched:
            # Aplicam oricum: poll-ul e doar o garda anti-container-vechi, iar 2s acopera
            # lejer swap-ul listei. Log DEBUG ca sa depistam valorile neasteptate.
            _log('poll timeout for %s (accepted=%r, current=%r) - applying anyway'
                 % (view_type, accepted, current))
    try:
        xbmc.executebuiltin('Container.SetViewMode(%s)' % str(view_id))
        _log('applied %s=%s' % (view_type, view_id))
    except Exception as e:
        _log('apply error: %r' % (e,))


def apply_for_content(content, view_type=None):
    """Helper pentru ramuri dinamice: content == 'movies'/'tvshows'/... (sau None)."""
    if content is None:
        return apply_view(view_type or 'main', None)
    content = content or ''
    return apply_view(view_type or view_for_content(content), content)


def clear_views():
    """Sterge view-urile salvate + memoria Kodi per folder pentru plugin (cu confirmare)."""
    try:
        if not xbmcgui.Dialog().yesno('[B]Set Views[/B]',
                                      'Reset all saved views for [B]all skins[/B]?\n'
                                      "Kodi's per-folder view memory for this addon will be cleared too."):
            return
    except Exception:
        return
    partial = False
    try:
        import sqlite3
        path = _db_path()
        if os.path.exists(path):
            con = sqlite3.connect(path, timeout=10)
            try:
                cur = con.cursor()
                cur.execute("DELETE FROM views")
                con.commit()
                try:
                    cur.execute("VACUUM")
                except Exception:
                    pass
            finally:
                con.close()
    except Exception as e:
        partial = True
        _log('reset db error: %r' % (e,), xbmc.LOGWARNING)
    try:
        import sqlite3
        vdb = xbmcvfs.translatePath('special://profile/Database/ViewModes6.db')
        if os.path.exists(vdb):
            con = sqlite3.connect(vdb, timeout=10)
            try:
                cur = con.cursor()
                cur.execute("DELETE FROM view WHERE path LIKE ?", ('plugin://' + PLUGIN_ID + '/%',))
                con.commit()
            finally:
                con.close()
    except Exception as e:
        partial = True
        _log('reset kodi db error: %r' % (e,), xbmc.LOGWARNING)
    _log('views reset (partial=%s)' % partial, xbmc.LOGINFO)
    try:
        xbmcgui.Dialog().notification(TITLE, 'Views reset (partial)' if partial else 'Views reset',
                                      _icon(), 3000, False)
    except Exception:
        pass
