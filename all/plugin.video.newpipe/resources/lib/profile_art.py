# -*- coding: utf-8 -*-
"""Local circular artwork for subscribed YouTube channel profiles.

YouTube TV returns protocol-relative ``//yt3.googleusercontent.com`` profile
URLs. Kodi does not resolve those URLs in ListItem artwork, so a folder falls
back to its generic icon. This module first normalizes the URL and, when the
optional Pillow module already available in Kodi is present, stores a circular
PNG copy in the add-on profile. Failure to download or process a profile never
prevents a subscriptions sync: its original HTTPS artwork is used instead.
"""
from __future__ import absolute_import

from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
from io import BytesIO
import os
import sys
from urllib.request import Request, urlopen

from . import storage

_CACHE_DIR = 'channel_avatars'
_MAX_AVATARS_PER_SYNC = 120
_TIMEOUT = 8
_MAX_IMAGE_BYTES = 2 * 1024 * 1024


def normalize_url(url):
    """Return an artwork URL Kodi can load directly."""
    value = str(url or '').strip()
    if value.startswith('//'):
        return 'https:' + value
    return value


def _pillow():
    """Load Kodi's optional PIL module without adding an install dependency."""
    try:
        from PIL import Image, ImageDraw
        return Image, ImageDraw
    except ImportError:
        pass

    # Recent Kodi Android builds commonly ship script.module.pil. It is not a
    # required dependency of NewPipe: this merely lets the feature use it when
    # it is already installed, while normal HTTPS artwork remains the fallback.
    try:
        import xbmcaddon
        module_path = xbmcaddon.Addon('script.module.pil').getAddonInfo('path')
        library_path = os.path.join(module_path, 'lib')
        if library_path and library_path not in sys.path:
            sys.path.insert(0, library_path)
        from PIL import Image, ImageDraw
        return Image, ImageDraw
    except Exception:
        return None, None


def _cache_path(url):
    folder = os.path.join(storage.PROFILE, _CACHE_DIR)
    digest = sha256(url.encode('utf-8')).hexdigest()
    return folder, os.path.join(folder, digest + '.png')


def _fetch(url):
    request = Request(url, headers={'User-Agent': 'Kodi NewPipe profile artwork'})
    with urlopen(request, timeout=_TIMEOUT) as response:
        payload = response.read(_MAX_IMAGE_BYTES + 1)
    if len(payload) > _MAX_IMAGE_BYTES:
        raise ValueError('profile image is too large')
    return payload


def _make_circle(url, image_module, draw_module):
    """Download one source avatar and write a transparent circular PNG."""
    folder, target = _cache_path(url)
    if os.path.isfile(target) and os.path.getsize(target) > 0:
        return target

    source = _fetch(url)
    avatar = image_module.open(BytesIO(source)).convert('RGBA')
    side = min(avatar.size)
    if side <= 0:
        raise ValueError('invalid profile image')
    left = (avatar.width - side) // 2
    top = (avatar.height - side) // 2
    avatar = avatar.crop((left, top, left + side, top + side))

    # A compact 176px cached avatar is sharp in Kodi's list views and avoids
    # repeatedly decoding a potentially much larger source image.
    output_size = min(176, side)
    if avatar.size != (output_size, output_size):
        resampling = getattr(getattr(image_module, 'Resampling', image_module), 'LANCZOS')
        avatar = avatar.resize((output_size, output_size), resampling)
    mask = image_module.new('L', (output_size, output_size), 0)
    draw_module.Draw(mask).ellipse((0, 0, output_size - 1, output_size - 1), fill=255)
    avatar.putalpha(mask)

    os.makedirs(folder, exist_ok=True)
    temporary = target + '.tmp'
    avatar.save(temporary, format='PNG', optimize=True)
    try:
        os.replace(temporary, target)
    except AttributeError:
        if os.path.isfile(target):
            os.remove(target)
        os.rename(temporary, target)
    return target


def prepare_channel_profiles(channels):
    """Normalize and, where supported, circularize subscribed-channel art.

    Returns a new list and never raises for one bad network image. The channel
    title and URL remain untouched, so browsing is independent from artwork.
    """
    entries = [dict(entry or {}) for entry in (channels or [])]
    targets = []
    for index, entry in enumerate(entries):
        source_url = normalize_url(entry.get('image'))
        entry['image'] = source_url
        if source_url.startswith(('https://', 'http://')):
            targets.append((index, source_url))

    image_module, draw_module = _pillow()
    if not image_module or not draw_module:
        return entries

    targets = targets[:_MAX_AVATARS_PER_SYNC]
    if not targets:
        return entries
    # Profile artwork is non-essential. Bounded workers prevent a large account
    # from blocking the Kodi UI or opening many parallel connections.
    with ThreadPoolExecutor(max_workers=4) as executor:
        pending = {
            executor.submit(_make_circle, url, image_module, draw_module): index
            for index, url in targets
        }
        for task in as_completed(pending):
            try:
                entries[pending[task]]['image'] = task.result()
            except Exception:
                # Keep the normalized remote picture as the graceful fallback.
                pass
    return entries
