# -*- coding: utf-8 -*-
import sys
import os
import re
import urllib.parse
import xbmc
import xbmcgui
import xbmcplugin
import xbmcvfs

from resources.lib.config import ADDON as PROXIED_ADDON, provider_title, _fmt_dmy

DEBRID_ACTIONS = {
    'debrid_menu',
    'debrid_torbox',
    'debrid_rd',
    'debrid_tb_cloud',
    'debrid_tb_folder',
    'debrid_tb_airlock',
    'debrid_tb_account',
    'debrid_rd_cloud',
    'debrid_rd_folder',
    'debrid_rd_downloads',
    'debrid_rd_account',
    'debrid_set_torbox_key',
    'debrid_set_rd_key',
    'debrid_disconnect',
    'debrid_tb_delete',
    'debrid_tb_toggle_airlock',
    'debrid_rd_delete_torrent',
    'debrid_rd_delete_download',
    'debrid_tb_clear_cache',
    'debrid_rd_clear_cache',
    'debrid_play',
    'debrid_download',
    'debrid_refresh',
}

_TB_COLOR = 'FF00FA9A'
_RD_COLOR = 'FF70A1FF'
_HL_COLOR = 'FFFDBD01'
_ERR_COLOR = 'FFFF5555'

MEDIA_LABELS = {
    'torrents': 'Torrent',
    'usenet': 'Usenet',
    'webdl': 'WebDownload',
}

_HANDLE = None
_BASE_URL = None
_ADDON = None

_CACHE_TTL = 1800


def _ensure_globals():
    global _ADDON, _BASE_URL, _HANDLE
    if _ADDON is None:
        _ADDON = PROXIED_ADDON
    if _BASE_URL is None:
        _BASE_URL = sys.argv[0]
    if _HANDLE is None:
        try:
            _HANDLE = int(sys.argv[1])
        except Exception:
            _HANDLE = -1


def _icon(name):
    root = xbmcvfs.translatePath(_ADDON.getAddonInfo('path')).replace('\\', '/')
    if not root.endswith('/'):
        root += '/'
    return root + 'resources/media/' + name


def _tb_icon():
    return _icon('torbox.png')


def _rd_icon():
    return _icon('realdebrid.png')


def _build_url(query):
    _ensure_globals()
    return _BASE_URL + '?' + urllib.parse.urlencode(query)


def _page_limit():
    from resources.lib.config import get_page_limit_value
    try:
        return int(get_page_limit_value())
    except Exception:
        return 20


_VIDEO_EXT = ('.mkv', '.mp4', '.avi', '.mov', '.m4v', '.webm', '.mpg', '.mpeg', '.wmv', '.m2ts')

_JUNK_RE = re.compile(r'\b(cam|camrip|hdcam|hdts|hdtc|ts|telesync|trailer|sample|proof|screener|telecine|workprint)\b', re.IGNORECASE)


def _is_junk_name(name):
    try:
        return bool(_JUNK_RE.search(str(name or '')))
    except Exception:
        return False


def _kodi_major_local():
    try:
        return int(str(xbmc.getInfoLabel('System.BuildVersion') or '').split('.')[0])
    except Exception:
        return 22


def _page_num(params):
    try:
        return max(1, int(params.get('page', '1') or 1))
    except Exception:
        return 1


def _expiry_us_format():
    try:
        from resources.lib.config import ADDON as _cfg
        return (_cfg.getSetting('date_format') or '0') == '1'
    except Exception:
        return False


def _parse_expiry(value):
    try:
        import datetime as _dtm
        if value is None:
            return None
        if isinstance(value, _dtm.datetime):
            return value.replace(tzinfo=None) if value.tzinfo else value
        if isinstance(value, _dtm.date):
            return _dtm.datetime(value.year, value.month, value.day)
        s = str(value).strip()
        if not s:
            return None
        if re.match(r'^-?\d+(\.\d+)?$', s):
            return _dtm.datetime.fromtimestamp(float(s))
        t = s.replace('Z', '+00:00')
        try:
            dt = _dtm.datetime.fromisoformat(t)
            return dt.replace(tzinfo=None) if dt.tzinfo else dt
        except Exception:
            pass
        for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
            try:
                return _dtm.datetime.strptime(s.split('.')[0], fmt)
            except Exception:
                continue
    except Exception:
        pass
    return None


def _fmt_expiry_date(value):
    dt = _parse_expiry(value)
    if dt is None:
        return ''
    try:
        if _expiry_us_format():
            return dt.strftime('%m/%d/%Y')
        return dt.strftime('%d.%m.%Y')
    except Exception:
        return ''


def _expiry_days_left(value):
    dt = _parse_expiry(value)
    if dt is None:
        return None
    try:
        import datetime as _dtm
        return max(0, (dt - _dtm.datetime.now()).days)
    except Exception:
        return None


def _end(succeeded=True, cache=False):
    _ensure_globals()
    xbmcplugin.endOfDirectory(_HANDLE, succeeded=succeeded, cacheToDisc=cache)


def _add_dir(url, li, is_folder=True):
    _ensure_globals()
    xbmcplugin.addDirectoryItem(_HANDLE, url, li, is_folder)


def _notify(msg, icon=None, ms=3000):
    xbmcgui.Dialog().notification(provider_title('tmdb', name='TMDb Movies'), msg, icon or _icon('debrid.png'), ms, False)


def _count(label, count):
    if count > 0:
        return f'{label} [B][COLOR {_HL_COLOR}]({count})[/COLOR][/B]'
    return label


def _fmt_size(num_bytes):
    try:
        b = float(num_bytes or 0)
    except Exception:
        b = 0.0
    if b >= 1024 ** 3:
        return f'{b / (1024 ** 3):.2f} GB'
    if b >= 1024 ** 2:
        return f'{b / (1024 ** 2):.2f} MB'
    if b > 0:
        return f'{b / 1024.0:.1f} KB'
    return ''


def _fmt_pct(progress):
    try:
        p = float(progress or 0)
        if p <= 1.0:
            p *= 100.0
        return int(round(p))
    except Exception:
        return 0


def _cache_get(key):
    try:
        from resources.lib.cache import MainCache
        return MainCache().get(key)
    except Exception:
        return None


def _cache_set(key, data, hours=_CACHE_TTL / 3600.0):
    try:
        from resources.lib.cache import MainCache
        MainCache().set(key, data, expiration=hours)
    except Exception:
        pass


