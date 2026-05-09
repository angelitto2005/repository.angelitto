import sys
import json
from indexers.tmdb_api import base_url, tmdb_api_key, tmdb_keyword_id, tmdb_people_info, tmdb_company_id, tmdb_movies_title_year, tmdb_tv_title_year
from modules import kodi_utils, meta_lists
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
listitem_position = {
	'similar': 0, 'recommended': 0, 'year_start': 3, 'year_end': 4, 'include_genres': 5, 'exclude_genres': 6, 'include_keywords': 7,
	'exclude_keywords': 8, 'language': 9, 'region': 10, 'network': 10, 'companies': 11, 'rating': 11, 'certification': 12,
	'rating_votes': 12, 'rating_movie': 13, 'sort_by': 13, 'rating_votes_movie': 14, 'cast': 15, 'sort_by_movie': 16, 'adult': 17
}

class Discover:
	def __init__(self, params):
		self.view = 'view.main'
		self.mediatype, self.key = params.get('mediatype'), params.get('key')
		self.window_id = 'SALTS_%s_discover_params' % self.mediatype.upper() if self.mediatype else ''
		try: self.discover_params = json.loads(kodi_utils.get_property(self.window_id))
		except: self.discover_params = {}
		self.tmdb_api = tmdb_api_key()

	def movie(self):
		if not 'mediatype' in self.discover_params: self._set_default_params('movie')
		names = self.discover_params['search_name']
		self._add_dir({'mode': 'discover._clear_property', 'mediatype': 'movie', 'list_name': '[B]%s[/B]' % ls(32656).upper()})
		if not 'recommended' in names:
			self._add_dir({'mode': 'discover.similar_recommended', 'mediatype': 'movie', 'key': 'similar', 'list_name': _ln_ins % (ls(32451), ls(32592), names.get('similar', ''))})
		if not 'similar' in names:
			self._add_dir({'mode': 'discover.similar_recommended', 'mediatype': 'movie', 'key': 'recommended', 'list_name': _ln_ins % (ls(32451), ls(32593), names.get('recommended', ''))})
		if not any(i in names for i in ('similar', 'recommended')):
			for item in (
				('discover.year_start', base_str % ('%s %s' % (ls(32543), ls(32654)), names.get('year_start', ''))),
				('discover.year_end', base_str % ('%s %s' % (ls(32543), ls(32655)), names.get('year_end', ''))),
				('discover.include_genres', base_str % (include_base_str % ls(32470), names.get('include_genres', ''))),
				('discover.exclude_genres', base_str % (exclude_base_str % ls(32470), names.get('exclude_genres', ''))),
				('discover.include_keywords', base_str % (include_base_str % ls(32657), names.get('include_keywords', ''))),
				('discover.exclude_keywords', base_str % (exclude_base_str % ls(32657), names.get('exclude_keywords', ''))),
				('discover.language', base_str % (ls(32658), names.get('language', ''))),
				('discover.region', base_str % (ls(32659), names.get('region', ''))),
				('discover.companies', base_str % (ls(32660), names.get('companies', ''))),
				('discover.certification', base_str % (ls(32473), names.get('certification', ''))),
				('discover.rating', base_str % ('%s %s' % (ls(32661), ls(32621)), names.get('rating', ''))),
				('discover.rating_votes', base_str % ('%s %s' % (ls(32661), ls(32663)), names.get('rating_votes', ''))),
				('discover.cast', base_str % (include_base_str % ls(32664), names.get('cast', ''))),
				('discover.sort_by', base_str % (ls(32067), names.get('sort_by', ''))),
				('discover.adult', base_str % (include_base_str % ls(32665), names.get('adult', ls(32860))))
			): self._add_dir({'mode': item[0], 'mediatype': 'movie', 'list_name': item[1]})
		self._add_defaults()
		self._end_directory()

	def tvshow(self):
		if not 'mediatype' in self.discover_params: self._set_default_params('tvshow')
		names = self.discover_params['search_name']
		self._add_dir({'mode': 'discover._clear_property', 'mediatype': 'tvshow', 'list_name': '[B]%s[/B]' % ls(32656).upper()})
		if not 'recommended' in names:
			self._add_dir({'mode': 'discover.similar_recommended', 'mediatype': 'tvshow', 'key': 'similar', 'list_name': _ln_ins % (ls(32451), ls(32592), names.get('similar', ''))})
		if not 'similar' in names:
			self._add_dir({'mode': 'discover.similar_recommended', 'mediatype': 'tvshow', 'key': 'recommended', 'list_name': _ln_ins % (ls(32451), ls(32593), names.get('recommended', ''))})
		if not any(i in names for i in ['similar', 'recommended']):
			for item in (
				('discover.year_start', base_str % ('%s %s' % (ls(32543), ls(32654)), names.get('year_start', ''))),
				('discover.year_end', base_str % ('%s %s' % (ls(32543), ls(32655)), names.get('year_end', ''))),
				('discover.include_genres', base_str % (include_base_str % ls(32470), names.get('include_genres', ''))),
				('discover.exclude_genres', base_str % (exclude_base_str % ls(32470), names.get('exclude_genres', ''))),
				('discover.include_keywords', base_str % (include_base_str % ls(32657), names.get('include_keywords', ''))),
				('discover.exclude_keywords', base_str % (exclude_base_str % ls(32657), names.get('exclude_keywords', ''))),
				('discover.language', base_str % (ls(32658), names.get('language', ''))),
				('discover.network', base_str % (ls(32480), names.get('network', ''))),
				('discover.rating', base_str % ('%s %s' % (ls(32661), ls(32621)), names.get('rating', ''))),
				('discover.rating_votes', base_str % ('%s %s' % (ls(32661), ls(32663)), names.get('rating_votes', ''))),
				('discover.sort_by', base_str % (ls(32067), names.get('sort_by', '')))
			): self._add_dir({'mode': item[0], 'mediatype': 'tvshow', 'list_name': item[1]})
		self._add_defaults()
		self._end_directory()

	def similar_recommended(self):
		key = self.key
		if self._action(key) in ('clear', None): return
		title = kodi_utils.dialog.input(heading_base % ls(32228))
		if not title: return
		if self.mediatype == 'movie': function = tmdb_movies_title_year
		else: function = tmdb_tv_title_year
		year = kodi_utils.dialog.numeric(0, heading_base % ('%s (%s)' % (ls(32543), ls(32669))))
		results = function(title, year)['results']
		if len(results) == 0: return kodi_utils.notification(32575)
		choice_list = []
		append = choice_list.append
		for item in results:
			title = item['title'] if self.mediatype == 'movie' else item['name']
			try: year = item['release_date'].split('-')[0] if self.mediatype == 'movie' else item['first_air_date'].split('-')[0]
			except: year = ''
			if year: rootname = '%s (%s)' % (title, year)
			else: rootname = title
			if item.get('poster_path'): icon = poster_url % item['poster_path']
			else: icon = poster
			append({'line1': rootname, 'line2': item['overview'], 'icon': icon, 'rootname': rootname, 'tmdb_id': str(item['id'])})
		heading = heading_base % ('%s %s' % (ls(32193), ls(32228)))
		kwargs = {'items': json.dumps(choice_list), 'heading': heading, 'multi_line': 'true'}
		values = kodi_utils.select_dialog([(i['tmdb_id'], i['rootname']) for i in choice_list], **kwargs)
		if values is None: return
		self._process(key, values)

	def include_keywords(self):
		key = 'include_keywords'
		if self._action(key) in ('clear', None): return
		current_key_ids = self.discover_params['search_string'].get(key, [])
		current_keywords = self.discover_params['search_name'].get(key, [])
		if not isinstance(current_key_ids, list):
			current_key_ids = current_key_ids.replace('&with_keywords=', '').split(', ')
		if not isinstance(current_keywords, list):
			current_keywords = current_keywords.split(', ')
		key_ids_append = current_key_ids.append
		key_words_append = current_keywords.append
		keyword = kodi_utils.dialog.input(heading_base % (include_base_str % ls(32657)))
		if keyword:
			try:
				result = tmdb_keyword_id(keyword)['results']
				keywords_choice = self._multiselect_dialog(heading_base % ('%s %s' % (ls(32193), ls(32657))), [i['name'].upper() for i in result], result)
				if keywords_choice != None:
					for i in keywords_choice:
						key_ids_append(str(i['id']))
						key_words_append(i['name'].upper())
			except: pass
			values = ('&with_keywords=%s' % ','.join([i for i in current_key_ids]), ', '.join([i for i in current_keywords]))
			self._process(key, values)

	def exclude_keywords(self):
		key = 'exclude_keywords'
		if self._action(key) in ('clear', None): return
		current_key_ids = self.discover_params['search_string'].get(key, [])
		current_keywords = self.discover_params['search_name'].get(key, [])
		if not isinstance(current_key_ids, list):
			current_key_ids = current_key_ids.split(', ')
		if not isinstance(current_keywords, list):
			current_keywords = current_keywords.split(', ')
		key_ids_append = current_key_ids.append
		key_words_append = current_keywords.append
		keyword = kodi_utils.dialog.input(heading_base % (exclude_base_str % ls(32657)))
		if keyword:
			try:
				result = tmdb_keyword_id(keyword)['results']
				keywords_choice = self._multiselect_dialog(heading_base % ('%s %s' % (ls(32193), ls(32657))), [i['name'].upper() for i in result], result)
				if keywords_choice != None:
					for i in keywords_choice:
						key_ids_append(str(i['id']))
						key_words_append(i['name'].upper())
			except: pass
			values = ('&without_keywords=%s' % ','.join([i for i in current_key_ids]), ', '.join([i for i in current_keywords]))
			self._process(key, values)

	def year_start(self):
		key = 'year_start'
		if self._action(key) in ('clear', None): return
		years = meta_lists.years()
		years_list = [str(i) for i in years]
		year_start = self._selection_dialog(years_list, years, heading_base % ('%s %s' % (ls(32654), ls(32543))))
		if year_start != None:
			if self.discover_params['mediatype'] == 'movie':
				value = 'primary_release_date.gte'
			else:
				value = 'first_air_date.gte'
			values = ('&%s=%s-01-01' % (value, str(year_start)), str(year_start))
			self._process(key, values)

	def year_end(self):
		key = 'year_end'
		if self._action(key) in ('clear', None): return
		years = meta_lists.years()
		years_list = [str(i) for i in years]
		year_end = self._selection_dialog(years_list, years, heading_base % ('%s %s' % (ls(32655), ls(32543))))
		if year_end != None:
			if self.discover_params['mediatype'] == 'movie':
				value = 'primary_release_date.lte'
			else:
				value = 'first_air_date.lte'
			values = ('&%s=%s-12-31' % (value, str(year_end)), str(year_end))
			self._process(key, values)

	def include_genres(self):
		key = 'include_genres'
		if self._action(key) in ('clear', None): return
		if self.discover_params['mediatype'] == 'movie': genres = meta_lists.movie_genres
		else: genres = meta_lists.tvshow_genres
		genre_list = [(k, v[0]) for k, v in sorted(genres.items())]
		genres_choice = self._multiselect_dialog(heading_base % (include_base_str % ls(32470)), [i[0] for i in genre_list], genre_list)
		if genres_choice != None:
			genre_ids = ','.join([i[1] for i in genres_choice])
			genre_names = ', '.join([i[0] for i in genres_choice])
			values = ('&with_genres=%s' % genre_ids, genre_names)
			self._process(key, values)

	def exclude_genres(self):
		key = 'exclude_genres'
		if self._action(key) in ('clear', None): return
		if self.discover_params['mediatype'] == 'movie': genres = meta_lists.movie_genres
		else: genres = meta_lists.tvshow_genres
		genre_list = [(k, v[0]) for k, v in sorted(genres.items())]
		genres_choice = self._multiselect_dialog(heading_base % (exclude_base_str % ls(32470)), [i[0] for i in genre_list], genre_list)
		if genres_choice != None:
			genre_ids = ','.join([i[1] for i in genres_choice])
			genre_names = ', '.join([i[0] for i in genres_choice])
			values = ('&without_genres=%s' % genre_ids, '/'.join(genre_names.split(', ')))
			self._process(key, values)

	def language(self):
		key = 'language'
		if self._action(key) in ('clear', None): return
		languages_list = meta_lists.languages
		language = self._selection_dialog([i[0] for i in languages_list], languages_list, heading_base % ls(32658))
		if language != None:
			values = ('&with_original_language=%s' % str(language[1]), str(language[1]).upper())
			self._process(key, values)

	def region(self):
		key = 'region'
		if self._action(key) in ('clear', None): return
		regions = meta_lists.regions
		region_names = [i['name'] for i in regions]
		region_codes = [i['code'] for i in regions]
		region = self._selection_dialog(region_names, region_codes, heading_base % ls(32659))
		if region != None:
			region_name = [i['name'] for i in regions if i['code'] == region][0]
			values = ('&region=%s' % region, region_name)
			self._process(key, values)

	def rating(self):
		key = 'rating'
		if self._action(key) in ('clear', None): return
		ratings = [i for i in range(1, 11)]
		ratings_list = [str(float(i)) for i in ratings]
		rating = self._selection_dialog(ratings_list, ratings, heading_base % ('%s %s' % (ls(32661), ls(32621))))
		if rating != None:
			values = ('&vote_average.gte=%s' % str(rating), str(float(rating)))
			self._process(key, values)

	def rating_votes(self):
		key = 'rating_votes'
		if self._action(key) in ('clear', None): return
		rating_votes = [i for i in range(0, 1001, 50)]
		rating_votes.pop(0)
		rating_votes.insert(0, 1)
		rating_votes_list = [str(i) for i in rating_votes]
		rating_votes = self._selection_dialog(rating_votes_list, rating_votes, heading_base % ('%s %s' % (ls(32661), ls(32663))))
		if rating_votes != None:
			values = ('&vote_count.gte=%s' % str(rating_votes), str(rating_votes))
			self._process(key, values)

	def certification(self):
		key = 'certification'
		if self._action(key) in ('clear', None): return
		certifications = meta_lists.movie_certifications
		certifications_list = [i.upper() for i in certifications]
		certification = self._selection_dialog(certifications_list, certifications, heading_base % ls(32473))
		if certification != None:
			values = ('&certification_country=US&certification=%s' % certification, certification.upper())
			self._process(key, values)

	def cast(self):
		key = 'cast'
		if self._action(key) in ('clear', None): return
		from modules.utils import safe_string, remove_accents
		query = kodi_utils.dialog.input(heading_base % ls(32664))
		if not query: return
		try: actors = tmdb_people_info(query)
		except: actors = None
		if not actors: return
		for item in actors:
			known_for_list = [i.get('title', 'NA') for i in item['known_for']]
			known_for_list = [i for i in known_for_list if not i == 'NA']
			item['icon'] = icon = profile_url % item['profile_path'] if item.get('profile_path') else people_icon
			item['line1'] = item['name']
			item['line2'] = ', '.join(known_for_list) if known_for_list else ''
		if len(actors) > 1:
			kwargs = {'items': json.dumps(actors), 'heading': heading_base % ls(32664), 'multi_line': 'true'}
			choice = kodi_utils.select_dialog(actors, **kwargs)
			if choice is None: return self._set_property()
			actor_id, actor_name = choice['id'], choice['name']
		else: actor_id, actor_name = [item['id'] for item in actors][0], [item['name'] for item in actors][0]
		if actor_id:
			values = ('&with_cast=%s' % str(actor_id), safe_string(remove_accents(actor_name)))
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
		if company:
			company_choice = None
			try:
				results = tmdb_company_id(company)
				if results['total_results'] == 0: return None
				if results['total_results'] == 1: company_choice = results['results']
				if not company_choice:
					results = results['results']
					company_choice = self._multiselect_dialog(heading_base % ls(32660), [i['name'].upper() for i in results], results)
				if company_choice != None:
					for i in company_choice:
						company_ids_append(str(i['id']))
						company_append(i['name'].upper())
				values = ('&with_companies=%s' % '|'.join([i for i in current_company_ids]), ', '.join([i for i in current_companies]))
				self._process(key, values)
			except: pass

	def sort_by(self):
		key = 'sort_by'
		if self._action(key) in ('clear', None): return
		if self.discover_params['mediatype'] == 'movie':
			sort_by_list = self._movies_sort()
		else:
			sort_by_list = self._tvshows_sort()
		sort_by_value = self._selection_dialog([i[0] for i in sort_by_list], [i[1] for i in sort_by_list], heading_base % ls(32067))
		if sort_by_value != None:
			sort_by_name = [i[0] for i in sort_by_list if i[1] == sort_by_value][0]
			values = (sort_by_value, sort_by_name)
			self._process(key, values)

	def adult(self):
		key = 'adult'
		include_adult = self._selection_dialog((ls(32859), ls(32860)), ('true', 'false'), heading_base % include_base_str % ls(32665))
		if include_adult != None:
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
		except:
			kodi_utils.notification(32574)

	def history(self):
		def _builder():
			for count, (data_id, item) in enumerate(data, 1):
				try:
					cm = []
					cm_append = cm.append
					item = eval(item)
					url_params = {'mode': item['mode'], 'action': item['action'], 'query': item['query'],
									'name': item['name'], 'iconImage': default_icon}
					display = '%s | %s' % (count, item['name'])
					url = build_url(url_params)
					remove_single_params = {'mode': 'discover_remove_from_history', 'data_id': data_id, 'silent': False}
					remove_all_params = {'mode': 'discover_remove_all_history', 'mediatype': mediatype, 'silent': True}
