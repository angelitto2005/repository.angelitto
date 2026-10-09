import hashlib
import os

import config

from . import segno


def _file_name(qr_url):
    digest = hashlib.sha256(str(qr_url).encode('utf-8')).hexdigest()[:16]
    return os.path.join(config.ensure_dir(config.ADDON_PROFILE),
                        'yt-login-qr-{0}.png'.format(digest))


def create(qr_url):
    """Render the device activation QR as a high contrast PNG."""
    if not qr_url:
        raise ValueError('QR URL is required')
    path = _file_name(qr_url)
    code = segno.make(qr_url, error='q')
    code.save(path, scale=8, border=4, dark='#0f172a', light='#ffffff')
    return path