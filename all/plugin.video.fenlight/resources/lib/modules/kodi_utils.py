# -*- coding: utf-8 -*-
# TRUMP WON
import xbmc, xbmcgui, xbmcplugin, xbmcvfs, xbmcaddon
import os
from urllib.parse import urlencode, unquote

def random_valid_type_check():
	return {'build_movie_list': 'movie', 'build_tvshow_list': 'tvshow', 'build_season_list': 'season', 'build_episode_list': 'episode',
	'build_in_progress_episode': 'single_episode', 'build_recently_watched_episode': 'single_episode', 'build_next_episode': 'single_episode',
	'build_my_calendar': 'single_episode', 'build_trakt_lists': 'trakt_list',
	'trakt.list.build_trakt_list': 'trakt_list', 'build_trakt_lists_contents': 'trakt_list', 'personal_lists.build_personal_list': 'personal_list',
	'build_personal_lists_contents': 'personal_list', 'tmdblist.build_tmdb_list': 'tmdb_list', 'build_tmdb_lists_contents': 'tmdb_list'}

def random_episodes_check():
	return {'build_in_progress_episode': 'episode.progress', 'build_recently_watched_episode': 'episode.recently_watched',
	'build_next_episode': 'episode.next', 'build_my_calendar': 'episode.trakt'}

def extras_button_label_values():
	return {'movie':
				{'movies_play': 'Playback', 'show_trailers': 'Trailer', 'show_images': 'Images',  'show_extrainfo': 'Extra Info', 'show_genres': 'Genres',
				'show_director': 'Director', 'show_options': 'Options', 'show_recommended': 'Recommended', 'show_more_like_this': 'More Like This',
				'show_trakt_manager': 'Trakt Lists', 'show_personallists_manager': 'Personal Lists', 'show_tmdb_manager': 'TMDb Lists', 'show_favorites_manager': 'Favorites Lists',
				'playback_choice': 'Playback Options', 'show_plot': 'Plot', 'show_keywords': 'Keywords', 'show_in_trakt_lists': 'In Trakt Lists', 'close_all': 'Close All Dialogs'},
			'tvshow':
				{'tvshow_browse': 'Browse', 'show_trailers': 'Trailer', 'show_images': 'Images', 'show_extrainfo': 'Extra Info', 'show_genres': 'Genres',
				'play_nextep': 'Play Next', 'show_options': 'Options', 'show_recommended': 'Recommended', 'show_more_like_this': 'More Like This',
				'show_trakt_manager': 'Trakt Lists', 'show_personallists_manager': 'Personal Lists', 'show_tmdb_manager': 'TMDb Lists', 'show_favorites_manager': 'Favorites Lists',
				'play_random_episode': 'Play Random', 'show_plot': 'Plot', 'show_keywords': 'Keywords', 'show_in_trakt_lists': 'In Trakt Lists', 'close_all': 'Close All Dialogs'}}

def context_menu_items():
	return {'extras': 'Extras', 'options': 'Options', 'playback_options': 'Playback Options', 'browse_movie_set': 'Browse Movie Set', 'browse_seasons': 'Browse TV Seasons',
			'browse_episodes': 'Browse Season Episodes', 'recommended': 'Browse Recommended', 'more_like_this': 'Browse More Like This', 'similar': 'Browse Similar',
			'in_trakt_list': 'In Trakt Lists', 'trakt_manager':'Trakt Lists Manager', 'personal_manager': 'Personal Lists Manager', 'tmdb_manager': 'TMDb Lists Manager',
			'favorites_manager': 'Favorites Manager', 'mark_watched': 'Mark Watched/Unwatched', 'unmark_previous_episode': 'Unmark Previous Watched Episode',
			'exit': 'Exit List', 'refresh': 'Refresh Widgets', 'reload': 'Reload Widgets'}

