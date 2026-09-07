from caches.main_cache import cache_object
from indexers.premiumize_api import PremiumizeAPI as Debrid
from modules import kodi_utils, source_utils
from modules.settings import enabled_debrids_check, filter_by_name
# from modules.kodi_utils import logger

extensions = tuple(source_utils.supported_video_extensions())
internal_results, check_title = source_utils.internal_results, source_utils.check_title
clean_file_name, clean_title = source_utils.clean_file_name, source_utils.clean_title
get_file_info, seas_ep_filter = source_utils.get_file_info, source_utils.seas_ep_filter
ls, build_url, make_listitem = kodi_utils.local_string, kodi_utils.build_url, kodi_utils.make_listitem
folder_str, file_str, delete_str, down_str = ls(32742).upper(), ls(32743).upper(), ls(32785), ls(32747)
archive_str, rename_str = ls(32749), ls(32748)
fanart = kodi_utils.get_addoninfo('fanart')
default_icon = kodi_utils.media_path(Debrid.icon)
default_art = {'icon': default_icon, 'poster': default_icon, 'thumb': default_icon, 'fanart': fanart, 'banner': default_icon}

class Menu(Debrid):
	def run(self, params):
		if   '_delete' in params['mode']:
			return self.cloud_delete(params['file_type'], params['id'])
		elif '_rename' in params['mode']:
			return self.cloud_rename(params['file_type'], params['id'], params['name'])
		elif '_browse_cloud' in params['mode']:
			items = self.parse_user_cloud(params.get('id'))
		elif '_downloads' in params['mode']:
			items = self.browse_downloads()
		else: return getattr(self, params['mode'].split('.')[-1])()
		__handle__ = int(kodi_utils.argv1())
		kodi_utils.add_items(__handle__, items)
		kodi_utils.set_content(__handle__, 'files')
		kodi_utils.end_directory(__handle__)
		kodi_utils.set_view_mode('view.premium')

	def show_account_info(self):
		from datetime import datetime, timezone
		try:
			kodi_utils.show_busy_dialog()
			account_info = self.account_info()
			username = account_info['customer_id']
			status = 'Premium' if account_info['premium_until'] else 'Expired'
			if account_info['premium_until']:
				expires = datetime.fromtimestamp(account_info['premium_until'], tz=timezone.utc)
				days_remaining = (expires - datetime.now(timezone.utc)).days
			else: expires, days_remaining = 'Expired', '0'
			percentage_used = str(round(float(account_info['limit_used']) * 100.0, 1))
			body = []
			append = body.append
