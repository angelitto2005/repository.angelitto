import re
import json
from threading import Thread
from . import kore
from .window_base import BaseDialog
# logger = kore.logger

empty_poster, addon_fanart = kore.empty_poster, kore.get_addon_fanart()
hide_busy_dialog, dialog, get_icon = kore.hide_busy_dialog, kore.dialog, kore.get_icon
select_dialog, notification = kore.select_dialog, kore.notification
debrid_dict, resume_dict = {
	'realdebrid': 'rd', 'alldebrid': 'ad', 'premiumize': 'pm', 'torbox': 'tb',
	'offcloud': 'oc', 'easydebrid': 'ed', 'debrider': 'db', 'debridlink': 'dl'
}, {10: 'resume', 11: 'start_over', 12: 'cancel'}
info_quality_dict, info_icons_dict = {
	'4k': get_icon('flag_4k'), '1080p': get_icon('flag_1080p'), '720p': get_icon('flag_720p'),
	'sd': get_icon('flag_sd'), 'cam': get_icon('flag_sd'), 'tele': get_icon('flag_sd'), 'scr': get_icon('flag_sd')
}, {'aiostreams': get_icon('premium')}
extra_info_choices, quality_choices = (
	('PACK', 'PACK'), ('DOLBY VISION', 'D/VISION'), ('HIGH DYNAMIC RANGE (HDR)', 'HDR'), ('HYBRID', 'HYBRID'), ('AV1', 'AV1'),
	('HEVC (X265)', 'HEVC'), ('REMUX', 'REMUX'), ('BLURAY', 'BLURAY'), ('SDR', 'SDR'), ('3D', '3D'), ('DOLBY ATMOS', 'ATMOS'), ('DOLBY TRUEHD', 'TRUEHD'),
	('DOLBY DIGITAL EX', 'DD-EX'), ('DOLBY DIGITAL PLUS', 'DD+'), ('DOLBY DIGITAL', 'DD'), ('DTS-HD MASTER AUDIO', 'DTS-HD MA'), ('DTS-X', 'DTS-X'),
	('DTS-HD', 'DTS-HD'), ('DTS', 'DTS'), ('AAC', 'AAC'), ('OPUS', 'OPUS'), ('MP3', 'MP3'), ('8CH AUDIO', '8CH'), ('7CH AUDIO', '7CH'), ('6CH AUDIO', '6CH'),
	('2CH AUDIO', '2CH'), ('DVD SOURCE', 'DVD'), ('WEB SOURCE', 'WEB'), ('MULTIPLE LANGUAGES', 'MULTI-LANG'), ('SUBTITLES', 'SUBS')
), ('4K', '1080P', '720P', 'SD', 'CAM/SCR/TELE')
poster_lists, prerelease_values, prerelease_key = ('list', 'medialist'), ('CAM', 'SCR', 'TELE'), 'CAM/SCR/TELE'
priority_label = '[COLOR firebrick][B]%s[/B][/COLOR]'
string, upper, lower = str, str.upper, str.lower
resume_timeout = 10000

