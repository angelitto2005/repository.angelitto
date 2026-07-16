import re
import time
import random
import hashlib
import unicodedata
import _strptime  # fix bug in python import
from html import unescape
from queue import SimpleQueue
from importlib import import_module
from datetime import datetime, timedelta, date
from modules.kodi_utils import local_string as ls, get_setting, logger
# from modules.kodi_utils import logger

class TaskPool:
	@staticmethod
	def process(_threads):
		for index, i in enumerate(_threads, 1):
			try: i.start()
			except Exception as e: logger('thread error', f"{index}: {e}")
			else: yield i

	def __init__(self, maxsize=None):
		self.maxsize = maxsize or int(get_setting('pov.max_threads', '100'))
		self._queue = SimpleQueue()

	def _thread_target(self, queue, target):
		while not queue.empty():
			try: target(*queue.get())
			except Exception as e: logger('queue error', f"{e}")

	def tasks(self, _target, _list, _thread):
		maxsize = min(len(_list), self.maxsize)
		[self._queue.put(tag) for tag in _list]
		threads = [_thread(target=self._thread_target, args=(self._queue, _target)) for i in range(maxsize)]
		return list(self.process(threads))

	def tasks_enumerate(self, _target, _list, _thread):
		maxsize = min(len(_list), self.maxsize)
		[self._queue.put((p, tag)) for p, tag in enumerate(_list, 1)]
		threads = [_thread(target=self._thread_target, args=(self._queue, _target)) for i in range(maxsize)]
		return list(self.process(threads))

def manual_function_import(location, function_name):
	return getattr(import_module(location), function_name)

def make_thread_list(_target, _list, _thread):
	for item in _list:
		threaded_object = _thread(target=_target, args=(item,))
		threaded_object.start()
		yield threaded_object

def make_thread_list_enumerate(_target, _list, _thread):
	for item_position, item in enumerate(_list):
		threaded_object = _thread(target=_target, args=(item_position, item))
		threaded_object.start()
		yield threaded_object

def chunks(item_list, limit):
	"""
	Yield successive limit-sized chunks from item_list.
	"""
	for i in range(0, len(item_list), limit): yield item_list[i:i + limit]

def string_to_float(string, default_return):
	"""
	Remove all alpha from string and return a float.
	Returns float of "default_return" upon ValueError.
	"""
	try: return float(''.join(c for c in string if (c.isdigit() or c =='.')))
	except ValueError: return float(default_return)

def string_alphanum_to_num(string):
	"""
	Remove all alpha from string and return remaining string.
	Returns original string upon ValueError.
	"""
	try: return ''.join(c for c in string if c.isdigit())
	except ValueError: return string

def get_next_episode_pointer(meta, current_season, current_episode):
	season_data = meta.get('season_data', [])
	season_info = next((i for i in season_data if i['season_number'] == current_season), None)
	if season_info and current_episode >= season_info['episode_count']: return current_season + 1, 1, True
	return current_season, current_episode + 1, False

def jsondate_to_datetime(jsondate_object, resformat=None):
	if resformat: return datetime_workaround(jsondate_object, resformat)
	return datetime.fromisoformat(jsondate_object.replace('Z', '+00:00'))

def get_datetime(string=False, dt=False):
	d = datetime.now()
	if dt and string: return str(d)
	if dt: return d
	if string: return str(d.date())
	return d.date()

def adjust_premiered_date(orig_date, adjust_hours):
	if not orig_date: return None, None
	datetime_object = jsondate_to_datetime('%s 20:00:00' % orig_date)
	adjusted_datetime = datetime_object + timedelta(hours=adjust_hours)
	adjusted_date = adjusted_datetime.date()
	return adjusted_date, str(adjusted_date)

def make_day(today, date, date_format, use_words=True):
	try: day = date.strftime(date_format)
	except ValueError: day = date.strftime('%Y-%m-%d')
	if not use_words: return day
	day_diff = (date - today).days
	if day_diff == -1: day = ls(32848).upper()
	elif day_diff == 0: day = ls(32849).upper()
	elif day_diff == 1: day = ls(32850).upper()
	elif 1 < day_diff < 7: day = ls({
		'Monday': 32971,
		'Tuesday': 32972,
		'Wednesday': 32973,
		'Thursday': 32974,
		'Friday': 32975,
		'Saturday': 32976,
		'Sunday': 32977
	}[date.strftime('%A')])
	return day

def subtract_dates(date1, date2):
	return (date1 - date2).days

def datetime_workaround(data, str_format):
	try: datetime_object = datetime.strptime(data, str_format)
	except: datetime_object = datetime(*(time.strptime(data, str_format)[0:6]))
	return datetime_object

def date_difference(current_date, compare_date, difference_tolerance, allow_postive_difference=False):
	try:
		difference = subtract_dates(current_date, compare_date)
		if not allow_postive_difference and difference > 0: return False
		else: difference = abs(difference)
		if difference > difference_tolerance: return False
		return True
	except: return True

