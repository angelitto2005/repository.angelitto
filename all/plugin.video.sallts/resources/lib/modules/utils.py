import re
import time
import random
import hashlib
import unicodedata
import _strptime  # fix bug in python import
from queue import SimpleQueue
from html import unescape
from importlib import import_module
from datetime import datetime, timedelta, date
from modules.kodi_utils import local_string as ls, get_setting, logger
# from modules.kodi_utils import logger

days_translate = {'Monday': 32971, 'Tuesday': 32972, 'Wednesday': 32973, 'Thursday': 32974, 'Friday': 32975, 'Saturday': 32976, 'Sunday': 32977}

class TaskPool:
	@staticmethod
	def process(_threads):
		for index, i in enumerate(_threads, 1):
			try: i.start()
			except Exception as e: logger('thread error', f"{index}: {e}")
			else: yield i

	def __init__(self, maxsize=None):
		self.maxsize = maxsize or int(get_setting('salts.max_threads', '100'))
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

def jsondate_to_datetime(jsondate_object, resformat, remove_time=False):
	if remove_time: datetime_object = datetime_workaround(jsondate_object, resformat).date()
	else: datetime_object = datetime_workaround(jsondate_object, resformat)
	return datetime_object

def get_datetime(string=False, dt=False):
	d = datetime.now()
	if dt: return d
	if string: return d.strftime('%Y-%m-%d')
	return datetime.date(d)

def adjust_premiered_date(orig_date, adjust_hours):
	if not orig_date: return None, None
	orig_date += ' 20:00:00'
	datetime_object = jsondate_to_datetime(orig_date, '%Y-%m-%d %H:%M:%S')
	adjusted_datetime = datetime_object + timedelta(hours=adjust_hours)
	adjusted_string = adjusted_datetime.strftime('%Y-%m-%d')
	return adjusted_datetime.date(), adjusted_string

def make_day(today, date, date_format, use_words=True):
	day_diff = (date - today).days
	try: day = date.strftime(date_format)
	except ValueError: day = date.strftime('%Y-%m-%d')
	if use_words:
		if day_diff == -1: day = ls(32848).upper()
		elif day_diff == 0: day = ls(32849).upper()
		elif day_diff == 1: day = ls(32850).upper()
		elif 1 < day_diff < 7: day = ls(days_translate[date.strftime('%A')])
	return day

def subtract_dates(date1, date2):
	return (date1 - date2).days
	return day

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
	''' born and died are str objects e.g. '1972-05-28' '''
	born = datetime_workaround(born, str_format)
	if not died: today = date.today()
	else: today = datetime_workaround(died, str_format)
	return today.year - born.year - ((today.month, today.day) < (born.month, born.day))

def batch_replace(s, replace_info):
	for r in replace_info:
		s = str(s).replace(r[0], r[1])
	return s

def clean_file_name(s, use_encoding=False, use_blanks=True):
	try:
		hex_entities = [['&#x26;', '&'], ['&#x27;', '\''], ['&#xC6;', 'AE'], ['&#xC7;', 'C'],
					['&#xF4;', 'o'], ['&#xE9;', 'e'], ['&#xEB;', 'e'], ['&#xED;', 'i'],
					['&#xEE;', 'i'], ['&#xA2;', 'c'], ['&#xE2;', 'a'], ['&#xEF;', 'i'],
					['&#xE1;', 'a'], ['&#xE8;', 'e'], ['%2E', '.'], ['&frac12;', '%BD'],
					['&#xBD;', '%BD'], ['&#xB3;', '%B3'], ['&#xB0;', '%B0'], ['&amp;', '&'],
					['&#xB7;', '.'], ['&#xE4;', 'A'], ['\xe2\x80\x99', '']]
		special_encoded = [['"', '%22'], ['*', '%2A'], ['/', '%2F'], [':', ','], ['<', '%3C'],
							['>', '%3E'], ['?', '%3F'], ['\\', '%5C'], ['|', '%7C']]

		special_blanks = [['"', ' '], ['/', ' '], [':', ''], ['<', ' '],
							['>', ' '], ['?', ' '], ['\\', ' '], ['|', ' '], ['%BD;', ' '],
							['%B3;', ' '], ['%B0;', ' '], ["'", ""], [' - ', ' '], ['.', ' '],
							['!', ''], [';', ''], [',', '']]
		s = batch_replace(s, hex_entities)
		if use_encoding: s = batch_replace(s, special_encoded)
		if use_blanks: s = batch_replace(s, special_blanks)
		s = s.strip()
	except: pass
	return s

