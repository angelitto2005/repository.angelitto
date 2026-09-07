from indexers.easynews_api import EasyNewsAPI as Debrid
from modules import kodi_utils, source_utils
from modules.settings import filter_by_name, easynews_language_filter
# from modules.kodi_utils import logger

internal_results, check_title = source_utils.internal_results, source_utils.check_title
clean_file_name, clean_title = source_utils.clean_file_name, source_utils.clean_title
get_file_info, seas_ep_filter = source_utils.get_file_info, source_utils.seas_ep_filter
ls, build_url, make_listitem = kodi_utils.local_string, kodi_utils.build_url, kodi_utils.make_listitem
down_str = ls(32747)
fanart = kodi_utils.get_addoninfo('fanart')
default_icon = kodi_utils.media_path('easynews.png')

def search_easynews(params):
	def _builder():
		for count, item in enumerate(files, 1):
			try:
				cm = []
				item_get = item.get
				url_dl = item_get('url_dl')
				thumbnail = item_get('thumbnail', default_icon)
				name = clean_file_name(item_get('name')).upper()
				size = str(round(float(int(item_get('rawSize')))/1073741824, 1))
				display = '%02d | [B]%s GB[/B] | [I]%s [/I]' % (count, size, name)
				params = {'id': url_dl, 'url': url_dl, 'image': default_icon}
				params.update({'name': item_get('name'), 'scrape_provider': 'easynews'})
				url = build_url({**params, 'mode': 'media_play'})
				down_file_params = {**params, 'mode': 'downloader', 'action': 'easynews_cloud'}
				cm.append((down_str,'RunPlugin(%s)' % build_url(down_file_params)))
				listitem = make_listitem()
				listitem.setLabel(display)
				listitem.addContextMenuItems(cm)
				listitem.setArt({'icon': thumbnail, 'poster': thumbnail, 'thumb': thumbnail, 'fanart': fanart, 'banner': default_icon})
				yield (url, listitem, False)
			except: pass
	search_name = clean_file_name(params.get('query'))
	files = Debrid().search(search_name)
	__handle__ = int(kodi_utils.argv1())
	kodi_utils.add_items(__handle__, list(_builder()))
	kodi_utils.set_content(__handle__, 'files')
	kodi_utils.end_directory(__handle__)
	kodi_utils.set_view_mode('view.premium')

def account_info(params):
	from datetime import datetime
	from modules.utils import jsondate_to_datetime
	try:
		kodi_utils.show_busy_dialog()
		account_info, usage_info = Debrid().account_info()
		if not account_info or not usage_info: return kodi_utils.notify_error()
		body = []
		append = body.append
		expires = jsondate_to_datetime(account_info[2], '%Y-%m-%d')
		days_remaining = (expires - datetime.today()).days
		append(ls(32755) % account_info[0])
		append(ls(32758) % account_info[1])
		append(ls(32757) % account_info[3])
		append('%s %s' % (ls(32772), usage_info[2].replace('years', ls(32472))))
		append(ls(32750) % expires.date() if hasattr(expires, 'date') else expires)
		append(ls(32751) % days_remaining)
		append(ls(32761) % usage_info[0].replace('Gigs', 'GB'))
		append(ls(32762) % usage_info[1].replace('Gigs', 'GB'))
		kodi_utils.hide_busy_dialog()
		return kodi_utils.show_text('Easynews'.upper(), '[CR]'.join(body), font_size='large')
	except: kodi_utils.hide_busy_dialog()

class source(Debrid):
	scrape_provider = 'easynews'
	def results(self, info):
		try:
			self.sources = []
			sources_append = self.sources.append
			filter_lang, lang_filters = easynews_language_filter()
			title, season, episode = info.get('title'), info.get('season'), info.get('episode')
			search_title = clean_file_name(title).replace('&', 'and')
			if season: query = '%s S%02dE%02d' % (search_title, season, episode)
			else: query = '%s %d' % (search_title, int(info.get('year')))
			if not filter_by_name(self.scrape_provider): self.aliases = None
			else: self.aliases = source_utils.get_aliases_titles(info.get('aliases', []))
			self.scrape_results = self.search(query, info.get('expiry_times')[0])
			if not self.scrape_results: return internal_results(self.scrape_provider, self.sources)
			for item in self.scrape_results:
				try:
					if filter_lang and not any(i in lang_filters for i in item['language']) : continue
					if not check_title(title, item['name'], self.aliases): continue
					if season:
						if not seas_ep_filter(season, episode, item['name']): continue
					normalized = clean_title(item['name'])

					display_name = clean_file_name(item['name']).replace('html', ' ')
					file_dl, size = item['url_dl'], round(float(int(item['rawSize']))/1073741824, 2)
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

