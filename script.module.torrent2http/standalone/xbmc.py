import os

LOGDEBUG = 0
LOGERROR = 4
LOGFATAL = 6
LOGINFO = 1
LOGNONE = 7
LOGNOTICE = 2
LOGSEVERE = 5
LOGWARNING = 3


def translatePath(path):

	if not path.startswith('special:'):
		return path
	
	current = os.path.dirname(__file__)
	root = os.path.abspath(os.path.join(current, os.pardir, os.pardir))
	
	if 'special://home/addons' in path:
		path = path.replace('special://home/addons', '').lstrip('/')
		path = os.path.join(root, path)
	elif 'special://temp' in path:
		path = path.replace('special://temp', '').lstrip('/')
		path = os.path.join(os.getcwd(), 'temp', path)
	else:
		raise Exception(path + ' is not valid')
		
	try:
		path = path.encode('utf-8')
	except:
		pass
		
	return path
	
	
def log(msg, level=LOGNOTICE):
	try:
		print(msg)
	except:
		pass
		
def sleep(t):
	import time
	time.sleep(float(t) / 1000)
		
# noinspection PyPep8Naming,PyUnusedLocal
def executeJSONRPC(jsonrpccommand):
	"""
	executeJSONRPC(jsonrpccommand)--Execute an JSONRPC command.
	jsonrpccommand : string - jsonrpc command to execute.
	List of commands - http://wiki.xbmc.org/?title=JSON-RPC_API
	example:
	- response = xbmc.executeJSONRPC('{ "jsonrpc": "2.0", "method": "JSONRPC.Introspect", "id": 1 }')
	"""
	return ""


# noinspection PyPep8Naming,PyUnusedLocal
def executebuiltin(function, block=False):
	"""
	executebuiltin(function)--Execute a built in XBMC function.
	function : string - builtin function to execute.
	List of functions - http://wiki.xbmc.org/?title=List_of_Built_In_Functions
	example:
	 - xbmc.executebuiltin('XBMC.RunXBE(c:\avalaunch.xbe)')
	"""

	if function.startswith('XBMC.Extract'):
		function = function.replace('XBMC.Extract', '')
		function = function.strip('()')
		params = function.split(',')
		src = params[0].strip('"')
		dst = params[1].strip('"')

		import zipfile
		try:
			zip_ref = zipfile.ZipFile(src, 'r')
			zip_ref.extractall(dst)
			zip_ref.close()
		except BaseException as e:
			print(e)
			raise

	pass
		
		
		
# noinspection PyUnusedLocal,PyMethodMayBeStatic,PyShadowingBuiltins,PyPep8Naming
class Monitor(object):
	"""
	Monitor class.
	Monitor() -- Creates a new Monitor to notify addon about changes.
	"""
	def abortRequested(self):
		return False
	
	def onAbortRequested(self):
		"""
		Deprecated!
		"""
		pass

	def onDatabaseUpdated(self, database):
		"""
		Deprecated!
		"""
		pass

	def onScreensaverActivated(self):
		"""
		onScreensaverActivated() -- onScreensaverActivated method.
		Will be called when screensaver kicks in
		"""
		pass

	def onScreensaverDeactivated(self):
		"""
		onScreensaverDeactivated() -- onScreensaverDeactivated method.
		Will be called when screensaver goes off
		"""
		pass

	def onSettingsChanged(self):
		"""
		onSettingsChanged() -- onSettingsChanged method.
		Will be called when addon settings are changed
		"""
		pass

	def onDatabaseScanStarted(self, database):
		"""
		Deprecated!
		"""
		pass

	def onNotification(self, sender, method, data):
		"""
		onNotification(sender, method, data)--onNotification method.

		sender : sender of the notification
		method : name of the notification
		data : JSON-encoded data of the notification

		Will be called when XBMC receives or sends a notification
		"""
		pass

	def onCleanStarted(self, library=''):
		"""
		onCleanStarted(library)--onCleanStarted method.

		library : video/music as string

		Will be called when library clean has started
		and return video or music to indicate which library is being cleaned
		"""
		pass

	def onCleanFinished(self, library=''):
		"""
		onCleanFinished(library)--onCleanFinished method.

		library : video/music as string

		Will be called when library clean has ended
		and return video or music to indicate which library has been cleaned
		"""
		pass

	def onDPMSActivated(self):
		"""
		onDPMSActivated() --onDPMSActivated method.

		Will be called when energysaving/DPMS gets active
		"""
		pass

	def onDPMSDeactivated(self):
		"""
		onDPMSDeactivated() --onDPMSDeactivated method.

		Will be called when energysaving/DPMS is turned off
		"""
		pass

	def onScanFinished(self, library=''):
		"""
		onScanFinished(library)--onScanFinished method.

		library : video/music as string

		Will be called when library scan has ended
		and return video or music to indicate which library has been scanned
		"""
		pass

	def onScanStarted(self, library=''):
		"""
		onScanStarted(library)--onScanStarted method.

		library : video/music as string

		Will be called when library scan has started
		and return video or music to indicate which library is being scanned
		"""
		pass

	def waitForAbort(self, timeout):
		"""
		waitForAbort([timeout]) -- Block until abort is requested, or until timeout occurs. If an
		abort requested have already been made, return immediately.
		Returns True when abort have been requested, False if a timeout is given and the operation times out.

		:param timeout: float - (optional) timeout in seconds. Default: no timeout.
		:return: bool
		"""
		return False
