import re

import config

from .scrapetube import scrapetube as _scrapetube
from .constants import COUNTRIES, LANGUAGES

_LANGUAGE_RE = re.compile(r'^[a-z]{2,3}(?:-[A-Z]{2})?$')
_COUNTRY_RE = re.compile(r'^[A-Za-z]{2}$')
_COUNTRY_CODES = frozenset((
    'AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI '
    'BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN '
    'CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK '
    'FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM '
    'HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN '
    'KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK '
    'ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP '
    'NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW '
    'SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF '
    'TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI '
    'VN VU WF WS YE YT ZA ZM ZW'
).split())

_original_get_session = None
_original_get_ajax_data = None
_active_language = 'en'
_active_country = 'US'

_COUNTRY_CATEGORY_SUFFIX = {
    'PT': 'Portugal',
    'AO': 'Angola',
    'MZ': 'Mocambique',
    'CV': 'Cabo Verde',
}

_CATEGORY_TERMS = {
    'pt': {'music': 'Musica', 'gaming': 'Jogos', 'news': 'Noticias',
           'movies': 'Filmes', 'live': 'Ao vivo', 'sports': 'Esportes',
           'podcasts': 'Podcasts'},
    'en': {'music': 'Music', 'gaming': 'Gaming', 'news': 'News',
           'movies': 'Movies', 'live': 'Live', 'sports': 'Sports',
           'podcasts': 'Podcasts'},
    'es': {'music': 'Musica', 'gaming': 'Videojuegos', 'news': 'Noticias',
           'movies': 'Peliculas', 'live': 'En vivo', 'sports': 'Deportes',
           'podcasts': 'Podcasts'},
    'fr': {'music': 'Musique', 'gaming': 'Jeux', 'news': 'Actualites',
           'movies': 'Films', 'live': 'En direct', 'sports': 'Sports',
           'podcasts': 'Podcasts'},
    'de': {'music': 'Musik', 'gaming': 'Gaming', 'news': 'Nachrichten',
           'movies': 'Filme', 'live': 'Live', 'sports': 'Sport',
           'podcasts': 'Podcasts'},
    'it': {'music': 'Musica', 'gaming': 'Giochi', 'news': 'Notizie',
           'movies': 'Film', 'live': 'Dal vivo', 'sports': 'Sport',
           'podcasts': 'Podcast'},
    'nl': {'music': 'Muziek', 'gaming': 'Games', 'news': 'Nieuws',
           'movies': 'Films', 'live': 'Live', 'sports': 'Sport',
           'podcasts': 'Podcasts'},
    'ro': {'music': 'Muzica', 'gaming': 'Jocuri', 'news': 'Stiri',
           'movies': 'Filme', 'live': 'Live', 'sports': 'Sport',
           'podcasts': 'Podcasturi'},
    'tr': {'music': 'Muzik', 'gaming': 'Oyunlar', 'news': 'Haberler',
           'movies': 'Filmler', 'live': 'Canli', 'sports': 'Spor',
           'podcasts': 'Podcastler'},
    'ja': {'music': 'Music', 'gaming': 'Game', 'news': 'News',
           'movies': 'Movie', 'live': 'Live', 'sports': 'Sports',
           'podcasts': 'Podcast'},
    'ko': {'music': 'Music', 'gaming': 'Game', 'news': 'News',
           'movies': 'Movie', 'live': 'Live', 'sports': 'Sports',
           'podcasts': 'Podcast'},
}
_LIVE_SUFFIX = {
    'pt': 'ao vivo', 'en': 'live', 'es': 'en vivo', 'fr': 'en direct',
    'de': 'live', 'it': 'dal vivo', 'nl': 'live', 'ro': 'live',
    'tr': 'canli', 'ja': 'live', 'ko': 'live',
}

_TRAILER_TERMS = {
    'original': 'official movie trailer',
    'localized': 'official trailer dubbed',
}


