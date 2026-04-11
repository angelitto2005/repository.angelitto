# -*- coding: utf-8 -*-
import xbmc, xbmcgui, xbmcvfs, xbmcaddon
import os, sys, re, json, urllib.parse, urllib.request, html
import time, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# Import uploader centralizat
try:
    from . import uploader
except:
    try: import uploader
    except: uploader = None

MODEL_PREFERAT = [
    "gemini-flash-lite-latest",    
    "gemini-flash-latest",
    "gemini-3.1-flash-lite-preview",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-3-flash-preview",    
]

# --- MODIFICARE: REGLAJE ECONOMIE ȘI RUPERE RÂNDURI ---
STOP_WORDS = {
    "ok", "okay", "yeah", "yes", "no", "nah", "yep", "yup", "oh", "ah", "wow", 
    "hey", "ha", "haha", "huh", "uh", "um", "mmm", "hmm", "oops", "phew", 
    "shh", "brrr", "sigh", "pant", "gasp", "laugh", "sob", "...", "..", "-", "--"
}

AD_PATTERNS = [
    r"www\.[a-z0-9]+\.[a-z]{2,}", r"https?://[^\s]+", r"subtitles by|translated by",
    r"OpenSubtitles|Subscene", r"support us|donate", r"@[a-z0-9_]+"
]

PAUZA_DUPA_EROARE = 10.0 
keys_lock = Lock()
write_lock = Lock()
keys_in_use = set()

def notify(title, message, icon=xbmcgui.NOTIFICATION_INFO, duration=3000):
    xbmc.executebuiltin('Notification("{}", "{}", "{}", {})'.format(title, message, duration, icon))