def _cache_del(key):
    try:
        from resources.lib.cache import MainCache
        MainCache().delete(key)
    except Exception:
        pass


def _cache_del_prefix(prefix):
    try:
        from resources.lib.cache import MainCache
        MainCache().delete_prefix(prefix)
    except Exception:
        pass


def invalidate_playback_cache(debrid_service):
    try:
        srv = str(debrid_service or '').lower().replace('-', '').replace(' ', '')
        if srv in ('realdebrid', 'rd'):
            _cache_del_prefix('tmdbmovies_rd_')
        elif srv in ('torbox', 'tb'):
            _cache_del_prefix('tmdbmovies_tb_')
    except Exception:
        pass


def _cached_call(key, fetch_fn):
    data = _cache_get(key)
    if data is not None:
        return data, None
    try:
        data = fetch_fn()
    except Exception as e:
        return None, str(e)
    _cache_set(key, data)
    return data, None


def _count_tb_finished_cached():
    total = 0
    for mt in ('torrents', 'usenet', 'webdl'):
        items = _cache_get(f'tmdbmovies_tb_cloud_{mt}')
        if isinstance(items, list):
            total += sum(1 for it in items if _tb_finished(it))
    return total


def _error_item(message, retry_query, icon=None):
    li = xbmcgui.ListItem(label=f'[B][COLOR {_ERR_COLOR}]Error:[/COLOR][/B] {message} - Click to retry')
    icon = icon or _icon('debrid.png')
    li.setArt({'icon': icon, 'thumb': icon})
    li.addContextMenuItems([('Refresh', f'RunPlugin({_build_url({"mode": "debrid_refresh"})})')])
    _add_dir(_build_url(retry_query), li, True)


def _empty_item(label='Cloud is empty', icon=None):
    li = xbmcgui.ListItem(label=label)
    icon = icon or _icon('debrid.png')
    li.setArt({'icon': icon, 'thumb': icon})
    _add_dir(_build_url({}), li, False)


def _add_inactive_row(label, icon):
    li = xbmcgui.ListItem(label=label)
    li.setArt({'icon': icon, 'thumb': icon})
    _add_dir(_build_url({'mode': 'debrid_refresh'}), li, False)


def _add_service_dir(label, query, icon):
    li = xbmcgui.ListItem(label=label)
    li.setArt({'icon': icon, 'thumb': icon, 'poster': icon})
    cm = [('Refresh', f'RunPlugin({_build_url({"mode": "debrid_refresh"})})')]
    li.addContextMenuItems(cm)
    _add_dir(_build_url(query), li, True)


def _add_account_item(label, query, icon):
    li = xbmcgui.ListItem(label=label)
    li.setArt({'icon': icon, 'thumb': icon, 'poster': icon})
    _add_dir(_build_url(query), li, False)


def _add_connect_item(label, query, icon):
    li = xbmcgui.ListItem(label=label)
    li.setArt({'icon': icon, 'thumb': icon, 'poster': icon})
    _add_dir(_build_url(query), li, False)


def _add_refresh_item(label, icon):
    li = xbmcgui.ListItem(label=f'[B][COLOR {_HL_COLOR}]{label}[/COLOR][/B]')
    li.setArt({'icon': icon, 'thumb': icon})
    li.addContextMenuItems([('Refresh', f'RunPlugin({_build_url({"mode": "debrid_refresh"})})')])
    url = _build_url({'mode': 'debrid_menu'})
    _add_dir(url, li, False)


def _add_clear_cache_item(label, mode, icon):
    li = xbmcgui.ListItem(label=label)
    li.setArt({'icon': icon, 'thumb': icon})
    _add_dir(_build_url({'mode': mode}), li, False)


def _add_disconnect_item(label, provider, icon):
    li = xbmcgui.ListItem(label=label)
    li.setArt({'icon': icon, 'thumb': icon})
    _add_dir(_build_url({'mode': 'debrid_disconnect', 'provider': provider}), li, False)


def _rd_cloud_limit():
    return max(5, min(int(_page_limit() or 20), 100))


def _rd_cloud_key(page, limit):
    return f"tmdbmovies_rd_cloud_p{page}_l{limit}"


def _count_rd_cloud_cached():
    items = _cache_get(_rd_cloud_key(1, _rd_cloud_limit()))
    if isinstance(items, list):
        return sum(1 for it in items if isinstance(it, dict) and str(it.get('status') or '') == 'downloaded')
    return 0


def _view_main():
    _ensure_globals()

    tb_count = _count_tb_finished_cached()
    rd_count = _count_rd_cloud_cached()

    _add_service_dir(_count('[B][COLOR ' + _TB_COLOR + ']TorBox[/COLOR][/B]', tb_count),
                     {'mode': 'debrid_torbox'}, _tb_icon())
    _add_service_dir(_count('[B][COLOR ' + _RD_COLOR + ']Real-Debrid[/COLOR][/B]', rd_count),
                     {'mode': 'debrid_rd'}, _rd_icon())
    _end()


