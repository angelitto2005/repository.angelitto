import json
from windows import BaseDialog
from modules.debrid import Source
from modules.kodi_utils import media_path, hide_busy_dialog, dialog, select_dialog, ok_dialog, local_string as ls
from modules.settings import get_art_provider, info_icons, provider_sort_ranks
# from modules.kodi_utils import logger

fanart_empty = BaseDialog.fanart
poster_empty = media_path('box_office.png')
info_icons_dict = {k: media_path(v) for k, v in info_icons()}
extra_info_choices = (
	('PACK', '[B]PACK[/B]'), ('DOLBY VISION', '[B]D/VISION[/B]'), ('HIGH DYNAMIC RANGE (HDR)', '[B]HDR[/B]'), ('HYBRID', '[B]HYBRID[/B]'), ('AV1', '[B]AV1[/B]'),
	('HEVC (X265)', '[B]HEVC[/B]'), ('REMUX', 'REMUX'), ('BLURAY', 'BLURAY'), ('SDR', 'SDR'), ('3D', '3D'), ('DOLBY ATMOS', 'ATMOS'), ('DOLBY TRUEHD', 'TRUEHD'),
	('DOLBY DIGITAL EX', 'DD-EX'), ('DOLBY DIGITAL PLUS', 'DD+'), ('DOLBY DIGITAL', 'DD'), ('DTS-HD MASTER AUDIO', 'DTS-HD MA'), ('DTS-X', 'DTS-X'),
	('DTS-HD', 'DTS-HD'), ('DTS', 'DTS'), ('ADVANCED AUDIO CODING (AAC)', 'AAC'), ('MP3', 'MP3'), ('8 CHANNEL AUDIO', '8CH'), ('7 CHANNEL AUDIO', '7CH'),
	('6 CHANNEL AUDIO', '6CH'), ('2 CHANNEL AUDIO', '2CH'), ('DVD SOURCE', 'DVD'), ('WEB SOURCE', 'WEB'), ('MULTIPLE LANGUAGES', 'MULTI-LANG'), ('SUBTITLES', 'SUBS')
)
quality_choices, pack_check = ('4K', '1080P', '720P', 'SD', 'TELE', 'CAM', 'SCR'), ('true', 'show', 'season')
extra_info_str, down_file_str, browse_pack_str, down_pack_str, cloud_str = ls(32605), ls(32747), ls(32746), ls(32007), ls(32016)
filter_str, clr_filter_str, filters_ignored, start_full_scrape = ls(32152), ls(32153), ls(32686), ls(32529)
filter_quality, filter_provider, filter_title, filter_extraInfo = ls(32154), ls(32157), ls(32679), ls(32169)
run_plugin_str, ignored_str = 'RunPlugin(%s)', '[B][COLOR dodgerblue](%s)[/COLOR][/B]'
en_seek_str, check_str = '[B]EN: PLAY (SEEK ENABLED)[/B]', '[B]CHECK CACHE STATUS[/B]'
string, upper, lower = str, str.upper, str.lower