def calculate_age(born, str_format, died=None):
	born = datetime_workaround(born, str_format)
	if not died: today = date.today()
	else: today = datetime_workaround(died, str_format)
	return today.year - born.year - ((today.month, today.day) < (born.month, born.day))

def safe_string(value):
	if value is None: return ''
	ascii_chars = ''.join(
		c for c in unicodedata.normalize('NFKD', str(value))
		if ord(c) < 128 and not unicodedata.combining(c)
	)
	return ascii_chars

def make_title_slug(name):
	slug = re.sub(r'[^a-z0-9_]+', '-', name.strip().lower())
	slug = slug.strip('-')
	return slug

def replace_html_codes(text):
	text = unescape(re.sub(r"(&#[0-9]+)(?=[^0-9;])", r"\1;", text))
	return text

def regex_from_to(text, from_string, to_string, excluding=True):
	if excluding: r = re.search(r"(?i)" + from_string + r"([\S\s]+?)" + to_string, text).group(1)
	else: r = re.search(r"(?i)(" + from_string + r"[\S\s]+?" + to_string + ")", text).group(1)
	return r

def regex_get_all(text, start_with, end_with):
	r = re.findall(r"(?i)(" + start_with + r"[\S\s]+?" + end_with + ")", text)
	return r

def byteify(data, ignore_dicts=False):
	try:
		if isinstance(data, str): return data.encode('utf-8')
		if isinstance(data, list): return [byteify(item, ignore_dicts=True) for item in data]
		if isinstance(data, dict) and not ignore_dicts:
			return dict([(byteify(key, ignore_dicts=True), byteify(value, ignore_dicts=True)) for key, value in data.iteritems()])
	except: pass
	return data

def gen_file_hash(file):
	try:
		md5_hash = hashlib.md5()
		with open(file, 'rb') as f:
			while True:
				chunk = f.read(65536)
				if not chunk: break
				md5_hash.update(chunk)
		return md5_hash.hexdigest()
	except: pass

def sec2time(sec, n_msec=3):
	""" Convert seconds to 'D days, HH:MM:SS.FFF' """
	if hasattr(sec,'__len__'): return [sec2time(s) for s in sec]
	m, s = divmod(sec, 60)
	h, m = divmod(m, 60)
	d, h = divmod(h, 24)
	if n_msec > 0: pattern = '%%02d:%%02d:%%0%d.%df' % (n_msec+3, n_msec)
	else: pattern = '%02d:%02d:%02d'
	if d == 0: return pattern % (h, m, s)
	return ('%d days, ' + pattern) % (d, h, m, s)

def released_key(item):
	if 'released' in item: return item['released'] or '2050-01-01'
	if 'first_aired' in item: return item['first_aired'] or '2050-01-01'
	return '2050-01-01'

ARTICLE_RE = re.compile(r'^(?:the|a|an)\s+', re.I)

def title_key(title, ignore_articles):
	if title is None: return ''
	if ignore_articles: return ARTICLE_RE.sub('', title)
	return title

def sort_for_article(item_list, sort_key, ignore_articles):
	return sorted(item_list, key=lambda k: title_key(k[sort_key], ignore_articles))

def sort_list(sort_key, sort_direction, list_data, ignore_articles):
	try:
		reverse = sort_direction != 'asc'
		if sort_key == 'rank': return sorted(list_data, key=lambda x: x['rank'], reverse=reverse)
		elif sort_key == 'added': return sorted(list_data, key=lambda x: x['listed_at'], reverse=reverse)
#		elif sort_key == 'title': return sorted(list_data, key=lambda x: title_key(x[x['type']].get('title'), ignore_articles), reverse=reverse)
		elif sort_key == 'title': return sorted(list_data, key=lambda x: title_key(x['movie' if x['type'] == 'movie' else 'show'].get('title'), ignore_articles), reverse=reverse)
		elif sort_key == 'released': return sorted(list_data, key=lambda x: released_key(x[x['type']]), reverse=reverse)
		elif sort_key == 'runtime': return sorted(list_data, key=lambda x: x[x['type']].get('runtime', 0), reverse=reverse)
		elif sort_key == 'popularity': return sorted(list_data, key=lambda x: x[x['type']].get('votes', 0), reverse=reverse)
		elif sort_key == 'percentage': return sorted(list_data, key=lambda x: x[x['type']].get('rating', 0), reverse=reverse)
		elif sort_key == 'votes': return sorted(list_data, key=lambda x: x[x['type']].get('votes', 0), reverse=reverse)
		elif sort_key == 'random': return sorted(list_data, key=lambda k: random.random())
		else: return list_data
	except: return list_data

def paginate_list(item_list, page, limit=20):
	if not item_list: return item_list, page
	pages = list(chunks(item_list, limit))
	total_pages = len(pages)
	return pages[page - 1], total_pages