class SourcesResults(BaseDialog):
	def __init__(self, *args, **kwargs):
		BaseDialog.__init__(self, *args)
		self.window_format = kwargs.get('window_format', 'list')
		self.window_id = kwargs.get('window_id', 2000)
		self.filter_window_id = 2100
		self.results = kwargs.get('results')
		self.info_highlights_dict = kwargs.get('scraper_settings')
		self.priority_language = kwargs.get('priority_language')
		self.meta = kwargs.get('meta')
		self.meta_get = self.meta.get
		self.make_poster = self.window_format in poster_lists
		self.poster = self.meta_get('poster') or empty_poster
		self.make_items()
		self.make_filter_items()
		self.set_properties()

	def onInit(self):
		self.filter_applied = False
		if self.make_poster: Thread(target=self.set_poster).start()
		self.add_items(self.window_id, self.item_list)
		self.add_items(self.filter_window_id, self.filter_list)
		self.setFocusId(self.window_id)

	def run(self):
		self.doModal()
		self.clearProperties()
		hide_busy_dialog()
		return self.selected

	def get_provider_and_path(self, provider):
		try: icon_path = info_icons_dict[provider]
		except: provider, icon_path = 'folders', get_icon('premium')
		return provider, icon_path

	def get_quality_and_path(self, quality):
		icon_path = info_quality_dict[quality]
		return quality, icon_path

	def filter_action(self, action):
		if action == self.right_action or action in self.closing_actions:
			self.select_item(self.filter_window_id, 0)
			self.setFocusId(self.window_id)
		if action in self.selection_actions:
			chosen_listitem = self.get_listitem(self.filter_window_id)
			filter_type, filter_value = chosen_listitem.getProperty('filter_info').split('_')
			if filter_type in ('quality', 'provider'):
				if filter_value == prerelease_key: filtered_list = [i for i in self.item_list if i.getProperty(filter_type) in filter_value.split('/')]
				else: filtered_list = [i for i in self.item_list if i.getProperty(filter_type) == filter_value]
			elif filter_type == 'special':
				if filter_value == 'title':
					keywords = dialog.input('Enter Keyword (Comma Separated for Multiple)')
					if not keywords: return
					keywords.replace(' ', '')
					keywords = keywords.split(',')
					choice = [upper(i) for i in keywords]
					filtered_list = [i for i in self.item_list if all(x in i.getProperty('name') for x in choice)]
				elif filter_value == 'extraInfo':
					list_items = [{'line1': item[0], 'icon': self.poster} for item in extra_info_choices]
					kwargs = {'items': json.dumps(list_items), 'heading': 'Filter Results', 'multi_choice': 'true'}
					choice = select_dialog(extra_info_choices, **kwargs)
					if choice is None: return
					choice = [i[1] for i in choice]
					filtered_list = [i for i in self.item_list if all(x in i.getProperty('extraInfo') for x in choice)]
			elif filter_type == 'results': return self.results_info(self.get_listitem(self.window_id))
			if not filtered_list: return notification('No Results', 2000)
			self.set_filter(filtered_list)

	def onAction(self, action):
		if self.get_visibility('Control.HasFocus(%s)' % self.filter_window_id): return self.filter_action(action)
		chosen_listitem = self.get_listitem(self.window_id)
		if action in self.closing_actions:
			if self.filter_applied: return self.clear_filter()
			self.selected = (None, '')
			return self.close()
		if action == self.info_action: self.results_info(chosen_listitem)
		elif action in self.selection_actions:
			chosen_source = json.loads(chosen_listitem.getProperty('source'))
			self.selected = ('play', chosen_source)
			return self.close()
		elif action in self.context_actions:
