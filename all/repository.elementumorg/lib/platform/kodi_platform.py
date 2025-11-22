import json
import logging
import os
import re
from io import open
from platform import release

import xbmc

try:
    from xbmcvfs import translatePath
except ImportError:
    from xbmc import translatePath

from .definitions import PlatformError, System, Arch, Platform

DARWIN_PLATFORMS = ("macOS", "iOS", "tvOS")
LINUX_PLATFORMS = ("Linux", "webOS")
ANDROID_PLATFORMS = ("Android",)
WINDOWS_PLATFORMS = ("Windows NT", "unknown Win32 platform")
SUPPORTED_PLATFORMS = DARWIN_PLATFORMS + ANDROID_PLATFORMS + LINUX_PLATFORMS + WINDOWS_PLATFORMS + (
    "FreeBSD", "unknown platform")

SUPPORTED_CPUS = ["ARM (Thumb)", "ARM", "LoongArch", "MIPS", "x86", "s390", "PowerPC", "RISC-V", "unknown CPU family"]

_PLATFORM_RE = re.compile(r"^({}) ({}) (\d+)-bit$".format(
    "|".join(map(re.escape, SUPPORTED_PLATFORMS)), "|".join(map(re.escape, SUPPORTED_CPUS))))


def get_application_name():
    cmd = '{"jsonrpc":"2.0", "method":"Application.GetProperties","params": {"properties": ["name"]}, "id":1}'
    data = json.loads(xbmc.executeJSONRPC(cmd))
    return data["result"]["name"]


def get_kodi_log_path():
    log_name = os.path.join(translatePath("special://logpath"), get_application_name().lower())
    return log_name + ".log", log_name + ".old.log"


def get_kodi_platform_from_log():
    # GetBuildTargetPlatformName, GetBuildTargetCpuFamily and GetXbmcBitness from 2nd log line
    # (tree/master -> blob/6d5b46ba127eacd706610a91a32167abfbf8ac8e)
    # https://github.com/xbmc/xbmc/tree/master/xbmc/utils/SystemInfo.cpp
    # https://github.com/xbmc/xbmc/tree/master/xbmc/application/Application.cpp#L3673
    new_log_path, old_log_path = get_kodi_log_path()
    with open(old_log_path if os.path.exists(old_log_path) else new_log_path, encoding="utf-8") as f:
        # Ignore first line
        next(f)
        # Second line ends with the platform
        kodi_platform = next(f).split("Platform: ")[-1].rstrip()

    return kodi_platform


def dump_platform():
    try:
        return get_kodi_platform_from_log()
    except Exception as e:
        logging.warning("Failed getting kodi platform: %s", e, exc_info=True)
        return "unknown"


def get_platform():
    raw_platform = dump_platform()
    logging.debug("Resolving platform - %s", raw_platform)
    match = _PLATFORM_RE.match(raw_platform)
    if not match:
        raise PlatformError("Unable to parse Kodi platform")

    platform_name = match.group(1)
    cpu_family = match.group(2)
    bitness = int(match.group(3))

    if platform_name in ANDROID_PLATFORMS:
        system = System.android
    elif platform_name in LINUX_PLATFORMS:
        system = System.linux
    elif platform_name in WINDOWS_PLATFORMS:
        system = System.windows
    elif platform_name in DARWIN_PLATFORMS:
        system = System.darwin
    else:
        raise PlatformError("Unknown platform: {}".format(platform_name))

    if cpu_family == "ARM":
        if system == System.android:
            arch = Arch.arm64 if bitness == 64 else Arch.arm
        elif system == System.linux:
            arch = Arch.arm64 if bitness == 64 else Arch.armv7
        else:
            raise PlatformError("Unknown arch {} for platform: {}".format(cpu_family, system))
    elif cpu_family == "x86":
        arch = Arch.x64 if bitness == 64 else Arch.x86
    else:
        raise PlatformError("Unknown platform: {}".format(cpu_family))

    return Platform(system, release(), arch)
