import json
import sqlite3 as database
from urllib.parse import urlencode, urlparse, parse_qsl
import xbmc, xbmcgui, xbmcplugin, xbmcvfs
from xbmcaddon import Addon

addon_object, window, execJSONRPC = Addon(), xbmcgui.Window(10000), xbmc.executeJSONRPC
player, xbmc_player, monitor, xbmc_monitor = xbmc.Player(), xbmc.Player, xbmc.Monitor(), xbmc.Monitor
dialog, progressDialog, progressDialogBG = xbmcgui.Dialog(), xbmcgui.DialogProgress(), xbmcgui.DialogProgressBG()
get_addoninfo, get_infolabel, get_visibility = addon_object.getAddonInfo, xbmc.getInfoLabel, xbmc.getCondVisibility

navigator_db   = 'special://profile/addon_data/plugin.video.pov/navigator.db'
watched_db     = 'special://profile/addon_data/plugin.video.pov/watched.db'
favorites_db   = 'special://profile/addon_data/plugin.video.pov/watched.db'
views_db       = 'special://profile/addon_data/plugin.video.pov/views.db'
trakt_db       = 'special://profile/addon_data/plugin.video.pov/traktcache.db'
mdbl_db        = 'special://profile/addon_data/plugin.video.pov/mdblcache.db'
maincache_db   = 'special://profile/addon_data/plugin.video.pov/maincache.db'
metacache_db   = 'special://profile/addon_data/plugin.video.pov/metacache.db'
debridcache_db = 'special://profile/addon_data/plugin.video.pov/debridcache.db'
external_db    = 'special://profile/addon_data/plugin.video.pov/providerscache.db'
scrapers_path  = 'special://home/addons/plugin.video.pov/resources/lib/scrapers/'
databases_path = 'special://profile/addon_data/plugin.video.pov/'
packages_path  = 'special://home/addons/packages/'
indicators_dict = {0: watched_db, 1: trakt_db, 2: mdbl_db}

def current_dbs():
	return {'settings.xml', 'fenomcache.db', 'traktcache.db', 'mdblcache.db', 'watched.db',
			'maincache.db', 'metacache.db', 'navigator.db', 'views.db', 'debridcache.db', 'providerscache.db'}

def logger(heading, function):
	xbmc.log('>> %s <<: %s' % (heading, function), 1)

def argv1():
	try: return __import__('sys').argv[1]
	except: return '-1'

def parsed_query(url):
	try: return dict(parse_qsl(urlparse(url).query))
	except: return dict()

def database_connect(file, **kwargs):
	return database.connect(translate_path(file), **kwargs)

def media_path(*args):
	path = 'special://home/addons/plugin.video.pov/resources/skins/Default/media/'
	return '%s%s' % (path, '/'.join(args)) if args else path

def get_property(prop):
	return window.getProperty(prop)

def set_property(prop, value):
	return window.setProperty(prop, value)

def clear_property(prop):
	return window.clearProperty(prop)

def addon(addon_id='plugin.video.pov'):
	return Addon(id=addon_id)

def addon_installed(addon_id):
	return get_visibility('System.AddonIsEnabled(%s)' % addon_id)

def add_item(handle, url, listitem, isFolder):
	xbmcplugin.addDirectoryItem(handle, url, listitem, isFolder)

def add_items(handle, item_list):
	xbmcplugin.addDirectoryItems(handle, item_list)

def set_content(handle, content):
	xbmcplugin.setContent(handle, content)

def set_category(handle, category):
	xbmcplugin.setPluginCategory(handle, category)

def set_sort_method(handle, method):
	if method == 'episodes': sort_method = xbmcplugin.SORT_METHOD_EPISODE
	elif method == 'files': sort_method = xbmcplugin.SORT_METHOD_FILE
	elif method == 'label': sort_method = xbmcplugin.SORT_METHOD_LABEL_IGNORE_THE#label
	else: sort_method = xbmcplugin.SORT_METHOD_UNSORTED
	xbmcplugin.addSortMethod(handle, sort_method)

