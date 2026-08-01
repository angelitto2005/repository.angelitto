from pathlib import Path
import sys
import xbmc

addon_root = str(Path(__file__).parent.parent.parent)
if addon_root not in sys.path:
    sys.path.insert(0, addon_root)

if __name__ == '__main__':
    from entry import run_plugin
    run_plugin()
    # RLI fix: prevent stale interpreter when container changes to another addon
    # (skip pentru modurile background invocate din Settings — RunPlugin nu are
    # container tmdbmovies; SystemExit aici omoară thread-ul de sync din
    # clear_provider_cache înainte să apuce să ruleze)
    try:
        _is_bg = len(sys.argv) > 2 and 'clear_provider_cache' in sys.argv[2]
        if not _is_bg:
            plugin_name = xbmc.getInfoLabel('Container.PluginName') or ''
            if plugin_name and 'tmdbmovies' not in plugin_name.lower():
                raise SystemExit()
    except SystemExit:
        raise
    except:
        pass
