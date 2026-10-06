# -*- coding: utf-8 -*-
"""

    Copyright (C) 2023-2025 plugin.video.youtube

    SPDX-License-Identifier: GPL-2.0-only
    See LICENSES/GPL-2.0-only for more information.
"""

from __future__ import absolute_import, division, unicode_literals

from .standalone.standalone_context import StandaloneContext
from .abstract_context import AbstractContext

XbmcContext = StandaloneContext

__all__ = ('StandaloneContext', 'AbstractContext', 'XbmcContext')