def end_directory(handle, cacheToDisc=None):
	if cacheToDisc is None: cacheToDisc = get_property('pov_kodi_menu_cache') == 'true'
	xbmcplugin.endOfDirectory(handle, cacheToDisc=cacheToDisc)

def set_resolvedurl(handle, item):
	xbmcplugin.setResolvedUrl(handle, True, item)

def make_cast_list(cast=None):
	if not cast: return []
	return [xbmc.Actor(**actor) for actor in cast]

def make_playlist(_type='video'):
	return xbmc.PlayList(xbmc.PLAYLIST_VIDEO) if _type == 'video' else xbmc.PlayList(xbmc.PLAYLIST_MUSIC)

def convert_language(lang, format='long'):
	return xbmc.convertLanguage(lang, xbmc.ISO_639_2 if format == 'long' else xbmc.ISO_639_1)

def supported_media():
	return xbmc.getSupportedMedia('video')

def translate_path(path):
	return xbmcvfs.translatePath(path)

def path_exists(path):
	return xbmcvfs.exists(path)

def make_directory(path):
	xbmcvfs.mkdir(path)

def make_directorys(path):
	xbmcvfs.mkdirs(path)

def open_file(file, mode='r'):
	return xbmcvfs.File(file, mode)

def copy_file(source, destination):
	return xbmcvfs.copy(source, destination)

def delete_file(_file):
	xbmcvfs.delete(_file)

def rename_file(old, new):
	xbmcvfs.rename(old, new)

def list_dirs(location):
	return xbmcvfs.listdir(location)

def make_listitem():
	return xbmcgui.ListItem(offscreen=True)

def local_string(string):
	try: _string = int(string)
	except: return string
	try: _string = str(addon_object.getLocalizedString(_string))
	except: _string = addon_object.getLocalizedString(_string)
	return _string or string

def sleep(time):
	return xbmc.sleep(time)

def execute_builtin(command):
	return xbmc.executebuiltin(command)

def get_kodi_version():
	return int(get_infolabel('System.BuildVersion')[0:2])

def skin_location():
	return 'vop.oediv.nigulp/snodda/emoh//:laiceps'[::-1]

def current_skin():
	return xbmc.getSkinDir()

def current_window_id():
	return xbmcgui.Window(xbmcgui.getCurrentWindowId())

def get_video_database_path():
	version = {19: '119', 20: '121', 21: '131', 22: '146'}[get_kodi_version()]
	return 'special://profile/Database/MyVideos%s.db' % version

def show_busy_dialog():
	return execute_builtin('ActivateWindow(busydialognocancel)')

def hide_busy_dialog():
	execute_builtin('Dialog.Close(busydialognocancel)')
	execute_builtin('Dialog.Close(busydialog)')

def close_all_dialog():
	execute_builtin('Dialog.Close(all,true)')

def container_content():
	return get_infolabel('Container.Content')

def external_browse():
	return 'pov' not in get_infolabel('Container.PluginName')

def widget_refresh():
	return execute_builtin('UpdateLibrary(video,special://skin/foo)')

def container_refresh():
	return execute_builtin('Container.Refresh')

def ok_dialog(heading='POV', text='', highlight='dodgerblue', ok_label=local_string(32839), top_space=True):
	if isinstance(heading, int): heading = local_string(heading)
	if isinstance(text, int): text = local_string(text)
	if not text: top_space, text = True, local_string(32760)
	if top_space: text = '[CR]%s' % text
	return dialog.ok(heading, text)

def confirm_dialog(heading='POV', text='', highlight='dodgerblue', ok_label=local_string(32839), cancel_label=local_string(32840), top_space=True, default_control=11):
	if isinstance(heading, int): heading = local_string(heading)
	if isinstance(text, int): text = local_string(text)
	if isinstance(ok_label, int): ok_label = local_string(ok_label)
	if isinstance(cancel_label, int): cancel_label = local_string(cancel_label)
	if not text: text = '[CR]%s' % local_string(32580)
	elif top_space: text = '[CR]%s' % text
	return dialog.yesno(heading, text, cancel_label, ok_label)