#			source = json.loads(chosen_listitem.getProperty('source'))
#			choice = self.context_menu(source)
#			if choice == 'results_info':
			return self.results_info(chosen_listitem)

	def make_items(self, filtered_list=None):
		def builder(results):
			for count, item in enumerate(results, 1):
				try:
					get = item.get
					scrape_provider = get('scrape_provider')
					quality = (get('resolution') or 'sd').replace('2160p', '4K')
					if not upper(quality) in quality_choices: quality = 'SD'
					name = get('folderName') or get('filename')
					languages = get('languages')
					if languages and self.priority_language:
						languages = [priority_label % i if _language.match(i) else i for i in item['languages']]
					try: size_label = f"{get('size', 0) / 1073741824:.2f} GB"
					except: size_label = '0.00 GB'
					basic_quality, quality_icon = self.get_quality_and_path(lower(quality))
					extraInfo = ' | '.join(i for i in (
						'[B](PACK)[/B]' if get('seasonPack') else None,
						get('releaseGroup'),
						get('network'),
						get('quality'),
						get('encode'),
						*item['visualTags'],
						*item['subtitles']
					) if i) or '--'
					extraInfo2 = ' | '.join(i for i in (
						*item['audioTags'],
						*item['audioChannels'],
						*languages
					) if i) or '--'
					service = get('service')
					debrid = upper(debrid_dict.get(service) or service or '')
					if debrid and get('cached'): debrid += '+'
					addon = upper(get('addon') or '')
					source = 'library' if get('library') else get('indexer') or addon or 'N/A'
					source_site = upper(source)
					provider, provider_icon = self.get_provider_and_path(lower(scrape_provider))
					listitem = self.make_listitem()
					listitem.setProperties({
						'highlight': self.info_highlights_dict[basic_quality],
						'source_type': 'DIRECT',
						'provider': debrid or addon or provider,
						'addon': addon,
						'name': upper(name),
						'source_site': source_site,
						'provider_icon': provider_icon,
						'quality_icon': quality_icon,
						'count': '%02d.' % count,
						'size_label': size_label,
						'extraInfo': extraInfo,
						'extraInfo2': extraInfo2,
						'quality': upper(quality),
						'hash': get('infoHash'),
						'source': json.dumps(item)
					})
					yield listitem
				except: pass
		try:
			_language = re.compile(rf"(multi|{self.priority_language})", flags=re.I)
			if filtered_list: return list(builder(filtered_list))
			self.item_list = list(builder(self.results))
			self.total_results = string(len(self.item_list))
		except: pass

	def make_filter_items(self):
		def builder(data):
			for item in data:
				listitem = self.make_listitem()
				listitem.setProperties({'label': item[0], 'filter_info': item[1]})
				yield listitem
		duplicates = set()
		qualities = [
			i.getProperty('quality') for i in self.item_list
			if not (i.getProperty('quality') in duplicates or duplicates.add(i.getProperty('quality')))
			and not i.getProperty('quality') == ''
		]
		if any(i in prerelease_values for i in qualities):
			qualities = [i for i in qualities if not i in prerelease_values] + [prerelease_key]
		qualities.sort(key=quality_choices.index)
		qualities = [('Show [B]%s[/B] Only' % i, 'quality_%s' % i) for i in qualities]
		data = qualities
		data.extend([
			('Filter by [B]Title[/B]...', 'special_title'),
			('Filter by [B]Info[/B]...', 'special_extraInfo'),
			('Result [B]Info[/B]...', 'results_info')
		])
		self.filter_list = list(builder(data))

	def set_properties(self):
		self.setProperty('window_format', self.window_format)
		self.setProperty('fanart', self.meta_get('fanart') or addon_fanart)
		self.setProperty('clearlogo', self.meta_get('clearlogo') or '')
		self.setProperty('title', self.meta_get('title'))
		self.setProperty('total_results', self.total_results)

	def set_poster(self):
		if self.window_id == 2000: self.set_image(200, self.poster)

	def context_menu(self, item):
		choices = []
		choices_append = choices.append
		choices_append(('Info', 'results_info'))
		list_items = [{'line1': i[0], 'icon': self.poster} for i in choices]
		kwargs = {'items': json.dumps(list_items)}
		choice = select_dialog([i[1] for i in choices], **kwargs)
		return choice

	def results_info(self, chosen_listitem):
		return self.open_window(
			('magneto.player.window_sources', 'SourcesInfo'),
			'sources_info.xml',
			item=chosen_listitem,
			art={'poster': self.meta_get('poster'), 'fanart': self.meta_get('fanart')}
		)

	def set_filter(self, filtered_list):
		self.filter_applied = True
		self.reset_window(self.window_id)
		self.add_items(self.window_id, filtered_list)
		self.setFocusId(self.window_id)
		self.setProperty('total_results', string(len(filtered_list)))
		self.setProperty('filter_applied', 'true')
		self.setProperty('filter_info', '| Press [B]BACK[/B] to Cancel')

	def clear_filter(self):
		self.filter_applied = False
		self.reset_window(self.window_id)
		self.add_items(self.window_id, self.item_list)
		self.setFocusId(self.window_id)
		self.select_item(self.filter_window_id, 0)
		self.setProperty('total_results', self.total_results)
		self.setProperty('filter_applied', 'false')
		self.setProperty('filter_info', '')

