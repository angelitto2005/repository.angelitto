# -*- coding: utf-8 -*-
import xbmc, xbmcgui, xbmcvfs, xbmcaddon
import os, re, json, urllib.parse, urllib.request, time, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# Import uploader centralizat
try:
    from . import uploader
except:
    try: import uploader
    except: uploader = None

# --- 1. GLOBALE ---
keys_lock = Lock()
write_lock = Lock()
keys_in_use = set()

STOP_WORDS = {
    "ok", "okay", "yeah", "yes", "no", "nah", "yep", "yup",
    "oh", "ohh", "ohhh", "ah", "ahh", "ahhh", "wow", "woww", 
    "hey", "heyy", "hey-hey", "ha", "haha", "hahaha", "huh", 
    "uh", "uh-huh", "uh-uh", "um", "umm", "mmm", "hmm", "hmmm",
    "oops", "phew", "shh", "shhh", "st", "sh", "brrr", 
    "grunt", "grunts", "sigh", "sighs", "pant", "panting", 
    "gasp", "gasps", "laugh", "laughs", "sob", "sobs"
}

def log(msg):
    xbmc.log("[DeepL_Robot_4] {}".format(msg), xbmc.LOGINFO)

def notify(title, message, duration=3500):
    xbmc.executebuiltin('Notification("{}", "{}", {})'.format(title, message, duration))

def show_error_and_open_settings(sub_addon_id, message):
    dialog = xbmcgui.Dialog()
    if dialog.yesno("Eroare DeepL R4", message + "\n\nVrei să mergi la setări pentru a schimba cheia sau robotul?"):
        xbmc.executebuiltin('Addon.OpenSettings({})'.format(sub_addon_id))

# --- 2. MOTORUL DE VERIFICARE ---
def get_sorted_keys(all_keys):
    key_status = []
    for k in all_keys:
        clean_key = k.strip()
        if not clean_key: continue
        url = "https://api-free.deepl.com/v2/usage"
        if not clean_key.endswith(":fx"): url = "https://api.deepl.com/v2/usage"
        headers = {"Authorization": "DeepL-Auth-Key {}".format(clean_key)}
        try:
            req = urllib.request.Request(url, headers=headers, method='GET')
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read().decode('utf-8'))
                liber = int(data.get('character_limit', 0)) - int(data.get('character_count', 0))
                if liber > 100: key_status.append((clean_key, liber))
        except: continue
    key_status.sort(key=lambda x: x[1], reverse=True)
    return key_status

# --- 3. WORKER ---
def translate_deepl(texts_list, target_lang, api_key):
    if not texts_list: return []
    url = "https://api-free.deepl.com/v2/translate"
    if not api_key.endswith(":fx"): url = "https://api.deepl.com/v2/translate"
    trg = target_lang.upper()
    if trg == "EN": trg = "EN-US"
    payload = {"text": [t.strip() for t in texts_list], "target_lang": trg, "split_sentences": "0"}
    try:
        body = json.dumps(payload).encode('utf-8')
        headers = {"Authorization": "DeepL-Auth-Key {}".format(api_key), "Content-Type": "application/json"}
        req = urllib.request.Request(url, data=body, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=12) as r:
            res_data = json.loads(r.read().decode('utf-8'))
            return [item.get('text', '') for item in res_data.get('translations', [])]
    except: return None

def process_batch_worker(batch, target_lang, keys_valide):
    if not xbmc.Player().isPlaying(): return None, 0
    processed_batch, to_api, api_map = [], [], []

    for idx, (b_id, timing, text) in enumerate(batch):
        clean_text = re.sub(r'\s+', ' ', re.sub(r'<[^>]*>', '', text).strip())
        word_only = re.sub(r'[^\w\s]', '', clean_text).lower().strip()
        if word_only in STOP_WORDS or not clean_text:
            processed_batch.append(clean_text)
        else:
            processed_batch.append(None) 
            to_api.append(clean_text)
            api_map.append(idx)

    tried, res_api = set(), []
    if to_api:
        while len(tried) < len(keys_valide):
            if not xbmc.Player().isPlaying(): break
            current_key = None
            with keys_lock:
                for k, _ in keys_valide:
                    if k not in keys_in_use and k not in tried:
                        current_key = k; keys_in_use.add(k); break
            if not current_key:
                time.sleep(1); continue
            res_api = translate_deepl(to_api, target_lang, current_key)
            with keys_lock: 
                if current_key in keys_in_use: keys_in_use.remove(current_key)
            if res_api and len(res_api) == len(to_api): break
            tried.add(current_key)
    
    api_idx, chunk, total_chars = 0, "", sum(len(t) for t in to_api)
    for i in range(len(processed_batch)):
        final_text = processed_batch[i]
        if final_text is None:
            final_text = res_api[api_idx] if api_idx < len(res_api) else ""
            api_idx += 1
        b_id, timing, _ = batch[i]
        chunk += "{}\n{}\n{}\n\n".format(b_id, timing, final_text)
    return chunk, total_chars

