from threading import Thread
from caches.main_cache import cache_object
from indexers.torbox_api import TorBoxAPI as Debrid
from modules import kodi_utils, source_utils
from modules.settings import enabled_debrids_check, filter_by_name
# from modules.kodi_utils import logger

extensions = tuple(source_utils.supported_video_extensions())
internal_results, check_title = source_utils.internal_results, source_utils.check_title
clean_file_name, clean_title = source_utils.clean_file_name, source_utils.clean_title
get_file_info, seas_ep_filter = source_utils.get_file_info, source_utils.seas_ep_filter
ls, build_url, make_listitem = kodi_utils.local_string, kodi_utils.build_url, kodi_utils.make_listitem
folder_str, file_str, delete_str, down_str = ls(32742).upper(), ls(32743).upper(), ls(32785), ls(32747)
_add_str, _rem_str, airlock_str = ls(32602).replace(' To', ''), ls(32603).replace(' From', ''), 'AIRLOCK'
fanart = kodi_utils.get_addoninfo('fanart')
default_icon = kodi_utils.media_path(Debrid.icon)
default_art = {'icon': default_icon, 'poster': default_icon, 'thumb': default_icon, 'fanart': fanart, 'banner': default_icon}

class Menu(Debrid):
	def run(self, params):
		if   '_airlock' in params['mode']:
			return self.cloud_airlock(params['id'], params['airlock'])
		elif '_delete' in params['mode']:
			return self.cloud_delete(params['id'])
		elif '_browse_folder' in params['mode']:
			folder_id, mediatype = params['id'].split(',')
			items = self.parse_folder(mediatype, folder_id)
		elif '_browse_cloud' in params['mode']:
			items = self.parse_user_cloud(params['mediatype'])
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
			username = account_info['customer']
			status = ('Free', 'Essential', 'Pro', 'Standard')[account_info['plan']]
			expires = datetime.fromisoformat(account_info['premium_expires_at'].replace('Z', '+00:00'))
			days_remaining = (expires - datetime.now(timezone.utc)).days
			body = []
			append = body.append
#			append(ls(32758) % username)
			append(ls(32757) % status)
			append(ls(32750) % expires.date() if hasattr(expires, 'date') else expires)
			append(ls(32751) % days_remaining)
			append('[B]Downloaded[/B]: %s' % account_info['total_downloaded'])
			kodi_utils.hide_busy_dialog()
			return kodi_utils.ok_dialog('TorBox'.upper(), '[CR]'.join(body), top_space=False)
		except: kodi_utils.hide_busy_dialog()

	def cloud_delete(self, folder_id):
		if not kodi_utils.confirm_dialog(): return
		result = self.delete_torrent(folder_id)
		if not result: return kodi_utils.notify_failed()
		self.clear_cache()
		kodi_utils.container_refresh()

	def cloud_airlock(self, folder_id, airlock_value):
		if airlock_value == 'false' and not kodi_utils.confirm_dialog(): return
		request_id, mediatype = folder_id.split(',')
		result = self.toggle_airlock(mediatype, request_id, airlock_value)
		if not result: return kodi_utils.notify_failed()
		self.clear_cache()
		kodi_utils.container_refresh()

	def parse_user_cloud(self, mediatype):
		string = 'pov_tb_user_cloud_%s' % mediatype
		items = cache_object(self.user_cloud, string, mediatype, 0.5)
		if not items: return []
		folders = []
		folders_append = folders.append
		for count, item in enumerate(items, 1):
			try:
				if not (item['download_finished'] and item['files']): continue
				cm = []
				cm_append = cm.append
				folder_id = '%s,%s' % (item['id'], mediatype)
				if item['airlocked']: airlock_value, func_str, res_str = 'false', _rem_str, airlock_str
				else: airlock_value, func_str, res_str = 'true', _add_str, folder_str
				display = '%02d | [B]%s[/B] | [I]%s [/I]' % (count, res_str, clean_file_name(item['name']).upper())
				url_params = {'mode': 'torbox.tb_browse_folder', 'id': folder_id}
				delete_params = {'mode': 'torbox.tb_delete', 'id': folder_id}
				airlock_params = {'mode': 'torbox.tb_airlock', 'id': folder_id, 'airlock': airlock_value}
				cm_append(('[B]%s %s[/B]' % (delete_str, folder_str.capitalize()), 'RunPlugin(%s)' % build_url(delete_params)))
				cm_append(('[B]%s %s[/B]' % (func_str, airlock_str.capitalize()), 'RunPlugin(%s)' % build_url(airlock_params)))
				url = build_url(url_params)
				listitem = make_listitem()
				listitem.setLabel(display)
				listitem.addContextMenuItems(cm)
				listitem.setArt(default_art)
				folders_append((url, listitem, True))
			except: pass
		return folders

	def parse_folder(self, mediatype, folder_id):
		string = 'pov_tb_user_cloud_%s_%s' % (mediatype, folder_id)
		items = cache_object(self.user_folder, string, [mediatype, folder_id], 0.5)
		if not items or not items['files']: return []
		files = []
		files_append = files.append
		for count, item in enumerate(items['files'], 1):
			try:
				if not item['short_name'].lower().endswith(extensions): continue
				cm = []
				cm_append = cm.append
				link = '%s,%s,%s' % (folder_id, item['id'], mediatype)
				name = clean_file_name(item['short_name']).upper()
				size = float(int(item['size']))/1073741824
				display = '%02d | [B]%s[/B] | %.2f GB | [I]%s [/I]' % (count, file_str, size, name)
				params = {'id': link, 'url': link, 'image': default_icon}
				params.update({'name': item['short_name'], 'scrape_provider': 'tb_cloud', 'direct_debrid_link': 'false'})
				url_params = {**params, 'mode': 'media_play'}
				down_file_params = {**params, 'mode': 'downloader', 'action': 'tb_cloud'}
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

class source(Debrid):
	scrape_provider = 'tb_cloud'
	def results(self, info):
		try:
			self.sources = []
			sources_append = self.sources.append
			if not enabled_debrids_check('tb'): return internal_results(self.scrape_provider, self.sources)
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
						if not (
							seas_ep_filter(season, episode, item['filename'])
							or # usenet obfuscation
							seas_ep_filter(season, episode, item['folder_name'])
						): continue
					elif any(x in normalized for x in extras_filtering_list): continue

					display_name = clean_file_name(item['filename']).replace('html', ' ')
					file_dl, size = item['link'], round(float(item['size'])/1073741824, 2)
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
			threads = []
			append = threads.append
			folders = 'usenet', 'webdl'
			for item in folders:
				append(i := Thread(target=self._scrape_folders, args=(item,)))
				i.start()
			self._scrape_folders('torrents')
			[i.join() for i in threads]
		except: pass

	def _scrape_folders(self, mediatype):
		try:
			results_append = self.scrape_results.append
			folder = self.user_cloud(mediatype)
			for item in folder:
				if not (item['download_finished'] and item['files']): continue
				for file in item['files']:
					try: file.update({
						'folder_name': item['name'], 'filename': file['short_name'],
						'link': '%s,%s,%s' % (item['id'], file['id'], mediatype)
					})
					except: pass
					else: results_append(file)
		except: pass

