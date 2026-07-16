import sys
import json
from datetime import timedelta
from types import MappingProxyType
from caches.main_cache import MainCache
from indexers import tmdb_api
from modules import kodi_utils, meta_lists
from modules.utils import safe_string
# logger = kodi_utils.logger

maincache_db = kodi_utils.maincache_db
ls, build_url, make_listitem = kodi_utils.local_string, kodi_utils.build_url, kodi_utils.make_listitem
fanart = kodi_utils.get_addoninfo('fanart')
poster = kodi_utils.media_path('box_office.png')
default_icon = kodi_utils.media_path('discover.png')
people_icon = kodi_utils.media_path('people.png')
poster_url, profile_url = 'https://image.tmdb.org/t/p/w780%s', 'https://image.tmdb.org/t/p/h632/%s'
base_str, heading_base = '[B]%s:[/B]  [I]%s[/I]', '%s %s - %s' % (ls(32036), ls(32451), '%s')
include_base_str, exclude_base_str = '%s %s' % (ls(32188), '%s'), '%s %s' % (ls(32189), '%s')
_ln_ins, menu_export_str, fold_export_str = '[B]%s %s:[/B]  [I]%s[/I]', 'MENU EXPORT', 'FOLDER EXPORT'
export_str, remove_str, clear_str = ls(32697), ls(32698), ls(32699)

