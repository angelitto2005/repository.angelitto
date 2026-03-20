import os

try:
    from ctypes import c_int, cdll
    ctypes_is_supported = True
except:
    ctypes_is_supported = False

platforms = {
    'android': [
        'arm64',
        'arm',
        'x64',
        'x86'
    ],
    'linux': [
        'arm64',
        'armv7',
        'armv7_softfp',
        'armv6',
        'x64',
        'x86'
    ],
    'windows': [
        'x64',
        'x86'
    ],
    'darwin': [
        'x64'
    ]
}


# We try to detect a proper platform by loading different precompiled shared libraries.
# Proper library should return '42' as a result to a 'int test()' method call.
# We give preference to a 'higher' arch (x64 over x96, arm64 over armv7, etc).
def detect_platform():
    if not ctypes_is_supported:
        return None
    for system in platforms.keys():
        for arch in platforms.get(system):
            try:
                library_path = get_library_path(system, arch)
                if not library_path:
                    continue

                # Try to load a library
                lib = cdll.LoadLibrary(library_path)

                # Make library call
                lib.test.restype = c_int
                result = lib.test()

                # Close the library, to avoid locking the file by a process
                # TODO: removing library close for Linux for now, due to reported segfaults
                if '.so' not in library_path:
                    try:
                        from ctypes import windll
                        windll.kernel32.FreeLibrary(lib._handle)
                    except:
                        pass

                # if '.so' in library_path:
                #     try:
                #         lib.dlclose(lib._handle)
                #     except:
                #         pass
                # else:
                #     try:
                #         from ctypes import windll
                #         windll.kernel32.FreeLibrary(lib._handle)
                #     except:
                #         pass

                if result and result == 42:
                    return system + "-" + arch
            except:
                pass
    return None

def get_library_path(system, arch):
    sub_dir = system + "_" + arch

    base_dir = os.path.dirname(__file__)
    if os.path.exists(os.path.join(base_dir, "libraries", sub_dir, "test.dll")):
        return os.path.join(base_dir, "libraries", sub_dir, "test.dll")
    elif os.path.exists(os.path.join(base_dir, "libraries", sub_dir, "test.so")):
        return os.path.join(base_dir, "libraries", sub_dir, "test.so")

    base_dir = os.path.join(os.path.dirname(__file__), "..")
    if os.path.exists(os.path.join(base_dir, "libraries", sub_dir, "test.dll")):
        return os.path.join(base_dir, "libraries", sub_dir, "test.dll")
    elif os.path.exists(os.path.join(base_dir, "libraries", sub_dir, "test.so")):
        return os.path.join(base_dir, "libraries", sub_dir, "test.so")

    return None