def select_dialog(function_list, **kwargs):
	def _builder():
		for count, item in enumerate(items, 1):
			line1 = '%s. %s' % (count, item['line1']) if enum else item['line1']
			line2 = '[I]%s[/I]' % (item.get('line2') or item['line1'])
			listitem = make_listitem()
			listitem.setLabel(line1.upper())
			listitem.setLabel2(line2.upper())
			listitem.setArt({'icon': item.get('icon') or default_icon})
			yield listitem
	default_icon = '%s%s' % (get_addoninfo('path'), 'pov_poster.png')
	items = json.loads(kwargs.get('items') or '[]')
	heading = kwargs.get('heading') or get_addoninfo('name')
	enum = kwargs.get('enumerate', 'false') == 'true'
	details = kwargs.get('multi_line', 'true') == 'true'
	multi_choice = kwargs.get('multi_choice', 'false') == 'true'
	if multi_choice:
		preselect = kwargs.get('preselect') or []
		selection = dialog.multiselect(heading, list(_builder()), preselect=preselect, useDetails=details)
	else:
		preselect = kwargs.get('preselect') if kwargs.get('preselect') is not None else -1
		selection = dialog.select(heading, list(_builder()), preselect=preselect, useDetails=details)
	if isinstance(selection, list) and multi_choice: return [function_list[i] for i in selection]
	if selection in (-1, None): return None
	return function_list[selection]

def show_text(heading, text=None, file=None, font_size='small', kodi_log=False):
	if isinstance(heading, int): heading = local_string(heading)
	heading = heading.replace('[B]', '').replace('[/B]', '')
	if file:
		with open_file(file) as f: text = f.readBytes().decode('utf-8-sig')
	if kodi_log and confirm_dialog(
		text=local_string(32855),
		ok_label=local_string(32824),
		cancel_label=local_string(32828)
	):
		lines = []
		for line in text.splitlines(keepends=True):
			if line[0].isdigit(): lines += [line]
			else: lines[-1] += line
		text = ''.join(i for i in reversed(lines) if any(x in i.lower() for x in ('exception', 'error')))
	if not text: return notification(32760)
	return dialog.textviewer(heading, text)

def notification(line1, time=3000, icon=None, sound=False):
	if isinstance(line1, int): line1 = local_string(line1)
	icon = icon or get_addoninfo('icon')
	dialog.notification('POV', line1, icon, time, sound)

def choose_view(view_type, content):
	from sys import argv
	__handle__ = int(argv[1])
	label = local_string(32547)
	fanart = get_addoninfo('fanart')
	icon = media_path('settings.png')
	params_url = build_url({'mode': 'set_view', 'view_type': view_type})
	listitem = make_listitem()
	listitem.setLabel(label)
	listitem.setArt({'icon': icon, 'poster': icon, 'thumb': icon, 'fanart': fanart, 'banner': icon})
	add_item(__handle__, params_url, listitem, False)
	set_content(__handle__, content)
	end_directory(__handle__)
	set_view_mode(view_type, content)

def set_view(view_type):
	view_id = str(current_window_id().getFocusId())
	dbcon = database_connect(views_db, isolation_level=None)
	dbcur = dbcon.cursor()
	dbcur.execute("""PRAGMA synchronous = OFF""")
	dbcur.execute("""PRAGMA journal_mode = OFF""")
	dbcur.execute("""INSERT OR REPLACE INTO views VALUES (?, ?)""", (view_type, view_id))
	set_view_property(view_type, view_id)
	notification(get_infolabel('Container.Viewmode').upper(), 1500)

def set_view_property(view_type, view_id):
	set_property('pov_%s' % view_type, view_id)

def set_view_properties():
	dbcon = database_connect(views_db, isolation_level=None)
	dbcur = dbcon.cursor()
	dbcur.execute("""SELECT * FROM views""")
	view_ids = dbcur.fetchall()
	for item in view_ids: set_property('pov_%s' % item[0], item[1])

def set_view_mode(view_type, content='files', is_widget=None):
	if is_widget is True or (is_widget is None and external_browse()): return
	view_id = get_property('pov_%s' % view_type)
	if not view_id: return
	try:
		for _ in range(60):
			sleep(50)
			if container_content() != content: continue
			return execute_builtin('Container.SetViewMode(%s)' % view_id)
	except: pass

