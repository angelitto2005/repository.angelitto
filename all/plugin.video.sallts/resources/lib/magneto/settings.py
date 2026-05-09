from . import kore
# logger = kore.logger

get_setting, set_setting, addon_path = kore.get_setting, kore.set_setting, kore.addon_path
results_window_numbers_dict = {'List': 2000, 'WideList': 2002}

def results_format():
	setting = int(get_setting('results.list_format', '1'))
	window_format = ('List', 'WideList')[setting]
	if not window_format in results_window_numbers_dict:
		window_format = 'List'
		kore.set_setting('results.list_format', window_format)
	window_number = results_window_numbers_dict[window_format]
	return window_format.lower(), window_number

def scraping_settings():
	highlight_type = int(get_setting('highlight.type', '1'))
	if highlight_type == 0:
		highlight_4K = get_setting('scraper_4k_highlight', 'magenta')
		highlight_1080P = get_setting('scraper_1080p_highlight', 'orange')
		highlight_720P = get_setting('scraper_720p_highlight', 'blue')
		highlight_SD = get_setting('scraper_SD_highlight', 'green')
		return {
			'highlight_type': highlight_type, '4k': highlight_4K,
			'1080p': highlight_1080P, '720p': highlight_720P, 'sd': highlight_SD
		}
	highlight = get_setting('scraper_single_highlight', 'dodgerblue')
	return {'highlight_type': 1, '4k': highlight, '1080p': highlight, '720p': highlight, 'sd': highlight}

def scraping_timeout():
	return int(get_setting('scraping_timeout', '30'))

def skin_location(skin_xml):
	return addon_path

def active_internal_scrapers():
	settings = ['provider.aiostreams']
	active = [i.split('.')[1] for i in settings if get_setting('%s' % i) == 'true']
	return active

def audio_filters():
	setting = get_setting('filter_audio')
	if setting in ('empty_setting', ''): return []
	return setting.split(', ')

def auto_play(mediatype):
	return get_setting('auto_play_%s' % mediatype, 'false') == 'true'

def filter_status(filter_type):
	return int(get_setting('filter_%s' % filter_type, '0'))

def priority_language():
	if get_setting('results.language_filter') == 'true': return get_setting('results.language', '')
	return False

def quality_filter(setting):
	return get_setting('%s' % setting).split(', ')

def color_pick(params):
	colors = {
		'white': 'FFFFFFFF', 'silver': 'FFC0C0C0', 'gray': 'FF808080', 'cyan': 'FF00FFFF',
		'lightblue': 'FFADD8E6', 'blue': 'FF0000FF', 'dodgerblue': 'FF1E90FF', 'darkblue': 'FF1E90FF',
		'maroon': 'FF800000', 'brown': 'FFA52A2A', 'red': 'FFFF0000', 'orange': 'FFFFA500', 'yellow': 'FFFFFF00',
		'lime': 'FF00FF00', 'green': 'FF008000', 'olive': '808000', 'magenta': 'FFFF00FF', 'purple': 'FF800080'
	}
	color_names = list(colors.keys())
	preselect = get_setting(params['setting'], '').lower()
	if preselect in color_names: preselect = color_names.index(preselect)
	else: preselect = -1
	heading = params['setting'].split('.')[-1].replace('_', ' ').title()
	items_list = [f"[COLOR {i}]{i}[/COLOR]" for i in color_names]
	selection = kore.dialog.select(heading, items_list, preselect=preselect)
	if selection < 0: return
	color = color_names[selection]
	display_color, display_value = params['setting'].replace('highlight', 'display'), colors[color]
	set_setting(display_color, f"[COLOR {display_value}]{color}[/COLOR]")
	set_setting(params['setting'], color)
