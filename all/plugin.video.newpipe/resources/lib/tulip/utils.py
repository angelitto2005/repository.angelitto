# -*- coding: utf-8 -*-

'''
    Tulip library
    Author Twilight0

    SPDX-License-Identifier: GPL-3.0-only
    See LICENSES/GPL-3.0-only for more information.
'''

import os
from tulip import cleantitle, kodi
from tulip.log import log
from os.path import basename
from urllib.parse import unquote, urlsplit, urlparse, urlunparse, quote, urlencode, parse_qsl
from http import client as httplib


def read_file(path, line_by_line=False, reverse=False, encoding='utf-8'):

    f = None
    try:
        f = open(path, 'r', encoding=encoding)
        if line_by_line:
            text = [i.rstrip('\n') for i in f.readlines()]
            if reverse:
                text = text[::-1]
        else:
            text = f.read()
        return text
    finally:
        if f is not None:
            f.close()


def trim_content(path, trim_size=10, encoding='utf-8'):

    """
    Keeps a file with records line by line to certain limit.
    Adds a new line to the bottom and has new items on top
    """

    f = None
    try:
        f = open(path, 'r', encoding=encoding)
        text = [i.rstrip('\n') for i in f.readlines()][::-1]
    finally:
        if f is not None:
            f.close()

    if len(text) > trim_size:
        f = None
        try:
            f = open(path, 'w', encoding='utf-8')
            dif = trim_size - len(text)
            result = text[:dif][::-1]
            f.write('\n'.join(result) + '\n')
        finally:
            if f is not None:
                f.close()


def add_to_file(path, text, trim_file=True, encoding='utf-8'):

    """
    Adds a record as a new line to a file
    """

    if not text:
        return

    f = None
    try:
        f = open(path, 'r', encoding=encoding)
        if text + '\n' in f.readlines():
            return
    except IOError:
        log('File {0} does not exist, creating new...'.format(os.path.basename(path)))
    finally:
        if f is not None:
            f.close()

    f = None
    try:
        f = open(path, 'a', encoding='utf-8')
        f.writelines(text + '\n')
    finally:
        if f is not None:
            f.close()

    if trim_file:
        trim_content(path=path)


def process_file(path, text, mode='remove', cleanse=True, refresh_container=True, heading=''):

    """
    This function can change a record to a file of records in a line by line (for instance a csv file)
    """

    f = None
    try:
        f = open(path, 'r', encoding='utf-8')
        lines = f.readlines()
    finally:
        if f is not None:
            f.close()

    if text + '\n' in lines:
        if mode == 'change':
            idx = lines.index(text + '\n')
            search_type, _, search_term = lines[idx].strip('\n').partition(',')
            str_input = kodi.inputDialog(heading=heading, default=search_term)
            if cleanse:
                str_input = cleantitle.strip_accents(str_input)
            lines[idx] = ','.join([search_type, str_input]) + '\n'
        else:
            lines.remove(text + '\n')
    else:
        return

    f = None
    try:
        f = open(path, 'w', encoding='utf-8')
        f.write(''.join(lines))
    finally:
        if f is not None:
            f.close()

    if refresh_container:
        kodi.refresh()


def single_picker(items, heading=None):

    """
    Selects an item from a list of items with select dialog
    """

    if not heading:
        heading = 'Choose an item'

    if isinstance(items[0], tuple):
        items = [item[0] for item in items]

    choice = kodi.selectDialog(heading=heading, list=items)

    # noinspection PyInconsistentReturns
    if choice <= len(items) and not choice == -1:
        popped = items[choice]
        if isinstance(popped, tuple):
            popped = popped[1]
            return popped
        else:
            return popped


def duration_converter(duration):

    """
    Converts duration in string (minutes:seconds) to integer in seconds
    """

    result = duration.split(':')

    result = int(result[0]) * 60 + int(result[1])

    return result


def percent(count, total):

    return min(int(round(count * 100 / total)), 100)


def py3_dec(d, encoding='utf-8'):

    if isinstance(d, bytes):
        d = d.decode(encoding)

    return d


def enum(**enums):

    try:
        return type(b'Enum', (), enums)
    except TypeError:
        return type('Enum', (), enums)


def list_divider(items_list, chunks):

    """
    This function can split a list into smaller parts.
    Can help creating pages
    """

    return [items_list[i:i + chunks] for i in range(0, len(items_list), chunks)]


def merge_dicts(d1, d2):

    d = d1.copy()
    d.update(d2)

    return d


def quote_paths(url):

    """
    This function will quote paths **only** in a given url
    :param url: string or unicode
    :return: joined url string
    """

    try:

        if url.startswith('http'):

            parsed = urlparse(url)
            processed_path = '/'.join([quote(i) for i in parsed.path.split('/')])
            url = urlunparse(parsed._replace(path=processed_path))

            return url

        else:

            path = '/'.join([quote(i) for i in url.split('/')])
            return path

    except Exception:

        return url


def form_data_conversion(form_data):

    if isinstance(form_data, dict):
        return urlencode(form_data)
    elif isinstance(form_data, str):
        return dict(parse_qsl(form_data))
    else:
        pass


def url2name(url):

    if '|' in url:
        url = url.split('|')[0]
    return basename(unquote(urlsplit(url)[2]))


def iteritems(d, **kw):

    return iter(d.items(**kw))



def check_connection(url="1.1.1.1", timeout=3):

    conn = httplib.HTTPConnection(url, timeout=timeout)

    try:

        conn.request("HEAD", "/")
        conn.close()

        return True

    except Exception as e:

        log(e)

        return False


def parse_headers(string):
    """
    Converts a multi-line response/request headers string into a dictionary
    :param string: string of headers
    :return: dictionary of response headers
    """

    headers = dict([line.partition(': ')[::2] for line in string.splitlines()])

    return headers


def convert_to_bool(val) -> bool:

    try:
        val = val.lower()
    except AttributeError:
        pass

    if val in ('y', 'yes', 't', 'true', 'on', '1', 1, True):
        return True
    elif val in ('n', 'no', 'f', 'false', 'off', '0', 0, False, None):
        return False
    else:
        raise ValueError(f"invalid truth value {val!r}")
