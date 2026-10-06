# -*- coding: utf-8 -*-
# NewPipe Addon
# Author Twilight0
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSES/GPL-3.0-only for more information.
# Minimal entry point: every action lives in resources.lib.routes,
# registered on urldispatcher via decorator (import side effect below).
import os
import sys
from sys import argv
from urllib.parse import parse_qsl

# All third-party code required by NewPipe is included in resources/lib.  Kodi
# normally adds only dependency add-ons to sys.path, so register this local
# directory before importing Tulip, Scrapetube or the URL dispatcher.
_LIBRARY_PATH = os.path.join(os.path.dirname(__file__), 'resources', 'lib')
if _LIBRARY_PATH not in sys.path:
    sys.path.insert(0, _LIBRARY_PATH)

from urldispatcher import urldispatcher
from resources.lib import routes  # noqa: F401


_STATE_PREFIX = 'np:'


def _params(argument):
    """Parse a Kodi plugin query and expand NewPipe route state.

    Tulip serializes only a limited set of item properties. Folder routes use
    its ``query`` property to carry a compact, URL-encoded state payload so
    page number, search type and channel tab survive a click.
    """
    params = dict(parse_qsl(argument[1:]))
    state = params.get('query', '')
    if state.startswith(_STATE_PREFIX):
        params.pop('query', None)
        params.update(dict(parse_qsl(state[len(_STATE_PREFIX):])))
    return params


def run(plugin_argv):
    params = _params(plugin_argv[2])
    urldispatcher.dispatch(params.get('action') or 'root', params)


if __name__ == '__main__':
    run(argv)
