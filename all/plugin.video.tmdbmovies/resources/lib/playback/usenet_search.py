"""Custom text search over the Usenet indexers picked in Settings, played through the NNTP engine."""

import hashlib
import json
import os
import re
import sys
from urllib.parse import urlencode

import xbmc
import xbmcgui
import xbmcplugin

from resources.lib.core.config import ADDON_DATA_DIR, ADDON_PATH, PLUGIN_URL
from resources.lib.core.log_safe import redact_text as _redact_log

_ART = ADDON_PATH.replace('\\', '/') + '/resources/media/'
_ICON_SEARCH = _ART + 'search_movie.png'
_ICON_HISTORY = _ART + 'search_history.png'
_SPLIT_PREFIX = re.compile(r'^.*?__NZBSPLIT__[0-9a-f]{8,}__NZBSPLIT__', re.I)
_YEAR_RE = re.compile(r'(?<![A-Za-z\d])((?:19|20)\d{2})(?![\dxX])')
_EPISODE_RE = re.compile(r'\bS(\d{1,2})E(\d{1,3})\b', re.I)
_QUALITY_COLOR = {'4K': 'FF00FFFF', '1080p': 'FF00FF7F',
                  '720p': 'FFFFD700', 'SD': 'FF00BFFF'}
_HISTORY_FILE = os.path.join(ADDON_DATA_DIR, 'usenet_search_history.json')


def _log(message):
    try:
        xbmc.log('[TMDb Movies] [USENET-SEARCH] %s' % message, xbmc.LOGINFO)
    except Exception:
        pass


_LINK_PREFIX = 'tmdbmovies_usenet_link_%s_'


def _remember_link(kind, url):
    url = str(url or '')
    key = hashlib.md5(url.encode('utf-8')).hexdigest() if url else ''
    if key:
        xbmcgui.Window(10000).setProperty((_LINK_PREFIX % kind) + key, url)
    return key


def resolve_links(params):
    """The playback links for a custom-search row; new rows keep them in window properties."""
    params = params or {}
    nzb = str(params.get('nzb_url') or '')
    en = str(params.get('en_url') or '')
    window = xbmcgui.Window(10000)
    if not nzb:
        key = str(params.get('nzb_key') or '')
        if key:
            nzb = window.getProperty((_LINK_PREFIX % 'nzb') + key) or ''
    if not en:
        key = str(params.get('en_key') or '')
        if key:
            en = window.getProperty((_LINK_PREFIX % 'en') + key) or ''
    return nzb, en


def _record_outcome(indexer, ok):
    try:
        from resources.lib.usenet import stats
        stats.indexer(indexer, **({'ok': 1} if ok else {'bad': 1}))
    except Exception:
        pass


def _handle():
    try:
        return int(sys.argv[1])
    except Exception:
        return -1


def _clean_title(title):
    text = str(title or '').strip()
    return _SPLIT_PREFIX.sub('', text) or text


def _size_text(size):
    try:
        size = int(size or 0)
    except (TypeError, ValueError):
        size = 0
    if size >= 1073741824:
        return '%.2f GB' % (size / 1073741824.0)
    if size:
        return '%.0f MB' % (size / 1048576.0)
    return ''