class SourceResults(BaseDialog):
	def __init__(self, *args, **kwargs):
		BaseDialog.__init__(self, args)
		self.window_style = kwargs.get('window_style', 'list contrast details')
		self.window_id = kwargs.get('window_id')
		self.results = kwargs.get('results')
		self.meta = kwargs.get('meta')
		self.info_highlights_dict = kwargs.get('scraper_settings')
		self.prescrape = kwargs.get('prescrape')
		if kwargs.get('filters_ignored'): self.filters_ignored = ignored_str % filters_ignored
		else: self.filters_ignored = ''
		self.make_items()
		self.set_properties()

	def onInit(self):
		self.filter_applied = False
		self.win = self.getControl(self.window_id)
		self.win.addItems(self.item_list)
		self.setFocusId(self.window_id)

	def run(self):
		self.doModal()
		self.clearProperties()
		hide_busy_dialog()
		return self.selected

	def get_provider_and_path(self, provider):
		if provider in info_icons_dict: provider_path = info_icons_dict[provider]
		else: provider, provider_path = 'folders', info_icons_dict['folders']
		return provider, provider_path

	def get_quality_and_path(self, quality):
		quality_path = info_icons_dict[quality]
		return quality, quality_path

	def onAction(self, action):
		chosen_listitem = self.get_listitem(self.window_id)
		if action in self.closing_actions:
			if self.filter_applied: return self.clear_filter()
			self.selected = (None, '')
			return self.close()
		if action in self.selection_actions:
			if chosen_listitem.getProperty('tikiskins.perform_full_search') == 'true':
				self.selected = ('perform_full_search', '')
				return self.close()
			if 'UNCACHED' not in chosen_listitem.getProperty('tikiskins.source_type'):
				self.selected = ('play', json.loads(chosen_listitem.getProperty('source')))
				return self.close()
			source = json.loads(chosen_listitem.getProperty('source'))
			magnet_url = str(source.get('url')).startswith('magnet')
			if magnet_url: link = Source(source, self.meta).manual_add_magnet_to_cloud()
			else: link = Source(source, self.meta).manual_add_nzb_to_cloud()
			if link is not None:
				source['unrestricted_link'] = link
				self.selected = ('play', source)
				return self.close()
		elif action == self.info_actions:
			kwargs = dict(item=chosen_listitem, fanart=self.original_fanart())
			self.open_window(('sources.window_sources', 'ResultsInfo'), 'sources_info.xml', **kwargs)
		elif action in self.context_actions:
			highlight = chosen_listitem.getProperty('tikiskins.highlight')
			source = json.loads(chosen_listitem.getProperty('source'))
			kwargs = dict(item=source, meta=self.meta, highlight=highlight, filter_applied=self.filter_applied)
			choice = self.open_window(('sources.window_sources', 'ResultsContextMenu'), 'contextmenu.xml', **kwargs)
			if choice is None: return
			if 'clear_results_filter' in choice: return self.clear_filter()
			elif 'results_filter' in choice: return self.filter_results()
			elif 'results_info' in choice:
				kwargs = dict(item=chosen_listitem, fanart=self.original_fanart())
				self.open_window(('sources.window_sources', 'ResultsInfo'), 'sources_info.xml', **kwargs)
			elif 'seekable_easynews' in choice:
				link = Source(source, self.meta).resolve_internal_sources(True)
				if link is not None:
					source['unrestricted_link'] = link
					self.selected = ('play', source)
					return self.close()
			elif 'browse_packs' in choice:
				link = Source(source, self.meta).browse_packs(highlight)
				if link != 'cancel':
					source['unrestricted_link'] = link
					self.selected = ('play', source)
					return self.close()
			elif 'manual_add_magnet_to_cloud' in choice: Source(source, self.meta).manual_add_magnet_to_cloud()
			elif 'unchecked_magnet_status' in choice: Source(source, self.meta).unchecked_magnet_status()
			else: self.execute_code(choice)

	def make_items(self):
		def builder():
			for count, item in enumerate(self.results, 1):
				try:
					get = item.get
					listitem = self.make_listitem()
					set_property = listitem.setProperty
					scrape_provider = item['scrape_provider']
					source = get('source')
					quality = get('quality', 'SD')
					basic_quality, quality_icon = self.get_quality_and_path(lower(quality))
					try: name = upper(get('URLName', 'N/A'))
					except: name = 'N/A'
					pack = get('package', 'false') in pack_check
