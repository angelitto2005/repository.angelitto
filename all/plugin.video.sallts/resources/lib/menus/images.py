import os
import json
from threading import Thread
from windows import open_window
from indexers.tmdb_api import tmdb_people_full_info, tmdb_popular_people, tmdb_image_base
from indexers.imdb_api import people_get_imdb_id, imdb_tagged_images
from modules.kodi_utils import media_path, notification, set_property, make_listitem, list_dirs, delete_file
# from modules.kodi_utils import logger

class Images:
	def run(self, params):
		self.params = params
		self.mode = self.params.pop('mode')
		if   self.mode == 'people_image_results': self.people_image_results()
		elif self.mode == 'people_tagged_image_results': self.people_tagged_image_results()
		elif self.mode == 'popular_people_image_results': self.popular_people_image_results()
		elif self.mode == 'browser_image': self.browser_image(params['folder_path'])
		elif self.mode == 'slideshow_image': return self.slideshow_image()
		elif self.mode == 'delete_image': return self.delete_image()
		if len(self.list_items) == 0 and not self.params.get('in_progress') == 'true':
			return notification(32490)
		if not 'in_progress' in params: self.open_window_xml()
		else: return self.list_items, self.next_page_params

	def open_window_xml(self):
		open_window(
			('windows.imageviewer', 'ThumbImageViewer'),
			'thumbviewer.xml',
			list_items=self.list_items,
			next_page_params=self.next_page_params,
			ImagesInstance=self
		)

	def slideshow_image(self):
		return open_window(
			('windows.imageviewer', 'SlideShow'),
			'slideshow.xml',
			all_images=json.loads(self.params['all_images']),
			index=int(self.params['current_index'])
		)

	def popular_people_image_results(self):
		def builder():
			for item in image_info['results']:
				if item['profile_path']:
					actor_poster = tmdb_image_base % ('w185', item['profile_path'])
					actor_image = tmdb_image_base % ('h632', item['profile_path'])
				else:
					actor_poster = media_path('people.png')
					actor_image = media_path('people.png')
				url_params = {
					'mode': 'person_data_dialog', 'actor_name': item['name'],
					'actor_id': item['id'], 'actor_image': actor_image
				}
				listitem = make_listitem()
				listitem.setProperty('tikiskins.thumb', actor_poster)
				listitem.setProperty('tikiskins.name', item['name'])
				listitem.setProperty('tikiskins.action', json.dumps(url_params))
				yield listitem
		page_no = int(self.params['page_no'])
		image_info = tmdb_popular_people(page_no)
		self.list_items = list(builder())
		if image_info['total_pages'] > page_no: page_no += 1
		else: page_no = 'final_page'
		self.next_page_params = {'mode': 'popular_people_image_results', 'page_no': page_no}

	def people_image_results(self):
		def builder():
			for item in all_images:
				try:
					listitem = make_listitem()
					listitem.setProperty('tikiskins.thumb', item[2])
					listitem.setProperty('tikiskins.path', item[1])
					listitem.setProperty('tikiskins.name', item[0])
					listitem.setProperty('tikiskins.action', image_action)
					yield listitem
				except: pass
		tmdb_images = []
		all_images = []
		tmdb_results = []
		tmdb_append = tmdb_results.append
		actor_name = self.params['actor_name']
		actor_id = self.params['actor_id']
		actor_image = self.params.get('actor_image', '')
		page_no = int(self.params['page_no'])
		rolling_count = int(self.params['rolling_count'])
		try: tmdb_append(tmdb_people_full_info(actor_id)['images'])
		except: pass
		tmdb_image_info = tmdb_results[0]['profiles']
		tmdb_images = [
			('%s_%sx%s_%03d' % (actor_name, i['height'],
			 i['width'], count), tmdb_image_base % ('original', i['file_path']),
			 tmdb_image_base % ('w185', i['file_path']))
			for count, i in enumerate(tmdb_image_info, rolling_count + 1)
		]
		all_images.extend(tmdb_images)
		rolling_count = rolling_count + len(tmdb_images)
		all_images_json = json.dumps([(i[1], i[0]) for i in all_images])
		image_action = json.dumps({'mode': 'slideshow_image', 'all_images': all_images_json})
		self.list_items = list(builder())
		page_no = 'final_page'
		self.next_page_params = {
			'mode': 'people_image_results', 'actor_id': actor_id, 'actor_name': actor_name,
			'actor_image': actor_image, 'page_no': page_no, 'rolling_count': rolling_count
		}

	def people_tagged_image_results(self):
		def builder():
			for count, item in enumerate(results, 1):
				try:
					media = item['type']
					thumb_url = item['url']
					image_url = item['url']
					name = '%s_%s_%03d' % (actor_name, media, count)
					listitem = make_listitem()
					listitem.setProperty('tikiskins.thumb', thumb_url)
					listitem.setProperty('tikiskins.path', image_url)
					listitem.setProperty('tikiskins.name', name)
					listitem.setProperty('tikiskins.action', image_action)
					yield listitem
				except: pass
		actor_name = self.params['actor_name']
		actor_id = self.params['actor_id']
		imdb_id = people_get_imdb_id(actor_name, actor_id)
		try: results = imdb_tagged_images(imdb_id)
		except: results = []
		all_images_json = json.dumps([(i['url'], i['type']) for i in results])
		image_action = json.dumps({'mode': 'slideshow_image', 'all_images': all_images_json})
		self.list_items = list(builder())
		self.next_page_params = {
			'mode': 'people_tagged_image_results', 'actor_id': actor_id, 'actor_name': actor_name
		}

	def browser_image(self, folder_path, return_items=False):
		def builder():
			for item in files:
				try:
					listitem = make_listitem()
					image_url = os.path.join(folder_path, item)
					try:
						thumb_url = [i for i in thumbs if i == item][0]
						thumb_url = os.path.join(thumbs_path, thumb_url)
					except:
						thumb_url = os.path.join(folder_path, item)
					listitem.setProperty('tikiskins.thumb', thumb_url)
					listitem.setProperty('tikiskins.path', image_url)
					listitem.setProperty('tikiskins.name', item)
					listitem.setProperty('tikiskins.delete', 'true')
					listitem.setProperty('tikiskins.folder_path', folder_path)
					listitem.setProperty('tikiskins.action', image_action)
					yield listitem
				except: pass
		files = list_dirs(folder_path)[1]
		files.sort()
		thumbs_path = os.path.join(folder_path, '.thumbs')
		thumbs = list_dirs(thumbs_path)[1]
		thumbs.sort()
		all_images_json = json.dumps([(os.path.join(folder_path, i), i) for i in files])
		image_action = json.dumps({
			'mode': 'slideshow_image', 'all_images': all_images_json, 'page_no': 'final_page'
		})
		self.list_items = list(builder())
		self.next_page_params = {}
		if return_items: return self.list_items

	def delete_image(self):
		image_url = self.params['image_url']
		thumb_url = self.params['thumb_url']
		folder_path = self.params['folder_path']
		delete_file(thumb_url)
		delete_file(image_url)
		set_property('salts_delete_image_finished', 'true')

