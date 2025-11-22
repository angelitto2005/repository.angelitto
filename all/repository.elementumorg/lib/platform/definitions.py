from collections import namedtuple


class PlatformError(Exception):
    pass


class Enum:
    @classmethod
    def values(cls):
        return [value for name, value in vars(cls).items() if not name.startswith("_")]


class System(Enum):
    linux = "linux"
    android = "android"
    darwin = "darwin"
    windows = "windows"


class Arch(Enum):
    x64 = "x64"
    x86 = "x86"
    arm = "arm"
    arm64 = "arm64"
    armv7 = "armv7"


class Platform(namedtuple("Platform", ["system", "version", "arch"])):
    def name(self, sep="-"):
        return self.system + sep + self.arch


SHARED_LIB_EXTENSIONS = {System.linux: ".so", System.android: ".so", System.darwin: ".dylib", System.windows: ".dll"}
EXECUTABLE_EXTENSIONS = {System.linux: "", System.android: "", System.darwin: "", System.windows: ".exe"}
