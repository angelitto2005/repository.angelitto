import re
from functools import total_ordering

_digits_re = re.compile(r"(\d+)")


@total_ordering
class InfinityType(object):
    def __repr__(self):
        return "Infinity"

    def __hash__(self):
        return hash(repr(self))

    def __eq__(self, other):
        return isinstance(other, self.__class__)

    def __ge__(self, other):
        return True

    def __neg__(self):
        return NegativeInfinity


@total_ordering
class NegativeInfinityType(object):
    def __repr__(self):
        return "-Infinity"

    def __hash__(self):
        return hash(repr(self))

    def __eq__(self, other):
        return isinstance(other, self.__class__)

    def __le__(self, other):
        return True

    def __neg__(self):
        return Infinity


@total_ordering
class _BaseVersion(object):
    _key = None

    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return None
        return self._key == other._key

    def __lt__(self, other):
        if not isinstance(other, self.__class__):
            return None
        return self._key < other._key


class Version(_BaseVersion):
    _version_re = re.compile(r"""
        ^v?
        (?P<release>[0-9]+(?:\.[0-9]+)*)
        (?P<extra>[^+]*)
        (?:\+(?P<build>.*))?
        $
    """, re.VERBOSE | re.IGNORECASE)

    def __init__(self, value, case_insensitive=True):
        if case_insensitive:
            value = value.lower()

        match = self._version_re.match(value)
        if match is None:
            raise ValueError("Invalid version {}".format(repr(value)))

        self._release = tuple(int(i) for i in match.group("release").split("."))
        self._extra = match.group("extra")
        self._build = match.group("build")
        self._key = self._make_key()

    def _make_key(self):
        for i, v in enumerate(reversed(self._release)):
            if v != 0:
                release = self._release[:len(self._release) - i]
                break
        else:
            release = ()

        extra = _nat_tuple(self._extra + "0") if self._extra else Infinity

        return release, extra


class DebianVersion(_BaseVersion):
    def __init__(self, version):
        self._key = _nat_tuple(version, lambda v: v.split("~") + [Infinity])


Infinity = InfinityType()
NegativeInfinity = NegativeInfinityType()


def try_parse_version(version, default=None):
    try:
        return Version(version)
    except ValueError:
        return default


def _nat_tuple(value, converter=lambda a: a):
    return tuple(converter(c) if i % 2 == 0 else int(c) for i, c in enumerate(_digits_re.split(value)))
