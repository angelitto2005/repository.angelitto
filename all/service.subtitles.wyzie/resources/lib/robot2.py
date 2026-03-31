# -*- coding: utf-8 -*-
import xbmc, xbmcgui, xbmcvfs, xbmcaddon
import os, re, json, urllib.parse, urllib.request, time
from threading import Thread, Lock

LINGVA_INSTANCES = [
    "https://lingva.ml",
    "https://translate.plausibility.cloud",
    "https://lingva.lunar.icu",
    "https://translate.projectsegfau.lt",
    "https://translate.dr460nf1r3.org"
]

def smart_wrap(text, limit=40):
    if not text or '\n' in text or len(text) <= limit:
        return text
    words = text.split(' ')
    mid = len(text) // 2
    curr = 0
    for i, w in enumerate(words):
        curr += len(w) + 1
        if curr >= mid:
            return ' '.join(words[:i+1]).strip() + '\n' + ' '.join(words[i+1:]).strip()
    return text

class PerfectRocket:
    def __init__(self, target_lang):
        self.target_lang = target_lang
        self.results = {}
        self.failed_indices = set()
        self.lock = Lock()
        self.mirror_idx = 0
        self.sep = " @@@ "
        self.br = " [n] "

    def _fetch_raw(self, text_batch):
        # Dacă filmul s-a oprit, nu mai facem cereri la API
        if not xbmc.Player().isPlaying(): return ""
        
        for _ in range(len(LINGVA_INSTANCES) * 2):
            if not xbmc.Player().isPlaying(): break
            with self.lock:
                base_url = LINGVA_INSTANCES[self.mirror_idx]
                self.mirror_idx = (self.mirror_idx + 1) % len(LINGVA_INSTANCES)
            try:
                url = f"{base_url}/api/v1/auto/{self.target_lang}/{urllib.parse.quote(text_batch)}"
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=7) as r:
                    res = json.loads(r.read().decode('utf-8'))
                    return res.get('translation', "")
            except:
                time.sleep(0.3)
        return ""

    def _process_recursive(self, lines, start_offset):
        if not lines or not xbmc.Player().isPlaying(): return []
        batch_text = self.sep.join([l.replace('\n', self.br).strip() for l in lines])
        translated = self._fetch_raw(batch_text)
        parts = [p.strip() for p in translated.split("@@@") if p.strip()]

        if len(parts) == len(lines):
            final = []
            for p in parts:
                clean = p.replace('[n]', '\n').replace('[N]', '\n').replace('<br>', '\n')
                clean = "\n".join([line.strip() for line in clean.split('\n') if line.strip()])
                final.append(smart_wrap(clean))
            return final
        
        if len(lines) > 1 and xbmc.Player().isPlaying():
            mid = len(lines) // 2
            return self._process_recursive(lines[:mid], start_offset) + \
                   self._process_recursive(lines[mid:], start_offset + mid)
        else:
            txt = lines[0] if isinstance(lines, list) else lines
            res = self._fetch_raw(txt.replace('\n', self.br))
            if res:
                return [smart_wrap(res.replace('[n]', '\n'))]
            else:
                with self.lock:
                    self.failed_indices.add(start_offset)
                return [txt]

    def worker(self, start_idx, chunk):
        if not xbmc.Player().isPlaying(): return
        res = self._process_recursive(chunk, start_idx)
        with self.lock:
            for i, line in enumerate(res):
                self.results[start_idx + i] = line

def run_translation(sub_addon_id):
    _addon = xbmcaddon.Addon(sub_addon_id)
    if _addon.getSetting('robot_activat') != 'true': return
    
    langs = ["ro", "en", "es", "fr", "de", "it", "hu", "pt", "ru", "tr", "bg", "el", "pl", "cs", "nl"]
    try: target_lang = langs[_addon.getSettingInt('subs_languages')]
    except: target_lang = "ro"

    profile_path = xbmcvfs.translatePath('special://profile/addon_data/%s/' % sub_addon_id)
    _, files = xbmcvfs.listdir(profile_path)
    srt_files = [f for f in files if f.lower().endswith('.srt') and not f.startswith('robot_tradus')]
    if not srt_files: return
    
    sub_path = os.path.join(profile_path, srt_files[0])
    out_path = os.path.join(profile_path, f"robot_tradus.{target_lang}.srt")

    try:
        start_time = time.time()
        f = xbmcvfs.File(sub_path); content = f.read(); f.close()
        pattern = re.compile(r'(\d+)\r?\n(\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3})\r?\n([\s\S]*?)(?=\r?\n\r?\n|$)')
        blocks = pattern.findall(content)
        original_texts = [re.sub(r'<[^>]*>', '', b[2]).strip() for b in blocks]

        rocket = PerfectRocket(target_lang)

        def sync_player(curr_count):
            if not xbmc.Player().isPlaying(): return
            srt_output = ""
            with rocket.lock:
                for k in range(len(blocks)):
                    idx, timing, _ = blocks[k]
                    t_text = rocket.results.get(k, original_texts[k])
                    srt_output += f"{idx}\n{timing}\n{t_text}\n\n"
            
            f_out = xbmcvfs.File(out_path, 'w'); f_out.write(srt_output); f_out.close()
            xbmc.Player().setSubtitles(out_path)
            elapsed = int(time.time() - start_time)
            xbmcgui.Dialog().notification('Robot Lingva', 'Linii: {}/{}'.format(curr_count, len(original_texts)), xbmcgui.NOTIFICATION_INFO, 1200, False)

        i = 0
        total = len(original_texts)

        # --- 1. START RAPID (Verificăm dacă filmul rulează) ---
        for _ in range(3):
            if not xbmc.Player().isPlaying(): return
            if i < total:
                chunk = original_texts[i:i+20]
                rocket.worker(i, chunk)
                i += len(chunk)
                sync_player(i)

        # --- 2. RESTUL (Verificăm isPlaying în buclă) ---
        batch_size = 20
        while i < total and xbmc.Player().isPlaying():
            threads = []
            for _ in range(8):
                if i >= total or not xbmc.Player().isPlaying(): break
                chunk = original_texts[i : i + batch_size]
                t = Thread(target=rocket.worker, args=(i, chunk))
                threads.append(t); t.start()
                i += len(chunk)
            
            for t in threads: t.join()
            
            if xbmc.Player().isPlaying():
                sync_player(i)
                time.sleep(0.05)

        # Statistici finale (doar dacă filmul mai rulează)
        if xbmc.Player().isPlaying():
            total_time = int(time.time() - start_time)
            speed = round(total / total_time, 1) if total_time > 0 else 0
            traduse = sum(1 for k in range(total) if k not in rocket.failed_indices and rocket.results.get(k) != original_texts[k])
            msg = 'Finalizat: {} linii în {}s ({} l/s)'.format(traduse, total_time, speed)
            xbmcgui.Dialog().notification('Robot Lingva', msg, xbmcgui.NOTIFICATION_INFO, 5000)

    except Exception as e:
        xbmc.log(f"Robot Perfect Error: {str(e)}", xbmc.LOGERROR)