def _release_tags(title):
    text = str(title or '').lower()
    tags = []
    if re.search(r'(?<!\d)(2160p|4k|uhd|3840x2160)', text):
        tags.append('4K')
    elif re.search(r'(?<!\d)(1080p|1080i|fhd|1920x1080)', text):
        tags.append('1080p')
    elif re.search(r'(?<!\d)(720p|1280x720)', text):
        tags.append('720p')
    elif re.search(r'(?<!\d)(480p|576p|sd)\b', text):
        tags.append('SD')
    if 'remux' in text:
        tags.append('REMUX')
    elif re.search(r'\b(blu-?ray|bdrip|brrip)\b', text):
        tags.append('BluRay')
    elif re.search(r'\bweb[- .]?dl\b', text):
        tags.append('WEB-DL')
    elif re.search(r'\bweb[- .]?rip\b', text):
        tags.append('WEBRip')
    elif re.search(r'\bhdtv\b', text):
        tags.append('HDTV')
    elif re.search(r'\b(dvdrip|dvd)\b', text):
        tags.append('DVD')
    if re.search(r'\b(dolby[ .]?vision|dovi|dv)\b', text):
        tags.append('Dolby Vision')
    elif 'hdr10+' in text:
        tags.append('HDR10+')
    elif re.search(r'\bhdr10?\b', text):
        tags.append('HDR')
    if re.search(r'\b(hevc|x265)\b', text) or 'h.265' in text:
        tags.append('HEVC')
    elif re.search(r'\b(x264|avc)\b', text) or 'h.264' in text:
        tags.append('H.264')
    elif re.search(r'\bav1\b', text):
        tags.append('AV1')
    elif re.search(r'\b(xvid|divx)\b', text):
        tags.append('XviD')
    if re.search(r'dts[- .]?hd', text):
        tags.append('DTS-HD MA' if re.search(r'dts[- .]?hd[ .-]?ma\b', text) else 'DTS-HD')
    elif re.search(r'\b(truehd|true[ .-]?hd)\b', text):
        tags.append('TrueHD')
    elif re.search(r'\bddp(?=[ .]?\d|\b)|dd\+|eac3|e-ac3', text):
        tags.append('DD+')
    elif re.search(r'\bac3\b', text):
        tags.append('AC3')
    elif re.search(r'\bdts(?=[ .]?\d|\b)', text):
        tags.append('DTS')
    elif re.search(r'\baac(?=[ .]?\d|\b)', text):
        tags.append('AAC')
    elif re.search(r'\bflac\b', text):
        tags.append('FLAC')
    if 'atmos' in text:
        tags.append('Atmos')
    if re.search(r'(?<!\d)7[ .]1(?!\d)', text):
        tags.append('7.1')
    elif re.search(r'(?<!\d)5[ .]1(?!\d)', text):
        tags.append('5.1')
    elif re.search(r'(?<!\d)2[ .]0(?!\d)', text) or re.search(r'\bstereo\b', text):
        tags.append('2.0')
    return tags


def _tag_color(tag):
    if tag in ('Dolby Vision', 'HDR10+', 'HDR'):
        color = 'FF87CEEB'
    elif tag in ('REMUX', 'BluRay', 'WEB-DL', 'WEBRip', 'HDTV', 'DVD'):
        color = 'FF00CED1'
    elif tag in ('HEVC', 'H.264', 'AV1', 'XviD'):
        color = 'FFFF69B4'
    elif tag in ('DTS-HD MA', 'DTS-HD', 'TrueHD', 'DD+', 'AC3', 'DTS', 'AAC', 'FLAC'):
        color = 'FF00FF00'
    elif tag == 'Atmos':
        color = 'FF00FFFF'
    else:
        color = 'FFCCCCFF'
    return '[B][COLOR %s]%s[/COLOR][/B]' % (color, tag)


def _video_info(title, size=0, indexer=''):
    title = str(title or '').strip() or 'Usenet'
    tags = _release_tags(title)
    size_text = _size_text(size)
    quality = next((tag for tag in tags if tag in _QUALITY_COLOR), '')
    rest = [tag for tag in tags if tag != quality]
    header = '[B][COLOR FFFF69B4]Usenet[/COLOR][/B]'
    if indexer:
        header += ' | [B][COLOR FF00CED1]%s[/COLOR][/B]' % indexer
    meta = []
    if quality:
        meta.append('[B][COLOR %s]%s[/COLOR][/B]'
                    % (_QUALITY_COLOR[quality], quality))
    if size_text:
        meta.append('[B][COLOR FFFFEA00]%s[/COLOR][/B]' % size_text)
    plot = [header]
    if meta:
        plot.append('  •  '.join(meta))
    if rest:
        plot.append('  •  '.join(_tag_color(tag) for tag in rest))
    plot.append('[COLOR FF20B2AA]Source:[/COLOR] '
                '[B][COLOR FFCCCCFF]%s[/COLOR][/B]' % title)
    info = {
        'title': title,
        'plot': '\n'.join(plot),
        'mediatype': 'video',
    }
    years = _YEAR_RE.findall(title)
    if years:
        try:
            info['year'] = int(years[-1])
        except ValueError:
            pass
    episode = _EPISODE_RE.search(title)
    if episode:
        try:
            info['season'] = int(episode.group(1))
            info['episode'] = int(episode.group(2))
        except ValueError:
            pass
    return info


def _url(data):
    return PLUGIN_URL + '?' + urlencode(data)


def _results_url(query):
    return _url({'mode': 'usenet_results', 'query': query})


