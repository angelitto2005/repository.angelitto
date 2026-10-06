# -*- coding: utf-8 -*-

'''
    Tulip library
    Author Twilight0

    SPDX-License-Identifier: GPL-3.0-only
    See LICENSES/GPL-3.0-only for more information.
'''

import sys
from urllib.parse import parse_qsl

argv = sys.argv

try:
    syshandle = int(argv[1])
except IndexError:
    syshandle = -1

sysaddon = argv[0]

try:

    params_tuple = parse_qsl(argv[2][1:])
    params = dict(params_tuple)

except IndexError:

    params = {'action': None}

__all__ = ["syshandle", "sysaddon", "params"]
