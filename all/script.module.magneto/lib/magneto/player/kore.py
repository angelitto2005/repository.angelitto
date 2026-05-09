import sys
import json
import _strptime
from urllib.parse import urlencode
import xbmc, xbmcgui, xbmcplugin, xbmcvfs, xbmcaddon

player, xbmc_player, xbmc_monitor, translatePath, xbmc_actor = xbmc.Player(), xbmc.Player, xbmc.Monitor, xbmcvfs.translatePath, xbmc.Actor
ListItem, getSkinDir, log, getCurrentWindowId, Window = xbmcgui.ListItem, xbmc.getSkinDir, xbmc.log, xbmcgui.getCurrentWindowId, xbmcgui.Window
File, exists, copy, delete, rmdir, rename = xbmcvfs.File, xbmcvfs.exists, xbmcvfs.copy, xbmcvfs.delete, xbmcvfs.rmdir, xbmcvfs.rename
get_infolabel, get_visibility, execute_JSON, window_xml_dialog = xbmc.getInfoLabel, xbmc.getCondVisibility, xbmc.executeJSONRPC, xbmcgui.WindowXMLDialog
executebuiltin, xbmc_sleep, convertLanguage, getSupportedMedia, PlayList = xbmc.executebuiltin, xbmc.sleep, xbmc.convertLanguage, xbmc.getSupportedMedia, xbmc.PlayList
monitor, window, dialog, progressDialog, progressDialogBG = xbmc_monitor(), Window(10000), xbmcgui.Dialog(), xbmcgui.DialogProgress(), xbmcgui.DialogProgressBG()
endOfDirectory, addSortMethod, listdir, mkdir, mkdirs = xbmcplugin.endOfDirectory, xbmcplugin.addSortMethod, xbmcvfs.listdir, xbmcvfs.mkdir, xbmcvfs.mkdirs
addDirectoryItem, addDirectoryItems, setContent, setCategory = xbmcplugin.addDirectoryItem, xbmcplugin.addDirectoryItems, xbmcplugin.setContent, xbmcplugin.setPluginCategory
window_xml_left_action, window_xml_right_action, window_xml_up_action, window_xml_down_action, window_xml_info_action = 1, 2, 3, 4, 11
window_xml_selection_actions, window_xml_closing_actions, window_xml_context_actions = (7, 100), (9, 10, 13, 92), (101, 108, 117)
addon_object = xbmcaddon.Addon()
addon_info = addon_object.getAddonInfo
addon_path = addon_info('path')
addon_icon = translatePath(addon_info('icon'))
userdata_path = translatePath(addon_info('profile'))
default_addon_fanart = translatePath(addon_info('fanart'))
empty_poster = addon_icon
int_window_prop = 'magneto.internal_results.%s'
myvideos_db_paths = {19: '119', 20: '121', 21: '131'}
sort_method_dict = {'episodes': 24, 'files': 5, 'label': 2}
playlist_type_dict = {'music': 0, 'video': 1}

def get_setting(setting_id, fallback=None):
	setting = xbmcaddon.Addon().getSetting(setting_id)
	if not fallback is None and not setting: setting = fallback
	return setting

def set_setting(setting_id, value):
	addon_object.setSetting(setting_id, value)

def get_icon(image_name):
	skin_path = 'special://home/addons/script.module.magneto/resources/skins/Default/media/%s.png'
	return skin_path % image_name

def get_addon_fanart():
	return get_property('magneto.addon_fanart') or default_addon_fanart

def build_url(url_params):
	return 'plugin://script.module.magneto/?%s' % urlencode(url_params)

def add_dir(url_params, list_name, handle, iconImage='folder', fanartImage=None, isFolder=True):
	fanart = fanartImage or get_addon_fanart()
	icon = get_icon(iconImage)
	url = build_url(url_params)
	listitem = make_listitem()
	listitem.setLabel(list_name)
	listitem.setArt({'icon': icon, 'poster': icon, 'thumb': icon, 'fanart': fanart, 'banner': fanart})
	info_tag = listitem.getVideoInfoTag(offscreen=True)
	info_tag.setPlot(' ')
	add_item(handle, url, listitem, isFolder)

