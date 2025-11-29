# -*- coding: utf-8 -*-
# Thanks to kodifitzwell for allowing me to borrow his code
import sys
from apis.offcloud_api import Offcloud
from modules import kodi_utils
from modules.source_utils import supported_video_extensions
from modules.utils import clean_file_name, normalize
# logger = kodi_utils.logger

def oc_cloud():
	def _builder():
		for count, item in enumerate(folders, 1):
			try:
				cm = []
				cm_append = cm.append
				is_folder = item['isDirectory']
				request_id, folder_name, server = item['requestId'], item['fileName'], item['server']
				delete_params = {'mode': 'offcloud.delete', 'folder_id': request_id}
				if is_folder:
					display = '%02d | [B]FOLDER[/B] | [I]%s [/I]' % (count, clean_file_name(normalize(folder_name)).upper())
					url_params = {'mode': 'offcloud.browse_oc_cloud', 'folder_id': request_id}
					cm_append(('[B]Delete Folder[/B]', 'RunPlugin(%s)' % kodi_utils.build_url(delete_params)))
				else:
					display = '%02d | [B]File[/B] | [I]%s [/I]' % (count, clean_file_name(normalize(folder_name)).upper())
					link = Offcloud.requote_uri(Offcloud.build_url(server, request_id, folder_name))
					url_params = {'mode': 'offcloud.resolve_oc', 'url': link, 'play': 'true'}
					down_file_params = {'mode': 'downloader', 'action': 'cloud.offcloud_direct', 'name': folder_name, 'url': link, 'image': icon}
					cm_append(('[B][B]Delete File[/B][/B]', 'RunPlugin(%s)' % kodi_utils.build_url(delete_params)))
					cm.append(('[B]Download File[/B]','RunPlugin(%s)' % kodi_utils.build_url(down_file_params)))
				url = kodi_utils.build_url(url_params)
				listitem = kodi_utils.make_listitem()
				listitem.setLabel(display)
				listitem.addContextMenuItems(cm)
				listitem.setArt({'icon': icon, 'poster': icon, 'thumb': icon, 'fanart': fanart, 'banner': icon})
				yield (url, listitem, is_folder)
			except: pass
	icon, fanart = kodi_utils.get_icon('offcloud'), kodi_utils.get_addon_fanart()
	cloud_folders = Offcloud.user_cloud()
	folders = [i for i in cloud_folders if i['status'] == 'downloaded']
	handle = int(sys.argv[1])
	kodi_utils.add_items(handle, list(_builder()))
	kodi_utils.set_content(handle, 'files')
	kodi_utils.end_directory(handle)
	kodi_utils.set_view_mode('view.premium')

def browse_oc_cloud(folder_id):
	def _builder():
		for count, item in enumerate(video_files, 1):
			try:
				cm = []
				name = item.split('/')[-1]
				name = clean_file_name(name).upper()
				link = Offcloud.requote_uri(item)
				display = '%02d | [B]FILE[/B] | [I]%s [/I]' % (count, name)
				url_params = {'mode': 'offcloud.resolve_oc', 'url': link, 'play': 'true'}
				url = kodi_utils.build_url(url_params)
				down_file_params = {'mode': 'downloader', 'action': 'cloud.offcloud_direct', 'name': name, 'url': link, 'image': icon}
				cm.append(('[B]Download File[/B]','RunPlugin(%s)' % kodi_utils.build_url(down_file_params)))
				listitem = kodi_utils.make_listitem()
				listitem.setLabel(display)
				listitem.addContextMenuItems(cm)
				listitem.setArt({'icon': icon, 'poster': icon, 'thumb': icon, 'fanart': fanart, 'banner': icon})
				listitem.setInfo('video', {})
				yield (url, listitem, False)
			except: pass
	icon, fanart = kodi_utils.get_icon('offcloud'), kodi_utils.get_addon_fanart()
	torrent_files = Offcloud.user_cloud_info(folder_id)
	video_files = [i for i in torrent_files if i.lower().endswith(tuple(supported_video_extensions()))]
	handle = int(sys.argv[1])
	kodi_utils.add_items(handle, list(_builder()))
	kodi_utils.set_content(handle, 'files')
	kodi_utils.end_directory(handle)
	kodi_utils.set_view_mode('view.premium')

def oc_delete(folder_id):
	if not kodi_utils.confirm_dialog(): return
	result = Offcloud.delete_torrent(folder_id)
	if 'success' not in result: return kodi_utils.notification('Error')
	Offcloud.clear_cache()
	kodi_utils.execute_builtin('Container.Refresh')

def resolve_oc(params):
	url = params['url']
	if params.get('play', 'false') != 'true' : return url
	from modules.player import FenLightPlayer
	FenLightPlayer().run(url, 'video')

def oc_account_info():
	try:
		kodi_utils.show_busy_dialog()
		account_info = Offcloud.account_info()
		body = []
		append = body.append
		append('[B]Email[/B]: %s' % account_info['email'])
		append('[B]User ID[/B]: %s' % account_info['userId'])
		append('[B]Premium[/B]: %s' % account_info['isPremium'])
		append('[B]Expires[/B]: %s' % account_info['expirationDate'])
		append('[B]Cloud Limit[/B]: {:,}'.format(account_info['limits']['cloud']))
		kodi_utils.hide_busy_dialog()
		return kodi_utils.show_text('OFFCLOUD', '\n\n'.join(body), font_size='large')
	except: kodi_utils.hide_busy_dialog()