#					if pack: extra_info = '[B]PACK[/B] | %s' % get('extraInfo', '')
#					else: extra_info = get('extraInfo', 'N/A')
#					if not extra_info: extra_info = 'N/A'
					extra_info = get('extraInfo', '') or 'N/A'
					extra_info = extra_info.rstrip('| ')
					if scrape_provider == 'external':
						if 'usenet' in source: source_site = get('tracker')
						else: source_site = get('provider')
						source_site = upper(source_site)
						provider = upper(get('debrid', source_site).replace('.me', ''))
						provider_lower = lower(provider)
						provider_icon = self.get_provider_and_path(provider_lower)[1]
						if 'cache_provider' in item:
							if 'Uncached' in item['cache_provider']:
								key = 'uncached'
								if 'age' in item:
									age = (get('age') or 'N/A').rstrip('d')
									value = 'uncached (%s days)' % age
								elif 'seeders' in item:
									seeders = get('seeders') or 0
									value = 'uncached (%d seeders)' % seeders
								else: value = 'uncached'
								set_property('tikiskins.source_type', upper(value))
								set_property('tikiskins.highlight', self.info_highlights_dict[key])
							else:
								if highlight_type == 0: key = 'torrent_highlight'
								elif highlight_type == 1: key = provider_lower
								else: key = basic_quality
								status = 'UNCHECKED' if 'Unchecked' in item['cache_provider'] else 'CACHED'
								set_property('tikiskins.source_type',
									'%s [B]%s[/B]' % (status, upper(get('package')))
									if pack else
									'%s' % status)
								set_property('tikiskins.highlight', self.info_highlights_dict[key])
						else:
							if highlight_type == 0: key = 'hoster_highlight'
							elif highlight_type == 1: key = provider_lower
							else: key = basic_quality
							set_property('tikiskins.source_type', source)
							set_property('tikiskins.highlight', self.info_highlights_dict[key])
						set_property('tikiskins.name', name)
						set_property('tikiskins.provider', provider)
					else:
						source_site = upper(source)
						provider, provider_icon = self.get_provider_and_path(lower(source))
						if highlight_type in (0, 1): key = provider
						else: key = basic_quality
						set_property('tikiskins.highlight', self.info_highlights_dict[key])
						set_property('tikiskins.name', name)
						set_property('tikiskins.source_type', 'DIRECT')
						set_property('tikiskins.provider', upper(provider))
					set_property('tikiskins.source_site', source_site)
					set_property('tikiskins.provider_icon', provider_icon)
					set_property('tikiskins.quality_icon', quality_icon)
					set_property('tikiskins.size_label', get('size_label', 'N/A'))
					set_property('tikiskins.extra_info', extra_info)
					set_property('tikiskins.quality', upper(quality))
					set_property('tikiskins.count', '%02d.' % count)
					set_property('tikiskins.hash', get('hash', 'N/A'))
					set_property('source', json.dumps(item))
					yield listitem
				except: pass
		try:
			highlight_type = self.info_highlights_dict['highlight_type']
			self.item_list = list(builder())
			self.total_results = string(len(self.item_list))
			if not self.prescrape: return
			prescrape_listitem = self.make_listitem()
			prescrape_listitem.setProperty('source', '{}')
			prescrape_listitem.setProperty('tikiskins.perform_full_search', 'true')
			prescrape_listitem.setProperty('tikiskins.start_full_scrape', '[B]***%s***[/B]' % upper(start_full_scrape))
			self.item_list.append(prescrape_listitem)
		except: pass

	def set_properties(self):
		self.poster_main, self.poster_backup, self.fanart_main, self.fanart_backup = get_art_provider()
		self.setProperty('tikiskins.window_style', self.window_style)
		self.setProperty('tikiskins.fanart', self.original_fanart())
		self.setProperty('tikiskins.poster', self.original_poster())
		self.setProperty('tikiskins.title', self.meta['title'])
		self.setProperty('tikiskins.clearlogo', self.meta['clearlogo'] or '')
		self.setProperty('tikiskins.plot', self.meta['plot'])
		self.setProperty('tikiskins.total_results', self.total_results)
		self.setProperty('tikiskins.filters_ignored', self.filters_ignored)
		self.setProperty('tikiskins.scrape_time', '%.2f' % self.meta['scrape_time'])

	def original_poster(self):
		poster = self.meta.get(self.poster_main) or self.meta.get(self.poster_backup) or poster_empty
		return poster

	def original_fanart(self):
		fanart = self.meta.get(self.fanart_main) or self.meta.get(self.fanart_backup) or fanart_empty
		return fanart

	def filter_results(self):
		choices = [(filter_quality, 'quality'), (filter_provider, 'provider'), (filter_title, 'keyword_title'), (filter_extraInfo, 'extra_info')]
		list_items = [{'line1': item[0]} for item in choices]
		heading = filter_str.replace('[B]', '').replace('[/B]', '')
		kwargs = {'items': json.dumps(list_items), 'heading': heading, 'enumerate': 'false', 'multi_choice': 'false', 'multi_line': 'false'}
		main_choice = select_dialog([i[1] for i in choices], **kwargs)
		if main_choice is None: return
		if main_choice in ('quality', 'provider'):
			if main_choice == 'quality': choice_sorter = quality_choices
			else:
				sort_ranks = provider_sort_ranks()
				sort_ranks['premiumize'] = sort_ranks.pop('premiumize.me')
				choice_sorter = sorted(sort_ranks.keys(), key=sort_ranks.get)
				choice_sorter = [upper(i) for i in choice_sorter]
			filter_property = 'tikiskins.%s' % main_choice
			duplicates = set()
			provider_choices = [
				i.getProperty(filter_property)
				for i in self.item_list
				if not (i.getProperty(filter_property) in duplicates or duplicates.add(i.getProperty(filter_property)))
				and i.getProperty(filter_property) != ''
			]
			provider_choices.sort(key=choice_sorter.index)
			list_items = [{'line1': item} for item in provider_choices]
			kwargs = {'items': json.dumps(list_items), 'heading': heading, 'enumerate': 'false', 'multi_choice': 'true', 'multi_line': 'false'}
			choice = select_dialog(provider_choices, **kwargs)
			if choice is None: return
			filtered_list = [i for i in self.item_list if any(x in i.getProperty(filter_property) for x in choice)]
		elif main_choice == 'keyword_title':
			keywords = dialog.input('Enter Keyword (Comma Separated for Multiple)')
			if not keywords: return
			keywords.replace(' ', '')
			keywords = keywords.split(',')
			choice = [upper(i) for i in keywords]
			filtered_list = [i for i in self.item_list if all(x in i.getProperty('tikiskins.name') for x in choice)]
		else:# extra_info
			list_items = [{'line1': item[0]} for item in extra_info_choices]
			kwargs = {'items': json.dumps(list_items), 'heading': heading, 'enumerate': 'false', 'multi_choice': 'true', 'multi_line': 'false'}
			choice = select_dialog(extra_info_choices, **kwargs)
			if choice is None: return
			choice = [i[1] for i in choice]
			filtered_list = [i for i in self.item_list if all(x in i.getProperty('tikiskins.extra_info') for x in choice)]
		if not filtered_list: return ok_dialog(text=32760, top_space=True)
		self.filter_applied = True
		self.win.reset()
		self.win.addItems(filtered_list)
		self.setFocusId(self.window_id)
		self.setProperty('tikiskins.total_results', string(len(filtered_list)))

	def clear_filter(self):
		self.win.reset()
		self.setProperty('tikiskins.total_results', self.total_results)
		self.onInit()

