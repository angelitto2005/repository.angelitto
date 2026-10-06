# -*- coding: utf-8 -*-
"""Runtime UI translations for NewPipe MOD.

Kodi loads ``strings.po`` according to its own global interface language. This
helper also lets the add-on follow its *Content language* selection, so the
NewPipe MOD menu can change language without changing the rest of Kodi.
"""
from __future__ import absolute_import

import ast
import os
import re

from tulip import kodi

_LANGUAGE_FOLDERS = {
    'pt': 'resource.language.pt_br',
    'pt-br': 'resource.language.pt_br',
    'pt-pt': 'resource.language.pt_pt',
    'en': 'resource.language.en_gb',
    'es': 'resource.language.es_es',
    'fr': 'resource.language.fr_fr',
    'de': 'resource.language.de_de',
    'it': 'resource.language.it_it',
    'nl': 'resource.language.nl_nl',
    'ro': 'resource.language.ro_ro',
    'tr': 'resource.language.tr_tr',
    'ja': 'resource.language.ja_jp',
    'ko': 'resource.language.ko_kr',
}
_ENTRY_RE = re.compile(
    r'msgctxt "#(?P<id>\d+)"\nmsgid "(?P<msgid>(?:\\.|[^"\\])*)"\nmsgstr "(?P<msgstr>(?:\\.|[^"\\])*)"',
    re.MULTILINE,
)
_CACHE = {}


def _setting(key, default=''):
    try:
        value = kodi.setting(key)
    except Exception:
        value = ''
    return value if value not in (None, '') else default


def language():
    """Return the selected menu language or an empty string for Kodi-native UI."""
    selected = str(_setting('interface_language', 'content')).replace('_', '-').strip().lower()
    if selected in ('kodi', 'auto'):
        return ''
    if selected in ('', 'content'):
        selected = str(_setting('content_language', 'en')).replace('_', '-').strip().lower()
    if selected == 'pt':
        country = str(_setting('content_country', '')).upper()
        selected = 'pt-pt' if country in ('PT', 'AO', 'MZ', 'CV') else 'pt-br'
    return selected if selected in _LANGUAGE_FOLDERS else 'en'


def _decode(value):
    try:
        return ast.literal_eval('"' + value + '"')
    except Exception:
        return value.replace('\\n', '\n').replace('\\"', '"').replace('\\\\', '\\')


def _translations(language_code):
    if language_code in _CACHE:
        return _CACHE[language_code]
    folder = _LANGUAGE_FOLDERS.get(language_code)
    if not folder:
        _CACHE[language_code] = {}
        return _CACHE[language_code]
    path = os.path.normpath(os.path.join(
        os.path.dirname(__file__), '..', 'language', folder, 'strings.po'))
    values = {}
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            source = handle.read()
        for match in _ENTRY_RE.finditer(source):
            translated = _decode(match.group('msgstr'))
            original = _decode(match.group('msgid'))
            values[int(match.group('id'))] = translated or original
    except Exception:
        values = {}
    _CACHE[language_code] = values
    return values


def text(string_id, fallback=''):
    """Translate a numeric add-on string id using the selected UI language."""
    if not isinstance(string_id, int):
        return string_id or fallback
    selected = language()
    if selected:
        value = _translations(selected).get(string_id)
        if value:
            return value
    try:
        value = kodi.i18n(string_id)
        # Kodi returns the id itself when an add-on resource is absent.
        if value and str(value) != str(string_id):
            return value
    except Exception:
        pass
    return fallback or str(string_id)


def reset_cache():
    """Test helper and safe hook after a language preference is changed."""
    _CACHE.clear()
