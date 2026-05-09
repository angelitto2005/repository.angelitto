"""
	Fenomscrapers Module
"""

from magneto.modules.control import addonPath, addonVersion, joinPath
from magneto.modules.textviewer import TextViewerXML


def get(file):
	magneto_path = addonPath()
	magneto_version = addonVersion()
	helpFile = joinPath(magneto_path, 'resources', 'help', file + '.txt')
	r = open(helpFile, 'r', encoding='utf-8', errors='ignore')
	text = r.read()
	r.close()
	heading = '[B]Magneto -  v%s - %s[/B]' % (magneto_version, file)
	windows = TextViewerXML('textviewer.xml', magneto_path, heading=heading, text=text)
	windows.run()
	del windows
