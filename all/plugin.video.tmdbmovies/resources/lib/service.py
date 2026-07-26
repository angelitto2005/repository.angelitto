from pathlib import Path
import sys

addon_root = str(Path(__file__).parent.parent.parent)
if addon_root not in sys.path:
    sys.path.insert(0, addon_root)

from entry import run_service
run_service()
