import sys
from debrids.easynews_api import EasyNewsAPI as EasyNews
from modules import kodi_utils
from modules.source_utils import clean_file_name
# from modules.kodi_utils import logger

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
	files = EasyNews().search(search_name)
	__handle__ = int(sys.argv[1])
	kodi_utils.add_items(__handle__, list(_builder()))
	kodi_utils.set_content(__handle__, 'files')
	kodi_utils.end_directory(__handle__)
	kodi_utils.set_view_mode('view.premium')

def account_info(params):
	from datetime import datetime
	from modules.utils import jsondate_to_datetime
	try:
		kodi_utils.show_busy_dialog()
		account_info, usage_info = EasyNews().account()
		if not account_info or not usage_info: return kodi_utils.ok_dialog(text=32574)
		body = []
		append = body.append
		expires = jsondate_to_datetime(account_info[2], '%Y-%m-%d')
		days_remaining = (expires - datetime.today()).days
		append(ls(32755) % account_info[0])
		append(ls(32758) % account_info[1])
		append(ls(32757) % account_info[3])
		append('%s %s' % (ls(32772), usage_info[2].replace('years', ls(32472))))
		append(ls(32750) % expires)
		append(ls(32751) % days_remaining)
		append(ls(32761) % usage_info[0].replace('Gigs', 'GB'))
		append(ls(32762) % usage_info[1].replace('Gigs', 'GB'))
		kodi_utils.hide_busy_dialog()
		return kodi_utils.show_text(ls(32070).upper(), '\n\n'.join(body), font_size='large')
	except: kodi_utils.hide_busy_dialog()

