import requests
from concurrent.futures import ThreadPoolExecutor as Pool, as_completed
from time import monotonic
import xbmc, xbmcaddon, xbmcgui
from magneto import sources as fs_sources

log = xbmc.log
Addon = xbmcaddon.Addon
list_item = xbmcgui.ListItem
dialog, select = xbmcgui.DialogProgress(), xbmcgui.Dialog().select
input, notification = xbmcgui.Dialog().input, xbmcgui.Dialog().notification

default_icon = Addon().getAddonInfo('icon')
movie_year_check_url = 'https://v2.sg.media-imdb.com/suggestion/t/%s.json'
total_str = 'TOTAL: [COLOR red][B]%s[/B][/COLOR]  |  '
total_str += '4K: [COLOR red][B]%d[/B][/COLOR]  |  1080p: [COLOR red][B]%d[/B][/COLOR]  |  '
total_str += '720p: [COLOR red][B]%d[/B][/COLOR]  |  SD: [COLOR red][B]%d[/B][/COLOR]'
input_str, nf_str = 'Enter a valid [B]Movie[/B] IMDb id:', 'Movie %s Not Found'
heading, resolutions = 'Magneto', '4K 1080p 720p SD'

def get_movie_source(module):
	try:
		start_time = monotonic()
		module.results = module.sources(module.data, {})
		module.elapsed = round(monotonic() - start_time, 3)
		if module.results is None:
			raise Exception('%s: %s fatal error' % (heading.upper(), module.name.upper()))
		for result in module.results:
			quality = result.get('quality')
			if not quality in module.metrics: module.metrics['SD'] += 1
			else: module.metrics[quality] = module.metrics.get(quality, 0) + 1
	except Exception as e: log(str(e), 1)
	return module

def module_factory(modules, data=None):
	items = []
	for provider, module in modules:
		if not module.hasMovies: continue
		m = module()
		m.results, m.elapsed = None, 0
		m.name, m.data = provider, data or {}
		m.metrics = dict.fromkeys(resolutions.split(), 0)
		items.append(m)
	return items

def _make_items(modules):
	for i, module in enumerate(modules):
		try:
			values = list(module.metrics.values())
			total = 'NONE' if module.results is None else sum(values)
			line1 = '%s: %.3fs' % (module.name.upper(), module.elapsed)
			line2 = total_str % (total, *values)
			icon = module.data['poster'] or default_icon
			item = list_item(line1, line2, offscreen=True)
			item.setArt({'icon': icon})
			yield item
		except: pass

def magneto():
	data = {'imdb': 'tt0120903', 'title': 'X-Men', 'aliases': [], 'year': 2000}
	data['poster'] = default_icon

	imdb_id = input(input_str, defaultt=data['imdb'])
	url = movie_year_check_url % imdb_id
	dialog.create(heading, 'Please Wait...')
	dialog.update(0, 'Fetching Metadata...')
	result = requests.get(url, timeout=5)
	if result.ok:
		result = result.json()
		items = (i for i in result['d'] if i['id'] == imdb_id)
		items = next(items, None) or dialog.close()
		if not items: return notification(heading, nf_str % imdb_id, time=3000)
		data['poster'] = items.get('i', {}).get('imageUrl')
		data['title'] = items.get('l')
		data['imdb'] = items.get('id')
		data['year'] = items.get('y')
	data['rootname'] = '%s (%s)' % (data['title'], data['year'])
	data['year'] = str(data['year'])

	modules = module_factory(fs_sources(ret_all=True), data)
	len_modules = len(modules)
	line0 = 'Title: %s' % data['rootname']
	with Pool(len_modules or 1) as pool:
		futures = [pool.submit(get_movie_source, i) for i in modules]
		for i, future in enumerate(as_completed(futures), 1):
			module = future.result()
			line1 = 'Source: %s' % module.name.upper()
			line2 = 'Elapsed: %.3f' % module.elapsed
			line3 = 'Results: %3d' % sum(module.metrics.values())
			dialog.update(int(i / len_modules * 100), '[CR]'.join((line0, line1, line2, line3)))
	dialog.update(100, 'Processing Results...')
	modules.sort(key=lambda k: k.elapsed)
	results = [i for i in modules if i.results]
	modules = results + [i for i in modules if not i in results]
	items = list(_make_items(modules))
	dialog.close()
	select(f"{heading} - {data['rootname']}", items, useDetails=True)