class Discover:
	def __init__(self, params):
		self.view = 'view.main'
		self.mediatype, self.key = params.get('mediatype'), params.get('key')
		self.window_id = 'pov_%s_discover_params' % self.mediatype.upper() if self.mediatype else ''
		try: self.discover_params = json.loads(kodi_utils.get_property(self.window_id))
		except: self.discover_params = {}

	def router(self):
		if 'mediatype' not in self.discover_params: self._set_default_params(self.mediatype)
		self._make_directory(self.discover_params['search_name'], self.mediatype)
		self._add_defaults()
		__handle__ = int(sys.argv[1])
		kodi_utils.set_content(__handle__, '')
		kodi_utils.end_directory(__handle__, cacheToDisc=False)
		kodi_utils.set_view_mode(self.view, '')

	def similar_recommended(self):
		key = self.key
		if self._action(key) in ('clear', None): return
		title = kodi_utils.dialog.input(heading_base % ls(32228))
		if not title: return
		year = kodi_utils.dialog.numeric(0, heading_base % ('%s (%s)' % (ls(32543), ls(32669))))
		if self.mediatype == 'movie':
			name, premiered, function = 'title', 'release_date', tmdb_api.tmdb_movies_title_year
		else: name, premiered, function = 'name', 'first_air_date', tmdb_api.tmdb_tv_title_year
		results = function(title, year)['results']
		if len(results) == 0: return kodi_utils.notification(32575)
		choice_list = []
		append = choice_list.append
		for item in results:
			try: year = item[premiered].split('-')[0]
			except: year = ''
			title = item[name]
			rootname = '%s (%s)' % (title, year) if year else title
			icon = poster_url % item['poster_path'] if item.get('poster_path') else poster
			append({'line1': rootname, 'line2': item['overview'], 'icon': icon, 'rootname': rootname, 'tmdb_id': str(item['id'])})
		heading = heading_base % ('%s %s' % (ls(32193), ls(32228)))
		kwargs = {'items': json.dumps(choice_list), 'heading': heading}
		values = kodi_utils.select_dialog([(i['tmdb_id'], i['rootname']) for i in choice_list], **kwargs)
		if values is None: return
		self._process(key, values)

	def _years(self, key, args):
		if self._action(key) in ('clear', None): return
		years = meta_lists.years()
		years_list = [str(i) for i in years]
		_year = self._selection_dialog(years_list, years, heading_base % ('%s %s' % (ls(args[0]), ls(32543))))
		if _year is None: return
		if self.discover_params['mediatype'] == 'movie': value = 'primary_release_date.%s' % args[1]
		else: value = 'first_air_date.%s' % args[1]
		values = (args[2] % (value, str(_year)), str(_year))
		self._process(key, values)

	def year_start(self):
		return self._years('year_start', (32654, 'gte', '&%s=%s-01-01'))

	def year_end(self):
		return self._years('year_end', (32655, 'lte', '&%s=%s-12-31'))

	def _genres(self, key, value):
		if self._action(key) in ('clear', None): return
		heading = {'include_genres': include_base_str, 'exclude_genres': exclude_base_str}[key]
		if self.discover_params['mediatype'] == 'movie': genres = meta_lists.movie_genres
		else: genres = meta_lists.tvshow_genres
		genre_list = [(k, v[0]) for k, v in sorted(genres.items())]
		genres_choice = self._multiselect_dialog(heading_base % (heading % ls(32470)), [i[0] for i in genre_list], genre_list)
		if not genres_choice: return
		genre_ids = ','.join([i[1] for i in genres_choice])
		genre_names = ', '.join([i[0] for i in genres_choice])
		values = (value + genre_ids, genre_names)
		self._process(key, values)

	def include_genres(self):
		return self._genres('include_genres', '&with_genres=')

	def exclude_genres(self):
		return self._genres('exclude_genres', '&without_genres=')

	def _keywords(self, key, value):
		if self._action(key) in ('clear', None): return
		current_key_ids = self.discover_params['search_string'].get(key, [])
		current_keywords = self.discover_params['search_name'].get(key, [])
		if not isinstance(current_key_ids, list):
			current_key_ids = current_key_ids.replace(value, '').split(', ')
		if not isinstance(current_keywords, list):
			current_keywords = current_keywords.split(', ')
		key_ids_append = current_key_ids.append
		key_words_append = current_keywords.append
		keyword = kodi_utils.dialog.input(heading_base % (include_base_str % ls(32657)))
		if not keyword: return
		try:
			result = tmdb_api.tmdb_keyword_id(keyword)['results']
			keywords_choice = self._multiselect_dialog(heading_base % ('%s %s' % (ls(32193), ls(32657))), [i['name'].upper() for i in result], result)
			if keywords_choice is None: return
			for i in keywords_choice:
				key_ids_append(str(i['id']))
				key_words_append(i['name'].upper())
		except: pass
		values = (value + ','.join([i for i in current_key_ids]), ', '.join([i for i in current_keywords]))
		self._process(key, values)

	def include_keywords(self):
		return self._keywords('include_keywords', '&with_keywords=')

	def exclude_keywords(self):
		return self._keywords('exclude_keywords', '&without_keywords=')

	def language(self):
		key = 'language'
		if self._action(key) in ('clear', None): return
		languages_list = [(k, v['iso']) for k, v in meta_lists.meta_languages.items()]
		language = self._selection_dialog([i[0] for i in languages_list], languages_list, heading_base % ls(32658))
		if language is None: return
		values = ('&with_original_language=%s' % str(language[1]), str(language[1]).upper())
		self._process(key, values)

	def rating(self):
		key = 'rating'
		if self._action(key) in ('clear', None): return
		ratings = [i for i in range(1, 11)]
		ratings_list = [str(float(i)) for i in ratings]
		rating = self._selection_dialog(ratings_list, ratings, heading_base % ('%s %s' % (ls(32661), ls(32621))))
		if rating is None: return
		values = ('&vote_average.gte=%s' % str(rating), str(float(rating)))
		self._process(key, values)

	def rating_votes(self):
		key = 'rating_votes'
		if self._action(key) in ('clear', None): return
		rating_votes = [1, *range(50, 1001, 50)]
		rating_votes_list = [str(i) for i in rating_votes]
		rating_votes = self._selection_dialog(rating_votes_list, rating_votes, heading_base % ('%s %s' % (ls(32661), ls(32663))))
		if rating_votes is None: return
		values = ('&vote_count.gte=%s' % str(rating_votes), str(rating_votes))
		self._process(key, values)

	def region(self):
		key = 'region'
		if self._action(key) in ('clear', None): return
		regions = tmdb_api.tmdb_region_ids()
		region_names = [i['name'] for i in regions]
		region_codes = [i['code'] for i in regions]
		region = self._selection_dialog(region_names, region_codes, heading_base % ls(32659))
		if region is None: return
		region_name = [i['name'] for i in regions if i['code'] == region][0]
		values = ('&region=%s' % region, region_name)
		self._process(key, values)

	def companies(self):
		key = 'companies'
		if self._action(key) in ('clear', None): return
		current_company_ids = self.discover_params['search_string'].get(key, [])
		current_companies = self.discover_params['search_name'].get(key, [])
		company_ids_append = current_company_ids.append
		company_append = current_companies.append
		if not isinstance(current_company_ids, list):
			current_company_ids = current_company_ids.replace('&with_companies=', '').split('|')
		if not isinstance(current_companies, list):
			current_companies = current_companies.split(', ')
		company = kodi_utils.dialog.input(heading_base % ls(32660))
		if not company: return
		try: companies = tmdb_api.tmdb_company_id(company)['results']
		except: companies = None
		if not companies: return kodi_utils.notification(32760)
		for item in companies:
			item['line1'] = item['name']
			item['line2'] = '%s (%s)' % (item['name'], item.get('origin_country') or 'N/A')
			item['icon'] = profile_url % item['logo_path'] if item.get('logo_path') else default_icon
		if len(companies) > 1:
			kwargs = {'items': json.dumps(companies), 'heading': heading_base % ls(32664), 'multi_choice': 'true'}
			company_choice = kodi_utils.select_dialog(companies, **kwargs)
			if company_choice is None: return self._set_property()
		else: company_choice = companies[0]
		for i in company_choice:
			company_ids_append(str(i['id']))
			company_append(i['name'].upper())
		values = ('&with_companies=%s' % '|'.join([i for i in current_company_ids]), ', '.join([i for i in current_companies]))
		self._process(key, values)

	def certification(self):
		key = 'certification'
		if self._action(key) in ('clear', None): return
		certifications = meta_lists.movie_certifications
		certifications_list = [i.upper() for i in certifications]
		certification = self._selection_dialog(certifications_list, certifications, heading_base % ls(32473))
		if certification is None: return
		values = ('&certification_country=US&certification=%s' % certification, certification.upper())
		self._process(key, values)

	def cast(self):
		key = 'cast'
		if self._action(key) in ('clear', None): return
		query = kodi_utils.dialog.input(heading_base % ls(32664))
		if not query: return
		try: actors = tmdb_api.tmdb_people_info(query)
		except: actors = None
		if not actors: return
		for item in actors:
			known_for_list = [i.get('title', 'NA') for i in item['known_for']]
			known_for_list = [i for i in known_for_list if i != 'NA']
			item['line1'] = item['name']
			item['line2'] = ', '.join(known_for_list) if known_for_list else ''
			item['icon'] = profile_url % item['profile_path'] if item.get('profile_path') else people_icon
		if len(actors) > 1:
			kwargs = {'items': json.dumps(actors), 'heading': heading_base % ls(32664)}
			choice = kodi_utils.select_dialog(actors, **kwargs)
			if choice is None: return self._set_property()
			actor_id, actor_name = choice['id'], choice['name']
		else: actor_id, actor_name = [(item['id'], item['name']) for item in actors][0]
		values = ('&with_cast=%s' % str(actor_id), safe_string(actor_name))
		self._process(key, values)

	def network(self):
		key = 'network'
		if self._action(key) in ('clear', None): return
		network_list = []
		append = network_list.append
		networks = sorted(meta_lists.networks, key=lambda k: k['name'])
		for item in networks:
			name = item['name']
			append({'line1': name, 'icon': item['logo'], 'name': name, 'id': item['id']})
		heading = heading_base % ls(32480)
		kwargs = {'items': json.dumps(network_list), 'heading': heading}
		choice = kodi_utils.select_dialog(network_list, **kwargs)
		if choice is None: return
		values = ('&with_networks=%s' % choice['id'], choice['name'])
		self._process(key, values)

	def sort_by(self):
		key = 'sort_by'
		if self._action(key) in ('clear', None): return
		if self.discover_params['mediatype'] == 'movie': sort_by_list = self._movies_sort()
		else: sort_by_list = self._tvshows_sort()
		sort_by_value = self._selection_dialog([i[0] for i in sort_by_list], [i[1] for i in sort_by_list], heading_base % ls(32067))
		if sort_by_value is None: return
		sort_by_name = [i[0] for i in sort_by_list if i[1] == sort_by_value][0]
		values = (sort_by_value, sort_by_name)
		self._process(key, values)

	def adult(self):
		key = 'adult'
		include_adult = self._selection_dialog((ls(32859), ls(32860)), ('true', 'false'), heading_base % include_base_str % ls(32665))
		if include_adult is None: return
		values = ('&include_adult=%s' % include_adult, include_adult.capitalize())
		self._process(key, values)

	def export(self):
		try:
			mediatype = self.discover_params['mediatype']
			query = self.discover_params['final_string']
			name = self.discover_params['name']
			set_history(mediatype, name, query)
			if mediatype == 'movie': final_params = {'mode': 'build_movie_list', 'action': 'tmdb_movies_discover'}
			else: final_params = {'mode': 'build_tvshow_list', 'action': 'tmdb_tv_discover'}
			final_params.update({'name': name, 'query': query, 'iconImage': 'discover.png'})
			if self.key == 'folder': mode = 'menu_editor.shortcut_folder_add_item'
			else: mode = 'menu_editor.add_external'
			url_params = {'mode': mode, 'name': name, 'menu_item': json.dumps(final_params), 'iconImage': 'discover.png'}
			kodi_utils.execute_builtin('RunPlugin(%s)' % build_url(url_params))
		except: kodi_utils.notification(32574)

	def history(self):
		return history(self.mediatype, self.view)

	def help(self):
		return kodi_utils.show_text(heading_base % ls(32487), help())

	def _set_default_params(self, mediatype):
		self._clear_property()
		if mediatype == 'movie': url_mediatype, param_mediatype = 'movie', 'Movies'
		else: url_mediatype, param_mediatype = 'tv', 'TV Shows'
		params = '?language=en-US&page=%s'
		base_url = tmdb_api.base_url
		search = {
			'base': '%s/discover/%s%s' % (base_url, url_mediatype, params),
			'base_similar': '%s/%s/%s/similar%s' % (base_url, url_mediatype, '%s', params),
			'base_recommended': '%s/%s/%s/recommendations%s' % (base_url, url_mediatype, '%s', params)
		}
		self.discover_params['mediatype'] = mediatype
		self.discover_params['search_name'] = {'mediatype': param_mediatype}
		self.discover_params['search_string'] =  search
		self._set_property()

	def _add_defaults(self):
		if self.discover_params['mediatype'] == 'movie': mode, action = 'build_movie_list', 'tmdb_movies_discover'
		else: mode, action = 'build_tvshow_list', 'tmdb_tv_discover'
		name = self.discover_params.get('name', '...')
		query = self.discover_params.get('final_string', '')
		self._add_dir({'mode': mode, 'action': action, 'query': query, 'name': name, 'list_name': ls(32666) % name},
					isFolder=True,
					icon=kodi_utils.media_path('search.png'))
		self._add_dir({'mode': 'discover.export', 'mediatype': self.mediatype, 'list_name': base_str % (menu_export_str, name)},
					icon=kodi_utils.media_path('item_jump.png'))
		self._add_dir({'mode': 'discover.export', 'mediatype': self.mediatype, 'list_name': base_str % (fold_export_str , name), 'key': 'folder'},
					icon=kodi_utils.media_path('folder.png'))

	def _action(self, key):
		dict_item = self.discover_params
		add_to_list = ('keyword', 'companies')
		action = ls(32602) if any(word in key for word in add_to_list) else ls(32668)
		if key in dict_item['search_name']:
			action = self._selection_dialog([action.capitalize(), ls(32671)], (action, 'clear'), heading_base % ls(32670))
		if action is None: return
		if action == 'clear':
			index = self._listitem_position(key)
			for k in ('search_string', 'search_name'): dict_item[k].pop(key, None)
			self._process(index=index)
		return action

	def _process(self, key=None, values=None, index=None):
		if key:
			index = self._listitem_position(key)
			self.discover_params['search_string'][key] = values[0]
			self.discover_params['search_name'][key] = values[1]
		self._build_string()
		self._build_name()
		self._set_property()
		kodi_utils.container_refresh()
		if index: kodi_utils.focus_index(index, 500)

	def _clear_property(self):
		kodi_utils.clear_property(self.window_id)
		self.discover_params = {}
		kodi_utils.container_refresh()

	def _set_property(self):
		return kodi_utils.set_property(self.window_id, json.dumps(self.discover_params))

	def _add_dir(self, params, isFolder=False, icon=None):
		__handle__ = int(sys.argv[1])
		icon = icon or default_icon
		list_name = params.get('list_name', '')
		url = build_url(params)
		listitem = make_listitem()
		listitem.setLabel(list_name)
		listitem.setArt({'icon': icon, 'poster': icon, 'thumb': icon, 'fanart': fanart, 'banner': icon})
		kodi_utils.add_item(__handle__, url, listitem, isFolder)

	def _make_directory(self, func, mediatype):
		self._add_dir({'mode': 'discover._clear_property', 'mediatype': mediatype, 'list_name': '[B]%s[/B]' % ls(32656).upper()})
		if 'recommended' not in func:
			list_name = _ln_ins % (ls(32451), ls(32592), func.get('similar', ''))
			self._add_dir({'mode': 'discover.similar_recommended', 'key': 'similar', 'mediatype': mediatype, 'list_name': list_name})
		if 'similar' not in func:
			list_name = _ln_ins % (ls(32451), ls(32593), func.get('recommended', ''))
			self._add_dir({'mode': 'discover.similar_recommended', 'key': 'recommended', 'mediatype': mediatype, 'list_name': list_name})
		if any(i in func for i in ('similar', 'recommended')): return
		menu = dict(FILTER)
		if mediatype == 'tvshow':
			for i in ('region', 'companies', 'certification', 'cast', 'adult'): menu.pop(i, None)
		else: menu.pop('network', None)
		for k, v in menu.items():
			if k == 'adult': list_name = base_str % (v, func.get(k, ls(32860)))
			else: list_name = base_str % (v, func.get(k, ''))
			self._add_dir({'mode': 'discover.%s' % k, 'mediatype': mediatype, 'list_name': list_name})

	def _selection_dialog(self, dialog_list, function_list, string):
		list_items = [{'line1': item, 'icon': default_icon} for item in dialog_list]
		kwargs = {'items': json.dumps(list_items), 'heading': string}
		return kodi_utils.select_dialog(function_list, multi_line='false', **kwargs)

	def _multiselect_dialog(self, string, dialog_list, function_list=None, preselect=None):
		if not function_list: function_list = dialog_list
		if not preselect: preselect = []
		list_items = [{'line1': item, 'icon': default_icon} for item in dialog_list]
		kwargs = {'items': json.dumps(list_items), 'heading': string, 'multi_choice': 'true', 'preselect': preselect}
		return kodi_utils.select_dialog(function_list, multi_line='false', **kwargs)

	def _build_string(self):
		string_params = self.discover_params['search_string']
		if 'similar' in string_params:
			string = string_params['base_similar'] % (string_params['similar'], '%s')
			self.discover_params['final_string'] = string
			return
		if 'recommended' in string_params:
			string = string_params['base_recommended'] % (string_params['recommended'], '%s')
			self.discover_params['final_string'] = string
			return
		string = string_params['base']
		for item in FILTER.keys():
			if item in string_params: string += string_params[item]
		self.discover_params['final_string'] = string

	def _build_name(self):
		values = self.discover_params['search_name']
		mediatype = values['mediatype']
		db_name = ls(32028) if mediatype == 'Movies' else ls(32029)
		name = ['[B]%s[/B]' % db_name]
		append = name.append
		if 'similar' in values:
			self.discover_params['name'] = '%s | %s %s' % (name[0], ls(32672), values['similar'])
			return
		if 'recommended' in values:
			self.discover_params['name'] = '%s | %s %s' % (name[0], ls(32673), values['recommended'])
			return
		if 'year_start' in values and 'year_end' in values:
			if values['year_start'] != values['year_end']:
				append('%s-%s' % (values['year_start'], values['year_end']))
			else: append(values['year_start'])
		elif 'year_start' in values:
			append(values['year_start'])
		elif 'year_end' in values:
			append(values['year_end'])
		if 'language' in values: append(values['language'])
		if 'region' in values: append(values['region'])
		if 'network' in values: append(values['network'])
		if 'include_genres' in values:
			genre_str = values['include_genres']
			if 'exclude_genres' in values:
				genre_str += ' (%s %s)' % (ls(32189).lower(), values['exclude_genres'])
			append(genre_str)
		elif 'exclude_genres' in values:
			append('%s %s' % (ls(32189).lower(), values['exclude_genres']))
		if 'companies' in values: append(values['companies'])
		if 'certification' in values: append(values['certification'])
		if 'rating' in values:
			rating_str = '%s+' % values['rating']
			if 'rating_votes' in values: rating_str += ' (%s)' % values['rating_votes']
			append(rating_str)
		elif 'rating_votes' in values:
			append('%s+ %s' % (values['rating_votes'], ls(32623).lower()))
		if 'cast' in values:
			append('%s %s' % (ls(32664).lower(), values['cast']))
		if 'include_keywords' in values:
			append('%s %s: %s' % (ls(32188).lower(), ls(32657).lower(), values['include_keywords']))
		if 'exclude_keywords' in values:
			append('%s %s: %s' % (ls(32189).lower(), ls(32657).lower(), values['exclude_keywords']))
		if 'sort_by' in values:
			append(values['sort_by'])
		if 'adult' in values and values['adult'] == ls(32859):
			append('%s %s' % (ls(32188).lower(), ls(32665).lower()))
		self.discover_params['name'] = ' | '.join(name)

	def _listitem_position(self, key):
		if self.mediatype == 'movie' and key in ('rating', 'rating_votes', 'sort_by'): key = '%s_movie' % key
		try: return listitem_position[key]
		except: return None

	def _movies_sort(self):
		pop_str, rel_str, rev_str, tit_str, rat_str, asc_str, desc_str = ls(32218), ls(32221), ls(32626), ls(32228), ls(32621), ls(32224), ls(32225)
		return [
			('%s (%s)' % (pop_str, asc_str), '&sort_by=popularity.asc'),            ('%s (%s)' % (pop_str, desc_str), '&sort_by=popularity.desc'),
			('%s (%s)' % (rel_str, asc_str), '&sort_by=primary_release_date.asc'),  ('%s (%s)' % (rel_str, desc_str), '&sort_by=primary_release_date.desc'),
			('%s (%s)' % (rev_str, asc_str), '&sort_by=revenue.asc'),               ('%s (%s)' % (rev_str, desc_str), '&sort_by=revenue.desc'),
			('%s (%s)' % (tit_str, asc_str), '&sort_by=original_title.asc'),        ('%s (%s)' % (tit_str, desc_str), '&sort_by=original_title.desc'),
			('%s (%s)' % (rat_str, asc_str), '&sort_by=vote_average.asc'),          ('%s (%s)' % (rat_str, desc_str), '&sort_by=vote_average.desc')
		]

	def _tvshows_sort(self):
		pop_str, prem_str, rat_str, asc_str, desc_str = ls(32218), ls(32620), ls(32621), ls(32224), ls(32225)
		return [
			('%s (%s)' % (pop_str, asc_str), '&sort_by=popularity.asc'),       ('%s (%s)' % (pop_str, desc_str), '&sort_by=popularity.desc'),
			('%s (%s)' % (prem_str, asc_str), '&sort_by=first_air_date.asc'),  ('%s (%s)' % (prem_str, desc_str), '&sort_by=first_air_date.desc'),
			('%s (%s)' % (rat_str, asc_str), '&sort_by=vote_average.asc'),     ('%s (%s)' % (rat_str, desc_str), '&sort_by=vote_average.desc')
		]

