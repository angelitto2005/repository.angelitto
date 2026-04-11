import xbmc, xbmcgui, xbmcvfs, xbmcaddon
import os, re, json, urllib.parse, urllib.request, time, threading, random, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
keys_lock = Lock()
write_lock = Lock()
keys_in_use = set()
TRADUCERI_CACHE = {}
STAT_TOTAL_CHARS = 0
STAT_CONSUM_DEEPL = 0
STAT_ECONOMIE = 0
STOP_WORDS = {
    "ok", "okay", "yeah", "yes", "no", "nah", "yep", "yup", "oh", "ah", "wow",
    "hey", "ha", "haha", "huh", "uh", "um", "mmm", "hmm", "oops", "phew",
    "shh", "brrr", "sigh", "pant", "gasp", "laugh", "sob", "...", "..", "-", "--"
}
AD_PATTERNS = [
    r"www\.[a-z0-9]+\.[a-z]{2,}", r"https?://[^\s]+", r"subtitles by|translated by",
    r"OpenSubtitles|Subscene", r"support us|donate", r"@[a-z0-9_]+"
]
addon_path = xbmcaddon.Addon().getAddonInfo('path')
lib_path = os.path.join(addon_path, 'lib')
res_lib_path = os.path.join(addon_path, 'resources', 'lib')
if lib_path not in sys.path: sys.path.append(lib_path)
if res_lib_path not in sys.path: sys.path.append(res_lib_path)
try:
    import uploader
    xbmc.log("[DeepL_Robot_4] Uploader.py găsit și încărcat din /lib", xbmc.LOGINFO)
except Exception as e:
    uploader = None
    xbmc.log("[DeepL_Robot_4] EROARE Import Uploader: " + str(e), xbmc.LOGERROR)
def log(msg):
    xbmc.log("[DeepL_Robot_4] {}".format(msg), xbmc.LOGINFO)
def notify(title, message, duration=3500):
    xbmc.executebuiltin('Notification("{}", "{}", {})'.format(title, message, duration))
def show_error_and_open_settings(sub_addon_id, message):
    dialog = xbmcgui.Dialog()
    if dialog.yesno("Eroare DeepL R4", message + "\nVrei să mergi la setări?"):
        xbmc.executebuiltin('Addon.OpenSettings({})'.format(sub_addon_id))
def split_smart_long_line(text, max_chars=44):
    if not text or len(text) <= max_chars or "\n" in text:
        return text
    match_dialog = re.search(r'\s+-\s*([A-ZĂÎȘȚÂ])', text)
    if match_dialog:
        split_pos = match_dialog.start()
        p1, p2 = text[:split_pos].strip(), text[split_pos:].strip()
        if len(p1) <= max_chars and len(p2) <= max_chars:
            if not p2.startswith('-'): p2 = "- " + p2
            return p1 + "\n" + p2
    match_punct = re.search(r'([.!?])\s+', text)
    if match_punct:
        split_pos = match_punct.start(1) + 1
        p1, p2 = text[:split_pos].strip(), text[split_pos:].strip()
        if len(p1) <= max_chars and len(p2) <= max_chars:
            return p1 + "\n" + p2
    if ',' in text:
        mid = len(text) // 2
        best_comma = -1
        min_dist = float('inf')
        for i, char in enumerate(text):
            if char == ',':
                dist = abs(i - mid)
                if dist < min_dist:
                    min_dist, best_comma = dist, i
        if best_comma != -1:
            p1, p2 = text[:best_comma + 1].strip(), text[best_comma + 1:].strip()
            if len(p1) <= max_chars and len(p2) <= max_chars:
                return p1 + "\n" + p2
    mid = len(text) // 2
    for i in range(0, 25):
        for pos in [mid + i, mid - i]:
            if 0 < pos < len(text) and text[pos] == ' ':
                return text[:pos].strip() + "\n" + text[pos:].strip()
    return text
def show_error_and_open_settings(sub_addon_id, message):
    if xbmcgui.Dialog().yesno("Eroare DeepL R4", message + "\nVrei setările?"):
        xbmc.executebuiltin('Addon.OpenSettings({})'.format(sub_addon_id))
