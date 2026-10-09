import config
from .cache import FunctionCache

CACHE_DIR = config.ensure_dir(config.profile_path('cache'))
_FUNCTION_CACHE = FunctionCache(CACHE_DIR)

cache_function = _FUNCTION_CACHE.cache_function
reset_cache = _FUNCTION_CACHE.reset_cache

PER_PAGE = (5, 10, 15, 20, 25, 30, 35, 40, 45, 50)
FEED_PER_CHANNEL = (1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20)

COUNTRIES = ('AO', 'AR', 'AT', 'AU', 'BE', 'BR', 'CA', 'CH', 'CL', 'CO', 'CV',
             'DK', 'ES', 'FI', 'FR', 'GB', 'GR', 'ID', 'IE', 'IN', 'IT', 'JP',
             'KR', 'MX', 'MZ', 'NL', 'NO', 'NZ', 'PE', 'PH', 'PL', 'PT', 'RO',
             'SE', 'TR', 'US', 'ZA')

LANGUAGES = ('pt-PT', 'pt-BR', 'en', 'es', 'fr', 'de', 'it', 'nl', 'ro', 'tr',
             'ja', 'ko')

TRENDING_CATEGORIES = ('music', 'gaming', 'news', 'movies', 'live')
LIVE_CATEGORIES = ('news', 'music', 'gaming', 'sports', 'podcasts')
TRAILER_AUDIO = ('original', 'localized')
SUBTITLE_MODES = ('off', 'original', 'preferred')


def _enum(name, values, fallback_index):
    raw = str(config.get_setting(name, '') or '').strip()
    for value in values:
        if raw == value or raw.lower() == str(value).lower():
            return value
    try:
        index = int(raw)
    except (TypeError, ValueError):
        index = -1
    if 0 <= index < len(values):
        return values[index]
    return values[fallback_index]


def results_per_page():
    return _enum('results_per_page', PER_PAGE, 4)


def feed_per_channel():
    return _enum('feed_per_channel', FEED_PER_CHANNEL, 4)


def trending_category():
    return _enum('trending_category', TRENDING_CATEGORIES, 0)


def live_category():
    return _enum('live_category', LIVE_CATEGORIES, 0)


def trailer_audio():
    return _enum('trailer_audio', TRAILER_AUDIO, 0)


def autoplay_next():
    """Master switch: keep playing the next videos of the same list."""
    return config.get_bool('autoplay_next', True)


def shuffle_play():
    """Shuffle switch: random order instead of the list order."""
    return config.get_bool('shuffle_play', False)


def subtitles_enabled():
    return _enum('subtitles', SUBTITLE_MODES, 0)


def cache_duration(minutes):
    return 0 if config.get_bool('debug', False) else minutes