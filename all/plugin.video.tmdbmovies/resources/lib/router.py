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
    try:
        plugin_name = xbmc.getInfoLabel('Container.PluginName') or ''
        if plugin_name and 'tmdbmovies' not in plugin_name.lower():
            raise SystemExit()
    except SystemExit:
        raise
    except:
        pass
