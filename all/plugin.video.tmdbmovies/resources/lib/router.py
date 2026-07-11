from pathlib import Path
import sys

addon_root = str(Path(__file__).parent.parent.parent)
if addon_root not in sys.path:
    sys.path.insert(0, addon_root)

if __name__ == '__main__':
    from entry import run_plugin
    run_plugin()