# --- FUNCȚIE NOUĂ: SMART SPLIT LA 44 CARACTERE ---
def split_smart_long_line(text, max_chars=44):
    if not text or len(text) <= max_chars or "\n" in text:
        return text
    
    # 1. Dialog secundar
    match_dialog = re.search(r'\s+-\s*([A-ZĂÎȘȚÂ])', text)
    if match_dialog:
        p1, p2 = text[:match_dialog.start()].strip(), text[match_dialog.start():].strip()
        if len(p1) <= max_chars and len(p2) <= max_chars:
            return p1 + "\n" + (p2 if p2.startswith('-') else "- " + p2)

    # 2. Punctuație finală (. ! ?)
    match_punct = re.search(r'([.!?])\s+', text)
    if match_punct:
        p1, p2 = text[:match_punct.start(1)+1].strip(), text[match_punct.start(1)+1:].strip()
        if len(p1) <= max_chars and len(p2) <= max_chars:
            return p1 + "\n" + p2
    
    # 3. Virgulă (cea mai aproape de mijloc)
    if ',' in text:
        mid = len(text) // 2
        commas = [i for i, c in enumerate(text) if c == ',']
        if commas:
            best_comma = min(commas, key=lambda x: abs(x - mid))
            p1, p2 = text[:best_comma+1].strip(), text[best_comma+1:].strip()
            if len(p1) <= max_chars and len(p2) <= max_chars:
                return p1 + "\n" + p2

    # 4. Fallback: Mijloc pe spațiu
    mid = len(text) // 2
    for i in range(0, 25):
        for pos in [mid + i, mid - i]:
            if 0 < pos < len(text) and text[pos] == ' ':
                return text[:pos].strip() + "\n" + text[pos:].strip()
    return text

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
    prompt = ("Translate to {}. STRICTLY maintain the original tone of a movie script. "
              "Do NOT censor profanity, slurs, or vulgar language. "
              "Translate slang and idioms with equivalent local natural expressions. "
              "Return ONLY a JSON object: {{'ID': 'translation'}}. No talk.").format(target_lang, style_instruction)
    
    payload = {
        "contents": [{"parts": [{"text": "{}\n\n{}".format(prompt, json.dumps(texts_dict, ensure_ascii=False))}]}],
        "generationConfig": {
            "temperature": 0.15,
            "response_mime_type": "application/json"
        },
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_CIVIC_INTEGRITY", "threshold": "BLOCK_NONE"},
        ]
    }

    try:
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=15) as r:
            res_data = json.loads(r.read().decode('utf-8'))
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
    if not xbmc.Player().isPlaying(): return None, 0, ""
    
    # --- MODIFICARE: FILTRARE ȘI ECONOMIE ÎNAINTE DE API ---
    to_translate = {}
    skipped_lines = {}

    for b_id, timing, text in batch:
        clean_text = re.sub(r'<[^>]*>', '', text).strip()
        clean_text = re.sub(r'\s+', ' ', clean_text)
        
        # Sărim peste reclame
        if any(re.search(p, clean_text, re.IGNORECASE) for p in AD_PATTERNS):
            skipped_lines[str(b_id)] = ""
            continue
            
        # Sărim peste cuvinte de umplutură (Stop words)
        word_only = re.sub(r'[^\w\s]', '', clean_text).lower().strip()
        if word_only in STOP_WORDS:
            skipped_lines[str(b_id)] = clean_text
            continue

        to_translate[str(b_id)] = clean_text

    if not to_translate:
        # Dacă tot batch-ul a fost filtrat, reconstruim SRT-ul pe loc
        chunk_srt = ""
        for b_id, timing, orig_text in batch:
            val = skipped_lines.get(str(b_id), "")
            chunk_srt += "{}\n{}\n{}\n\n".format(b_id, timing, val)
        return chunk_srt, 1, "Skipped"

    tried_keys_indices = set()
    while len(tried_keys_indices) < len(all_keys):
        if not xbmc.Player().isPlaying(): break
        current_key = None
        k_idx_real = 0
        with keys_lock:
            for i, k in enumerate(all_keys):
                if k not in keys_in_use and i not in tried_keys_indices:
                    current_key = k; keys_in_use.add(k)
                    k_idx_real = i + 1; break
        if not current_key:
            time.sleep(2); continue

        try:
            for model in MODEL_PREFERAT:
                if not xbmc.Player().isPlaying(): return None, 0, ""
                rezultat = translate_gemini(to_translate, target_lang, current_key, model, style_instruction)
                if rezultat:
                    chunk_srt = ""
                    for b_id, timing, orig_text in batch:
                        # Luăm traducerea din API sau din lista de "sărite" sau originalul
                        trad = rezultat.get(str(b_id), skipped_lines.get(str(b_id), orig_text))
                        
                        # --- MODIFICARE: SMART SPLIT + CURĂȚARE ---
                        trad = str(trad).replace('- ', '').strip()
                        trad = split_smart_long_line(trad, max_chars=44)
                        linii = [l.strip().lstrip('- ').strip() for l in trad.splitlines()]
                        final_text = "\n".join(linii)
                        
                        chunk_srt += "{}\n{}\n{}\n\n".format(b_id, timing, final_text)
                    return chunk_srt, k_idx_real, model
            tried_keys_indices.add(k_idx_real - 1)
        finally:
            with keys_lock:
                if current_key in keys_in_use: keys_in_use.remove(current_key)
    return None, 0, ""
