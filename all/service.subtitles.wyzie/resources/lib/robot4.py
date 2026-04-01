# -*- coding: utf-8 -*-
import xbmc, xbmcgui, xbmcvfs, xbmcaddon
import os, re, json, urllib.parse, urllib.request, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# --- 1. GLOBALE ---
keys_lock = Lock()
write_lock = Lock()
keys_in_use = set()

# LISTĂ STOP WORDS (Cuvinte care rămân la fel și nu consumă caractere API)
STOP_WORDS = {
    # Confirmări și negări universale
    "ok", "okay", "yeah", "yes", "no", "nah", "yep", "yup",
    
    # Exclamații și sunete
    "oh", "ohh", "ohhh", "ah", "ahh", "ahhh", "wow", "woww", 
    "hey", "heyy", "hey-hey", "ha", "haha", "hahaha", "huh", 
    "uh", "uh-huh", "uh-uh", "um", "umm", "mmm", "hmm", "hmmm",
    "oops", "phew", "shh", "shhh", "st", "sh", "brrr",
    
    # Onomatopee și sunete ambientale comune în subtitrări
    "grunt", "grunts", "sigh", "sighs", "pant", "panting", 
    "gasp", "gasps", "laugh", "laughs", "sob", "sobs"
}

def log(msg):
    xbmc.log("[DeepL_Robot_4] {}".format(msg), xbmc.LOGINFO)

def notify(title, message, duration=3500):
    xbmc.executebuiltin('Notification("{}", "{}", {})'.format(title, message, duration))

# --- FUNCȚIE NOUĂ: DIALOG REDIRECȚIONARE SETĂRI ---
def show_error_and_open_settings(sub_addon_id, message):
    dialog = xbmcgui.Dialog()
    if dialog.yesno("Eroare DeepL R4", message + "\n\nVrei să mergi la setări pentru a schimba cheia sau robotul?"):
        xbmc.executebuiltin('Addon.OpenSettings({})'.format(sub_addon_id))

# --- 2. MOTORUL DE VERIFICARE (SORTARE DUPĂ REZERVĂ) ---
def get_sorted_keys(all_keys):
    """ Verifică toate cheile și le sortează: cea mai plină prima """
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

# --- 3. WORKER EFICIENT ---
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
    
    # Curățare tag-uri și spații pentru analiză
    processed_batch = []
    to_api = []
    api_map = [] # Reține indexul original pentru reîntregire

    for idx, (b_id, timing, text) in enumerate(batch):
        clean_text = re.sub(r'\s+', ' ', re.sub(r'<[^>]*>', '', text).strip())
        
        # LOGICĂ ECONOMIE: Verificăm dacă e un Stop Word (ex: "Oh", "Hey!")
        word_only = re.sub(r'[^\w\s]', '', clean_text).lower().strip()
        
        if word_only in STOP_WORDS or not clean_text:
            # Păstrăm textul original fără să consumăm API
            processed_batch.append(clean_text)
        else:
            # Marcăm pentru API și salvăm poziția
            processed_batch.append(None) 
            to_api.append(clean_text)
            api_map.append(idx)

    tried = set()
    res_api = []
    
    # Trimitem la API doar ce nu este Stop Word
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
                
            if res_api and len(res_api) == len(to_api):
                break
            tried.add(current_key)
    
    # Reîntregim batch-ul (Stop Words + Traduceri API)
    api_idx = 0
    chunk = ""
    total_chars = sum(len(t) for t in to_api)

    for i in range(len(processed_batch)):
        final_text = processed_batch[i]
        if final_text is None: # Adică a fost trimis la API
            final_text = res_api[api_idx] if api_idx < len(res_api) else ""
            api_idx += 1
        
        b_id, timing, _ = batch[i]
        chunk += "{}\n{}\n{}\n\n".format(b_id, timing, final_text)

    return chunk, total_chars

# --- 4. RUNNER ROBOT 4 ---
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
    srt_list = [f for f in files if f.lower().endswith('.srt') and 'robot_tradus' not in f]
    if not srt_list: return
    
    sub_path = os.path.join(profile_path, srt_list[0])
    out_path = os.path.join(profile_path, "robot_tradus.{}.srt".format(target_lang))

    if xbmcvfs.exists(out_path):
        xbmc.Player().setSubtitles(out_path)
        return

    try:
        f = xbmcvfs.File(sub_path); content = f.read(); f.close()
        blocks = re.findall(r'(\d+)\s*\r?\n(\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3})\s*\r?\n([\s\S]*?)(?=\r?\n\r?\n|$)', content)
        if not blocks: return

        total_chars_film = sum(len(re.sub(r'<[^>]*>', '', b).strip()) for _, _, b in blocks)
        
        notify("DeepL Robot 4", "Verificăm validitatea cheilor...")
        keys_valide = get_sorted_keys(all_keys)
        
        if not keys_valide:
            show_error_and_open_settings(sub_addon_id, "Cheile DeepL sunt invalide sau expirate.")
            return

        total_liber = sum(k[1] for k in keys_valide)

        if total_chars_film > total_liber:
            msg = "LIMITE INSUFICIENTE!\nFilm: ~{} char\nDisponibil: {} char".format(total_chars_film, total_liber)
            show_error_and_open_settings(sub_addon_id, msg)
            return

        notify("DeepL Robot 4", "Pornire: {} char libere | Viteză: {}".format(total_liber, workers))

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
                        f_out = xbmcvfs.File(out_path, 'w')
                        f_out.write(full_srt)
                        f_out.close()
                        if xbmc.Player().isPlaying(): xbmc.Player().setSubtitles(out_path)

        if xbmc.Player().isPlaying() and len(final_results) == len(batches):
            notify("Succes Robot 4", "Traducere finalizată!")

    except Exception as e: log("Eroare Robot 4: {}".format(str(e)))
