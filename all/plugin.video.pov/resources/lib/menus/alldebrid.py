import sys
from datetime import datetime
from debrids.alldebrid_api import AllDebridAPI as Debrid
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
			return self.cloud_delete(params['id'])
		elif '_browse_cloud' in params['mode']:
			items = self.torrent_info(params['id'])
			items = self.flatten_magnet_files(items['files'])
			_builder = self.browse_cloud
		elif '_torrent_cloud' in params['mode']:
			items = self.user_cloud()['magnets']
			_builder = self.torrent_cloud
		elif '_downloads' in params['mode']:
			items = self.downloads()['links']
			_builder = self.browse_downloads
		else: return getattr(self, params['mode'].split('.')[-1])()
		__handle__ = int(sys.argv[1])
		kodi_utils.add_items(__handle__, list(_builder(items)))
		kodi_utils.set_content(__handle__, 'files')
		kodi_utils.end_directory(__handle__)
		kodi_utils.set_view_mode('view.premium')

	def torrent_cloud(self, items):
		items.sort(key=lambda k: (k['uploadDate'], k['id']), reverse=True)
		for count, item in enumerate(items, 1):
			try:
				cm = []
				cm_append = cm.append
				folder_name = item['filename']
				display = '%02d | [B]%s[/B] | [I]%s [/I]' % (count, folder_str, clean_file_name(normalize(folder_name)).upper())
				url_params = {'mode': 'alldebrid.ad_browse_cloud', 'id': item['id']}
				delete_params = {'mode': 'alldebrid.ad_delete', 'id': item['id']}
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
				if not item['n'].lower().endswith(tuple(extensions)): continue
				cm = []
				cm_append = cm.append
				name = clean_file_name(item['n']).upper()
				size = float(int(item['s']))/1073741824
				display = '%02d | [B]%s[/B] | %.2f GB | [I]%s [/I]' % (count, file_str, size, name)
				params = {'name': name, 'url': item['l'], 'image': default_icon}
				url_params = {**params, 'mode': 'alldebrid.resolve_ad', 'play': 'true'}
				down_file_params = {**params, 'mode': 'downloader', 'action': 'cloud.alldebrid'}
				cm_append((down_str, 'RunPlugin(%s)' % build_url(down_file_params)))
				url = build_url(url_params)
				listitem = make_listitem()
				listitem.setLabel(display)
				listitem.addContextMenuItems(cm)
				listitem.setArt(default_art)
				listitem.setInfo('video', {})
				yield (url, listitem, False)
			except: pass

	def browse_downloads(self, items):
		items.sort(key=lambda k: k['date'], reverse=True)
		for count, item in enumerate(items, 1):
			try:
				if not item['filename'].lower().endswith(tuple(extensions)): continue
				cm = []
				cm_append = cm.append
				name = clean_file_name(item['filename']).upper()
				size = float(int(item['size']))/1073741824
				datetime_object = datetime.fromtimestamp(item['date']).strftime('%Y-%m-%d')
				display = '%02d | %.2f GB | %s | [I]%s [/I]' % (count, size, datetime_object, name)
				params = {'name': name, 'url': item['link_dl'], 'image': default_icon}
				url_params = {**params, 'mode': 'media_play', 'mediatype': 'video'}
				down_file_params = {**params, 'mode': 'downloader', 'action': 'cloud.alldebrid_direct'}
				cm_append((down_str, 'RunPlugin(%s)' % build_url(down_file_params)))
				url = build_url(url_params)
				listitem = make_listitem()
				listitem.setLabel(display)
				listitem.addContextMenuItems(cm)
				listitem.setArt(default_art)
				yield (url, listitem, False)
			except: pass

	def cloud_delete(self, file_id):
		if not kodi_utils.confirm_dialog(): return
		result = self.delete_torrent(file_id)
		if not result: return kodi_utils.notification(32574)
		self.clear_cache()
		kodi_utils.container_refresh()

	def show_account_info(self):
		try:
			kodi_utils.show_busy_dialog()
			account_info = self.account_info()['user']
			username = account_info['username']
			email = account_info['email']
			status = 'Premium' if account_info['isPremium'] else 'Not Active'
			expires = datetime.fromtimestamp(account_info['premiumUntil'])
			days_remaining = (expires - datetime.today()).days
			body = []
			append = body.append
			append(ls(32755) % username)
			append(ls(32756) % email)
			append(ls(32757) % status)
			append(ls(32750) % expires)
			append(ls(32751) % days_remaining)
			kodi_utils.hide_busy_dialog()
			return kodi_utils.show_text(ls(32063).upper(), '\n\n'.join(body), font_size='large')
		except: kodi_utils.hide_busy_dialog()

def resolve_ad(params):
	url = params['url']
	resolved_link = Debrid().unrestrict_link(url)
	if params.get('play', 'false') != 'true' : return resolved_link
	kodi_utils.player.play(resolved_link)

