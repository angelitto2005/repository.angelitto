"""
certifi.py
~~~~~~~~~~

This module returns the installation location of cacert.pem or its contents.

Kodi ships Python 3.8 (Omega) up to 3.14 (Piers), so the upstream
``importlib.resources`` version switches are replaced by a plain filesystem
lookup: an addon is never zipimported, so the package always sits on disk.
"""
import os

__all__ = ["contents", "where"]


def where() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "cacert.pem")


def contents() -> str:
    with open(where(), encoding="ascii") as data:
        return data.read()