class ResultsInfo(BaseDialog):
	def __init__(self, *args, **kwargs):
		BaseDialog.__init__(self, args)
		self.item = kwargs['item']
		self.fanart = kwargs.get('fanart') or ''
		self.set_properties()

	def run(self):
		self.doModal()

	def onAction(self, action):
		self.close()

	def get_provider_and_path(self):
		provider = lower(self.item.getProperty('tikiskins.provider'))
		if provider in info_icons_dict: provider_path = info_icons_dict[provider]
		else: provider_path = info_icons_dict['folders']
		return provider, provider_path

	def get_quality_and_path(self):
		quality = lower(self.item.getProperty('tikiskins.quality'))
		quality_path = info_icons_dict[quality]
		return quality, quality_path

	def set_properties(self):
		provider, provider_path = self.get_provider_and_path()
		quality, quality_path = self.get_quality_and_path()
		self.setProperty('tikiskins.results.info.fanart', self.fanart)
		self.setProperty('tikiskins.results.info.name', self.item.getProperty('tikiskins.name'))
		self.setProperty('tikiskins.results.info.source_type', self.item.getProperty('tikiskins.source_type'))
		self.setProperty('tikiskins.results.info.source_site', self.item.getProperty('tikiskins.source_site'))
		self.setProperty('tikiskins.results.info.size_label', self.item.getProperty('tikiskins.size_label'))
		self.setProperty('tikiskins.results.info.extra_info', self.item.getProperty('tikiskins.extra_info'))
		self.setProperty('tikiskins.results.info.highlight', self.item.getProperty('tikiskins.highlight'))
		self.setProperty('tikiskins.results.info.hash', self.item.getProperty('tikiskins.hash'))
		self.setProperty('tikiskins.results.info.provider', provider)
		self.setProperty('tikiskins.results.info.quality', quality)
		self.setProperty('tikiskins.results.info.provider_icon', provider_path)
		self.setProperty('tikiskins.results.info.quality_icon', quality_path)

