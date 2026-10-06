# -*- coding: utf-8 -*-
"""Small stdlib HTTP transport for the vendored YouTube resolver.

Only the Net API consumed by ``ytresolver.kodion.network.netpy`` is exposed.
It deliberately has no dependency on ResolveURL, six or a separate Kodi module.
"""
from __future__ import absolute_import

import gzip
import json
import ssl
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import (
    HTTPBasicAuthHandler,
    HTTPCookieProcessor,
    HTTPHandler,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
)

_DEFAULT_UA = (
    'Mozilla/5.0 (Linux; Android 11; K) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/134.0.0.0 Mobile Safari/537.36'
)


class HttpResponse(object):
    """Subset of ResolveURL's response surface needed by netpy."""

    def __init__(self, response):
        self._response = response
        self._content = None

    @property
    def content(self):
        if self._content is None:
            body = self._response.read()
            if self._response.headers.get('content-encoding', '').lower() == 'gzip':
                try:
                    body = gzip.decompress(body)
                except (OSError, EOFError):
                    pass
            self._content = body
        return self._content

    def get_headers(self, as_dict=False):
        headers = self._response.headers
        if as_dict:
            return {key.title(): value for key, value in headers.items()}
        return list(headers.items())

    def get_url(self):
        return self._response.geturl()

    def close(self):
        try:
            self._response.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()
        return False


class Net(object):
    """Minimal, Python 3 only version of ResolveURL's Net helper."""

    def __init__(self, cookie_file='', proxy='', user_agent='', ssl_verify=True,
                 http_debug=False):
        self._cookies = CookieJar()
        self._proxy = proxy
        self._user_agent = user_agent or _DEFAULT_UA
        self._ssl_verify = bool(ssl_verify)
        self._opener = self._build_opener(http_debug)

    def _build_opener(self, http_debug=False):
        handlers = [
            HTTPCookieProcessor(self._cookies),
            HTTPBasicAuthHandler(),
            HTTPHandler(debuglevel=1 if http_debug else 0),
        ]
        if self._proxy:
            handlers.append(ProxyHandler({'http': self._proxy, 'https': self._proxy}))
        try:
            if self._ssl_verify:
                context = ssl.create_default_context()
            else:
                context = ssl._create_unverified_context()
            handlers.append(HTTPSHandler(context=context, debuglevel=1 if http_debug else 0))
        except Exception:
            handlers.append(HTTPSHandler(debuglevel=1 if http_debug else 0))
        return build_opener(*handlers)

    def _fetch(self, url, form_data=None, headers=None, compression=True,
               jdata=False, timeout=20, method=None):
        headers = dict(headers or {})
        data = None
        if form_data is not None:
            if jdata:
                data = json.dumps(form_data).encode('utf-8')
                headers.setdefault('Content-Type', 'application/json')
            elif isinstance(form_data, bytes):
                data = form_data
            elif isinstance(form_data, str):
                data = form_data.encode('utf-8')
            else:
                data = urlencode(form_data, doseq=True).encode('utf-8')
        request = Request(url, data=data)
        if method:
            request.get_method = lambda: method
        request.add_header('User-Agent', self._user_agent)
        if compression:
            request.add_header('Accept-Encoding', 'gzip')
        for key, value in headers.items():
            request.add_header(key, value)
        # HTTPError is intentionally propagated: the resolver turns it into a
        # normal client failure and can try its compatible mobile fallback.
        return HttpResponse(self._opener.open(request, timeout=timeout))

    def http_GET(self, url, headers=None, compression=True, redirect=True,
                 timeout=20):
        return self._fetch(url, headers=headers, compression=compression,
                           timeout=timeout)

    def http_POST(self, url, form_data, headers=None, compression=True,
                  jdata=False, redirect=True, timeout=20):
        return self._fetch(url, form_data=form_data, headers=headers,
                           compression=compression, jdata=jdata,
                           timeout=timeout)

    def http_HEAD(self, url, headers=None):
        return self._fetch(url, headers=headers, compression=False,
                           method='HEAD')


__all__ = ('Net', 'HttpResponse', 'HTTPError')
