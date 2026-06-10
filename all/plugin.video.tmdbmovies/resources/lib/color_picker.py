import os
import json
import xbmcgui
import xbmcaddon

def _load_colors():
    try:
        p = os.path.join(os.path.dirname(__file__), 'json', 'colors.json')
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return []

def _find_index_by_value(colors, val):
    for i, c in enumerate(colors):
        if c['name'] == val or c['hex'] == val:
            return i
    return -1

def pick_color(setting_id):
    if not setting_id:
        return
    colors = _load_colors()
    if not colors:
        xbmcgui.Dialog().notification('Error', 'colors.json not found', xbmcgui.NOTIFICATION_ERROR)
        return

    current_val = xbmcaddon.Addon('plugin.video.tmdbmovies').getSetting(setting_id)
    current_idx = -1
    if current_val.startswith('[COLOR '):
        name = current_val.split('[/COLOR]')[0].split('■ ', 1)[-1] if '■ ' in current_val else ''
        current_idx = _find_index_by_value(colors, name)
    elif current_val.startswith('FF') and len(current_val) == 8:
        current_idx = _find_index_by_value(colors, current_val)
    elif current_val.isdigit():
        try: current_idx = int(current_val)
        except: pass
    else:
        current_idx = _find_index_by_value(colors, current_val)

    names = [f'[COLOR {c["hex"]}]■ {c["name"]}[/COLOR]' for c in colors]
    if current_idx >= 0:
        try:
            idx = xbmcgui.Dialog().select(f'Choose color for {setting_id}', names, preselect=current_idx)
        except TypeError:
            idx = xbmcgui.Dialog().select(f'Choose color for {setting_id}', names)
    else:
        idx = xbmcgui.Dialog().select(f'Choose color for {setting_id}', names)

    if idx >= 0:
        c = colors[idx]
        display_val = f'[COLOR {c["hex"]}]■ {c["name"]}[/COLOR]'
        xbmcaddon.Addon('plugin.video.tmdbmovies').setSetting(setting_id, display_val)
        pass