def video_extensions():
	return ('m4v', '3g2', '3gp', 'nsv', 'tp', 'ts', 'ty', 'pls', 'rm', 'rmvb', 'mpd', 'ifo', 'mov', 'qt', 'divx', 'xvid', 'bivx', 'vob', 'nrg', 'img', 'iso', 'udf', 'pva',
			'wmv', 'asf', 'asx', 'ogm', 'm2v', 'avi', 'bin', 'dat', 'mpg', 'mpeg', 'mp4', 'mkv', 'mk3d', 'avc', 'vp3', 'svq3', 'nuv', 'viv', 'dv', 'fli', 'flv', 'wpl',
			'xspf', 'vdr', 'dvr-ms', 'xsp', 'mts', 'm2t', 'm2ts', 'evo', 'ogv', 'sdp', 'avs', 'rec', 'url', 'pxml', 'vc1', 'h264', 'rcv', 'rss', 'mpls', 'mpl', 'webm',
			'bdmv', 'bdm', 'wtv', 'trp', 'f4v', 'pvr', 'disc')

def image_extensions():
	return ('jpg', 'jpeg', 'jpe', 'jif', 'jfif', 'jfi', 'bmp', 'dib', 'png', 'gif', 'webp', 'tiff', 'tif',
			'psd', 'raw', 'arw', 'cr2', 'nrw', 'k25', 'jp2', 'j2k', 'jpf', 'jpx', 'jpm', 'mj2')

def kodi_progress_background():
	return xbmcgui.DialogProgressBG()

def get_visibility(obj):
	return xbmc.getCondVisibility(obj)

def get_infolabel(label):
	return xbmc.getInfoLabel(label)

def kodi_actor():
	return xbmc.Actor

def translate_path(_path):
	return xbmcvfs.translatePath(_path)

def kodi_monitor():
	return xbmc.Monitor()

def kodi_player():
	return xbmc.Player()

def kodi_dialog():
	return xbmcgui.Dialog()

def addon_info(info):
	return xbmcaddon.Addon('plugin.video.fenlight').getAddonInfo(info)

def addon_version():
	return get_property('fenlight.addon_version') or addon_info('version')

def addon_path():
	return get_property('fenlight.addon_path') or addon_info('path')

def addon_profile():
	return get_property('fenlight.addon_profile') or translate_path(addon_info('profile'))

def addon_icon():
	return get_property('fenlight.addon_icon') or translate_path(addon_info('icon'))

def addon_icon_mini():
	return get_property('fenlight.addon_icon_mini') or os.path.join(addon_info('path'), 'resources', 'media', 'addon_icons', 'minis',
														os.path.basename(translate_path(addon_info('icon'))))

def addon_fanart():
	return get_property('fenlight.addon_fanart') or translate_path(addon_info('fanart'))

def get_icon(image_name, image_folder='icons'):
	return translate_path('special://home/addons/plugin.video.fenlight/resources/media/%s/%s.png' % (image_folder, image_name))

def get_addon_fanart():
	return get_property('fenlight.default_addon_fanart') or addon_fanart()

def build_url(url_params):
	return 'plugin://plugin.video.fenlight/?%s' % urlencode(url_params)

def add_dir(handle, url_params, list_name, icon_image='folder', fanart_image=None, isFolder=True):
	fanart = fanart_image or get_addon_fanart()
	icon = get_icon(icon_image)
	url = build_url(url_params)
	listitem = make_listitem()
	listitem.setLabel(list_name)
	listitem.setArt({'icon': icon, 'poster': icon, 'thumb': icon, 'fanart': fanart, 'banner': fanart})
	info_tag = listitem.getVideoInfoTag(True)
	info_tag.setPlot(' ')
	add_item(handle, url, listitem, isFolder)

def make_listitem():
	return xbmcgui.ListItem(offscreen=True)

def add_item(handle, url, listitem, isFolder):
	xbmcplugin.addDirectoryItem(handle, url, listitem, isFolder)

def add_items(handle, item_list):
	xbmcplugin.addDirectoryItems(handle, item_list)

def set_content(handle, content):
	xbmcplugin.setContent(handle, content)

def set_category(handle, label):
	xbmcplugin.setPluginCategory(handle, label)

def end_directory(handle, cacheToDisc=True):
	xbmcplugin.endOfDirectory(handle, cacheToDisc=cacheToDisc)

def set_view_mode(view_type, content='files', is_external=None):
	if not get_property('fenlight.use_viewtypes') == 'true': return
	if is_external == None: is_external = external()
	if is_external: return
	view_id = get_property('fenlight.%s' % view_type) or None
	if not view_id: return
	try:
		hold = 0
		sleep(100)
		while not container_content() == content:
			hold += 1
			if hold < 3000: sleep(1)
			else: return
		execute_builtin('Container.SetViewMode(%s)' % view_id)
	except: return

