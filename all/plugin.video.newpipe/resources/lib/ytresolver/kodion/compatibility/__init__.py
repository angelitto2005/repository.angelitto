# -*- coding: utf-8 -*-
"""
    Pure Python 3 compatibility bridge for ytresolver using standard library and kodi_six
"""
import os
import sys
import pickle
import hashlib
from html import escape as entity_escape, unescape
from io import StringIO
from http.server import BaseHTTPRequestHandler
from socketserver import TCPServer, ThreadingMixIn
from urllib.parse import (
    parse_qs,
    parse_qsl,
    quote,
    quote_plus,
    unquote,
    unquote_plus,
    urlencode,
    urljoin,
    urlsplit,
    urlunsplit,
)

# Standard Kodi mock / runtime bridge from kodi_six
import kodi_six
from kodi_six import xbmc, xbmcaddon, xbmcgui, xbmcplugin, xbmcvfs

string_type = str
to_str = str
to_unicode = str
range_type = (range, list)


def available_cpu_count():
    try:
        return os.cpu_count() or 1
    except Exception:
        return 1


def generate_hash(value):
    if not isinstance(value, bytes):
        value = str(value).encode('utf-8')
    return hashlib.md5(value).hexdigest()


def datetime_infolabel(dt=None):
    from datetime import datetime
    dt = dt or datetime.now()
    return dt.strftime('%Y-%m-%d %H:%M:%S')
