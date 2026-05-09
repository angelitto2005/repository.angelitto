import sys
from urllib.parse import unquote
from datetime import timedelta
from caches.main_cache import MainCache
from modules import kodi_utils, settings
# from modules.kodi_utils import logger

ls, build_url, make_listitem = kodi_utils.local_string, kodi_utils.build_url, kodi_utils.make_listitem
search_icon = kodi_utils.media_path('search_history.png')
default_icon = kodi_utils.media_path('search.png')
remove_str, search_str, hist_str, clear_str = ls(32698), ls(32450), ls(32486), ls(32699)
new_search_str = '[B]%s %s...[/B]' % (ls(32857).upper(), search_str.upper())
mode_dict, query_dict = {
	'movie': ('movie_queries', {'mode': 'get_search_term', 'mediatype': 'movie'}),
	'tvshow': ('tvshow_queries', {'mode': 'get_search_term', 'mediatype': 'tv_show'}),
	'people': ('people_queries', {'mode': 'get_search_term', 'search_type': 'people'}),
	'tmdb_collections': ('tmdb_collections_queries', {'mode': 'get_search_term', 'search_type': 'tmdb_collections', 'mediatype': 'movie'})
}, {
	'people': ('people_queries', {'mode': 'person_search'}),
	'tmdb_collections': ('tmdb_collections_queries', {'mode': 'build_movie_list', 'action': 'tmdb_movies_search_collections'})
}

def search_history(params):
	def _builder():
		for query in contents:
			try:
				cm = []
				url_params['query'] = query
				display = '[B]%s:[/B] [I]%s[/I]' % (hist_str.upper(), query)
				url = build_url(url_params)
				cm.append(('[B]%s[/B]' % remove_str, 'RunPlugin(%s)' % build_url({'mode': 'remove_from_history', 'setting_id': setting_id, 'query': query})))
				cm.append(('[B]%s[/B]' % clear_str, 'RunPlugin(%s)' % build_url({'mode': 'clear_search_history', 'setting_id': setting_id, 'query': query})))
				listitem = make_listitem()
				listitem.setLabel(display)
				listitem.setArt({'icon': search_icon, 'poster': search_icon, 'thumb': search_icon, 'fanart': fanart, 'banner': search_icon})
				listitem.addContextMenuItems(cm)
				yield (url, listitem, False)
			except: pass
	__handle__, fanart = int(sys.argv[1]), settings.addon_fanart()
	setting_id, action_dict = mode_dict[params['action']]
	url_params = dict(action_dict)
	kodi_utils.add_dir(__handle__, action_dict, new_search_str, iconImage=default_icon, isFolder=False)
	contents = MainCache().get(setting_id)
	if contents: kodi_utils.add_items(__handle__, list(_builder()))
	kodi_utils.set_category(__handle__, params.get('name'))
	kodi_utils.set_content(__handle__, '')
	kodi_utils.end_directory(__handle__)
	kodi_utils.set_view_mode('view.main', '')

def get_search_term(params):
	kodi_utils.close_all_dialog()
	mediatype = params.get('mediatype', '')
	search_type = params.get('search_type', 'media_title')
	params_query = params.get('query', '')
	if not search_type in query_dict:
		if mediatype == 'movie':
			string, url_params = 'movie_queries', {'mode': 'build_movie_list', 'action': 'tmdb_movies_search'}
		else: string, url_params = 'tvshow_queries', {'mode': 'build_tvshow_list', 'action': 'tmdb_tv_search'}
	else: string, url_params = query_dict[search_type]
	query = params_query or kodi_utils.dialog.input('SALTS')
	if not query.strip(): return
	query = unquote(query)
	add_to_search_history(query, string)
	url_params['query'] = query
	if kodi_utils.external_browse():
		return kodi_utils.execute_builtin('ActivateWindow(Videos,%s,return)' % kodi_utils.build_url(url_params))
	return kodi_utils.execute_builtin('Container.Update(%s)' % kodi_utils.build_url(url_params))

def add_to_search_history(search_name, search_list):
	try:
		result = []
		maincache = MainCache()
		cache = maincache.get(search_list)
		if cache: result = cache
		if search_name in result: result.remove(search_name)
		result.insert(0, search_name)
		result = result[:50]
		maincache.set(search_list, result, expiration=timedelta(days=365))
	except: pass

def remove_from_search_history(params):
	try:
		maincache = MainCache()
		result = maincache.get(params['setting_id'])
		result.remove(params.get('query'))
		maincache.set(params['setting_id'], result, expiration=timedelta(days=365))
		kodi_utils.notification(32576)
		kodi_utils.container_refresh()
	except: pass

def clear_search_history(params):
	try:
		MainCache().delete(params['setting_id'])
		kodi_utils.notification(32576)
		kodi_utils.container_refresh()
	except: pass

