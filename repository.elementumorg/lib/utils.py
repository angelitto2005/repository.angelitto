import json
import logging
import sys

try:
    from urllib.request import urlopen, Request
    from urllib.parse import urlparse, urlencode
    from urllib.error import HTTPError
except ImportError:
    # noinspection PyUnresolvedReferences
    from urllib2 import urlopen, Request, HTTPError
    # noinspection PyUnresolvedReferences
    from urlparse import urlparse
    # noinspection PyUnresolvedReferences
    from urllib import urlencode

PY3 = sys.version_info.major >= 3

if PY3:
    string_types = str

    def str_to_unicode(s):
        return s

    def str_to_bytes(s):
        return s.encode()
else:
    # noinspection PyUnresolvedReferences
    string_types = basestring  # noqa

    def str_to_unicode(s):
        return s.decode("utf-8")

    def str_to_bytes(s):
        return s


def remove_prefix(text, prefix):
    return text[len(prefix):] if text.startswith(prefix) else text


def is_http_like(s):
    try:
        result = urlparse(s)
        return result.netloc and result.scheme in ("http", "https")
    except ValueError:
        return False


def request(url, params=None, data=None, headers=None, **kwargs):
    if params:
        url += "?" + urlencode(params)
    request_params = Request(url, data=data, headers=headers if headers else {})
    logging.debug("Doing a HTTP %s request to %s", request_params.get_method(), url)
    try:
        response = urlopen(request_params, **kwargs)
    except HTTPError as e:
        response = e
    logging.debug(
        "HTTP %s response from %s received with status %s",
        request_params.get_method(), url, response.getcode())
    return Response(response)


class HTTPResponseError(Exception):
    def __init__(self, message, response):
        super(HTTPResponseError, self).__init__(message)
        self.response = response


class Response(object):
    def __init__(self, response):
        self._response = response
        self._content = None

    @property
    def content(self):
        if self._content is None:
            self._content = self._response.read()
        return self._content

    @property
    def raw(self):
        return self._response

    @property
    def headers(self):
        return self._response.info()

    @property
    def status_code(self):
        return self._response.getcode()

    def json(self, **kwargs):
        return json.loads(self.content, **kwargs)

    def raise_for_status(self):
        if 400 <= self.status_code < 500:
            raise HTTPResponseError("Client Error: {}".format(self.status_code), self)
        elif 500 <= self.status_code < 600:
            raise HTTPResponseError("Server Error: {}".format(self.status_code), self)

    def close(self):
        self._response.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()