FILTER = MappingProxyType({
	'year_start': '%s %s' % (ls(32543), ls(32654)),      'year_end': '%s %s' % (ls(32543), ls(32655)),
	'include_genres': include_base_str % ls(32470),      'exclude_genres': exclude_base_str % ls(32470),
	'include_keywords': include_base_str % ls(32657),    'exclude_keywords': exclude_base_str % ls(32657),
	'language': ls(32658),                               'region': ls(32659),
	'companies': ls(32660),                              'certification': ls(32473),
	'cast': include_base_str % ls(32664),                'network': ls(32480),
	'rating': '%s %s' % (ls(32661), ls(32621)),          'rating_votes': '%s %s' % (ls(32661), ls(32663)),
	'sort_by': ls(32067),                                'adult': include_base_str % ls(32665)
})

listitem_position = {
	'similar': 0,             'recommended': 0,          'year_start': 3,
	'year_end': 4,            'include_genres': 5,       'exclude_genres': 6,
	'include_keywords': 7,    'exclude_keywords': 8,     'language': 9,
	'region': 10,             'network': 10,             'companies': 11,
	'rating': 11,             'certification': 12,       'rating_votes': 12,
	'rating_movie': 13,       'sort_by': 13,             'rating_votes_movie': 14,
	'cast': 15,               'sort_by_movie': 16,       'adult': 17
}

