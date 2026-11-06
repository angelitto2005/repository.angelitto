"""The settings from Settings > Usenet, read in the shape the engine wants."""

import hashlib
import os
import re

PORT_BY_CHOICE = ('563', '443', '119')
CLIENT_AGENTS = (
    '',
    'SABnzbd/4.4.2',
    'NZBGet/21.1',
    'Sonarr/4.0.12.2823',
    'Radarr/5.18.4.9677',
    'Prowlarr/1.30.2.4933',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    '',
)
CUSTOM_CLIENT = 7
DEFAULT_TIMEOUT = 20
DEFAULT_CONNECTIONS = 8
DEFAULT_PREFETCH_MB = 12
DEFAULT_CACHE_MB = 36
DEFAULT_HOLE_PERCENT = 2
DEFAULT_HOLE_CONSECUTIVE = 4
NZB_KEEP_SECONDS = 3 * 86400
NZB_MAX_BYTES = 256 * 1024 * 1024
INDEXER_SLOTS = 6


def addon():
    from resources.lib.core.config import ADDON
    return ADDON


def text(key, default=''):
    try:
        value = addon().getSetting(key)
    except Exception:
        return default
    if value is None or value == '':
        return default
    return value


def flag(key, default=False):
    value = str(text(key, '')).strip().lower()
    if not value:
        return default
    return value in ('true', '1', 'yes', 'on')


def number(key, default, low=None, high=None):
    try:
        value = int(float(str(text(key, '')).strip()))
    except Exception:
        value = default
    if low is not None:
        value = max(low, value)
    if high is not None:
        value = min(high, value)
    return value


# -- files ---------------------------------------------------------------------

def profile_dir():
    try:
        import xbmcvfs
        path = xbmcvfs.translatePath(addon().getAddonInfo('profile'))
    except Exception:
        return ''
    path = path.replace('\\', '/')
    return path if path.endswith('/') else path + '/'


def data_file(name):
    return profile_dir() + name


def nzb_dir():
    path = profile_dir() + 'usenet/nzb/'
    try:
        if not os.path.isdir(path):
            os.makedirs(path)
    except Exception:
        return ''
    return path


def nzb_key(url):
    """Same key everywhere: md5 of the NZB link, without the API key on disk."""
    return hashlib.md5((url or '').encode('utf-8')).hexdigest()


def nzb_path(key):
    folder = nzb_dir()
    return (folder + key + '.nzb') if folder else ''


def cleanup_nzb(max_age=NZB_KEEP_SECONDS, max_bytes=NZB_MAX_BYTES):
    """Drop old NZBs, then the oldest ones until the folder fits max_bytes.

    A plan only needs its NZB while it is built or reused, so an old file is
    worth nothing; the size cap keeps a long browsing session from growing the
    profile without bound.
    """
    folder = nzb_dir()
    if not folder:
        return
    import time
    now = time.time()
    try:
        names = os.listdir(folder)
    except Exception:
        return
    kept = []
    for name in names:
        path = folder + name
        try:
            stat = os.stat(path)
            if now - stat.st_mtime > max_age:
                os.remove(path)
                continue
            kept.append((stat.st_mtime, stat.st_size, path))
        except Exception:
            continue
    total = sum(size for _mtime, size, _path in kept)
    if total <= max_bytes:
        return
    for _mtime, size, path in sorted(kept):
        try:
            os.remove(path)
            total -= size
        except Exception:
            continue
        if total <= max_bytes:
            break


# -- prefs ---------------------------------------------------------------------

def enabled():
    return flag('use_usenet_nzb')


def episodes_only():
    return flag('usenet_nzb.episodes_only', True)


def min_size_bytes():
    return number('usenet_nzb.min_size_mb', 50, 0, 500) * 1024 * 1024


def max_results():
    return number('usenet_nzb.max_results', 30, 5, 60)


def indexer_agent():
    """The identity sent to indexers; empty means the add-on's own name."""
    choice = number('usenet_nzb.client', 0, 0, len(CLIENT_AGENTS) - 1)
    if choice == CUSTOM_CLIENT:
        return str(text('usenet_nzb.user_agent', '')).strip()
    return CLIENT_AGENTS[choice]


def health_mode():
    """0 = off, 1 = when playing, 2 = while listing."""
    return number('usenet_nzb.health', 1, 0, 2)


def health_max():
    return number('usenet_nzb.health_max', 8, 1, 20)


def timeout():
    return number('usenet_nzb.timeout', DEFAULT_TIMEOUT, 10, 60)


def prefetch_bytes():
    return number('usenet_nzb.prefetch_mb', DEFAULT_PREFETCH_MB, 4, 64) * 1024 * 1024


def cache_bytes():
    return number('usenet_nzb.cache_mb', DEFAULT_CACHE_MB, 8, 128) * 1024 * 1024


def age_badge():
    return flag('usenet_nzb.age_badge', True)


def grabs_badge():
    """How many times the NZB was grabbed - a good sign it is still there."""
    return flag('usenet_nzb.grabs_badge', True)


