from datetime import datetime, timezone
from threading import Thread
from caches.main_cache import cache_object
from indexers.alldebrid_api import AllDebridAPI as Debrid
from modules import kodi_utils, source_utils
from modules.settings import enabled_debrids_check, filter_by_name
# from modules.kodi_utils import logger

extensions = tuple(source_utils.supported_video_extensions())
internal_results, check_title = source_utils.internal_results, source_utils.check_title
clean_file_name, clean_title = source_utils.clean_file_name, source_utils.clean_title
get_file_info, seas_ep_filter = source_utils.get_file_info, source_utils.seas_ep_filter
ls, build_url, make_listitem = kodi_utils.local_string, kodi_utils.build_url, kodi_utils.make_listitem
folder_str, file_str, delete_str, down_str = ls(32742).upper(), ls(32743).upper(), ls(32785), ls(32747)
fanart = kodi_utils.get_addoninfo('fanart')
default_icon = kodi_utils.media_path(Debrid.icon)
default_art = {'icon': default_icon, 'poster': default_icon, 'thumb': default_icon, 'fanart': fanart, 'banner': default_icon}

class Menu(Debrid):
	def run(self, params):
		if   '_delete' in params['mode']:
			return self.cloud_delete(params['id'])
		elif '_browse_folder' in params['mode']:
			items = self.parse_folder(params['id'])
		elif '_browse_cloud' in params['mode']:
			items = self.parse_user_cloud()
		elif '_downloads' in params['mode']:
			items = self.browse_downloads()
		else: return getattr(self, params['mode'].split('.')[-1])()
		__handle__ = int(kodi_utils.argv1())
		kodi_utils.add_items(__handle__, items)
		kodi_utils.set_content(__handle__, 'files')
		kodi_utils.end_directory(__handle__)
		kodi_utils.set_view_mode('view.premium')

	def show_account_info(self):
		try:
			kodi_utils.show_busy_dialog()
			account_info = self.account_info()['user']
			username = account_info['username']
			status = 'Premium' if account_info['isPremium'] else 'Expired'
			if account_info['premiumUntil']:
				expires = datetime.fromtimestamp(account_info['premiumUntil'], tz=timezone.utc)
				days_remaining = (expires - datetime.now(timezone.utc)).days
			else: expires, days_remaining = 'Expired', '0'
			body = []
			append = body.append