def clean_title(title):
	try:
		if not title: return
		title = title.lower()
		title = re.sub(r'&#(\d+);', '', title)
		title = re.sub(r'(&#[0-9]+)([^;^0-9]+)', '\\1;\\2', title)
		title = re.sub(r'(&#[0-9]+)([^;^0-9]+)', '\\1;\\2', title)
		title = title.replace('&quot;', '\"').replace('&amp;', '&')
		title = re.sub(r'\n|([\[({].+?[})\]])|([:;–\-"\',!_.?~$@])|\s', '', title)
	except: pass
	return title

def byteify(data, ignore_dicts=False):
	try:
		if isinstance(data, unicode): return data.encode('utf-8')
		if isinstance(data, list): return [byteify(item, ignore_dicts=True) for item in data]
		if isinstance(data, dict) and not ignore_dicts:
			return dict([(byteify(key, ignore_dicts=True), byteify(value, ignore_dicts=True)) for key, value in data.iteritems()])
	except: pass
	return data

def normalize(txt):
	txt = re.sub(r'[^\x00-\x7f]',r'', txt)
	return txt

def safe_string(obj):
	try:
		try: return str(obj)
		except UnicodeEncodeError: return obj.encode('utf-8', 'ignore').decode('ascii', 'ignore')
		except: return ""
	except: return obj

def remove_accents(obj):
	try:
		try: obj = u'%s' % obj
		except: pass
		obj = ''.join(c for c in unicodedata.normalize('NFD', obj) if unicodedata.category(c) != 'Mn')
	except: pass
	return obj

def regex_from_to(text, from_string, to_string, excluding=True):
	if excluding: r = re.search(r"(?i)" + from_string + r"([\S\s]+?)" + to_string, text).group(1)
	else: r = re.search(r"(?i)(" + from_string + r"[\S\s]+?" + to_string + ")", text).group(1)
	return r

def regex_get_all(text, start_with, end_with):
	r = re.findall(r"(?i)(" + start_with + r"[\S\s]+?" + end_with + ")", text)
	return r

def replace_html_codes(txt):
	txt = re.sub(r"(&#[0-9]+)([^;^0-9]+)", "\\1;\\2", txt)
	txt = unescape(txt)
	txt = txt.replace("&quot;", "\"")
	txt = txt.replace("&amp;", "&")
	return txt

def gen_file_hash(file):
	try:
		md5_hash = hashlib.md5()
		with open(file, 'rb') as afile:
			buf = afile.read()
			md5_hash.update(buf)
			return md5_hash.hexdigest()
	except: pass

def sec2time(sec, n_msec=3):
	''' Convert seconds to 'D days, HH:MM:SS.FFF' '''
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

def title_key(title, ignore_articles):
	if not ignore_articles: return title
	try:
		if title is None: title = ''
		match = re.match(r'^(?:the|an|a)\s+(\w.*)', title, re.I)
		if match and match.group(1): title = match.group(1)
	except: pass
	return title

def sort_for_article(_list, _key, ignore_articles):
	if not ignore_articles: _list.sort(key=lambda k: k[_key])
	else: _list.sort(key=lambda k: re.sub(r'(^the |^a |^an )', '', k[_key].lower()))
	return _list

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

def paginate_list(item_list, page, letter, limit=20):
	def _get_start_index(letter):
		if letter == 't':
			try:
				beginswith_tuple = ('s', 'the s', 'a s', 'an s')
				indexes = [i for i, v in enumerate(title_list) if v.startswith(beginswith_tuple)]
				start_index = indexes[-1:][0] + 1
			except: start_index = None
		else:
			beginswith_tuple = (letter, 'the %s' % letter, 'a %s' % letter, 'an %s' % letter)
			try: start_index = next(i for i, v in enumerate(title_list) if v.startswith(beginswith_tuple))
			except: start_index = None
		return start_index
	if letter != 'None':
		from itertools import chain, zip_longest
		title_list = [i['title'].lower() for i in item_list]
		start_list = [chr(i) for i in range(97, 123)]
		letter_index = start_list.index(letter)
		base_list = [element for element in list(chain.from_iterable([val for val in zip_longest(start_list[letter_index:], start_list[:letter_index][::-1])])) if element != None]
		for i in base_list:
			start_index = _get_start_index(i)
			if start_index: break
		item_list = item_list[start_index:]
	if not item_list: return item_list, page
	pages = list(chunks(item_list, limit))
	total_pages = len(pages)
	return pages[page - 1], total_pages

def make_title_slug(name):
	name = name.strip()
	name = name.lower()
	name = re.sub('[^a-z0-9_]', '-', name)
	name = re.sub('--+', '-', name)
	return name