def hole_filling():
    """Keep playing a slightly damaged release instead of refusing it."""
    return flag('usenet_nzb.hole_filling', True)


def hole_percent():
    """0 = no percentage limit, otherwise how much of the read data may be missing."""
    return number('usenet_nzb.hole_percent', DEFAULT_HOLE_PERCENT, 0, 10)


def hole_consecutive():
    """0 = no run limit, otherwise how many articles in a row may be gone."""
    return number('usenet_nzb.hole_consecutive', DEFAULT_HOLE_CONSECUTIVE, 0, 30)


def player_options():
    return {'timeout': timeout(), 'prefetch_bytes': prefetch_bytes(), 'cache_bytes': cache_bytes(),
            'hole_filling': hole_filling(), 'hole_percent': hole_percent(),
            'hole_consecutive': hole_consecutive()}


# -- providers -----------------------------------------------------------------

def provider_enabled(index):
    return flag('usenet_nzb.provider%d.enabled' % index, True)


def provider(index):
    if not provider_enabled(index):
        return None
    host = str(text('usenet_nzb.provider%d.host' % index, '')).strip()
    if not host:
        return None
    if '://' in host:
        host = host.split('://', 1)[1]
    host = host.split('/', 1)[0].strip()
    if not host:
        return None
    port = PORT_BY_CHOICE[number('usenet_nzb.provider%d.port' % index, 0, 0, 2)]
    return {
        'index': index,
        'label': host,
        'host': host,
        'port': int(port),
        'ssl': flag('usenet_nzb.provider%d.ssl' % index, True),
        'connections': number('usenet_nzb.provider%d.connections' % index, DEFAULT_CONNECTIONS, 1, 60),
        'user': str(text('usenet_nzb.provider%d.user' % index, '')).strip(),
        'password': str(text('usenet_nzb.provider%d.password' % index, '')),
        'backup': index == 2 and flag('usenet_nzb.provider2.backup', True),
        'timeout': timeout(),
    }


def providers():
    return [item for item in (provider(1), provider(2)) if item]


def primary_providers():
    marked = [item for item in providers() if not item.get('backup')]
    return marked or providers()[:1]


def backup_providers():
    primary = set(item.get('index') for item in primary_providers())
    return [item for item in providers() if item.get('backup') and item.get('index') not in primary]


_PROVIDER_NAMES = {
    'easynews.com': 'EasyNews',
    'newshosting.com': 'Newshosting',
    'tweaknews.eu': 'TweakNews',
    'tweak-news.eu': 'TweakNews',
    'eweka.nl': 'Eweka',
    'usenetserver.com': 'UsenetServer',
    'frugalusenet.com': 'Frugal Usenet',
    'blocknews.net': 'BlockNews',
    'newsdemon.com': 'NewsDemon',
    'usenetexpress.com': 'UsenetExpress',
    'vipernews.com': 'ViperNews',
    'giganews.com': 'GigaNews',
    'xsusenet.com': 'XS Usenet',
}

STATE_FILE = 'usenet_state.json'
PRIMARY_DOWN_SECONDS = 600
SERVED_SECONDS = 600


def provider_name(item):
    """'news.easynews.com' -> 'EasyNews' - what the user sees in the list."""
    host = str((item or {}).get('host') or '').lower()
    if not host:
        return ''
    for key, name in _PROVIDER_NAMES.items():
        if host == key or host.endswith('.' + key):
            return name
    cleaned = re.sub(r'^(news|secure|ssl|reader)\.', '', host)
    return cleaned.split('.')[0].capitalize()


def state():
    try:
        import json
        with open(data_file(STATE_FILE), encoding='utf-8') as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _state_update(values):
    import json
    data = state()
    data.update(values)
    path = data_file(STATE_FILE)
    if not path:
        return
    try:
        temp = path + '.tmp'
        with open(temp, 'w', encoding='utf-8') as handle:
            json.dump(data, handle)
        os.replace(temp, path)
    except Exception:
        pass


def mark_primary_down(seconds=PRIMARY_DOWN_SECONDS):
    """The primary refused a connection: the backup answers until this expires."""
    import time
    _state_update({'primary_down_until': time.time() + seconds})


def clear_primary_down():
    import time
    if state().get('primary_down_until'):
        _state_update({'primary_down_until': 0, 'primary_ok_at': time.time()})


def provider_down():
    import time
    try:
        return float(state().get('primary_down_until') or 0) > time.time()
    except Exception:
        return False


def mark_served(item, seconds=SERVED_SECONDS):
    """Remember who actually answered: the list stops guessing from settings."""
    name = provider_name(item)
    if not name:
        return
    import time
    _state_update({'served_by': name, 'served_at': time.time()})


def active_provider_name():
    """Who serves the next stream: the one that served last, or the expected one."""
    import time
    data = state()
    served, when = data.get('served_by'), float(data.get('served_at') or 0)
    if served and time.time() - when < SERVED_SECONDS:
        return served
    primary = primary_providers()
    backup = backup_providers()
    if primary and not (backup and provider_down()):
        return provider_name(primary[0])
    if backup:
        return provider_name(backup[0])
    return provider_name(primary[0]) if primary else ''


