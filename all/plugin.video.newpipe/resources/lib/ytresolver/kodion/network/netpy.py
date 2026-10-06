# -*- coding: utf-8 -*-
"""
net.py-backed HTTP transport for the ytresolver engine.

Strict requirement: NewPipe's bundled net.py-compatible transport is the only
HTTP layer here. No external Kodi library is loaded.

Drop-in replacement for kodion/network/requests.py: provides the same
`BaseRequestsClass` / `InvalidJSONError` names with the same `.request()`
contract (hooks, error mapping, response objects), implemented on top of
the local ``newpipe_net.Net``.

Vendoring note: kodion/network/__init__.py must export from `.netpy`
instead of `.requests` (one-line patch, documented in the vendor notes).
"""

from __future__ import absolute_import, division, unicode_literals

import json as _json
from urllib.parse import urlencode

from .. import logging


__all__ = (
    'BaseRequestsClass',
    'InvalidJSONError',
)


class NetpyError(Exception):
    """Base transport error (takes the place of requests.RequestException)."""

    def __init__(self, *args, **kwargs):
        super(NetpyError, self).__init__(*args)
        self.response = kwargs.get('response')
        self.request = kwargs.get('request')
        for attr, value in kwargs.items():
            if attr not in self.__dict__:
                setattr(self, attr, value)


class NetpyHTTPError(NetpyError):
    """HTTP error with an attached NetpyResponse (`.response`)."""


class InvalidJSONError(ValueError):
    pass


class NetpyResponse(object):
    """Minimal requests.Response surface used by the engine hooks."""

    def __init__(self, status_code, headers, content, url='', reason=''):
        self.status_code = status_code
        self.headers = headers or {}
        self._content = content if isinstance(content, bytes) else (
            content.encode('utf-8') if isinstance(content, str) else b'')
        self.url = url
        self.reason = reason

    @property
    def content(self):
        return self._content

    @property
    def text(self):
        try:
            return self._content.decode('utf-8')
        except UnicodeDecodeError:
            return self._content.decode('utf-8', errors='replace')

    def json(self, **kwargs):
        try:
            return _json.loads(self.text)
        except ValueError as exc:
            raise InvalidJSONError(str(exc))

    def raise_for_status(self):
        if self.status_code is None or not 200 <= self.status_code < 400:
            raise NetpyHTTPError(
                'HTTP status: %r' % (self.status_code,), response=self)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _get_net(verify=True):
    # Imported lazily so the engine remains self-contained inside NewPipe.
    from newpipe_net import Net
    return Net(ssl_verify=bool(verify))


