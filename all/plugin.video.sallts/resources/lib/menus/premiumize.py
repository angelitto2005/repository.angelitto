import sys
from debrids.premiumize_api import PremiumizeAPI as Debrid
from modules import kodi_utils
from modules.source_utils import supported_video_extensions
from modules.utils import clean_file_name, normalize
# from modules.kodi_utils import logger

get_setting, set_setting = kodi_utils.get_setting, kodi_utils.set_setting
ls, build_url, make_listitem = kodi_utils.local_string, kodi_utils.build_url, kodi_utils.make_listitem
folder_str, file_str, down_str, archive_str, rename_str, delete_str = ls(32742).upper(), ls(32743).upper(), ls(32747), ls(32982), ls(32748), ls(32785)
fanart = kodi_utils.get_addoninfo('fanart')
default_icon = kodi_utils.media_path(Debrid.icon)
default_art = {'icon': default_icon, 'poster': default_icon, 'thumb': default_icon, 'fanart': fanart, 'banner': default_icon}
extensions = supported_video_extensions()

class Menu(Debrid):
	def run(self, params, *args):
		if   '_delete' in params['mode']:
			return self.cloud_delete(params['file_type'], params['id'])
		elif '_rename' in params['mode']:
			return self.cloud_rename(params['file_type'], params['id'], params['name'])
		elif '_torrent_cloud' in params['mode']:
			args = params.get('id'), params.get('folder_name')
			items = self.user_cloud(args[0])['content']
			_builder = self.torrent_cloud
		elif '_downloads' in params['mode']:
			items = self.downloads()['transfers']
			_builder = self.browse_downloads
		else: return getattr(self, params['mode'].split('.')[-1])()
		__handle__ = int(sys.argv[1])
		kodi_utils.add_items(__handle__, list(_builder(items, *args)))
		kodi_utils.set_content(__handle__, 'files')
		kodi_utils.end_directory(__handle__)
		kodi_utils.set_view_mode('view.premium')

	def torrent_cloud(self, items, folder_id=None, folder_name=None):
		items.sort(key=lambda k: k['name'])
		items.sort(key=lambda k: k['type'], reverse=True)
		for count, item in enumerate(items, 1):
			try:
				if not ('link' in item and item['link'].lower().endswith(tuple(extensions))) and not item['type'] == 'folder': continue
				cm = []
				cm_append = cm.append
				file_type = item['type']
				name = clean_file_name(item['name']).upper()
				rename_params = {'mode': 'premiumize.pm_rename', 'file_type': file_type, 'id': item['id'], 'name': item['name']}
				delete_params = {'mode': 'premiumize.pm_delete', 'id': item['id']}
				if file_type == 'folder':
					is_folder = True
					download_string = archive_str
					delete_params['file_type'] = 'folder'
					string = folder_str
					display = '%02d | [B]%s[/B] | [I]%s [/I]' % (count, folder_str, name)
					url_params = {'mode': 'premiumize.pm_torrent_cloud', 'id': item['id'], 'folder_name': normalize(item['name'])}
				else:
					is_folder = False
					download_string = down_str
					delete_params['file_type'] = 'item'
					string = file_str
					url_link = item['link']
					if url_link.startswith('/'): url_link = 'https' + url_link
					size = item['size']
					display_size = float(int(size))/1073741824
					display = '%02d | [B]%s[/B] | %.2f GB | [I]%s [/I]' % (count, file_str, display_size, name)
					url_params = {'mode': 'media_play', 'url': url_link, 'mediatype': 'video'}
					down_file_params = {'mode': 'downloader', 'action': 'cloud.premiumize', 'name': item['name'], 'url': url_link, 'image': default_icon}
					cm_append((download_string, 'RunPlugin(%s)' % build_url(down_file_params)))
				cm_append(('[B]%s %s[/B]' % (delete_str, string.capitalize()), 'RunPlugin(%s)' % build_url(delete_params)))
				cm_append((rename_str % file_type.capitalize(), 'RunPlugin(%s)' % build_url(rename_params)))
				url = build_url(url_params)
				listitem = make_listitem()
				listitem.setLabel(display)
				listitem.addContextMenuItems(cm)
				listitem.setArt(default_art)
				yield (url, listitem, is_folder)
			except: pass

	def browse_downloads(self, items):
		KODI_VERSION = kodi_utils.get_kodi_version()
		for count, item in enumerate(items, 1):
			try:
				cm = []
				cm_append = cm.append
				file_type = 'folder' if item['file_id'] is None else 'file'
				name = clean_file_name(item['name']).upper()
				message = '[CR]'.join(item['message'].split(', '))
				status, progress = item['status'], item['progress']
				progress = 100 if status == 'finished' else progress or 0
				if file_type == 'folder':
					is_folder = True if status == 'finished' else False
					display = '%02d | %.2f%% | [B]%s[/B] | [I]%s [/I]' % (count, progress, folder_str, name)
					if is_folder: url_params = {'mode': 'premiumize.pm_torrent_cloud', 'id': item['folder_id'], 'folder_name': normalize(item['name'])}
					else: url_params = {'mode': 'premiumize.pm_downloads'}
				else:
					is_folder = False
					details = self.get_item_details(item['file_id'])
					url_link = details['link']
					if url_link.startswith('/'): url_link = 'https' + url_link
					size = details['size']
					display_size = float(int(size))/1073741824
					display = '%02d | %.2f%% | [B]%s[/B] | %.2f GB | [I]%s [/I]' % (count, progress, file_str, display_size, name)
					url_params = {'mode': 'media_play', 'url': url_link, 'mediatype': 'video'}
					down_file_params = {'mode': 'downloader', 'mediatype': 'cloud.premiumize', 'name': item['name'], 'url': url_link, 'image': default_icon}
					cm_append((down_str, 'RunPlugin(%s)' % build_url(down_file_params)))
				url = build_url(url_params)
				listitem = make_listitem()
				listitem.setLabel(display)
				listitem.addContextMenuItems(cm)
				listitem.setArt(default_art)
				if not status == 'finished': listitem.setInfo('video', {'plot': message}) if KODI_VERSION < 20 else listitem.getVideoInfoTag().setPlot(message)
				yield (url, listitem, is_folder)
			except: pass

	def cloud_delete(self, file_type, file_id):
		if not kodi_utils.confirm_dialog(): return
		result = self.delete_object(file_type, file_id)
		if not result: return kodi_utils.ok_dialog(text=32574, top_space=True)
		self.clear_cache()
		kodi_utils.container_refresh()

	def cloud_rename(self, file_type, file_id, current_name):
		new_name = kodi_utils.dialog.input('SALTS', defaultt=current_name)
		if not new_name: return
		result = self.rename_cache_item(file_type, file_id, new_name)
		if not result: return kodi_utils.ok_dialog(text=32574, top_space=True)
		self.clear_cache()
		kodi_utils.container_refresh()

	def show_account_info(self):
		import math
		from datetime import datetime
		try:
			kodi_utils.show_busy_dialog()
			account_info = self.account_info()
			customer_id = account_info['customer_id']
			if account_info['premium_until']:
				expires = datetime.fromtimestamp(account_info['premium_until'])
				days_remaining = (expires - datetime.today()).days
			else: expires, days_remaining = 'Expired', 'None'
			points_used = int(math.floor(float(account_info['space_used']) / 1073741824.0))
			space_used = float(int(account_info['space_used']))/1073741824
			percentage_used = str(round(float(account_info['limit_used']) * 100.0, 1))
			body = []
			append = body.append
			append(ls(32749) % customer_id)
			append(ls(32750) % expires)
			append(ls(32751) % days_remaining)
			append(ls(32752) % points_used)
			append(ls(32753) % space_used)
			append(ls(32754) % (percentage_used + '%'))
			kodi_utils.hide_busy_dialog()
			return kodi_utils.show_text(ls(32061).upper(), '\n\n'.join(body), font_size='large')
		except: kodi_utils.hide_busy_dialog()

