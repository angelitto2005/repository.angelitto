import re
from collections import namedtuple
from html.parser import HTMLParser

DomMatch = namedtuple('DOMMatch', ['attrs', 'content'])
re_type = type(re.compile(''))

def parseDOM(html, name='', attrs=None, ret=False):
	results = []
	try:
		# If attrs is passed and has string values, compile them as usual
		if attrs:
			processed_attrs = {}
			for key, value in attrs.items():
				if isinstance(value, str):
					processed_attrs[key] = re.compile(value + ('$' if value else ''))
				else:
					processed_attrs[key] = value
			attrs = processed_attrs

		results = parse_dom(html, name, attrs, ret)

		if ret:
			results = [i.attrs.get(ret.lower(), '') for i in results]
		else:
			results = [i.content for i in results]
	except: pass
	return results

class DOMParser(HTMLParser):
	def __init__(self, target_tag, target_attrs):
		HTMLParser.__init__(self)

		# 1. Handle Tag Sequences (e.g. ['div', 'section', 'article'])
		if isinstance(target_tag, (list, tuple, set)):
			self.target_tags = {i.lower() for i in target_tag}
		else:
			self.target_tags = {target_tag.lower()}

		# 2. Normalize target attributes
		self.target_attrs = {}
		if target_attrs:
			for k, v in target_attrs.items():
				k_lower = k.lower()
				# If the value is already a compiled regex or list/set, preserve it
				if isinstance(v, (re_type, list, tuple, set)):
					self.target_attrs[k_lower] = v
				elif isinstance(v, str):
					self.target_attrs[k_lower] = re.compile(v + ('$' if v else ''))
				else:
					self.target_attrs[k_lower] = v

		self.matches = []
		self.depth = 0
		self.recording = False
		self.recorded_chunks = []
		self.current_attrs = None
		self.active_tag = None  # Track which tag opened the current capture

	def _attr_matches(self, attrs_dict):
		for k, target_val in self.target_attrs.items():
			if k not in attrs_dict:
				return False
			val = attrs_dict[k]

			# Handle Regex Match
			if isinstance(target_val, re_type):
				if not target_val.match(val):
					return False
			# Handle Sequence/List of acceptable attribute strings (OR Match)
			elif isinstance(target_val, (list, tuple, set)):
				current_values = set(val.split(' '))
				# If none of our target values exist in the tag's attribute, fail
				if not any(i in current_values for i in target_val):
					return False
			else:
				# Standard subset match
				temp_target = [target_val] if isinstance(target_val, str) else target_val
				if not set(temp_target) <= set(val.split(' ')):
					return False
		return True

	def handle_starttag(self, tag, attrs):
		tag_lower = tag.lower()
		attrs_dict = {k.lower(): v or '' for k, v in attrs}

		if self.recording:
			if tag_lower == self.active_tag:
				self.depth += 1
			attr_str = ''.join([f' {k}="{v}"' for k, v in attrs])
			self.recorded_chunks.append(f"<{tag}{attr_str}>")
			return

		# Check if tag is in our allowed target_tags sequence
		if tag_lower in self.target_tags and self._attr_matches(attrs_dict):
			self.recording = True
			self.active_tag = tag_lower  # Lock the recording context to this specific tag type
			self.depth = 1
			self.current_attrs = attrs_dict
			self.recorded_chunks = []

	def handle_endtag(self, tag):
		tag_lower = tag.lower()
		if self.recording:
			if tag_lower == self.active_tag:
				self.depth -= 1
				if self.depth == 0:
					self.recording = False
					content = ''.join(self.recorded_chunks)
					self.matches.append(DomMatch(self.current_attrs, content))
					self.active_tag = None
					return
			self.recorded_chunks.append(f"</{tag}>")

	def handle_data(self, data):
		if self.recording:
			self.recorded_chunks.append(data)

	def handle_comment(self, data):
		if self.recording:
			self.recorded_chunks.append(f"<!--{data}-->")

def parse_dom(html, name='', attrs=None, req=False, exclude_comments=False):
	all_results = []
	try:
		if attrs is None: attrs = {}

		# Clean the name(s)
		if isinstance(name, str):
			name = name.strip()
		elif isinstance(name, (list, tuple, set)):
			name = [i.strip() for i in name if isinstance(i, str)]

		if isinstance(html, str) or isinstance(html, DomMatch): html = [html]
		elif not isinstance(html, list): return ''
		if not name: return ''
		if not isinstance(attrs, dict): return ''

		if req:
			if not isinstance(req, list): req = [req]
			req = set([i.lower() for i in req])

		for item in html:
			if isinstance(item, DomMatch):
				item = item.content
			if exclude_comments:
				item = re.sub(r'<!--.*?-->', '', item, flags=re.S)

			parser = DOMParser(name, attrs)
			parser.feed(item)
			results = parser.matches

			if req: results = [i for i in results if req <= set(i.attrs.keys())]

			all_results += results
	except: pass
	return all_results

