import hashlib
import os

import config

from . import segno

DONATE_URL = 'https://ko-fi.com/angelitto'


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


def cleanup():
    """Delete stale activation QRs (kept until login succeeds)."""
    try:
        folder = config.ensure_dir(config.ADDON_PROFILE)
    except Exception:
        return 0
    try:
        keep = os.path.basename(_file_name(DONATE_URL))
    except Exception:
        keep = ''
    removed = 0
    try:
        names = os.listdir(folder)
    except OSError:
        return 0
    for name in names:
        if not name.startswith('yt-login-qr-') or not name.endswith('.png'):
            continue
        if keep and name == keep:
            continue
        try:
            os.remove(os.path.join(folder, name))
            removed += 1
        except OSError:
            pass
    return removed