def history(mediatype, view_mode):
	data = get_history(mediatype)
	item_list = []
	for count, (data_id, item) in enumerate(data, 1):
		try:
			cm = []
			cm_append = cm.append
			item = eval(item)
			url_params = {'mode': item['mode'], 'action': item['action'], 'query': item['query'], 'name': item['name'], 'iconImage': default_icon}
			display = '%s | %s' % (count, item['name'])
			url = build_url(url_params)
			remove_one_params = {'mode': 'discover_remove_from_history', 'data_id': data_id, 'silent': False}
			remove_all_params = {'mode': 'discover_remove_all_history', 'mediatype': mediatype, 'silent': True}
			cm_append(('[B]%s[/B]' % remove_str, 'RunPlugin(%s)'% build_url(remove_one_params)))
			cm_append(('[B]%s[/B]' % clear_str, 'RunPlugin(%s)'% build_url(remove_all_params)))
			listitem = make_listitem()
			listitem.setLabel(display)
			listitem.addContextMenuItems(cm)
			listitem.setArt({'icon': default_icon, 'poster': default_icon, 'thumb': default_icon, 'fanart': fanart, 'banner': default_icon})
			item_list.append((url, listitem, True))
		except: pass
	__handle__ = int(sys.argv[1])
	kodi_utils.add_items(__handle__, item_list)
	kodi_utils.set_content(__handle__, '')
	kodi_utils.end_directory(__handle__, cacheToDisc=False)
	kodi_utils.set_view_mode(view_mode, '')