class SourcesPlayback(BaseDialog):
	def __init__(self, *args, **kwargs):
		BaseDialog.__init__(self, *args)
		self.meta = kwargs.get('meta')
		self.is_canceled, self.skip_resolve, self.resume_choice = False, False, None
		self.meta_get = self.meta.get
		self.enable_scraper()

	def run(self):
		self.doModal()
		self.clearProperties()
		self.clear_modals()

	def onClick(self, controlID):
		self.resume_choice = resume_dict[controlID]

	def onAction(self, action):
		if action in self.closing_actions: self.is_canceled = True
		elif action == self.right_action and self.window_mode == 'resolver': self.skip_resolve = True

	def iscanceled(self):
		return self.is_canceled

	def skip_resolved(self):
		status = self.skip_resolve
		self.skip_resolve = False
		return status

	def reset_is_cancelled(self):
		self.is_canceled = False

	def enable_scraper(self):
		self.window_mode = 'scraper'
		self.set_scraper_properties()

	def enable_resolver(self):
		self.window_mode = 'resolver'
		self.set_resolver_properties()

	def enable_resume(self, percent):
		self.window_mode = 'resume'
		self.set_resume_properties(percent)

	def busy_spinner(self, toggle='true'):
		self.setProperty('enable_busy_spinner', toggle)

	def set_scraper_properties(self):
		title, year, genre = self.meta_get('title'), string(self.meta_get('year')), self.meta_get('genre', '')
		poster = self.meta_get('poster') or empty_poster
		fanart = self.meta_get('fanart') or addon_fanart
		clearlogo = self.meta_get('clearlogo') or ''
		self.setProperty('window_mode', self.window_mode)
		self.setProperty('title', title)
		self.setProperty('fanart', fanart)
		self.setProperty('clearlogo', clearlogo)
		self.setProperty('year', year)
		self.setProperty('poster', poster)
		self.setProperty('genre', ', '.join(genre))

	def set_resolver_properties(self):
		if self.meta_get('mediatype') == 'episode': self.text = '[B]%02dx%02d - %s[/B][CR][CR]%s' % (
			self.meta_get('season'),
			self.meta_get('episode'),
			self.meta_get('ep_name', 'N/A').upper(),
			''
		)
		else: self.text = ''
		self.setProperty('window_mode', self.window_mode)
		self.setProperty('text', self.text)

	def set_resume_properties(self, percent):
		self.setProperty('window_mode', self.window_mode)
		self.setProperty('resume_percent', percent)
		self.setFocusId(10)
		self.update_resumer()

	def update_scraper(self, results_sd, results_720p, results_1080p, results_4k, results_total, content='', percent=0):
		self.setProperty('results_4k', string(results_4k))
		self.setProperty('results_1080p', string(results_1080p))
		self.setProperty('results_720p', string(results_720p))
		self.setProperty('results_sd', string(results_sd))
		self.setProperty('results_total', string(results_total))
		self.setProperty('percent', string(percent))
		self.set_text(2001, content)

	def update_resolver(self, text='', percent=0):
		try: self.setProperty('percent', string(percent))
		except: pass
		if text: self.set_text(2002, text)

	def update_resumer(self):
		count = 0
		while self.resume_choice is None:
			percent = int((float(count)/resume_timeout)*100)
			if percent >= 100: self.resume_choice = 'resume'
			self.setProperty('percent', string(percent))
			count += 100
			self.sleep(100)

class SourcesInfo(BaseDialog):
	def __init__(self, *args, **kwargs):
		BaseDialog.__init__(self, *args)
		self.item = kwargs['item']
		self.art = kwargs.get('art') or {}
		self.item_get_property = self.item.getProperty
		self.set_properties()

	def run(self):
		self.doModal()

	def onAction(self, action):
		self.close()

	def get_provider_and_path(self):
		try:
			provider = lower(self.item_get_property('provider'))
			icon_path = info_icons_dict[provider]
		except: provider, icon_path = 'folders', get_icon('premium')
		return provider, icon_path

	def get_quality_and_path(self):
		quality = lower(self.item_get_property('quality'))
		icon_path = info_quality_dict[quality]
		return quality, icon_path

	def set_properties(self):
		provider, provider_path = self.get_provider_and_path()
		quality, quality_path = self.get_quality_and_path()
		self.setProperty('name', self.item_get_property('name'))
		self.setProperty('source_type', self.item_get_property('source_type'))
		self.setProperty('source_site', self.item_get_property('source_site'))
		self.setProperty('size_label', self.item_get_property('size_label'))
		self.setProperty('extraInfo', self.item_get_property('extraInfo'))
		self.setProperty('highlight', self.item_get_property('highlight'))
		self.setProperty('hash', self.item_get_property('hash'))
		self.setProperty('poster', self.art.get('poster', ''))
		self.setProperty('fanart', self.art.get('fanart', ''))
		self.setProperty('provider', self.item_get_property('addon'))
		self.setProperty('quality', quality)
		self.setProperty('provider_icon', provider_path)
		self.setProperty('quality_icon', quality_path)
