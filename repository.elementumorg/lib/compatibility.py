import importlib
import os
import re
import sys
from xml.etree import ElementTree  # nosec

import xbmc
import xbmcaddon

from lib.version import DebianVersion

PY3 = sys.version_info.major >= 3

_digits_re = re.compile(r"(\d+)")


class UndefinedModuleError(ImportError):
    pass


class InvalidModuleVersionError(ImportError):
    pass


def register_module(name, module=None, py2_module=None, py3_module=None, version=None):
    try:
        importlib.import_module(name)
        xbmc.log("{} module is already installed".format(name), xbmc.LOGDEBUG)
    except ImportError:
        xbmc.log("Failed to import module. Going to register it.", xbmc.LOGDEBUG)
        module = module or (py3_module if PY3 else py2_module)
        if module is None:
            raise UndefinedModuleError("No module was defined")
        if has_addon(module):
            xbmc.log("{} module is already installed, but missing on addon.xml".format(name), xbmc.LOGDEBUG)
            import_module(module, version=version)
        else:
            install_and_import_module(name, module, version=version)


def import_module(module, version=None):
    addon = xbmcaddon.Addon(module)
    addon_path = addon.getAddonInfo("path")
    addon_version = addon.getAddonInfo("version")
    if not PY3:
        # noinspection PyUnresolvedReferences
        addon_path = addon_path.decode("utf-8")
        # noinspection PyUnresolvedReferences
        addon_version = addon_version.decode("utf-8")
    if version is not None and DebianVersion(addon_version) < DebianVersion(version):
        raise InvalidModuleVersionError("No valid version for module {}: {} < {}".format(
            module, addon_version, version))
    tree = ElementTree.parse(os.path.join(addon_path, "addon.xml"))
    # Check for dependencies
    for dependency in tree.findall("./requires//import"):
        dependency_module = dependency.attrib["addon"]
        if dependency_module.startswith("script.module."):
            xbmc.log("{} module depends on {}. Going to import it.".format(module, dependency_module), xbmc.LOGDEBUG)
            import_module(dependency_module, dependency.attrib.get("version"))
    # Install the actual module
    library_path = tree.find("./extension[@point='xbmc.python.module']").attrib["library"]
    sys.path.append(os.path.join(addon_path, library_path))


def install_and_import_module(name, module, version=None):
    xbmc.log("Installing and registering module {}:{}".format(name, module), xbmc.LOGINFO)
    install_addon(module)
    import_module(module, version=version)


def install_addon(addon):
    xbmc.executebuiltin("InstallAddon(" + addon + ")", wait=True)


def has_addon(addon):
    return xbmc.getCondVisibility("System.HasAddon(" + addon + ")")