def content_language():
    custom = str(config.get_setting('content_language_custom', '') or '').strip()
    if custom and _LANGUAGE_RE.match(custom.replace('_', '-')):
        return custom.replace('_', '-')
    raw = str(config.get_setting('content_language', '') or '').strip()
    if raw in LANGUAGES:
        return raw
    try:
        index = int(raw)
    except (TypeError, ValueError):
        index = -1
    if 0 <= index < len(LANGUAGES):
        return LANGUAGES[index]
    value = 'en'
    if not custom and value == 'en':
        country = content_country()
        if country in ('US', 'CA', 'GB', 'IE', 'IN', 'PH', 'AU', 'NZ'):
            value = 'en'
    return value


def content_country():
    custom = str(config.get_setting('content_country_custom', '') or '').strip().upper()
    if custom and _COUNTRY_RE.match(custom) and custom in _COUNTRY_CODES:
        return custom
    raw = str(config.get_setting('content_country', '') or '').strip().upper()
    if _COUNTRY_RE.match(raw) and raw in _COUNTRY_CODES:
        return raw
    try:
        index = int(raw)
    except (TypeError, ValueError):
        index = -1
    if 0 <= index < len(COUNTRIES):
        return COUNTRIES[index]
    return 'US'


def trailer_query():
    raw = str(config.get_setting('trailer_audio', '') or '').strip().lower()
    audio = 'localized' if raw in ('localized', '1') else 'original'
    language = content_language().split('-', 1)[0].lower()
    terms = _CATEGORY_TERMS.get(language, _CATEGORY_TERMS['en'])
    base = _TRAILER_TERMS[audio]
    if audio == 'localized' and language != 'en':
        base = 'official movie trailer {0}'.format(terms['movies'].lower())
    return base


def cache_key():
    return '{}:{}'.format(content_language(), content_country())


def _category_identifier(value):
    text = str(value or '').strip()
    if text in _CATEGORY_TERMS['en']:
        return text
    normalized = text.casefold()
    for terms in _CATEGORY_TERMS.values():
        for identifier, label in terms.items():
            label = label.casefold()
            if normalized == label or normalized.startswith(label + ' '):
                return identifier
    return ''


def category_query(category, live=False):
    original = str(category or '').strip()
    identifier = _category_identifier(original)
    if not identifier:
        return original
    language = content_language().split('-', 1)[0].lower()
    terms = _CATEGORY_TERMS.get(language, _CATEGORY_TERMS['en'])
    query = terms.get(identifier, original)
    if live and identifier != 'live':
        suffix = _LIVE_SUFFIX.get(language, 'live')
        if suffix.casefold() not in query.casefold():
            query = '{} {}'.format(query, suffix)
    return query


def regional_category_query(query):
    text = str(query or '').strip()
    suffix = _COUNTRY_CATEGORY_SUFFIX.get(content_country(), '')
    if not suffix or not text or suffix.casefold() in text.casefold():
        return text
    return '{} {}'.format(text, suffix)


def _accept_language(language):
    base = language.split('-', 1)[0]
    return '{},{};q=0.9,en;q=0.5'.format(language, base)


def _localized_session(proxies=None, cookies=None):
    session = _original_get_session(proxies, cookies)
    session.headers['Accept-Language'] = _accept_language(_active_language)
    params = dict(getattr(session, 'params', None) or {})
    params.update({'hl': _active_language, 'gl': _active_country})
    session.params = params
    return session


def _localized_ajax_data(session, api_endpoint, api_key, next_data, client):
    localized_client = dict(client or {})
    localized_client['hl'] = _active_language
    localized_client['gl'] = _active_country
    return _original_get_ajax_data(
        session, api_endpoint, api_key, next_data, localized_client
    )


def configure():
    global _original_get_session, _original_get_ajax_data
    global _active_language, _active_country

    _active_language = content_language()
    _active_country = content_country()

    if _original_get_session is None:
        _original_get_session = _scrapetube.get_session
        _scrapetube.get_session = _localized_session
    if _original_get_ajax_data is None:
        _original_get_ajax_data = _scrapetube.get_ajax_data
        _scrapetube.get_ajax_data = _localized_ajax_data

    return '{}:{}'.format(_active_language, _active_country)