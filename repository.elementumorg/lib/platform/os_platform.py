import logging
import os
import platform
import sys

from .definitions import Arch, System, Platform


def get_platform():
    system = platform.system().lower()
    version = platform.release()
    arch = Arch.x64 if sys.maxsize > 2 ** 32 else Arch.x86
    machine = platform.machine().lower()
    is_arch64 = "64" in machine and arch == Arch.x64

    logging.debug("Resolving platform - system=%s, version=%s, arch=%s, machine=%s", system, version, arch, machine)

    if "ANDROID_STORAGE" in os.environ:
        system = System.android
        if "arm" in machine or "aarch" in machine:
            arch = Arch.arm64 if is_arch64 else Arch.arm
    elif system == System.linux:
        if "armv7" in machine:
            arch = Arch.armv7
        elif "aarch" in machine:
            arch = Arch.arm64 if is_arch64 else Arch.armv7
        elif "arm" in machine:
            arch = Arch.arm64 if is_arch64 else Arch.arm
    elif system == System.windows:
        if machine.endswith("64"):
            arch = Arch.x64
    elif system == System.darwin:
        arch = Arch.x64

    if system not in System.values() or arch not in Arch.values():
        logging.warning("Unknown system (%s) and/or arch (%s) values", system, arch)

    return Platform(system, version, arch)


def dump_platform():
    return "system: {}\nrelease: {}\nmachine: {}\narchitecture: {}\nmax_size: {} ({:x} {})\nplatform: {}".format(
        platform.system(), platform.release(), platform.machine(), platform.architecture(), sys.maxsize,
        sys.maxsize, ">32b" if sys.maxsize > 2 ** 32 else "<=32b", platform.platform())
