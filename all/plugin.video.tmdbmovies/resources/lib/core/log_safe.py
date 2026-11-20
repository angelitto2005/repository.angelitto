"""Mask API keys and passwords before a value reaches a Kodi log line."""

import re

_SECRET = re.compile(r'(?i)((?:apikey|api_key|passkey|token|key|sig|signature|password|pwd)=)[^&\s\'"]+')
_QUERY_R = re.compile(r'(?i)([?&]r=)[^&\s\'"]+')
_CREDENTIALS = re.compile(r'(https?://)[^/\s:@]+:[^/\s@]+@')


def redact_text(value):
    """The same string with key, token and password values replaced by ***."""
    clean = _SECRET.sub(r'\1***', str(value or ''))
    clean = _QUERY_R.sub(r'\1***', clean)
    return _CREDENTIALS.sub(r'\1***@', clean)


def clean(value, name=''):
    """A log-safe copy of a dict/list tree; _torrent_b64 keeps only its size."""
    if name == '_torrent_b64':
        return '<%d chars>' % len(value) if isinstance(value, str) else '<bytes>'
    if isinstance(value, dict):
        return {key: clean(item, key) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(item, name) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value