#					export_params = {'mode': 'navigator.adjust_main_lists', 'method': 'add_external', 'list_name': name, 'menu_item': json.dumps(url_params)}
					cm_append(('[B]%s[/B]' % remove_str, 'RunPlugin(%s)'% build_url(remove_single_params)))
					cm_append(('[B]%s[/B]' % clear_str, 'RunPlugin(%s)'% build_url(remove_all_params)))
#					cm_append(('[B]%s[/B]' % export_str, 'RunPlugin(%s)'% build_url(export_params)))
					listitem = make_listitem()
					listitem.setLabel(display)
					listitem.addContextMenuItems(cm)
					listitem.setArt({'icon': default_icon, 'poster': default_icon, 'thumb': default_icon, 'fanart': fanart, 'banner': default_icon})
					yield (url, listitem, True)
				except: pass
		__handle__ = int(sys.argv[1])
		mediatype = self.mediatype
		data = get_history(mediatype)
		item_list = list(_builder())
		kodi_utils.add_items(__handle__, item_list)
		self._end_directory()

	def help(self):
		return kodi_utils.show_text(heading_base % ls(32487), discover_help)

	def _set_default_params(self, mediatype):
		self._clear_property()
		url_mediatype = 'movie' if mediatype == 'movie' else 'tv'
		param_mediatype = 'Movies' if mediatype == 'movie' else 'TV Shows'
		self.discover_params['mediatype'] = mediatype
		self.discover_params['search_string'] = {
			'base': '%s/discover/%s?api_key=%s&language=en-US&page=%s' % (base_url, url_mediatype, self.tmdb_api, '%s'),
			'base_similar': '%s/%s/%s/similar?api_key=%s&language=en-US&page=%s' % (base_url, url_mediatype, '%s', self.tmdb_api, '%s'),
			'base_recommended': '%s/%s/%s/recommendations?api_key=%s&language=en-US&page=%s' % (base_url, url_mediatype, '%s', self.tmdb_api, '%s')
		}
		self.discover_params['search_name'] = {'mediatype': param_mediatype}
		self._set_property()

	def _add_defaults(self):
		if self.discover_params['mediatype'] == 'movie':
			mode = 'build_movie_list'
			action = 'tmdb_movies_discover'
		else:
			mode = 'build_tvshow_list'
			action = 'tmdb_tv_discover'
		name = self.discover_params.get('name', '...')
		query = self.discover_params.get('final_string', '')
		self._add_dir({'mode': mode, 'action': action, 'query': query, 'name': name, 'list_name': ls(32666) % name}, isFolder=True,
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

	def _end_directory(self):
		__handle__ = int(sys.argv[1])
		kodi_utils.set_content(__handle__, '')
		kodi_utils.end_directory(__handle__, cacheToDisc=False)
		kodi_utils.set_view_mode(self.view, '')

	def _selection_dialog(self, dialog_list, function_list, string):
		list_items = [{'line1': item, 'icon': default_icon} for item in dialog_list]
		kwargs = {'items': json.dumps(list_items), 'heading': string}
		return kodi_utils.select_dialog(function_list, **kwargs)

	def _multiselect_dialog(self, string, dialog_list, function_list=None, preselect= []):
		if not function_list: function_list = dialog_list
		list_items = [{'line1': item, 'icon': default_icon} for item in dialog_list]
		kwargs = {'items': json.dumps(list_items), 'heading': string, 'multi_choice': 'true', 'preselect': preselect}
		return kodi_utils.select_dialog(function_list, **kwargs)

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
		if 'year_start' in string_params: string += string_params['year_start']
		if 'year_end' in string_params: string += string_params['year_end']
		if 'include_genres' in string_params: string += string_params['include_genres']
		if 'exclude_genres' in string_params: string += string_params['exclude_genres']
		if 'include_keywords' in string_params: string += string_params['include_keywords']
		if 'exclude_keywords' in string_params: string += string_params['exclude_keywords']
		if 'companies' in string_params: string += string_params['companies']
		if 'language' in string_params: string += string_params['language']
		if 'region' in string_params: string += string_params['region']
		if 'rating' in string_params: string += string_params['rating']
		if 'rating_votes' in string_params: string += string_params['rating_votes']
		if 'certification' in string_params: string += string_params['certification']
		if 'cast' in string_params: string += string_params['cast']
		if 'network' in string_params: string += string_params['network']
		if 'adult' in string_params: string += string_params['adult']
		if 'sort_by' in string_params: string += string_params['sort_by']
		self.discover_params['final_string'] = string

	def _build_name(self):
		values = self.discover_params['search_name']
		mediatype = values['mediatype']
		db_name = ls(32028) if mediatype == 'Movies' else ls(32029)
		name = '[B]%s[/B] ' % db_name
		if 'similar' in values:
			name += '| %s %s' % (ls(32672), values['similar'])
			self.discover_params['name'] = name
			return
		if 'recommended' in values:
			name += '| %s %s' % (ls(32673), values['recommended'])
			self.discover_params['name'] = name
			return
		if 'year_start' in values:
			if 'year_end' in values and not values['year_start'] == values['year_end']: name += '| %s' % values['year_start']
			else: name += '| %s ' % values['year_start']
		if 'year_end' in values:
			if 'year_start' in values:
				if not values['year_start'] == values['year_end']: name += '-%s ' % values['year_end']
			else: name += '| %s ' % values['year_end']
		if 'language' in values: name += '| %s ' % values['language']
		if 'region' in values: name += '| %s ' % values['region']
		if 'network' in values: name += '| %s ' % values['network']
		if 'include_genres' in values:
			name += '| %s ' % values['include_genres']
			if 'exclude_genres' in values: name += '(%s %s) ' % (ls(32189).lower(), values['exclude_genres'])
		elif 'exclude_genres' in values: name += '| %s %s ' % (ls(32189).lower(), values['exclude_genres'])
		if 'companies' in values: name += '| %s ' % values['companies']
		if 'certification' in values: name += '| %s ' % values['certification']
		if 'rating' in values:
			name += '| %s+ ' % values['rating']
			if 'rating_votes' in values: name += '(%s) ' % values['rating_votes']
		elif 'rating_votes' in values: name += '| %s+ %s ' % (values['rating_votes'], ls(32623).lower())
		if 'cast' in values: name += '| %s %s ' % (ls(32664).lower(), values['cast'])
		if 'include_keywords' in values: name += '| %s %s: %s ' % (ls(32188).lower(), ls(32657).lower(), values['include_keywords'])
		if 'exclude_keywords' in values: name += '| %s %s: %s ' % (ls(32189).lower(), ls(32657).lower(), values['exclude_keywords'])
		if 'sort_by' in values: name += '| %s ' % values['sort_by']
		if 'adult' in values and values['adult'] == ls(32859): name += '| %s %s ' % (ls(32188).lower(), ls(32665).lower())
		self.discover_params['name'] = name

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

def get_history(mediatype):
	string = 'salts_discover_%s_%%' % mediatype
	dbcon = kodi_utils.database_connect(maincache_db)
	dbcur = dbcon.cursor()
	dbcur.execute("""SELECT id, data FROM maincache WHERE id LIKE ? ORDER BY rowid DESC""", (string,))
	history = dbcur.fetchall()
	return history

def set_history(mediatype, name, query):
	from caches.main_cache import MainCache
	from datetime import timedelta
	string = 'salts_discover_%s_%s' % (mediatype, query)
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

discover_help = (
"""
[COLOR orange][B]SALTS Discover[/B][/COLOR]

SALTS Discover is a feature that allows you to browse and/or export lists that you make yourself using the filter values you provide. Only the filters you wish to use need to be assigned a value, the rest can be left blank. Once you've set your desired filters, select 'Save & Browse Results' if you want to simply start looking through the list you have made or 'Menu Export' to place your new list in one of the SALTS Main Menus (Root, Movies or TV Shows). Your lists are saved for 7 days, and can be re-viewed by navigating into 'DISCOVER: History'. There are many different lists you could make using different filters, below are 2 examples:

  [B]EXAMPLE 1:[/B]
  You want to search for Comedy/Action Movies made in the 1980's that are PG Rated:
- Assign a "[B]Year Start[/B]" filter of "1980"
- Assign a "[B]Year End[/B]" filter of "1989"
- Assign a "[B]Include Genres[/B]" filter of "Action, Comedy"
- Assign a "[B]Certification[/B]" filter of "PG"
- Select "[B]Browse Results[/B]" to immediately see the results or "[B]Menu Export[/B]" to export the
  list to SALTS Root Menu or SALTS Movies Menu etc

  [B]EXAMPLE 2:[/B]
  You want to search for Movies Similar to Avengers Endgame.
- Assign a "[B]Discover Recommended[/B]" Title of "Avengers Endgame"
- Assign a "[B]Discover Recommended[/B]" Year of "2019" or leave blank
- Choose from the titles presented for the correct Movie/TV Show
- Once a "Discover Recommended" has been set, the other filters are not available.
- Select "[B]Browse Results[/B]" to immediately see the results or "[B]Menu Export[/B]" to export the
  list to SALTS Root Menu or SALTS Movies Menu etc"""
)

