# -*- coding: utf-8 -*-
"""YouTube content country/language support.

This mirrors the NewPipe Extractor approach: every YouTube request receives an
explicit content language (``hl``) and content country (``gl``), rather than
leaving the result selection to an exit-node/IP location.
"""
import re

from tulip import kodi
import scrapetube.scrapetube as _scrapetube


_DEFAULT_LANGUAGE = 'pt'
_DEFAULT_COUNTRY = 'BR'
_LANGUAGE_RE = re.compile(r'^[a-z]{2,3}(?:-[A-Z]{2})?$')
_COUNTRY_RE = re.compile(r'^[A-Z]{2}$')

_original_get_session = None
_original_get_ajax_data = None
_active_language = _DEFAULT_LANGUAGE
_active_country = _DEFAULT_COUNTRY
_COUNTRY_CATEGORY_SUFFIX = {
    # Portuguese is a shared language. YouTube's search relevance still sends
    # the generic Portuguese category words to Brazil even with gl=PT. Add a
    # country qualifier only to built-in browse categories; normal user
    # searches remain untouched.
    'PT': 'Portugal',
    'AO': 'Angola',
    'MZ': 'Moçambique',
    'CV': 'Cabo Verde',
}

# Labels in the Kodi interface stay in the interface language, but a category
# search must use the *configured YouTube content language*. Sending ``Música``
# while requesting ``hl=ro&gl=RO`` still asks YouTube for Portuguese content.
# These are the exact query terms sent for every language offered in settings.
_CATEGORY_TERMS = {
    'pt': {'music': 'Música', 'gaming': 'Jogos', 'news': 'Notícias',
           'movies': 'Filmes', 'live': 'Ao vivo', 'sports': 'Esportes',
           'podcasts': 'Podcasts'},
    'en': {'music': 'Music', 'gaming': 'Gaming', 'news': 'News',
           'movies': 'Movies', 'live': 'Live', 'sports': 'Sports',
           'podcasts': 'Podcasts'},
    'es': {'music': 'Música', 'gaming': 'Videojuegos', 'news': 'Noticias',
           'movies': 'Películas', 'live': 'En vivo', 'sports': 'Deportes',
           'podcasts': 'Pódcasts'},
    'fr': {'music': 'Musique', 'gaming': 'Jeux', 'news': 'Actualités',
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
    'ro': {'music': 'Muzică', 'gaming': 'Jocuri', 'news': 'Știri',
           'movies': 'Filme', 'live': 'Live', 'sports': 'Sport',
           'podcasts': 'Podcasturi'},
    'tr': {'music': 'Müzik', 'gaming': 'Oyunlar', 'news': 'Haberler',
           'movies': 'Filmler', 'live': 'Canlı', 'sports': 'Spor',
           'podcasts': 'Podcastler'},
    'ja': {'music': '音楽', 'gaming': 'ゲーム', 'news': 'ニュース',
           'movies': '映画', 'live': 'ライブ', 'sports': 'スポーツ',
           'podcasts': 'ポッドキャスト'},
    'ko': {'music': '음악', 'gaming': '게임', 'news': '뉴스',
           'movies': '영화', 'live': '라이브', 'sports': '스포츠',
           'podcasts': '팟캐스트'},
}
_LIVE_SUFFIX = {
    'pt': 'ao vivo', 'en': 'live', 'es': 'en vivo', 'fr': 'en direct',
    'de': 'live', 'it': 'dal vivo', 'nl': 'live', 'ro': 'live',
    'tr': 'canlı', 'ja': 'ライブ', 'ko': '라이브',
}


def _setting(name, default):
    try:
        value = kodi.setting(name)
    except Exception:
        value = ''
    return str(value or default).strip()


def _custom_or_setting(custom_name, setting_name, default):
    """Prefer an optional manually entered code over the visible picker."""
    custom = _setting(custom_name, '')
    return custom or _setting(setting_name, default)


def content_language():
    """Return a safe YouTube ``hl`` code; default to Portuguese."""
    custom = _setting('content_language_custom', '')
    value = (custom or _setting('content_language', _DEFAULT_LANGUAGE)).replace('_', '-')
    # Old installations store the generic ``pt`` value. Make it regional so
    # changing just the country from Brazil to Portugal also changes YouTube's
    # language preference to pt-PT rather than leaving Brazilian Portuguese.
    if not custom and value.lower() == 'pt':
        country = content_country()
        if country == 'PT':
            value = 'pt-PT'
        elif country == 'BR':
            value = 'pt-BR'
    if not _LANGUAGE_RE.match(value):
        return _DEFAULT_LANGUAGE
    return value


def content_country():
    """Return a safe YouTube ``gl`` country code; default to Brazil."""
    value = _custom_or_setting(
        'content_country_custom', 'content_country', _DEFAULT_COUNTRY).upper()
    if not _COUNTRY_RE.match(value):
        return _DEFAULT_COUNTRY
    return value


def cache_key():
    """A locale-sensitive cache key so a setting change never reuses old results."""
    return '{0}:{1}'.format(content_language(), content_country())


def _category_identifier(value):
    """Resolve category ids and old localized route terms to one stable id."""
    text = str(value or '').strip()
    if text in _CATEGORY_TERMS['en']:
        return text
    normalized = text.casefold()
    for terms in _CATEGORY_TERMS.values():
        for identifier, label in terms.items():
            label = label.casefold()
            # Handles persisted routes from previous versions, such as
            # ``Música`` and ``Notícias ao vivo``.
            if normalized == label or normalized.startswith(label + ' '):
                return identifier
    return ''


def category_query(category, live=False):
    """Return a category query in the selected YouTube content language.

    A free-text query is deliberately left untouched; only internal category
    ids/labels are translated. This lets a user search any phrase manually.
    """
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
            query = '{0} {1}'.format(query, suffix)
    return query


def regional_category_query(query):
    """Disambiguate built-in category words for small shared-language markets."""
    text = str(query or '').strip()
    suffix = _COUNTRY_CATEGORY_SUFFIX.get(content_country(), '')
    if not suffix or not text or suffix.casefold() in text.casefold():
        return text
    return '{0} {1}'.format(text, suffix)


def _accept_language(language):
    base = language.split('-', 1)[0]
    return '{0},{1};q=0.9,en;q=0.5'.format(language, base)


def _localized_session(proxies=None, cookies=None):
    session = _original_get_session(proxies, cookies)
    session.headers['Accept-Language'] = _accept_language(_active_language)
    params = dict(getattr(session, 'params', None) or {})
    params.update({'hl': _active_language, 'gl': _active_country})
    session.params = params
    return session


def _localized_ajax_data(session, api_endpoint, api_key, next_data, client):
    # Scrapetube forwards the client it parsed from the first page. Force the
    # same locale in every continuation request, matching NewPipe Extractor's
    # InnerTube ``context.client.hl`` / ``context.client.gl`` behavior.
    localized_client = dict(client or {})
    localized_client['hl'] = _active_language
    localized_client['gl'] = _active_country
    return _original_get_ajax_data(
        session, api_endpoint, api_key, next_data, localized_client
    )


def configure():
    """Apply the active Kodi content locale to Scrapetube safely and idempotently."""
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

    return '{0}:{1}'.format(_active_language, _active_country)