def get_history(mediatype):
	string = 'pov_discover_%s_%%' % mediatype
	dbcon = kodi_utils.database_connect(maincache_db)
	dbcur = dbcon.cursor()
	dbcur.execute("""SELECT id, data FROM maincache WHERE id LIKE ? ORDER BY rowid DESC""", (string,))
	history = dbcur.fetchall()
	return history

def set_history(mediatype, name, query):
	string = 'pov_discover_%s_%s' % (mediatype, query)
	maincache = MainCache()
	cache = maincache.get(string)
	if cache: return
	if mediatype == 'movie':
		mode = 'build_movie_list'
		action = 'tmdb_movies_discover'
	else:
		mode = 'build_tvshow_list'
		action = 'tmdb_tv_discover'
	data = {'mode': mode, 'action': action, 'name': name, 'query': query}
	maincache.set(string, data, expiration=timedelta(days=7))

def remove_from_history(params):
	dbcon = kodi_utils.database_connect(maincache_db, isolation_level=None)
	dbcur = dbcon.cursor()
	dbcur.execute("""PRAGMA synchronous = OFF""")
	dbcur.execute("""PRAGMA journal_mode = OFF""")
	dbcur.execute("""DELETE FROM maincache WHERE id = ?""", (params['data_id'],))
	kodi_utils.clear_property(params['data_id'])
	kodi_utils.container_refresh()
	if not params['silent']: kodi_utils.notification(32576)