def random_integer(start=1, end=1000000):
	from random import randint
	return randint(start, end)

def remove_keys(dict_item, dict_removals):
	for k in dict_removals: dict_item.pop(k, None)
	return dict_item

def append_path(_path):
	import sys
	sys.path.append(translate_path(_path))

def logger(heading, function):
	xbmc.log('###%s###: %s' % (heading, function), 1)

def kodi_window():
	return xbmcgui.Window(10000)

def get_property(prop):
	return kodi_window().getProperty(prop)

def set_property(prop, value):
	return kodi_window().setProperty(prop, value)

def clear_property(prop):
	return kodi_window().clearProperty(prop)

def clear_all_properties():
	return kodi_window().clearProperties()

def addon(addon_id='plugin.video.fenlight'):
	return xbmcaddon.Addon(id=addon_id)

def addon_installed(addon_id):
	return get_visibility('System.HasAddon(%s)' % addon_id)

def addon_enabled(addon_id):
	return get_visibility('System.AddonIsEnabled(%s)' % addon_id)

def container_content():
	return get_infolabel('Container.Content')

def set_sort_method(handle, method):
	xbmcplugin.addSortMethod(handle, {'episodes': 24, 'files': 5, 'label': 2, 'none': 0}[method])

def make_session(url='https://'):
	import requests
	session = requests.Session()
	session.mount(url, requests.adapters.HTTPAdapter(pool_maxsize=100))
	return session	

def make_playlist(playlist_type='video'):
	return xbmc.PlayList({'music': 0, 'video': 1}[playlist_type])

def supported_media():
	return xbmc.getSupportedMedia('video')

def path_exists(path):
	return xbmcvfs.exists(path)

def open_file(_file, mode='r'):
	return xbmcvfs.File(_file, mode)

def copy_file(source, destination):
	return xbmcvfs.copy(source, destination)

def delete_file(_file):
	xbmcvfs.delete(_file)

def delete_folder(_folder, force=False):
	xbmcvfs.rmdir(_folder, force)

def rename_file(old, new):
	xbmcvfs.rename(old, new)

def list_dirs(location):
	return xbmcvfs.listdir(location)

def make_directory(path):
	xbmcvfs.mkdir(path)

def make_directories(path):
	xbmcvfs.mkdirs(path)

def sleep(time):
	return xbmc.sleep(time)

def execute_builtin(command, block=False):
	return xbmc.executebuiltin(command, block)

def current_skin():
	return xbmc.getSkinDir()

def get_window_id():
	return xbmcgui.getCurrentWindowId()

def current_window_object():
	return xbmcgui.Window(get_window_id())

def kodi_version():
	return int(get_infolabel('System.BuildVersion')[0:2])

def get_video_database_path():
	return translate_path('special://profile/Database/MyVideos%s.db' % {19: '119', 20: '121', 21: '124'}[kodi_version()])

def show_busy_dialog():
	return execute_builtin('ActivateWindow(busydialognocancel)')

def hide_busy_dialog():
	execute_builtin('Dialog.Close(busydialognocancel)')
	execute_builtin('Dialog.Close(busydialog)')

def close_dialog(dialog, block=False):
	execute_builtin('Dialog.Close(%s,true)' % dialog, block)

def close_all_dialog():
	execute_builtin('Dialog.Close(all,true)')

def run_addon(addon='plugin.video.fenlight', block=False):
	return execute_builtin('RunAddon(%s)' % addon, block)

def external():
	return 'fenlight' not in get_infolabel('Container.PluginName')

def home():
	return xbmcgui.getCurrentWindowId() == 10000

def folder_path():
	return get_infolabel('Container.FolderPath')

def path_check(string):
	return string in unquote(folder_path())

def reload_skin():
	execute_builtin('ReloadSkin()')

def kodi_refresh():
	execute_builtin('UpdateLibrary(video,special://skin/foo)')

def run_plugin(params, block=False):
	if isinstance(params, dict): params = build_url(params)
	return execute_builtin('RunPlugin(%s)' % params, block)

def container_update(params, block=False):
	if isinstance(params, dict): params = build_url(params)
	return execute_builtin('Container.Update(%s)' % params, block)

