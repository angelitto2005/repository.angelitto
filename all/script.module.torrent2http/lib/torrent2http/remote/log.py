try:
    from xbmc import log
except:
    def log(s):
        print(s)
        
import xbmc

import inspect

prefix = 'script.module.torrent2http'

def debug(s, line = None):
    
    try:
        if isinstance(s, BaseException):
            print_tb(s)
        elif isinstance(s, unicode):
            s = s.encode('utf-8')
        elif not isinstance(s, str):
            s = str(s)
    except:
        if isinstance(s, BaseException):
            print_tb(s)
        else:
            s = str(s)

    if prefix:
        if line:
            message = '[%s: %s] %s' % (prefix, str(line), s)
        else:
            message = '[%s]  %s' % (prefix, s)
    else:
        if line:
            message = '[%s]  %s' % (line, s)
        else:
            message = s
            
    log(message)
    

def print_tb(e=None):
    import sys
    exc_type, exc_val, exc_tb = sys.exc_info()
    import traceback
    traceback.print_exception(exc_type, exc_val, exc_tb, limit=10, file=sys.stderr)

    if e:
        debug(str(e))

def lineno():
    """Returns the current line number in our program."""
    return inspect.currentframe().f_back.f_lineno

def logs(msg):
    try:
        xbmc.log("### [%s]: %s" % ('engine',msg,), level=xbmc.LOGDEBUG )
    except UnicodeEncodeError:
        xbmc.log("### [%s]: %s" % ('engine',msg.encode("utf-8", "ignore"),), level=xbmc.LOGDEBUG )
    except:
        xbmc.log("### [%s]: %s" % ('engine','ERROR LOG',), level=xbmc.LOGDEBUG )
