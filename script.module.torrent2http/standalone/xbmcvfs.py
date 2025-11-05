import os

def encode_fs(string): 
	return string

# noinspection PyUnusedLocal,PyMethodMayBeStatic,PyShadowingBuiltins,PyPep8Naming,PyBroadException
def mkdir(path):
	"""Create a folder.

	path: folder

	Example:
		success = xbmcfvs.mkdir(path)
	"""
	if os.path.exists(path):
		return False


	try:
		os.mkdir(encode_fs(path))
		return True
	except BaseException as e:
		print(e)
		raise AssertionError("Can't makedirs %s", path)
		return False


# noinspection PyUnusedLocal,PyMethodMayBeStatic,PyShadowingBuiltins,PyPep8Naming,PyBroadException
def mkdirs(path):
	"""
	mkdirs(path)--Create folder(s) - it will create all folders in the path.

	path : folder

	example:

	- success = xbmcvfs.mkdirs(path)
	"""
	
	if os.path.exists(path):
		return False
	
	try:
		os.makedirs(encode_fs(path))
		return True
	except BaseException as e:
		print(e)
		raise AssertionError("Can't makedirs %s", path)
		return False

# noinspection PyUnusedLocal,PyMethodMayBeStatic,PyShadowingBuiltins,PyPep8Naming,PyBroadException
def exists(path):
	"""Checks for a file or folder existance, mimics Pythons os.path.exists()

	path: string - file or folder

	Example:
		success = xbmcvfs.exists(path)"""
	try:
		return os.path.exists(encode_fs(path))
	except:
		return False

# noinspection PyUnusedLocal,PyMethodMayBeStatic,PyShadowingBuiltins,PyPep8Naming,PyBroadException
def delete(file):
	"""Deletes a file.

	file: string - file to delete

	Example:
		xbmcvfs.delete(file)"""
	try:
		os.remove(encode_fs(file))
		return True
	except:
		print("Can't remove %s" % file)
		return False
		