def _view_torbox():
    _ensure_globals()
    from resources.lib import torbox_api

    if not torbox_api.is_authenticated():
        _add_connect_item('[B][COLOR ' + _TB_COLOR + ']Connect TorBox[/COLOR][/B] (enter API key)',
                          {'mode': 'debrid_set_torbox_key'}, _tb_icon())
        _end()
        return

    counts = {}
    first_err = None
    first_mt = ''
    for mt in ('torrents', 'usenet', 'webdl'):
        items, err = _cached_call(f'tmdbmovies_tb_cloud_{mt}', lambda m=mt: torbox_api.user_cloud(m))
        counts[mt] = sum(1 for it in (items or []) if _tb_finished(it))
        if err and first_err is None:
            first_err = err
            first_mt = mt
    if first_err is not None:
        _error_item(first_err, {'mode': 'debrid_tb_cloud', 'mediatype': first_mt}, _tb_icon())

    _add_account_item('[B][COLOR ' + _TB_COLOR + ']TorBox Account[/COLOR][/B]', {'mode': 'debrid_tb_account'}, _tb_icon())
    if first_err is None:
        _add_service_dir(_count('[B]TorBox Torrent[/B]', counts.get('torrents', 0)), {'mode': 'debrid_tb_cloud', 'mediatype': 'torrents'}, _tb_icon())
        _add_service_dir(_count('[B]TorBox Usenet[/B]', counts.get('usenet', 0)), {'mode': 'debrid_tb_cloud', 'mediatype': 'usenet'}, _tb_icon())
        _add_service_dir(_count('[B]TorBox WebDownload[/B]', counts.get('webdl', 0)), {'mode': 'debrid_tb_cloud', 'mediatype': 'webdl'}, _tb_icon())

        air_count = 0
        for mt in ('torrents', 'usenet', 'webdl'):
            air_items = _cache_get(f'tmdbmovies_tb_cloud_{mt}')
            if isinstance(air_items, list):
                air_count += sum(1 for it in air_items if isinstance(it, dict) and it.get('airlocked') is True)
        _add_service_dir(_count('[B][COLOR FF00E5FF]AirLock[/COLOR][/B] (Extended Retention)', air_count),
                         {'mode': 'debrid_tb_airlock'}, _tb_icon())

    _add_clear_cache_item('[B][COLOR ' + _ERR_COLOR + ']Clear TorBox Cache[/COLOR][/B]', 'debrid_tb_clear_cache', _tb_icon())
    _add_disconnect_item('[B][COLOR ' + _ERR_COLOR + ']Disconnect TorBox[/COLOR][/B]', 'torbox', _tb_icon())
    _end()


def _view_rd():
    _ensure_globals()
    from resources.lib import realdebrid_api

    if not realdebrid_api.is_authenticated():
        _add_connect_item('[B][COLOR ' + _RD_COLOR + ']Connect Real-Debrid[/COLOR][/B] (enter API key)',
                          {'mode': 'debrid_set_rd_key'}, _rd_icon())
        _end()
        return

    items, err = _cached_call(_rd_cloud_key(1, _rd_cloud_limit()), lambda: realdebrid_api.user_cloud(1, _rd_cloud_limit()))
    if err:
        _error_item(err, {'mode': 'debrid_rd_cloud'}, _rd_icon())

    _add_account_item('[B][COLOR ' + _RD_COLOR + ']Real-Debrid Account Info[/COLOR][/B]', {'mode': 'debrid_rd_account'}, _rd_icon())
    if not err:
        _add_service_dir(_count('[B]Real-Debrid Cloud Storage[/B]', _count_rd_cloud_cached()), {'mode': 'debrid_rd_cloud'}, _rd_icon())
        _add_service_dir('[B]Real-Debrid History[/B]', {'mode': 'debrid_rd_downloads'}, _rd_icon())
    _add_clear_cache_item('[B][COLOR ' + _ERR_COLOR + ']Clear Real-Debrid Cache[/COLOR][/B]', 'debrid_rd_clear_cache', _rd_icon())
    _add_disconnect_item('[B][COLOR ' + _ERR_COLOR + ']Disconnect Real-Debrid[/COLOR][/B]', 'rd', _rd_icon())
    _end()


def _tb_finished(item):
    if not isinstance(item, dict):
        return False
    if item.get('download_finished') is True:
        return True
    name = str(item.get('name') or '')
    if not name:
        return False
    progress = _fmt_pct(item.get('progress'))
    if progress < 100:
        return False
    dl_state = str(item.get('download_state') or '').lower()
    if dl_state in ('downloading', 'metadl', 'checkingresumedata', 'paused', 'stalled (no seeds)'):
        return False
    return True


def _tb_status(item):
    dl_state = str(item.get('download_state') or '').strip()
    progress = _fmt_pct(item.get('progress'))
    if progress >= 100:
        return 'CACHED' if dl_state.lower() == 'cached' else 'FINISHED'
    return dl_state.upper() or 'ACTIVE'


