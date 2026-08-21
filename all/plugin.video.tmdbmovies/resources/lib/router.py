from pathlib import Path
import sys
import xbmc

addon_root = str(Path(__file__).parent.parent.parent)
if addon_root not in sys.path:
    sys.path.insert(0, addon_root)

if __name__ == '__main__':
    # Timestamp de navigare: citit de background_warmup ca sa se auto-opreasca
    # cand userul navigheaza (warmup-ul ocupa slotul de script si toate
    # click-urile asteapta la coada pina termina — spinner infinit).
    try:
        import time as _t
        import xbmcgui as _xg
        _xg.Window(10000).setProperty('tmdbmovies_last_nav_ts', str(_t.time()))
    except Exception:
        pass
    # Breadcrumb pe fiecare invocare — doar la LOGDEBUG (apare cu debug
    # logging enabled in Kodi; log-ul normal ramane curat).
    try:
        xbmc.log("[ROUTER] invoke argv1={} argv2={}".format(
            sys.argv[0][-40:], (sys.argv[2][:120] if len(sys.argv) > 2 else '')),
            xbmc.LOGDEBUG)
    except Exception:
        pass
    # GIL responsiveness (vezi run_service din entry.py): interval implicit
    # 5ms lasa thread-urile de sync sa tina GIL-ul in portii lungi si
    # evenimentele GUI de container raman neprocesate (spinner infinit).
    try:
        if sys.getswitchinterval() > 0.002:
            sys.setswitchinterval(0.001)
    except Exception:
        pass
    from entry import run_plugin
    run_plugin()
    # RLI fix: prevent stale interpreter when container changes to another addon
    # (skip pentru modurile background invocate din Settings — RunPlugin nu are
    # container tmdbmovies; SystemExit aici omoara thread-ul de sync din
    # clear_provider_cache inainte sa apuce sa ruleze)
    try:
        _is_bg = len(sys.argv) > 2 and 'clear_provider_cache' in sys.argv[2]
        if not _is_bg:
            # Instrumentare blocaj-post-randare — LOGDEBUG (invizibil normal).
            plugin_name = xbmc.getInfoLabel('Container.PluginName') or ''
            xbmc.log("[ROUTER] post-plugin: PluginName={!r}".format(plugin_name), xbmc.LOGDEBUG)
            if plugin_name and 'tmdbmovies' not in plugin_name.lower():
                xbmc.log("[ROUTER] post-plugin: stale interpreter -> SystemExit", xbmc.LOGDEBUG)
                raise SystemExit()
    except SystemExit:
        raise
    except Exception as _e:
        xbmc.log("[ROUTER] post-plugin error: {!r}".format(_e), xbmc.LOGERROR)