def make_listitem():
	return ListItem(offscreen=True)

def add_item(handle, url, listitem, isFolder):
	addDirectoryItem(handle, url, listitem, isFolder)

def add_items(handle, item_list):
	addDirectoryItems(handle, item_list)

def set_content(handle, content):
	setContent(handle, content)

def set_category(handle, label):
	setCategory(handle, label)

def end_directory(handle, cacheToDisc=True):
	endOfDirectory(handle, cacheToDisc=cacheToDisc)

def remove_keys(dict_item, dict_removals):
	for k in dict_removals: dict_item.pop(k, None)
	return dict_item

def append_path(_path):
	sys.path.append(translatePath(_path))

def logger(heading, function):
	log('🧲 %s 🧲: %s' % (heading, function), 1)

def get_property(prop):
	return window.getProperty(prop)

def set_property(prop, value):
	return window.setProperty(prop, value)

def clear_property(prop):
	return window.clearProperty(prop)

def addon(addon_id='script.module.magneto'):
	return xbmcaddon.Addon(id=addon_id)

def addon_installed(addon_id):
	return get_visibility('System.HasAddon(%s)' % addon_id)

def addon_enabled(addon_id):
	return get_visibility('System.AddonIsEnabled(%s)' % addon_id)

def container_content():
	return get_infolabel('Container.Content')

def set_sort_method(handle, method):
	addSortMethod(handle, sort_method_dict[method])

def make_playlist(playlist_type='video'):
	return PlayList(playlist_type_dict[playlist_type])

def convert_language(lang):
	return convertLanguage(lang, 1)

def supported_media():
	return getSupportedMedia('video')

def path_exists(path):
	return exists(path)

def open_file(_file, mode='r'):
	return File(_file, mode)

def copy_file(source, destination):
	return copy(source, destination)

def delete_file(_file):
	delete(_file)

def delete_folder(_folder, force=False):
	rmdir(_folder, force)

def rename_file(old, new):
	rename(old, new)

def list_dirs(location):
	return listdir(location)

def make_directory(path):
	mkdir(path)

def make_directories(path):
	mkdirs(path)

def translate_path(path):
	return translatePath(path)

def sleep(time):
	return xbmc_sleep(time)

def execute_builtin(command, block=False):
	return executebuiltin(command, block)

def current_skin():
	return getSkinDir()

def kodi_version():
	return int(get_infolabel('System.BuildVersion')[0:2])

def show_busy_dialog():
	return execute_builtin('ActivateWindow(busydialognocancel)')

def hide_busy_dialog():
	execute_builtin('Dialog.Close(busydialognocancel)')
	execute_builtin('Dialog.Close(busydialog)')

def close_dialog(dialog, block=False):
	execute_builtin('Dialog.Close(%s,true)' % dialog, block)

def close_all_dialog():
	execute_builtin('Dialog.Close(all,true)')

def select_dialog(function_list, **kwargs):
	items = json.loads(kwargs.pop('items'))
	heading = kwargs.pop('heading') or addon_info('name')
	select = dialog.multiselect if kwargs.pop('multi_choice', False) == 'true' else dialog.select
	selection = select(heading, [i['line1'] for i in items], **kwargs)
	if selection is None: return
	if isinstance(selection, int) and selection < 0: return
	if isinstance(selection, list): return [function_list[i] for i in selection]
	return function_list[selection]

def notification(line1, time=5000, icon=None):
	icon = icon or addon_icon
	dialog.notification(addon_info('name'), line1, icon, time)

def timeIt(func):
	# Thanks to 123Venom
	import time
	fnc_name = func.__name__
	def wrap(*args, **kwargs):
		started_at = time.time()
		result = func(*args, **kwargs)
		logger('%s.%s' % (__name__ , fnc_name), (time.time() - started_at))
		return result
	return wrap

def manual_function_import(location, function_name):
	from importlib import import_module
	return getattr(import_module(location), function_name)
