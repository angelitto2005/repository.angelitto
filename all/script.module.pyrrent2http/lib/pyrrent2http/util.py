import sys
import socket
import chardet
import os
from . import MediaType
import mimetypes
import urlparse, urllib

SUBTITLES_FORMATS = ['.aqt', '.gsub', '.jss', '.sub', '.ttxt', '.pjs', '.psb', '.rt', '.smi', '.stl',
                         '.ssf', '.srt', '.ssa', '.ass', '.usf', '.idx']

class Struct(dict):
    def __getattr__(self, attr):
        return self[attr]
    def __setattr__(self, attr, value):
        self[attr] = value

def uri2path(uri):
    if uri[1] == ':' and sys.platform.startswith('win'):
        uri = 'file:///' + uri
    fileUri = urlparse.urlparse(uri)
    if fileUri.scheme == 'file':
        uriPath = fileUri.path
        if uriPath != '' and sys.platform.startswith('win') and (os.path.sep == uriPath[0] or uriPath[0] == '/'):
            uriPath = uriPath[1:]
    absPath = os.path.abspath(urllib.unquote(uriPath))
    return localize_path(absPath)

def detect_media_type(name):
    ext = os.path.splitext(name)[1]
    if ext in SUBTITLES_FORMATS:
        return MediaType.SUBTITLES
    else:
        mime_type = mimetypes.guess_type(name)[0]
        if not mime_type:
            return MediaType.UNKNOWN
        mime_type = mime_type.split("/")[0]
        if mime_type == 'audio':
            return MediaType.AUDIO
        elif mime_type == 'video':
            return MediaType.VIDEO
        else:
            return MediaType.UNKNOWN
def unicode_msg(tmpl, args):
    msg = isinstance(tmpl, unicode) and tmpl or tmpl.decode(chardet.detect(tmpl)['encoding'])
    arg_ = []
    for a in args:
        arg_.append(isinstance(a, unicode) and a or a.decode(chardet.detect(a)['encoding']))
    return msg % tuple(arg_)

def encode_msg(msg):
    msg = isinstance(msg, unicode) and msg.encode(sys.getfilesystemencoding() != 'ascii' and sys.getfilesystemencoding() or 'utf-8') or msg
    return msg
    

def localize_path(path):
    if not isinstance(path, unicode): path = path.decode(chardet.detect(path)['encoding'])
    if not sys.platform.startswith('win'):
        path = path.encode((sys.getfilesystemencoding() not in ('ascii', 'ANSI_X3.4-1968')) and sys.getfilesystemencoding() or 'utf-8')
    return path

def can_bind(host, port):
    """
    Checks we can bind to specified host and port

    :param host: Host
    :param port: Port
    :return: True if bind succeed
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind((host, port))
        s.close()
    except socket.error:
        return False
    return True


def find_free_port(host):
    """
    Finds free TCP port that can be used for binding

    :param host: Host
    :return: Free port
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind((host, 0))
        port = s.getsockname()[1]
        s.close()
    except socket.error:
        return False
    return port


def ensure_fs_encoding(string):
    if isinstance(string, str):
        string = string.decode('utf-8')
    return string.encode(sys.getfilesystemencoding() or 'utf-8')