# --- 4. RUNNER ---
def run_translation(sub_addon_id):
    _addon = xbmcaddon.Addon(sub_addon_id)
    raw_keys = [_addon.getSetting('api_key_r4_{}'.format(i)) for i in range(1, 6)]
    all_keys = [k for k in raw_keys if k.strip()]
    if not all_keys:
        show_error_and_open_settings(sub_addon_id, "Nu ai introdus nicio cheie DeepL (R4).")
        return

    langs = ["ro", "en", "es", "fr", "de", "it", "hu", "pt", "ru", "tr", "bg", "el", "pl", "cs", "nl"]
    try: target_lang = langs[_addon.getSettingInt('subs_languages')]
    except: target_lang = "ro"
    workers = max(1, _addon.getSettingInt('max_workers_count_r4') + 1)

    profile_path = xbmcvfs.translatePath("special://profile/addon_data/{}/".format(sub_addon_id))
    _, files = xbmcvfs.listdir(profile_path)
    srt_list = [f for f in files if f.lower().endswith('.srt') and not (f.startswith('Google-') or f.startswith('Gemini-') or f.startswith('Lingva-') or f.startswith('DeepL-'))]
    if not srt_list: return
    
    orig_full_name = srt_list[0]
    sub_path = os.path.join(profile_path, orig_full_name)
    base_name = orig_full_name.rsplit('.', 1)[0]
    final_name = "DeepL-{}.{}.srt".format(base_name, target_lang)
    out_path = os.path.join(profile_path, final_name)

    if uploader:
        # 1. Luăm calea (ex: "Seriale/tt123_S-01_E-01" sau "Filme/tt123")
        cale_cloud = uploader.get_folder_grup() 
        auth = uploader.koofr_get_auth()
        
        # 2. Folosim variabila CORECtĂ (cale_cloud) în URL
        remote_url = "https://app.koofr.net/dav/Koofr/Subtitrari/{}/{}".format(cale_cloud, urllib.parse.quote(final_name))
        
        try:
            req_c = urllib.request.Request(remote_url, method='GET', headers={"Authorization": auth})
            with urllib.request.urlopen(req_c, timeout=10) as r:
                if r.getcode() == 200:
                    xbmc.executebuiltin('Notification("Cloud", "Subtitrare găsită!", 2000)')
                    with xbmcvfs.File(output_path, 'wb') as f_o: f_o.write(r.read())
                    xbmc.Player().setSubtitles(output_path)
                    return # Oprim robotul aici dacă am găsit-o deja
        except:
            pass


    try:
        f = xbmcvfs.File(sub_path); content = f.read(); f.close()
        blocks = re.findall(r'(\d+)\s*\r?\n(\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3})\s*\r?\n([\s\S]*?)(?=\r?\n\r?\n|$)', content)
        if not blocks: return

        total_chars_film = sum(len(re.sub(r'<[^>]*>', '', b[2]).strip()) for b in blocks)
        notify("DeepL Robot 4", "Verificăm cheile...")
        keys_valide = get_sorted_keys(all_keys)
        
        if not keys_valide:
            show_error_and_open_settings(sub_addon_id, "Cheile DeepL sunt invalide sau expirate.")
            return

        total_liber = sum(k[1] for k in keys_valide)
        if total_chars_film > total_liber:
            msg = "LIMITE INSUFICIENTE!\nFilm: ~{} char\nDisponibil: {} char".format(total_chars_film, total_liber)
            show_error_and_open_settings(sub_addon_id, msg); return

        notify("DeepL Robot 4", "Pornire: {} char libere".format(total_liber))
        batches = [blocks[i:i + 50] for i in range(0, len(blocks), 50)]
        final_results = {}

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(process_batch_worker, b, target_lang, keys_valide): i for i, b in enumerate(batches)}
            for future in as_completed(futures):
                if not xbmc.Player().isPlaying(): break
                idx = futures[future]
                res_srt, _ = future.result()
                if res_srt:
                    with write_lock:
                        final_results[idx] = res_srt
                        full_srt = "".join([final_results[i] for i in sorted(final_results.keys())])
                        with xbmcvfs.File(out_path, 'w') as f_o: f_o.write(full_srt)
                        if xbmc.Player().isPlaying(): xbmc.Player().setSubtitles(out_path)

        if xbmc.Player().isPlaying() and len(final_results) == len(batches):
            notify("Succes Robot 4", "Traducere finalizată!")
            if uploader: threading.Thread(target=uploader.upload_now, args=(out_path, final_name)).start()

    except Exception as e: log("Eroare Robot 4: {}".format(str(e)))