def remove_all_history(params):
	mediatype = params['mediatype']
	if not kodi_utils.confirm_dialog(): return
	all_history = get_history(mediatype)
	for item in (i[0] for i in all_history):
		remove_from_history({'data_id': item, 'silent': True})
	kodi_utils.notification(32576)

def help(): return (
"""
[COLOR dodgerblue][B]POV Discover[/B][/COLOR]

POV Discover is a feature that allows you to browse and/or export lists that you make yourself using the filter values you provide. Only the filters you wish to use need to be assigned a value, the rest can be left blank. Once you've set your desired filters, select 'Save & Browse Results' if you want to simply start looking through the list you have made or 'Menu Export' to place your new list in one of the POV Main Menus (Root, Movies or TV Shows). Your lists are saved for 7 days, and can be re-viewed by navigating into 'DISCOVER: History'. There are many different lists you could make using different filters, below are 2 examples:

  [B]EXAMPLE 1:[/B]
  You want to search for Comedy/Action Movies made in the 1980's that are PG Rated:
- Assign a "[B]Year Start[/B]" filter of "1980"
- Assign a "[B]Year End[/B]" filter of "1989"
- Assign a "[B]Include Genres[/B]" filter of "Action, Comedy"
- Assign a "[B]Certification[/B]" filter of "PG"
- Select "[B]Browse Results[/B]" to immediately see the results or "[B]Menu Export[/B]" to export the
  list to POV Root Menu or POV Movies Menu etc

  [B]EXAMPLE 2:[/B]
  You want to search for Movies Similar to Avengers Endgame.
- Assign a "[B]Discover Recommended[/B]" Title of "Avengers Endgame"
- Assign a "[B]Discover Recommended[/B]" Year of "2019" or leave blank
- Choose from the titles presented for the correct Movie/TV Show
- Once a "Discover Recommended" has been set, the other filters are not available.
- Select "[B]Browse Results[/B]" to immediately see the results or "[B]Menu Export[/B]" to export the
  list to POV Root Menu or POV Movies Menu etc"""
)

