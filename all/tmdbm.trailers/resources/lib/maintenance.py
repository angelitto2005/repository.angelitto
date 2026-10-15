import os
import xml.etree.ElementTree as ET

import xbmc

import config

_PRESERVE_IDS = ('installed_version',)


def _default_xml():
    return os.path.join(config.ADDON_PATH, 'resources', 'settings.xml')


def _profile_xml():
    return os.path.join(config.ADDON_PROFILE, 'settings.xml')


def clean_settings():
    default_xml = _default_xml()
    profile_xml = _profile_xml()
    if not os.path.isfile(default_xml) or not os.path.isfile(profile_xml):
        return False
    try:
        root_default = ET.parse(default_xml).getroot()
        active = {item.get('id') for item in root_default.iter('setting')
                  if item.get('id')}
        tree_profile = ET.parse(profile_xml)
        root_profile = tree_profile.getroot()
        removed = 0
        for item in root_profile.findall('setting'):
            setting_id = item.get('id') or ''
            if setting_id in active or setting_id in _PRESERVE_IDS:
                continue
            root_profile.remove(item)
            removed += 1
        if removed > 0:
            tree_profile.write(profile_xml, encoding='utf-8',
                               xml_declaration=True)
            config.log('[Maintenance] Settings clean: removed {} orphaned '
                       'setting(s).'.format(removed))
            return True
    except Exception as exc:
        config.log('[Maintenance] Settings clean failed: {}'.format(exc),
                   xbmc.LOGERROR)
    return False


def _version_tuple(value):
    try:
        parts = []
        for chunk in str(value or '').strip().split('.'):
            digits = ''
            for char in chunk:
                if char.isdigit():
                    digits += char
                else:
                    break
            parts.append(int(digits) if digits else 0)
        return tuple(parts) if parts else None
    except Exception:
        return None


def check_addon_update():
    try:
        current = config.ADDON.getAddonInfo('version')
    except Exception:
        return False
    try:
        saved = config.ADDON.getSetting('installed_version')
    except Exception:
        saved = ''
    if saved == current:
        return False
    saved_tuple = _version_tuple(saved)
    current_tuple = _version_tuple(current)
    if saved and saved_tuple is not None and current_tuple is not None \
            and saved_tuple > current_tuple:
        config.log('[Maintenance] Downgrade {} -> {}; version saved, '
                   'no cleanup.'.format(saved, current))
    else:
        config.log('[Maintenance] Update {} -> {}; cleaning '
                   'settings.'.format(saved or '?', current))
        clean_settings()
    try:
        config.ADDON.setSetting('installed_version', current)
    except Exception:
        pass
    return True
