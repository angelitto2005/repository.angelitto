import xbmc, xbmcgui, xbmcvfs, xbmcaddon
import os, sys, re, json, urllib.parse, urllib.request, html, threading, time
try:
    from . import uploader
except:
    try: import uploader
    except: uploader = None
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
def wrap_text(text, limit=45):
    """Logica originala de formatare randuri."""
    try: text = html.unescape(text)
    except: pass
    words = text.split()
    lines, current_line, current_length = [], [], 0
    for word in words:
        if current_length + len(word) + 1 <= limit:
            current_line.append(word); current_length += len(word) + 1
        else:
            lines.append(" ".join(current_line)); current_line = [word]; current_length = len(word)
    if current_line: lines.append(" ".join(current_line))
    return "\n".join(lines)
def translate_batch(texts, target_lang, api_key):
    """Logica originala Google Translate V2."""
    try:
        base_url = "https://translation.googleapis.com/language/translate/v2?key=" + api_key
        payload = {'q': texts, 'target': target_lang, 'format': 'text'}
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        headers = {'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
        req = urllib.request.Request(base_url, data=body, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=15) as r:
            res_data = json.loads(r.read().decode('utf-8'))
            return [wrap_text(t['translatedText']) for t in res_data['data']['translations']]
    except urllib.error.HTTPError as e:
        return "ERROR_KEY"
    except:
        return None
def run_translation(sub_addon_id):
    _addon = xbmcaddon.Addon(sub_addon_id)
    if _addon.getSetting('robot_activat') != 'true': return
    all_keys = []
    for i in range(1, 6):
        kn = _addon.getSetting('api_key_r1_%d' % i)
        if kn and kn not in all_keys: all_keys.append(kn)
    for k in backup_keys:
        if k and k not in all_keys: all_keys.append(k)
    if not all_keys:
        if xbmcgui.Dialog().yesno("Eroare", "Lipsa Chei API! Deschizi setarile?"): _addon.openSettings()
        return
    langs = ["ro", "en", "es", "fr", "de", "it", "hu", "pt", "ru", "tr", "bg", "el", "pl", "cs", "nl"]
    try: target_lang = langs[_addon.getSettingInt('subs_languages')]
    except: target_lang = "ro"
    profile_path = xbmcvfs.translatePath('special://profile/addon_data/%s/' % sub_addon_id)
    _, files = xbmcvfs.listdir(profile_path)
    srt_files = [f for f in files if f.lower().endswith('.srt') and not (f.startswith('Google-') or f.startswith('Gemini-') or f.startswith('Lingva-'))]
    if not srt_files: return
    orig_full_name = srt_files[0]
    sub_path = os.path.join(profile_path, orig_full_name)
    base_name = orig_full_name.rsplit('.', 1)[0]
    final_name = "Google-{}.{}.srt".format(base_name, target_lang)
    output_path = os.path.join(profile_path, final_name)
    if uploader:
        cale_cloud = uploader.get_folder_grup()
        auth = uploader.koofr_get_auth()
        remote_url = "https://app.koofr.net/dav/Koofr/Subtitrari/{}/{}".format(cale_cloud, urllib.parse.quote(final_name))
        try:
            req_c = urllib.request.Request(remote_url, method='GET', headers={"Authorization": auth})
            with urllib.request.urlopen(req_c, timeout=10) as r:
                if r.getcode() == 200:
                    xbmc.executebuiltin('Notification("Cloud", "Subtitrare găsită!", 2000)')
                    with xbmcvfs.File(output_path, 'wb') as f_o: f_o.write(r.read())
                    xbmc.Player().setSubtitles(output_path)
                    return
        except:
            pass
    try:
        f = xbmcvfs.File(sub_path); content = f.read(); f.close()
        pattern = re.compile(r'(\d+)\r?\n(\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3})\r?\n([\s\S]*?)(?=\r?\n\r?\n|$)')
        blocks = pattern.findall(content)
        total = len(blocks)
        translated_srt, batch_size, current_key_idx = "", 80, 0
        xbmc.executebuiltin('Notification("Google", "Linii: 0/{}", 1500)'.format(total))
        for i in range(0, total, batch_size):
            if not xbmc.Player().isPlaying(): return
            batch = blocks[i : i + batch_size]
            original_texts = [re.sub(r'<[^>]*>', '', b[2]).strip() for b in batch]
            translations = None
            while current_key_idx < len(all_keys):
                res = translate_batch(original_texts, target_lang, all_keys[current_key_idx])
                if res == "ERROR_KEY":
                    current_key_idx += 1; continue
                if res: translations = res; break
                else: break
            if not translations:
                if xbmcgui.Dialog().yesno("Eroare", "Toate cheile au esuat! Mergi la setari?"): _addon.openSettings()
                return
            for j, (idx, timing, _) in enumerate(batch):
                t_text = translations[j] if j < len(translations) else original_texts[j]
                translated_srt += "{}\n{}\n{}\n\n".format(idx, timing, t_text)
            with xbmcvfs.File(output_path, 'w') as f_w: f_w.write(translated_srt)
            if xbmc.Player().isPlaying(): xbmc.Player().setSubtitles(output_path)
            xbmc.executebuiltin('Notification("Google", "Linii: {}/{}", 1000)'.format(min(i + batch_size, total), total))
        if xbmc.Player().isPlaying() and uploader:
            threading.Thread(target=uploader.upload_now, args=(output_path, final_name)).start()
    except Exception as e:
        xbmc.log("Eroare Robot Google: " + str(e), xbmc.LOGERROR)