def split_smart_long_line(text, max_chars=44):
    if not text or len(text) <= max_chars or "\n" in text:
        return text
    match_dialog = re.search(r'\s+-\s*([A-ZĂÎȘȚÂ])', text)
    if match_dialog:
        split_pos = match_dialog.start()
        p1, p2 = text[:split_pos].strip(), text[split_pos:].strip()
        if len(p1) <= max_chars and len(p2) <= max_chars:
            if not p2.startswith('-'): p2 = "- " + p2
            return p1 + "\n" + p2
    match_punct = re.search(r'([.!?])\s+', text)
    if match_punct:
        split_pos = match_punct.start(1) + 1
        p1, p2 = text[:split_pos].strip(), text[split_pos:].strip()
        if len(p1) <= max_chars and len(p2) <= max_chars:
            return p1 + "\n" + p2
    if ',' in text:
        mid = len(text) // 2
        best_comma = -1
        min_dist = float('inf')
        for i, char in enumerate(text):
            if char == ',':
                dist = abs(i - mid)
                if dist < min_dist:
                    min_dist, best_comma = dist, i
        if best_comma != -1:
            p1, p2 = text[:best_comma + 1].strip(), text[best_comma + 1:].strip()
            if len(p1) <= max_chars and len(p2) <= max_chars:
                return p1 + "\n" + p2
    mid = len(text) // 2
    for i in range(0, 25):
        for pos in [mid + i, mid - i]:
            if 0 < pos < len(text) and text[pos] == ' ':
                return text[:pos].strip() + "\n" + text[pos:].strip()
    return text
def get_sorted_keys(all_keys, blacklist_path, chars_film):
    necesar_minim = int(chars_film * 1.2)
    colectate = []
    suma_totala_liber = 0
    keys_reale = [k.strip() for k in all_keys if k.strip() and k != "cloud_fallback"]
    if keys_reale:
        log("Verificăm {} chei din setări...".format(len(keys_reale)))
        random.shuffle(keys_reale)
        for k in keys_reale:
            url = "https://api-free.deepl.com/v2/usage" if k.endswith(":fx") else "https://api.deepl.com/v2/usage"
            try:
                req = urllib.request.Request(url, headers={"Authorization": "DeepL-Auth-Key {}".format(k)})
                with urllib.request.urlopen(req, timeout=6) as r:
                    data = json.loads(r.read().decode('utf-8'))
                    liber = int(data.get('character_limit', 0)) - int(data.get('character_count', 0))
                    if liber > 500:
                        colectate.append((k, liber))
                        suma_totala_liber += liber
                        log("Sursă din setări: {}... ({} libere)".format(k[:5], liber))
                    if suma_totala_liber >= necesar_minim:
                        log("Total suficient din setări.")
                        return colectate
            except: continue
    if suma_totala_liber < necesar_minim:
        log("Caractere insuficiente în setări. Apelăm la system_core (Koofr)...")
        try:
            import system_core
            cheie_cloud = system_core.get_cloud_key()
            if cheie_cloud:
                url_c = "https://api-free.deepl.com/v2/usage" if cheie_cloud.endswith(":fx") else "https://api.deepl.com/v2/usage"
                req_c = urllib.request.Request(url_c, headers={"Authorization": "DeepL-Auth-Key {}".format(cheie_cloud)})
                with urllib.request.urlopen(req_c, timeout=6) as r_c:
                    d_c = json.loads(r_c.read().decode('utf-8'))
                    lib_c = int(d_c.get('character_limit', 0)) - int(d_c.get('character_count', 0))
                    if lib_c > 1000:
                        colectate.append((cheie_cloud, lib_c))
                        suma_totala_liber += lib_c
                        log("Cheie primită din Cloud și activată!")
        except Exception as e:
            log("Eroare la apelarea Cloud-ului: " + str(e))
    return colectate