#			append(ls(32754) % username)
			append(ls(32757) % status)
			append(ls(32750) % expires.date() if hasattr(expires, 'date') else expires)
			append(ls(32751) % days_remaining)
			append('[B]Fair Use (Percentage Used):[/B] %s%%' % percentage_used)
			kodi_utils.hide_busy_dialog()
			return kodi_utils.ok_dialog('Premiumize'.upper(), '[CR]'.join(body), top_space=False)
		except: kodi_utils.hide_busy_dialog()

	def cloud_delete(self, file_type, file_id):
		if not kodi_utils.confirm_dialog(): return
		result = self.delete_object(file_type, file_id)
		if not result: return kodi_utils.notify_failed()
		self.clear_cache()
		kodi_utils.container_refresh()

	def cloud_rename(self, file_type, file_id, current_name):
		new_name = kodi_utils.dialog.input('POV', defaultt=current_name)
		if not new_name: return
		result = self.rename_cache_item(file_type, file_id, new_name)
		if not result: return kodi_utils.notify_failed()
		self.clear_cache()
		kodi_utils.container_refresh()

	def parse_user_cloud(self, folder_id):
		if not folder_id:
			string = 'pov_pm_user_cloud'
			func = self.user_cloud
			folder_id = []
		else:
			string = 'pov_pm_user_cloud_%s' % folder_id
			func = self.user_folder
		items = cache_object(func, string, folder_id, 0.5)
		if not items or not items['content']: return []
		folders = []
		folders_append = folders.append
		for count, item in enumerate(items['content'], 1):
			try:
				if not ('link' in item and item['link'].lower().endswith(extensions)) and item['type'] != 'folder': continue
				cm = []
				cm_append = cm.append
				file_type = item['type']
				name = clean_file_name(item['name']).upper()
				delete_params = {'mode': 'premiumize.pm_delete', 'id': item['id']}
				rename_params = {'mode': 'premiumize.pm_rename', 'file_type': file_type, 'id': item['id'], 'name': item['name']}
				down_file_params = {}
				if file_type == 'folder':
					is_folder = True
					download_string = archive_str
					delete_params['file_type'] = 'folder'
					string = folder_str
					display = '%02d | [B]%s[/B] | [I]%s [/I]' % (count, folder_str, name)
					url_params = {'mode': 'premiumize.pm_browse_cloud', 'id': item['id']}
				else:
					is_folder = False
					download_string = down_str
					delete_params['file_type'] = 'item'
					string = file_str
					url_link = item['link']
					if url_link.startswith('/'): url_link = 'https:/' + url_link
					size = item['size']
					display_size = float(int(size))/1073741824
					display = '%02d | [B]%s[/B] | %.2f GB | [I]%s [/I]' % (count, file_str, display_size, name)
					params = {'id': url_link, 'url': url_link, 'image': default_icon}
					params.update({'name': item['name'], 'scrape_provider': 'pm_cloud'})
					url_params = {**params, 'mode': 'media_play'}
					down_file_params = {**params, 'mode': 'downloader', 'action': 'pm_cloud'}
				cm_append(('[B]%s %s[/B]' % (delete_str, string.capitalize()), 'RunPlugin(%s)' % build_url(delete_params)))
				if down_file_params: cm_append((download_string, 'RunPlugin(%s)' % build_url(down_file_params)))
				cm_append((rename_str % file_type.capitalize(), 'RunPlugin(%s)' % build_url(rename_params)))
				url = build_url(url_params)
				listitem = make_listitem()
				listitem.setLabel(display)
				listitem.addContextMenuItems(cm)
				listitem.setArt(default_art)
				folders_append((url, listitem, is_folder))
			except: pass
		return folders

	def browse_downloads(self):
		string = 'pov_pm_downloads'
		items = cache_object(self.downloads, string, [], 0.5)
		if not items or not items['transfers']: return []
		KODI_VERSION = kodi_utils.get_kodi_version()
		folders = []
		folders_append = folders.append
		for count, item in enumerate(items['transfers'], 1):
			try:
				cm = []
				cm_append = cm.append
				file_type = 'folder' if item['file_id'] is None else 'file'
				name = clean_file_name(item['name']).upper()
				message = '[CR]'.join(item['message'].split(', ')) if item['message'] else ''
				status, progress = item['status'], item['progress']
				progress = 100 if status == 'finished' else progress or 0
				delete_params = {'mode': 'premiumize.pm_delete', 'file_type': 'transfer', 'id': item['id']}
				down_file_params = {}
				if file_type == 'folder':
					is_folder = True if status == 'finished' else False
					string = folder_str
					display = '%02d | %.2f%% | [B]%s[/B] | [I]%s [/I]' % (count, progress, folder_str, name)
					if is_folder: url_params = {'mode': 'premiumize.pm_browse_cloud', 'id': item['folder_id'], 'folder_name': clean_file_name(item['name'])}
					else: url_params = {'mode': 'premiumize.pm_downloads'}
				else:
					is_folder = False
					string = file_str
					details = self.get_item_details(item['file_id'])
					url_link = details['link']
					if url_link.startswith('/'): url_link = 'https:/' + url_link
					size = details['size']
					display_size = float(int(size))/1073741824
					display = '%02d | %.2f%% | [B]%s[/B] | %.2f GB | [I]%s [/I]' % (count, progress, file_str, display_size, name)
					params = {'id': url_link, 'url': url_link, 'image': default_icon}
					params.update({'name': item['name'], 'scrape_provider': 'pm_cloud'})
					url_params = {**params, 'mode': 'media_play'}
					down_file_params = {**params, 'mode': 'downloader', 'action': 'pm_cloud'}
				cm_append(('[B]%s %s[/B]' % (delete_str, string.capitalize()), 'RunPlugin(%s)' % build_url(delete_params)))
				if down_file_params: cm_append((down_str, 'RunPlugin(%s)' % build_url(down_file_params)))
				url = build_url(url_params)
				listitem = make_listitem()
				listitem.setLabel(display)
				listitem.addContextMenuItems(cm)
				listitem.setArt(default_art)
				if status != 'finished': listitem.setInfo('video', {'plot': message}) if KODI_VERSION < 20 else listitem.getVideoInfoTag().setPlot(message)
				folders_append((url, listitem, is_folder))
			except: pass
		return folders

class source(Debrid):
	scrape_provider = 'pm_cloud'
	def results(self, info):
		try:
			self.sources = []
			sources_append = self.sources.append
			if not enabled_debrids_check('pm'): return internal_results(self.scrape_provider, self.sources)
			self.scrape_results = []
			title, season, episode = info.get('title'), info.get('season'), info.get('episode')
			if not filter_by_name(self.scrape_provider): self.aliases = None
			else: self.aliases = source_utils.get_aliases_titles(info.get('aliases', []))
			self._scrape_cloud()
			if not self.scrape_results: return internal_results(self.scrape_provider, self.sources)
			extras_filtering_list = tuple(i for i in source_utils.extras_filter() if i not in title.lower())
			for item in self.scrape_results:
				try:
					normalized = clean_title(item['filename'])
					if not normalized.endswith(extensions): continue
					for i in ('filename', 'folder_name'):
						if check_title(title, item[i], self.aliases): break
					else: continue
					if season:
						if not seas_ep_filter(season, episode, item['filename']): continue
					elif any(x in normalized for x in extras_filtering_list): continue

					display_name = clean_file_name(item['filename']).replace('html', ' ')
					file_dl = self.get_item_details(item['link'])['link']
					size = round(float(int(item['size']))/1073741824, 2)
					video_quality, details = get_file_info(name_info=normalized)
					sources_append({
						'direct': True,
						'source': self.scrape_provider, 'scrape_provider': self.scrape_provider,
						'id': file_dl, 'url_dl': file_dl,
						'name': display_name, 'display_name': display_name,
						'extraInfo': details, 'quality': video_quality,
						'size': size, 'size_label': '%.2f GB' % size
					})
				except: pass
		except Exception as e:
			from modules.kodi_utils import logger
			logger(f"POV {self.scrape_provider} Exception", e)
		internal_results(self.scrape_provider, self.sources)
		return self.sources

	def _scrape_cloud(self):
		try:
			results_append = self.scrape_results.append
			folders = self.item_listall()
			for item in folders:
				try: item.update({'folder_name': item['path'], 'filename': item['name'], 'link': item['id']})
				except: pass
				else: results_append(item)
		except: pass