def providers_ready():
    return all(item.get('user') and item.get('password') for item in primary_providers())


# -- indexers ------------------------------------------------------------------

_PRESETS = {
    'nzbgeek': 'NZBgeek', 'api.nzbgeek.info': 'NZBgeek',
    'nzbfinder': 'NZBFinder', 'nzbfinder.ws': 'NZBFinder',
    'drunkenslug': 'DrunkenSlug', 'drunkenslug.com': 'DrunkenSlug',
    'nzbplanet': 'NZBPlanet', 'api.nzbplanet.net': 'NZBPlanet',
    'nzbsu': 'nzb.su', 'api.nzb.su': 'nzb.su',
    'althub': 'altHUB', 'api.althub.co.za': 'altHUB',
    'ninjacentral': 'NinjaCentral', 'ninjacentral.co.za': 'NinjaCentral',
    'usenet-crawler': 'Usenet Crawler', 'usenet-crawler.com': 'Usenet Crawler',
    'nzbstars': 'NZBStars', 'nzbstars.com': 'NZBStars',
    'tabula-rasa': 'Tabula Rasa', 'tabula-rasa.pw': 'Tabula Rasa',
    'nzb.su': 'nzb.su',
    'nzb.info': 'NZB.Info', 'api.nzb.info': 'NZB.Info',
}


def normalise_url(value):
    url = str(value or '').strip().split('?', 1)[0].rstrip('/')
    if not url:
        return ''
    if not re.match(r'https?://', url, re.I):
        url = 'https://' + url
    if not url.lower().endswith('/api'):
        url += '/api'
    return url


def indexer_name(url):
    host = re.sub(r'^https?://', '', str(url or ''), flags=re.I).split('/', 1)[0].lower()
    for key, name in _PRESETS.items():
        if host == key or host.startswith(key + '.'):
            return name
    cleaned = re.sub(r'^(api|www|feed)\.', '', host)
    for key, name in _PRESETS.items():
        if cleaned == key:
            return name
    return cleaned.split('.')[0].capitalize() or 'Indexer'


def split_entry(chunk):
    """'https://api.site.com : KEY' -> ('https://api.site.com', 'KEY').

    The colon of 'https:' is not the separator, so the last colon wins, and only
    when what follows it looks like a key: no slash, no space. A '|' or a plain
    space still work, and '?apikey=KEY' links are understood too.
    """
    chunk = (chunk or '').strip()
    if not chunk:
        return '', ''
    known = re.search('[?&]apikey=([^& ]+)', chunk, re.I)
    if known:
        return chunk[:known.start()], known.group(1)
    if '|' in chunk:
        url, key = chunk.split('|', 1)
        return url.strip(), key.strip()
    at = chunk.rfind(':')
    if at > 0:
        url = chunk[:at].strip()
        key = chunk[at + 1:].strip()
        if key and not any(ch in key for ch in '/?&') and not any(ch.isspace() for ch in key):
            if '://' in url or ('.' in url and not any(ch.isspace() for ch in url)):
                return url, key
    pieces = chunk.split(None, 1)
    return pieces[0], (pieces[1].strip() if len(pieces) > 1 else '')


def _indexer(url, key):
    url = normalise_url(url)
    key = str(key or '').strip()
    if not url or not key or any(ch.isspace() for ch in key):
        return None
    return {'name': indexer_name(url), 'url': url, 'key': key}


def parse_indexers(raw):
    """'address : key, address : key' -> [{'name', 'url', 'key'}]."""
    found = []
    for chunk in re.split('[,;\n]+', str(raw or '')):
        item = _indexer(*split_entry(chunk))
        if item:
            found.append(item)
    return found


def indexer_slot(number):
    """One of the six indexer slots, or None when it is off or incomplete."""
    if not flag('usenet_nzb.indexer%d.enabled' % number, False):
        return None
    return _indexer(text('usenet_nzb.indexer%d.url' % number, ''),
                    text('usenet_nzb.indexer%d.key' % number, ''))


def indexers_enabled():
    return flag('usenet_nzb.indexers.enabled', True)


def indexers():
    """The slots in order, then the extra comma list; one entry per address."""
    if not indexers_enabled():
        return []
    found = []
    seen = set()
    for number in range(1, INDEXER_SLOTS + 1):
        item = indexer_slot(number)
        if item and item['url'] not in seen:
            seen.add(item['url'])
            found.append(item)
    for item in parse_indexers(text('usenet_nzb.indexers', '')):
        if item['url'] not in seen:
            seen.add(item['url'])
            found.append(item)
    return found


def fetch_mode():
    """'sequential' asks one indexer at a time, 'parallel' asks all of them."""
    return 'parallel' if number('usenet_nzb.fetch_mode', 0, 0, 1) == 1 else 'sequential'


def stop_after():
    """In sequential mode the next indexer is asked while fewer are usable."""
    return number('usenet_nzb.stop_after', 4, 1, 10)


def ready():
    return bool(enabled() and indexers() and providers() and providers_ready())
