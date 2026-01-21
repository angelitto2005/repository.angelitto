# -*- coding: utf-8 -*-
import xbmc, xbmcgui, xbmcvfs
import os, sys, re, json, urllib.parse, urllib.request

# Modificat pentru a suporta o listă de chei în key.py
try:
    from .key import api_keys as backup_keys
except ImportError:
    try:
        import key
        backup_keys = key.api_keys 
    except:
        try:
            from .key import api_key as b_key
            backup_keys = [b_key]
        except:
            backup_keys = []

def translate_batch(texts, target_lang, api_key):
    try:
        base_url = "https://translation.googleapis.com/language/translate/v2?key=" + api_key
        payload = {'q': texts, 'target': target_lang, 'format': 'text'}
        body = json.dumps(payload).encode('utf-8')
        headers = {'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
        req = urllib.request.Request(base_url, data=body, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=15) as r:
            res_data = json.loads(r.read().decode('utf-8'))
            return [t['translatedText'] for t in res_data['data']['translations']]
    except urllib.error.HTTPError as e:
        return "ERROR_KEY"
    except:
        return None

def run_translation(sub_addon_id):
    import xbmcaddon
    _addon = xbmcaddon.Addon(sub_addon_id)
    
    # --- VERIFICARE DACĂ ROBOTUL ESTE ACTIVAT ---
    if _addon.getSetting('robot_activat') != 'true':
        return

    all_keys = []
    k1 = _addon.getSetting('api_key_google')
    if k1: all_keys.append(k1)
    
    for i in range(2, 6):
        kn = _addon.getSetting('api_key_%d' % i)
        if kn and kn not in all_keys:
            all_keys.append(kn)
            
    for k in backup_keys:
        if k and k not in all_keys:
            all_keys.append(k)

    if not all_keys:
        xbmcgui.Dialog().ok("Eroare", "Nu s-a găsit nicio cheie API!")
        return

    langs = ["ro", "en", "es", "fr", "de", "it", "hu", "pt", "ru", "tr", "bg", "el", "pl", "cs", "nl"]
    try:
        idx = _addon.getSettingInt('subs_languages')
        target_lang = langs[idx]
    except:
        target_lang = "ro"

    profile_path = xbmcvfs.translatePath('special://profile/addon_data/%s/' % sub_addon_id)
    _, files = xbmcvfs.listdir(profile_path)
    srt_files = [f for f in files if f.lower().endswith('.srt') and not f.startswith('robot_tradus')]

    if not srt_files: return

    sub_path = os.path.join(profile_path, srt_files[0])

    try:
        f = xbmcvfs.File(sub_path); content = f.read(); f.close()
        pattern = re.compile(r'(\d+)\r?\n(\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3})\r?\n([\s\S]*?)(?=\r?\n\r?\n|$)')
        blocks = pattern.findall(content)
        total = len(blocks)
        translated_srt = ""; batch_size = 99 
        
        current_key_idx = 0
        xbmcgui.Dialog().notification('Robot', 'Traducere pornită (Chei: %d)' % len(all_keys), xbmcgui.NOTIFICATION_INFO, 2500)

        for i in range(0, total, batch_size):
            batch = blocks[i : i + batch_size]
            original_texts = [re.sub(r'<[^>]*>', '', b[2]).strip() for b in batch]
            
            success = False
            while current_key_idx < len(all_keys):
                res = translate_batch(original_texts, target_lang, all_keys[current_key_idx])
                if res == "ERROR_KEY":
                    current_key_idx += 1
                    continue
                if res:
                    translations = res
                    success = True
                    break
                else:
                    translations = original_texts
                    success = True
                    break
            
            # --- MODIFICARE PENTRU DEZACTIVARE ---
            if not success:
                if xbmcgui.Dialog().yesno("Eroare Critică", "Toate cheile API Google au expirat sau sunt invalide!\nDorești să dezactivezi Robotul din setări pentru a nu mai vedea această eroare?"):
                    _addon.setSetting('robot_activat', 'false')
                return

            for j, (idx, timing, _) in enumerate(batch):
                t_text = translations[j] if j < len(translations) else original_texts[j]
                translated_srt += "%s\n%s\n%s\n\n" % (idx, timing, t_text)

        output_path = os.path.join(profile_path, "robot_tradus.%s.srt" % target_lang)
        f = xbmcvfs.File(output_path, 'w'); f.write(translated_srt); f.close()
        
        xbmc.Player().setSubtitles(output_path)
        xbmcgui.Dialog().notification('[COLOR lime]Robot Traducător[/COLOR]', '[COLOR lime]Traducere Gata![/COLOR]', xbmcgui.NOTIFICATION_INFO, 4000)
        
    except Exception as e:
        xbmcgui.Dialog().notification('Robot', 'Eroare la procesare SRT', xbmcgui.NOTIFICATION_ERROR, 3000)
