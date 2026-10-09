import datetime
import json
import os

import xbmc
import xbmcaddon
import xbmcvfs

ADDON_ID = 'tmdbm.trailers'
ADDON = xbmcaddon.Addon(ADDON_ID)
ADDON_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo('path'))
ADDON_PROFILE = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
MEDIA_DIR = os.path.join(ADDON_PATH, 'resources', 'media')

if not os.path.isdir(ADDON_PROFILE):
    try:
        os.makedirs(ADDON_PROFILE)
    except OSError:
        pass


def log(msg, level=xbmc.LOGINFO):
    try:
        xbmc.log('[{}] {}'.format(ADDON_ID, msg), level)
    except Exception:
        pass


def debug(msg):
    log(msg, xbmc.LOGDEBUG)


def get_setting(name, default=''):
    """Read a setting fresh at call time.

    With reuselanguageinvoker the single ADDON object caches values at import
    time, so settings changed while the interpreter stays alive are not seen.
    Reading through JSON-RPC (Settings Manager) bypasses that stale C++ cache.
    """
    try:
        res = xbmc.executeJSONRPC(
            '{{"jsonrpc":"2.0","method":"Settings.GetSettingValue",'
            '"params":{{"setting":"{}.{}"}},"id":1}}'.format(ADDON_ID, name))
        val = json.loads(res).get('result', {}).get('value')
        if val is not None:
            return str(val)
    except Exception:
        pass
    try:
        return ADDON.getSetting(name)
    except Exception:
        return default


def get_int(name, default=0):
    try:
        return int(str(get_setting(name, default)).strip())
    except (TypeError, ValueError):
        return default


def get_bool(name, default=False):
    return str(get_setting(name, 'true' if default else 'false')).lower() == 'true'


def icon(name):
    path = os.path.join(MEDIA_DIR, str(name) + '.png')
    return path if os.path.isfile(path) else ''


def addon_icon():
    path = os.path.join(ADDON_PATH, 'icon.png')
    return path if os.path.isfile(path) else ''


def profile_path(name):
    return os.path.join(ADDON_PROFILE, name)


def relative_date(value):
    """Date for the info column: "3 months ago", "1 year ago".

    YouTube already sends that text for most results, so it is passed through;
    a raw 20240104 or 2024-01-04 is turned into the same wording.
    """
    text = str(value or '').strip()
    if not text:
        return ''
    if not text.isdigit() and '-' not in text:
        return text
    digits = ''.join(ch for ch in text if ch.isdigit())
    if len(digits) < 8:
        return text
    try:
        stamp = datetime.datetime(int(digits[0:4]), int(digits[4:6]),
                                  int(digits[6:8]))
    except ValueError:
        return text
    delta = datetime.datetime.now() - stamp
    days = delta.days
    if days < 0:
        return text
    if days < 1:
        return 'today'
    if days == 1:
        return '1 day ago'
    if days < 7:
        return '{} days ago'.format(days)
    if days < 31:
        weeks = days // 7
        return '{} week{} ago'.format(weeks, '' if weeks == 1 else 's')
    if days < 365:
        months = max(1, days // 30)
        return '{} month{} ago'.format(months, '' if months == 1 else 's')
    years = max(1, days // 365)
    return '{} year{} ago'.format(years, '' if years == 1 else 's')


def ensure_dir(path):
    try:
        if not os.path.isdir(path):
            os.makedirs(path)
    except OSError:
        pass
    return path