class BaseRequestsClass(object):
    log = logging.getLogger(__name__)

    _nets = {}
    _context = None
    _verify = True
    _timeout = 20
    _default_exc = (NetpyError,)

    METHODS_TO_CACHE = {'GET', 'HEAD'}

    def __init__(self,
                 context=None,
                 verify_ssl=None,
                 timeout=None,
                 proxy_settings=None,
                 exc_type=None,
                 **_kwargs):
        super(BaseRequestsClass, self).__init__()
        BaseRequestsClass.init(
            context=context,
            verify_ssl=verify_ssl,
            timeout=timeout,
            proxy_settings=proxy_settings,
        )
        self._default_exc = (
            (NetpyError,) + exc_type
            if isinstance(exc_type, tuple) else
            (NetpyError, exc_type)
            if exc_type else
            (NetpyError,)
        )

    @classmethod
    def init(cls,
             context=None,
             verify_ssl=None,
             timeout=None,
             proxy_settings=None,
             **_kwargs):
        cls._context = (cls._context
                        if context is None else
                        context)
        if cls._context:
            settings = cls._context.get_settings()
            cls._verify = (settings.verify_ssl()
                           if verify_ssl is None else
                           verify_ssl)
            cls._timeout = (settings.requests_timeout()
                            if timeout is None else
                            timeout)
            if proxy_settings is None:
                proxy_settings = settings.proxy_settings()
            if proxy_settings:
                raise NetpyError(
                    'proxy_settings are not supported by the net.py backend: %r'
                    % (proxy_settings,))

    def reinit(self, **kwargs):
        self.__init__(**kwargs)

    def context_changed(self, context):
        return self._context != context

    def __enter__(self):
        return self

    def __exit__(self, exc_type=None, exc_val=None, exc_tb=None):
        return False

    @classmethod
    def _net(cls, verify=True):
        key = bool(verify)
        net = cls._nets.get(key)
        if net is None:
            net = cls._nets[key] = _get_net(verify=key)
        return net

    @staticmethod
    def _raise_exception(new_exception, *args, **kwargs):
        if not new_exception:
            return
        if isinstance(new_exception, type) and issubclass(new_exception, NetpyError):
            new_exception = new_exception(*args)
            attrs = new_exception.__dict__
            for attr, value in kwargs.items():
                if attr not in attrs:
                    setattr(new_exception, attr, value)
            raise new_exception
        else:
            raise new_exception(*args, **kwargs)

    def _response_hook_json(self, **kwargs):
        response = kwargs['response']
        if response is None:
            return None, None
        with response:
            try:
                json_data = response.json()
                if 'error' in json_data:
                    kwargs.setdefault('pass_data', True)
                    kwargs.setdefault('json_data', json_data)
                    json_data.setdefault('code', response.status_code)
                    self._raise_exception(
                        kwargs.get('exception', NetpyError),
                        '"error" in response JSON data',
                        **kwargs
                    )
            except ValueError as exc:
                if kwargs.get('raise_exc') is None:
                    kwargs['raise_exc'] = True
                self._raise_exception(
                    InvalidJSONError,
                    exc,
                    **kwargs
                )

            response.raise_for_status()

        return json_data.get('etag'), json_data

    def _response_hook_text(self, **kwargs):
        response = kwargs['response']
        if response is None:
            return None, None
        with response:
            response.raise_for_status()
            result = response.text
        if not result:
            self._raise_exception(
                kwargs.get('exception', NetpyError),
                'Empty response text',
                **kwargs
            )

        return None, result

    def request(self, url=None, method='GET',
                params=None, data=None, headers=None, cookies=None, files=None,
                auth=None, timeout=None, allow_redirects=None, proxies=None,
                hooks=None, stream=None, verify=None, cert=None, json=None,
                prepared_request=None,
                response_hook=None,
                error_hook=None,
                event_hook_kwargs=None,
                error_title=None,
                error_info=None,
                raise_exc=None,
                cache=None,
                **kwargs):
        if files or auth or cert or stream or prepared_request:
            raise NetpyError(
                'Unsupported request feature (files/auth/cert/stream/prepared_request)')
        if proxies:
            raise NetpyError('proxies are not supported by the net.py backend')
        if hooks:
            raise NetpyError('requests-hooks are not supported by the net.py backend')
        if method is None:
            method = 'GET'
        method = method.upper()

        if timeout is None:
            timeout = self._timeout
        if isinstance(timeout, (tuple, list)):
            timeout = timeout[1] if len(timeout) > 1 else timeout[0]
        if timeout is None:
            timeout = 20
        if verify is None:
            verify = self._verify

        headers = dict(headers or {})
        if cookies:
            headers['Cookie'] = '; '.join(
                '{0}={1}'.format(k, v) for k, v in cookies.items())

        if params:
            query = urlencode(params, doseq=True)
            url = '{0}{1}{2}'.format(url, '&' if url and '?' in url else '?', query)

        if event_hook_kwargs is None:
            event_hook_kwargs = {}

        try:
            net = self._net(verify=verify)
            if method == 'GET':
                raw = net.http_GET(url, headers=headers, timeout=timeout)
            elif method == 'POST':
                if json is not None:
                    raw = net.http_POST(url, json, headers=headers,
                                        jdata=True, timeout=timeout)
                else:
                    raw = net.http_POST(url, data or {}, headers=headers,
                                        timeout=timeout)
            elif method == 'HEAD':
                raw = net.http_HEAD(url, headers=headers)
            else:
                raise NetpyError('Unsupported method: %r' % (method,))

            body = raw.content
            # NOTE: net.py only surfaces success here (failures raise, see
            # below); urllib only returns without raising on 2xx. Cache the
            # bytes now: HttpResponse.content is a one-shot read upstream.
            if isinstance(body, str):
                body_bytes = body.encode('utf-8')
            else:
                body_bytes = body or b''
            response = NetpyResponse(
                200, raw.get_headers(as_dict=True), body_bytes, url=url)

            if response_hook:
                event_hook_kwargs['exception'] = self._default_exc[-1]
                event_hook_kwargs['raise_exc'] = raise_exc
                event_hook_kwargs['response'] = response
                _, data = response_hook(**event_hook_kwargs)
                return data
            response.raise_for_status()
            return response

        except self._default_exc as exc:
            # Map transport failures (urllib HTTPError carries the status).
            exc_response = getattr(exc, 'response', None)
            if exc_response is None and hasattr(exc, 'code'):
                try:
                    err_body = exc.read()
                except Exception:
                    err_body = b''
                exc_response = NetpyResponse(
                    getattr(exc, 'code', None),
                    dict(getattr(exc, 'headers', {}) or {}),
                    err_body if isinstance(err_body, bytes) else b'',
                    url=url or '')
                exc.response = exc_response

            if exc_response is not None:
                response_text = exc_response.text or repr(exc_response)
                response_status = exc_response.status_code
                response_reason = exc_response.reason or 'No response'
            else:
                response_text = None
                response_status = 'Error'
                response_reason = 'No response'

            log_msg = [
                '{title}',
                'URL:      {method} {url!u}',
                'Status:   {response_status} - {response_reason}',
                'Response: {response_text}',
            ]

            kwargs.update(event_hook_kwargs)
            kwargs['exc'] = exc
            kwargs['response'] = exc_response

            if error_hook:
                error_response = error_hook(**kwargs)
                _title, _info, _detail, _response, _exc = error_response
                if _title is not None:
                    error_title = _title
                if _info:
                    if isinstance(_info, (list, tuple)):
                        log_msg.extend(_info)
                    else:
                        log_msg.append(_info)
                if _detail is not None:
                    kwargs.update(_detail)
                if _response is not None:
                    response = _response
                if _exc is not None:
                    raise_exc = _exc

            if error_info:
                if isinstance(error_info, (list, tuple)):
                    log_msg.extend(error_info)
                else:
                    log_msg.append(error_info)

            self.log.exception(log_msg,
                               title=(error_title or 'Failed'),
                               method=method,
                               url=url,
                               response_status=response_status,
                               response_reason=response_reason,
                               response_text=response_text,
                               **kwargs)

            if raise_exc:
                if not isinstance(raise_exc, BaseException):
                    if not callable(raise_exc):
                        raise_exc = self._default_exc[-1]
                    raise_exc = raise_exc(error_title)

                if isinstance(raise_exc, BaseException):
                    raise_exc.__cause__ = exc
                    raise raise_exc
                raise exc

        return None