def clear_view(view_type):
	if not confirm_dialog(): return
	try:
		dbcon = database_connect(views_db, isolation_level=None)
		dbcur = dbcon.cursor()
		dbcur.execute("""PRAGMA synchronous = OFF""")
		dbcur.execute("""PRAGMA journal_mode = OFF""")
		dbcur.execute("""SELECT view_type FROM views""")
		for item in dbcur.fetchall(): clear_property('pov_%s' % item[0])
		dbcur.execute("""DELETE FROM views""")
		dbcur.execute("""VACUUM""")
		dbcon = database_connect('special://profile/Database/ViewModes6.db')
		dbcur = dbcon.cursor()
		dbcur.execute("""DELETE FROM view WHERE path LIKE 'plugin://plugin.video.pov/%'""")
		dbcon.commit()
		dbcon.close()
	except: return notification(32574, 1500)
	notification(32576, 1500)

def build_url(url_params):
	return f"{'/vop.oediv.nigulp//:nigulp'[::-1]}?{urlencode(url_params)}"

def add_dir(__handle__, url_params, list_name, iconImage=None, fanartImage=None, isFolder=True):
	if 'new_page' in url_params: list_name = f"{list_name} >> {url_params['new_page']} <<"
	fanart = fanartImage or get_addoninfo('fanart')
	icon = iconImage or media_path('item_next.png')
	url = build_url(url_params)
	listitem = make_listitem()
	listitem.setLabel(list_name)
	listitem.setArt({'icon': icon, 'poster': icon, 'thumb': icon, 'fanart': fanart, 'banner': icon})
	add_item(__handle__, url, listitem, isFolder)

def remove_meta_keys(dict_item, dict_removals):
	for k in dict_removals: dict_item.pop(k, None)
	return dict_item

def volume_checker(volume_setting=None):
	try: # 0% == -60db, 100% == 0db
		if get_visibility('Player.Muted'): return
		from modules.utils import string_alphanum_to_num
		if not volume_setting: volume_setting = get_setting('volumecheck.percent', '100')
		max_volume = int(min(int(volume_setting), 100))
		current_volume_db = int(string_alphanum_to_num(get_infolabel('Player.Volume').split('.')[0]))
		current_volume_percent = int(100 - ((float(current_volume_db)/60)*100))
		if current_volume_percent > max_volume: execute_builtin('SetVolume(%d)' % int(max_volume))
	except: pass

def focus_index(index, sleep_time=100):
	sleep(sleep_time)
	current_window = current_window_id()
	focus_id = current_window.getFocusId()
	try: current_window.getControl(focus_id).selectItem(index)
	except: pass

def clean_settings_window_properties():
	clear_property('pov_settings')
	notification(32576, 1500)

def fetch_kodi_imagecache(image):
	result = None
	try:
		dbcon = database_connect('special://profile/Database/Textures13.db')
		dbcur = dbcon.cursor()
		dbcur.execute("""SELECT cachedurl FROM texture WHERE url = ?""", (image,))
		result = dbcur.fetchone()[0]
	except: pass
	return result

class SettingsManager:
	def __init__(self):
		self._cache = {}
		self._last_raw_string = None

	def _sync(self):
		current_raw = get_property('pov_settings')
		if current_raw == self._last_raw_string: return
		try: self._cache = json.loads(current_raw)
		except Exception: self._cache = make_settings_dict()
		self._last_raw_string = current_raw

	def get(self, key, fallback=None):
		self._sync()
		value = self._cache.get(key, '')
		if value == '' and fallback is not None: return fallback
		return value

manager = SettingsManager()

def get_setting(setting_id, fallback=None):
	try: value = manager.get(setting_id, fallback)
	except: value = Addon().getSetting(setting_id)
	return value

def set_setting(setting_id, value):
	Addon().setSetting(setting_id, value)