def translate_deepl(texts_list, target_lang, api_key):
    if not texts_list: return []
    url = "https://api-free.deepl.com/v2/translate" if api_key.endswith(":fx") else "https://api.deepl.com/v2/translate"
    trg = target_lang.upper()
    if trg == "EN": trg = "EN-US"
    payload = {
        "text": texts_list,
        "target_lang": trg,
        "split_sentences": "nonewlines",
        "preserve_formatting": True,
        "formality": "prefer_less",
        "context": "Movie dialogue, informal street talk, use 'tu' not 'dumneavoastra'"
    }
    try:
        body = json.dumps(payload).encode('utf-8')
        headers = {"Authorization": "DeepL-Auth-Key {}".format(api_key), "Content-Type": "application/json"}
        req = urllib.request.Request(url, data=body, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=18) as r:
            res_data = json.loads(r.read().decode('utf-8'))
            return [item.get('text', '') for item in res_data.get('translations', [])]
    except Exception as e:
        log("Eroare cheie {}... : {}".format(api_key[:5], str(e)))
        return None
def process_batch_worker(batch, target_lang, keys_valide):
    if not xbmc.Player().isPlaying(): return None, 0
    global STAT_TOTAL_CHARS, STAT_CONSUM_DEEPL, STAT_ECONOMIE
    processed_batch, to_api = [], []
    for idx, (b_id, timing, text) in enumerate(batch):
        clean_text = re.sub(r'<[^>]*>', '', text).strip()
        clean_text = re.sub(r'\s+', ' ', clean_text)
        with keys_lock: STAT_TOTAL_CHARS += len(clean_text)
        if any(re.search(p, clean_text, re.IGNORECASE) for p in AD_PATTERNS):
            with keys_lock: STAT_ECONOMIE += len(clean_text)
            processed_batch.append(""); continue
        core_text = clean_text.lstrip('- ').rstrip(',. ')
        if not core_text:
            processed_batch.append(""); continue
        if core_text in TRADUCERI_CACHE:
            processed_batch.append(TRADUCERI_CACHE[core_text])
            with keys_lock: STAT_ECONOMIE += len(clean_text)
        else:
            word_only = re.sub(r'[^\w\s]', '', core_text).lower().strip()
            if word_only in STOP_WORDS:
                processed_batch.append(core_text)
                with keys_lock: STAT_ECONOMIE += len(clean_text)
            else:
                processed_batch.append(None)
                to_api.append(core_text)
                with keys_lock: STAT_CONSUM_DEEPL += len(core_text)
    res_api = []
    if to_api:
        for current_key, _ in keys_valide:
            if not xbmc.Player().isPlaying(): break
            temp_res = translate_deepl(to_api, target_lang, current_key)
            if temp_res and len(temp_res) == len(to_api):
                res_api = temp_res
                for i, trans in enumerate(res_api):
                    TRADUCERI_CACHE[to_api[i]] = trans
                break
            else:
                log("Cheia {}... s-a epuizat. Încercăm următoarea...".format(current_key[:5]))
                continue
    api_idx, chunk = 0, ""
    for i in range(len(processed_batch)):
        final = processed_batch[i]
        if final is None:
            final = res_api[api_idx] if res_api and api_idx < len(res_api) else ""
            api_idx += 1
        if final:
            final = split_smart_long_line(str(final).replace('- ', '').strip(), max_chars=44)
            linii = [l.strip().lstrip('- ').strip() for l in final.splitlines()]
            final_curat = "\n".join(linii)
        else:
            final_curat = ""
        b_id, timing, _ = batch[i]
        chunk += "{}\n{}\n{}\n\n".format(b_id, timing, final_curat)
    return chunk, 0