class ResultsContextMenu(BaseDialog):
	def __init__(self, *args, **kwargs):
		BaseDialog.__init__(self, args)
		self.window_id = 2020
		self.item = kwargs['item']
		self.highlight = kwargs['highlight']
		self.meta = kwargs['meta']
		self.filter_applied = kwargs['filter_applied']
		self.item_list = []
		self.selected = None
		self.make_menu()
		self.set_properties()

	def onInit(self):
		win = self.getControl(self.window_id)
		win.addItems(self.item_list)
		self.setFocusId(self.window_id)

	def run(self):
		self.doModal()
		return self.selected

	def onAction(self, action):
		if action in self.closing_actions: return self.close()
		if action in self.selection_actions:
			chosen_listitem = self.get_listitem(self.window_id)
			self.selected = chosen_listitem.getProperty('tikiskins.context.action')
			return self.close()
		elif action in self.context_actions: return self.close()

	def make_menu(self):
		append = self.item_list.append
		meta_json = json.dumps(self.meta)
		source = json.dumps(self.item)
		name, provider_source = self.item.get('name'), self.item.get('source')
		magnet_url, info_hash = self.item.get('url', 'None'), self.item.get('hash', 'None')
		scrape_provider, cache_provider = self.item.get('scrape_provider'), self.item.get('cache_provider', 'None')
		if next((True for x in ('real-debrid', 'alldebrid') if x in cache_provider), False):
			append(self.make_contextmenu_item(check_str, run_plugin_str, {'mode': 'unchecked_magnet_status'}))
		if 'easynews' in scrape_provider:
			append(self.make_contextmenu_item(en_seek_str, run_plugin_str, {'mode': 'seekable_easynews'}))
		if self.filter_applied:
			append(self.make_contextmenu_item(clr_filter_str, run_plugin_str, {'mode': 'clear_results_filter'}))
		else: append(self.make_contextmenu_item(filter_str, run_plugin_str, {'mode': 'results_filter'}))
		append(self.make_contextmenu_item(extra_info_str, run_plugin_str, {'mode': 'results_info'}))
		if 'Uncached' in cache_provider: return
		if 'package' in self.item:
			append(self.make_contextmenu_item(browse_pack_str, run_plugin_str, {'mode': 'browse_packs'}))
			append(self.make_contextmenu_item(down_pack_str, run_plugin_str, {
				'mode': 'downloader', 'action': 'meta.pack', 'source': source, 'meta': meta_json,
				'name': self.meta.get('rootname', ''), 'provider': cache_provider, 'url': None,
				'magnet_url': magnet_url, 'info_hash': info_hash, 'highlight': self.highlight
			}))
		if scrape_provider != 'folders':
			append(self.make_contextmenu_item(down_file_str, run_plugin_str, {
				'mode': 'downloader', 'action': 'meta.single', 'source': source, 'meta': meta_json,
				'name': self.meta.get('rootname', ''), 'provider': scrape_provider, 'url': None
			}))
		if provider_source == 'torrent':
			append(self.make_contextmenu_item(cloud_str, run_plugin_str, {'mode': 'manual_add_magnet_to_cloud'}))

	def set_properties(self):
		self.setProperty('tikiskins.context.highlight', self.highlight)

