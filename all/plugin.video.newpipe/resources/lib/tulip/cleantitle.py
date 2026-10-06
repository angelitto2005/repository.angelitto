# -*- coding: utf-8 -*-

'''
    Tulip library
    Author Twilight0

    SPDX-License-Identifier: GPL-3.0-only
    See LICENSES/GPL-3.0-only for more information.
'''

import re
import unicodedata
from html import unescape


def get(title, lower=True):

    if title is None:
        return

    title = re.sub(r'&#(\d+);', '', title)
    title = re.sub(r'(&#[0-9]+)([^;^0-9]+)', '\\1;\\2', title)
    title = re.sub(r'\n|([[].+?[]])|([(].+?[)])|\s(vs|v[.])\s|([:;\-,\'\s.?])|\s', '', title)

    if lower:

        title = title.lower()

    return title


def query(title):

    if title is None:
        return

    title = title.replace("'", '').rsplit(':', 1)[0]

    return title


def normalize(title):

    if not title:
        return title

    try:
        if isinstance(title, bytes):
            title = title.decode('utf-8', 'ignore')
        return unicodedata.normalize('NFKD', title).encode('ascii', 'ignore').decode('utf-8')
    except Exception:
        return title


def strip_accents(string):

    result = ''.join(c for c in unicodedata.normalize('NFD', string) if unicodedata.category(c) != 'Mn')

    return result


def stripTags(html):

    sub_start = html.find("<")
    sub_end = html.find(">")
    while sub_end > sub_start > -1:
        html = html.replace(html[sub_start:sub_end + 1], "").strip()
        sub_start = html.find("<")
        sub_end = html.find(">")

    return html


def replaceHTMLCodes(txt):

    if not txt:
        return txt

    txt = re.sub(r'(&#[0-9]+)([^;^0-9]+)', r'\1;\2', txt)
    txt = unescape(txt)
    txt = txt.replace('&#8482;', '(TM)').replace('&#169;', '(c)').replace('&#174;', '(r)')

    return txt


__all__ = ['get', 'replaceHTMLCodes', 'query', 'normalize', 'strip_accents', 'stripTags']
