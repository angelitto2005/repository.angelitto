# @package xbmcaddon
# A class to access addon properties.
#

import os, utils
import xml.etree.ElementTree as ET

# ------------------------------------------------------------------------------------------------------------------- #
class AddonRO(object):
	def __init__(self, id=None, xml_filename='settings.xml'):
		self._addon_xml 	= xml_filename
		self.load()


	def load(self):

		with open(self._addon_xml, 'r') as f:
			content = f.read()
			self.root = ET.fromstring(content)
		self.mtime = os.path.getmtime(self._addon_xml)

	# get setting no caching
	def getSetting(self, s):
		if not os.path.exists(self._addon_xml):
			return u''

		if self.mtime != os.path.getmtime(self._addon_xml):
			self.load()

		for item in self.root:
			if item.get('id') == s:
				return item.get('value').encode('utf-8')
		return u''


# ------------------------------------------------------------------------------------------------------------------- #
class Addon(AddonRO):
	def __init__(self, id=None):
		"""Creates a new Addon class.

		id: string - id of the addon (autodetected in XBMC Eden)

		Example:
			self.Addon = xbmcaddon.Addon(id='script.recentlyadded')
		"""
		# In CLI mode, xbmcswift2 must be run from the root of the addon
		# directory, so we can rely on getcwd() being correct.
		current = os.path.dirname(__file__)
		addonxml = os.path.join(current, '../addon.xml')
		self._info = {
			'id': id or utils.get_addon_id(addonxml),
			'name': utils.get_addon_name(addonxml),
		}
		self._strings = {}
		self._settings = {}
		
		AddonRO.__init__(self, id=id)
	
	
	def getAddonInfo(self, id):
		"""Returns the value of an addon property as a string.

		id: string - id of the property that the module needs to access.

		Note:
			Choices are (author, changelog, description, disclaimer, fanart, icon, id, name, path
			profile, stars, summary, type, version)

		Example:
			version = self.Addon.getAddonInfo('version')
		"""
		properties = ['author', 'changelog', 'description', 'disclaimer',
					  'fanart', 'icon', 'id', 'name', 'path', 'profile', 'stars', 'summary',
					  'type', 'version']
		assert id in properties, '%s is not a valid property.' % id
		return self._info.get(id, 'Unavailable')
