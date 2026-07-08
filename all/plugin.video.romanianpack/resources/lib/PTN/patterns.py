#!/usr/bin/env python
# -*- coding: utf-8 -*-

patterns = [
    ('season', (r'[\. ]((?:Complete.)?s[0-9]{2}-s[0-9]{2}|'
                r's([0-9]{1,2})(?:e[0-9]{2})?|'
                r'([0-9]{1,2})x[0-9]{2})(?:[\. ]|$)')),
    ('episode', (r'((?:[ex]|ep)([0-9]{2})(?:[^0-9]|$))')),
    ('year', (r'([\[\(]?((?:19[0-9]|20[0123])[0-9])[\]\)]?)')),
    ('resolution', (r'([0-9]{3,4}p|1280x720)')),
    ('quality', (r'((?:PPV\.)?[HP]DTV|(?:HD)?CAM|B[DR]Rip|(?:HD-?)?TS|'
                 r'(?:PPV )?WEB-?DL(?: DVDRip)?|HDRip|HDTVRip|DVDRip|DVDRIP|'
                 r'CamRip|W[EB]BRip|BluRay|DvDScr|hdtv|telesync)')),
    ('codec', (r'(xvid|[hx]\.?26[45])')),
    ('audio', (r'(MP3|DD5\.?1|Dual[\- ]Audio|LiNE|DTS|'
               r'AAC[.-]LC|AAC(?:\.?2\.0)?|'
               r'AC3(?:\.5\.1)?)')),
    ('group', r'(- ?([^-]+(?:-={[^-]+-?$)?))$'),
    ('region', r'R[0-9]'),
    ('extended', r'(EXTENDED(:?.CUT)?)'),
    ('hardcoded', 'HC'),
    ('proper', 'PROPER'),
    ('repack', 'REPACK'),
    ('container', r'(MKV|AVI|MP4)'),
    ('widescreen', 'WS'),
    ('website', r'^(\[ ?([^\]]+?) ?\])'),
    ('language', r'(rus\.eng|ita\.eng)'),
    ('subtitles', r'(DKsubs)'),
    ('sbs', r'(?:Half-)?SBS'),
    ('unrated', 'UNRATED'),
    ('size', r'(\d+(?:\.\d+)?(?:GB|MB))'),
    ('3d', '3D')
]

types = {
    'season': 'integer',
    'episode': 'integer',
    'year': 'integer',
    'extended': 'boolean',
    'hardcoded': 'boolean',
    'proper': 'boolean',
    'repack': 'boolean',
    'widescreen': 'boolean',
    'unrated': 'boolean',
    '3d': 'boolean'
}
