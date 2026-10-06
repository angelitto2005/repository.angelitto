# -*- coding: utf-8 -*-
"""

    Copyright (C) 2014-2016 bromix (plugin.video.youtube)
    Copyright (C) 2016-2025 plugin.video.youtube

    SPDX-License-Identifier: GPL-2.0-only
    See LICENSES/GPL-2.0-only for more information.
"""

from __future__ import absolute_import, division, unicode_literals

from .base_item import BaseItem
from . import context_menu_items
from . import context_menu_items as menu_items
from .command_item import CommandItem
from .directory_item import DirectoryItem
from .image_item import ImageItem
from .media_item import AudioItem, MediaItem, VideoItem
from .next_page_item import NextPageItem
from .search_items import NewSearchItem, SearchHistoryItem, SearchItem
from .uri_item import UriItem
from .utils import from_json
def directory_listitem(*args, **kwargs): return None
def image_listitem(*args, **kwargs): return None
def media_listitem(*args, **kwargs): return None
def playback_item(context, item, **kwargs): return item
def uri_listitem(*args, **kwargs): return None


__all__ = (
    'AudioItem',
    'BaseItem',
    'CommandItem',
    'DirectoryItem',
    'ImageItem',
    'MediaItem',
    'NewSearchItem',
    'NextPageItem',
    'SearchHistoryItem',
    'SearchItem',
    'UriItem',
    'VideoItem',
    'from_json',
    'directory_listitem',
    'image_listitem',
    'media_listitem',
    'playback_item',
    'uri_listitem',
)