def _item(handle, mode, label, params=None, folder=True):
    data = {'mode': mode}
    data.update(params or {})
    li = xbmcgui.ListItem(label=label)
    li.setArt({'icon': _ICON_SEARCH, 'thumb': _ICON_SEARCH})
    xbmcplugin.addDirectoryItem(handle, _url(data), li, folder)


def _notify(message):
    try:
        xbmcgui.Dialog().notification(
            '[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]',
            message, _ICON_SEARCH, 2000, False)
    except Exception:
        pass


def _history_load():
    try:
        with open(_HISTORY_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    history = []
    for item in data:
        if isinstance(item, dict):
            query = str(item.get('query') or '').strip()
            if query:
                history.append({'query': query})
    return history[:20]


def _history_save(history):
    try:
        with open(_HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history[:20], f, ensure_ascii=False)
        return True
    except Exception as exc:
        _log('history save failed: %s' % exc)
        return False


def _history_add(query):
    query = str(query or '').strip()
    if not query:
        return
    history = [h for h in _history_load() if h.get('query') != query]
    history.insert(0, {'query': query})
    _history_save(history)


def _history_rename(old_query, new_query):
    new_query = str(new_query or '').strip()
    if not new_query or new_query == old_query:
        return False
    history = _history_load()
    for item in history:
        if item.get('query') == old_query:
            item['query'] = new_query
            return _history_save(history)
    return False


def _history_remove(query):
    _history_save([h for h in _history_load() if h.get('query') != query])


def _history_clear():
    _history_save([])


def _history_context(query):
    return [
        ('Rename', 'RunPlugin(%s)' % _url({'mode': 'usenet_history_rename', 'query': query})),
        ('Delete', 'RunPlugin(%s)' % _url({'mode': 'usenet_history_delete', 'query': query})),
    ]


def search_menu(params=None):
    handle = _handle()
    if handle < 0:
        return
    items = []
    search_li = xbmcgui.ListItem(label='[B][COLOR FF00CED1]Search Now[/COLOR][/B]')
    search_li.setArt({'icon': _ICON_SEARCH, 'thumb': _ICON_SEARCH})
    items.append((_url({'mode': 'usenet_search_input'}), search_li, False))

    history = _history_load()
    for entry in history:
        query = entry['query']
        hist_li = xbmcgui.ListItem(label=query)
        hist_li.setArt({'icon': _ICON_HISTORY, 'thumb': _ICON_HISTORY})
        hist_li.addContextMenuItems(_history_context(query))
        items.append((_results_url(query), hist_li, True))

    if history:
        clear_li = xbmcgui.ListItem(label='[B][COLOR FFFF4444]Delete all history[/COLOR][/B]')
        clear_li.setArt({'icon': 'DefaultAddonNone.png', 'thumb': 'DefaultAddonNone.png'})
        items.append((_url({'mode': 'usenet_history_clear'}), clear_li, False))

    xbmcplugin.addDirectoryItems(handle, items, len(items))
    xbmcplugin.endOfDirectory(handle)


def search_input(params=None):
    query = xbmcgui.Dialog().input('Search Usenet', defaultt='', type=xbmcgui.INPUT_ALPHANUM)
    if not query:
        return
    query = str(query).strip()
    if not query:
        return
    _history_add(query)
    xbmc.executebuiltin('Container.Update(%s)' % _results_url(query))


def search_results(params=None):
    handle = _handle()
    if handle < 0:
        return
    params = params or {}
    query = str(params.get('query') or '').strip()
    if not query:
        xbmcplugin.endOfDirectory(handle, False)
        return

    try:
        from resources.lib.usenet import config as usenet_config
        from resources.lib.usenet import indexer
    except Exception as exc:
        _log('engine not available: %s' % exc)
        _item(handle, 'usenet_search', '[B][COLOR FFFF5555]Usenet engine is not available[/COLOR][/B]')
        xbmcplugin.endOfDirectory(handle, True, False, True)
        return
    if not usenet_config.enabled():
        _item(handle, 'usenet_search', '[B][COLOR FFFF5555]Enable Usenet first[/COLOR][/B]')
        xbmcplugin.endOfDirectory(handle, True, False, True)
        return
    if not usenet_config.providers():
        _item(handle, 'usenet_search', '[B][COLOR FFFF5555]No Usenet provider is configured[/COLOR][/B]')
        xbmcplugin.endOfDirectory(handle, True, False, True)
        return

    scope = usenet_config.context_search_scope()
    per_indexer_limit = usenet_config.max_results()
    progress = xbmcgui.DialogProgressBG()
    try:
        progress.create('Usenet search', {
            'free': 'Searching the free indexers...',
            'paid': 'Searching the paid indexers...',
        }.get(scope, 'Searching all indexers...'))
    except Exception:
        progress = None
    try:
        rows, notes = indexer.find(
            'movie', '', None, None, title=query, year=None, alt_title='',
            logger=_log, use_cache=False, mode=usenet_config.fetch_mode(),
            min_usable=usenet_config.stop_after(), min_size=usenet_config.min_size_bytes(),
            episodes_only=False, per_indexer_limit=per_indexer_limit,
            scope=scope, all_categories=True)
    except Exception as exc:
        rows, notes = [], [str(exc)[:120]]
    finally:
        try:
            if progress is not None:
                progress.close()
        except Exception:
            pass

    en_rows = []
    try:
        from resources.lib.api import easynews_direct
        include_en = usenet_config.context_search_easynews()
        if include_en and not easynews_direct.available():
            if not easynews_direct.enabled():
                _log('EasyNews Direct search skipped: the switch is off')
                _reason = 'EasyNews Direct is off - turn it on in Settings'
            else:
                _log('EasyNews Direct search skipped: set user/password or an EasyNews provider')
                _reason = 'EasyNews Direct needs user/password (or an EasyNews provider)'
            try:
                _win = xbmcgui.Window(10000)
                if not _win.getProperty('tmdbmovies.easynews_direct_hint'):
                    _win.setProperty('tmdbmovies.easynews_direct_hint', '1')
                    _notify('[B][COLOR FFCCCCFF]%s[/COLOR][/B]' % _reason)
            except Exception:
                pass
        if include_en and easynews_direct.available():
            found = easynews_direct.search_custom(query, per_indexer_limit)
            for item in found:
                name = str(item.get('name') or '').strip()
                en_url = str(item.get('url') or '').strip()
                if not name or not en_url:
                    continue
                en_rows.append({
                    'title': name,
                    'size': item.get('size') or 0,
                    'indexer': 'EasyNews Direct',
                    'en_url': en_url,
                })
            _log('EasyNews Direct: %d release(s)' % len(en_rows))
    except Exception as exc:
        _log('EasyNews Direct search failed: %s' % type(exc).__name__)
        notes.append('EasyNews Direct: search failed')
    rows = en_rows + rows
    try:
        _release_records = usenet_config.release_records()
    except Exception:
        _release_records = {}

    for note in notes:
        _log(note)
    _log('query %r -> %d release(s)' % (query, len(rows)))

    search_li = xbmcgui.ListItem(label='[B][COLOR FF00CED1]Search again[/COLOR][/B]')
    search_li.setArt({'icon': _ICON_SEARCH, 'thumb': _ICON_SEARCH})
    xbmcplugin.addDirectoryItem(handle, _url({'mode': 'usenet_search_input'}), search_li, False)

    if not rows:
        reason = notes[0] if notes else 'No results for "%s"' % query
        _item(handle, 'usenet_search', '[B][COLOR FFFF5555]%s[/COLOR][/B]' % reason, folder=False)
        xbmcplugin.endOfDirectory(handle, True, False, True)
        return

    for row in rows:
        title = _clean_title(row.get('title'))
        size_text = _size_text(row.get('size'))
        indexer = row.get('indexer') or 'Usenet'
        plot = ' | '.join(piece for piece in (size_text, indexer) if piece)
        params = {'title': title, 'indexer': indexer, 'size': row.get('size') or 0}
        if row.get('en_url'):
            params['en_key'] = _remember_link('en', row.get('en_url'))
        else:
            params['nzb_key'] = _remember_link('nzb', row.get('nzb_url'))
        _nested = False
        _nzb_link = row.get('nzb_url') or ''
        if _nzb_link and _release_records:
            try:
                _nested = bool((_release_records.get(usenet_config.nzb_key(_nzb_link))
                                or {}).get('nested'))
            except Exception:
                _nested = False
        if _nested:
            plot = ' | '.join(piece for piece in (plot, 'Nested RAR, not streamable') if piece)
        _label = title
        if _nested:
            _label = '%s  [COLOR FFFF5555][B]NESTED RAR[/B][/COLOR]' % title
        li = xbmcgui.ListItem(label=_label)
        li.setArt({'icon': _ICON_SEARCH, 'thumb': _ICON_SEARCH})
        try:
            li.setInfo('video', {'title': title, 'plot': plot, 'mediatype': 'video'})
        except Exception:
            pass
        li.setProperty('IsPlayable', 'true')
        xbmcplugin.addDirectoryItem(
            handle, _url(dict({'mode': 'usenet_custom_play'}, **params)), li, False)
    try:
        xbmcplugin.setContent(handle, 'videos')
    except Exception:
        pass
    xbmcplugin.endOfDirectory(handle, True, False, True)


def history_rename(params=None):
    query = str((params or {}).get('query') or '')
    if not query:
        return
    new_query = xbmcgui.Dialog().input('Rename search', defaultt=query, type=xbmcgui.INPUT_ALPHANUM)
    if not new_query:
        return
    if _history_rename(query, str(new_query).strip()):
        _notify('Renamed')
        xbmc.executebuiltin('Container.Refresh')


def history_delete(params=None):
    query = str((params or {}).get('query') or '')
    if not query:
        return
    _history_remove(query)
    _notify('Deleted')
    xbmc.executebuiltin('Container.Refresh')


def history_clear(params=None):
    _history_clear()
    _notify('History cleared')
    xbmc.executebuiltin('Container.Refresh')


def _play_easynews(handle, remote_url, title='', size=0, indexer='EasyNews Direct'):
    local = ''
    try:
        from resources.lib.api.easynews_proxy import playback_url
        local = playback_url(remote_url)
    except Exception as exc:
        _log('EasyNews proxy failed: %s' % type(exc).__name__)
    if not local:
        try:
            from resources.lib.api.easynews_direct import resolve_playback
            local = resolve_playback(remote_url)
        except Exception as exc:
            _log('EasyNews resolve failed: %s' % type(exc).__name__)
    if not local:
        _notify('EasyNews Direct stream is unavailable')
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
        return
    if '|seekable=' not in local:
        local += '|seekable=1'
    _log('playing EasyNews Direct: %s' % (title or 'stream'))
    li = xbmcgui.ListItem(label=title or 'EasyNews Direct', path=local)
    try:
        li.setInfo('video', _video_info(title, size, indexer))
    except Exception as exc:
        _log('info tag failed: %s' % exc)
    xbmcplugin.setResolvedUrl(handle, True, li)


def play_result(nzb_url, title='', indexer='', size=0, en_url=''):
    handle = _handle()
    if handle < 0:
        return
    if en_url:
        _play_easynews(handle, en_url, title, size, indexer)
        return
    if not nzb_url:
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
        return
    url, why, retry = '', '', False
    progress = xbmcgui.DialogProgressBG()
    try:
        progress.create('Usenet', 'Preparing %s...' % (title[:60] or 'stream'))
    except Exception:
        progress = None
    try:
        from resources.lib.usenet import vfs, server
        try:
            if vfs.enabled() and vfs.available():
                url, why, retry = vfs.prepare_stream(nzb_url, indexer_name=indexer)
                if not url and not retry:
                    _log('VFS failed: %s' % _redact_log(why))
            else:
                why = 'the VFS add-on is off'
        except Exception as exc:
            why = str(exc)[:90]
        if not url:
            try:
                url, why = server.prepare_stream(nzb_url, indexer_name=indexer)
            except Exception as exc:
                url, why = '', str(exc)[:90]
    finally:
        try:
            if progress is not None:
                progress.close()
        except Exception:
            pass
    if not url:
        why = _redact_log(why)
        _record_outcome(indexer, False)
        _log('play failed: %s' % why)
        try:
            xbmcgui.Dialog().notification(
                '[B][COLOR FF00CED1]Usenet[/COLOR][/B]',
                '[B][COLOR FFCCCCFF]%s[/COLOR][/B]' % (why or 'the stream could not be opened'),
                _ICON_SEARCH, 5000)
        except Exception:
            pass
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
        return
    _log('playing %s' % (title or 'release'))
    li = xbmcgui.ListItem(label=title or 'Usenet', path=url)
    try:
        li.setInfo('video', _video_info(title, size, indexer))
    except Exception as exc:
        _log('info tag failed: %s' % exc)
    _record_outcome(indexer, True)
    xbmcplugin.setResolvedUrl(handle, True, li)
