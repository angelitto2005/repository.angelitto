from pathlib import Path
import sys

lib_path = str(Path(__file__).parent)
if lib_path not in sys.path: sys.path.insert(0, lib_path)

if __name__ == '__main__':
	from entry import Router
	Router().run(sys)