def make_settings_dict():
	import xml.etree.ElementTree as ET
	settings_dict = None
	setting = Addon().getSetting
	try:
		default_xml = 'special://home/addons/plugin.video.pov/resources/settings.xml'
		with open_file(default_xml) as xml_file: root = ET.fromstring(xml_file.read())
		settings_dict = {i: setting(i) for item in root.iter('setting') if (i := item.get('id'))}
		set_property('pov_settings', json.dumps(settings_dict))
	except Exception as e: logger('make_settings_dict error', str(e))
	return settings_dict

def clean_settings(silent=False):
	import xml.etree.ElementTree as ET
	addon_ids = 'plugin.video.pov'
	default_xml = 'special://home/addons/%s/resources/settings.xml' % addon_ids
	profile_xml = 'special://profile/addon_data/%s/settings.xml' % addon_ids
	try:
		removed_settings = []
		removed_append = removed_settings.append
		with open_file(default_xml) as xml_file: root = ET.fromstring(xml_file.read())
		active_settings = [item.get('id') for item in root.iter('setting') if item.get('id')]
		with open_file(profile_xml) as xml_file: root = ET.fromstring(xml_file.read())
		for item in root.iter('setting'):
			if item.get('id') in active_settings: continue
			removed_append(item)
		for item in removed_settings: root.remove(item)
		with open_file(profile_xml, 'w') as xml_file: xml_file.write(ET.tostring(root))
		text = local_string(32813) % len(removed_settings) if removed_settings else 32576
		if not silent: notification(text, 1500)
	except:
		if not silent: notification(32574, 1500)

def open_settings(query, addon='plugin.video.pov'):
	hide_busy_dialog()
	execute_builtin('Addon.OpenSettings(%s)' % addon)
	if not query: return
	try:
		if get_kodi_version() < 20: button, control = 100, 80
		else: button, control = 200, 180
		menu, function = query.split('.')
		execute_builtin('SetFocus(%i)' % (int(menu) - button))
		execute_builtin('SetFocus(%i)' % (int(function) - control))
	except: notification(32574)

def toggle_language_invoker():
	import xml.etree.ElementTree as ET
	close_all_dialog()
	sleep(100)
	current_addon_setting = get_setting('reuse_language_invoker', 'true')
	new_value = 'false' if current_addon_setting == 'true' else 'true'
	if not confirm_dialog(text=local_string(32979) % (current_addon_setting.upper(), new_value.upper())): return
	if new_value == 'true' and not confirm_dialog(text=32980): return
	addon_xml = translate_path('special://home/addons/plugin.video.pov/addon.xml')
	tree = ET.parse(addon_xml)
	root = tree.getroot()
	item = next(root.iter('reuselanguageinvoker'), None)
	if item is None: return notification(32574, 1500)
	item.text = new_value
	tree.write(addon_xml)
	set_setting('reuse_language_invoker', new_value)
	ok_dialog(text=32981)
	execute_builtin('LoadProfile(%s)' % get_infolabel('system.profilename'))

def upload_logfile():
	# Thanks 123Venom
	log_file, url = 'special://logpath/kodi.log', 'https://paste.kodi.tv/'
	if not path_exists(log_file): return ok_dialog(text='Error. Log File Not Found.')
	from platform import python_version
	text = f"Kodi: {get_infolabel('System.BuildVersion')}[CR]Python: {python_version()}[CR]{local_string(32580)}"
	if not confirm_dialog(text=text, top_space=False): return
	show_busy_dialog()
	import requests
	try:
		with open_file(log_file) as f: text = f.readBytes().decode('utf-8-sig')
		response = requests.post('%s%s' % (url, 'documents'), data=text, timeout=10.0).json()
		if 'key' in response: ok_dialog(text=url + response['key'])
		else: ok_dialog(text='Error. Log Upload Failed')
	except: notification(32574, 1500)
	hide_busy_dialog()

def timeIt(func):
	# Thanks to 123Venom
	import time
	fnc_name = func.__name__
	def wrap(*args, **kwargs):
		started_at = time.perf_counter()
		result = func(*args, **kwargs)
		logger('%s.%s' % (__name__ , fnc_name), (time.perf_counter() - started_at))
		return result
	return wrap

