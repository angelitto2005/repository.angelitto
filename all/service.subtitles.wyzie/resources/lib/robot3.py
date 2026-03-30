# -*- coding: utf-8 -*-
import xbmc, xbmcgui, xbmcvfs
import os, sys, re, json, urllib.parse, urllib.request
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
MODEL_PREFERAT = [
    "gemini-3.1-flash-lite-preview",
    "gemini-3-flash-preview",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash", 
    ]
PAUZA_DUPA_EROARE = 10.0 
keys_lock = Lock()
write_lock = Lock()
keys_in_use = set()
def notify(title, message, icon=xbmcgui.NOTIFICATION_INFO, duration=3000):
    xbmc.executebuiltin('Notification("{}", "{}", {}, {})'.format(title, message, duration, icon))
try:
    from .key import api_keys as backup_keys
except ImportError:
    try: 
        import key
        backup_keys = key.api_keys 
    except: 
        backup_keys = []
def translate_gemini(texts_dict, target_lang, api_key, model_name, style_instruction=""):
    url = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent?key={}".format(model_name, api_key)
    prompt = ("Translate to {}. Maintain the original tone, including any profanity or slang.\n{}\n"
              "Return ONLY a JSON object: {{'ID': 'translation'}}. No talk.").format(target_lang, style_instruction)
    payload = {
        "contents": [{"parts": [{"text": "{}\n\n{}".format(prompt, json.dumps(texts_dict, ensure_ascii=False))}]}],
        "generationConfig": {"temperature": 0.1, "response_mime_type": "application/json"},
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
        ]
    }
    try:
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=15) as r:
            res_data = json.loads(r.read().decode('utf-8'))
            # Parsare sigura a raspunsului
            try:
                candidates = res_data.get('candidates', [{}])[0]
                content = candidates.get('content', {})
                parts = content.get('parts', [{}])[0]
                text_raspuns = parts.get('text', '')
            except:
                text_raspuns = ""
            match = re.search(r'\{.*\}', text_raspuns, re.DOTALL)
            return json.loads(match.group()) if match else json.loads(text_raspuns)
    except Exception:
        return None
def process_batch_worker(batch, target_lang, all_keys, style_instruction):
    to_translate = {str(b[0]): re.sub(r'<[^>]*>', '', b[2]).strip() for b in batch}
    tried_keys_indices = set()
    while len(tried_keys_indices) < len(all_keys):
        current_key = None
        k_idx_real = 0
        with keys_lock:
            for i, k in enumerate(all_keys):
                if k not in keys_in_use and i not in tried_keys_indices:
                    current_key = k
                    keys_in_use.add(k)
                    k_idx_real = i + 1
                    break
        if not current_key:
            if len(keys_in_use) >= len(all_keys):
                time.sleep(2); continue
            else: break
        try:
            for model in MODEL_PREFERAT:
                rezultat = translate_gemini(to_translate, target_lang, current_key, model, style_instruction)
                if rezultat:
                    chunk_srt = ""
                    for b_id, timing, orig_text in batch:
                        trad = rezultat.get(str(b_id), rezultat.get(b_id, orig_text))
                        chunk_srt += "{}\n{}\n{}\n\n".format(b_id, timing, trad)
                    return chunk_srt, k_idx_real, model
            tried_keys_indices.add(k_idx_real - 1)
        finally:
            with keys_lock:
                if current_key in keys_in_use: keys_in_use.remove(current_key)
    return None, 0, ""