def run_translation(sub_addon_id):
    _addon = xbmcaddon.Addon(sub_addon_id)
    if _addon.getSetting('robot_activat') != 'true': return
    
    try: max_workers_setat = _addon.getSettingInt('max_workers_count') + 1
    except: max_workers_setat = 1
    
    # 1. COLECTARE CHEI
    keys_din_setari = [_addon.getSetting('api_key_r3_{}'.format(i)) for i in range(1, 6)]
    all_keys = list(dict.fromkeys([k for k in keys_din_setari if k] + backup_keys))
    
    if not all_keys:
        if xbmcgui.Dialog().yesno("Eroare Gemini", "Lipsă Chei API! Mergi la setări?"): 
            _addon.openSettings()
        return

    # 2. SETĂRI LIMBĂ ȘI CĂI
    langs = ["ro", "en", "es", "fr", "de", "it", "hu", "pt", "ru", "tr", "bg", "el", "pl", "cs", "nl"]
    try: target_lang = langs[_addon.getSettingInt('subs_languages')]
    except: target_lang = "ro"

    profile_path = xbmcvfs.translatePath('special://profile/addon_data/{}/'.format(sub_addon_id))
    _, files = xbmcvfs.listdir(profile_path)
    srt_files = [f for f in files if f.lower().endswith('.srt') and not (f.startswith('Google-') or f.startswith('Gemini-') or f.startswith('Lingva-'))]
    if not srt_files: return

    # FIX: Luăm string-ul corect din listă
    orig_full_name = srt_files[0]
    sub_path = os.path.join(profile_path, orig_full_name)
    base_name = orig_full_name.rsplit('.', 1)[0]
    final_name = "Gemini-{}.{}.srt".format(base_name, target_lang)
    output_path = os.path.join(profile_path, final_name)

    # 3. VERIFICARE CLOUD (Economie jetoane)
    if uploader:
        cale_cloud = uploader.get_folder_grup() 
        auth = uploader.koofr_get_auth()
        remote_url = "https://app.koofr.net/dav/Koofr/Subtitrari/{}/{}".format(cale_cloud, urllib.parse.quote(final_name))
        try:
            req_c = urllib.request.Request(remote_url, method='GET', headers={"Authorization": auth})
            with urllib.request.urlopen(req_c, timeout=10) as r:
                if r.getcode() == 200:
                    notify("Cloud", "Subtitrare găsită! Descărcăm...", duration=2000)
                    with xbmcvfs.File(output_path, 'wb') as f_o: f_o.write(r.read())
                    xbmc.Player().setSubtitles(output_path)
                    return 
        except: pass

    # 4. PROCESARE FIȘIER ȘI TRADUCERE
    try:
        start_time = time.time()
        last_notify_time = 0
        
        with xbmcvfs.File(sub_path) as f:
            content = f.read()
            
        pattern = re.compile(r'(\d+)\r?\n(\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3})\r?\n([\s\S]*?)(?=\r?\n\r?\n|$)')
        blocks = pattern.findall(content)
        
        # Batch-uri de 100 pentru Gemini (e mai eficient cu pachete mari)
        batches = [blocks[i:i + 100] for i in range(0, len(blocks), 100)]
        total_lines = len(blocks)
        completed_lines, final_results = 0, {}
        chei_folosite, modele_folosite = set(), set()
        
        notify("Gemini Robot", "Start: {} linii | Pachete: {}".format(total_lines, len(batches)))

        with ThreadPoolExecutor(max_workers=max_workers_setat) as executor:
            # "Professional localization" + instrucțiunea de stil
            futures = {executor.submit(process_batch_worker, b, target_lang, all_keys, "Professional movie localization, no censorship."): i for i, b in enumerate(batches)}
            
            for future in as_completed(futures):
                if not xbmc.Player().isPlaying(): break
                idx = futures[future]
                res_srt, k_num, model_name = future.result()
                
                if res_srt:
                    with write_lock:
                        final_results[idx] = res_srt
                        completed_lines += len(batches[idx])
                        if k_num > 0: chei_folosite.add(str(k_num))
                        if model_name: modele_folosite.add(model_name)
                        
                        # Salvare progresivă
                        current_srt = "".join([final_results[i] for i in sorted(final_results.keys())])
                        with xbmcvfs.File(output_path, 'w') as f_out: f_out.write(current_srt)
                        
                        if xbmc.Player().isPlaying(): 
                            xbmc.Player().setSubtitles(output_path)
                            
                    t_acum = time.time()
                    if (t_acum - last_notify_time > 15 or completed_lines == total_lines) and xbmc.Player().isPlaying():
                        msg = '{}/{} linii | M:{}'.format(completed_lines, total_lines, model_name)
                        notify('Gemini Progres', msg, duration=2000)
                        last_notify_time = t_acum
                else: 
                    log("Un batch a eșuat complet la traducere.")
                    break

        # FINALIZARE
        if not xbmc.Player().isPlaying(): return
        
        if len(final_results) == len(batches):
            statistici = "Modele: {} | Chei: {}".format(", ".join(modele_folosite), ", ".join(chei_folosite))
            notify("Succes Complet", statistici, duration=5000)
            if uploader:
                threading.Thread(target=uploader.upload_now, args=(output_path, final_name)).start()
        elif completed_lines > 0:
            if not xbmcgui.Dialog().yesno("Incomplet", "Unele linii au eșuat. Păstrezi ce s-a tradus?"):
                xbmcvfs.delete(output_path)

    except Exception as e:
        xbmc.log("Eroare Critică Robot Gemini: " + str(e), xbmc.LOGERROR)
