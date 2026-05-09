import json
from threading import Thread
from windows import BaseDialog
from indexers.tmdb_api import tmdb_people_info, tmdb_people_full_info, tmdb_image_base
from menus.images import Images
from modules import dialogs
from modules.utils import calculate_age
from modules.kodi_utils import media_path, notification, show_text, local_string as ls
from modules.settings import extras_enable_scrollbars, extras_exclude_non_acting, get_resolution
# from modules.kodi_utils import logger

fanart = BaseDialog.fanart
backup_thumbnail = media_path('box_office.png')
backup_cast_thumbnail = media_path('people.png')
roles_exclude = ('himself', 'herself', 'self', 'narrator', 'voice (voice)')
button_ids = (10, 11, 50)
genres_exclude = (10763, 10764, 10767)
gender_dict = {0: '', 1: ls(32844), 2: ls(32843), 3: ls(32466)}
more_from_movies_id, more_from_tvshows_id, imdb_videos_id, more_from_director_id = 2050, 2051, 2052, 2053

class People(BaseDialog):
	def __init__(self, *args, **kwargs):
		BaseDialog.__init__(self, args)
		self.control_id = None
		self.kwargs = kwargs
		self.set_starting_constants()
		self.make_person_data()
		self.set_properties()

	def onInit(self):
		Thread(target=self.make_imdb_videos).start()
		Thread(target=self.make_more_from, args=('movie',)).start()
		Thread(target=self.make_more_from, args=('tvshow',)).start()
		Thread(target=self.make_more_from, args=('director',)).start()

	def run(self):
		self.doModal()
		self.clearProperties()

	def onClick(self, controlID):
		self.control_id = None
		if controlID in button_ids:
			if controlID == 10:
				params = {'mode': 'people_image_results', 'actor_name': self.person_name, 'actor_id': self.person_id,
						'actor_image': self.person_image, 'page_no': 1, 'rolling_count': 0}
				Images().run(params)
			elif controlID == 11:
				params = {'mode': 'people_tagged_image_results', 'actor_name': self.person_name, 'actor_id': self.person_id}
				Images().run(params)
			elif controlID == 50:
				show_text(self.person_name, self.person_biography, font_size='large')
		else: self.control_id = controlID

	def onAction(self, action):
		if action in self.closing_actions: self.close()
		if not self.control_id: return
		if action in self.selection_actions:
			chosen_listitem = self.get_listitem(self.control_id)
			chosen_var = chosen_listitem.getProperty(self.item_action_dict[self.control_id])
			if self.control_id in (2050, 2051, 2053):
				if self.control_id in (2050, 2053): mediatype = 'movie'
				else: mediatype = 'tvshow'
				params = {'tmdb_id': chosen_var, 'mediatype': mediatype, 'is_widget': 'false'}
				return dialogs.extras_menu(params)
			elif self.control_id == 2052:
				params = json.loads(chosen_var)
				chosen = dialogs.imdb_videos_choice(params['videos'], params['thumb'])
				if not chosen: return
				return self.open_window(('windows.videoplayer', 'VideoPlayer'), 'videoplayer.xml', video=chosen)

	def make_person_data(self):
		if self.kwargs['query']:
			try: self.person_id = tmdb_people_info(self.kwargs['query'])[0]['id']
			except: notification(32760)
		else: self.person_id = self.kwargs['actor_id']
		person_info = tmdb_people_full_info(self.person_id)
		if person_info.get('biography') in ('', None): person_info = tmdb_people_full_info(self.person_id, 'en')
		self.person_name = person_info['name']
		image_path = person_info['profile_path']
		if image_path: self.person_image = tmdb_image_base % ('h632', image_path)
		else: self.person_image = backup_cast_thumbnail
		try: self.person_gender = gender_dict[person_info.get('gender')]
		except: self.person_gender = ''
		place_of_birth = person_info.get('place_of_birth')
		if place_of_birth: self.person_place_of_birth = place_of_birth
		else: self.person_place_of_birth = ''
		biography = person_info.get('biography')
		if biography: self.person_biography = biography
		else: self.person_biography = ls(32760)
		birthday = person_info.get('birthday')
		if birthday: self.person_birthday = birthday
		else: self.person_birthday = ''
		deathday = person_info.get('deathday')
		if deathday: self.person_deathday = deathday
		else: self.person_deathday = ''
		if self.person_deathday: self.person_age = calculate_age(self.person_birthday, '%Y-%m-%d', self.person_deathday)
		elif self.person_birthday: self.person_age = calculate_age(self.person_birthday, '%Y-%m-%d')
		else:self.person_age = ''
		self.imdb_id = person_info['imdb_id']
		more_from_data = person_info['combined_credits']
		acting_data = more_from_data['cast']
		directing_data = more_from_data['crew']
		self.movie_data = [i for i in acting_data if i['media_type'] == 'movie']
		self.tvshow_data = [i for i in acting_data if i['media_type'] == 'tv']
		self.director_data = [i for i in directing_data if i['job'].lower() == 'director']

	def make_more_from(self, mediatype):
		try:
			if mediatype == 'movie':
				list_type = mediatype
				_id = more_from_movies_id
				data = self.movie_data
				if self.exclude_non_acting:
					try: data = [i for i in data if not 99 in i['genre_ids'] and not i['character'].lower() in roles_exclude]
					except: pass
			elif mediatype == 'tvshow':
				list_type = mediatype
				_id = more_from_tvshows_id
				data = self.tvshow_data
				if self.exclude_non_acting:
					try: data = [i for i in data if not any(x in genres_exclude for x in i['genre_ids']) and not i['character'].lower() in roles_exclude]
					except: pass
			else:#director
				list_type = 'movie'
				_id = more_from_director_id
				data = self.director_data
			item_list = list(self.make_tmdb_listitems(data, list_type))
			self.setProperty('tikiskins.person.more_from_%s.number' % mediatype, '(x%02d)' % len(item_list))
			self.item_action_dict[_id] = 'tikiskins.person.tmdb_id'
			control = self.getControl(_id)
			control.addItems(item_list)
		except: pass

	def make_imdb_videos(self):
		def builder():
			for count, item in enumerate(data, 1):
				try:
					listitem = self.make_listitem()
					listitem.setProperty('tikiskins.person.name', '%01d. %s' % (count, item['title']))
					listitem.setProperty('tikiskins.person.thumbnail', item['poster'])
					listitem.setProperty('tikiskins.person.params', json.dumps({'videos': json.dumps(item['videos']), 'thumb': item['poster']}))
					yield listitem
				except: pass
		try:
			data = []
			item_list = list(builder())
			self.setProperty('tikiskins.person.imdb_videos.number', '(x%02d)' % len(item_list))
			self.item_action_dict[imdb_videos_id] = 'tikiskins.person.params'
			control = self.getControl(imdb_videos_id)
			control.addItems(item_list)
		except: pass

	def make_tmdb_listitems(self, data, mediatype):
		used_ids = []
		append = used_ids.append
		name_key = 'title' if mediatype == 'movie' else 'name'
		release_key = 'release_date' if mediatype == 'movie' else 'first_air_date'
		for item in sorted(data, key=lambda x: x.get(release_key) or '', reverse=True):
			try:
				tmdb_id = item['id']
				if tmdb_id in used_ids: continue
				listitem = self.make_listitem()
				poster_path = item['poster_path']
				if not poster_path: thumbnail = backup_thumbnail
				else: thumbnail = tmdb_image_base % (self.poster_resolution, poster_path)
				year = item.get(release_key)
				if year in (None, ''): year = 'N/A'
				else:
					try: year = year.split('-')[0]
					except: pass
				listitem.setProperty('tikiskins.person.name', item[name_key])
				listitem.setProperty('tikiskins.person.release_date', year)
				listitem.setProperty('tikiskins.person.vote_average', '%.1f' % item['vote_average'])
				listitem.setProperty('tikiskins.person.thumbnail', thumbnail)
				listitem.setProperty('tikiskins.person.tmdb_id', str(tmdb_id))
				append(tmdb_id)
				yield listitem
			except: pass

	def set_starting_constants(self):
		self.item_action_dict = {}
		self.enable_scrollbars = extras_enable_scrollbars()
		self.exclude_non_acting = extras_exclude_non_acting()
		self.poster_resolution = get_resolution()['poster']
		self.plugin_runner = 'RunPlugin(%s)'

	def set_properties(self):
		self.setProperty('tikiskins.person.name', self.person_name)
		self.setProperty('tikiskins.person.id', str(self.person_id))
		self.setProperty('tikiskins.person.image', self.person_image)
		self.setProperty('tikiskins.person.fanart', fanart)
		self.setProperty('tikiskins.person.gender', self.person_gender)
		self.setProperty('tikiskins.person.place_of_birth', self.person_place_of_birth)
		self.setProperty('tikiskins.person.biography', self.person_biography)
		self.setProperty('tikiskins.person.birthday', self.person_birthday)
		self.setProperty('tikiskins.person.deathday', self.person_deathday)
		self.setProperty('tikiskins.person.age', str(self.person_age))
		self.setProperty('tikiskins.person.enable_scrollbars', self.enable_scrollbars)