def run_translation(sub_addon_id):
    import xbmcaddon
    _addon = xbmcaddon.Addon(sub_addon_id)
    if _addon.getSetting('robot_activat') != 'true': return
    try: max_workers_setat = _addon.getSettingInt('max_workers_count') + 1
    except: max_workers_setat = 1
    
    # --- DOAR ACEASTĂ LINIE A FOST MODIFICATĂ (ID: api_key_r3_) ---
    keys_din_setari = [_addon.getSetting('api_key_r3_{}'.format(i)) for i in range(1, 6)]
    # -------------------------------------------------------------

    all_keys = list(dict.fromkeys([k for k in keys_din_setari if k] + backup_keys))
    if not all_keys:
        if xbmcgui.Dialog().yesno("Eroare: Lipsă Chei", "Nu s-a găsit nicio cheie API validă!\n\nVrei să deschizi Setările pentru a introduce o cheie sau a schimba robotul?"):
            _addon.openSettings()
        return

    langs = ["ro", "en", "es", "fr", "de", "it", "hu", "pt", "ru", "tr", "bg", "el", "pl", "cs", "nl"]
    try: target_lang = langs[_addon.getSettingInt('subs_languages')]
    except: target_lang = "ro"
    profile_path = xbmcvfs.translatePath('special://profile/addon_data/{}/'.format(sub_addon_id))
    dirs, files = xbmcvfs.listdir(profile_path)
    srt_files = [f for f in files if f.lower().endswith('.srt') and not f.startswith('robot_tradus')]
    if not srt_files: return
    sub_path = os.path.join(profile_path, srt_files[0])
    output_path = os.path.join(profile_path, "robot_tradus.{}.srt".format(target_lang))
    try:
        start_time = time.time()
        last_notify_time = 0
        f = xbmcvfs.File(sub_path); content = f.read(); f.close()
        pattern = re.compile(r'(\d+)\r?\n(\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3})\r?\n([\s\S]*?)(?=\r?\n\r?\n|$)')
        blocks = pattern.findall(content)
        batches = [blocks[i:i + 100] for i in range(0, len(blocks), 100)]
        total_lines = len(blocks)
        completed_lines, final_results = 0, {}
        chei_folosite, modele_folosite = set(), set()
        notify("Robot Gemini", "Start: {} linii | Pachete: {}".format(total_lines, len(batches)))
        with ThreadPoolExecutor(max_workers=max_workers_setat) as executor:
            futures = {executor.submit(process_batch_worker, b, target_lang, all_keys, "Professional localization."): i for i, b in enumerate(batches)}
            for future in as_completed(futures):
                idx = futures[future]
                res_text, k_num, model_name = future.result()
                if not res_text:
                    time.sleep(2)
                    res_text, k_num, model_name = process_batch_worker(batches[idx], target_lang, all_keys, "Professional localization.")
                if res_text:
                    with write_lock:
                        final_results[idx] = res_text
                        completed_lines += len(batches[idx])
                        chei_folosite.add(str(k_num))
                        modele_folosite.add(model_name)
                        current_srt = "".join([final_results[i] for i in sorted(final_results.keys())])
                        f_out = xbmcvfs.File(output_path, 'w'); f_out.write(current_srt); f_out.close()
                        xbmc.Player().setSubtitles(output_path)
                    t_acum = time.time()
                    if t_acum - last_notify_time > 10 or completed_lines == total_lines:
                        msg = 'Linii: {}/{} | K:{} | M:{}'.format(completed_lines, total_lines, k_num, model_name)
                        notify('Robot Gemini', msg, duration=2500)
                        last_notify_time = t_acum
                    time.sleep(3.0)
                else: break
        success = (len(final_results) == len(batches))
        if success:
            statistici = "M: {} | K: {}".format(", ".join(modele_folosite), ", ".join(chei_folosite))
            notify("Succes Complet", statistici, duration=6000)
        else:
            if completed_lines > 0:
                text_eroare = (
                    "Procesul s-a oprit la linia {}.\n"
                    "Cel mai probabil, cheile tale au atins LIMITA ZILNICĂ (Rate Limit).\n"
                    "Dorești să păstrezi ce s-a tradus până acum?"
                ).format(completed_lines)
                if xbmcgui.Dialog().yesno("Traducere Incompletă", text_eroare):
                    pass
                else:
                    xbmcvfs.delete(output_path)
            else:
                text_fail = (
                    "Robotul nu a putut traduce nicio linie. Verifică:\n"
                    "- Dacă cheile API sunt CORECTE.\n"
                    "- Dacă nu ai atins LIMITA (Rate Limit).\n\n"
                    "Vrei să deschizi Setările pentru a schimba robotul sau cheile?"
                )
                if xbmcgui.Dialog().yesno("Eroare Pornire", text_fail):
                    _addon.openSettings()
    except Exception as e:
        xbmcgui.Dialog().ok("Eroare", str(e))