def activate_window(params, block=False):
	if isinstance(params, dict): params = build_url(params)
	return execute_builtin('ActivateWindow(Videos,%s,return)' % params, block)

def container_refresh():
	return execute_builtin('Container.Refresh')

def container_refresh_input(params, block=False):
	if isinstance(params, dict): params = build_url(params)
	return execute_builtin('Container.Refresh(%s)' % params, block)

def replace_window(params, block=False):
	if isinstance(params, dict): params = build_url(params)
	return execute_builtin('ReplaceWindow(Videos,%s)' % params, block)

def disable_enable_addon(addon_name='plugin.video.fenlight'):
	import json
	try:
		xbmc.executeJSONRPC(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'Addons.SetAddonEnabled', 'params': {'addonid': addon_name, 'enabled': False}}))
		xbmc.executeJSONRPC(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'Addons.SetAddonEnabled', 'params': {'addonid': addon_name, 'enabled': True}}))
	except: pass

def update_local_addons():
	execute_builtin('UpdateLocalAddons', True)
	sleep(2500)
 
def update_kodi_addons_db(addon_name='plugin.video.fenlight'):
	import time
	import sqlite3 as database
	try:
		date = time.strftime('%Y-%m-%d %H:%M:%S')
		dbcon = database.connect(translate_path('special://database/Addons33.db'), timeout=40.0)
		dbcon.execute("INSERT OR REPLACE INTO installed (addonID, enabled, lastUpdated) VALUES (?, ?, ?)", (addon_name, 1, date))
		dbcon.close()
	except: pass

def get_jsonrpc(request):
	import json
	response = xbmc.executeJSONRPC(json.dumps(request))
	result = json.loads(response)
	return result.get('result', None)

def jsonrpc_get_directory(directory, properties=['title', 'file', 'thumbnail']):
	command = {'jsonrpc': '2.0', 'id': 1, 'method': 'Files.GetDirectory', 'params': {'directory': directory, 'media': 'files', 'properties': properties}}
	try:
		files = get_jsonrpc(command).get('files')
		results = [i for i in files if i['file'].startswith('plugin://') and i['filetype'] == 'directory']
	except: results = None
	return results

def jsonrpc_get_addons(_type, properties=['thumbnail', 'name']):
	command = {'jsonrpc': '2.0', 'method': 'Addons.GetAddons','params':{'type':_type, 'properties': properties}, 'id': '1'}
	results = get_jsonrpc(command).get('addons')
	return results

def jsonrpc_get_system_setting(setting_id, setting_value=''):
	command = {'jsonrpc': '2.0', 'id': 1, 'method': 'Settings.GetSettingValue', 'params': {'setting': setting_id}}
	try: result = get_jsonrpc(command)['value']
	except: result = setting_value
	return result

def open_settings():
	from windows.base_window import open_window
	open_window(('windows.settings_manager', 'SettingsManager'), 'settings_manager.xml')

def external_scraper_settings():
	try:
		external = get_property('fenlight.external_scraper.module')
		if external in ('empty_setting', ''): return
		execute_builtin('Addon.OpenSettings(%s)' % external)
	except: pass

def progress_dialog(heading='', icon=None):
	from threading import Thread
	from windows.base_window import create_window
	progress_dialog = create_window(('windows.progress', 'Progress'), 'progress.xml', heading=heading, icon=icon or addon_icon())
	Thread(target=progress_dialog.run).start()
	return progress_dialog

def select_dialog(function_list, **kwargs):
	from windows.base_window import open_window
	selection = open_window(('windows.default_dialogs', 'Select'), 'select.xml', **kwargs)
	if selection in (None, []): return selection
	if kwargs.get('multi_choice', 'false') == 'true': return [function_list[i] for i in selection]
	return function_list[selection]

def confirm_dialog(heading='', text='Are you sure?', ok_label='OK', cancel_label='Cancel', default_control=11):
	from windows.base_window import open_window
	kwargs = {'heading': heading, 'text': text, 'ok_label': ok_label, 'cancel_label': cancel_label, 'default_control': default_control}
	return open_window(('windows.default_dialogs', 'Confirm'), 'confirm.xml', **kwargs)

def ok_dialog(heading='', text='No Results', ok_label='OK'):
	from windows.base_window import open_window
	kwargs = {'heading': heading, 'text': text, 'ok_label': ok_label}
	return open_window(('windows.default_dialogs', 'OK'), 'ok.xml', **kwargs)

