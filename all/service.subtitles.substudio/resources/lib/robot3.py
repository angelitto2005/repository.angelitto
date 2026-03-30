# -*- coding: utf-8 -*-
import xbmc, xbmcgui, xbmcvfs, xbmcaddon
import os, re, json, urllib.parse, urllib.request, html, time

def wrap_text(text, limit=45):
    text = html.unescape(text)
    words = text.split()
    lines, current_line, current_length = [], [], 0
    for word in words:
        if current_length + len(word) + 1 <= limit:
            current_line.append(word)
            current_length += len(word) + 1
        else:
            lines.append(" ".join(current_line))
            current_line = [word]
            current_length = len(word)
    if current_line:
        lines.append(" ".join(current_line))
    return "\n".join(lines)

def translate_batch(texts, target_lang, api_key):
    try:
        base_url = "https://translation.googleapis.com/language/translate/v2?key=" + api_key
        payload = {'q': texts, 'target': target_lang, 'format': 'text'}
        body = json.dumps(payload).encode('utf-8')
        headers = {'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
        req = urllib.request.Request(base_url, data=body, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=15) as r:
            res_data = json.loads(r.read().decode('utf-8'))
            return [wrap_text(t['translatedText']) for t in res_data['data']['translations']]
    except urllib.error.HTTPError:
        return "ERROR_KEY"
    except Exception:
        return None

def _player_has_media():
    try:
        return xbmc.getCondVisibility('Player.HasVideo') or xbmc.Player().isPlayingVideo()
    except Exception:
        return False

def run_translation(sub_addon_id):
    _addon = xbmcaddon.Addon(sub_addon_id)
    if _addon.getSetting('robot_activat') != 'true': return

    all_keys = []
    for i in range(1, 6):
        kn = _addon.getSetting('api_key_r1_%d' % i)
        if kn and kn.strip() and kn.strip() not in all_keys: 
            all_keys.append(kn.strip())

    # 1. PROTECȚIE: Dacă utilizatorul nu a pus NICIO cheie în setări
    if not all_keys:
        xbmcgui.Dialog().notification('Google Robot', 'Lipsă chei API în setări!', xbmcgui.NOTIFICATION_ERROR, 5000)
        return

    # 2. VALIDARE ONLINE: Dacă a pus chei, le verificăm dacă sunt reale
    def _validate_google_key(key):
        try:
            url = f"https://translation.googleapis.com/language/translate/v2/languages?key={key}"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5): return True
        except urllib.error.HTTPError as e:
            if e.code in (400, 403): return False # 400/403 = API Key Invalid
        except Exception: return True
        return True

    valid_keys = [k for k in all_keys if _validate_google_key(k)]

    # 3. PROTECȚIE: Dacă a pus chei, dar TOATE sunt greșite sau expirate
    if not valid_keys:
        xbmcgui.Dialog().notification('Google Robot', 'Cheile API introduse sunt INVALIDE!', xbmcgui.NOTIFICATION_ERROR, 5000)
        return
        
    all_keys = valid_keys
    # -------------------------------------------------------

    langs = ["ro", "en", "es", "fr", "de", "it", "hu", "pt", "ru", "tr", "bg", "el", "pl", "cs", "nl"]
    try: target_lang = langs[_addon.getSettingInt('subs_languages')]
    except Exception: target_lang = "ro"

    profile_path = xbmcvfs.translatePath('special://profile/addon_data/%s/' % sub_addon_id)
    _, files = xbmcvfs.listdir(profile_path)
    srt_files = [f for f in files if f.lower().endswith('.srt') and not f.startswith('robot_tradus')]
    if not srt_files: return

    original_name = srt_files[0]
    sub_path = os.path.join(profile_path, original_name)
    base_clean_name = re.sub(r'\.[a-z]{2,3}$', '', os.path.splitext(original_name)[0], flags=re.IGNORECASE)
    clean_name = f"{base_clean_name}.{target_lang}.srt"

    pDialog = xbmcgui.DialogProgressBG()

    try:
        f = xbmcvfs.File(sub_path); content = f.read(); f.close()
        pattern = re.compile(r'(\d+)\r?\n(\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3})\r?\n([\s\S]*?)(?=\r?\n\r?\n|$)')
        blocks = pattern.findall(content)
        total = len(blocks)
        translated_srt = ""
        batch_size = 90 
        
        current_key_idx = 0
        start_time = time.time()
        
        pDialog.create('SubStudio', f'Google API: Traducere în {target_lang.upper()}...')

        for i in range(0, total, batch_size):
            if not _player_has_media():
                pDialog.close()
                xbmcgui.Dialog().notification('Google Robot', 'Traducere oprită de utilizator', xbmcgui.NOTIFICATION_WARNING, 3000)
                xbmc.log("Google Robot oprit (Player Closed)", xbmc.LOGINFO)
                return

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
                    translations = [wrap_text(t) for t in original_texts]
                    success = True
                    break
            
            if not success:
                _addon.setSetting('robot_activat', 'false')
                pDialog.close()
                xbmcgui.Dialog().notification('Google Robot', 'Chei expirate. Robot oprit.', xbmcgui.NOTIFICATION_ERROR, 5000)
                return

            for j, (idx, timing, _) in enumerate(batch):
                t_text = translations[j] if j < len(translations) else original_texts[j]
                translated_srt += f"{idx}\n{timing}\n{t_text}\n\n"
            
            xbmc.log(f"Google Robot: S-au tradus liniile de la {i} la {i + len(batch)}", xbmc.LOGINFO)
            pDialog.update(int((i / total) * 100))
            
            # --- Live Injection pt Google API ---
            if not _player_has_media(): break
            try:
                raw_bytes = b'\xef\xbb\xbf' + translated_srt.encode('utf-8')
                temp_dir = xbmcvfs.translatePath('special://temp/substudio_subs/')
                if not xbmcvfs.exists(temp_dir): xbmcvfs.mkdirs(temp_dir)
                ts = int(time.time())
                tf = os.path.join(temp_dir, f"robot_{ts}")
                xbmcvfs.mkdirs(tf)
                
                temp_sub = os.path.join(tf, clean_name)
                ft = xbmcvfs.File(temp_sub, 'wb'); ft.write(raw_bytes); ft.close()
                xbmc.Player().setSubtitles(temp_sub)
            except Exception: pass

        pDialog.close()
        
        if not _player_has_media():
            xbmcgui.Dialog().notification('Google Robot', 'Traducere oprită de utilizator', xbmcgui.NOTIFICATION_WARNING, 3000)
            xbmc.log("Google Robot oprit (Player Closed) la finalizare", xbmc.LOGINFO)
            return

        # Salvare finala permanenta
        out_path = os.path.join(profile_path, f"robot_tradus.{target_lang}.srt")
        f = xbmcvfs.File(out_path, 'wb'); f.write(b'\xef\xbb\xbf' + translated_srt.encode('utf-8')); f.close()
        
        if _addon.getSetting('save_translations') == 'true':
            try:
                saved_dir = os.path.join(profile_path, 'Subtitrari traduse')
                if not xbmcvfs.exists(saved_dir): xbmcvfs.mkdirs(saved_dir)
                saved_path = os.path.join(saved_dir, clean_name)
                xbmcvfs.copy(out_path, saved_path)
                
                imdb_id = xbmc.getInfoLabel("VideoPlayer.IMDBNumber") or ""
                tmdb_id = xbmc.getInfoLabel("ListItem.Property(tmdb_id)") or ""
                video_title = xbmc.getInfoLabel("VideoPlayer.Title") or ""
                index_path = os.path.join(saved_dir, 'index.json')
                
                index = {}
                if xbmcvfs.exists(index_path):
                    try:
                        f_idx = xbmcvfs.File(index_path); raw = f_idx.read(); f_idx.close()
                        if raw: index = json.loads(raw.decode('utf-8'))
                    except Exception: pass
                    
                index[clean_name] = {'imdb': imdb_id, 'tmdb': tmdb_id, 'title': video_title, 'file': clean_name, 'complete': True}
                index_data = json.dumps(index, ensure_ascii=False, indent=2)
                f_idx_w = xbmcvfs.File(index_path, 'w'); f_idx_w.write(index_data.encode('utf-8')); f_idx_w.close()
            except Exception: pass

        total_time = int(time.time() - start_time)
        xbmcgui.Dialog().notification('Google Robot', f'Traducere completă în {total_time}s', xbmcgui.NOTIFICATION_INFO, 4000)
        
    except Exception as e:
        try: pDialog.close()
        except Exception: pass
        xbmc.log(f"Google Robot Error: {str(e)}", xbmc.LOGERROR)