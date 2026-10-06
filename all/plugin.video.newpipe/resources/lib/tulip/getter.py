# -*- coding: utf-8 -*-

'''
    Tulip library
    Author Twilight0

    SPDX-License-Identifier: GPL-3.0-only
    See LICENSES/GPL-3.0-only for more information.
'''


import os.path
import urllib.request as urllib2
import time
import m3u8
from useragents import get_ua
from tulip.utils import percent, url2name, iteritems
from tulip import kodi
from urllib.parse import urlparse, parse_qsl


def retriever(source, destination, user_agent=None, referer=None, reporthook=None, data=None, **kwargs):

    if user_agent is None:
        user_agent = get_ua()

    if referer is None:
        referer = '{0}://{1}/'.format(urlparse(source).scheme, urlparse(source).netloc)

    headers = {'User-Agent': user_agent, 'Accept': '*/*', 'Referer': referer}
    if kwargs:
        headers.update(kwargs)

    req = urllib2.Request(source, data=data, headers=headers)
    with urllib2.urlopen(req) as resp, open(destination, 'wb') as out_file:
        filesize = int(resp.headers.get('Content-Length', -1))
        blocksize = 8192
        numblocks = 0
        if reporthook:
            reporthook(numblocks, blocksize, filesize)
        while True:
            chunk = resp.read(blocksize)
            if not chunk:
                break
            out_file.write(chunk)
            numblocks += 1
            if reporthook:
                reporthook(numblocks, blocksize, filesize)


def download_media(
        url, output_folder, filename=None, heading=kodi.name(),
        line1='Downloading...[CR]%.02f MB of %.02f MB[CR]Speed: %.02f Kb/s'
):

    with kodi.ProgressDialog(heading, line1=line1) as pd:

        user_agent = get_ua()

        if not os.path.exists(output_folder):
            os.makedirs(output_folder)

        if not filename:
            filename = url2name(url)
        elif not filename.endswith(('.mp4', '.mkv', '.flv', '.avi', '.mpg', '.m4v')):
            filename += '.mp4'

        destination = os.path.join(output_folder, filename)

        if '|' in url:
            url, _, head = url.rpartition('|')
            headers = dict(parse_qsl(head))
            user_agent = headers['User-Agent']
            if 'Referer' in headers:
                referer = headers['Referer']
            else:
                referer = '{0}://{1}/'.format(urlparse(url).scheme, urlparse(url).netloc)
        else:
            referer = '{0}://{1}/'.format(urlparse(url).scheme, urlparse(url).netloc)

        start_time = time.time()

        try:
            retriever(
                url, destination, user_agent=user_agent, referer=referer,
                reporthook=lambda numblocks, blocksize, filesize: _pbhook(
                    numblocks, blocksize, filesize, pd, start_time, line1
                )
            )
        except Exception:
            pd.update(100, 'Cancelled')


def _pbhook(numblocks, blocksize, filesize, pd, start_time, line1):

    _percent = min(numblocks * blocksize * 100 / filesize, 100)
    _percent = int(_percent)
    currently_downloaded = float(numblocks) * blocksize / (1024 * 1024)
    kbps_speed = numblocks * blocksize / (time.time() - start_time)

    if kbps_speed > 0:
        eta = (filesize - numblocks * blocksize) / kbps_speed
    else:
        eta = 0

    kbps_speed = kbps_speed / 1024
    total = float(filesize) / (1024 * 1024)
    line1 = line1 % (currently_downloaded, total, kbps_speed)
    line1 += ' - ETA: %02d:%02d' % divmod(eta, 60)
    pd.update(_percent, line1)

    if pd.is_canceled():
        raise Exception


class M3U8:

    def __init__(self, url, headers=None, heading=''):

        self.url = url
        self.headers = headers
        self.heading = heading

    def stream_picker(self, qualities, urls):

        if not self.heading:
            heading = 'Select a quality'
        else:
            heading = self.heading

        _choice = kodi.selectDialog(heading=heading, list=qualities)

        # noinspection PyInconsistentReturns
        if _choice <= len(qualities) and not _choice == -1:
            self.url = urls[_choice]
            return self.url

    def m3u8_picker(self):

        try:

            if '|' not in self.url or self.headers is None:
                raise TypeError

            if '|' in self.url:

                link, _, head = self.url.rpartition('|')
                headers = dict(parse_qsl(head))
                streams = m3u8.load(link, headers=headers).playlists

            else:

                streams = m3u8.load(self.url, headers=self.headers).playlists

        except TypeError:

            streams = m3u8.load(self.url).playlists

        if not streams:
            return self.url

        qualities = []
        urls = []

        for stream in streams:

            quality = repr(stream.stream_info.resolution).strip('()').replace(', ', 'x')

            if quality == 'None':
                quality = 'Auto'

            uri = stream.absolute_uri

            qualities.append(quality)

            try:

                if '|' not in self.url:
                    raise TypeError

                urls.append(uri + ''.join(self.url.rpartition('|')[1:]))

            except TypeError:
                urls.append(uri)

        if len(qualities) == 1:

            return self.url

        else:

            return self.stream_picker(qualities, urls)

    def downloader(self, output_folder, filename=None, heading='', line1='', pd_dialog='Downloading segment {0} from {1}'):

        if not os.path.exists(output_folder):
            os.makedirs(output_folder)

        if not heading:
            heading = 'Downloading ts segments'

        url = self.m3u8_picker()

        if '|' in url:

            url, _, head = url.rpartition('|')
            headers = dict(parse_qsl(head))

        elif self.headers:

            headers = self.headers

        else:

            headers = {'User-Agent': get_ua()}

        _m3u8 = m3u8.load(url, headers=headers)

        segments = _m3u8.files

        if not filename:
            filename = os.path.split(urlparse(url).path.replace('m3u8', 'ts'))[1]
        elif not filename.endswith('.ts'):
            filename += '.ts'

        destination = os.path.join(output_folder, filename)

        if os.path.exists(destination):
            pass

        f = open(destination,  'ab')

        with kodi.ProgressDialog(heading=heading, line1=line1) as pd:

            for count, segment in list(enumerate(segments, start=1)):

                if not segment.startswith('http'):
                    segment = ''.join([_m3u8.base_uri, segment])

                req = urllib2.Request(segment)

                for k, v in iteritems(headers):
                    req.add_header(k, v)

                opener = urllib2.urlopen(req)
                data = opener.read()
                f.write(data)

                pd.update(percent=percent(count, len(segments)), line1=pd_dialog.format(count, len(segments)))

                if pd.is_canceled():
                    f.close()
                    break

            f.close()



