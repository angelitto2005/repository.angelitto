# -*- coding: utf-8 -*-
"""
    Clean, Pythonic logging wrapper for ytresolver using Python's standard logging library
"""
import logging
import sys

CRITICAL = logging.CRITICAL
FATAL = logging.FATAL
ERROR = logging.ERROR
WARNING = logging.WARNING
WARN = logging.WARN
INFO = logging.INFO
DEBUG = logging.DEBUG
NOTSET = logging.NOTSET


class FormattedLogger(logging.Logger):
    """
    Logger wrapper supporting ytresolver's tuple/dict message formatting.
    """
    def _format_msg(self, msg, *args, **kwargs):
        if isinstance(msg, (tuple, list)):
            msg = ' - '.join(str(m) for m in msg)
        if kwargs and 'stacklevel' not in kwargs:
            try:
                fmt_str = str(msg).replace('!v}', '!r}')
                msg = fmt_str.format(**kwargs)
            except Exception:
                pass
        return msg

    @property
    def debugging(self):
        return self.isEnabledFor(logging.DEBUG)

    def debug(self, msg, *args, **kwargs):
        stacklevel = kwargs.pop('stacklevel', 2)
        super().debug(self._format_msg(msg, *args, **kwargs), *args, stacklevel=stacklevel)

    def info(self, msg, *args, **kwargs):
        stacklevel = kwargs.pop('stacklevel', 2)
        super().info(self._format_msg(msg, *args, **kwargs), *args, stacklevel=stacklevel)

    def warning(self, msg, *args, **kwargs):
        stacklevel = kwargs.pop('stacklevel', 2)
        super().warning(self._format_msg(msg, *args, **kwargs), *args, stacklevel=stacklevel)

    def error(self, msg, *args, **kwargs):
        stacklevel = kwargs.pop('stacklevel', 2)
        super().error(self._format_msg(msg, *args, **kwargs), *args, stacklevel=stacklevel)

    def exception(self, msg, *args, **kwargs):
        stacklevel = kwargs.pop('stacklevel', 2)
        super().exception(self._format_msg(msg, *args, **kwargs), *args, stacklevel=stacklevel)


logging.setLoggerClass(FormattedLogger)


def getLogger(name=None):
    logger = logging.getLogger(name or 'ytresolver')
    return logger


def log(level, msg, *args, **kwargs):
    getLogger().log(level, msg, *args, **kwargs)


def debug(msg, *args, **kwargs):
    getLogger().debug(msg, *args, **kwargs)


def info(msg, *args, **kwargs):
    getLogger().info(msg, *args, **kwargs)


def warning(msg, *args, **kwargs):
    getLogger().warning(msg, *args, **kwargs)


def error(msg, *args, **kwargs):
    getLogger().error(msg, *args, **kwargs)


def exception(msg, *args, **kwargs):
    getLogger().exception(msg, *args, **kwargs)
