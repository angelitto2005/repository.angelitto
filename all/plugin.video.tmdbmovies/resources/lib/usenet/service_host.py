"""Starts the Usenet HTTP server inside the add-on service.

Called once from run_service(): the server has to outlive any single plugin
call, because Kodi keeps reading the stream for the whole film.
"""

# daemon guard: nothing we start may hold Kodi open at exit (AGENTS.md pattern)
try:
    from resources.lib.core.daemon_guard import install as _install_daemon_guard
    _install_daemon_guard()
except Exception:
    pass



def start():
    from . import config, server
    if not config.enabled():
        return False
    if not config.providers():
        return False
    started = server.start()
    try:
        import xbmc
        if started:
            xbmc.log('[TMDb Movies] [Usenet] local server listening on 127.0.0.1:%d' % server.port(),
                     xbmc.LOGINFO)
        else:
            xbmc.log('[TMDb Movies] [Usenet] no free port for the local server', xbmc.LOGERROR)
    except Exception:
        pass
    return started

def stop():
    """Called when the service ends: Kodi must not wait for us."""
    try:
        from . import server
        server.stop()
    except Exception:
        pass
