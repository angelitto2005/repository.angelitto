import sys
from debrids.offcloud_api import OffcloudAPI as Debrid
from modules import kodi_utils
from modules.source_utils import supported_video_extensions
from modules.utils import clean_file_name, normalize
# from modules.kodi_utils import logger

get_setting, set_setting = kodi_utils.get_setting, kodi_utils.set_setting
ls, build_url, make_listitem = kodi_utils.local_string, kodi_utils.build_url, kodi_utils.make_listitem
folder_str, file_str, delete_str, down_str = ls(32742).upper(), ls(32743).upper(), ls(32785), ls(32747)
fanart = kodi_utils.get_addoninfo('fanart')
default_icon = kodi_utils.media_path(Debrid.icon)
default_art = {'icon': default_icon, 'poster': default_icon, 'thumb': default_icon, 'fanart': fanart, 'banner': default_icon}
extensions = supported_video_extensions()

class Menu(Debrid):
	def run(self, params):
		if   '_delete' in params['mode']:
			return self.cloud_delete(params['folder_id'])
		elif '_browse_cloud' in params['mode']:
			items = self.torrent_info(params['folder_id'])
			items = items['files']
			_builder = self.browse_cloud
		elif '_torrent_cloud' in params['mode']:
			items = self.user_cloud()
			_builder = self.torrent_cloud
		else: return getattr(self, params['mode'].split('.')[-1])()
		__handle__ = int(sys.argv[1])
		kodi_utils.add_items(__handle__, list(_builder(items)))
		kodi_utils.set_content(__handle__, 'files')
		kodi_utils.end_directory(__handle__)
		kodi_utils.set_view_mode('view.premium')

	def torrent_cloud(self, items):
		for count, item in enumerate(items, 1):
			try:
				cm = []
				cm_append = cm.append
				request_id, folder_name = item['requestId'], item['fileName']
				display = '%02d | [B]%s[/B] | [I]%s [/I]' % (count, folder_str, clean_file_name(normalize(folder_name)).upper())
				url_params = {'mode': 'offcloud.oc_browse_cloud', 'folder_id': request_id}
				delete_params = {'mode': 'offcloud.oc_delete', 'folder_id': request_id}
				cm_append(('[B]%s %s[/B]' % (delete_str, folder_str.capitalize()), 'RunPlugin(%s)' % build_url(delete_params)))
				url = build_url(url_params)
				listitem = make_listitem()
				listitem.setLabel(display)
				listitem.addContextMenuItems(cm)
				listitem.setArt(default_art)
				yield (url, listitem, True)
			except: pass

	def browse_cloud(self, items):
		for count, item in enumerate(items, 1):
			try:
				if not item['path'].lower().endswith(tuple(extensions)): continue
				cm = []
				cm_append = cm.append
				name = clean_file_name(item['path']).upper()
				size = float(int(item['size']))/1073741824
				display = '%02d | [B]%s[/B] | %.2f GB | [I]%s [/I]' % (count, file_str, size, name)
				params = {'name': name, 'url': item['url'], 'image': default_icon}
				url_params = {**params, 'mode': 'media_play', 'mediatype': 'video'}
				down_file_params = {**params, 'mode': 'downloader', 'action': 'cloud.offcloud_direct'}
				cm_append((down_str, 'RunPlugin(%s)' % build_url(down_file_params)))
				url = build_url(url_params)
				listitem = make_listitem()
				listitem.setLabel(display)
				listitem.addContextMenuItems(cm)
				listitem.setArt(default_art)
				listitem.setInfo('video', {})
				yield (url, listitem, False)
			except: pass

	def cloud_delete(self, folder_id):
		if not kodi_utils.confirm_dialog(): return
		result = self.delete_torrent(folder_id)
		if not result: return kodi_utils.notification(32574)
		self.clear_cache()
		kodi_utils.container_refresh()

	def show_account_info(self):
		from datetime import datetime
		from modules.utils import datetime_workaround
		try:
			kodi_utils.show_busy_dialog()
			account_info = self.account_info()
			expires = datetime_workaround(account_info['expiration_date'], '%Y-%m-%d')
			days_remaining = (expires - datetime.today()).days
			body = []
			append = body.append
			append(ls(32758) % account_info['user_id'])
			append(ls(32757) % ('Premium' if account_info['is_premium'] else 'Expired'))
			append(ls(32750) % expires)
			append(ls(32751) % days_remaining)
			kodi_utils.hide_busy_dialog()
			return kodi_utils.show_text('Offcloud'.upper(), '\n\n'.join(body), font_size='large')
		except: kodi_utils.hide_busy_dialog()