def run_translation(sub_addon_id):
    _addon = xbmcaddon.Addon(sub_addon_id)
    profile_path = xbmcvfs.translatePath("special://profile/addon_data/{}/".format(sub_addon_id))
    combined_keys = []
    for i in range(1, 6):
        k = _addon.getSetting('api_key_r4_{}'.format(i)).strip()
        if k: combined_keys.append(k)
    keys_file = os.path.join(profile_path, "keys.txt")
    if xbmcvfs.exists(keys_file):
        try:
            with xbmcvfs.File(keys_file) as f:
                combined_keys.extend([k.strip() for k in f.read().splitlines() if k.strip()])
        except: pass
    all_keys = list(set(combined_keys))
    if not all_keys: all_keys = ["cloud_fallback"]
    if not all_keys:
        show_error_and_open_settings(sub_addon_id, "Nu ai introdus nicio cheie API!")
        return
    langs = ["ro", "en", "es", "fr", "de", "it", "hu", "pt", "ru", "tr", "bg", "el", "pl", "cs", "nl"]
    try: target_lang = langs[_addon.getSettingInt('subs_languages')]
    except: target_lang = "ro"
    _, files = xbmcvfs.listdir(profile_path)
    srt_files = [f for f in files if f.lower().endswith('.srt') and not f.startswith('DeepL-')]
    if not srt_files:
        log("Nu am găsit niciun fișier SRT în: " + profile_path)
        return
    orig_name = srt_files[0]
    sub_path = os.path.join(profile_path, orig_name)
    base_name = orig_name.rsplit('.', 1)[0]
    final_name = "DeepL-{}.{}.srt".format(base_name, target_lang)
    out_path = os.path.join(profile_path, final_name)
    if uploader:
        try:
            auth = uploader.koofr_get_auth()
            remote_url = "https://app.koofr.net/dav/Koofr/Subtitrari/{}/{}".format(uploader.get_folder_grup(), urllib.parse.quote(final_name))
            req_c = urllib.request.Request(remote_url, method='GET', headers={"Authorization": auth})
            with urllib.request.urlopen(req_c, timeout=10) as r:
                if r.getcode() == 200:
                    notify("Cloud", "Găsită în cloud! Descărcăm...", 3000)
                    with xbmcvfs.File(out_path, 'wb') as f_o: f_o.write(r.read())
                    xbmc.Player().setSubtitles(out_path)
                    return
        except: pass
    try:
        with xbmcvfs.File(sub_path) as f:
            content = f.read()
        blocks = re.findall(r'(\d+)\s*\r?\n(\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3})\s*\r?\n([\s\S]*?)(?=\r?\n\r?\n|$)', content)
        if not blocks:
            notify("Eroare", "Format SRT invalid!")
            return
        chars_estimat = sum(len(re.sub(r'<[^>]*>', '', b[2]).strip()) for b in blocks)
        log("Film curent: ~{} caractere estimate".format(chars_estimat))
        blacklist_file = os.path.join(profile_path, "blacklist.json")
        keys_valide = get_sorted_keys(all_keys, blacklist_file, chars_estimat)
        suma_disponibila = sum(k[1] for k in keys_valide) if keys_valide else 0
        if not keys_valide or suma_disponibila < int(chars_estimat * 1.1):
            msg = "FALIMENT CARACTERE!\nFilm: ~{}\nDisponibil: {}\nAdaugă chei noi în setări! sau schimbă Robotu".format(chars_estimat, suma_disponibila)
            show_error_and_open_settings(sub_addon_id, msg)
            return
        notify("DeepL Robot", "Folosim {} surse ({} char)".format(len(keys_valide), suma_disponibila), 4000)
        batches = [blocks[i:i + 50] for i in range(0, len(blocks), 50)]
        final_results = {}
        last_write = 0
        workers = max(1, _addon.getSettingInt('max_workers_count_r4') + 1)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(process_batch_worker, b, target_lang, keys_valide): i for i, b in enumerate(batches)}
            for future in as_completed(futures):
                if not xbmc.Player().isPlaying():
                    break
                idx = futures[future]
                res_srt, _ = future.result()
                if res_srt:
                    with write_lock:
                        final_results[idx] = res_srt
                        if (time.time() - last_write > 3.0) or (len(final_results) == len(batches)):
                            full_srt = "".join([final_results[i] for i in sorted(final_results.keys())])
                            with xbmcvfs.File(out_path, 'w') as f_o:
                                f_o.write(full_srt)
                            if xbmc.Player().isPlaying():
                                xbmc.Player().setSubtitles(out_path)
                            last_write = time.time()
        if len(final_results) == len(batches):
            notify("Succes", "Traducere completă (Multi-Key)!")
            if uploader:
                up_thread = threading.Thread(target=uploader.upload_now, args=(out_path, final_name))
                up_thread.start()
                log("Upload inițiat pentru: " + final_name)
    except Exception as e:
        log("Eroare Critică Runner: " + str(e))
        notify("Eroare", "Vezi log-ul pentru detalii.")