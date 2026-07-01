import os
import platform
import struct
import zipfile
import shutil

import xbmc
import xbmcgui
import xbmcvfs
import xbmcaddon

IS_ANDROID = xbmc.getCondVisibility('System.Platform.Android')


def _get_profile():
    try:
        return xbmcvfs.translatePath(
            xbmcaddon.Addon('tmdbm.trailers').getAddonInfo('profile')
        )
    except Exception:
        return None


def _get_dest_dir():
    profile = _get_profile()
    if not profile:
        return None
    dest = os.path.join(profile, 'js_runtime')
    if not os.path.exists(dest):
        try:
            os.makedirs(dest)
        except Exception:
            pass
    return dest


def _get_system_arch():
    if IS_ANDROID:
        return 'Android', ''

    system = platform.system()
    if system == 'Windows':
        arch = platform.architecture()[0].lower()
    else:
        try:
            arch = platform.machine().lower()
        except Exception:
            arch = ''

    if 'aarch64' in arch or 'arm64' in arch:
        arch = 'arm64' if struct.calcsize("P") * 8 == 64 else 'armv7'
    elif 'arm' in arch:
        arch = 'armv7'
    elif arch == 'i686':
        arch = 'i386'

    return system, arch


def _clear_dir(dest_dir):
    for f in os.listdir(dest_dir):
        try:
            os.remove(os.path.join(dest_dir, f))
        except Exception:
            pass


def install_deno(reinstall=False):
    if IS_ANDROID:
        return None

    dest_dir = _get_dest_dir()
    if not dest_dir:
        return None

    import requests
    VERSION = '2.1.13'
    SOURCES = {
        'Windows64bit': 'https://github.com/denoland/deno/releases/download/v{}/deno-x86_64-pc-windows-msvc.zip'.format(VERSION),
        'Linuxx86_64': 'https://github.com/denoland/deno/releases/download/v{}/deno-x86_64-unknown-linux-gnu.zip'.format(VERSION),
        'Linuxarm64': 'https://github.com/denoland/deno/releases/download/v{}/deno-aarch64-unknown-linux-gnu.zip'.format(VERSION),
        'Darwinx86_64': 'https://github.com/denoland/deno/releases/download/v{}/deno-x86_64-apple-darwin.zip'.format(VERSION),
        'Darwinarm64': 'https://github.com/denoland/deno/releases/download/v{}/deno-aarch64-apple-darwin.zip'.format(VERSION),
    }

    system, arch = _get_system_arch()
    url = SOURCES.get(system + arch)
    if not url:
        return None

    ext = '.exe' if system == 'Windows' else ''
    dst_file = os.path.join(dest_dir, 'deno_' + VERSION + ext)
    if os.path.exists(dst_file) and not reinstall:
        return dst_file

    progress = xbmcgui.DialogProgress()
    progress.create('Installing Deno', 'Downloading...')
    try:
        _clear_dir(dest_dir)
        resp = requests.get(url, stream=True, timeout=60)
        zip_path = dst_file + '.zip'
        total = int(resp.headers.get('content-length', 0))
        downloaded = 0
        with open(zip_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    progress.update(int(downloaded * 100 / total))
                if progress.iscanceled():
                    return None

        progress.update(90, 'Extracting...')
        with zipfile.ZipFile(zip_path, 'r') as z:
            z.extractall(dest_dir)
        os.remove(zip_path)

        extracted = os.path.join(dest_dir, os.listdir(dest_dir)[0])
        if extracted != dst_file:
            if os.path.exists(dst_file):
                os.remove(dst_file)
            os.rename(extracted, dst_file)
        os.chmod(dst_file, 0o775)
        return dst_file
    except Exception as e:
        xbmc.log('[tmdbm.trailers] Deno install error: {}'.format(str(e)), xbmc.LOGERROR)
        return None
    finally:
        progress.close()


def install_node(reinstall=False):
    if IS_ANDROID:
        return None

    dest_dir = _get_dest_dir()
    if not dest_dir:
        return None

    import requests
    SOURCES = {
        'Windows64bit': 'https://nodejs.org/dist/v22.12.0/node-v22.12.0-win-x64.zip',
        'Windows32bit': 'https://nodejs.org/dist/v22.12.0/node-v22.12.0-win-x86.zip',
        'Linuxx86_64': 'https://nodejs.org/dist/v22.12.0/node-v22.12.0-linux-x64.tar.gz',
        'Linuxarm64': 'https://nodejs.org/dist/v22.12.0/node-v22.12.0-linux-arm64.tar.gz',
        'Darwinx86_64': 'https://nodejs.org/dist/v22.12.0/node-v22.12.0-darwin-x64.tar.gz',
        'Darwinarm64': 'https://nodejs.org/dist/v22.12.0/node-v22.12.0-darwin-arm64.tar.gz',
    }

    system, arch = _get_system_arch()
    url = SOURCES.get(system + arch)
    if not url:
        return None

    ext = '.exe' if system == 'Windows' else ''
    import re
    ver = re.search(r'v(\d+\.\d+\.\d+)', url).group(1)
    dst_file = os.path.join(dest_dir, 'node-v{}-{}-{}{}'.format(ver, system.lower(), arch, ext))
    if os.path.exists(dst_file) and not reinstall:
        return dst_file

    progress = xbmcgui.DialogProgress()
    progress.create('Installing Node.js', 'Downloading...')
    try:
        _clear_dir(dest_dir)
        filename = os.path.basename(url)
        dl_path = os.path.join(dest_dir, filename)
        resp = requests.get(url, stream=True, timeout=60)
        total = int(resp.headers.get('content-length', 0))
        downloaded = 0
        with open(dl_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    progress.update(int(downloaded * 100 / total))
                if progress.iscanceled():
                    return None

        progress.update(90, 'Extracting...')
        if dl_path.endswith('.gz'):
            import tarfile
            with tarfile.open(dl_path, 'r:gz') as z:
                for member in z.getmembers():
                    if member.isfile() and member.name.lower().endswith('/bin/node'):
                        with z.extractfile(member) as f_in, open(dst_file, 'wb') as f_out:
                            shutil.copyfileobj(f_in, f_out, length=65536)
                        break
                else:
                    return None
        elif dl_path.endswith('.zip'):
            with zipfile.ZipFile(dl_path, 'r') as z:
                for name in z.namelist():
                    if os.path.basename(name).lower() in ('node.exe', 'node'):
                        with z.open(name) as src, open(dst_file, 'wb') as dst:
                            while True:
                                chunk = src.read(65536)
                                if not chunk:
                                    break
                                dst.write(chunk)
                        break
                else:
                    return None

        os.remove(dl_path)
        os.chmod(dst_file, 0o775)
        return dst_file
    except Exception as e:
        xbmc.log('[tmdbm.trailers] Node.js install error: {}'.format(str(e)), xbmc.LOGERROR)
        return None
    finally:
        progress.close()


def install_js(reinstall=False):
    path = install_deno(reinstall=reinstall)
    if path:
        return {"deno": {'path': path}}

    path = install_node(reinstall=reinstall)
    if path:
        return {'node': {'path': path}}

    return None