def show_text(heading, text=None, file=None, font_size='small', kodi_log=False):
	from windows.base_window import open_window
	heading = heading.replace('[B]', '').replace('[/B]', '')
	if file:
		with open(file, encoding='utf-8') as r: text = r.readlines()
	if kodi_log:
		confirm = confirm_dialog(text='Show Log Errors Only?', ok_label='Yes', cancel_label='No')
		if confirm == None: return
		if confirm: text = [i for i in text if any(x in i.lower() for x in ('exception', 'error', '[test]'))]
	text = ''.join(text)
	return open_window(('windows.textviewer', 'TextViewer'), 'textviewer.xml', heading=heading, text=text, font_size=font_size)

def notification(line1, time=5000, icon=None):
	kodi_dialog().notification('Fen Light', line1, icon or addon_icon(), time)

def external_playback_check(params):
	from modules.settings import playback_key
	if not playback_key() in params:
		ok_dialog('External Playback Detected', 'Playback through external addons is not supported.[CR]')
		return False
	return True

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

def volume_checker():
	# 0% == -60db, 100% == 0db
	try:
		if get_property('fenlight.playback.volumecheck_enabled') == 'false' or get_visibility('Player.Muted'): return
		from modules.utils import string_alphanum_to_num
		max_volume = min(int(get_property('fenlight.playback.volumecheck_percent') or '50'), 100)
		if int(100 - (float(string_alphanum_to_num(get_infolabel('Player.Volume').split('.')[0]))/60)*100) > max_volume: execute_builtin('SetVolume(%d)' % max_volume)
	except: pass

def focus_index(index):
	current_window = current_window_object()
	focus_id = current_window.getFocusId()
	try: current_window.getControl(focus_id).selectItem(index)
	except: pass

def get_all_icon_vars():
	icon_items = list_dirs(translate_path('special://home/addons/plugin.video.fenlight/resources/media/icons'))[1]
	icon_items = [i.replace('.png', '') for i in icon_items]
	return icon_items

def upload_logfile(params):
	import json
	import requests
	from modules.utils import copy2clip, make_qrcode
	log_files = [('Current Kodi Log', 'kodi.log'), ('Previous Kodi Log', 'kodi.old.log')]
	list_items = [{'line1': i[0]} for i in log_files]
	kwargs = {'items': json.dumps(list_items), 'heading': 'Choose Which Log File to Upload', 'narrow_window': 'true'}
	log_file = select_dialog(log_files, **kwargs)
	if log_file == None: return
	log_name, log_file = log_file
	if not confirm_dialog(heading=log_name): return
	show_busy_dialog()
	url = 'https://paste.kodi.tv/'
	log_file = translate_path('special://logpath/%s' % log_file)
	if not path_exists(log_file): return ok_dialog(text='Error. Log Upload Failed')
	try:
		with open_file(log_file) as f: text = f.read()
		UserAgent = 'script.kodi.loguploader: 1.0'
		response = requests.post('%s%s' % (url, 'documents'), data=text.encode('utf-8', errors='ignore'), headers={'User-Agent': UserAgent}).json()
		if 'key' in response:
			user_code = response['key']
			url = '%s%s' % (url, user_code)
			copy2clip(url)
			qr_code = make_qrcode(url) or ''
			progressDialog = progress_dialog(heading='Kodi Log Uploader', icon=qr_code)
			count, success = 20, None
			while not progressDialog.iscanceled() and count >= 0 and success == None:
				try:
					count -= 1
					progressDialog.update('Share or Access with this url: [B]%s[/B][CR]Or Access using this QR Code' % url, count)
					sleep(2500)
				except: success = False
		else: ok_dialog(text='Error. Log Upload Failed')
	except: ok_dialog(text='Error. Log Upload Failed')
	hide_busy_dialog()

def fetch_kodi_imagecache(image):
	import sqlite3 as database
	result = None
	try:
		dbcon = database.connect(translate_path('special://database/Textures13.db'), timeout=40.0)
		dbcur = dbcon.cursor()
		dbcur.execute("SELECT cachedurl FROM texture WHERE url = ?", (image,))
		result = dbcur.fetchone()[0]
	except: pass
	return result
