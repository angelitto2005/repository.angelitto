
import os
import importlib
from pkgutil import iter_modules
from modules.kodi_utils import get_setting, logger


sourcePath = os.path.dirname(__file__)
files = os.listdir(sourcePath)
__all__ = [filename[:-3] for filename in files if not filename.startswith('__') and filename.endswith('.py')]

def sources(ret_all=False):
	try:
		sourceDict = []
		append = sourceDict.append
		for loader, module_name, is_pkg in iter_modules([sourcePath]):
			if is_pkg: continue
			if not ret_all and not enabledCheck(module_name): continue
			try: module_source = importlib.import_module('.' + module_name, package=__name__).source
			except Exception as e: logger('POV', 'Error: Loading module: "%s": %s' % (module_name, e))
			else: append((module_name, module_source))
		return sourceDict
	except:
		from magneto.modules import log_utils
		log_utils.error()
		return []

def enabledCheck(module_name):
	try: return get_setting('provider.' + module_name) == 'true'
	except:
		from magneto.modules import log_utils
		log_utils.error()
		return True

