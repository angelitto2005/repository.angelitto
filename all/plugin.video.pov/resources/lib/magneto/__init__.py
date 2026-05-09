
import os
from pkgutil import walk_packages
from modules.kodi_utils import get_setting, logger


sourcePath = os.path.dirname(__file__)
files = os.listdir(sourcePath)
__all__ = [filename[:-3] for filename in files if not filename.startswith('__') and filename.endswith('.py')]

def sources(ret_all=False):
	try:
		sourceDict = []
		append = sourceDict.append
		for loader, module_name, is_pkg in walk_packages([sourcePath]):
			if is_pkg: continue
			if not ret_all and not enabledCheck(module_name): continue
			try: append((module_name, loader.find_spec(module_name).loader.load_module(module_name).source))
			except Exception as e: logger('POV', 'Error: Loading module: "%s": %s' % (module_name, e))
		return sourceDict
	except:
		from fenom import log_utils
		log_utils.error()
		return []

def enabledCheck(module_name):
	try: return get_setting('provider.' + module_name) == 'true'
	except:
		from fenom import log_utils
		log_utils.error()
		return True

