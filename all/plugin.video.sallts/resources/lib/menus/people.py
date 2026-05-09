import sys
from urllib.parse import unquote
from windows import open_window
from indexers.tmdb_api import tmdb_people_info, tmdb_image_base
from menus.images import Images
from modules import kodi_utils, settings
# from modules.kodi_utils import logger

KODI_VERSION = kodi_utils.get_kodi_version()
ls, build_url, make_listitem = kodi_utils.local_string, kodi_utils.build_url, kodi_utils.make_listitem
fanart_empty = kodi_utils.get_addoninfo('fanart')
poster_empty = kodi_utils.media_path('people.png')
gender_dict = {0: '', 1: ls(32844), 2: ls(32843), 3: ls(32466)}

def popular_people():
	Images().run({'mode': 'popular_people_image_results', 'page_no': 1})

def person_data_dialog(params):
	if 'query' in params: query = unquote(params['query'])
	else: query = None
	open_window(
		('windows.people', 'People'),
		'people.xml',
		query=query,
		actor_id=params.get('actor_id'),
		actor_name=params.get('actor_name'),
		actor_image=params.get('actor_image')
	)

def person_search(query):
	def _builder():
		for item in actors:
			try:
				name, gender = '%s' % item['name'], gender_dict[item['gender']]
				if not item['name'] == item['original_name']: name += ' - %s' % item['original_name']
				if gender: name += ' (%s)' % gender
				known_for_list = item['known_for']
				plot = '[CR]'.join(i['title'] for i in known_for_list if 'title' in i and i['title'])
				fanart = (tmdb_image_base % (image_resolution['fanart'], i['backdrop_path']) for i in known_for_list if i['backdrop_path'])
				fanart = next(fanart, fanart_empty)
				poster = (tmdb_image_base % (image_resolution['poster'], i['poster_path']) for i in known_for_list if i['poster_path'])
				poster = next(poster, poster_empty)
				icon = tmdb_image_base % (image_resolution['poster'], item['profile_path']) if item['profile_path'] else poster
				url_params = build_url({'mode': 'person_data_dialog', 'actor_id': item['id'], 'actor_name': item['name'], 'actor_image': icon})
				listitem = make_listitem()
				listitem.setLabel(name)
				listitem.setArt({'icon': icon, 'poster': icon, 'thumb': icon, 'fanart': fanart, 'banner': icon})
				listitem.setInfo('video', {'plot': plot}) if KODI_VERSION < 20 else listitem.getVideoInfoTag().setPlot(plot)
				yield (url_params, listitem, False)
			except: pass
	__handle__ = int(sys.argv[1])
	image_resolution = settings.get_resolution()
	try: actors = tmdb_people_info(query)
	except: actors = []
	kodi_utils.add_items(__handle__, list(_builder()))
	kodi_utils.set_category(__handle__, query)
	kodi_utils.set_content(__handle__, 'artists')
	kodi_utils.end_directory(__handle__)

