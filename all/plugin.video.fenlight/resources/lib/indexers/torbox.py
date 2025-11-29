import sys
from apis.torbox_api import TorBox
from modules.source_utils import supported_video_extensions
from modules.utils import clean_file_name, normalize
from modules import kodi_utils
# from modules.kodi_utils import logger

def tb_cloud():
	def _builder():
		for count, item in enumerate(folders, 1):
			try:
				cm = []
				cm_append = cm.append
				display = '%02d | [B]FOLDER[/B] | [I]%s [/I]' % (count, clean_file_name(normalize(item['name'])).upper())
				url_params = {'mode': 'torbox.browse_tb_cloud', 'folder_id': item['id'], 'media_type': item['media_type']}
				delete_params = {'mode': 'torbox.delete', 'folder_id': item['id'], 'media_type': item['media_type']}
				cm_append(('[B]Delete Folder[/B]', 'RunPlugin(%s)' % kodi_utils.build_url(delete_params)))
				url = kodi_utils.build_url(url_params)
				listitem = kodi_utils.make_listitem()
				listitem.setLabel(display)
				listitem.addContextMenuItems(cm)
				listitem.setArt({'icon': icon, 'poster': icon, 'thumb': icon, 'fanart': fanart, 'banner': icon})
				yield (url, listitem, True)
			except: pass
	icon, fanart = kodi_utils.get_icon('torbox'), kodi_utils.get_addon_fanart()
	torrents_folders, usenets_folders = TorBox.user_cloud(), TorBox.user_cloud_usenet()
	t_data, u_data = torrents_folders['data'], usenets_folders['data']
	folders_torrents = [{**i, 'media_type': 'torrent'} for i in t_data if i['download_finished']]
	folders_usenets = [{**i, 'media_type': 'usenet'} for i in u_data if i['download_finished']]
	folders = folders_torrents + folders_usenets
	folders.sort(key=lambda k: k['updated_at'], reverse=True)
	handle = int(sys.argv[1])
	kodi_utils.add_items(handle, list(_builder()))
	kodi_utils.set_content(handle, 'files')
	kodi_utils.end_directory(handle)
	kodi_utils.set_view_mode('view.premium')

def browse_tb_cloud(folder_id, media_type):
	def _builder():
		for count, item in enumerate(video_files, 1):
			try:
				cm = []
				name = clean_file_name(item['short_name']).upper()
				size = float(int(item['size']))/1073741824
				display = '%02d | [B]FILE[/B] | %.2f GB | [I]%s [/I]' % (count, size, name)
				url_link = '%d,%d' % (int(folder_id), item['id'])
				url_params = {'mode': 'torbox.resolve_tb', 'play': 'true', 'url': url_link, 'media_type': item['media_type']}
				down_file_params = {'mode': 'downloader.runner', 'name': name, 'url': url_link, 'media_type': item['media_type'], 'action': 'cloud.torbox', 'image': icon}
				cm.append(('[B]Download File[/B]','RunPlugin(%s)' % kodi_utils.build_url(down_file_params)))
				url = kodi_utils.build_url(url_params)
				listitem = kodi_utils.make_listitem()
				listitem.setLabel(display)
				listitem.addContextMenuItems(cm)
				listitem.setArt({'icon': icon, 'poster': icon, 'thumb': icon, 'fanart': fanart, 'banner': icon})
				listitem.setInfo('video', {})
				yield (url, listitem, False)
			except: pass
	if media_type == 'torrent': files = TorBox.user_cloud_info(folder_id)
	else: files = TorBox.user_cloud_info_usenet(folder_id)
	data_files = files['data']['files']
	video_files = [{**i, 'media_type': media_type} for i in data_files if i['short_name'].lower().endswith(tuple(supported_video_extensions()))]
	icon, fanart = kodi_utils.get_icon('torbox'), kodi_utils.get_addon_fanart()
	handle = int(sys.argv[1])
	kodi_utils.add_items(handle, list(_builder()))
	kodi_utils.set_content(handle, 'files')
	kodi_utils.end_directory(handle)
	kodi_utils.set_view_mode('view.premium')

def tb_delete(folder_id, media_type):
	if not kodi_utils.confirm_dialog(): return
	if media_type == 'torrent': result = TorBox.delete_torrent(folder_id)
	else: result = TorBox.delete_usenet(folder_id)
	if not result['success']: return kodi_utils.notification('Error')
	TorBox.clear_cache()
	kodi_utils.execute_builtin('Container.Refresh')

def resolve_tb(params):
	file_id, media_type = params['url'], params['media_type']
	if media_type == 'torrent': resolved_link = TorBox.unrestrict_link(file_id)
	else: resolved_link = TorBox.unrestrict_usenet(file_id)
	if params.get('play', 'false') != 'true': return resolved_link
	from modules.player import FenLightPlayer
	FenLightPlayer().run(resolved_link, 'video')

def tb_account_info():
	try:
		kodi_utils.show_busy_dialog()
		plans = {0: 'Free plan', 1: 'Essential plan', 2: 'Pro plan', 3: 'Standard plan'}
		account_info = TorBox.account_info()
		account_info = account_info['data']
		body = []
		append = body.append
		append('[B]Email[/B]: %s' % account_info['email'])
		append('[B]customer[/B]: %s' % account_info['customer'])
		append('[B]Plan[/B]: %s' % plans[account_info['plan']])
		append('[B]Expires[/B]: %s' % account_info['premium_expires_at'])
		append('[B]Downloaded[/B]: {:,}'.format(account_info['total_downloaded']))
		kodi_utils.hide_busy_dialog()
		return kodi_utils.show_text('TorBox'.upper(), '\n\n'.join(body), font_size='large')
	except: kodi_utils.hide_busy_dialog()

