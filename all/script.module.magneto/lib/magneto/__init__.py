"""
	Fenomscrapers Module
"""

import os
from pkgutil import walk_packages
from magneto.modules.control import setting as getSetting

debug = getSetting('debug.enabled') == 'true'
sourceFolder = 'providers'

def sources(specified_folders=None, ret_all=False):
	try:
		sourceDict = []
		append = sourceDict.append
		sourceFolderLocation = os.path.join(os.path.dirname(__file__), sourceFolder)
		sourceSubFolders = [x[1] for x in os.walk(sourceFolderLocation)][0]
		if specified_folders: sourceSubFolders = specified_folders
		for i in sourceSubFolders:
			for loader, module_name, is_pkg in walk_packages([os.path.join(sourceFolderLocation, i)]):
				if is_pkg: continue
				if ret_all or enabledCheck(module_name):
					try:
#						module = loader.find_module(module_name).load_module(module_name)
						module = loader.find_spec(module_name).loader.load_module(module_name)
						append((module_name, module.source))
					except Exception as e:
						if debug:
							from magneto.modules import log_utils
							log_utils.log('Error: Loading module: "%s": %s' % (module_name, e), level=log_utils.LOGWARNING)
		return sourceDict
	except:
		from magneto.modules import log_utils
		log_utils.error()
		return []

def enabledCheck(module_name):
	try:
		if getSetting('provider.' + module_name) == 'true': return True
		else: return False
	except:
		from magneto.modules import log_utils
		log_utils.error()
		return True