#			append(ls(32755) % username)
			append(ls(32757) % status)
			append(ls(32750) % expires.date() if hasattr(expires, 'date') else expires)
			append(ls(32751) % days_remaining)
			kodi_utils.hide_busy_dialog()
			return kodi_utils.ok_dialog('All Debrid'.upper(), '[CR]'.join(body), top_space=False)
		except: kodi_utils.hide_busy_dialog()

	def cloud_delete(self, file_id):
		if not kodi_utils.confirm_dialog(): return
		result = self.delete_torrent(file_id)
		if not result: return kodi_utils.notify_failed()
		self.clear_cache()
		kodi_utils.container_refresh()

	def parse_user_cloud(self):
		string = 'pov_ad_user_cloud'
		items = cache_object(self.user_cloud, string, [], 0.5)
		if not items or not items['magnets']: return []
		items['magnets'].sort(key=lambda k: (k['uploadDate'], k['id']), reverse=True)
		folders = []
		folders_append = folders.append
		for count, item in enumerate(items['magnets'], 1):
			try:
				if not item['statusCode'] == 4: continue
				cm = []
				cm_append = cm.append
				folder_name = item['filename']
				display = '%02d | [B]%s[/B] | [I]%s [/I]' % (count, folder_str, clean_file_name(folder_name).upper())
				url_params = {'mode': 'alldebrid.ad_browse_folder', 'id': item['id']}
				delete_params = {'mode': 'alldebrid.ad_delete', 'id': item['id']}
				cm_append(('[B]%s %s[/B]' % (delete_str, folder_str.capitalize()), 'RunPlugin(%s)' % build_url(delete_params)))
				url = build_url(url_params)
				listitem = make_listitem()
				listitem.setLabel(display)
				listitem.addContextMenuItems(cm)
				listitem.setArt(default_art)
				folders_append((url, listitem, True))
			except: pass
		return folders

	def parse_folder(self, folder_id):
		string = 'pov_ad_user_cloud_%s' % folder_id
		items = cache_object(self.user_folder, string, folder_id, 0.5)
		if not items or not items['files']: return []
		items['links'] = self.flatten_magnet_files(items['files'])
		files = []
		files_append = files.append
		for count, item in enumerate(items['links'], 1):
			try:
				if not item['n'].lower().endswith(extensions): continue
				cm = []
				cm_append = cm.append
				name = clean_file_name(item['n']).upper()
				size = float(int(item['s']))/1073741824
				display = '%02d | [B]%s[/B] | %.2f GB | [I]%s [/I]' % (count, file_str, size, name)
				params = {'id': item['l'], 'url': item['l'], 'image': default_icon}
				params.update({'name': item['n'], 'scrape_provider': 'ad_cloud', 'direct_debrid_link': 'false'})
				url_params = {**params, 'mode': 'media_play'}
				down_file_params = {**params, 'mode': 'downloader', 'action': 'ad_cloud'}
				cm_append((down_str, 'RunPlugin(%s)' % build_url(down_file_params)))
				url = build_url(url_params)
				listitem = make_listitem()
				listitem.setLabel(display)
				listitem.addContextMenuItems(cm)
				listitem.setArt(default_art)
				listitem.setInfo('video', {})
				files_append((url, listitem, False))
			except: pass
		return files

	def browse_downloads(self):
		string = 'pov_ad_downloads'
		items = cache_object(self.downloads, string, [], 0.5)
		if not items or not items['links']: return []
		items['links'].sort(key=lambda k: k['date'], reverse=True)
		folders = []
		folders_append = folders.append
		for count, item in enumerate(items['links'], 1):
			try:
				if not item['filename'].lower().endswith(extensions): continue
				cm = []
				cm_append = cm.append
				name = clean_file_name(item['filename']).upper()
				size = float(int(item['size']))/1073741824
				datetime_object = datetime.fromtimestamp(item['date']).date()
				display = '%02d | %.2f GB | %s | [I]%s [/I]' % (count, size, datetime_object, name)
				params = {'id': item['link_dl'], 'url': item['link_dl'], 'image': default_icon}
				params.update({'name': item['filename'], 'scrape_provider': 'ad_cloud'})
				url_params = {**params, 'mode': 'media_play'}
				down_file_params = {**params, 'mode': 'downloader', 'action': 'ad_cloud'}
				cm_append((down_str, 'RunPlugin(%s)' % build_url(down_file_params)))
				url = build_url(url_params)
				listitem = make_listitem()
				listitem.setLabel(display)
				listitem.addContextMenuItems(cm)
				listitem.setArt(default_art)
				folders_append((url, listitem, False))
			except: pass
		return folders

class source(Debrid):
	scrape_provider = 'ad_cloud'
	def results(self, info):
		try:
			self.sources = []
			sources_append = self.sources.append
			if not enabled_debrids_check('ad'): return internal_results(self.scrape_provider, self.sources)
			self.scrape_results = []
			title, season, episode = info.get('title'), info.get('season'), info.get('episode')
			if not filter_by_name(self.scrape_provider): self.aliases = None
			else: self.aliases = source_utils.get_aliases_titles(info.get('aliases', []))
			self._scrape_cloud(title)
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
					direct_debrid_link = item.get('downloads', False)
					file_dl = item['link_dl'] if direct_debrid_link else item['link']
					size = round(float(int(item['size']))/1073741824, 2)
					video_quality, details = get_file_info(name_info=normalized)
					sources_append({
						'direct': True, 'direct_debrid_link': direct_debrid_link,
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

	def _scrape_cloud(self, title):
		try:
			threads = []
			append = threads.append
			folders = self.user_cloud()
			for item in folders['magnets']:
				if not item['statusCode'] == 4: continue
				if not check_title(title, item['filename'], self.aliases): continue
				append(i := Thread(target=self._scrape_folders, args=(item,)))
				i.start()
			self._scrape_downloads()
			[i.join() for i in threads]
		except: pass

	def _scrape_folders(self, folder_info):
		try:
			results_append = self.scrape_results.append
			folder = self.user_folder(folder_info['id'])
			folder['links'] = self.flatten_magnet_files(folder['files'])
			for item in folder['links']:
				try: item.update({
					'folder_name': folder_info['filename'], 'filename': item['n'],
					'size': item['s'], 'link': item['l']
				})
				except: pass
				else: results_append(item)
		except: pass

	def _scrape_downloads(self):
		try:
			results_append = self.scrape_results.append
			downloads = self.downloads()
			for item in downloads['links']:
				try: item.update({'folder_name': item['filename'], 'downloads': True})
				except: pass
				else: results_append(item)
		except: pass