def _view_tb_cloud(params):
    _ensure_globals()
    from resources.lib import torbox_api

    mediatype = params.get('mediatype', 'torrents')
    if mediatype not in ('torrents', 'usenet', 'webdl'):
        mediatype = 'torrents'
    page = _page_num(params)

    items, err = _cached_call(f'tmdbmovies_tb_cloud_{mediatype}', lambda: torbox_api.user_cloud(mediatype))
    if err:
        _error_item(err, {'mode': 'debrid_tb_cloud', 'mediatype': mediatype, 'page': str(page)}, _tb_icon())
        _end()
        return

    ordered = sorted((items or []),
                     key=lambda it: str(it.get('updated_at') or it.get('created_at') or ''), reverse=True)

    if not ordered:
        _empty_item('Cloud is empty', _tb_icon())
        _end()
        return

    limit = _page_limit()
    total_pages = max(1, -(-len(ordered) // limit))
    start = (page - 1) * limit
    chunk = ordered[start:start + limit]

    for it in chunk:
        if not isinstance(it, dict):
            continue
        if _tb_finished(it):
            _add_tb_folder_row(it, mediatype)
        else:
            nm = str(it.get('name') or 'Unnamed')
            if _is_junk_name(nm):
                continue
            pct = _fmt_pct(it.get('progress'))
            _add_inactive_row(f'[B]{_tb_status(it)} - {pct}%[/B] | [I]{nm}[/I]', _tb_icon())

    if page < total_pages:
        li = xbmcgui.ListItem(label='[B][COLOR ' + _HL_COLOR + ']Next Page >>[/COLOR][/B]')
        li.setArt({'icon': _tb_icon(), 'thumb': _tb_icon()})
        _add_dir(_build_url({'mode': 'debrid_tb_cloud', 'mediatype': mediatype, 'page': str(page + 1)}), li, True)

    _end()


def _add_tb_folder_row(item, mediatype):
    name = str(item.get('name') or 'Unnamed')
    if _is_junk_name(name):
        return
    size = _fmt_size(item.get('size'))
    created = _fmt_dmy(item.get('created_at') or '')
    status = _tb_status(item)
    parts = [f'[B]{status}[/B]']
    if size:
        parts.append(size)
    if created:
        parts.append(created)
    label = ' | '.join(parts) + f' | [I]{name}[/I]'
    airlocked = item.get('airlocked')
    if isinstance(airlocked, bool) and airlocked:
        label += ' | [B][COLOR FF00E5FF]AIRLOCK[/COLOR][/B]'

    li = xbmcgui.ListItem(label=label)
    li.setArt({'icon': _tb_icon(), 'thumb': _tb_icon(), 'poster': _tb_icon()})
    try:
        tag = li.getVideoInfoTag()
        tag.setTitle(name)
        tag.setPlot(f'{MEDIA_LABELS[mediatype]}: {name} | Status: {status} | Size: {size or "?"} | Added: {created or "?"}')
    except Exception:
        pass

    item_id = item.get('id')
    base_q = {'mode': 'debrid_tb_folder', 'mediatype': mediatype, 'item_id': str(item_id), 'name': name}
    cm = [
        ('Delete', f'RunPlugin({_build_url({"mode": "debrid_tb_delete", "mediatype": mediatype, "item_id": str(item_id), "name": name})})'),
    ]
    if isinstance(airlocked, bool):
        air_label = 'Remove from [B][COLOR FF00E5FF]AirLock[/COLOR][/B]' if airlocked else 'Add to [B][COLOR FF00E5FF]AirLock[/COLOR][/B]'
        cm.append((air_label, f'RunPlugin({_build_url({"mode": "debrid_tb_toggle_airlock", "mediatype": mediatype, "item_id": str(item_id), "name": name})})'))
    cm.append(('Refresh', f'RunPlugin({_build_url({"mode": "debrid_refresh"})})'))
    li.addContextMenuItems(cm)
    _add_dir(_build_url(base_q), li, True)


def _view_tb_airlock(params):
    _ensure_globals()
    from resources.lib import torbox_api
    page = _page_num(params)

    merged = []
    had_err = None
    for mt in ('torrents', 'usenet', 'webdl'):
        items, err = _cached_call(f'tmdbmovies_tb_cloud_{mt}', lambda m=mt: torbox_api.user_cloud(m))
        if err:
            had_err = err
            break
        for it in (items or []):
            if isinstance(it, dict) and it.get('airlocked') is True:
                it = dict(it)
                it['_mt'] = mt
                merged.append(it)

    if had_err:
        _error_item(had_err, {'mode': 'debrid_tb_airlock', 'page': str(page)}, _tb_icon())
        _end()
        return

    merged.sort(key=lambda it: str(it.get('updated_at') or it.get('created_at') or ''), reverse=True)

    if not merged:
        _empty_item('No AirLocked items', _tb_icon())
        _end()
        return

    limit = _page_limit()
    total_pages = max(1, -(-len(merged) // limit))
    start = (page - 1) * limit
    chunk = merged[start:start + limit]

    for it in chunk:
        _add_tb_folder_row(it, it.get('_mt') or 'torrents')

    if page < total_pages:
        li = xbmcgui.ListItem(label='[B][COLOR ' + _HL_COLOR + ']Next Page >>[/COLOR][/B]')
        li.setArt({'icon': _tb_icon(), 'thumb': _tb_icon()})
        _add_dir(_build_url({'mode': 'debrid_tb_airlock', 'page': str(page + 1)}), li, True)

    _end()


def _view_tb_folder(params):
    _ensure_globals()
    from resources.lib import torbox_api

    mediatype = params.get('mediatype', 'torrents')
    item_id = params.get('item_id', '')
    name = params.get('name', '')

    if not item_id:
        _empty_item('Invalid item', _tb_icon())
        _end()
        return

    try:
        info = torbox_api.user_folder(mediatype, item_id)
    except Exception as e:
        _error_item(str(e), {'mode': 'debrid_tb_cloud', 'mediatype': mediatype}, _tb_icon())
        _end()
        return

    if not isinstance(info, dict):
        _empty_item('Item not found on TorBox', _tb_icon())
        _end()
        return

    files = info.get('files')
    if not isinstance(files, list):
        files = []

    video_files = []
    for f in files:
        if not isinstance(f, dict):
            continue
        f_idx = f.get('id', 0)
        fname = str(f.get('name') or f.get('short_name') or '')
        if not fname.lower().endswith(_VIDEO_EXT):
            continue
        if _is_junk_name(fname):
            continue
        video_files.append((f_idx, fname, f.get('size')))

    if not video_files:
        _empty_item('No playable files', _tb_icon())
        _end()
        return

    video_files.sort(key=lambda t: -(t[2] or 0))
    for idx, (f_idx, fname, fsize) in enumerate(video_files, start=1):
        size = _fmt_size(fsize)
        label = f'{idx:02d} | [B]FILE[/B] | ' + (size + ' | ' if size else '') + f'[I]{fname}[/I]'
        li = xbmcgui.ListItem(label=label)
        li.setArt({'icon': _tb_icon(), 'thumb': _tb_icon(), 'poster': _tb_icon()})
        try:
            tag = li.getVideoInfoTag()
            tag.setTitle(fname)
            tag.setPlot(f'{MEDIA_LABELS.get(mediatype, "File")}: {name} | File: {fname} | Size: {size or "?"}')
        except Exception:
            pass
        li.setProperty('IsPlayable', 'true')
        play_q = {'mode': 'debrid_play', 'mediatype': mediatype, 'item_id': str(item_id), 'file_id': str(f_idx), 'name': name, 'file_name': fname}
        dl_q = {'mode': 'debrid_download', 'mediatype': mediatype, 'item_id': str(item_id), 'file_id': str(f_idx), 'name': name, 'file_name': fname}
        cm = [
            ('Download', f'RunPlugin({_build_url(dl_q)})'),
            ('Delete Containing Transfer', f'RunPlugin({_build_url({"mode": "debrid_tb_delete", "mediatype": mediatype, "item_id": str(item_id), "name": name})})'),
            ('Refresh', f'RunPlugin({_build_url({"mode": "debrid_refresh"})})'),
        ]
        li.addContextMenuItems(cm)
        _add_dir(_build_url(play_q), li, False)

    _end()


TB_PLANS = {
    0: 'Free',
    1: 'Essential',
    2: 'Pro',
    3: 'Standard',
}


def _tb_plan_name(value):
    if isinstance(value, str) and value and not value.isdigit():
        return value
    try:
        return TB_PLANS.get(int(value), 'Unknown')
    except Exception:
        return 'Unknown'


def _view_tb_account():
    _ensure_globals()
    from resources.lib import torbox_api

    try:
        info = torbox_api.account_info()
    except Exception as e:
        xbmcgui.Dialog().ok('TorBox Account', str(e))
        return

    plan = _tb_plan_name(info.get('plan'))
    email = str(info.get('email') or '?')
    expires_at = info.get('premium_expires_at') or ''
    try:
        dl_val = float(info.get('total_downloaded') or 0)
    except Exception:
        dl_val = 0.0
    xbmc.log(f'[DEBRID][TorBox] total_downloaded raw: {info.get("total_downloaded")}', xbmc.LOGDEBUG)
    dl_str = f'{dl_val:g} GB'

    lines = [
        '[B]Email:[/B] ' + email,
        '[B]Plan:[/B] ' + plan,
    ]
    exp_date = _fmt_expiry_date(expires_at)
    if exp_date:
        lines.append('[B]Premium expires:[/B] ' + exp_date)
        days = _expiry_days_left(expires_at)
        if days is not None:
            lines.append('[B]Days remaining:[/B] ' + str(days))
    lines.append('[B]Total downloaded:[/B] ' + (dl_str or '0'))
    if plan == 'Pro':
        quota = '1 TB'
    elif plan == 'Standard':
        quota = '500 GB'
    elif plan == 'Essential':
        quota = '300 GB'
    else:
        quota = '0 GB (paid plans only)'
    lines.append('[B]AirLock quota:[/B] ' + quota)
    xbmcgui.Dialog().textviewer('TorBox Account', '\n'.join(lines))


def _view_rd_cloud(params):
    _ensure_globals()
    from resources.lib import realdebrid_api

    page = _page_num(params)
    limit = _rd_cloud_limit()
    items, err = _cached_call(_rd_cloud_key(page, limit), lambda: realdebrid_api.user_cloud(page, limit))
    if err:
        _error_item(err, {'mode': 'debrid_rd_cloud', 'page': str(page)}, _rd_icon())
        _end()
        return

    raw_count = len(items or [])
    ordered = sorted((items or []),
                     key=lambda it: str(it.get('added') or ''), reverse=True)

    if not raw_count:
        _empty_item('Cloud is empty', _rd_icon())
        _end()
        return

    for it in ordered:
        if not isinstance(it, dict):
            continue
        if str(it.get('status') or '') == 'downloaded':
            _add_rd_folder_row(it)
        else:
            nm = str(it.get('filename') or 'Unnamed')
            if _is_junk_name(nm):
                continue
            try:
                pct = int(float(it.get('progress') or 0))
            except Exception:
                pct = 0
            _add_inactive_row(f'[B]{str(it.get("status") or "active").upper()} - {pct}%[/B] | [I]{nm}[/I]', _rd_icon())

    if raw_count >= limit:
        li = xbmcgui.ListItem(label='[B][COLOR ' + _HL_COLOR + ']Next Page >>[/COLOR][/B]')
        li.setArt({'icon': _rd_icon(), 'thumb': _rd_icon()})
        _add_dir(_build_url({'mode': 'debrid_rd_cloud', 'page': str(page + 1)}), li, True)

    _end()


def _add_rd_folder_row(item):
    name = str(item.get('filename') or 'Unnamed')
    if _is_junk_name(name):
        return
    size = _fmt_size(item.get('bytes'))
    added = _fmt_dmy(item.get('added') or '')
    status = str(item.get('status') or 'unknown').upper()
    label = f'[B]{status}[/B] | ' + (size + ' | ' if size else '') + (added + ' | ' if added else '') + f'[I]{name}[/I]'

    li = xbmcgui.ListItem(label=label)
    li.setArt({'icon': _rd_icon(), 'thumb': _rd_icon(), 'poster': _rd_icon()})
    try:
        tag = li.getVideoInfoTag()
        tag.setTitle(name)
        tag.setPlot(f'Cloud Storage: {name} | Status: {status} | Size: {size or "?"} | Added: {added or "?"}')
    except Exception:
        pass

    tid = item.get('id')
    cm = [
        ('Delete', f'RunPlugin({_build_url({"mode": "debrid_rd_delete_torrent", "item_id": str(tid), "name": name})})'),
        ('Refresh', f'RunPlugin({_build_url({"mode": "debrid_refresh"})})'),
    ]
    li.addContextMenuItems(cm)
    _add_dir(_build_url({'mode': 'debrid_rd_folder', 'item_id': str(tid), 'name': name}), li, True)


def _rd_selected_links(info):
    try:
        files = info.get('files') or []
        links = info.get('links') or []
    except Exception:
        return []
    out = []
    link_iter = iter(links)
    for f in files:
        if not isinstance(f, dict):
            continue
        if not f.get('selected', 1):
            continue
        out.append((f.get('id'), next(link_iter, '')))
    return out


def _rd_find_download(did, page, limit):
    from resources.lib import realdebrid_api
    pages = [page]
    for step in (1, -1, 2, -2):
        if len(pages) >= 5:
            break
        cand = page + step
        if cand >= 1 and cand not in pages:
            pages.append(cand)
    for p in pages:
        key = f'tmdbmovies_rd_downloads_p{p}_l{limit}'
        payload = _cache_get(key)
        if payload is None:
            try:
                payload = realdebrid_api.downloads(p, limit)
            except Exception:
                continue
            try:
                _cache_set(key, payload)
            except Exception:
                pass
        items = []
        if isinstance(payload, dict):
            items = payload.get('items') or []
        elif isinstance(payload, list):
            items = payload
        for it in items:
            if isinstance(it, dict) and str(it.get('id') or '') == str(did):
                return it
    return None


def _view_rd_folder(params):
    _ensure_globals()
    from resources.lib import realdebrid_api

    tid = params.get('item_id', '')
    name = params.get('name', '')

    if not tid:
        _empty_item('Invalid item', _rd_icon())
        _end()
        return

    try:
        info = realdebrid_api.torrent_info(tid)
    except Exception as e:
        _error_item(str(e), {'mode': 'debrid_rd_cloud'}, _rd_icon())
        _end()
        return

    files = info.get('files') or []
    links = info.get('links') or []

    video_files = []
    link_iter = iter(links)
    for f in files:
        if not isinstance(f, dict):
            continue
        if not f.get('selected', 1):
            continue
        link = next(link_iter, '')
        fname = str(f.get('path') or f.get('name') or '')
        if not fname.lower().endswith(_VIDEO_EXT):
            continue
        if _is_junk_name(fname):
            continue
        short = fname.split('/')[-1] if '/' in fname else fname
        video_files.append((f.get('id'), short, f.get('bytes'), fname, link))

    if not video_files:
        _empty_item('No playable files', _rd_icon())
        _end()
        return

    video_files.sort(key=lambda t: -(t[2] or 0))
    for idx, (fid, short, fsize, full_path, link) in enumerate(video_files, start=1):
        size = _fmt_size(fsize)
        label = f'{idx:02d} | [B]FILE[/B] | ' + (size + ' | ' if size else '') + f'[I]{short}[/I]'
        li = xbmcgui.ListItem(label=label)
        li.setArt({'icon': _rd_icon(), 'thumb': _rd_icon(), 'poster': _rd_icon()})
        try:
            tag = li.getVideoInfoTag()
            tag.setTitle(short)
            tag.setPlot(f'Cloud Storage: {name} | File: {full_path} | Size: {size or "?"}')
        except Exception:
            pass
        li.setProperty('IsPlayable', 'true')
        play_q = {'mode': 'debrid_play', 'provider': 'rd', 'item_id': str(tid), 'file_id': str(fid or 0), 'name': name, 'file_name': short}
        dl_q = {'mode': 'debrid_download', 'provider': 'rd', 'item_id': str(tid), 'file_id': str(fid or 0), 'name': name, 'file_name': short}
        cm = [
            ('Download', f'RunPlugin({_build_url(dl_q)})'),
            ('Delete Containing Transfer', f'RunPlugin({_build_url({"mode": "debrid_rd_delete_torrent", "item_id": str(tid), "name": name})})'),
            ('Refresh', f'RunPlugin({_build_url({"mode": "debrid_refresh"})})'),
        ]
        li.addContextMenuItems(cm)
        _add_dir(_build_url(play_q), li, False)

    _end()


def _view_rd_downloads(params):
    _ensure_globals()
    from resources.lib import realdebrid_api

    page = _page_num(params)
    limit = _page_limit()
    key = f'tmdbmovies_rd_downloads_p{page}_l{limit}'
    payload, err = _cached_call(key, lambda: realdebrid_api.downloads(page, limit))
    if err:
        _error_item(err, {'mode': 'debrid_rd_downloads', 'page': str(page)}, _rd_icon())
        _end()
        return

    if isinstance(payload, dict) and 'items' in payload:
        listing = payload.get('items') or []
        total_pages = int(payload.get('total_pages', 1) or 1)
    else:
        listing, total_pages = (payload or []), 1
    xbmc.log(f'[DEBRID][RD] history page {page} limit {limit}: {len(listing or [])} items, {total_pages} pages', xbmc.LOGDEBUG)

    if not listing:
        _empty_item('No download history', _rd_icon())
        _end()
        return

    for it in listing:
        _add_rd_download_row(it, page)

    if page < total_pages:
        li = xbmcgui.ListItem(label='[B][COLOR ' + _HL_COLOR + ']Next Page >>[/COLOR][/B]')
        li.setArt({'icon': _rd_icon(), 'thumb': _rd_icon()})
        _add_dir(_build_url({'mode': 'debrid_rd_downloads', 'page': str(page + 1)}), li, True)

    _end()


def _add_rd_download_row(item, page=1):
    name = str(item.get('filename') or 'Unnamed')
    size = _fmt_size(item.get('filesize'))
    generated = _fmt_dmy(item.get('generated') or '')
    host = str(item.get('host') or '')
    if _is_junk_name(name):
        return
    label = f'[B]DL[/B] | ' + (size + ' | ' if size else '') + (generated + ' | ' if generated else '') + f'[I]{name}[/I]'

    li = xbmcgui.ListItem(label=label)
    li.setArt({'icon': _rd_icon(), 'thumb': _rd_icon(), 'poster': _rd_icon()})
    try:
        tag = li.getVideoInfoTag()
        tag.setTitle(name)
        tag.setPlot(f'History: {name} | Host: {host} | Size: {size or "?"} | Generated: {generated or "?"}')
    except Exception:
        pass

    did = item.get('id')
    play_q = {'mode': 'debrid_play', 'provider': 'rd', 'item_id': str(did), 'page': str(page), 'name': name, 'file_name': name}
    dl_q = {'mode': 'debrid_download', 'provider': 'rd', 'item_id': str(did), 'page': str(page), 'name': name, 'file_name': name}
    cm = [
        ('Download', f'RunPlugin({_build_url(dl_q)})'),
        ('Delete', f'RunPlugin({_build_url({"mode": "debrid_rd_delete_download", "item_id": str(did), "name": name})})'),
        ('Refresh', f'RunPlugin({_build_url({"mode": "debrid_refresh"})})'),
    ]
    li.addContextMenuItems(cm)
    li.setProperty('IsPlayable', 'true')
    _add_dir(_build_url(play_q), li, False)


def _view_rd_account():
    _ensure_globals()
    from resources.lib import realdebrid_api

    try:
        info = realdebrid_api.account_info()
    except Exception as e:
        xbmcgui.Dialog().ok('Real-Debrid Account Info', str(e))
        return

    user = str(info.get('username') or '?')
    email = str(info.get('email') or '?')
    plan = str(info.get('type') or '?')
    expiration = info.get('expiration') or ''
    points = info.get('points') or 0

    lines = [
        '[B]User:[/B] ' + user,
        '[B]Email:[/B] ' + email,
        '[B]Plan:[/B] ' + plan,
    ]
    exp_date = _fmt_expiry_date(expiration)
    if exp_date:
        lines.append('[B]Expires:[/B] ' + exp_date)
        days = _expiry_days_left(expiration)
        if days is not None:
            lines.append(f'[B]Days left:[/B] {days}')
    else:
        atype = str(info.get('type') or '').strip().lower()
        lines.append('[B]Days left:[/B] ' + ('0' if atype and atype != 'premium' else 'Unknown'))
    lines.append(f'[B]Fidelity points:[/B] {points}')
    xbmcgui.Dialog().textviewer('Real-Debrid Account Info', '\n'.join(lines))


def _set_api_key(provider):
    _ensure_globals()
    dialog = xbmcgui.Dialog()
    if provider == 'torbox':
        heading = 'Enter TorBox API Key (torbox.app/settings)'
        setting = 'torbox_api_key'
    else:
        heading = 'Enter Real-Debrid API Key (real-debrid.com/apitoken)'
        setting = 'rd_api_key'

    key = dialog.input(heading, type=xbmcgui.INPUT_ALPHANUM, option=xbmcgui.ALPHANUM_HIDE_INPUT)
    key = (key or '').strip()
    if not key:
        return

    busy = xbmcgui.DialogProgressBG()
    busy.create(provider_title('tmdb', name='TMDb Movies'), 'Validating API key...')
    valid = False
    detail = ''
    try:
        if provider == 'torbox':
            from resources.lib import torbox_api
            from resources.lib.config import ADDON as _A
            _prev = (_A.getSetting('torbox_api_key') or '').strip()
            _A.setSetting('torbox_api_key', key)
            try:
                torbox_api.account_info()
                valid = True
            except Exception as e:
                detail = str(e)
                _A.setSetting('torbox_api_key', _prev)
        else:
            from resources.lib import realdebrid_api
            from resources.lib.config import ADDON as _A
            _prev = (_A.getSetting('rd_api_key') or '').strip()
            _A.setSetting('rd_api_key', key)
            try:
                realdebrid_api.account_info()
                valid = True
            except Exception as e:
                detail = str(e)
                _A.setSetting('rd_api_key', _prev)
    finally:
        busy.close()

    if valid:
        try:
            if provider == 'torbox':
                from resources.lib import torbox_api
                torbox_api.clear_cloud_cache()
                info = torbox_api.account_info()
                _ADDON.setSetting('torbox_status', 'Connected')
            else:
                from resources.lib import realdebrid_api
                realdebrid_api.clear_cloud_cache()
                info = realdebrid_api.account_info()
                _ADDON.setSetting('rd_status', 'Connected')
        except Exception:
            pass
        _notify('Connected to ' + ('TorBox' if provider == 'torbox' else 'Real-Debrid'))
        xbmc.executebuiltin('Container.Refresh')
    else:
        _notify('Invalid API key: ' + detail, ms=4000)


def _disconnect(provider):
    _ensure_globals()
    if provider not in ('torbox', 'rd'):
        _notify('Unknown provider', ms=3000)
        return
    label = 'TorBox' if provider == 'torbox' else 'Real-Debrid'
    if not xbmcgui.Dialog().yesno('Disconnect ' + label, f'Remove the saved API key for [B]{label}[/B]?'):
        return
    if provider == 'torbox':
        _ADDON.setSetting('torbox_api_key', '')
        _ADDON.setSetting('torbox_status', 'Disconnected')
        try:
            from resources.lib import torbox_api
            torbox_api.clear_cloud_cache()
        except Exception:
            pass
        _notify('Disconnected from TorBox')
    else:
        _ADDON.setSetting('rd_api_key', '')
        _ADDON.setSetting('rd_status', 'Disconnected')
        try:
            from resources.lib import realdebrid_api
            realdebrid_api.clear_cloud_cache()
        except Exception:
            pass
        _notify('Disconnected from Real-Debrid')
    xbmc.executebuiltin('Container.Refresh')


def _confirm_delete(name):
    return xbmcgui.Dialog().yesno('Delete from Debrid', f'Delete [B]{name}[/B] permanently from your debrid account?')


def _delete_tb(params):
    _ensure_globals()
    from resources.lib import torbox_api

    mediatype = params.get('mediatype', 'torrents')
    item_id = params.get('item_id', '')
    name = params.get('name', '') or 'this item'

    if not item_id:
        return
    if not _confirm_delete(name):
        return
    try:
        torbox_api.delete_item(mediatype, item_id)
    except Exception as e:
        _notify(f'Delete failed: {e}', ms=4000)
        return
    _cache_del_prefix('tmdbmovies_tb_')
    _notify(f'{name} was removed', icon=_tb_icon())
    xbmc.executebuiltin('Container.Refresh')


def _toggle_tb_airlock(params):
    _ensure_globals()
    from resources.lib import torbox_api

    mediatype = params.get('mediatype', 'torrents')
    item_id = params.get('item_id', '')
    name = params.get('name', '') or 'this item'

    if not item_id:
        return
    if not xbmcgui.Dialog().yesno('AirLock', f'Toggle AirLock for [B]{name}[/B]? Removing does not reset the countdown; the item remains subject to its last download/activity.'):
        return
    try:
        new_state = torbox_api.toggle_airlock(mediatype, item_id)
    except Exception as e:
        _notify(f'AirLock: {e}', ms=4000)
        return
    _cache_del_prefix('tmdbmovies_tb_')
    verb = 'added to' if new_state else 'removed from'
    _notify(f'{name} {verb} AirLock', icon=_tb_icon())
    xbmc.executebuiltin('Container.Refresh')


def _delete_rd_torrent(params):
    _ensure_globals()
    from resources.lib import realdebrid_api

    item_id = params.get('item_id', '')
    name = params.get('name', '') or 'this item'
    if not item_id:
        return
    if not _confirm_delete(name):
        return
    try:
        realdebrid_api.delete_torrent(item_id)
    except Exception as e:
        _notify(f'Delete failed: {e}', ms=4000)
        return
    _cache_del_prefix('tmdbmovies_rd_')
    _notify(f'{name} was removed', icon=_rd_icon())
    xbmc.executebuiltin('Container.Refresh')


def _delete_rd_download(params):
    _ensure_globals()
    from resources.lib import realdebrid_api

    item_id = params.get('item_id', '')
    name = params.get('name', '') or 'this item'
    if not item_id:
        return
    if not xbmcgui.Dialog().yesno('Delete from History', f'Remove [B]{name}[/B] from download history? The files in Cloud Storage are kept.'):
        return
    try:
        realdebrid_api.delete_download(item_id)
    except Exception as e:
        _notify(f'Delete failed: {e}', ms=4000)
        return
    _cache_del_prefix('tmdbmovies_rd_')
    _notify(f'{name} was removed', icon=_rd_icon())
    xbmc.executebuiltin('Container.Refresh')


def _resolve_tb_link(mediatype, item_id, file_id):
    from resources.lib import torbox_api
    return torbox_api.unrestrict_link(mediatype, item_id, file_id)


def _resolve_rd_link(params):
    from resources.lib import realdebrid_api
    item_id = params.get('item_id', '')
    file_id = params.get('file_id', '')
    if file_id:
        info = realdebrid_api.torrent_info(item_id)
        for sid, link in _rd_selected_links(info):
            if str(sid) == str(file_id) and link:
                return realdebrid_api.unrestrict_link(link)
        raise Exception('File link not available')
    page = _page_num(params)
    limit = _page_limit()
    found = _rd_find_download(item_id, page, limit)
    if isinstance(found, dict):
        direct = str(found.get('download') or '')
        if direct:
            return realdebrid_api.unrestrict_link(direct)
    raise Exception('File link not available')


def _resolve_link(params):
    provider = params.get('provider', '')
    if provider == 'rd':
        return _resolve_rd_link(params)
    mediatype = params.get('mediatype', 'torrents')
    return _resolve_tb_link(mediatype, params.get('item_id', ''), params.get('file_id', '0'))


def _play(params):
    _ensure_globals()
    name = params.get('name', '') or ''
    file_name = params.get('file_name', '') or name

    busy = xbmcgui.DialogProgressBG()
    busy.create(provider_title('tmdb', name='TMDb Movies'), 'Resolving debrid link...')
    url = None
    err = ''
    try:
        url = _resolve_link(params)
    except Exception as e:
        err = str(e)
    finally:
        busy.close()

    if not url:
        _notify('Playback failed: ' + (err or 'no link'), ms=4000)
        if _HANDLE >= 0:
            xbmcplugin.setResolvedUrl(_HANDLE, False, xbmcgui.ListItem())
        return

    li = xbmcgui.ListItem(label=file_name, path=url)
    li.setArt({'icon': _icon('debrid.png'), 'thumb': _icon('debrid.png')})
    try:
        tag = li.getVideoInfoTag()
        tag.setTitle(file_name)
    except Exception:
        pass
    li.setPath(url)

    if _HANDLE >= 0:
        if _kodi_major_local() >= 22:
            xbmcplugin.setResolvedUrl(_HANDLE, True, li)
        else:
            xbmcplugin.setResolvedUrl(_HANDLE, True, li)
            xbmc.Player().play(url, li)
    else:
        xbmc.Player().play(url, li)


def _download(params):
    _ensure_globals()
    name = params.get('name', '') or ''
    file_name = params.get('file_name', '') or name

    busy = xbmcgui.DialogProgressBG()
    busy.create(provider_title('tmdb', name='TMDb Movies'), 'Resolving debrid link...')
    url = None
    err = ''
    try:
        url = _resolve_link(params)
    except Exception as e:
        err = str(e)
    finally:
        busy.close()

    if not url:
        _notify('Download failed: ' + (err or 'no link'), ms=4000)
        return

    from resources.lib.downloader import start_download_thread
    try:
        start_download_thread(url, title=file_name, year='', tmdb_id='debrid_' + str(params.get('item_id', '0')) + '_' + str(params.get('file_id', '') or params.get('item_id', '0')),
                              c_type='movie', season=None, episode=None, release_name=file_name, provider_id='debrid')
        _notify('Download started', icon=_icon('debrid.png'))
    except Exception as e:
        _notify(f'Download failed: {e}', ms=4000)


def _clear_tb_cache():
    try:
        from resources.lib import torbox_api
        torbox_api.clear_cloud_cache()
    except Exception:
        pass
    _notify('TorBox cache cleared')
    xbmc.executebuiltin('Container.Refresh')


def _clear_rd_cache():
    try:
        from resources.lib import realdebrid_api
        realdebrid_api.clear_cloud_cache()
    except Exception:
        pass
    _notify('Real-Debrid cache cleared')
    xbmc.executebuiltin('Container.Refresh')


def _refresh():
    _cache_del_prefix('tmdbmovies_tb_')
    _cache_del_prefix('tmdbmovies_rd_')
    xbmc.executebuiltin('Container.Refresh')


def _migrate_status_labels():
    try:
        for _key_id, _st_id in (('torbox_api_key', 'torbox_status'), ('rd_api_key', 'rd_status')):
            _key = (_ADDON.getSetting(_key_id) or '').strip()
            _st = (_ADDON.getSetting(_st_id) or '').strip()
            if _key and _key in _st:
                _ADDON.setSetting(_st_id, 'Connected')
            elif _st.startswith('Connected:'):
                _ADDON.setSetting(_st_id, 'Connected')
    except Exception:
        pass


def handle_debrid_action(params, handle, base_url, addon):
    action = params.get('mode', params.get('action', ''))
    if action not in DEBRID_ACTIONS:
        try:
            if int(handle) >= 0:
                xbmcplugin.endOfDirectory(int(handle), succeeded=False)
        except Exception:
            pass
        return False
    _ensure_globals()
    global _HANDLE, _BASE_URL, _ADDON
    _HANDLE = handle
    _BASE_URL = base_url
    _ADDON = addon
    _migrate_status_labels()
    if action == 'debrid_menu':
        _view_main()
    elif action == 'debrid_torbox':
        _view_torbox()
    elif action == 'debrid_rd':
        _view_rd()
    elif action == 'debrid_tb_cloud':
        _view_tb_cloud(params)
    elif action == 'debrid_tb_folder':
        _view_tb_folder(params)
    elif action == 'debrid_tb_airlock':
        _view_tb_airlock(params)
    elif action == 'debrid_tb_account':
        _view_tb_account()
    elif action == 'debrid_rd_cloud':
        _view_rd_cloud(params)
    elif action == 'debrid_rd_folder':
        _view_rd_folder(params)
    elif action == 'debrid_rd_downloads':
        _view_rd_downloads(params)
    elif action == 'debrid_rd_account':
        _view_rd_account()
    elif action == 'debrid_set_torbox_key':
        _set_api_key('torbox')
    elif action == 'debrid_set_rd_key':
        _set_api_key('rd')
    elif action == 'debrid_disconnect':
        _disconnect(params.get('provider', ''))
    elif action == 'debrid_tb_delete':
        _delete_tb(params)
    elif action == 'debrid_tb_toggle_airlock':
        _toggle_tb_airlock(params)
    elif action == 'debrid_rd_delete_torrent':
        _delete_rd_torrent(params)
    elif action == 'debrid_rd_delete_download':
        _delete_rd_download(params)
    elif action == 'debrid_tb_clear_cache':
        _clear_tb_cache()
    elif action == 'debrid_rd_clear_cache':
        _clear_rd_cache()
    elif action == 'debrid_play':
        _play(params)
    elif action == 'debrid_download':
        _download(params)
    elif action == 'debrid_refresh':
        _refresh()
    return True
